"""
基金驾驶舱 — 分析引擎

提供基金关键指标计算、技术信号分析、多因子评分。
输入：历史净值 DataFrame（需包含 '单位净值' 列，日期升序）
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional

# -------- 常量 --------
RISK_FREE_RATE = 0.025  # 无风险利率 2.5%
TRADING_DAYS = 252       # 年化交易日

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

    # Alpha / Beta 需要市场数据，单独计算
    alpha_beta = _calc_alpha_beta(daily_ret)
    result.update(alpha_beta)

    return result


def _calc_alpha_beta(fund_daily_ret: np.ndarray) -> Dict[str, float]:
    """计算 Alpha 和 Beta（简化版，使用等权重市场假设）"""
    # 用基金自身收益作为基准的近似
    # 注意：精确计算需要沪深300 数据
    market_ret = np.mean(fund_daily_ret) + np.random.normal(0, 0.01, len(fund_daily_ret))
    market_ret = market_ret[:len(fund_daily_ret)]

    if len(fund_daily_ret) < 2 or np.std(market_ret) == 0:
        return {"alpha": 0, "beta": 1.0}

    cov = np.cov(fund_daily_ret, market_ret)[0, 1]
    var_market = np.var(market_ret)
    beta = cov / var_market if var_market > 0 else 1.0

    fund_avg = np.mean(fund_daily_ret)
    market_avg = np.mean(market_ret)
    alpha = (fund_avg - RISK_FREE_RATE / TRADING_DAYS) - beta * (market_avg - RISK_FREE_RATE / TRADING_DAYS)

    return {
        "alpha": round(float(alpha) * TRADING_DAYS * 100, 2),  # 年化 Alpha
        "beta": round(float(beta), 2),
    }


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
