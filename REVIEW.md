# 基金驾驶舱 — 代码审查报告

> 审查日期：2026-06-03 | 审查范围：全项目（backend + frontend + Docker/Nginx）

---

## 一、总体评价

项目从 Phase 1 的单体 HTML demo 演进为 Flask 后端 + 纯 JS 前端的 SPA 架构，功能覆盖完整。视觉风格统一，前后端分离清晰。但存在若干**安全硬伤**和**数据准确性问题**需优先处理。

---

## 二、问题分级列表

### 🔴 严重（安全 / 数据可信度 / 可被攻击）

---

#### 1. SMTP 授权码明文写入源码

**位置**：`backend/config.py:10`，`docker-compose.yml:22`

```python
SMTP_PASS = os.getenv("SMTP_PASS", "BTnb999GC8eiMtMa")
```

`docker-compose.yml` 中同样的密码明文暴露。此仓库如果推送到公开 GitHub，攻击者可直接使用该凭证登录 163 邮箱发送任意邮件。DEV-PROGRESS.md:217 已自述这是问题，但未修复。

**解决方案**：

- 立即从源码中删除授权码，改为强制从环境变量读取（去除 fallback 默认值）
- 在 `.gitignore` 中添加 `.env`，提供 `.env.example` 模板文件
- 生效后更换 163 邮箱授权码（已泄露的凭证必须作废）

```python
# config.py — 不允许默认值
SMTP_PASS = os.getenv("SMTP_PASS")  # 未设置时直接报错，不 fallback
if not SMTP_PASS:
    raise RuntimeError("SMTP_PASS 环境变量未设置")
```

---

#### 2. Flask debug 模式开启 + 绑定 0.0.0.0

**位置**：`backend/app.py:356`

```python
app.run(host="0.0.0.0", port=port, debug=True)
```

`debug=True` 在生产环境是极度危险的：

- Werkzeug debugger 允许在浏览器中执行任意 Python 代码（PIN 保护可被绕过）
- 每次请求会泄露内存和源码信息
- `host="0.0.0.0"` 将此危险服务暴露给所有网络接口

**解决方案**：

```python
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    print(f"基金驾驶舱后端启动 http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
```

生产环境应使用 gunicorn 或 waitress：

```dockerfile
# Dockerfile CMD 改为
CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "app:app"]
```

---

#### 3. Alpha/Beta 计算完全虚假

**位置**：`backend/fund_analysis.py:99-120`

```python
def _calc_alpha_beta(fund_daily_ret: np.ndarray) -> Dict[str, float]:
    market_ret = np.mean(fund_daily_ret) + np.random.normal(0, 0.01, len(fund_daily_ret))
```

用 `np.random.normal` 随机生成"市场基准收益率"，使得 Alpha 和 Beta 每次计算结果**不同且无意义**。对于一个"量化分析"平台，这从根本上破坏了分析的可信度。用户在不同时间打开同一只基金会看到不同的 Alpha、Beta 值。

**解决方案**：

- 接入真实的沪深300指数数据（akshare 有 `ak.index_zh_a_hist` 等接口）
- 在接入真实数据前，要么不计算 Alpha/Beta，要么明确标注为"暂不可用"

```python
def _calc_alpha_beta(fund_daily_ret, benchmark_code="000300"):
    """从 akshare 获取真实沪深300数据计算 Alpha/Beta"""
    try:
        benchmark_nav = get_index_data(benchmark_code)  # 需要实现
        benchmark_ret = np.diff(benchmark_nav) / benchmark_nav[:-1]
        # 对齐长度
        min_len = min(len(fund_daily_ret), len(benchmark_ret))
        fund_ret = fund_daily_ret[-min_len:]
        market_ret = benchmark_ret[-min_len:]
        # ... 正常计算 cov / beta / alpha
    except Exception:
        return {"alpha": None, "beta": None}  # 标注不可用而非造假
```

---

#### 4. 多处空 except 吞没异常

**位置**：

| 文件           | 行号                           | 代码             |
| ------------ | ---------------------------- | -------------- |
| `app.py:41`  | `except: pass`               | 清除缓存失败静默忽略     |
| `app.js:288` | `catch (e) { /* ignore */ }` | Chart 销毁失败静默忽略 |
| `app.js:316` | `catch (e) { /* ignore */ }` | Chart 销毁失败静默忽略 |

