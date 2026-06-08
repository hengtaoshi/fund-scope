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
import threading
import time
from datetime import datetime, date
from functools import wraps
from fund_data import get_fund_nav, get_fund_info, get_fund_manager, search_fund
from database import init_db, add_holding, get_all_holdings, get_holding, update_holding, delete_holding, get_user_by_email, create_user
from fund_analysis import calc_indicators, calc_signals, calc_score
from email_sender import send_report, test_connection as test_smtp, send_deploy_notification, send_daily_report
from config import CACHE_DIR, DAILY_REPORT_EMAIL, DAILY_REPORT_TIME
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
        # 昨日（上一交易日）净值
        nav_vals = nav_df["单位净值"].values if not nav_df.empty else []
        yesterday_nav = float(nav_vals[-2]) if len(nav_vals) >= 2 else latest_nav
        cost_total = h["shares"] * h["cost_nav"]
        current_total = h["shares"] * latest_nav
        yesterday_total = h["shares"] * yesterday_nav
        daily_profit = round(current_total - yesterday_total, 2)
        daily_return_pct = round((latest_nav - yesterday_nav) / yesterday_nav * 100, 2) if yesterday_nav > 0 else 0
        results.append({
            "id": h["id"],
            "code": h["code"],
            "name": h["name"],
            "shares": h["shares"],
            "cost_nav": h["cost_nav"],
            "current_nav": latest_nav,
            "yesterday_nav": yesterday_nav,
            "cost_total": round(cost_total, 2),
            "current_total": round(current_total, 2),
            "profit": round(current_total - cost_total, 2),
            "return_pct": round((current_total - cost_total) / cost_total * 100, 2) if cost_total > 0 else 0,
            "daily_profit": daily_profit,
            "daily_return_pct": daily_return_pct,
            "added_at": h["added_at"],
            "notes": h["notes"],
            "total_invested": h.get("total_invested"),
            "dca_start_date": h.get("dca_start_date"),
            "dca_amount": h.get("dca_amount"),
            "dca_frequency": h.get("dca_frequency"),
            "dca_end_date": h.get("dca_end_date"),
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
    dca_end_date = data.get("dca_end_date")
    holding_id = add_holding(request.current_user['user_id'], code, name, shares, cost_nav, notes, total_invested, dca_start_date, dca_amount, dca_frequency, dca_end_date)
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
    dca_end_date = data.get("dca_end_date")
    ok = update_holding(holding_id, request.current_user['user_id'], shares, cost_nav, notes, total_invested, dca_start_date, dca_amount, dca_frequency, dca_end_date)
    return jsonify({"updated": ok}), 200 if ok else 304


@app.route("/api/portfolio/<int:holding_id>", methods=["DELETE"])
@login_required
def portfolio_delete(holding_id: int):
    """删除持仓"""
    ok = delete_holding(holding_id, request.current_user['user_id'])
    return jsonify({"deleted": ok}), 200 if ok else 404


@app.route("/api/portfolio/<int:holding_id>/stop-dca", methods=["POST"])
@login_required
def portfolio_stop_dca(holding_id: int):
    """终止定投：设置 dca_end_date 为今天，冻结累计投入"""
    from datetime import date
    holding = get_holding(holding_id, request.current_user['user_id'])
    if not holding:
        return jsonify({"error": "持仓不存在"}), 404
    if not holding.get("dca_start_date"):
        return jsonify({"error": "该持仓非定投模式"}), 400
    if holding.get("dca_end_date"):
        return jsonify({"error": "定投已终止"}), 400
    today = date.today().isoformat()
    ok = update_holding(holding_id, request.current_user['user_id'], dca_end_date=today)
    return jsonify({"stopped": ok, "dca_end_date": today}), 200 if ok else 304


@app.route("/api/portfolio/<int:holding_id>/resume-dca", methods=["POST"])
@login_required
def portfolio_resume_dca(holding_id: int):
    """恢复定投：清除 dca_end_date"""
    holding = get_holding(holding_id, request.current_user['user_id'])
    if not holding:
        return jsonify({"error": "持仓不存在"}), 404
    if not holding.get("dca_start_date"):
        return jsonify({"error": "该持仓非定投模式"}), 400
    if not holding.get("dca_end_date"):
        return jsonify({"error": "定投未终止"}), 400
    ok = update_holding(holding_id, request.current_user['user_id'], dca_end_date=None)
    return jsonify({"resumed": ok}), 200 if ok else 304


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


@app.route("/api/send-daily-report", methods=["POST"])
@login_required
def api_send_daily_report():
    """发送每日收益报告"""
    if not DAILY_REPORT_EMAIL:
        return jsonify({"error": "DAILY_REPORT_EMAIL 未设置"}), 400

    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"error": "暂无持仓"}), 404

    results = []
    total_val = 0
    total_daily = 0
    total_profit = 0
    for h in holdings:
        nav_df = get_fund_nav(h["code"], force_refresh=True)
        if nav_df.empty:
            continue
        nav_vals = nav_df["单位净值"].values
        latest_nav = float(nav_vals[-1])
        yesterday_nav = float(nav_vals[-2]) if len(nav_vals) >= 2 else latest_nav
        current_total = h["shares"] * latest_nav
        cost_total = h["shares"] * h["cost_nav"]
        yesterday_total = h["shares"] * yesterday_nav
        daily_profit = round(current_total - yesterday_total, 2)
        daily_return_pct = round((latest_nav - yesterday_nav) / yesterday_nav * 100, 2) if yesterday_nav > 0 else 0
        profit = round(current_total - cost_total, 2)
        return_pct = round(profit / cost_total * 100, 2) if cost_total > 0 else 0

        total_val += current_total
        total_daily += daily_profit
        total_profit += profit

        results.append({
            "name": h["name"],
            "code": h["code"],
            "shares": h["shares"],
            "current_nav": latest_nav,
            "yesterday_nav": yesterday_nav,
            "daily_profit": daily_profit,
            "daily_return_pct": daily_return_pct,
            "profit": profit,
            "return_pct": return_pct,
            "current_total": round(current_total, 2),
        })

    result = send_daily_report(DAILY_REPORT_EMAIL, results, {
        "total_val": round(total_val, 2),
        "total_daily_profit": round(total_daily, 2),
        "total_profit": round(total_profit, 2),
    })
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
    commit_msg = body.get("head_commit", {}).get("message", "")
    author_name = body.get("head_commit", {}).get("author", {}).get("name", "")

    try:
        result_fetch = subprocess.run(
            ["git", "-C", project_dir, "fetch", "origin", "master"],
            capture_output=True, text=True, timeout=60
        )
        if result_fetch.returncode != 0:
            send_deploy_notification(False, commit_msg, author_name, result_fetch.stderr.strip())
            return jsonify({"error": "git fetch 失败", "detail": result_fetch.stderr.strip()}), 500

        result_reset = subprocess.run(
            ["git", "-C", project_dir, "reset", "--hard", "origin/master"],
            capture_output=True, text=True, timeout=30
        )
        if result_reset.returncode != 0:
            send_deploy_notification(False, commit_msg, author_name, result_reset.stderr.strip())
            return jsonify({"error": "git reset 失败", "detail": result_reset.stderr.strip()}), 500

        # 写入触发文件，由宿主机 cron 执行 docker compose up --build
        trigger_file = os.path.join(project_dir, ".deploy-trigger")
        with open(trigger_file, "w") as f:
            f.write(body.get("head_commit", {}).get("message", "webhook"))

        # 发送部署成功通知
        send_deploy_notification(True, commit_msg, author_name)

        return jsonify({
            "success": True,
            "message": "已触发部署，宿主机将在 1 分钟内执行重建",
            "commit": body.get("head_commit", {}).get("message", ""),
            "author": body.get("head_commit", {}).get("author", {}).get("name", ""),
        })

    except subprocess.TimeoutExpired:
        send_deploy_notification(False, commit_msg, author_name, "部署超时")
        return jsonify({"error": "部署超时"}), 500
    except Exception as e:
        send_deploy_notification(False, commit_msg, author_name, str(e))
        return jsonify({"error": str(e)}), 500


