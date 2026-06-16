"""
基金范围 — 分析引擎

提供基金关键指标计算、技术信号分析、多因子评分。
输入：历史净值 DataFrame（需包含 '单位净值' 列，日期升序）
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

# -------- 常量 --------
RISK_FREE_RATE = 0.025  # 无风险利率 2.5%
TRADING_DAYS = 252       # 年化交易日


# -------- XIRR 真实年化收益率 --------


def calc_xirr(cashflows: list) -> float | None:
    """
    计算 XIRR（年化内部收益率）

    参数:
        cashflows: [(date_str, amount), ...]
           买入为负值（支出），卖出为正值（收入），当前市值为正（最后一天虚拟卖出）

    返回:
        float: 年化收益率（小数，如 0.083 = 8.3%）
        None: 数据不足或计算失败
    """
    if len(cashflows) < 2:
        return None

    try:
        from pyxirr import xirr
        dates = [row[0] if isinstance(row[0], str) else row[0].isoformat() for row in cashflows]
        amounts = [float(row[1]) for row in cashflows]
        result = xirr(dates, amounts)
        return float(result) if result is not None else None
    except ImportError:
        pass  # 降级到手动计算
    except Exception:
        pass

    # 手动二分法计算 XIRR（降级方案）
    # 目标是解 NPV = Σ(CF_i / (1+r)^(days_i/365)) = 0
    import datetime

    today = datetime.date.today()
    parsed_dates = []
    for row in cashflows:
        if isinstance(row[0], str):
            d = datetime.date.fromisoformat(row[0][:10])
        else:
            d = row[0]
        parsed_dates.append(d)

    amounts = [float(row[1]) for row in cashflows]

    def npv(rate):
        total = 0.0
        for i, d in enumerate(parsed_dates):
            days = (today - d).days
            total += amounts[i] / ((1 + rate) ** (days / 365.0))
        return total

    # 二分法搜索
    lo, hi = -0.99, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        try:
            v = npv(mid)
        except (OverflowError, ZeroDivisionError):
            return None
        if abs(v) < 1e-7:
            return mid
        if v > 0:
            lo = mid
        else:
            hi = mid

    return None


# -------- 指标计算 --------


def calc_indicators(nav_df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算基金关键指标

    参数:
        nav_df: 包含 '单位净值' 列的 DataFrame，按日期升序

    返回:
        dict: {
            annual_return, annual_volatility, max_drawdown,
            sharpe_ratio, sortino_ratio, calmar_ratio,
            alpha, beta, latest_nav, data_count, start_date, end_date
        }
    """
    if nav_df.empty or "单位净值" not in nav_df.columns:
        return {"error": "数据不足"}

    nav = nav_df["单位净值"].values
    dates = nav_df["日期"].values if "日期" in nav_df.columns else None

    n = len(nav)
    if n < 2:
        return {"error": "数据不足"}

    # 日收益率
    daily_ret = np.diff(nav) / nav[:-1]

    # 年化收益率
    years = n / TRADING_DAYS
    annual_return = (nav[-1] / nav[0]) ** (1 / years) - 1 if years > 0 else 0

    # 年化波动率
    annual_volatility = float(np.std(daily_ret, ddof=1) * np.sqrt(TRADING_DAYS))

    # 最大回撤
    rolling_max = np.maximum.accumulate(nav)
    drawdowns = (rolling_max - nav) / rolling_max
    max_drawdown = float(np.max(drawdowns))

    # 夏普比率
    sharpe_ratio = (annual_return - RISK_FREE_RATE) / annual_volatility if annual_volatility > 0 else 0

    # 索提诺比率
    downside_ret = daily_ret[daily_ret < 0]
    downside_std = float(np.std(downside_ret, ddof=1) * np.sqrt(TRADING_DAYS)) if len(downside_ret) > 1 else 0.01
    sortino_ratio = (annual_return - RISK_FREE_RATE) / downside_std if downside_std > 0 else 0

    # 卡玛比率
    calmar_ratio = annual_return / max_drawdown if max_drawdown > 0 else 0

    # 近 N 月收益率
    def period_return(months: int) -> Optional[float]:
        days = months * 21  # 约 21 交易日/月
        if n > days:
            return float(nav[-1] / nav[-1 - days] - 1)
        return None

    result = {
        "annual_return": round(float(annual_return) * 100, 2),
        "annual_volatility": round(float(annual_volatility) * 100, 2),
        "max_drawdown": round(float(max_drawdown) * 100, 2),
        "sharpe_ratio": round(float(sharpe_ratio), 2),
        "sortino_ratio": round(float(sortino_ratio), 2),
        "calmar_ratio": round(float(calmar_ratio), 2),
        "return_1m": round(period_return(1) * 100, 2) if period_return(1) is not None else None,
        "return_3m": round(period_return(3) * 100, 2) if period_return(3) is not None else None,
        "return_6m": round(period_return(6) * 100, 2) if period_return(6) is not None else None,
        "return_1y": round(period_return(12) * 100, 2) if period_return(12) is not None else None,
        "latest_nav": round(float(nav[-1]), 4),
        "data_count": n,
        "start_date": str(dates[0]) if dates is not None else "",
        "end_date": str(dates[-1]) if dates is not None else "",
    }

    # Alpha / Beta 使用沪深300真实数据
    alpha_beta = _calc_alpha_beta(nav, nav_df)
    result.update(alpha_beta)

    return result


