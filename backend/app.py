"""
基金范围 — Flask 主入口
"""
import sys
import os
from flask import Flask, jsonify, request, send_from_directory, Response

# 确保能找到同级模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, date
from functools import wraps
import urllib.request
import urllib.error
import json as json_module
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed
import pandas as pd
from fund_data import get_fund_nav, get_fund_info, get_fund_manager, search_fund, screen_funds, get_fund_holdings, get_index_data
from database import init_db, add_holding, get_all_holdings, get_holding, update_holding, delete_holding, get_user_by_email, create_user, get_transactions, add_transaction, delete_transaction, get_holdings_from_transactions, get_watchlist, add_watchlist, delete_watchlist, update_watchlist
from fund_analysis import calc_indicators, calc_signals, calc_score, calc_xirr, calc_portfolio_var
from email_sender import send_report, test_connection as test_smtp, send_deploy_notification, send_daily_report
from config import CACHE_DIR, DAILY_REPORT_EMAIL, DAILY_REPORT_TIME, DEEPSEEK_API_KEY, DEEPSEEK_MODEL
# JWT_SECRET 必须通过环境变量或 .env 文件设置
# 生成命令：python3 -c "import secrets; print(secrets.token_hex(32))"

from auth import (
    sign_jwt, verify_jwt, refresh_jwt, verify_password, hash_password, login_required,
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

# 全局错误处理：所有 API 错误返回 JSON 而非 HTML
@app.errorhandler(404)
def api_not_found(e):
    return jsonify({"error": "接口不存在", "path": request.path}), 404

@app.errorhandler(500)
def api_server_error(e):
    return jsonify({"error": "服务器内部错误", "detail": str(e) if os.environ.get("FLASK_DEBUG") else ""}), 500

@app.errorhandler(Exception)
def api_exception(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "服务器错误", "detail": str(e) if os.environ.get("FLASK_DEBUG") else ""}), 500
    raise e  # 非 API 路由仍然抛出，让 Flask 默认处理

# 前端 JS 不缓存，确保更新后立即生效
@app.after_request
def no_cache_js(response):
    if response.content_type and "javascript" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

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

# ====== 注册蓝图 ======
from routes import auth_bp, fund_bp, analysis_bp, portfolio_bp, ai_bp
app.register_blueprint(auth_bp)


@app.route("/api/health")
def health():
    """健康检查"""
    return jsonify({"status": "ok", "service": "基金范围"})


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

# ====== 认证 API（已移至 routes/auth.py）======


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


@app.route("/api/fund/navs")
def fund_navs_batch():
    """批量获取基金历史净值（逗号分隔）"""
    codes_str = request.args.get("codes", "")
    if not codes_str:
        return jsonify({"error": "缺少参数 codes，逗号分隔多个基金代码"}), 400
    codes = [c.strip() for c in codes_str.split(",") if c.strip()]
    if not codes:
        return jsonify({"error": "无效的基金代码"}), 400
    force = request.args.get("force", "").lower() == "true"

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    errors = []
    with ThreadPoolExecutor(max_workers=min(len(codes), 10)) as executor:
        future_map = {executor.submit(get_fund_nav, code, force): code for code in codes}
        for future in as_completed(future_map, timeout=30):
            code = future_map[future]
            try:
                df = future.result()
                if df.empty:
                    errors.append(code)
                else:
                    results[code] = {
                        "code": code,
                        "count": len(df),
                        "data": df.to_dict(orient="records"),
                    }
            except Exception as e:
                errors.append(code)
                print(f"[ERROR] 批量获取 {code} 净值失败: {e}")

    return jsonify({"navs": results, "errors": errors})


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


@app.route("/api/analysis/compare", methods=["POST"])
def analysis_compare():
    """基金对比：接受多个基金代码，返回各基金核心指标矩阵"""
    data = request.get_json(force=True)
    codes = data.get("codes", [])
    if not codes or not isinstance(codes, list):
        return jsonify({"error": "请提供基金代码列表"}), 400
    if len(codes) < 2:
        return jsonify({"error": "至少选择 2 只基金进行对比"}), 400
    if len(codes) > 10:
        return jsonify({"error": "最多对比 10 只基金"}), 400

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=min(len(codes), 5)) as executor:
        future_map = {executor.submit(_get_analysis, code): code for code in codes}
        for future in as_completed(future_map, timeout=60):
            code = future_map[future]
            try:
                result, err = future.result()
                if err:
                    errors.append({"code": code, "error": err})
                elif result:
                    # 提取核心对比指标
                    ind = result.get("indicators", {})
                    sig = result.get("signals", {})
                    sc = result.get("score", {})
                    results.append({
                        "code": result["code"],
                        "name": result["name"],
                        "type": result.get("type", ""),
                        "annual_return": ind.get("annual_return"),
                        "annual_volatility": ind.get("annual_volatility"),
                        "max_drawdown": ind.get("max_drawdown"),
                        "sharpe_ratio": ind.get("sharpe_ratio"),
                        "sortino_ratio": ind.get("sortino_ratio"),
                        "calmar_ratio": ind.get("calmar_ratio"),
                        "return_1m": ind.get("return_1m"),
                        "return_3m": ind.get("return_3m"),
                        "return_1y": ind.get("return_1y"),
                        "rsi": sig.get("rsi", {}).get("value") if isinstance(sig.get("rsi"), dict) else None,
                        "rsi_signal": sig.get("rsi", {}).get("signal") if isinstance(sig.get("rsi"), dict) else None,
                        "total_score": sc.get("total_score"),
                        "level": sc.get("level"),
                        "action": sc.get("action"),
                        "stars": sc.get("stars"),
                    })
            except Exception as e:
                errors.append({"code": code, "error": str(e)[:100]})

    return jsonify({
        "results": sorted(results, key=lambda x: -(x.get("total_score") or 0)),
        "errors": errors,
        "count": len(results),
    })


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
    return _build_portfolio_response(force)