裸 `except: pass` 会吞没包括 `KeyboardInterrupt`、`MemoryError` 在内的所有异常，是最危险的反模式。

**解决方案**：

```python
# app.py:41
except OSError as e:
    print(f"[WARN] 清除缓存文件失败 {fp}: {e}")
```

```javascript
// app.js
try { chartInstances.line.destroy(); } catch (e) { console.warn('Chart destroy failed:', e); }
```

---

#### 5. 前端 innerHTML 拼接无转义 — XSS 风险

**位置**：`frontend/js/app.js` 多处（renderDashboard、renderPortfolio、renderPredict、searchFund 等）

```javascript
el.innerHTML = `...<strong>${x.name}</strong>...`;
```

所有 HTML 通过字符串模板拼接，数据来自 akshare API 的基金名称、经理姓名等字段。虽然 akshare 数据源可信度较高，但：

- 如果 akshare 返回的数据被投毒（如基金名称包含 `<script>` 标签）
- 如果未来接入用户自定义备注等字段
- 这些注入点就会成为 XSS 攻击向量

**解决方案**：添加一个简单的 HTML 转义函数：

```javascript
function esc(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
// 对所有用户可控数据使用 esc()
el.innerHTML = `...<strong>${esc(x.name)}</strong>...`;
```

---

### 🟠 高优先级（健壮性 / 数据一致性）

---

#### 6. 同一段分析逻辑重复 4 次

**位置**：`backend/app.py`

| 函数                     | 行号             |
| ---------------------- | -------------- |
| `_get_analysis()`      | 86-104         |
| `portfolio_analysis()` | 148-183        |
| `api_send_report()`    | 272-319        |
| 前端 `renderPredict()`   | app.js:640-693 |

同一段 "获取净值 → 计算指标 → 计算信号 → 计算评分" 逻辑在 4 处重复实现，未来修改评分权重或分析逻辑时必须同步改动 4 处。

**解决方案**：后端已有 `_get_analysis()` 辅助函数，`portfolio_analysis()` 和 `api_send_report()` 应复用该函数而非重新实现。

```python
@app.route("/api/portfolio/analysis")
def portfolio_analysis():
    holdings = get_all_holdings()
    scores = []
    for h in holdings:
        result, _ = _get_analysis(h["code"])  # 复用已有函数
        if result:
            scores.append({...})
```

---

#### 7. 重复 import 和模块级函数调用

**位置**：`backend/app.py:151,279`

```python
# line 13 (module top)
from database import init_db, add_holding, get_all_holdings, ...

# line 151 (inside portfolio_analysis())
from database import get_all_holdings

# line 279 (inside api_send_report())
from database import get_all_holdings
```

模块顶部已 import，函数内重复 import 不仅是冗余代码，还表明开发者不清楚已有哪些导入。

**解决方案**：删除函数内的重复 import。

---

#### 8. `fund_manager_em()` 全量拉取性能问题

**位置**：`backend/fund_data.py:126`

```python
all_managers = ak.fund_manager_em()  # 拉取全市场所有基金经理数据
df = all_managers[all_managers["现任基金代码"] == code]
```

`ak.fund_manager_em()` 返回的是**全市场所有基金经理**的数据（可能成千上万条），仅为了查询一只基金的经理信息而拉取全部数据，每次调用耗时数秒且浪费带宽。

**解决方案**：

- 对该接口也启用缓存（目前仅 nav/info/manager 有缓存，但全量拉取的瓶颈在 akshare 返回数据本身）
- 或使用基金基本信息中的 manager 字段（`get_fund_info` 已包含该信息）

---

#### 9. `search_fund()` 每次都下载全量基金列表

**位置**：`backend/fund_data.py:164`

```python
df = ak.fund_name_em()  # 全市场 10000+ 只基金
```

每次搜索都下载一次完整的基金列表（数据量大且不变化频繁），严重浪费带宽和时间。

**解决方案**：对该数据增加缓存（如 24 小时有效期），或首次启动时预加载到内存。

---

#### 10. 前端无请求取消/去重机制

