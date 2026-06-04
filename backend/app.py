"""
基金驾驶舱 — Flask 主入口
"""
import sys
import os
from flask import Flask, jsonify, request, send_from_directory

# 确保能找到同级模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re
import shutil
import subprocess
from functools import wraps
from fund_data import get_fund_nav, get_fund_info, get_fund_manager, search_fund
from database import init_db, add_holding, get_all_holdings, get_holding, update_holding, delete_holding, get_user_by_email, create_user
from fund_analysis import calc_indicators, calc_signals, calc_score
from email_sender import send_report, test_connection as test_smtp
from config import CACHE_DIR
# 默认 JWT_SECRET（生产环境应用环境变量覆盖）
if not os.environ.get("JWT_SECRET"):
    os.environ["JWT_SECRET"] = "fund-dashboard-jwt-secret-key-2025"

from auth import (
    sign_jwt, verify_jwt, verify_password, hash_password,
    send_verification_code, check_verification_code, check_rate_limit,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

# 启动时初始化数据库
init_db()

# 本地开发模式：自动创建测试用户
if os.environ.get("SKIP_AUTH", "").lower() in ("1", "true"):
    test_email = "test@dev.local"
    test_password = "test123456"
    existing = get_user_by_email(test_email)
    if not existing:
        create_user(test_email, hash_password(test_password))
        print(f"[DEV] 已创建测试用户: {test_email} / {test_password}")
    else:
        print(f"[DEV] 测试用户已存在: {test_email}")

app = Flask(__name__)

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




@app.route("/api/health")
def health():
    """健康检查"""
    return jsonify({"status": "ok", "service": "基金驾驶舱"})


@app.route("/api/clear-cache")
@login_required
def api_clear_cache():
    """清除所有数据缓存，下次请求重新抓取"""
    if os.path.exists(CACHE_DIR):
        for f in os.listdir(CACHE_DIR):
            fp = os.path.join(CACHE_DIR, f)
            try:
                os.remove(fp)
            except OSError as e:
                print(f"[WARN] 清除缓存文件失败 {fp}: {e}")
    return jsonify({"success": True, "message": "缓存已清除"})

# ====== 认证 API ======


@app.route("/api/auth/send-code", methods=["POST"])
def api_send_code():
    """发送邮箱验证码"""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "请输入有效邮箱"}), 400
    result = send_verification_code(email)
    status = 200 if result["success"] else 400
    return jsonify(result), status


@app.route("/api/auth/register", methods=["POST"])
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

    # 验证码校验
    if not check_verification_code(email, code):
        return jsonify({"error": "验证码错误或已过期"}), 400

    # 检查是否已注册
    if get_user_by_email(email):
        return jsonify({"error": "该邮箱已注册"}), 400

    # 创建用户
    pw_hash = hash_password(password)
    user = create_user(email, pw_hash)

    # 签发令牌
    token = sign_jwt(user, email)
    return jsonify({"success": True, "token": token, "email": email}), 201


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """登录：邮箱 + 密码"""
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "请输入邮箱和密码"}), 400

    # IP 限流：同一 IP 5 次失败后锁定 15 分钟
    ip = request.remote_addr or "unknown"
    if not check_rate_limit(ip, max_attempts=5, window_seconds=900):
        return jsonify({"error": "登录尝试过于频繁，请 15 分钟后再试"}), 429

    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return jsonify({"error": "邮箱或密码错误"}), 401

    token = sign_jwt(user["id"], email)
    return jsonify({"success": True, "token": token, "email": email})


@app.route("/api/auth/dev-login", methods=["POST"])
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


@app.route("/api/auth/me")
@login_required
def api_me():
    """获取当前登录用户信息"""
    return jsonify({
        "user_id": request.current_user["user_id"],
        "email": request.current_user["email"],
    })


@app.route("/api/fund/<code>")
def fund_detail(code: str):
    """基金详情（基本信息 + 现任经理）"""
    info = get_fund_info(code)
    if not info:
        return jsonify({"error": f"未找到基金 {code}"}), 404

    managers = get_fund_manager(code)
    info["managers"] = managers[:3]  # 取最近 3 位经理

    return jsonify(info)