def _calc_dca_xirr(holding: dict, nav_df, current_total: float) -> float | None:
    """从定投持仓数据计算 XIRR 真实年化收益率

    根据 dca_start_date / dca_amount / dca_frequency 生成现金流序列，
    调用 calc_xirr 计算年化收益率。

    返回:
        float: 年化收益率百分比（如 9.53 = 9.53%）
        None: 数据不足以计算
    """
    dca_start = holding.get("dca_start_date")
    dca_amount = holding.get("dca_amount")
    dca_freq = holding.get("dca_frequency")
    dca_end = holding.get("dca_end_date")
    if not dca_start or not dca_amount or not dca_freq or nav_df.empty:
        return None
    if current_total <= 0:
        return None

    from datetime import date as date_type
    from fund_analysis import calc_xirr

    today_str = date_type.today().isoformat()
    end_str = dca_end[:10] if dca_end else today_str

    # 获取净值数据中的交易日（按日期升序）
    nav = nav_df[["日期", "单位净值"]].copy()
    nav["日期"] = nav["日期"].astype(str).str[:10]
    nav = nav[(nav["日期"] >= dca_start[:10]) & (nav["日期"] <= end_str)]
    if nav.empty:
        return None

    # 按频率选择定投日期
    if dca_freq == "daily":
        dca_dates = nav["日期"].tolist()[:-2] if len(nav) > 2 else []  # QDII T+2
    elif dca_freq == "weekly":
        dca_dates = nav["日期"].iloc[::5].tolist()
    elif dca_freq == "monthly":
        seen_months = set()
        dca_dates = []
        for d in nav["日期"]:
            m = d[:7]
            if m not in seen_months:
                seen_months.add(m)
                dca_dates.append(d)
    else:
        return None

    cashflows = []
    for d in dca_dates:
        cashflows.append((d, -dca_amount))

    # 初始投入（dca_initial 字段），放在第一个定投日
    dca_initial = holding.get("dca_initial", 0) or 0
    if dca_initial > 0.01 and dca_dates:
        cashflows[0] = (cashflows[0][0], cashflows[0][1] - dca_initial)

    # 当前市值作为最后一项（正现金流）
    cashflows.append((today_str, current_total))

    if len(cashflows) < 2:
        return None

    xirr_val = calc_xirr(cashflows)
    if xirr_val is not None:
        return round(xirr_val * 100, 2)  # 转为百分比
    return None


def _build_portfolio_response(force=False):
    """构建持仓响应数据（供 portfolio_list 和 dashboard 共用）"""
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

        # XIRR：仅定投基金计算
        xirr_val = None
        if h.get("dca_start_date"):
            xirr_val = _calc_dca_xirr(h, nav_df, current_total)

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
            "xirr": xirr_val,
            "daily_profit": daily_profit,
            "daily_return_pct": daily_return_pct,
            "added_at": h["added_at"],
            "notes": h["notes"],
            "total_invested": h.get("total_invested"),
            "dca_start_date": h.get("dca_start_date"),
            "dca_amount": h.get("dca_amount"),
            "dca_frequency": h.get("dca_frequency"),
            "dca_end_date": h.get("dca_end_date"),
            "dca_initial": h.get("dca_initial"),
        })
    return jsonify({"holdings": results})


@app.route("/api/portfolio/dashboard", methods=["GET"])
@login_required
def portfolio_dashboard():
    """聚合仪表盘数据：持仓 + 汇总统计（一次返回，减少前端请求）"""
    force = request.args.get("force", "").lower() == "true"
    holdings = get_all_holdings(request.current_user['user_id'])

    results = []
    total_value = 0
    total_cost = 0
    total_daily = 0

    for h in holdings:
        nav_df = get_fund_nav(h["code"], force_refresh=force)
        latest_nav = float(nav_df["单位净值"].iloc[-1]) if not nav_df.empty else 0
        nav_vals = nav_df["单位净值"].values if not nav_df.empty else []
        yesterday_nav = float(nav_vals[-2]) if len(nav_vals) >= 2 else latest_nav
        cost_total = h["shares"] * h["cost_nav"]
        current_total = h["shares"] * latest_nav
        yesterday_total = h["shares"] * yesterday_nav
        daily_profit = round(current_total - yesterday_total, 2)
        daily_return_pct = round((latest_nav - yesterday_nav) / yesterday_nav * 100, 2) if yesterday_nav > 0 else 0

        total_value += current_total
        total_cost += cost_total
        total_daily += daily_profit

        # XIRR：仅定投基金计算
        xirr_val = None
        if h.get("dca_start_date"):
            xirr_val = _calc_dca_xirr(h, nav_df, current_total)

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
            "xirr": xirr_val,
            "daily_profit": daily_profit,
            "daily_return_pct": daily_return_pct,
            "added_at": h["added_at"],
            "notes": h["notes"],
            "total_invested": h.get("total_invested"),
            "dca_start_date": h.get("dca_start_date"),
            "dca_amount": h.get("dca_amount"),
            "dca_frequency": h.get("dca_frequency"),
            "dca_end_date": h.get("dca_end_date"),
            "dca_initial": h.get("dca_initial"),
        })

    total_profit = round(total_value - total_cost, 2)
    total_pct = round(total_profit / total_cost * 100, 2) if total_cost > 0 else 0

    return jsonify({
        "holdings": results,
        "summary": {
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": total_profit,
            "total_return_pct": total_pct,
            "total_daily_profit": round(total_daily, 2),
            "fund_count": len(results),
        },
        "codes": [h["code"] for h in results if h.get("dca_start_date")],
    })


@app.route("/api/portfolio/history")
@login_required
def portfolio_history():
    """组合历史市值曲线：按持仓份额回溯各日期的组合总市值
    
    查询参数:
        period: 1m|3m|6m|1y|all（默认 1y）
    """
    period = request.args.get("period", "1y")
    period_days = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}.get(period, 9999)
    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"dates": [], "portfolioValues": [], "totalInvested": 0, "totalCost": 0})

    # 总投入成本
    total_invested = sum(h["shares"] * h["cost_nav"] for h in holdings)

    # 并行拉取所有基金历史净值
    nav_map = {}
    with ThreadPoolExecutor(max_workers=min(len(holdings), 10)) as executor:
        future_map = {executor.submit(get_fund_nav, h["code"]): h for h in holdings}
        try:
            for future in as_completed(future_map, timeout=60):
                h = future_map[future]
                try:
                    df = future.result(timeout=0)
                    if not df.empty and "日期" in df.columns and "单位净值" in df.columns:
                        nav_map[h["code"]] = df[["日期", "单位净值"]].copy()
                except Exception:
                    continue
        except FutureTimeout:
            pass

    if not nav_map:
        return jsonify({"dates": [], "portfolioValues": [], "totalInvested": round(total_invested, 2), "totalCost": round(total_invested, 2)})

    # 构建统一日期索引（所有基金的净值日期的并集，降序）
    all_dates = set()
    for code, df in nav_map.items():
        for d in df["日期"]:
            all_dates.add(str(d)[:10])
    all_dates = sorted(all_dates, reverse=True)  # 最新在前
    # 按 period 截取
    if period_days < len(all_dates):
        all_dates = all_dates[:period_days]

    # 构建每只基金的 {日期→净值} 映射
    nav_dict = {}
    for code, df in nav_map.items():
        m = {}
        for _, row in df.iterrows():
            m[str(row["日期"])[:10]] = float(row["单位净值"])
        nav_dict[code] = m

    # 逐日期计算组合市值：对每个日期，取每只基金在该日或之前最新的净值 × 份额
    portfolio_values = []
    # 缓存每只基金最近找到的净值
    latest_nav_cache = {code: None for code in nav_map}

    for d in all_dates:
        total_val = 0.0
        for h in holdings:
            code = h["code"]
            if code not in nav_dict:
                continue
            nav_map_code = nav_dict[code]
            # 当前日期有净值就用，否则沿用最近的
            nav_val = nav_map_code.get(d)
            if nav_val is not None:
                latest_nav_cache[code] = nav_val
            elif latest_nav_cache[code] is None:
                # 向前搜索第一个可用净值（最坏情况：遍历所有日期）
                for dd in sorted(nav_map_code.keys()):
                    if dd <= d:
                        latest_nav_cache[code] = nav_map_code[dd]
                        nav_val = nav_map_code[dd]
                        break
                if nav_val is None:
                    continue
            else:
                nav_val = latest_nav_cache[code]
            total_val += h["shares"] * nav_val
        portfolio_values.append(round(total_val, 2))

    # 结果按日期升序（从旧到新，方便画图）
    all_dates.reverse()
    portfolio_values.reverse()

    return jsonify({
        "dates": all_dates,
        "portfolioValues": portfolio_values,
        "totalInvested": round(total_invested, 2),
        "totalCost": round(total_invested, 2),
    })