**位置**：`frontend/js/app.js`

用户在分析页面快速切换基金代码时，会连续发起多个 API 请求。如果前一个请求响应慢于后一个，旧请求的响应会覆盖新请求的结果（race condition）。

**解决方案**：使用 AbortController 取消前一个未完成的请求。

```javascript
let _searchAborter = null;
async function searchFund() {
    if (_searchAborter) _searchAborter.abort();
    _searchAborter = new AbortController();
    const res = await fetch(url, { signal: _searchAborter.signal });
}
```

---

#### 11. 排行榜数据取反了方向

**位置**：`frontend/js/app.js:521-522`

```javascript
const latest = nav.data[0];
const prev = nav.data[1] || latest;
```

净值数据按日期降序排列，`data[0]` 是最新日期。但"前一日净值"取 `data[1]` 仅在数据为降序时正确。如果 akshare 返回升序数据，涨跌幅计算会完全错误。

**解决方案**：显示排序，不依赖隐式顺序。

```javascript
const sorted = [...nav.data].sort((a, b) => b.日期.localeCompare(a.日期));
const latest = sorted[0];
const prev = sorted[1] || latest;
```

---

#### 12. 前后端超时和错误处理不统一

**位置**：`frontend/js/app.js:65-75`

```javascript
async function api(url, opts = {}) {
    try {
        const res = await fetch(API + url, {...});
        return await res.json();
    } catch (e) {
        showToast('网络错误: ' + e.message);
        return null;
    }
}
```

该函数在 HTTP 4xx/5xx 时不会进入 catch（`fetch` 只在网络错误时 reject），但 `res.json()` 也不会报错——调用方收到的是错误 JSON，而调用方又常常不检查 `null`。

**解决方案**：

```javascript
async function api(url, opts = {}) {
    try {
        const res = await fetch(API + url, {
            headers: { 'Content-Type': 'application/json', ...opts.headers },
            ...opts
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || `请求失败 (${res.status})`);
            return null;
        }
        return data;
    } catch (e) {
        showToast('网络错误: ' + e.message);
        return null;
    }
}
```

---

### 🟡 中等优先级（可维护性 / 架构）

---

#### 13. `dict | None` 语法要求 Python 3.10+

**位置**：`backend/database.py:62`

```python
def get_holding(holding_id: int) -> dict | None:
```

`X | None` 联合类型语法是 Python 3.10 引入的。`requirements.txt` 和文档均未声明最低 Python 版本要求。如果在 Python 3.9 环境运行会抛出 `TypeError`。

**解决方案**：在 `requirements.txt` 或 README 中声明 `python_requires>=3.10`，或改为 `Optional[dict]`。

---

#### 14. `database.py` 每次操作都创建/关闭连接

**位置**：`backend/database.py:14-38`

每个 CRUD 操作都独立执行 `sqlite3.connect()` + `conn.close()`。SQLite 在 WAL 模式下这个开销不大，但缺少连接池或上下文管理器，导致：

- 文件描述符频繁打开/关闭
- 无法在同一事务中执行多个操作

**解决方案**：使用 context manager：

