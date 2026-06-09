<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/flask-3.0+-lightgrey?style=flat-square&logo=flask" alt="Flask">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square" alt="PRs Welcome">
</p>

<h1 align="center">Fund Scope · 基金驾驶舱</h1>

<p align="center">
  个人基金量化分析平台 — 管理持仓、多因子评分、智能定投、AI 问答<br>
  数据驱动决策，让每一笔投资都有据可依。
</p>

<p align="center">
  <a href="#features">功能</a> ·
  <a href="#quick-start">快速开始</a> ·
  <a href="#configuration">配置</a> ·
  <a href="#development">开发</a> ·
  <a href="#deployment">部署</a>
</p>

---

## Features

<table>
  <tr>
    <td width="50%">
      <h3>📊 行情看板</h3>
      <ul>
        <li>总资产、累计收益、日收益一目了然</li>
        <li>收益曲线 + 盈亏分布 Chart.js 可视化</li>
        <li>昨日收益对比，追踪每日波动</li>
      </ul>
    </td>
    <td width="50%">
      <h3>📋 智能持仓管理</h3>
      <ul>
        <li>添加/编辑/删除基金持仓</li>
        <li>自动同步最新净值和收益</li>
        <li>组合穿透分析，了解底层资产分布</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td>
      <h3>🎯 多因子评分</h3>
      <ul>
        <li>基于多维度指标（收益率、波动率、夏普比率等）自动评分</li>
        <li>五星评级 + 买卖持有信号</li>
        <li>辅助基金筛选，快速定位优质基金</li>
      </ul>
    </td>
    <td>
      <h3>🤖 AI 问答</h3>
      <ul>
        <li>接入 DeepSeek API，智能分析基金</li>
        <li>预计算专业指标（年化收益率、最大回撤、Alpha/Beta等）</li>
        <li>结构化的分析框架，辅助投资决策</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td>
      <h3>📅 智能定投规划</h3>
      <ul>
        <li>按日/周/月频率自动计算定投期数</li>
        <li>基于实际净值交易日精准计数</li>
        <li>已投金额自动累加，支持终止/恢复</li>
      </ul>
    </td>
    <td>
      <h3>🔍 基金筛选</h3>
      <ul>
        <li>按类型、主题、收益率等多条件组合筛选</li>
        <li>中国公募基金全市场覆盖</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td>
      <h3>📧 每日收益报告</h3>
      <ul>
        <li>定时邮件推送每日持仓收益</li>
        <li>支持自定义推送时间和邮箱</li>
      </ul>
    </td>
    <td>
      <h3>🔐 用户系统</h3>
      <ul>
        <li>JWT 认证，注册/登录/验证码</li>
        <li>邮箱验证，保障账户安全</li>
      </ul>
    </td>
  </tr>
</table>

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11+, Flask, PyJWT |
| **Frontend** | Vanilla JS SPA, Chart.js |
| **Data** | SQLite, akshare (中国公募基金数据) |
| **AI** | DeepSeek API |
| **Email** | SMTP (SendGrid / QQ邮箱等) |
| **Deploy** | Docker Compose, Nginx |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- 一个 DeepSeek API Key（[申请](https://platform.deepseek.com/)）
- （可选）一个 SMTP 邮箱账号用于邮件功能

### 1. 克隆仓库

```bash
git clone https://github.com/Shihengtao2324/fund-scope.git
cd fund-scope
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 填入你的配置（至少需要 `JWT_SECRET`）：

```ini
JWT_SECRET=<生成一个随机密钥>
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
```

生成 JWT 密钥：
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. 启动

```bash
docker compose up -d --build
```

访问 http://localhost:5000

> 首次启动会自动创建数据库表，无需手动初始化。

## Configuration

所有配置通过环境变量注入，参见 [`.env.example`](.env.example)：

| 变量 | 必填 | 说明 |
|------|------|------|
| `JWT_SECRET` | ✅ | JWT 签名密钥 |
| `DEEPSEEK_API_KEY` | ❌ | DeepSeek API Key（AI 问答功能需要） |
| `SMTP_SERVER` | ❌ | SMTP 服务器地址，默认 `smtp.qq.com` |
| `SMTP_PORT` | ❌ | SMTP 端口，默认 `465` |
| `SMTP_USER` | ❌ | SMTP 用户名 |
| `SMTP_PASS` | ❌ | SMTP 密码/授权码 |
| `DAILY_REPORT_EMAIL` | ❌ | 每日报告接收邮箱 |
| `DAILY_REPORT_TIME` | ❌ | 每日报告发送时间，默认 `20:00` |

## Development

本地开发（跳过 JWT 认证，免登录）：

```bash
cd backend
pip install -r requirements.txt
FLASK_DEBUG=1 SKIP_AUTH=1 python app.py
```

访问 http://localhost:5000

### Project Structure

```
fund-scope/
├── backend/
│   ├── app.py              # Flask 主入口（~60 routes）
│   ├── auth.py             # JWT 认证、注册、验证码
│   ├── config.py           # 配置读取（环境变量）
│   ├── database.py         # SQLite ORM
│   ├── email_sender.py     # 邮件发送
│   ├── fund_data.py        # akshare 数据获取 & 缓存
│   └── fund_analysis.py    # 多因子评分分析
├── frontend/
│   ├── index.html          # SPA 入口
│   ├── css/                # 样式
│   └── js/app.js           # 页面路由 & 交互逻辑
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Deployment

### Docker 部署（推荐）

```bash
docker compose up -d --build
```

建议配合 Nginx 反向代理 + HTTPS（如使用 Let's Encrypt）。

### 自动部署

项目内置了 Gitee/GitHub Webhook 自动部署支持：

1. 在 `.env` 中配置 `WEBHOOK_SECRET`
2. 在代码托管平台配置 Webhook POST 到 `https://your-domain/api/deploy`
3. 宿主机 cron 每分钟检测 `.deploy-trigger` 文件，自动执行 `docker compose up -d --build`

## Data Source

所有基金数据通过 [akshare](https://github.com/akfamily/akshare) 从中国公募基金公开市场获取，数据缓存 4 小时以减少请求频率。

## License

[MIT](LICENSE)

---

<p align="center">
  Built with ❤️ for personal fund analytics
</p>