def _calc_alpha_beta(nav: np.ndarray, nav_df: pd.DataFrame) -> Dict[str, float]:
    """计算 Alpha 和 Beta（使用沪深300真实数据）"""
    try:
        from fund_data import get_index_data
        index_df = get_index_data("000300")
        if index_df.empty or "日期" not in index_df.columns or "收盘" not in index_df.columns:
            return {"alpha": None, "beta": None}

        # 构建指数日收益映射 {日期: 收益率}
        idx = index_df[["日期", "收盘"]].copy()
        idx["指数日收益"] = idx["收盘"].pct_change()
        idx_map = {}
        for _, row in idx.iterrows():
            d = str(row["日期"])[:10]
            idx_map[d] = float(row["指数日收益"]) if pd.notna(row["指数日收益"]) else None

        # 对齐基金和指数的日期，计算日收益率
        dates = nav_df["日期"].values if "日期" in nav_df.columns else None
        if dates is None or len(dates) < 10:
            return {"alpha": None, "beta": None}

        fund_rets = []
        market_rets = []
        prev_nav = None
        for i in range(len(nav)):
            d = str(dates[i])[:10]
            if d in idx_map and idx_map[d] is not None:
                if prev_nav is not None and prev_nav > 0:
                    fund_ret = nav[i] / prev_nav - 1
                    fund_rets.append(fund_ret)
                    market_rets.append(idx_map[d])
                prev_nav = nav[i]

        if len(fund_rets) < 10:
            return {"alpha": None, "beta": None}

        fund_arr = np.array(fund_rets)
        market_arr = np.array(market_rets)

        cov = np.cov(fund_arr, market_arr)[0, 1]
        var_market = np.var(market_arr)
        beta = cov / var_market if var_market > 0 else 1.0

        fund_avg = np.mean(fund_arr)
        market_avg = np.mean(market_arr)
        rf_daily = RISK_FREE_RATE / TRADING_DAYS
        alpha = (fund_avg - rf_daily) - beta * (market_avg - rf_daily)

        return {
            "alpha": round(float(alpha) * TRADING_DAYS * 100, 2),  # 年化 Alpha
            "beta": round(float(beta), 2),
        }
    except ImportError:
        pass
    except Exception as e:
        print(f"[WARN] Alpha/Beta 计算失败: {e}")
    return {"alpha": None, "beta": None}


# -------- 技术信号 --------