# ====== 每日报告定时调度 ======

_scheduler_running = False
_last_report_date = None  # 防止同一天重复发送


def _daily_report_scheduler():
    """后台线程：每天在 DAILY_REPORT_TIME 触发一次每日报告"""
    global _scheduler_running, _last_report_date
    _scheduler_running = True
    print(f"[调度器] 每日报告已启动，计划时间 {DAILY_REPORT_TIME}")

    while _scheduler_running:
        try:
            now = datetime.now()
            target_h, target_m = map(int, DAILY_REPORT_TIME.split(":"))
            # 计算距离下一次触发还有多久
            target = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
            if target <= now:
                target = target.replace(day=now.day + 1)  # 明天同一时间
            wait_seconds = (target - now).total_seconds()
            # 最多等 120 秒就重新检查一次（避免 sleep 过长）
            while wait_seconds > 0 and _scheduler_running:
                time.sleep(min(wait_seconds, 120))
                wait_seconds -= 120
                if not _scheduler_running:
                    break

            if not _scheduler_running:
                break

            today_str = date.today().isoformat()
            if _last_report_date == today_str:
                continue  # 今天已发送，跳过

            # 发送每日报告
            if DAILY_REPORT_EMAIL:
                try:
                    from database import get_all_holdings
                    holdings = get_all_holdings(1)  # user_id=1
                    if holdings:
                        results = []
                        total_val = total_daily = total_profit = 0
                        for h in holdings:
                            nav_df = get_fund_nav(h["code"], force_refresh=True)
                            if nav_df.empty:
                                continue
                            nav_vals = nav_df["单位净值"].values
                            latest_nav = float(nav_vals[-1])
                            yesterday_nav = float(nav_vals[-2]) if len(nav_vals) >= 2 else latest_nav
                            current_total = h["shares"] * latest_nav
                            cost_total = h["shares"] * h["cost_nav"]
                            daily_profit = round(current_total - h["shares"] * yesterday_nav, 2)
                            daily_pct = round((latest_nav - yesterday_nav) / yesterday_nav * 100, 2) if yesterday_nav > 0 else 0
                            profit = round(current_total - cost_total, 2)
                            return_pct = round(profit / cost_total * 100, 2) if cost_total > 0 else 0
                            total_val += current_total
                            total_daily += daily_profit
                            total_profit += profit
                            results.append({
                                "name": h["name"], "code": h["code"], "shares": h["shares"],
                                "current_nav": latest_nav, "yesterday_nav": yesterday_nav,
                                "daily_profit": daily_profit, "daily_return_pct": daily_pct,
                                "profit": profit, "return_pct": return_pct,
                                "current_total": round(current_total, 2),
                            })
                        totals = {"total_val": round(total_val, 2), "total_daily_profit": round(total_daily, 2), "total_profit": round(total_profit, 2)}
                        send_daily_report(DAILY_REPORT_EMAIL, results, totals)
                        _last_report_date = today_str
                        print(f"[调度器] 每日报告已发送 → {DAILY_REPORT_EMAIL}")
                except Exception as e:
                    print(f"[调度器] 发送失败: {e}")
        except Exception as e:
            print(f"[调度器] 异常: {e}")
            time.sleep(300)  # 出错等 5 分钟再重试


def start_scheduler():
    """启动每日报告后台线程"""
    if not DAILY_REPORT_EMAIL:
        print("[调度器] DAILY_REPORT_EMAIL 未设置，跳过")
        return
    t = threading.Thread(target=_daily_report_scheduler, daemon=True)
    t.start()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    print(f"基金驾驶舱后端启动 http://127.0.0.1:{port}  debug={debug}")
    start_scheduler()
    app.run(host="0.0.0.0", port=port, debug=debug)
