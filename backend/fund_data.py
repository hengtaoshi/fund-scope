"""
基金范围 — akshare 数据层

提供基金数据获取接口，含本地缓存机制。
所有请求遵守低频规则（间隔 ≥ 1 秒）。
"""
import os
import json
import time
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from config import CACHE_DIR, CACHE_EXPIRE_HOURS, AKSHARE_INTERVAL

_last_request_time = 0

def _rate_limit():
    """请求频率限制"""
    global _last_request_time
    now = time.time()
    gap = now - _last_request_time
    if gap < AKSHARE_INTERVAL:
        time.sleep(AKSHARE_INTERVAL - gap)
    _last_request_time = time.time()

def _cache_path(code: str, data_type: str) -> str:
    """缓存文件路径"""
    return os.path.join(CACHE_DIR, f"{code}_{data_type}.json")

def _is_cache_valid(path: str) -> bool:
    """判断缓存是否在有效期内"""
    if not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return datetime.now() - mtime < timedelta(hours=CACHE_EXPIRE_HOURS)

def get_fund_nav(code: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    获取基金历史净值（日线）

    参数:
        code: 基金代码，如 "005827"
        force_refresh: 强制刷新缓存

    返回:
        DataFrame: columns = ['日期', '单位净值', '累计净值', '日增长率']
    """
    cache_path = _cache_path(code, "nav")

    if not force_refresh and _is_cache_valid(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return pd.DataFrame(data)

    _rate_limit()
    try:
        df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
        # 统一列名
        col_map = {"净值日期": "日期", "单位净值": "单位净值", "日增长率": "日增长率"}
        df = df.rename(columns=col_map)
        df["累计净值"] = df["单位净值"]
        # 日期转字符串
        df["日期"] = df["日期"].astype(str)
        # 缓存
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, default=str)
        return df
    except Exception as e:
        print(f"[ERROR] 获取基金净值失败 {code}: {e}")
        return pd.DataFrame()


def get_fund_info(code: str, force_refresh: bool = False) -> dict:
    """
    获取基金基本信息（雪球数据源）

    返回:
        dict: { fund_name, fund_code, fund_type, establish_date, fund_size, manager }
    """
    cache_path = _cache_path(code, "info")

    if not force_refresh and _is_cache_valid(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    _rate_limit()
    try:
        df = ak.fund_individual_basic_info_xq(symbol=code)
        info = {}
        for _, row in df.iterrows():
            info[row["item"]] = str(row["value"])
        result = {
            "fund_name": info.get("基金名称", ""),
            "fund_code": code,
            "fund_type": info.get("基金类型", ""),
            "establish_date": info.get("成立时间", ""),
            "fund_size": info.get("最新规模", ""),
            "manager": info.get("基金经理", ""),
        }
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
        return result
    except Exception as e:
        print(f"[ERROR] 获取基金信息失败 {code}: {e}")
        return {}


def get_fund_manager(code: str, force_refresh: bool = False) -> list:
    """
    获取基金经理信息

    返回:
        list[dict]: [{ name, start_date, return_rate }, ...]
    """
    cache_path = _cache_path(code, "manager")

    if not force_refresh and _is_cache_valid(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    _rate_limit()
    try:
        # fund_manager_em() 返回全量经理数据，按基金代码筛选
        all_managers = ak.fund_manager_em()
        # 查找包含该基金代码的经理记录
        df = all_managers[all_managers["现任基金代码"] == code].copy()
        managers = []
        for _, row in df.iterrows():
            managers.append({
                "name": row.get("姓名", ""),
                "start_date": row.get("任职日期", ""),
                "return_rate": row.get("任职回报", ""),
            })
        if not managers:
            # 降级：从基金基本信息中获取经理姓名
            info = get_fund_info(code)
            name = info.get("manager", "").split()[0] if info.get("manager") else ""
            if name:
                managers.append({"name": name, "start_date": "", "return_rate": ""})

        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(managers, f, ensure_ascii=False)
        return managers
    except Exception as e:
        print(f"[ERROR] 获取基金经理信息失败 {code}: {e}")
        return []


def search_fund(keyword: str) -> list:
    """
    搜索基金

    参数:
        keyword: 基金代码或名称关键词

    返回:
        list[dict]: [{ code, name, type }]
    """
    _rate_limit()
    try:
        df = ak.fund_name_em()
        mask = df["基金代码"].str.contains(keyword, na=False) | df["基金简称"].str.contains(keyword, na=False)
        results = df[mask].head(10)
        return results.rename(columns={
            "基金代码": "code", "基金简称": "name", "基金类型": "type"
        })[["code", "name", "type"]].to_dict(orient="records")
    except Exception as e:
        print(f"[ERROR] 搜索基金失败: {e}")
        return []


def get_index_data(code: str = "000300", force_refresh: bool = False) -> pd.DataFrame:
    """
    获取指数历史数据（默认沪深300）
    """
    cache_path = _cache_path(f"index_{code}", "nav")
    if not force_refresh and _is_cache_valid(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return pd.DataFrame(data) if data else pd.DataFrame()

    _rate_limit()
    try:
        symbol = f"sh{code}" if code.startswith("0") else f"sz{code}"
        df = ak.stock_zh_index_daily_em(symbol=symbol)
        if df.empty:
            return pd.DataFrame()
        if "date" in df.columns:
            df = df.rename(columns={"date": "日期"})
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, default=str)
        return df
    except Exception as e:
        print(f"[ERROR] 获取指数 {code} 数据失败: {e}")
        return pd.DataFrame()


def _safe_float(val):
    """安全转换为 float，处理 None/NaN/空字符串"""
    if val is None:
        return None
    try:
        v = float(val)
        return None if (isinstance(v, float) and v != v) else v  # NaN check
    except (ValueError, TypeError):
        return None


def get_index_valuation(force_refresh: bool = False) -> list:
    """
    获取主要指数估值数据

    参数:
        force_refresh: 强制刷新缓存

    返回:
        list[dict]: [{ code, name, current_value, change_pct, pe_ratio, pb_ratio, price_percentile, status }]
    """
    indices = [
        ("sh000001", "上证指数"),
        ("sz399001", "深证成指"),
        ("sh000300", "沪深300"),
        ("sh000905", "中证500"),
        ("sz399006", "创业板指"),
        ("sh000688", "科创50"),
    ]
    results = []
    for code, name in indices:
        cache_path = _cache_path(code, "index_daily")
        df = None

        if not force_refresh and _is_cache_valid(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                df = pd.DataFrame(data)
            except Exception:
                pass

        if df is None:
            _rate_limit()
            try:
                df = ak.stock_zh_index_daily_em(symbol=code)
                os.makedirs(CACHE_DIR, exist_ok=True)
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, default=str)
            except Exception as e:
                print(f"[ERROR] 获取指数数据失败 {code}: {e}")
                results.append({
                    "code": code, "name": name, "current_value": None,
                    "change_pct": None, "pe_ratio": None, "pb_ratio": None,
                    "price_percentile": None, "status": "未知",
                })
                continue

        if df is not None and not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date")

            latest = df.iloc[-1]
            current_value = float(latest["close"])

            # 涨跌幅手工计算
            prev_close = float(df.iloc[-2]["close"]) if len(df) >= 2 else current_value
            change_pct = round((current_value - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0

            # 5 年历史百分位
            five_years_ago = df["date"].max() - pd.Timedelta(days=365 * 5)
            window = df[df["date"] >= five_years_ago]["close"].values

            if len(window) > 1:
                count_le = (window <= current_value).sum()
                percentile = round(count_le / len(window) * 100, 1)

                if percentile < 20:
                    status = "低估"
                elif percentile < 50:
                    status = "适中"
                elif percentile < 80:
                    status = "偏高"
                else:
                    status = "过热"
            else:
                percentile = None
                status = "未知"

            results.append({
                "code": code,
                "name": name,
                "current_value": current_value,
                "change_pct": change_pct,
                "pe_ratio": None,
                "pb_ratio": None,
                "price_percentile": percentile,
                "status": status,
            })

    return results


def screen_funds(fund_type: str = None, sort_by: str = "近1年", order: str = "desc",
                  page: int = 1, page_size: int = 20, keyword: str = "") -> dict:
    """
    筛选基金（排行数据缓存 1 小时）

    参数:
        fund_type: 基金类型筛选
        sort_by: 排序列（近1周/近1月/近3月/近6月/近1年/近2年/近3年）
        order: asc / desc
        page: 页码
        page_size: 每页条数
        keyword: 基金代码/名称关键词

    返回:
        dict: { total, page, page_size, funds: [{ code, name, type, nav, accum_nav, return_1w, ... }] }
    """
    cache_path = _cache_path("fund_rank", "screen")
    df = None

    # 自定义 1 小时缓存检查（覆盖默认 4 小时）
    if os.path.exists(cache_path):
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(cache_path))
            if datetime.now() - mtime < timedelta(hours=1):
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                df = pd.DataFrame(data)
        except Exception:
            pass

    if df is None:
        _rate_limit()
        try:
            df = ak.fund_open_fund_rank_em()
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"[ERROR] 获取基金排名失败: {e}")
            return {"total": 0, "page": page, "page_size": page_size, "funds": []}

    if df.empty:
        return {"total": 0, "page": page, "page_size": page_size, "funds": []}

    # 获取基金类型映射
    type_map = {}
    try:
        _rate_limit()
        name_df = ak.fund_name_em()
        for _, row in name_df.iterrows():
            type_map[str(row["基金代码"])] = row.get("基金类型", "")
    except Exception as e:
        print(f"[ERROR] 获取基金类型信息失败: {e}")

    # 确保代码为字符串
    df["基金代码"] = df["基金代码"].astype(str)

    # 关键词筛选
    if keyword:
        mask = df["基金代码"].str.contains(keyword, na=False) | df["基金简称"].str.contains(keyword, na=False)
        df = df[mask]

    # 基金类型筛选
    if fund_type and type_map:
        df = df[df["基金代码"].map(lambda c: type_map.get(c, "") == fund_type)]

    # 排序
    if sort_by in df.columns:
        df[sort_by] = pd.to_numeric(df[sort_by], errors="coerce")
        ascending = order.lower() != "desc"
        df = df.sort_values(by=sort_by, ascending=ascending)

    total = len(df)
    start = (page - 1) * page_size
    end = start + page_size
    page_df = df.iloc[start:end]

    funds = []
    for _, row in page_df.iterrows():
        code = str(row.get("基金代码", ""))
        funds.append({
            "code": code,
            "name": str(row.get("基金简称", "")),
            "type": type_map.get(code, ""),
            "nav": _safe_float(row.get("单位净值")),
            "accum_nav": _safe_float(row.get("累计净值")),
            "return_1w": _safe_float(row.get("近1周")),
            "return_1m": _safe_float(row.get("近1月")),
            "return_3m": _safe_float(row.get("近3月")),
            "return_6m": _safe_float(row.get("近6月")),
            "return_1y": _safe_float(row.get("近1年")),
            "return_3y": _safe_float(row.get("近3年")),
        })

    return {"total": total, "page": page, "page_size": page_size, "funds": funds}


def get_fund_holdings(code: str, force_refresh: bool = False) -> list:
    """
    获取基金持仓（前十大重仓股）

    参数:
        code: 基金代码
        force_refresh: 强制刷新缓存

    返回:
        list[dict]: [{ stock_code, stock_name, proportion, market_value }]
    """
    cache_path = _cache_path(code, "holdings")

    if not force_refresh and _is_cache_valid(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    _rate_limit()
    try:
        df = ak.fund_portfolio_holdings_em(symbol=code)
        if df.empty:
            return []

        # 将中文列名映射为英文
        col_map = {}
        for col in df.columns:
            if col in ("股票代码",):
                col_map[col] = "stock_code"
            elif col in ("股票名称",):
                col_map[col] = "stock_name"
            elif col in ("占净值比例", "占净资产比例", "持仓占比"):
                col_map[col] = "proportion"
            elif col in ("持仓市值", "市值", "持有金额"):
                col_map[col] = "market_value"
        df = df.rename(columns=col_map)

        keep_cols = [v for v in col_map.values() if v in df.columns]
        if not keep_cols:
            return []

        result = []
        for _, row in df[keep_cols].iterrows():
            item = {}
            for k in keep_cols:
                v = row[k]
                if isinstance(v, str):
                    v = v.strip()
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    if k in ("proportion", "market_value"):
                        try:
                            v = float(v)
                        except (ValueError, TypeError):
                            pass
                else:
                    v = None
                item[k] = v
            result.append(item)

        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, default=str)
        return result

    except Exception as e:
        print(f"[ERROR] 获取基金持仓失败 {code}: {e}")
        return []