@app.route("/api/fund/<code>/nav")
def fund_nav(code: str):
    """基金历史净值"""
    force = request.args.get("force", "").lower() == "true"
    df = get_fund_nav(code, force_refresh=force)
    if df.empty:
        return jsonify({"error": f"获取 {code} 净值失败"}), 500
    return jsonify({
        "code": code,
        "count": len(df),
        "data": df.to_dict(orient="records"),
    })


@app.route("/api/fund/search")
def fund_search():
    """搜索基金"""
    keyword = request.args.get("q", "")
    if not keyword:
        return jsonify({"error": "缺少搜索关键词 ?q="}), 400
    results = search_fund(keyword)
    return jsonify({"results": results})


# ====== 分析引擎 ======


def _get_analysis(code: str):
    """获取基金完整分析数据"""
    nav_df = get_fund_nav(code)
    if nav_df.empty:
        return None, "获取净值失败"
    indicators = calc_indicators(nav_df)
    if "error" in indicators:
        return None, indicators["error"]
    signals = calc_signals(nav_df)
    score = calc_score(indicators, signals)
    info = get_fund_info(code)
    return {
        "code": code,
        "name": info.get("fund_name", ""),
        "type": info.get("fund_type", ""),
        "indicators": indicators,
        "signals": signals,
        "score": score,
    }, None


@app.route("/api/analysis/<code>")
def analysis_full(code: str):
    """基金完整分析（指标+信号+评分）"""
    result, err = _get_analysis(code)
    if err:
        return jsonify({"error": err}), 500
    return jsonify(result)


@app.route("/api/analysis/<code>/indicators")
def analysis_indicators(code: str):
    """仅指标"""
    nav_df = get_fund_nav(code)
    if nav_df.empty:
        return jsonify({"error": "获取净值失败"}), 500
    ind = calc_indicators(nav_df)
    return jsonify(ind)


@app.route("/api/analysis/<code>/signals")
def analysis_signals(code: str):
    """仅技术信号"""
    nav_df = get_fund_nav(code)
    if nav_df.empty:
        return jsonify({"error": "获取净值失败"}), 500
    sig = calc_signals(nav_df)
    return jsonify(sig)


@app.route("/api/analysis/<code>/score")
def analysis_score(code: str):
    """仅评分"""
    nav_df = get_fund_nav(code)
    if nav_df.empty:
        return jsonify({"error": "获取净值失败"}), 500
    ind = calc_indicators(nav_df)
    sig = calc_signals(nav_df)
    sc = calc_score(ind, sig)
    return jsonify(sc)


@app.route("/api/portfolio/analysis")
@login_required
def portfolio_analysis():
    """组合综合评分"""
    from database import get_all_holdings
    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"error": "暂无持仓"}), 404

    scores = []
    for h in holdings:
        nav_df = get_fund_nav(h["code"])
        if nav_df.empty:
            continue
        ind = calc_indicators(nav_df)
        sig = calc_signals(nav_df)
        sc = calc_score(ind, sig)
        scores.append({
            "code": h["code"],
            "name": h["name"],
            "score": sc["total_score"],
            "action": sc["action"],
            "level": sc["level"],
        })

    if not scores:
        return jsonify({"error": "分析失败"}), 500

    avg_score = round(sum(s["score"] for s in scores) / len(scores))
    buy_count = sum(1 for s in scores if "买入" in s["action"])

    return jsonify({
        "portfolio_score": avg_score,
        "fund_count": len(scores),
        "buy_recommend": buy_count,
        "holdings": scores,
    })


# ====== 持仓管理 ======


