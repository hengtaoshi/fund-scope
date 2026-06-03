"""
基金驾驶舱 — 配置文件
"""
import os

# SMTP 邮箱（从环境变量读取，不上传 git）
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
FROM_NAME = os.getenv("FROM_NAME", "基金驾驶舱")  # 发件人显示名称，隐藏个人邮箱

# 数据缓存
CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "cache")
CACHE_EXPIRE_HOURS = 4  # 缓存有效期

# akshare 请求间隔（秒）
AKSHARE_INTERVAL = 1.0
