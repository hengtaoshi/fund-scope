"""
基金驾驶舱 — Flask 主入口
"""
import sys
import os
from flask import Flask, jsonify, request, send_from_directory

# 确保能找到同级模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fund_data import get_fund_nav, get_fund_info, get_fund_manager, search_fund
from database import init_db, add_holding, get_all_holdings, get_holding, update_holding, delete_holding
from fund_analysis import calc_indicators, calc_signals, calc_score
from email_sender import send_report, test_connection as test_smtp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

# 启动时初始化数据库
init_db()

app = Flask(__name__)


@app.route("/api/health")
def health():
    """健康检查"""
    return jsonify({"status": "ok", "service": "基金驾驶舱"})


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
def portfolio_analysis():
    """组合综合评分"""
    from database import get_all_holdings
    holdings = get_all_holdings()
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
def portfolio_list():
    """获取全部持仓（含实时市值）"""
    holdings = get_all_holdings()
    results = []
    for h in holdings:
        nav_df = get_fund_nav(h["code"])
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
        })
    return jsonify({"holdings": results})


@app.route("/api/portfolio", methods=["POST"])
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

    holding_id = add_holding(code, name, shares, cost_nav, notes)
    return jsonify({"id": holding_id, "name": name}), 201


@app.route("/api/portfolio/<int:holding_id>", methods=["PUT"])
def portfolio_update(holding_id: int):
    """更新持仓"""
    holding = get_holding(holding_id)
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

    ok = update_holding(holding_id, shares, cost_nav, notes)
    return jsonify({"updated": ok}), 200 if ok else 304


@app.route("/api/portfolio/<int:holding_id>", methods=["DELETE"])
def portfolio_delete(holding_id: int):
    """删除持仓"""
    ok = delete_holding(holding_id)
    return jsonify({"deleted": ok}), 200 if ok else 404


# ====== 邮件发送 ======


@app.route("/api/send-report", methods=["POST"])
def api_send_report():
    """发送加仓报告"""
    data = request.get_json(force=True)
    to_email = data.get("email", "").strip()

    # 获取持仓分析数据
    from database import get_all_holdings
    holdings = get_all_holdings()
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
def api_test_email():
    """测试 SMTP 连接"""
    result = test_smtp()
    status = 200 if result["success"] else 500
    return jsonify(result), status


# ====== 前端页面 ======


@app.route("/")
def serve_frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/js/<path:filename>")
def serve_js(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "js"), filename)


@app.route("/css/<path:filename>")
def serve_css(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "css"), filename)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"基金驾驶舱后端启动 http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