@app.route("/api/portfolio/signals")
@login_required
def portfolio_signals():
    """所有持仓的技术信号汇总 + 告警"""
    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"signals": [], "alerts": []})

    signals_result = []
    alerts = []

    for h in holdings:
        nav_df = get_fund_nav(h["code"])
        if nav_df.empty:
            continue
        sig = calc_signals(nav_df)
        ind = calc_indicators(nav_df)
        if "error" in sig:
            continue

        summary = sig.get("summary", [])
        rsi = sig.get("rsi", {})
        macd = sig.get("macd", {})
        ma = sig.get("ma", {})

        entry = {
            "code": h["code"],
            "name": h["name"],
            "rsi_value": rsi.get("value"),
            "rsi_signal": rsi.get("signal", ""),
            "macd_signal": macd.get("signal", ""),
            "ma_status": ma.get("status", ""),
            "signals": summary,
            "daily_change": None,
        }
        signals_result.append(entry)

        # 检查告警条件
        nav = nav_df["单位净值"].values
        if len(nav) >= 2:
            daily_chg = (nav[-1] - nav[-2]) / nav[-2] * 100
            entry["daily_change"] = round(daily_chg, 2)
            if daily_chg < -3:
                alerts.append({
                    "code": h["code"],
                    "name": h["name"],
                    "type": "大跌",
                    "message": f"{h['name']} 今日大跌 {daily_chg:.1f}%",
                    "severity": "danger",
                })
            elif daily_chg < -2:
                alerts.append({
                    "code": h["code"],
                    "name": h["name"],
                    "type": "下跌",
                    "message": f"{h['name']} 今日下跌 {daily_chg:.1f}%",
                    "severity": "warning",
                })
        # RSI 超卖/超买
        rsi_val = rsi.get("value")
        if rsi_val is not None:
            if rsi_val < 30:
                alerts.append({
                    "code": h["code"],
                    "name": h["name"],
                    "type": "RSI超卖",
                    "message": f"{h['name']} RSI {rsi_val:.0f}，进入超卖区间",
                    "severity": "info",
                })
            elif rsi_val > 70:
                alerts.append({
                    "code": h["code"],
                    "name": h["name"],
                    "type": "RSI超买",
                    "message": f"{h['name']} RSI {rsi_val:.0f}，进入超买区间",
                    "severity": "warning",
                })

    return jsonify({
        "signals": signals_result,
        "alerts": alerts,
    })


@app.route("/api/portfolio/risk")
@login_required
def portfolio_risk():
    """组合风险指标（VaR / 波动率 / 回撤）"""
    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"error": "暂无持仓"})

    nav_dfs = []
    for h in holdings:
        df = get_fund_nav(h["code"])
        if not df.empty:
            nav_dfs.append(df)

    if len(nav_dfs) < 1:
        return jsonify({"error": "净值数据不足"})

    weights = [1.0 / len(nav_dfs)] * len(nav_dfs)
    risk = calc_portfolio_var(nav_dfs, weights)

    # 风险分解：每只基金对组合的贡献
    breakdown = []
    total_vol = risk.get("volatility", 0)
    for i, h in enumerate(holdings):
        df = get_fund_nav(h["code"])
        if df.empty:
            continue
        nav = df["单位净值"].values
        rets = np.diff(nav) / nav[:-1]
        vol = float(np.std(rets, ddof=1) * np.sqrt(252)) * 100 if len(rets) > 1 else 0
        weight_pct = round(100.0 / len(holdings), 1)
        risk_contrib = round(vol * weight_pct / 100, 2) if total_vol > 0 else 0
        breakdown.append({
            "code": h["code"],
            "name": h["name"],
            "weight": weight_pct,
            "volatility": round(vol, 2),
            "risk_contribution": risk_contrib,
        })
    breakdown.sort(key=lambda x: -x["risk_contribution"])

    return jsonify({
        "risk": risk,
        "breakdown": breakdown,
    })


@app.route("/api/portfolio/excess-return")
@login_required
def portfolio_excess_return():
    """持仓 vs 沪深300 超额收益"""
    from datetime import date
    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"excess_return": None, "error": "暂无持仓"})

    try:
        index_df = get_index_data("000300")  # 沪深300
        if index_df.empty:
            return jsonify({"excess_return": None, "error": "获取指数数据失败"})
    except Exception as e:
        return jsonify({"excess_return": None, "error": str(e)[:100]})

    # 计算组合每日收益率
    portfolio_daily_returns = {}
    for h in holdings:
        nav_df = get_fund_nav(h["code"])
        if nav_df.empty or "单位净值" not in nav_df.columns:
            continue
        nav = nav_df[["日期", "单位净值"]].copy()
        nav["日收益"] = nav["单位净值"].pct_change()
        for _, row in nav.iterrows():
            d = str(row["日期"])[:10]
            ret = row["日收益"]
            if pd.notna(ret):
                weight = h["shares"] * float(nav[nav["日期"] == row["日期"]]["单位净值"].iloc[0]) if not nav.empty else 0
                # 简化：等权重
                portfolio_daily_returns.setdefault(d, []).append(float(ret))

    # 取每日均值作为组合日收益
    port_dates = sorted(portfolio_daily_returns.keys())
    if not port_dates:
        return jsonify({"excess_return": None, "error": "净值数据不足"})

    # 指数收益率
    idx = index_df[["日期", "收盘"]].copy()
    idx["指数日收益"] = idx["收盘"].pct_change()
    idx_map = {}
    for _, row in idx.iterrows():
        d = str(row["日期"])[:10]
        idx_map[d] = float(row["指数日收益"]) if pd.notna(row["指数日收益"]) else 0

    # 超额收益
    cum_port = 1.0
    cum_idx = 1.0
    total_excess = 0.0
    daily_excess = []
    for d in port_dates:
        port_ret = sum(portfolio_daily_returns[d]) / len(portfolio_daily_returns[d])
        idx_ret = idx_map.get(d, 0)
        excess = port_ret - idx_ret
        cum_port *= (1 + port_ret)
        cum_idx *= (1 + idx_ret)
        total_excess += excess
        daily_excess.append({
            "date": d,
            "portfolio_return": round(port_ret * 100, 4),
            "index_return": round(idx_ret * 100, 4),
            "excess_return": round(excess * 100, 4),
            "cumulative_excess": round((cum_port - cum_idx) * 100, 4),
        })

    cumulative_excess_pct = round((cum_port - cum_idx) * 100, 2)

    return jsonify({
        "total_excess_pct": cumulative_excess_pct,
        "portfolio_return_pct": round((cum_port - 1) * 100, 2),
        "index_return_pct": round((cum_idx - 1) * 100, 2),
        "daily": daily_excess[-252:] if len(daily_excess) > 252 else daily_excess,
    })


