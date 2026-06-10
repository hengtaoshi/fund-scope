# 基金驾驶舱 — Gitee Webhook 自动部署指南

## 一、什么是 CI/CD 自动部署

**CI/CD** 是 "持续集成 / 持续部署" 的缩写，核心思想就是一句话：

> 你 push 代码 → 服务器自动拉取 → 自动构建 → 自动重启服务

在你的场景下：

```
本地 git push → Gitee 收到新代码 → Gitee 发通知给你服务器 → 服务器自动部署
```

这消除了手动 SSH 登录、git pull、docker compose rebuild 等重复操作。

---

## 二、方案架构

```
┌──────────────┐     git push      ┌─────────────────┐
│   你的电脑     │ ───────────────→ │     Gitee        │
│  (VS Code)   │                   │  (代码托管平台)    │
└──────────────┘                   └────────┬────────┘
                                            │ POST /api/deploy
                                            │ (密码签名, 防恶意调用)
                                            ▼
                                  ┌─────────────────┐
                                  │   你的服务器       │
                                  │  124.221.92.130  │
                                  │                  │
                                  │  新 Flask 路由     │
                                  │  ↓               │
                                  │  git pull        │
                                  │  docker compose   │
                                  │    up -d --build  │
                                  │  ↓               │
                                  │  fund-cockpit-api │
                                  │  容器重建并重启     │
                                  └─────────────────┘
```

### 为什么用 Gitee Webhook 而不是 GitHub Actions？

- 你的代码在 **Gitee**（`gitee.com/hengtaoshi/quantitative-warehouse.git`）
- Gitee Webhook 是 Gitee 原生功能，无需第三方平台
- 只需要在服务器上写一段极简的接收代码（约 30 行），零外部依赖
- 服务器不需要公网可达（你的服务器已经有公网 IP）

---

## 三、核心原理详解

### 3.1 Gitee Webhook 工作流程

```
步骤1: 开发者 git push 到 Gitee
步骤2: Gitee 检测到仓库有新的 push
步骤3: Gitee 向你配置的 URL 发送 HTTP POST 请求
       → 请求头: X-Gitee-Token (你预设的密码)
       → 请求体: JSON，包含分支、提交者、commit 记录等
步骤4: 你的服务器接收请求，验证密码
步骤5: 密码正确则执行部署脚本
步骤6: 返回 HTTP 200 给 Gitee
```

### 3.2 安全性

每次 Webhook 请求都带有一个**预设密码**放在请求头中：

```python
# 服务器端验证
expected_token = "你自己设定的密码"
actual_token = request.headers.get("X-Gitee-Token", "")
if actual_token != expected_token:
    return "非法请求", 403  # 拒绝执行
```

这防止了：
- 恶意扫描器触发你的部署
- 不相关的人伪造部署请求
- 暴力破解（密码足够长）

### 3.3 部署操作

验证通过后，服务器执行的就是你之前手动做的两步操作：

```bash
# 1. 拉取最新代码
cd /root/fund-cockpit && git pull origin master

# 2. 重新构建并启动 Docker 容器
cd /root/fund-cockpit && docker compose up -d --build
```

`--build` 参数让 Docker 重新构建镜像（因为 Python 代码或前端文件变了）。
`.env` 文件在项目目录中，Docker Compose 自动读取，不会受 git pull 影响（.env 不在 Git 中）。

---

## 四、实施步骤

### 步骤 1：在服务器上添加接收 Webhook 的接口

在 `backend/app.py` 文件末尾（`if __name__ == "__main__":` 之前）添加以下路由：

```python
# ====== Gitee Webhook 自动部署 (2026-06-04) ======

import subprocess

@app.route("/api/deploy", methods=["POST"])
def deploy_webhook():
    """接收 Gitee Webhook，自动 git pull + docker rebuild"""
    # ---- 1. 验证密码 ----
    expected = os.environ.get("WEBHOOK_SECRET", "change-me-please")
    actual = request.headers.get("X-Gitee-Token", "")
    if not actual or actual != expected:
        return jsonify({"error": "未授权"}), 403

    # ---- 2. 只响应 master 分支 ----
    body = request.get_json(silent=True) or {}
    ref = body.get("ref", "")
    if ref != "refs/heads/master":
        return jsonify({"message": f"跳过非 master 分支: {ref}"})

    # ---- 3. 执行部署 ----
    project_dir = os.path.dirname(BASE_DIR)  # /root/fund-cockpit
    git_dir = os.path.join(project_dir, ".git")
    
    if not os.path.isdir(git_dir):
        return jsonify({"error": "项目目录不是 Git 仓库"}), 500

    try:
        # git pull
        result_pull = subprocess.run(
            ["git", "-C", project_dir, "pull", "origin", "master"],
            capture_output=True, text=True, timeout=60
        )
        if result_pull.returncode != 0:
            return jsonify({
                "error": "git pull 失败",
                "detail": result_pull.stderr.strip()
            }), 500

        # docker compose up -d --build
        result_build = subprocess.run(
            ["docker", "compose", "-f", os.path.join(project_dir, "docker-compose.yml"),
             "up", "-d", "--build"],
            capture_output=True, text=True, timeout=300
        )
        if result_build.returncode != 0:
            return jsonify({
                "error": "docker compose 失败",
                "detail": result_build.stderr.strip()
            }), 500

        return jsonify({
            "success": True,
            "summary": {
                "branch": "master",
                "commit": body.get("head_commit", {}).get("message", ""),
                "author": body.get("head_commit", {}).get("author", {}).get("name", ""),
            }
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "部署超时"}), 500
    except Exception as e:
        return jsonify({"error": f"部署异常: {str(e)}"}), 500
```

