"""认证相关路由"""
import re
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flask import request, jsonify
from auth import (
    sign_jwt, refresh_jwt, verify_password, hash_password, login_required,
    send_verification_code, check_verification_code, check_rate_limit,
)
from database import get_user_by_email, create_user
from . import auth_bp


@auth_bp.route("/api/auth/send-code", methods=["POST"])
def api_send_code():
    """发送邮箱验证码"""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "请输入有效邮箱"}), 400
    result = send_verification_code(email)
    status = 200 if result["success"] else 400
    return jsonify(result), status


@auth_bp.route("/api/auth/register", methods=["POST"])
def api_register():
    """注册：验证码校验 + 设置密码"""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    code = (data.get("code") or "").strip()
    password = data.get("password") or ""

    if not email or "@" not in email:
        return jsonify({"error": "请输入有效邮箱"}), 400
    if not code or len(code) != 6:
        return jsonify({"error": "请输入 6 位验证码"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400
    if not re.search(r'[a-zA-Z]', password) or not re.search(r'\d', password):
        return jsonify({"error": "密码需包含字母和数字"}), 400

    if not check_verification_code(email, code):
        return jsonify({"error": "验证码错误或已过期"}), 400
    if get_user_by_email(email):
        return jsonify({"error": "该邮箱已注册"}), 400

    pw_hash = hash_password(password)
    user = create_user(email, pw_hash)
    token = sign_jwt(user, email)
    return jsonify({"success": True, "token": token, "email": email}), 201


@auth_bp.route("/api/auth/login", methods=["POST"])
def api_login():
    """登录：邮箱 + 密码"""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "请输入邮箱和密码"}), 400

    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip, max_attempts=5, window_seconds=900):
        return jsonify({"error": "登录尝试过于频繁，请 15 分钟后再试"}), 429

    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return jsonify({"error": "邮箱或密码错误"}), 401

    token = sign_jwt(user["id"], email)
    return jsonify({"success": True, "token": token, "email": email})


@auth_bp.route("/api/auth/dev-login", methods=["POST"])
def api_dev_login():
    """开发模式自动登录（仅 SKIP_AUTH=1 时可用）"""
    if os.environ.get("SKIP_AUTH", "").lower() not in ("1", "true"):
        return jsonify({"error": "仅开发模式可用"}), 403
    user = get_user_by_email("test@dev.local")
    if not user:
        create_user("test@dev.local", hash_password("test123456"))
        user = get_user_by_email("test@dev.local")
    token = sign_jwt(user["id"], "test@dev.local")
    return jsonify({"success": True, "token": token, "email": "test@dev.local"})


@auth_bp.route("/api/auth/me")
@login_required
def api_me():
    """获取当前登录用户信息"""
    return jsonify({
        "user_id": request.current_user["user_id"],
        "email": request.current_user["email"],
    })


@auth_bp.route("/api/auth/refresh", methods=["POST"])
@login_required
def api_refresh_token():
    """刷新 JWT 令牌（静默续期）"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "无效令牌"}), 401
    token = auth.split(" ", 1)[1]
    new_token = refresh_jwt(token)
    if not new_token:
        return jsonify({"error": "令牌刷新失败"}), 401
    return jsonify({"success": True, "token": new_token})