@app.route("/api/portfolio/export")
@login_required
def portfolio_export():
    """导出持仓数据为 CSV"""
    import csv
    import io

    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"error": "暂无持仓"}), 404

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["基金代码", "基金名称", "可用份额", "成本净值", "最新净值",
                      "持仓成本", "持仓市值", "累计收益", "收益率%",
                      "昨日收益", "日收益率%", "累计投入", "定投状态",
                      "添加时间", "备注"])

    for h in holdings:
        nav_df = get_fund_nav(h["code"])
        latest_nav = float(nav_df["单位净值"].iloc[-1]) if not nav_df.empty else 0
        nav_vals = nav_df["单位净值"].values if not nav_df.empty else []
        yesterday_nav = float(nav_vals[-2]) if len(nav_vals) >= 2 else latest_nav
        cost_total = round(h["shares"] * h["cost_nav"], 2)
        current_total = round(h["shares"] * latest_nav, 2)
        profit = round(current_total - cost_total, 2)
        return_pct = round(profit / cost_total * 100, 2) if cost_total > 0 else 0
        daily_profit = round(current_total - h["shares"] * yesterday_nav, 2)
        daily_pct = round((latest_nav - yesterday_nav) / yesterday_nav * 100, 2) if yesterday_nav > 0 else 0

        is_dca = h.get("total_invested") is not None
        dca_status = ""
        if is_dca:
            if h.get("dca_end_date"):
                dca_status = f"已终止(至{h['dca_end_date'][:10]})"
            else:
                dca_status = f"定投中({h.get('dca_frequency','')} ¥{h.get('dca_amount','')})"

        writer.writerow([
            h["code"], h["name"], h["shares"], h["cost_nav"], latest_nav,
            cost_total, current_total, profit, return_pct,
            daily_profit, daily_pct, h.get("total_invested") or cost_total, dca_status,
            h["added_at"][:10], h.get("notes", ""),
        ])

    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=fund_portfolio.csv",
            "Content-Type": "text/csv; charset=utf-8-sig",
        }
    )


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
    dca_initial = data.get("dca_initial")
    holding_id = add_holding(request.current_user['user_id'], code, name, shares, cost_nav, notes, total_invested, dca_start_date, dca_amount, dca_frequency, dca_end_date, dca_initial)
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
    dca_initial = data.get("dca_initial")
    ok = update_holding(holding_id, request.current_user['user_id'], shares, cost_nav, notes, total_invested, dca_start_date, dca_amount, dca_frequency, dca_end_date, dca_initial)
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


@app.route("/api/portfolio/<int:holding_id>/sync-dca", methods=["POST"])
@login_required
def portfolio_sync_dca(holding_id: int):
    """同步定投数据：前端算好份额和累计投入后，写入数据库"""
    holding = get_holding(holding_id, request.current_user['user_id'])
    if not holding:
        return jsonify({"error": "持仓不存在"}), 404
    if not holding.get("dca_start_date"):
        return jsonify({"error": "该持仓非定投模式"}), 400

    data = request.get_json(force=True)
    shares = data.get("shares")
    total_invested = data.get("total_invested")
    cost_nav = data.get("cost_nav")

    if shares is None or total_invested is None:
        return jsonify({"error": "缺少 shares 或 total_invested"}), 400
    if shares <= 0 or total_invested <= 0:
        return jsonify({"error": "份额和投入金额必须大于 0"}), 400

    dca_initial = data.get("dca_initial")
    ok = update_holding(holding_id, request.current_user['user_id'],
                        shares=shares, total_invested=total_invested, cost_nav=cost_nav,
                        dca_initial=dca_initial)
    return jsonify({"synced": ok, "shares": shares, "total_invested": total_invested, "cost_nav": cost_nav, "dca_initial": dca_initial}), 200 if ok else 304


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


# ====== 交易流水（v2）======


@app.route("/api/transactions", methods=["GET"])
@login_required
def api_get_transactions():
    """获取交易记录列表，可选 ?fund_code=xxx 筛选"""
    fund_code = request.args.get("fund_code", "").strip() or None
    txs = get_transactions(request.current_user["user_id"], fund_code)
    return jsonify({"transactions": txs})


@app.route("/api/transactions", methods=["POST"])
@login_required
def api_add_transaction():
    """添加一笔交易记录（买入/卖出/分红）"""
    data = request.get_json(force=True)
    fund_code = (data.get("fund_code") or "").strip()
    tx_type = (data.get("type") or "").strip()
    shares = float(data.get("shares", 0))
    price = float(data.get("price", 0))
    tx_date = (data.get("tx_date") or "").strip()
    note = (data.get("note") or "").strip()

    if not fund_code or tx_type not in ("buy", "sell", "dividend"):
        return jsonify({"error": "参数无效"}), 400
    if shares <= 0 or price <= 0:
        return jsonify({"error": "份额和价格必须大于0"}), 400

    amount = round(shares * price, 2)
    fee = float(data.get("fee", 0))

    # 自动补全基金名称
    info = get_fund_info(fund_code)
    fund_name = info.get("fund_name", fund_code) if info else fund_code

    tx_id = add_transaction(
        user_id=request.current_user["user_id"],
        fund_code=fund_code,
        fund_name=fund_name,
        tx_type=tx_type,
        shares=shares,
        price=price,
        amount=amount,
        tx_date=tx_date,
        fee=fee,
        note=note,
    )
    return jsonify({"id": tx_id, "fund_name": fund_name}), 201


