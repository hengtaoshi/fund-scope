# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

个人基金量化分析平台 (Fund Cockpit) — 管理基金持仓、多因子评分分析、自动定投。  
Flask 单页后端 + 原生 JS 前端，Docker Compose 部署在单台 VPS，前有雷池 WAF + Nginx 反代。

## Key architecture

```
VPS (124.221.92.130)
  雷池 WAF (443) → Nginx (80) → Flask :5000 (Docker)
                                    │
  Gitee Webhook → /api/deploy ──────┤
      cron → .deploy-trigger → docker compose up --build
```

- **Monolithic Flask** — ~60 routes 全部在 `backend/app.py`，按领域拆分为 `fund_data.py` / `fund_analysis.py` / `database.py` / `email_sender.py` / `auth.py`
- **Vanilla JS SPA** — `frontend/js/app.js` 用 `renderPage()` 切换页面，Chart.js 绘制图表
- **JWT auth** — `auth.py` 处理登录/注册/验证码，`@login_required` 装饰器保护 API
- **SQLite** — `database.py` 管理持仓、用户表，数据存 Docker volume `fund_data`
- **数据源** — `akshare` 库获取中国公募基金数据，结果缓存 4 小时

## Common commands

```bash
# 本地开发（跳过登录）
cd backend && FLASK_DEBUG=1 SKIP_AUTH=1 python app.py
# → http://localhost:5000

# Docker 构建启动
docker compose up -d --build

# 查看日志
docker logs -f fund-cockpit-api

# 手动触发部署（在服务器上）
touch /root/fund-cockpit/.deploy-trigger
# cron 每分钟检测，执行 git fetch + reset + docker compose up --build
```

无测试、无 lint、无构建步骤。

## Deployment (CI/CD)

- **Gitee Webhook** — push 到 `master` → Gitee POST `/api/deploy` → Flask 验证 token → `git fetch + reset --hard origin/master` → 写 `.deploy-trigger` 文件
- **宿主机 cron** — 每分钟执行 `/root/fund-cockpit/deploy.sh`，检测到 `.deploy-trigger` 后执行 `docker compose up -d --build`
- **`.env` 文件** — 在服务器 `/root/fund-cockpit/.env`，不存 Git，通过 docker-compose 注入容器

### 部署成功邮件通知

Webhook 执行后自动通过 SMTP 发送结果通知到 `DEPLOY_NOTIFY_EMAIL`。使用 `email_sender.py` 中的 `send_deploy_notification()` 发送，支持成功/失败状态和提交信息。

## Server environment

- **Host:** 124.221.92.130, 项目路径 `/root/fund-cockpit`
- **Gitee:** `gitee.com/hengtaoshi/quantitative-warehouse.git`, PAT 在 `/root/.git-credentials`
- **WAF:** 雷池 SafeLine 社区版，管理面板 `https://124.221.92.130:9443`
- **Domain:** `fund.hengtaoyuan.asia`
- **Container:** `fund-cockpit-api` (Python 3.11-slim, Flask dev server)

## Frontend patterns

- `$(id)` = `document.getElementById(id)`, `qsa(sel)` = `document.querySelectorAll(sel)`
- `api()` helper — 封装 fetch，自动处理 401 跳转登录
- `renderPage(page)` — 用 AbortController 取消上一页的进行中请求，`_renderGeneration` 防竞态
- 颜色: 金色 `#c7883c`，炭黑 `#2c2a26`，暖白 `#faf7f2`
- 中国股市惯例: 红色 = 涨，绿色 = 跌
- `fmtMoney()` / `fmtPct()` / `cls()` 工具函数在 `app.js` 顶部
