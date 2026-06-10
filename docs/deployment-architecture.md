# 部署架构与流量路径

## 服务拓扑

```
                      Internet
                         │
                  fund.hengtaoyuan.asia
                         │ :443
                         ▼
┌─────────────────────────────────┐
│    雷池 Safeline tengine         │  ← host 网络模式，reuseport
│  SSL 卸载 + WAF 检测             │
│  0.0.0.0:443 → backend_1        │
│  upstream: 127.0.0.1:9080       │
└──────────────┬──────────────────┘
               │ :9080
               ▼
┌─────────────────────────────────┐
│    aaPanel Nginx                 │
│  fund-cockpit.conf               │
│  listen 9080/9444                │
│  proxy_pass 127.0.0.1:5000      │
└──────────────┬──────────────────┘
               │ :5000
               ▼
┌─────────────────────────────────┐
│    fund-cockpit-api (Docker)     │
│  127.0.0.1:5000                 │
│  Flask 后端 + SQLite + akshare   │
└─────────────────────────────────┘
```

## 端口说明

| 端口 | 监听者 | 说明 |
|------|--------|------|
| `443` | 雷池 tengine | 对外 HTTPS 入口，SSL 终止 + WAF 检测 |
| `9080` | aaPanel Nginx | 雷池上游，HTTP 转发给后端 |
| `9444` | aaPanel Nginx | HTTPS（备，已通过雷池统一处理） |
| `5000` | fund-cockpit-api | Flask 容器，仅监听 127.0.0.1 |

## 请求处理流程

1. **用户请求** → `https://fund.hengtaoyuan.asia` 到达服务器 443 端口
2. **雷池 tengine** 接管连接（`reuseport` 与 aaPanel Nginx 共享 443 端口）
   - 完成 SSL 卸载
   - 经过 WAF 检测引擎（SQL 注入、XSS、CC 攻击等）
   - 检测通过后转发到 upstream `backend_1`（即 `127.0.0.1:9080`）
3. **aaPanel Nginx** 收到请求
   - 匹配 server_name `fund.hengtaoyuan.asia`
   - `proxy_pass http://127.0.0.1:5000`
4. **fund-cockpit-api 容器** 处理请求并返回响应
5. 响应沿原路径返回给用户

## 安全隔离

- `fund-cockpit-api` 只绑定 `127.0.0.1:5000`，无法从外部直接访问
- 所有外部流量强制经过雷池 WAF 过滤
- aaPanel Nginx 为中间层，可在此处添加额外访问控制或缓存

## 定时邮件任务

- `DAILY_REPORT_TIME=20:00` 每天 20:00 触发
- 容器内 daemon 线程执行，不走外部 HTTP
- SMTP 直连 QQ 邮箱（smtp.qq.com:465），无需经过 WAF