@app.route("/api/transactions/<int:tx_id>", methods=["DELETE"])
@login_required
def api_delete_transaction(tx_id: int):
    """删除交易记录"""
    ok = delete_transaction(tx_id, request.current_user["user_id"])
    return jsonify({"deleted": ok}), 200 if ok else 404


# ====== 自选列表 ======


@app.route("/api/watchlist", methods=["GET"])
@login_required
def api_get_watchlist():
    """获取自选列表（附最新净值）"""
    items = get_watchlist(request.current_user["user_id"])
    results = []
    for w in items:
        nav_df = get_fund_nav(w["code"])
        current_nav = float(nav_df["单位净值"].iloc[-1]) if not nav_df.empty else None
        nav_vals = nav_df["单位净值"].values if not nav_df.empty else []
        yesterday_nav = float(nav_vals[-2]) if len(nav_vals) >= 2 else current_nav
        daily_change = round((current_nav - yesterday_nav) / yesterday_nav * 100, 2) if current_nav and yesterday_nav else None
        results.append({
            "id": w["id"],
            "code": w["code"],
            "name": w["name"],
            "fund_type": w.get("fund_type", ""),
            "current_nav": current_nav,
            "daily_change": daily_change,
            "target_price": w.get("target_price"),
            "alert_enabled": bool(w.get("alert_enabled")),
            "notes": w.get("notes", ""),
            "added_at": w["added_at"],
        })
    return jsonify({"watchlist": results})


@app.route("/api/watchlist", methods=["POST"])
@login_required
def api_add_watchlist():
    """添加自选"""
    data = request.get_json(force=True)
    code = (data.get("code") or "").strip()
    notes = (data.get("notes") or "").strip()
    target_price = data.get("target_price")
    if target_price is not None:
        target_price = float(target_price)
    if not code:
        return jsonify({"error": "基金代码不能为空"}), 400
    # 自动补全信息
    info = get_fund_info(code)
    name = info.get("fund_name", code) if info else code
    fund_type = info.get("fund_type", "") if info else ""
    result = add_watchlist(request.current_user["user_id"], code, name, fund_type, notes, target_price)
    status = 200 if result.get("exists") else 201
    return jsonify(result), status


@app.route("/api/watchlist/<int:watch_id>", methods=["DELETE"])
@login_required
def api_delete_watchlist(watch_id: int):
    """删除自选"""
    ok = delete_watchlist(watch_id, request.current_user["user_id"])
    return jsonify({"deleted": ok}), 200 if ok else 404


@app.route("/api/watchlist/<int:watch_id>", methods=["PUT"])
@login_required
def api_update_watchlist(watch_id: int):
    """更新自选备注/提醒价"""
    data = request.get_json(force=True)
    notes = data.get("notes")
    target_price = data.get("target_price")
    alert_enabled = data.get("alert_enabled")
    if target_price is not None:
        target_price = float(target_price)
    ok = update_watchlist(watch_id, request.current_user["user_id"], notes, target_price, alert_enabled)
    return jsonify({"updated": ok}), 200 if ok else 304


@app.route("/api/portfolio/holdings")
@login_required
def api_portfolio_holdings_v2():
    """从交易流水汇总持仓（v2 版本，替代旧的 /api/portfolio）"""
    user_id = request.current_user["user_id"]
    holdings = get_holdings_from_transactions(user_id)
    if not holdings:
        return jsonify({"holdings": [], "summary": {}})

    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = []
    total_value = 0
    total_cost = 0

    cashflows_all = []  # 用于组合级 XIRR
    nav_data_cache = {}

    for h in holdings:
        code = h["fund_code"]
        nav_df = get_fund_nav(code)
        if nav_df.empty:
            continue
        latest_nav = float(nav_df["单位净值"].iloc[-1])
        current_total = round(h["total_shares"] * latest_nav, 2)
        cost_total = round(h["net_cost"], 2)
        profit = round(current_total - cost_total, 2)
        return_pct = round(profit / cost_total * 100, 2) if cost_total > 0 else 0
        total_value += current_total
        total_cost += cost_total

        # 获取该基金的交易流水用于单基金 XIRR
        txs = get_transactions(user_id, code)
        tx_cashflows = []
        for tx in txs:
            if tx["type"] == "buy":
                tx_cashflows.append((tx["tx_date"], -tx["amount"]))
            elif tx["type"] == "sell":
                tx_cashflows.append((tx["tx_date"], tx["amount"]))
        # 加入当前市值作为虚拟卖出
        tx_cashflows.append((date.today().isoformat(), current_total))
        xirr_val = calc_xirr(tx_cashflows)

        results.append({
            "code": code,
            "name": h["fund_name"],
            "shares": round(h["total_shares"], 2),
            "cost_nav": round(cost_total / h["total_shares"], 4) if h["total_shares"] > 0 else 0,
            "current_nav": latest_nav,
            "cost_total": cost_total,
            "current_total": current_total,
            "profit": profit,
            "return_pct": return_pct,
            "xirr": round(xirr_val * 100, 2) if xirr_val is not None else None,
            "tx_count": h["tx_count"],
            "last_tx_date": h["last_tx_date"],
        })

        # 收集组合级现金流
        for tx in txs:
            if tx["type"] == "buy":
                cashflows_all.append((tx["tx_date"], -tx["amount"]))
            elif tx["type"] == "sell":
                cashflows_all.append((tx["tx_date"], tx["amount"]))

    # 组合级 XIRR：加入总市值作为虚拟卖出
    cashflows_all.append((date.today().isoformat(), total_value))
    portfolio_xirr = calc_xirr(cashflows_all)

    total_profit = round(total_value - total_cost, 2)
    total_pct = round(total_profit / total_cost * 100, 2) if total_cost > 0 else 0

    return jsonify({
        "holdings": results,
        "summary": {
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_profit": total_profit,
            "total_return_pct": total_pct,
            "portfolio_xirr": round(portfolio_xirr * 100, 2) if portfolio_xirr is not None else None,
            "fund_count": len(results),
        },
    })


# ====== 旧持仓兼容层（无交易流水时自动迁移）======


