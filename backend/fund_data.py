"""
基金驾驶舱 — akshare 数据层

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