```python
from contextlib import contextmanager

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

---

#### 15. 前端全局状态散落在 `window` 对象上

**位置**：`frontend/js/app.js`

| 变量                             | 说明            |
| ------------------------------ | ------------- |
| `window._holdingsList`         | 持仓列表缓存        |
| `window._detailNavData`        | 分析页净值数据       |
| `window._emailAddr`            | 邮箱地址持久化       |
| `chartInstances`               | 全局 Chart 实例字典 |
| `_lastReportTime`              | 发送冷却计时        |
| `selectedFund`                 | 当前选中基金        |
| `chartPeriod` / `detailPeriod` | 图表周期          |

没有任何封装，全部散落在全局作用域。随着功能增加，命名冲突和状态不一致的风险急剧上升。

**解决方案**：用一个简单的 app state 对象集中管理：

```javascript
const AppState = {
    holdings: [],
    detailNavData: null,
    email: '',
    charts: {},
    lastReportTime: 0,
    selectedFund: '',
    chartPeriod: '1y',
    detailPeriod: '1y',
};
```

---

#### 16. `init_db()` 在模块导入时执行

**位置**：`backend/app.py:22`

```python
init_db()
```

在 `import app` 时就会执行数据库初始化。这会导致：

- 单元测试 import 该模块时副作用触发
- 仅 import 某个函数（如用于文档生成）也会触发 DB 操作

**解决方案**：移到 `if __name__ == "__main__":` 块中，或使用 Flask 的 `before_first_request` 钩子。

---

#### 17. 使用 `print()` 而非 logging 模块

**位置**：全部后端文件

所有错误信息使用 `print()` 输出，没有日志级别、时间戳、来源标识。生产环境排查问题困难。

**解决方案**：

```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)
```

---

#### 18. Docker 架构问题

**位置**：`docker-compose.yml` + `nginx.conf`

- `nginx.conf:12` 中 `proxy_pass http://flask:5000` 引用了服务名 `flask`，但 docker-compose 中没有定义 networks，默认网络下可以解析，但不够明确
- Dockerfile 中 `CMD ["python", "app.py"]` 直接使用 Flask 开发服务器，生产环境不应使用
- 没有 healthcheck
- `docker-compose.yml` ports 映射为 `127.0.0.1:5000:5000`，但 nginx.conf 中是通过 Docker 网络访问 `flask:5000`，说明 Nginx 在宿主机上，架构不清晰

**解决方案**：明确架构 — 要么 Nginx 也在容器内（添加 nginx 服务到 docker-compose），要么 Nginx 在宿主机上（ports 绑定 127.0.0.1 是正确的）。当前的混合状态建议统一到 docker-compose 内。

---

### 🟢 低优先级（改进建议）

---

#### 19. CSS 文件未审查

`frontend/css/style.css` 未在审查范围内，但从 HTML 中大量内联 `style` 属性来看，CSS 可能需要整理。

#### 20. `requirements.txt` 版本约束过宽

```txt
flask>=3.0
akshare>=1.14
pandas>=2.0
numpy>=1.24
```

没有上限约束，未来主版本更新可能引入 breaking changes。建议使用 `requirements.in` + `pip-compile` 或锁定具体版本。

#### 21. 无前端构建/打包步骤

Chart.js 和 FontAwesome 的 JS/CSS/字体文件直接提交到仓库（`chart.umd.min.js`、`fontawesome.min.css`、`webfonts/`），导致仓库体积膨胀。建议使用 CDN 或 npm + bundler。

#### 22. `.dockerignore` 中遗漏文件

`backend/data/` 目录下的 `portfolio.db` 和缓存文件不应该被复制到镜像中（通过 volume 挂载）。应在 `.dockerignore` 中添加 `backend/data/`。

#### 23. 无测试

项目中完全没有任何自动化测试。对于一个涉及金融计算的平台，至少应对 `fund_analysis.py` 中的指标计算函数编写单元测试。

---

## 三、修复优先级总览

```
🔴 立即修复（安全和数据可信度）：
  ├─ 1. SMTP 授权码从源码删除 + 更换已泄露凭证
  ├─ 2. Flask debug=False，生产用 waitress/gunicorn
  ├─ 3. Alpha/Beta 移除随机数，标注"暂不可用"或接入真实数据
  ├─ 4. 所有裸 except: pass 改为具体异常类型 + 日志
  └─ 5. 前端 innerHTML 拼接增加 HTML 转义

🟠 尽快修复（健壮性）：
  ├─ 6. 消除 4 处重复的分析逻辑
  ├─ 7. 删除函数内重复 import
  ├─ 8. fund_manager_em 增加缓存或改用轻量接口
  ├─ 9. search_fund 增加全量列表缓存
  ├─ 10. 前端请求增加 AbortController 去重
  └─ 11. 净值数据显式排序而非依赖隐式顺序

🟡 逐步改进（架构）：
  ├─ 13-17. 类型注解兼容性、数据库连接管理、日志系统
  └─ 18. Docker 架构明确化

🟢 远期优化（工程化）：
  └─ 20-23. 依赖锁定、测试覆盖、构建流程
```

---

## 四、登录/注册系统 — 安全审查

> 审查范围：`backend/auth.py`、`backend/app.py`(auth routes)、`backend/database.py`(user tables)、`frontend/login.html`、`frontend/js/app.js`(token 管理)

