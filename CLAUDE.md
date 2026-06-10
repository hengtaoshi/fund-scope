# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

个人基金量化分析平台 — a personal fund portfolio analysis SPA. Flask backend serving a vanilla-JS frontend, deployed via Docker Compose on a single VPS behind Safeline WAF + Nginx reverse proxy. Data source is akshare (Chinese open-fund data).

## Common commands

```bash
# Local development (SKIP_AUTH bypasses login)
cd backend && FLASK_DEBUG=1 SKIP_AUTH=1 python app.py
# → http://localhost:5000

# Docker build + run
docker compose up -d --build

# View logs
docker logs -f fund-cockpit-api

# Deploy manually (on server, after git push)
touch /root/fund-cockpit/.deploy-trigger
# Cron picks it up within 1 minute and runs git fetch + reset + docker compose up --build
```

No linting, testing, or build steps exist in this project.

## Architecture

```
Browser                     Server (124.221.92.130)
  │                         │
  ├─ fund.hengtaoyuan.asia ─┤─ Safeline WAF → Nginx → fund-cockpit-api:5000 (Docker)
  │                         │                │
  │                         │   /api/deploy ← Gitee Webhook (push → auto deploy)
  │                         │
  └─ SPA (index.html)       └─ Flask app.py (all routes in single file)
       js/app.js                ├─ /api/health, /api/auth/*, /api/deploy (no auth)
       css/style.css            ├─ /api/portfolio, /api/fund/*, /api/analysis/* (JWT)
       login.html               ├─ /api/send-report, /api/clear-cache
                                ├─ fund_data.py — akshare wrapper
                                ├─ fund_analysis.py — sharpe/drawdown/RSI/MACD/scoring
                                ├─ database.py — SQLite (holdings, users)
                                ├─ email_sender.py — SMTP via SendGrid
                                ├─ auth.py — JWT + email verification codes
                                └─ config.py — env-backed settings
```

**Key architectural decisions:**

- **Monolithic Flask app** — all ~60 routes in a single `app.py`. Domain modules (`fund_data.py`, `fund_analysis.py`, `database.py`, etc.) are imported, not separate services.
- **CI/CD via Gitee Webhook** — Push to `master` → Gitee POSTs to `/api/deploy` → Flask writes `.deploy-trigger` file → host cron (`* * * * * /root/fund-cockpit/deploy.sh`) runs git fetch + reset + `docker compose up --build`. The webhook handler does NOT run docker compose itself (container cannot rebuild itself — the subprocess dies when compose stops the container).
- **Docker mounts host binaries** — `docker-compose.yml` mounts `/usr/bin/docker:/usr/local/bin/docker:ro` and compose CLI plugins so the container can issue `docker compose` commands through the host's socket without installing Docker inside the image.
- **No frontend framework** — vanilla JS SPA. Page switching is `content.innerHTML = html` with async data fetching. No router, no state management library, no URL hash changes.

## Frontend patterns

**Page rendering** (`js/app.js`):
- `renderPage(page)` dispatches to `renderDashboard`, `renderPortfolio`, etc. Each fetches data via `api()`, builds an HTML string, writes to `el.innerHTML`, then sets up Chart.js instances in a `setTimeout`.
- **Race condition fix (v4):** `renderPage` uses an `AbortController` to cancel in-flight fetches from the previous page when navigation changes. A `_renderGeneration` counter double-checks that a stale render never writes to `$('content')`. The `api()` helper attaches the abort signal to every `fetch()` and re-throws `AbortError` so it propagates to `renderPage`'s try/catch.
- `api()` catches general network errors and shows a toast. On 401, it clears the token and redirects to `/login`. AbortErrors are re-thrown, not toasted.
- `renderLineChart` (called from `switchFund`/`setChartPeriod` outside `renderPage`'s try/catch) has its own AbortError catch to avoid unhandled rejections.

**Navigation**: sidebar `.nav-item` click → `renderPage(page)`. Nav active state is set synchronously (before async render), so it always reflects the last click. The content area is the async part that had the race condition.

**Auth**: localStorage `fund_token`. Dev mode: `SKIP_AUTH=1` skips JWT entirely. Production: `/login` page with email verification code + password.

**Conventions:**
- `$(id)` = `document.getElementById(id)`, `qsa(sel)` = `document.querySelectorAll(sel)`
- `fmtMoney(n)` → `¥1,234`, `fmtPct(n)` → `+12.50%`, `cls(val)` → `text-up`/`text-down`
- Color scheme: amber gold `#c7883c`, charcoal `#2c2a26`, warm white `#faf7f2`
- Chinese market convention: red = up (涨), green = down (跌) — opposite of Western

## Server environment

- **Host:** 124.221.92.130 (root), project at `/root/fund-cockpit`
- **Gitee:** `https://gitee.com/hengtaoshi/quantitative-warehouse.git`, PAT stored in `/root/.git-credentials`
- **Webhook secret:** `rn4xpL81ScLlPemv8h0KbDnznxQy1uHb` (in `.env` as `WEBHOOK_SECRET`)
- **WAF:** Safeline (雷石) at port 80/443, routes to `fund-cockpit-api:5000`
- **Cron deploy script:** `/root/fund-cockpit/deploy.sh` — checks for `.deploy-trigger`, runs `git fetch + reset --hard + docker compose up -d --build`
- **Docker images use Chinese mirrors:** USTC for apt, Tsinghua for pip (defined in Dockerfile)

## Git workflow

- Branch: `master` only
- Push → Gitee webhook → auto deploy (within ~1 minute)
- Gitee webhook URL: `https://fund.hengtaoyuan.asia/api/deploy`