**注意：** 此路由**不需要** `@login_required` 装饰器，因为安全校验由 `WEBHOOK_SECRET` 密码完成（Gitee 不需要登录你的系统）。

### 步骤 2：配置环境变量

在服务器上的 `.env` 文件中添加一行：

```ini
WEBHOOK_SECRET=你的自定义密码至少16位
```

> 例如：`WEBHOOK_SECRET=my-fund-platform-deploy-key-2025`
> 这个密码不存 Git，不会泄露。

### 步骤 3：在 Gitee 后台配置 Webhook

1. 打开你的 Gitee 仓库页面：https://gitee.com/hengtaoshi/quantitative-warehouse
2. 进入 **管理** → **Webhooks**（在左侧导航栏）
3. 点击 **新建 WebHook**

填写内容：

| 字段 | 值 |
|------|-----|
| **URL** | `http://hengtaoyuan.asia/api/deploy` |
| **密码** | 与 `.env` 中 `WEBHOOK_SECRET` 的值一致 |
| **事件** | 勾选 **Push**（只监听 push 事件即可） |

4. 点击 **添加**

### 步骤 4：测试验证

先用手动方式在服务器上测试接口是否正常：

```bash
# 在服务器上执行，模拟 Gitee 的请求
curl -X POST http://127.0.0.1:5000/api/deploy \
  -H "Content-Type: application/json" \
  -H "X-Gitee-Token: 你的WEBHOOK_SECRET密码" \
  -d '{"ref": "refs/heads/master"}'
```

预期返回：
```json
{"success": true, "summary": {"branch": "master", ...}}
```

然后本地 push 一次测试，看服务器是否自动部署：

```bash
# 在你的电脑上，改一行代码，提交并推送
git add . && git commit -m "test: 测试 webhook 自动部署" && git push
```

登录服务器查看容器是否重建：

```bash
docker ps  # 看 fund-cockpit-api 的 STATUS 是否刚刚重启
```

---

## 五、你的项目环境信息

以下是你当前环境的实际情况，供参考：

| 项目 | 值 |
|------|-----|
| **代码托管** | Gitee |
| **仓库地址** | `https://gitee.com/hengtaoshi/quantitative-warehouse.git` |
| **服务器 IP** | `124.221.92.130` |
| **域名** | `hengtaoyuan.asia` |
| **项目路径** | `/root/fund-cockpit/` |
| **容器名称** | `fund-cockpit-api` |
| **编排工具** | Docker Compose (`docker-compose.yml`) |
| **Flask 端口** | `5000`（仅绑定 127.0.0.1，由宿主机 Nginx 反代） |
| **Nginx 反代** | 宿主机 `/etc/nginx/` 配置，域名 `hengtaoyuan.asia` → `127.0.0.1:5000` |
| **持久化** | Docker Volume `fund_data` → `/app/backend/data`（SQLite 数据库） |
| **环境变量** | `.env` 文件在 `/root/fund-cockpit/.env`（不存 Git） |
| **Git 凭证** | 服务器已配置 `git credential-store`（首次部署时已设置） |

---

## 六、常见问题

### Q: Nginx 会拦截 Webhook 吗？

不会。Nginx 配置了 `location / { proxy_pass http://flask:5000; }`，所有请求（包括 `/api/deploy`）都会反向代理到 Flask，Flask 路由处理 `/api/deploy`。

### Q: 部署途中如果有用户访问会怎样？

Nginx 在 Docker 重建期间（约 5-10 秒）会返回 502 Bad Gateway。用户刷新即可。这是可接受的短暂中断，不需要额外处理。

### Q: 如果部署失败了怎么办？

Webhook 返回错误信息给 Gitee，你可以在 Gitee Webhook 管理页面的"最近发送"列表看到失败原因。代码不会破坏运行中的容器——旧容器只有在 `docker compose up -d` 成功后才替换。

### Q: .env 文件会被 git pull 覆盖吗？

不会。`.env` 在 `.gitignore` 中，不在 Git 仓库里。`git pull` 只更新 Git 追踪的文件。加上之前的部署脚本中已经做了 `.env` 备份恢复的机制。

### Q: 如何回滚？

推送一个有问题的 commit 后想回滚，只需在本地：

```bash
git revert HEAD           # 创建回滚 commit
git push                  # 推送 → 自动部署到回滚版本
```

或者回退到之前的 tag（你在 v1.1-dca-20260604 已打好标签）：
```bash
git checkout v1.1-dca-20260604 -- .   # 恢复文件到 tag 版本
git commit -m "revert: 回滚到 v1.1" && git push
```

---

## 七、进阶：零停机部署（可选）

上面的方案有 5-10 秒的 502 窗口期。如果以后想做到**零停机**，只需要修改 `docker-compose.yml`：

```yaml
services:
  flask:
    # ... 原有配置 ...
    deploy:
      update_config:
        order: start-first   # 先启动新容器，再停旧容器
```

但这需要 Docker Swarm 模式（`docker swarm init`）。对于个人项目，当前的重启方案已经足够。

---

## 八、总结

| 对比项 | 现在的做法 | Webhook 自动部署 |
|--------|----------|-----------------|
| 部署方式 | SSH 手动连接 → git pull → docker compose | git push → 自动完成 |
| 耗时 | ~2 分钟（含连接登录） | ~30 秒（全自动） |
| 出错可能 | 手动输错命令 | 每次都一致执行 |
| 额外依赖 | 无 | 一个 Flask 路由 + Gitee 配置 |

**改动量：** 仅在 `app.py` 加约 40 行代码 + 服务器 `.env` 加一行密码 + Gitee 后台填一个 URL。
