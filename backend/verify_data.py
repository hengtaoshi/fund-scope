#!/usr/bin/env python
"""
基金驾驶舱 — akshare 数据层验证脚本

验证三项核心数据源能否正常获取：
1. 基金历史净值
2. 基金基本信息
3. 基金经理信息
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fund_data import get_fund_nav, get_fund_info, get_fund_manager


def verify():
    """运行验证"""
    test_codes = ["005827", "161005", "161725"]  # 易方达蓝筹、富国天惠、招商白酒
    errors = []
    successes = []

    for code in test_codes:
        print(f"\n{'='*50}")
        print(f"📌 测试基金代码: {code}")
        print(f"{'='*50}")

        # 1. 基金信息
        print("\n📋 基金信息:")
        info = get_fund_info(code)
        if info:
            print(f"   名称: {info.get('fund_name', 'N/A')}")
            print(f"   类型: {info.get('fund_type', 'N/A')}")
            print(f"   成立日: {info.get('establish_date', 'N/A')}")
            print(f"   规模: {info.get('fund_size', 'N/A')}")
            print(f"   经理: {info.get('manager', 'N/A')}")
            successes.append(f"{code}: 信息获取成功")
        else:
            errors.append(f"{code}: 信息获取失败")

        # 2. 基金经理
        print("\n👤 基金经理:")
        managers = get_fund_manager(code)
        if managers:
            for m in managers[:3]:
                print(f"   {m.get('name', 'N/A')} | 任职: {m.get('start_date', 'N/A')} | 回报: {m.get('return_rate', 'N/A')}")
            successes.append(f"{code}: 经理信息获取成功")
        else:
            errors.append(f"{code}: 经理信息获取失败")

        # 3. 净值
        print("\n📈 净值数据:")
        nav = get_fund_nav(code)
        if not nav.empty:
            print(f"   数据量: {len(nav)} 条")
            print(f"   日期范围: {nav['日期'].iloc[-1]} ~ {nav['日期'].iloc[0]}")
            print(f"   最新净值: {nav['单位净值'].iloc[0]:.4f}")
            successes.append(f"{code}: 净值获取成功 ({len(nav)} 条)")
        else:
            errors.append(f"{code}: 净值获取失败")

    # 汇总
    print(f"\n\n{'='*50}")
    print("📊 验证结果汇总")
    print(f"{'='*50}")
    print(f"✅ 成功: {len(successes)}")
    for s in successes:
        print(f"   ✔ {s}")
    print(f"❌ 失败: {len(errors)}")
    for e in errors:
        print(f"   ✘ {e}")

    return len(errors) == 0


if __name__ == "__main__":
    success = verify()
    sys.exit(0 if success else 1)