@app.route("/api/portfolio", methods=["GET"])
@login_required
def portfolio_list():
    """获取全部持仓（含实时市值）"""
    force = request.args.get("force", "").lower() == "true"
    holdings = get_all_holdings(request.current_user['user_id'])
    results = []
    for h in holdings:
        nav_df = get_fund_nav(h["code"], force_refresh=force)
        latest_nav = float(nav_df["单位净值"].iloc[-1]) if not nav_df.empty else 0
        cost_total = h["shares"] * h["cost_nav"]
        current_total = h["shares"] * latest_nav
        results.append({
            "id": h["id"],
            "code": h["code"],
            "name": h["name"],
            "shares": h["shares"],
            "cost_nav": h["cost_nav"],
            "current_nav": latest_nav,
            "cost_total": round(cost_total, 2),
            "current_total": round(current_total, 2),
            "profit": round(current_total - cost_total, 2),
            "return_pct": round((current_total - cost_total) / cost_total * 100, 2) if cost_total > 0 else 0,
            "added_at": h["added_at"],
            "notes": h["notes"],
            "total_invested": h.get("total_invested"),
            "dca_start_date": h.get("dca_start_date"),
            "dca_amount": h.get("dca_amount"),
            "dca_frequency": h.get("dca_frequency"),
        })
    return jsonify({"holdings": results})


@app.route("/api/portfolio", methods=["POST"])
@login_required
def portfolio_add():
    """添加持仓"""
    data = request.get_json(force=True)
    code = data.get("code", "").strip()
    shares = data.get("shares", 0)
    cost_nav = data.get("cost_nav", 0)
    notes = data.get("notes", "")

    if not code:
        return jsonify({"error": "基金代码不能为空"}), 400
    if shares <= 0:
        return jsonify({"error": "份额必须大于 0"}), 400
    if cost_nav <= 0:
        return jsonify({"error": "成本净值必须大于 0"}), 400

    # 自动补全基金名称
    info = get_fund_info(code)
    name = info.get("fund_name", code) if info else code

    total_invested = data.get("total_invested")
    dca_start_date = data.get("dca_start_date")
    dca_amount = data.get("dca_amount")
    dca_frequency = data.get("dca_frequency")
    holding_id = add_holding(request.current_user['user_id'], code, name, shares, cost_nav, notes, total_invested, dca_start_date, dca_amount, dca_frequency)
    return jsonify({"id": holding_id, "name": name}), 201


@app.route("/api/portfolio/<int:holding_id>", methods=["PUT"])
@login_required
def portfolio_update(holding_id: int):
    """更新持仓"""
    holding = get_holding(holding_id, request.current_user['user_id'])
    if not holding:
        return jsonify({"error": "持仓不存在"}), 404

    data = request.get_json(force=True)
    shares = data.get("shares")
    cost_nav = data.get("cost_nav")
    notes = data.get("notes")

    if shares is not None and shares <= 0:
        return jsonify({"error": "份额必须大于 0"}), 400
    if cost_nav is not None and cost_nav <= 0:
        return jsonify({"error": "成本净值必须大于 0"}), 400

    total_invested = data.get("total_invested")
    dca_start_date = data.get("dca_start_date")
    dca_amount = data.get("dca_amount")
    dca_frequency = data.get("dca_frequency")
    ok = update_holding(holding_id, request.current_user['user_id'], shares, cost_nav, notes, total_invested, dca_start_date, dca_amount, dca_frequency)
    return jsonify({"updated": ok}), 200 if ok else 304


@app.route("/api/portfolio/<int:holding_id>", methods=["DELETE"])
@login_required
def portfolio_delete(holding_id: int):
    """删除持仓"""
    ok = delete_holding(holding_id, request.current_user['user_id'])
    return jsonify({"deleted": ok}), 200 if ok else 404


# ====== 邮件发送 ======


