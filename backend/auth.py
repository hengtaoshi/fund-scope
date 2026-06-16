"""
基金范围 — 认证模块

用户注册/登录：邮箱验证码 → 密码登录
"""
import os
import secrets
import smtplib
from functools import wraps
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from datetime import datetime, timedelta

import jwt
from werkzeug.security import generate_password_hash, check_password_hash
from flask import request, jsonify

from config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM, FROM_NAME, REPLY_TO_EMAIL
from database import (
    get_user_by_email, create_user,
    save_verification_code, get_latest_code, mark_code_used,
)

# JWT 密钥（必须通过环境变量设置）
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET 环境变量未设置，请设置一个 256-bit 随机密钥")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 7

# 验证码有效期（分钟）
CODE_EXPIRE_MINUTES = 5

# 发送验证码冷却时间（秒）
SEND_COOLDOWN_SECONDS = 60

# ====== IP 限流（内存中） ======
_login_attempts = {}  # {ip: [timestamp, ...]}

def check_rate_limit(ip: str, max_attempts: int, window_seconds: int) -> bool:
    """检查 IP 是否超过限流阈值"""
    now = datetime.now()
    attempts = [t for t in _login_attempts.get(ip, [])
                if (now - t).seconds < window_seconds]
    if len(attempts) >= max_attempts:
        return False
    attempts.append(now)
    _login_attempts[ip] = attempts
    return True


# ====== 密码哈希 ======

def hash_password(password: str) -> str:
    """密码哈希"""
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码"""
    return check_password_hash(password_hash, password)


# ====== JWT 中间件 ======


def login_required(f):
    """JWT 登录校验装饰器"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if os.environ.get("SKIP_AUTH", "").lower() in ("1", "true"):
            request.current_user = {"user_id": 1, "email": "dev@localhost"}
            return f(*args, **kwargs)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "未登录"}), 401
        token = auth.split(" ", 1)[1]
        payload = verify_jwt(token)
        if not payload:
            return jsonify({"error": "登录已过期，请重新登录"}), 401
        request.current_user = payload
        return f(*args, **kwargs)
    return decorated


# ====== JWT 令牌 ======

def sign_jwt(user_id: int, email: str) -> str:
    """签发 JWT 令牌"""
    payload = {
        "user_id": user_id,
        "email": email,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict | None:
    """验证 JWT 令牌，返回 payload 或 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


def refresh_jwt(token: str) -> str | None:
    """刷新 JWT 令牌：验证旧令牌有效后签发新令牌（续期 7 天）"""
    payload = verify_jwt(token)
    if not payload:
        return None
    # 签发新令牌，沿用原有 user_id 和 email
    return sign_jwt(payload["user_id"], payload["email"])


# ====== 验证码 ======

def generate_code() -> str:
    """生成 6 位数字验证码（密码学安全随机数）"""
    return str(secrets.randbelow(900000) + 100000)


def send_email(to_email: str, subject: str, body: str) -> bool:
    """发送邮件"""
    if not SMTP_SERVER or not SMTP_USER or not SMTP_PASS:
        print("[auth] SMTP 未配置，无法发送邮件")
        return False

    server = None
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        sender_addr = EMAIL_FROM or SMTP_USER
        msg["From"] = formataddr((FROM_NAME, sender_addr))
        msg["To"] = to_email
        if REPLY_TO_EMAIL:
            msg["Reply-To"] = REPLY_TO_EMAIL

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(sender_addr, [to_email], msg.as_string())
        return True
    except Exception as e:
        print(f"[auth] 邮件发送失败: {e}")
        return False
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass


def send_verification_code(email: str) -> dict:
    """发送验证码（含限流检查）"""
    # 检查冷却时间
    last_code = get_latest_code(email)
    if last_code:
        last_time = datetime.fromisoformat(last_code["created_at"])
        if datetime.now() - last_time < timedelta(seconds=SEND_COOLDOWN_SECONDS):
            remaining = SEND_COOLDOWN_SECONDS - (datetime.now() - last_time).seconds
            return {"success": False, "message": f"请 {remaining} 秒后再试"}

    code = generate_code()
    save_verification_code(email, code)

    subject = "基金范围 - 验证码"
    body = f"""
您的验证码为：{code}

验证码 5 分钟内有效，请勿泄露给他人。

（如非本人操作，请忽略此邮件）
"""
    ok = send_email(email, subject, body)
    if ok:
        return {"success": True, "message": "验证码已发送"}
    else:
        return {"success": False, "message": "验证码发送失败，请检查邮箱配置"}


def check_verification_code(email: str, code: str) -> bool:
    """校验验证码（5 分钟内有效，一次有效）"""
    record = get_latest_code(email)
    if not record:
        return False

    # 检查有效期
    created = datetime.fromisoformat(record["created_at"])
    if datetime.now() - created > timedelta(minutes=CODE_EXPIRE_MINUTES):
        return False

    # 检查验证码
    if record["code"] != code:
        return False

    # 标记已使用
    mark_code_used(record["id"])
    return True