def calc_signals(nav_df: pd.DataFrame) -> Dict[str, Any]:
    """
    计算技术信号

    返回:
        dict: { ma_status, rsi, macd, bollinger, signals_list }
    """
    if nav_df.empty or "单位净值" not in nav_df.columns:
        return {"error": "数据不足"}

    nav = nav_df["单位净值"].values
    n = len(nav)
    if n < 60:
        return {"error": f"数据不足60个交易日（当前{n}天）"}

    close = pd.Series(nav)

    # ---- 均线 ----
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    current = close.iloc[-1]

    if current > ma5 > ma20 > ma60:
        ma_status = "多头排列"
        ma_direction = "up"
    elif current < ma5 < ma20 < ma60:
        ma_status = "空头排列"
        ma_direction = "down"
    else:
        ma_status = "缠绕"
        ma_direction = "neutral"

    # ---- RSI (14日) ----
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50

    if rsi_val < 30:
        rsi_signal = "超卖"
        rsi_type = "down"
    elif rsi_val > 70:
        rsi_signal = "超买"
        rsi_type = "up"
    else:
        rsi_signal = "中性"
        rsi_type = "neutral"

    # ---- MACD (12/26/9) ----
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    macd_val = 2 * (dif - dea)

    macd_current = float(macd_val.iloc[-1]) if not np.isnan(macd_val.iloc[-1]) else 0
    macd_prev = float(macd_val.iloc[-2]) if len(macd_val) > 1 and not np.isnan(macd_val.iloc[-2]) else 0

    if macd_current > 0 and macd_prev <= 0:
        macd_signal = "金叉"
        macd_type = "up"
    elif macd_current < 0 and macd_prev >= 0:
        macd_signal = "死叉"
        macd_type = "down"
    elif macd_current > 0:
        macd_signal = "多头"
        macd_type = "up"
    elif macd_current < 0:
        macd_signal = "空头"
        macd_type = "down"
    else:
        macd_signal = "粘合"
        macd_type = "neutral"

    # ---- 布林带 (20日, 2σ) ----
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    bb_current = float(bb_mid.iloc[-1]) if not np.isnan(bb_mid.iloc[-1]) else current
    bb_upper_val = float(bb_upper.iloc[-1]) if not np.isnan(bb_upper.iloc[-1]) else current
    bb_lower_val = float(bb_lower.iloc[-1]) if not np.isnan(bb_lower.iloc[-1]) else current

    if current >= bb_upper_val:
        bb_signal = "上轨压力"
        bb_type = "up"
    elif current <= bb_lower_val:
        bb_signal = "下轨支撑"
        bb_type = "down"
    elif current > bb_current:
        bb_signal = "中轨上方"
        bb_type = "up"
    elif current < bb_current:
        bb_signal = "中轨下方"
        bb_type = "down"
    else:
        bb_signal = "中轨附近"
        bb_type = "neutral"

    return {
        "ma": {"value": f"5日{ma5:.3f} / 20日{ma20:.3f} / 60日{ma60:.3f}", "status": ma_status, "direction": ma_direction},
        "rsi": {"value": round(rsi_val, 1), "signal": rsi_signal, "type": rsi_type},
        "macd": {"value": round(macd_current, 4), "signal": macd_signal, "type": macd_type},
        "bollinger": {"upper": round(bb_upper_val, 3), "mid": round(bb_current, 3), "lower": round(bb_lower_val, 3), "signal": bb_signal, "type": bb_type},
        "summary": [
            {"label": f"RSI {rsi_val:.0f} {rsi_signal}", "type": rsi_type},
            {"label": f"MACD {macd_signal} {'↑' if macd_type=='up' else '↓' if macd_type=='down' else '—'}", "type": macd_type},
            {"label": f"均线 {ma_status} {'↑' if ma_direction=='up' else '↓' if ma_direction=='down' else '—'}", "type": ma_direction},
            {"label": f"布林带 {bb_signal}", "type": bb_type},
        ],
    }


# -------- 多因子评分 --------