@app.route("/api/send-report", methods=["POST"])
@login_required
def api_send_report():
    """发送加仓报告"""
    data = request.get_json(force=True)
    to_email = data.get("email", "").strip()

    # 获取持仓分析数据
    from database import get_all_holdings
    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"success": False, "message": "暂无持仓"}), 400

    report_holdings = []
    for h in holdings:
        nav_df = get_fund_nav(h["code"])
        if nav_df.empty:
            continue
        ind = calc_indicators(nav_df)
        sig = calc_signals(nav_df)
        sc = calc_score(ind, sig)
        signals_list = sig.get("summary", []) if isinstance(sig, dict) else []
        report_holdings.append({
            "code": h["code"],
            "name": h["name"],
            "score": sc["total_score"],
            "level": sc["level"],
            "action": sc["action"],
            "annual_return": ind.get("annual_return", "-"),
            "max_drawdown": ind.get("max_drawdown", "-"),
            "signals": signals_list,
            "comment": f'基于多因子评分，当前评分 {sc["total_score"]} 分，{sc["level"]}，建议 {sc["action"]}',
        })

    if not report_holdings:
        return jsonify({"success": False, "message": "分析失败"}), 500

    avg_score = round(sum(h["score"] for h in report_holdings) / len(report_holdings))
    buy_count = sum(1 for h in report_holdings if "买入" in h["action"])

    report_data = {
        "portfolio_score": avg_score,
        "buy_recommend": buy_count,
        "holdings": report_holdings,
    }

    result = send_report(to_email, report_data)
    status = 200 if result["success"] else 500
    return jsonify(result), status


@app.route("/api/test-email", methods=["POST"])
@login_required
def api_test_email():
    """测试 SMTP 连接"""
    result = test_smtp()
    status = 200 if result["success"] else 500
    return jsonify(result), status


# ====== 前端页面 ======


@app.route("/")
def serve_frontend():
    """主页面（需登录）"""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/login")
def serve_login():
    """登录页面"""
    return send_from_directory(FRONTEND_DIR, "login.html")


@app.route("/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "js"), filename)


@app.route("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "css"), filename)


@app.route("/webfonts/<path:filename>")
def serve_webfonts(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "webfonts"), filename)


# ====== Gitee Webhook 自动部署 ======


@app.route("/api/deploy", methods=["POST"])
def deploy_webhook():
    """接收 Gitee Webhook，自动 git pull + docker compose up -d --build"""
    expected = os.environ.get("WEBHOOK_SECRET", "")
    actual = request.headers.get("X-Gitee-Token", "")
    if not expected or not actual or actual != expected:
        return jsonify({"error": "未授权"}), 403

    body = request.get_json(silent=True) or {}
    ref = body.get("ref", "")
    if ref != "refs/heads/master":
        return jsonify({"message": f"跳过非 master 分支"})

    project_dir = os.environ.get("PROJECT_DIR", os.path.dirname(BASE_DIR))

    try:
        result_fetch = subprocess.run(
            ["git", "-C", project_dir, "fetch", "origin", "master"],
            capture_output=True, text=True, timeout=60
        )
        if result_fetch.returncode != 0:
            return jsonify({"error": "git fetch 失败", "detail": result_fetch.stderr.strip()}), 500

        result_reset = subprocess.run(
            ["git", "-C", project_dir, "reset", "--hard", "origin/master"],
            capture_output=True, text=True, timeout=30
        )
        if result_reset.returncode != 0:
            return jsonify({"error": "git reset 失败", "detail": result_reset.stderr.strip()}), 500

        result_build = subprocess.run(
            ["docker", "compose", "-f", os.path.join(project_dir, "docker-compose.yml"),
             "up", "-d", "--build", "--remove-orphans"],
            capture_output=True, text=True, timeout=300
        )
        if result_build.returncode != 0:
            return jsonify({"error": "docker compose 失败", "detail": result_build.stderr.strip()}), 500

        return jsonify({
            "success": True,
            "commit": body.get("head_commit", {}).get("message", ""),
            "author": body.get("head_commit", {}).get("author", {}).get("name", ""),
        })

    except subprocess.TimeoutExpired:
        return jsonify({"error": "部署超时"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    print(f"基金驾驶舱后端启动 http://127.0.0.1:{port}  debug={debug}")
    app.run(host="0.0.0.0", port=port, debug=debug)
