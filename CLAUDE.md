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

## Git 仓库

- **远程仓库:** `https://gitee.com/hengtaoshi/quantitative-warehouse.git`
- **分支策略:** 所有开发直接在 `master` 分支进行

## 标准部署流程（必须遵守）

所有代码变更必须经过以下流程，**禁止直接通过 SFTP/SCP 上传文件到服务器**：

1. **本地修改 → 测试**
2. **`git add` / `git commit` / `git push origin master`** 推送到 Gitee
3. **Gitee Webhook 自动触发** → Gitee POST `/api/deploy` → Flask 验证 token → `git fetch + reset --hard origin/master` → 写 `.deploy-trigger` 文件
4. **宿主机 cron 每分钟检测** — 发现 `.deploy-trigger` 后执行 `docker compose up -d --build`
5. 部署成功/失败自动发送邮件通知到 `DEPLOY_NOTIFY_EMAIL`

### 特殊情况处理

- 服务器 `.env` 文件在 `/root/fund-cockpit/.env`，**不提交到 Git**，通过 docker-compose `env_file` 注入容器
- Webhook 密钥 `WEBHOOK_SECRET` 在 `.env` 中配置
- Gitee PAT 存在 `/root/.git-credentials`
- 如需强制服务器从远程拉取最新代码（跳过 webhook）：`ssh root@124.221.92.130 "cd /root/fund-cockpit && git fetch origin master && git reset --hard origin/master && touch .deploy-trigger"`

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