def _migrate_old_holdings(user_id: int):
    """如果旧 holdings 表有数据但 transactions 表为空，自动迁移"""
    old = get_all_holdings(user_id)
    if not old:
        return
    existing_tx = get_transactions(user_id)
    if existing_tx:
        return  # 已有交易流水，不重复迁移
    print(f"[迁移] 为用户 {user_id} 将 {len(old)} 条旧持仓转为交易记录")
    for h in old:
        add_transaction(
            user_id=user_id,
            fund_code=h["code"],
            fund_name=h["name"],
            tx_type="buy",
            shares=h["shares"],
            price=h["cost_nav"],
            amount=h["shares"] * h["cost_nav"],
            tx_date=h["added_at"][:10],
            note="迁移自旧持仓",
        )
        # 如果有定投数据，补推定投交易
        if h.get("dca_start_date") and h.get("dca_amount") and h.get("total_invested"):
            import math
            dca_shares = h["dca_amount"] / h["cost_nav"] if h["cost_nav"] > 0 else 0
            # 补推定投期数（简化：平均到日期区间）
            total_invested = h["total_invested"] or 0
            extra_invested = max(0, total_invested - h["shares"] * h["cost_nav"])
            if extra_invested > 0:
                add_transaction(
                    user_id=user_id,
                    fund_code=h["code"],
                    fund_name=h["name"],
                    tx_type="buy",
                    shares=extra_invested / h["cost_nav"] if h["cost_nav"] > 0 else 0,
                    price=h["cost_nav"],
                    amount=extra_invested,
                    tx_date=h["dca_start_date"][:10],
                    note="DCA迁移（估算）",
                )
    print(f"[迁移] 完成")


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


# ====== Webhook 自动部署（Gitee / GitHub 通用）======
# 去重缓存：记录已处理过的 commit ID，防止 Gitee 重试导致重复邮件
_deployed_commits = set()


@app.route("/api/deploy", methods=["POST"])
def deploy_webhook():
    """接收 Git Webhook，自动 git pull + docker compose up -d --build"""
    expected = os.environ.get("WEBHOOK_SECRET", "")
    actual = request.headers.get("X-Gitee-Token", request.headers.get("X-Hub-Signature-256", ""))
    if not expected or not actual or actual != expected:
        return jsonify({"error": "未授权"}), 403

    body = request.get_json(silent=True) or {}
    ref = body.get("ref", "")
    if ref != "refs/heads/master":
        return jsonify({"message": f"跳过非 master 分支"})

    project_dir = os.environ.get("PROJECT_DIR", os.path.dirname(BASE_DIR))
    commit_msg = body.get("head_commit", {}).get("message", "")
    author_name = body.get("head_commit", {}).get("author", {}).get("name", "")
    commit_id = body.get("head_commit", {}).get("id", "")

    # Gitee 重试去重：同一 commit 只处理一次
    if commit_id and commit_id in _deployed_commits:
        return jsonify({"message": "重复 webhook，已跳过"})

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
        if commit_id:
            _deployed_commits.add(commit_id)
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


# 定时清理去重缓存（每2小时清一次，防止内存泄漏）
def _cleanup_deployed_cache():
    global _deployed_commits
    _deployed_commits.clear()


# ====== 每日报告定时调度 ======

_scheduler_running = False
_last_report_date = None  # 防止同一天重复发送


def _is_fund_updated_today(code: str) -> bool:
    """检查单只基金今日净值是否已更新（最新一条数据的日期是否为今天）"""
    try:
        nav_df = get_fund_nav(code, force_refresh=True)
        if nav_df.empty:
            return False
        latest_date = str(nav_df["日期"].iloc[-1])
        return latest_date == date.today().isoformat()
    except Exception as e:
        print(f"[调度器] 检查基金 {code} 净值更新时出错: {e}")
        return False


def _wait_for_all_funds_updated(holdings, max_wait_minutes=180, check_interval=60):
    """
    等待所有基金今日净值更新完毕，再继续发送邮件。

    工作方式：
    1. 逐个检查每只基金的最新净值日期是否为今天
    2. 未更新的基金每隔 check_interval 秒重试
    3. 超过 max_wait_minutes 分钟则超时返回（仍会发送邮件，兜底）

    参数:
        holdings: 持仓列表
        max_wait_minutes: 最大等待分钟数（默认 180 分钟 = 3 小时，到 23:00）
        check_interval: 每次重试间隔（秒，默认 60 秒）

    返回:
        bool: True 表示全部更新完毕, False 表示超时
    """
    codes = [h["code"] for h in holdings]
    if not codes:
        return True

    start_time = time.time()
    deadline = start_time + max_wait_minutes * 60
    pending = set(codes)

    print(f"[调度器] 开始检测基金净值更新状态: {', '.join(sorted(pending))}")

    while time.time() < deadline:
        still_pending = set()
        for code in pending:
            if _is_fund_updated_today(code):
                print(f"[调度器] ✅ 基金 {code} 今日净值已更新")
            else:
                still_pending.add(code)

        if not still_pending:
            print("[调度器] 🎉 所有基金今日净值已全部更新完毕")
            return True

        pending = still_pending
        remaining = max(int(deadline - time.time()), 0)
        print(f"[调度器] ⏳ 以下基金尚未更新: {', '.join(sorted(pending))}，"
              f"剩余等待时间 {remaining // 60} 分钟")
        time.sleep(min(check_interval, remaining + 1))

    not_updated = ', '.join(sorted(pending))
    print(f"[调度器] ⚠️ 等待超时（{max_wait_minutes} 分钟），以下基金仍未更新: {not_updated}")
    return False


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
                        # 🔄 先等待所有基金今日净值更新完毕，再组装数据发送
                        print(f"[调度器] 等待所有基金更新今日净值...")
                        _wait_for_all_funds_updated(holdings)

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
    """启动定时任务"""
    # 每日报告
    if DAILY_REPORT_EMAIL:
        t = threading.Thread(target=_daily_report_scheduler, daemon=True)
        t.start()
        print(f"[调度器] 每日报告已启动，计划时间 {DAILY_REPORT_TIME}")
    else:
        print("[调度器] DAILY_REPORT_EMAIL 未设置，跳过")

    # 每2小时清理 webhook 去重缓存
    def _cleanup_loop():
        while True:
            time.sleep(7200)
            _deployed_commits.clear()
    threading.Thread(target=_cleanup_loop, daemon=True).start()


# ====== 市场指数 ======


# ====== 基金筛选 ======


@app.route("/api/funds/screen")
def fund_screen():
    """基金筛选与排行"""
    fund_type = request.args.get("type")
    sort_by = request.args.get("sort_by", "近1年")
    order = request.args.get("order", "desc")
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    keyword = request.args.get("keyword", "")
    try:
        data = screen_funds(
            fund_type=fund_type, sort_by=sort_by, order=order,
            page=page, page_size=page_size, keyword=keyword
        )
        return jsonify(data)
    except Exception as e:
        return jsonify({"total": 0, "page": page, "page_size": page_size, "funds": [], "error": str(e)[:200]})


# ====== 持仓穿透分析 ======


