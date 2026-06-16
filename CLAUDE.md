# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

个人基金量化分析平台 (Fund Cockpit) — 管理基金持仓、多因子评分分析、AI 诊断、自动定投。  
Flask 单页后端 + 原生 JS 前端，Docker Compose 部署在单台 VPS，前有雷池 WAF + Nginx 反代。

## Architecture

```
VPS (YOUR_SERVER_IP)
  雷池 WAF (443) → Nginx (80) → Flask :5000 (Docker)
                                    │
  Gitee Webhook → /api/deploy ──────┤
      cron → .deploy-trigger → docker compose up --build
```

### Backend (`backend/`)

- **`app.py`** — Flask 主入口，~1200 行，包含约 60 个路由。按功能分区：认证 API、持仓 CRUD、基金分析、AI 对话、穿透分析、部署 Webhook。启动时启动后台调度器 `start_scheduler()`（每日报告 + webhook 去重缓存清理）。
- **`fund_data.py`** — akshare 数据层，所有请求受 `_rate_limit()`（1 秒间隔）控制，结果缓存 4 小时到 `backend/data/cache/`。
- **`fund_analysis.py`** — 纯函数分析引擎：指标计算（年化收益/波动率/夏普/最大回撤）、技术信号（RSI/MACD/布林带/均线）、多因子评分（收益30%+风控25%+性价比20%+技术面15%+稳定性10%）。
- **`database.py`** — SQLite，`holdings` 表含 DCA 字段（`total_invested`, `dca_start_date`, `dca_amount`, `dca_frequency`, `dca_end_date`），`users` 表，`verification_codes` 表。支持逐字段更新（`update_holding` 用 sentinel `_UNSET` 区分不更新 vs 显式 NULL）。
- **`auth.py`** — JWT 签发/验证（HS256，7 天过期），邮箱验证码登录（5 分钟有效，60 秒冷却），IP 限流。
- **`email_sender.py`** — SMTP 邮件：部署通知、每日收益报告、分析报告。
- **`config.py`** — 从环境变量读取配置（SMTP、DeepSeek、缓存、akshare 间隔）。
- **`run.py`** — 本地开发启动脚本，设默认 JWT_SECRET 后启动 Flask dev server。

### Frontend (`frontend/`)

- **`index.html`** — SPA 外壳，加载 Chart.js、Font Awesome、marked.js + DOMPurify（Markdown 渲染）。
- **`js/app.js`** — 全部前端逻辑，~1500 行。`renderPage(page)` 切换页面，AbortController 取消旧请求，`_renderGeneration` 防竞态。
- **`css/style.css`** — 单文件样式。
- **`login.html`** — 独立登录页。

### Data flow

```
akshare (东方财富/雪球) → fund_data.py (缓存4h) → app.py (API) → 前端 Chart.js 图表
                                                        ↘ SQLite (持仓/用户)
                                                        ↘ DeepSeek API (AI 对话)
```

## Common commands

```bash
# 本地开发（跳过登录）
cd backend && FLASK_DEBUG=1 SKIP_AUTH=1 python app.py
# → http://localhost:5000

# 或用 run.py（设默认 JWT_SECRET）
cd backend && python run.py

# Docker 构建启动
docker compose up -d --build

# 查看日志
docker logs -f fund-cockpit-api

# 手动触发部署（在服务器上）
ssh root@YOUR_SERVER_IP "cd /path/to/project && git fetch origin master && git reset --hard origin/master && touch .deploy-trigger"
```

无测试、无 lint。

## Git & Deploy

- **远程仓库:** `https://gitee.com/hengtaoshi/quantitative-warehouse.git`
- **分支:** 所有开发直接在 `master` 分支
- **部署流程:** `git push origin master` → Gitee Webhook POST `/api/deploy` → Flask 验证 token → `git fetch + reset --hard origin/master` → 写 `.deploy-trigger` → cron 检测后 `docker compose up -d --build`
- **禁止直接通过 SFTP/SCP 上传文件到服务器**
- 服务器 `.env` 文件在 `/path/to/project/.env`，**不提交 Git**
- Gitee PAT 存在 `/path/to/.git-credentials`

## Server

- **Host:** YOUR_SERVER_IP, 密码 `YOUR_PASSWORD`
- **Domain:** your-domain.com
- **项目路径:** `/path/to/project`（宿主机），容器内 `/app/backend`（代码）+ `/path/to/project`（挂载）
- **Container:** `fund-cockpit-api` (Python 3.11-slim, Flask dev server)

## Frontend patterns

- `$(id)` = `document.getElementById(id)`, `qsa(sel)` = `document.querySelectorAll(sel)`
- `api(url, opts)` — fetch 封装，自动带 JWT，401 跳转登录，支持 AbortSignal 取消
- `fmtMoney(n)` / `fmtPct(n)` / `cls(val)` — 格式化工具函数，在 `app.js` 顶部
- `esc(str)` — HTML 转义，user 消息用；AI 消息用 `marked.parse()` + `DOMPurify.sanitize()`
- `renderPage(page)` — 路由分发，每个页面一个 `renderXxx(el)` 函数，写入 `$('content')`
- 颜色: 金色 `#c7883c`，炭黑 `#2c2a26`，暖白 `#faf7f2`
- 中国股市惯例: 红色 = 涨，绿色 = 跌
- JS/CSS 版本号 `?v=N` 防缓存，更新 app.js 后务必 +1

## Backend patterns

- `@login_required` 装饰器保护需要登录的路由，`request.current_user` 获取用户信息
- 本地开发设 `SKIP_AUTH=1` 跳过登录校验
- AI 对话在 `/api/ai/chat`，调用 DeepSeek API（`deepseek-chat` 模型），带持仓上下文和系统提示词
- 基金类型来自雪球 `fund_individual_basic_info_xq()`，QDII 类型为 `"QDII-混合"`
- akshare 某些函数（如 `fund_portfolio_holdings_em`）可能因版本更新不可用，所有 akshare 调用都在 try-except 中
- 净值获取用 `ThreadPoolExecutor` 加 20 秒超时防止单个基金卡死

## DCA tracking

持仓的 DCA 定投数据在 `holdings` 表字段中：`total_invested`（累计投入）、`dca_amount`（每期金额）、`dca_frequency`（daily/weekly/monthly）、`dca_start_date/end_date`。前端加载持仓后调用 `calcDcaInfo()` 根据 NAV 记录数计算预期投入。**注意：总投入按实际交易日数计算，不虚增未出净值的日期。**
