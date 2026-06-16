"""启动脚本 - 设置环境变量后启动"""
import os
os.environ.setdefault("JWT_SECRET", "dev-secret-key-quant-cockpit-2024")
os.environ.setdefault("FLASK_DEBUG", "1")

from app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    print(f"基金范围后端启动 http://127.0.0.1:{port}  debug={debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)
