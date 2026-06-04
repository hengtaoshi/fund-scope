# ============================================
# 基金驾驶舱 — Dockerfile
# 单容器：Flask 后端 + 静态前端
# ============================================
FROM python:3.11-slim

WORKDIR /app

# akshare / numpy / pandas 均有 pre-built wheels，无需 gcc

# 换 Debian 国内镜像源（加速 apt 下载）
RUN sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources

# 安装 git + docker CLI（用于 Webhook 自动部署）
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz | \
    tar xz -C /usr/local/bin --strip-components=1 docker/docker && \
    apt-get remove -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY backend/requirements.txt ./backend/
# 使用清华 PyPI 镜像加速国内下载
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r backend/requirements.txt

# 复制后端代码
COPY backend/ ./backend/

# 复制前端静态文件
COPY frontend/ ./frontend/

# 创建数据目录（init_db 会自动创建，但先创建确保权限）
RUN mkdir -p backend/data/cache

EXPOSE 5000

WORKDIR /app/backend

CMD ["python", "app.py"]