@app.route("/api/portfolio/penetration")
@login_required
def portfolio_penetration():
    """持仓穿透：按基金类型分布"""
    holdings = get_all_holdings(request.current_user['user_id'])
    if not holdings:
        return jsonify({"type_distribution": [], "fund_details": [], "total_value": 0, "total_count": 0})

    fund_details = []
    type_values = {}
    total_value = 0

    for h in holdings:
        nav_df = get_fund_nav(h["code"])
        current_nav = float(nav_df["单位净值"].iloc[-1]) if not nav_df.empty else 0
        value = round(h["shares"] * current_nav, 2)
        total_value += value

        info = get_fund_info(h["code"])
        fund_type = info.get("fund_type", "未知") if info else "未知"

        fund_details.append({
            "code": h["code"],
            "name": h["name"],
            "type": fund_type,
            "value": value,
            "proportion": 0,
        })

        if fund_type not in type_values:
            type_values[fund_type] = {"count": 0, "total_value": 0}
        type_values[fund_type]["count"] += 1
        type_values[fund_type]["total_value"] += value

    for fd in fund_details:
        fd["proportion"] = round(fd["value"] / total_value * 100, 2) if total_value > 0 else 0

    type_distribution = [
        {
            "type": ft,
            "count": data["count"],
            "total_value": round(data["total_value"], 2),
            "proportion": round(data["total_value"] / total_value * 100, 2) if total_value > 0 else 0,
        }
        for ft, data in type_values.items()
    ]
    type_distribution.sort(key=lambda x: x["proportion"], reverse=True)

    return jsonify({
        "type_distribution": type_distribution,
        "fund_details": fund_details,
        "total_value": round(total_value, 2),
        "total_count": len(holdings),
    })


# ====== 定投测算 ======


@app.route("/api/dca/project", methods=["POST"])
def dca_project():
    """定投收益测算"""
    data = request.get_json(force=True)
    fund_code = data.get("fund_code", "")
    monthly_amount = float(data.get("monthly_amount", 0))
    months = int(data.get("months", 0))
    expected_return = float(data.get("expected_annual_return", 8))

    if not fund_code or monthly_amount <= 0 or months <= 0:
        return jsonify({"error": "参数无效"}), 400

    monthly_rate = expected_return / 12 / 100
    total_principal = round(monthly_amount * months, 2)

    if monthly_rate > 0:
        estimated_total = round(monthly_amount * ((1 + monthly_rate) ** months - 1) / monthly_rate, 2)
    else:
        estimated_total = total_principal

    estimated_profit = round(estimated_total - total_principal, 2)

    schedule = []
    for i in range(1, min(months, 12) + 1):
        accumulated_principal = round(monthly_amount * i, 2)
        if monthly_rate > 0:
            accumulated_total = round(monthly_amount * ((1 + monthly_rate) ** i - 1) / monthly_rate, 2)
        else:
            accumulated_total = accumulated_principal
        schedule.append({
            "month": i,
            "contribution": monthly_amount,
            "accumulated_principal": accumulated_principal,
            "accumulated_total": accumulated_total,
        })

    return jsonify({
        "monthly_amount": monthly_amount,
        "months": months,
        "expected_return_pct": expected_return,
        "total_principal": total_principal,
        "estimated_total": estimated_total,
        "estimated_profit": estimated_profit,
        "schedule": schedule,
    })


# ====== AI 对话 ======

# 导入分析引擎
from fund_analysis import calc_indicators, calc_signals, calc_score