def calc_score(indicators: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    多因子综合评分

    权重:
        收益能力 30%: 年化收益、近1年收益、近6月收益
        风控能力 25%: 最大回撤、年化波动率
        性价比 20%: 夏普比率、索提诺比率、卡玛比率
        技术面 15%: 均线、MACD、RSI、布林带
        稳定性 10%: 数据量覆盖

    返回:
        dict: { total_score, dimensions, level, level_stars, action }
    """
    # 各维度评分（0-100）
    score_return = _score_return(indicators)
    score_risk = _score_risk(indicators)
    score_value = _score_value(indicators)
    score_technical = _score_technical(signals)
    score_stability = _score_stability(indicators)

    total = (
        score_return * 0.30
        + score_risk * 0.25
        + score_value * 0.20
        + score_technical * 0.15
        + score_stability * 0.10
    )
    total = round(total)

    # 等级
    if total >= 90:
        level, stars, action = "优质", "⭐⭐⭐⭐⭐", "强烈推荐买入"
    elif total >= 70:
        level, stars, action = "良好", "⭐⭐⭐⭐", "推荐买入"
    elif total >= 50:
        level, stars, action = "一般", "⭐⭐⭐", "观望 / 定投"
    elif total >= 30:
        level, stars, action = "较差", "⭐⭐", "建议减仓"
    else:
        level, stars, action = "差质", "⭐", "建议卖出"

    return {
        "total_score": total,
        "level": level,
        "stars": stars,
        "action": action,
        "dimensions": {
            "收益能力": {"score": score_return, "weight": "30%"},
            "风控能力": {"score": score_risk, "weight": "25%"},
            "性价比": {"score": score_value, "weight": "20%"},
            "技术面": {"score": score_technical, "weight": "15%"},
            "稳定性": {"score": score_stability, "weight": "10%"},
        },
    }


def _score_return(ind: Dict[str, Any]) -> int:
    """收益能力评分"""
    score = 50
    ann = ind.get("annual_return", 0) or 0
    r1y = ind.get("return_1y") or ind.get("return_6m") or 0
    if ann > 20:
        score += 30
    elif ann > 10:
        score += 20
    elif ann > 5:
        score += 10
    elif ann < -10:
        score -= 20
    elif ann < -5:
        score -= 10
    if r1y and r1y > 0:
        score += 10
    return max(0, min(100, score))


def _score_risk(ind: Dict[str, Any]) -> int:
    """风控能力评分"""
    score = 50
    dd = abs(ind.get("max_drawdown", 0) or 0)
    vol = ind.get("annual_volatility", 0) or 0
    if dd < 10:
        score += 25
    elif dd < 20:
        score += 15
    elif dd < 30:
        score += 5
    elif dd > 40:
        score -= 15
    if vol < 15:
        score += 15
    elif vol < 25:
        score += 5
    elif vol > 35:
        score -= 10
    return max(0, min(100, score))


def _score_value(ind: Dict[str, Any]) -> int:
    """性价比评分"""
    score = 50
    sharpe = ind.get("sharpe_ratio", 0) or 0
    calmar = ind.get("calmar_ratio", 0) or 0
    if sharpe > 1.5:
        score += 25
    elif sharpe > 1.0:
        score += 15
    elif sharpe > 0.5:
        score += 5
    elif sharpe < 0:
        score -= 15
    if calmar > 1:
        score += 15
    elif calmar > 0.5:
        score += 5
    elif calmar < 0:
        score -= 10
    return max(0, min(100, score))


def _score_technical(signals: Dict[str, Any]) -> int:
    """技术面评分"""
    if "error" in signals:
        return 50
    score = 50
    # 均线方向
    ma_dir = signals.get("ma", {}).get("direction", "neutral")
    if ma_dir == "up":
        score += 15
    elif ma_dir == "down":
        score -= 10
    # MACD
    macd_type = signals.get("macd", {}).get("type", "neutral")
    if macd_type == "up":
        score += 15
    elif macd_type == "down":
        score -= 10
    # RSI
    rsi_type = signals.get("rsi", {}).get("type", "neutral")
    if rsi_type == "down":
        score += 5  # 超卖反弹机会
    elif rsi_type == "up":
        score -= 5  # 超买回调风险
    return max(0, min(100, score))


def _score_stability(ind: Dict[str, Any]) -> int:
    """稳定性评分（数据覆盖度）"""
    n = ind.get("data_count", 0)
    if n > 1000:
        return 90
    elif n > 500:
        return 80
    elif n > 200:
        return 70
    elif n > 60:
        return 50
    else:
        return 30


# -------- 组合风险指标 --------


def calc_portfolio_var(nav_df_list: list[pd.DataFrame], weights: list[float],
                       confidence: float = 0.95) -> dict:
    """
    计算组合 VaR（历史模拟法）

    参数:
        nav_df_list: 每只基金的净值 DataFrame 列表（含 '单位净值' 列）
        weights: 每只基金的市值权重
        confidence: 置信度，默认 95%

    返回:
        dict: { daily_var, annual_var, daily_cvar, max_drawdown, current_drawdown, volatility }
    """
    if not nav_df_list or not weights or len(nav_df_list) != len(weights):
        return {"error": "参数无效"}

    # 计算每只基金的日收益率序列，对齐日期
    daily_rets = []
    common_dates = None

    for df in nav_df_list:
        if df.empty or "单位净值" not in df.columns:
            continue
        d = df[["日期", "单位净值"]].copy()
        d["ret"] = d["单位净值"].pct_change()
        d = d.dropna()
        if common_dates is None:
            common_dates = set(d["日期"].values)
        else:
            common_dates = common_dates & set(d["日期"].values)

    if not common_dates or len(common_dates) < 5:
        return {"error": "数据不足"}

    # 构建组合日收益率
    portfolio_rets = []
    for df in nav_df_list:
        if df.empty or "单位净值" not in df.columns:
            continue
        d = df[["日期", "单位净值"]].copy()
        d["ret"] = d["单位净值"].pct_change()
        d = d[d["日期"].isin(common_dates)].dropna()
        if not d.empty:
            portfolio_rets.append(d["ret"].values[:len(common_dates)])

    if not portfolio_rets:
        return {"error": "数据不足"}

    # 等权组合日收益率
    n_funds = len(portfolio_rets)
    min_len = min(len(r) for r in portfolio_rets)
    combined_ret = np.zeros(min_len)
    for r in portfolio_rets:
        combined_ret += r[:min_len] / n_funds

    # VaR (历史模拟法)
    sorted_rets = np.sort(combined_ret)
    var_idx = int(len(sorted_rets) * (1 - confidence))
    daily_var = float(sorted_rets[var_idx]) if var_idx < len(sorted_rets) else 0.0

    # CVaR (低于 VaR 的均值)
    cvar_vals = sorted_rets[:var_idx + 1]
    daily_cvar = float(np.mean(cvar_vals)) if len(cvar_vals) > 0 else daily_var

    # 年化
    annual_var = daily_var * np.sqrt(252)
    annual_vol = float(np.std(combined_ret, ddof=1) * np.sqrt(252))

    # 最大回撤
    cum = np.cumprod(1 + combined_ret)
    running_max = np.maximum.accumulate(cum)
    drawdown = (cum - running_max) / running_max
    max_dd = float(np.min(drawdown)) if len(drawdown) > 0 else 0.0
    current_dd = float(drawdown[-1]) if len(drawdown) > 0 else 0.0

    # 夏普
    sharpe = (np.mean(combined_ret) * 252 - RISK_FREE_RATE) / annual_vol if annual_vol > 0 else 0

    return {
        "daily_var_95": round(daily_var * 100, 2),
        "annual_var_95": round(annual_var * 100, 2),
        "daily_cvar_95": round(daily_cvar * 100, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "current_drawdown": round(current_dd * 100, 2),
        "volatility": round(annual_vol * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "data_days": min_len,
    }