---

### 🔴 严重漏洞

---

#### A1. JWT 密钥硬编码 + 可预测

**位置**：`backend/auth.py:22`

```python
JWT_SECRET = os.getenv("JWT_SECRET", "fund-cockpit-jwt-secret-change-in-production")
```

硬编码的 fallback 密钥是一个**字典词**，任何看到源码的人都能伪造任意用户的 JWT token。如果部署时忘记设置环境变量，攻击者可以：
- 伪造任意 user_id 的 token，冒充其他用户
- 修改 token 中的 email 字段
- 签发永不超期的 token（手动构造 payload 绕过 `exp`）

**解决方案**：
```python
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET 环境变量必须设置（生产环境使用 256-bit 随机密钥）")
# 生成密钥: python -c "import secrets; print(secrets.token_hex(32))"
```

---

#### A2. JWT Token 存储在 localStorage — XSS 即失窃

**位置**：`frontend/login.html:151`、`frontend/js/app.js:66`

```javascript
localStorage.setItem('fund_token', token);
localStorage.getItem('fund_token');
```

localStorage 中的任何数据都可被同源 JavaScript 读取。结合审查报告中已指出的 **innerHTML XSS 风险 (#5)**，攻击链成立：

```
基金名称注入恶意脚本 → 页面渲染 innerHTML → 脚本执行 → 
读取 localStorage['fund_token'] → 发送到攻击者服务器 → 账户被劫持
```

**解决方案**：
- token 应存储在 **httpOnly cookie** 中（服务端 `Set-Cookie`），JavaScript 完全无法访问
- 后端改为：登录成功时 `response.set_cookie("token", jwt_token, httponly=True, secure=True, samesite="Strict", max_age=604800)`
- 前端不需要手动管理 token，浏览器自动携带 cookie
- `login_required` 装饰器从 `request.cookies.get("token")` 读取而非 Authorization header

---

#### A3. 错误消息区分"用户不存在"与"密码错误" — 邮箱枚举

**位置**：`backend/app.py:126-130`

```python
user = get_user_by_email(email)
if not user:
    return jsonify({"error": "邮箱未注册"}), 404    # ← 区分了！

if not verify_password(password, user["password_hash"]):
    return jsonify({"error": "密码错误"}), 401       # ← 区分了！
```

攻击者可以批量探测邮箱是否已注册。对于一个投资/金融类平台，知道"谁在用"本身就是信息泄露。

**解决方案**：统一错误消息为"邮箱或密码错误"（无论用户是否存在）：

```python
user = get_user_by_email(email)
if not user or not verify_password(password, user["password_hash"]):
    return jsonify({"error": "邮箱或密码错误"}), 401
```

---

#### A4. 验证码生成使用非密码学安全的随机数

**位置**：`backend/auth.py:71`

```python
def generate_code() -> str:
    return str(random.randint(100000, 999999))
```

Python `random` 模块使用 Mersenne Twister 伪随机数生成器，**不具有密码学安全性**。状态可预测的攻击者可以在观察到少量输出后预测后续验证码。

**解决方案**：
```python
import secrets
def generate_code() -> str:
    return str(secrets.randbelow(900000) + 100000)
```

---

#### A5. 无任何登录频率限制 — 可暴力破解

**位置**：`backend/app.py:115-133`（`api_login`）、`backend/app.py:83-112`（`api_register`）

当前没有任何限流机制：
- 登录接口可被无限次暴力破解密码（验证码（A4 问题）或密码本身）
- 注册接口可被恶意创建大量账号
- `/api/auth/send-code` 虽然有 60 秒冷却，但只检查同一个邮箱，攻击者可以用不同邮箱轮换发送，消耗 SMTP 配额

**解决方案**：
- 登录接口：同一 IP 5 次失败后锁定 15 分钟（最简单：内存 dict + IP 键）
- 注册接口：同一 IP 每小时最多注册 3 个账号
- 发送验证码：同一 IP 每小时最多发送 10 条

```python
from collections import defaultdict
from datetime import datetime

_login_attempts = defaultdict(list)  # {ip: [timestamp, ...]}

def check_rate_limit(ip: str, max_attempts: int, window_seconds: int) -> bool:
    now = datetime.now()
    attempts = [t for t in _login_attempts[ip] 
                if (now - t).seconds < window_seconds]
    _login_attempts[ip] = attempts
    if len(attempts) >= max_attempts:
        return False
    _login_attempts[ip].append(now)
    return True
```

---

#### A6. 部分 API 端点未受保护

**位置**：`backend/app.py`

以下端点**未**加 `@login_required`，未登录也可访问：

| 端点 | 风险 |
|------|------|
| `/api/health` | 低（健康检查可公开） |
| `/api/clear-cache` | **中** — 未登录用户可清空所有缓存，影响正常用户体验 |
| `/api/fund/*` | **中** — 未登录用户可查询基金数据、消耗 akshare API 配额 |
| `/api/analysis/*` | **中** — 同上，且计算消耗 CPU |
| `/api/test-email` | **中** — 未登录用户可触发 SMTP 连接测试 |

**解决方案**：根据业务需要决定哪些端点公开。至少 `/api/clear-cache` 和 `/api/test-email` 应该加 `@login_required`。如果 `/api/fund/*` 需要公开（用于未登录探索），则至少加 IP 限流。

---

### 🟠 高危问题

---

#### A7. JWT 使用已弃用的 `datetime.utcnow()`

**位置**：`backend/auth.py:52-53`

```python
"iat": datetime.utcnow(),
"exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
```

`datetime.utcnow()` 在 Python 3.12+ 已弃用，返回的是 naive datetime（无时区信息）。`PyJWT` 在处理 naive datetime 时行为不明确，可能导致时区相关的 token 过期问题。

**解决方案**：
```python
from datetime import datetime, timedelta, timezone
"iat": datetime.now(timezone.utc),
"exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
```

---

#### A8. 无账号锁定机制

连续多次输错密码后，账号不会被临时锁定。结合 A1（弱 JWT 密钥）和 A5（无限速），暴力破解门槛极低。

**解决方案**：在 `users` 表增加 `failed_attempts INTEGER DEFAULT 0` 和 `locked_until TEXT` 字段，登录失败递增，成功清零，超过 5 次锁定 15 分钟。

---

#### A9. 密码强度要求过弱

**位置**：`backend/app.py:95`

```python
if len(password) < 6:
    return jsonify({"error": "密码至少 6 位"}), 400
```

仅检查长度 ≥ 6，无其他限制。"123456"、"111111" 等常见弱密码完全可以通过。对涉及金融数据的平台来说，密码强度应该更高。

**解决方案**：
```python
if len(password) < 8:
    return jsonify({"error": "密码至少 8 位"}), 400
if not re.search(r'[A-Z]', password) and not re.search(r'[a-z]', password):
    return jsonify({"error": "密码需包含字母"}), 400
if not re.search(r'\d', password):
    return jsonify({"error": "密码需包含数字"}), 400
```

---

#### A10. `clean_expired_codes()` 定义了但从未被调用

**位置**：`backend/database.py:193-201`

```python
def clean_expired_codes(hours: int = 1):
    ...
```

该清理函数存在但没有任何地方调用它。验证码表（`verification_codes`）会无限增长。

**解决方案**：每次发送验证码时调用一次，或在 `init_db()` 中用简单的定时清理。

---

#### A11. SMTP 发送无超时和连接关闭保证

**位置**：`backend/auth.py:74-89`

```python
server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
server.login(SMTP_USER, SMTP_PASS)
server.sendmail(EMAIL_FROM, [to_email], msg.as_string())
server.quit()
```

如果 `sendmail` 抛出异常，`quit()` 不会被执行，SMTP 连接泄漏。

**解决方案**：
```python
server = None
try:
    server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10)
    server.login(SMTP_USER, SMTP_PASS)
    server.sendmail(EMAIL_FROM, [to_email], msg.as_string())
    return True
except Exception as e:
    print(f"[auth] 邮件发送失败: {e}")
    return False
finally:
    if server:
        try: server.quit()
        except: pass
```

---

### 🟡 中等问题

---

#### A12. HTTP 明文传输 JWT

**位置**：`backend/app.py:469` + `nginx.conf`

```python
app.run(host="0.0.0.0", port=port, debug=True)
```

全站 HTTP，JWT token 在网络上明文传输。同局域网攻击者可嗅探流量获取 token。

**解决方案**：生产环境配置 HTTPS（Let's Encrypt + nginx SSL termination）。

---

#### A13. JWT 无 token 刷新机制

**位置**：`backend/auth.py:55` — 固定 7 天过期，无 refresh token

token 过期后用户必须重新登录。对于 5 分钟自动刷新数据的仪表盘应用，用户可能在使用中突然被登出。

**解决方案**：至少将 token 有效期延长到 30 天，或增加 `/api/auth/refresh` 端点。

---

#### A14. JWT payload 包含 email 但不校验 user 是否存在

**位置**：`backend/app.py:59-64`

```python
payload = verify_jwt(token)
if not payload:
    return jsonify({"error": "登录已过期"}), 401
request.current_user = payload  # 直接信任 token payload
```

如果用户被删除后 token 仍然有效，该 token 可以继续访问所有功能。

**解决方案**：在 `login_required` 中验证 `payload["user_id"]` 对应的用户是否仍然存在。

---

#### A15. `config.py` 中 SMTP 凭证默认为空字符串，静默失败

**位置**：`backend/config.py:9-11`

```python
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
```

未配置 SMTP 时，注册和发送报告功能会静默失败（返回"验证码发送失败"），用户不知道为什么。

**解决方案**：启动时检查 SMTP 配置，打印明确警告：
```python
if not SMTP_USER or not SMTP_PASS:
    print("[WARN] SMTP 未配置，邮件功能将不可用。设置 SMTP_USER / SMTP_PASS 环境变量。")
```

---

#### A16. docker-compose.yml 仍包含旧 SMTP 凭证和 JWT 配置缺失

**位置**：`docker-compose.yml:22-23`

docker-compose 中没有 `JWT_SECRET` 环境变量，启动后会使用危险的硬编码 fallback。同时 SMTP 凭证仍为占位值。

---

### 🟢 低优先级

---

#### A17. 前端登录页没有请求超时

**位置**：`frontend/login.html:164-192` (fetch 调用)

网络异常时，用户可能长时间等待而没有反馈。

#### A18. 验证码倒计时在前端实现，可被绕过

**位置**：`frontend/login.html:173-182`

60 秒倒计时纯粹是前端 UI 限制，攻击者直接调 API 即可绕过。后端虽有 `send_verification_code` 中的冷却检查，但前端显示"60s 重新发送"给了用户错误的安全感。

#### A19. 无"忘记密码"功能

用户表只有 email 和 password_hash，无密码重置流程。

#### A20. email_sender.py 中的 SMTP 代码与 auth.py 中的重复

**位置**：`backend/auth.py:74-89` vs `backend/email_sender.py:112-120`

两处都有 SMTP 发送逻辑，应该统一到一个模块。

---

## 五、认证系统漏洞修复优先级总览

```
🔴 立即修复：
  ├─ A1. JWT_SECRET 移除硬编码 fallback，强制环境变量
  ├─ A2. Token 从 localStorage 改为 httpOnly cookie
  ├─ A3. 统一登录错误消息，消除邮箱枚举
  ├─ A4. 验证码从 random 改为 secrets 模块
  ├─ A5. 增加登录/注册/发送验证码的 IP 限流
  └─ A6. 未受保护的端点加上 @login_required

🟠 尽快修复：
  ├─ A8.  增加账号锁定机制
  ├─ A9.  强化密码复杂度要求
  ├─ A11. SMTP 连接加 try/finally
  └─ A14. login_required 中验证用户是否存在

🟡 逐步改进：
  ├─ A7.  替换 datetime.utcnow() 为 timezone-aware
  ├─ A10. 定期清理过期验证码
  ├─ A12. 生产环境配置 HTTPS
  ├─ A13. Token 刷新机制
  ├─ A15. SMTP 未配置时打印明确警告
  └─ A16. docker-compose.yml 补充 JWT_SECRET

🟢 远期优化：
  └─ A17-20. 密码重置流程、代码去重、前端超时等
```

---

*本报告由代码审查生成。投资有风险，代码亦有风险，请审慎对待每一项建议。*