@app.route("/api/ai/chat", methods=["POST"])
@login_required
def ai_chat():
    """专业 AI 基金分析助手（SSE 流式）"""
    data = request.get_json(force=True)
    message = (data.get("message") or "").strip()
    history = data.get("history", [])

    if not DEEPSEEK_API_KEY:
        return jsonify({"error": "请先配置 DeepSeek API Key"}), 400

    if not message:
        return jsonify({"error": "请输入消息"}), 400

    user_id = request.current_user['user_id']

    def generate():
        # ====== 第 1 步：立即发送 keep-alive，防止 Nginx 504 ======
        yield f"data: {json_module.dumps({'status': 'started'})}\n\n"

        try:
            # ====== 第 2 步：获取持仓数据（在 keep-alive 之后，Nginx 已知连接存活）======
            holdings = get_all_holdings(user_id)
            fund_details = []
            total_value = 0
            total_cost = 0

            if not holdings:
                portfolio_context = "当前无持仓数据"
            else:
                nav_futures = {}
                with ThreadPoolExecutor(max_workers=min(len(holdings), 5)) as executor:
                    for h in holdings:
                        nav_futures[executor.submit(get_fund_nav, h["code"])] = h

                    try:
                        for future in as_completed(nav_futures, timeout=30):
                            h = nav_futures[future]
                            try:
                                nav_df = future.result(timeout=0)
                            except Exception as e:
                                print(f"[WARN] 获取基金 {h['code']} 净值异常（已跳过）: {e}")
                                continue

                            if nav_df.empty:
                                continue

                            current_nav = float(nav_df["单位净值"].iloc[-1])
                            value = round(h["shares"] * current_nav, 2)
                            cost_total_holding = round(h["shares"] * h["cost_nav"], 2)
                            profit = round(value - cost_total_holding, 2)
                            profit_pct = round(profit / cost_total_holding * 100, 2) if cost_total_holding > 0 else 0
                            total_value += value
                            total_cost += cost_total_holding

                            info = get_fund_info(h["code"])
                            managers = get_fund_manager(h["code"])
                            indicators = calc_indicators(nav_df)
                            signals = calc_signals(nav_df)
                            score = calc_score(indicators, signals) if "error" not in indicators and "error" not in signals else {}
                            top_holdings_data = get_fund_holdings(h["code"])

                            fund_details.append({
                                "code": h["code"],
                                "name": h["name"],
                                "shares": h["shares"],
                                "cost_nav": h["cost_nav"],
                                "current_nav": current_nav,
                                "value": value,
                                "cost_total": cost_total_holding,
                                "profit": profit,
                                "profit_pct": profit_pct,
                                "weight_pct": 0,
                                "fund_type": info.get("fund_type", ""),
                                "fund_size": info.get("fund_size", ""),
                                "manager_name": info.get("manager", ""),
                                "establish_date": info.get("establish_date", ""),
                                "indicators": indicators,
                                "signals": signals,
                                "score": score,
                                "managers": managers,
                                "top_holdings": [th.get("stock_name", "") for th in top_holdings_data[:5] if th.get("stock_name")],
                            })
                    except FutureTimeout:
                        print("[WARN] 部分基金净值获取超过 30s，已跳过未完成项")

            # ====== 第 3 步：计算组合指标 ======
            for fd in fund_details:
                fd["weight_pct"] = round(fd["value"] / total_value * 100, 2) if total_value > 0 else 0

            total_profit = round(total_value - total_cost, 2)
            total_profit_pct = round(total_profit / total_cost * 100, 2) if total_cost > 0 else 0

            type_dist = {}
            for fd in fund_details:
                t = fd["fund_type"] or "未知"
                type_dist[t] = type_dist.get(t, 0) + fd["weight_pct"]

            sorted_by_weight = sorted(fund_details, key=lambda x: x["weight_pct"], reverse=True)
            top3 = round(sum(f["weight_pct"] for f in sorted_by_weight[:3]), 2)
            top5 = round(sum(f["weight_pct"] for f in sorted_by_weight[:5]), 2)
            gainers = sorted(fund_details, key=lambda x: x["profit_pct"], reverse=True)
            losers = sorted(fund_details, key=lambda x: x["profit_pct"])
            avg_score = round(
                sum(f["score"].get("total_score", 50) * f["weight_pct"] for f in fund_details if f["score"])
                / max(sum(f["weight_pct"] for f in fund_details if f["score"]), 1), 1
            ) if fund_details else 0

            # ====== 第 4 步：构建 System Prompt ======
            sections = [f"""【组合总览】
总市值: {round(total_value, 2)} 元
总成本: {round(total_cost, 2)} 元
累计盈亏: {total_profit} 元 ({total_profit_pct}%)
持仓数量: {len(fund_details)} 只
组合评分: {avg_score}/100
集中度: 前3持仓占比 {top3}%, 前5占比 {top5}%
最佳表现: {gainers[0]['name'] + '(' + str(gainers[0]['profit_pct']) + '%)' if gainers else '无'}
最差表现: {losers[0]['name'] + '(' + str(losers[0]['profit_pct']) + '%)' if losers else '无'}"""]

            type_lines = [f"  {t}: {pct}%" for t, pct in sorted(type_dist.items(), key=lambda x: -x[1])]
            sections.append("【持仓类型分布】\n" + "\n".join(type_lines))

            fund_lines = []
            for fd in fund_details:
                ind = fd["indicators"]
                sig = fd["signals"]
                sco = fd["score"]
                lines = [
                    f"基金: {fd['name']}({fd['code']})",
                    f"  类型: {fd['fund_type']} | 规模: {fd['fund_size']} | 经理: {fd['manager_name']}",
                    f"  仓位占比: {fd['weight_pct']}% | 市值: {fd['value']} | 盈亏: {fd['profit']} ({fd['profit_pct']}%)",
                ]
                if "error" not in ind:
                    lines.append(f"  年化收益: {ind.get('annual_return', 'N/A')}% | 年化波动: {ind.get('annual_volatility', 'N/A')}%")
                    lines.append(f"  最大回撤: {ind.get('max_drawdown', 'N/A')}% | 夏普比率: {ind.get('sharpe_ratio', 'N/A')}")
                    lines.append(f"  近1月: {ind.get('return_1m', 'N/A')}% | 近3月: {ind.get('return_3m', 'N/A')}% | 近1年: {ind.get('return_1y', 'N/A')}%")
                if "error" not in sig:
                    lines.append(f"  RSI: {sig.get('rsi', {}).get('value', 'N/A')} ({sig.get('rsi', {}).get('signal', '')})")
                    lines.append(f"  MACD: {sig.get('macd', {}).get('signal', 'N/A')} | 均线: {sig.get('ma', {}).get('status', '')}")
                if sco:
                    lines.append(f"  综合评分: {sco.get('total_score', 'N/A')}/100 ({sco.get('level', '')}) | 建议: {sco.get('action', '')}")
                if fd["top_holdings"]:
                    lines.append(f"  前5重仓: {'/'.join(fd['top_holdings'])}")
                if fd["managers"]:
                    mgr = fd["managers"][0]
                    lines.append(f"  基金经理: {mgr.get('name', '')} 任职回报: {mgr.get('return_rate', 'N/A')}")
                fund_lines.append("\n".join(lines))
            sections.append("【持仓明细分析】\n" + "\n".join(fund_lines))

            if fund_details:
                portfolio_context = "\n\n".join(sections)

            system_prompt = f"""你是资深基金投资顾问，基于用户持仓数据提供专业分析。

{portfolio_context}

## 回复要求
- 先给一句话核心结论，再展开分析
- 用 Markdown 表格对比各基金关键指标
- 建议必须量化（如"建议仓位降至10%"）
- 总长度控制在 30 行以内
- 不预测未来涨跌，不推荐具体股票"""

            # ====== 第 5 步：构建消息列表 ======
            messages = [{"role": "system", "content": system_prompt}]
            for h in history[-10:]:
                role = h.get("role", "user")
                if role == "ai":       # DeepSeek 要求 "assistant" 而非 "ai"
                    role = "assistant"
                messages.append({"role": role, "content": h.get("content", "")})
            messages.append({"role": "user", "content": message})

            # ====== 第 6 步：调用 DeepSeek 流式 API ======
            url = "https://api.deepseek.com/v1/chat/completions"
            req_headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            }
            req_body = json_module.dumps({
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 4000,
                "stream": True,
            }).encode("utf-8")

            req = urllib.request.Request(url, data=req_body, headers=req_headers, method="POST")

            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    if resp.status != 200:
                        error_body = resp.read().decode("utf-8", errors="replace")[:500]
                        print(f"[ERROR] DeepSeek API HTTP {resp.status}: {error_body}")
                        yield f"data: {json_module.dumps({'error': f'AI 服务异常 (HTTP {resp.status})'})}\n\n"
                        return

                    for line in resp:
                        line = line.decode("utf-8").strip()
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            yield "data: [DONE]\n\n"
                            break
                        try:
                            chunk = json_module.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield f"data: {json_module.dumps({'content': content})}\n\n"
                        except json_module.JSONDecodeError:
                            continue
            except urllib.error.HTTPError as e:
                error_body = ""
                try:
                    error_body = e.read().decode("utf-8", errors="replace")[:500]
                except Exception:
                    pass
                print(f"[ERROR] DeepSeek API HTTP {e.code}: {error_body}")
                yield f"data: {json_module.dumps({'error': f'AI 服务异常 (HTTP {e.code})'})}\n\n"
            except urllib.error.URLError as e:
                print(f"[ERROR] DeepSeek API 连接失败: {e.reason}")
                yield f"data: {json_module.dumps({'error': 'AI 服务连接失败'})}\n\n"
            except Exception as e:
                print(f"[ERROR] DeepSeek API 调用失败: {e}")
                yield f"data: {json_module.dumps({'error': 'AI 服务调用失败'})}\n\n"

        except Exception as e:
            print(f"[ERROR] AI 对话处理异常: {e}")
            yield f"data: {json_module.dumps({'error': 'AI 服务异常，请稍后重试'})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    print(f"基金范围后端启动 http://127.0.0.1:{port}  debug={debug}")
    start_scheduler()
    app.run(host="0.0.0.0", port=port, debug=debug)
