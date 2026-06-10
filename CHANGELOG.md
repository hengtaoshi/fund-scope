# 近期改动报告

> 日期：2025-07-14 | 基于仓库最新代码

---

## 一、定投功能（DCA）

### 1.1 数据库

`backend/database.py` — holdings 表新增 3 个字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_invested` | REAL | 累计投入金额（定投模式自动计算） |
| `dca_start_date` | TEXT | 定投开始日期 |
| `dca_amount` | REAL | 每期定投金额 |
| `dca_frequency` | TEXT | 定投频率：daily / weekly / monthly |

### 1.2 后端 API

`backend/app.py` — portfolio 相关接口适配：

- `GET /api/portfolio` 返回新增字段
- `POST /api/portfolio` 接收定投参数
- `PUT /api/portfolio/<id>` 更新定投参数

### 1.3 前端交互

`frontend/js/app.js` — 添加持仓弹窗：

- 新增「买入方式」切换开关：普通买入 / 定投模式
- **普通模式**：填基金代码 + 可用份额 + 成本单价
- **定投模式**：填基金代码 + 每期金额 + 频率 + 开始日期
- 定投模式下自动隐藏份额和单价字段
- 点击确认后，系统自动调用 akshare 获取历史净值，按频率逐期计算累计投入和份额

**定投自动计算逻辑：**

```javascript
// 每天: 取开始日至今所有交易日
// 每周: 每5个交易日取1次
// 每月: 每月取第1个交易日
// 累计投入 = 期数 × 每期金额
// 累计份额 = Σ(每期金额 ÷ 当日净值)
// 平均成本 = 累计投入 ÷ 累计份额
```

### 1.4 前端展示

持仓页和概览页的定投基金显示：

```
易方达蓝筹精选 定投
从 2025-01-10 开始
20元/周
应投 24 期 · 应投入 ¥480       ← 理论值
实际投入 ¥520 · 差额 +¥40      ← 实际 vs 理论
净值 1.5200 → 1.6830 +10.7%   ← 开始日至今基金涨幅
```

### 1.5 修改弹窗

编辑持仓时，定投基金显示定投计划参数（金额/频率/日期），可修改后保存。

---

## 二、本地开发绕过登录

`backend/app.py` 和 `frontend/js/app.js`：

- 后端：`login_required` 装饰器检测 `JWT_SECRET` 环境变量，未设置时自动放行（`user_id=1`）
- 前端：启动时检测 token 不存在则调用 `/api/health` 试探，后端未开启认证则直接进入主界面

**本地开发**：直接访问 http://localhost:5000，无需登录
**服务器部署**：设置 `JWT_SECRET` 环境变量即可开启登录认证

---

## 三、缓存控制

| 位置 | 改动 |
|------|------|
| `frontend/index.html` | 添加 `Cache-Control: no-cache` meta 标签 + JS 引用加版本号 `app.js?v=2` |
| `backend/app.py` | Flask 返回首页时设置 `Cache-Control: no-cache` 响应头 |

---

## 四、其他优化

| 改动 | 说明 |
|------|------|
| 图表十字光标 | Chart.js 插件，悬停显示竖虚线+横虚线+交点 |
| 图表时段切换 | 1月/3月/6月/1年 按钮切换 |
| 基金选择器 | 折线图支持点击切换显示不同基金 |
| 饼图配色 | 动态生成暖色系配色，支持任意数量基金 |
| 定投开始日净值对比 | 从 NAV 数据中找到开始日净值和今日净值对比 |

---

## 五、项目文件结构（当前）

```
fund-platform/
├── backend/
│   ├── app.py                 # Flask 主入口（含 auth 绕过）
│   ├── fund_data.py           # akshare 数据层
│   ├── fund_analysis.py       # 多因子评分 + 技术指标
│   ├── database.py            # SQLite（含定投字段）
│   ├── email_sender.py        # SMTP 邮件
│   ├── auth.py                # JWT 认证
│   ├── config.py              # 配置
│   ├── requirements.txt
│   └── data/                  # 数据库 + 缓存
├── frontend/
│   ├── index.html             # 主页面（禁止缓存）
│   ├── login.html             # 登录页
│   ├── css/style.css          # 样式
│   └── js/app.js              # 前端应用逻辑
├── PLAN.md
├── REVIEW.md
├── FIX-PLAN.md
├── DEV-PROGRESS.md
└── fix_auth.py                # 临时修复脚本（可删除）
```
