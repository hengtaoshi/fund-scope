# 基金范围 → 量化分析平台 · 改造方案

## 一、核心问题诊断：收益率不准

### 1.1 当前计算方式（错的）

```
profit = current_total - cost_total
return_pct = profit / cost_total
```
其中 `cost_total = shares × cost_nav`

**为什么不准：**

| 场景 | 实际应该怎么算 | 现在怎么算 |
|------|--------------|-----------|
| 一次性买入后持有 | `(净值-成本)/成本` ✅ 对 | ✅ 对 |
| 定投每月买100元 | 要用 XIRR 考虑每笔钱的时间价值 | 用平均成本×总份额 ❌ |
| 中途加仓/减仓 | 每笔交易的权重不同 | 简单平均成本 ❌ |
| 分红再投资 | 份额增加但成本不变 | 不处理，成本一直不对 ❌ |

**要解决这个问题，必须先有交易流水，再从流水算真实收益率。**

### 1.2 解决方案：交易流水 + XIRR

**新增 `transactions` 表：**
```sql
CREATE TABLE transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    fund_code   TEXT NOT NULL,
    fund_name   TEXT NOT NULL DEFAULT '',
    type        TEXT NOT NULL CHECK(type IN ('buy', 'sell', 'dividend')),
    shares      REAL NOT NULL,
    price       REAL NOT NULL,       -- 交易时净值
    amount      REAL NOT NULL,       -- 交易金额（正数=支出，负数=收入）
    fee         REAL DEFAULT 0,      -- 手续费
    tx_date     TEXT NOT NULL,        -- 交易日期
    note        TEXT DEFAULT '',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
)
```

**真实收益率计算 — XIRR：**
- XIRR = 考虑每一笔现金流（买入/卖出/分红）发生日期的年化内部收益率
- 比简单收益率更科学，也是邮政/支付宝/天天基金都在用的算法
- Python 有 `numpy_financial.irr` 或 `pyxirr` 库可以直接算

---

## 二、功能改造全景图

### 优先级 P0（必须做，不改没法用）

| # | 功能 | 说明 | 涉及文件 |
|---|------|------|---------|
| 1 | **交易流水表 + 交易记录页面** | 替代当前的"添加持仓"逻辑，每次买入/卖出都记一笔 | `database.py`, `app.py`, `app.js` |
| 2 | **XIRR 真实收益率** | 后端用现金流算年化收益率，前端显示 | `fund_analysis.py`, `app.py` |
| 3 | **基准对比 + 超额收益** | 持仓 vs 沪深300 的超额收益曲线 + 累计超额 | `app.py`, `fund_data.py`, `app.js` |
| 4 | **组合风险仪表盘** | VaR、波动率、最大回撤显示在仪表盘第一屏 | `app.py`, `app.js` |

### 优先级 P1（重要迭代）

| # | 功能 | 说明 |
|---|------|------|
| 5 | **信号仪表盘** | 所有持仓的 RSI/MACD/均线汇总在一张表 |
| 6 | **信号告警** | 净值跌幅 > 5% / RSI超卖时页面Banner提示 |
| 7 | **相关性矩阵** | 持仓基金两两相关系数 + 热力图 |
| 8 | **仓位优化** | 马科维茨均值-方差模型算最优权重 |

### 优先级 P2（锦上添花）

| # | 功能 | 说明 |
|---|------|------|
| 9 | **再平衡提醒** | 当前权重偏离目标超阈值时提醒 |
| 10 | **压力测试** | 假设市场跌20%/涨20%组合的损益 |
| 11 | **行业暴露分析** | 穿透到底层股票的行业分布 |
| 12 | **费率分析** | 管理费+托管费对收益的影响 |

---

## 三、P0 功能详细设计

### P0-1：交易流水表 + 交易记录页面

**思路转变：**
```
旧：先有持仓 → 在持仓上加加减减
新：先有交易流水 → 持仓由流水汇总得出（这才是银行/券商的做法）
```

**数据流：**
```
添加交易(buy/sell) → 写入 transactions 表
                    → 实时计算当前持仓(SUM shares by fund_code)
                    → 实时计算真实收益率(XIRR by fund_code)
```

**前端改动：**
- "添加持仓"改为"买入记录"（时间 + 代码 + 份额 + 净值 + 手续费）
- 新增"卖出记录"（时间 + 代码 + 份额 + 净值）
- 新增"交易记录"页面，按时间线展示所有交易
- 持仓页面仍然存在，但由后端聚合交易数据生成

**迁移方案：**
- 旧数据：现有的 holdings 表数据 → 转换为一条 "买入" 记录（用当时的 cost_nav 和 shares）
- 新数据：全部走 transactions 表

**涉及文件：** `backend/database.py`, `backend/app.py`, `frontend/js/app.js`, `frontend/css/style.css`

---

### P0-2：XIRR 真实收益率

**算法说明：**
```
XIRR 是解这个方程：
  0 = Σ(CF_i / (1 + r)^(days_i / 365))

其中：
  CF_i = 第 i 笔现金流（买入为负，卖出为正，当前市值为正）
  days_i = 第 i 笔距离今天的天数
  r = 年化收益率（XIRR）
```

**实现方式：**
- `pip install pyxirr` 或 `numpy_financial`
- 后端新增函数 `calc_xirr(cashflows: list[(date, amount)]) → float`
- 组合层面和单基金层面都算

**显示：**
```
当前（错的）：累计收益 +12.5%
改后（对的）：XIRR年化收益 +8.3% | 累计收益 +12.5% | 持有期 1.8年
```

**涉及文件：** `backend/fund_analysis.py`, `backend/app.py`, `frontend/js/app.js`

---

### P0-3：基准对比 + 超额收益

**数据源：**
- 沪深300指数 (`000300.SH`) 通过 akshare `stock_zh_index_daily_em` 获取
- 可选：同类基金均值（通过 `fund_open_fund_rank_em` 获取同类平均）

**计算逻辑：**
```
超额收益 = 持仓当日收益 - 基准当日收益
累计超额 = Σ(每日超额收益)
信息比率 = 年化超额收益 / 跟踪误差
```

**显示：**
- 仪表盘统计卡片新增"超额收益"和"信息比率"
- 仪表盘折线图可选"叠加基准"（持仓净值 vs 沪深300）
- 新增"超额收益曲线"图

**涉及文件：** `backend/fund_data.py`（加获取指数函数）, `backend/app.py`, `frontend/js/app.js`

---

### P0-4：组合风险仪表盘

**指标：**

| 指标 | 算法 | 说明 |
|------|------|------|
| 组合VaR(95%) | 历史模拟法：取持仓日收益率序列的 5% 分位数 | 明天最大可能亏多少 |
| 组合CVaR | 低于 VaR 的收益率的均值 | 如果亏了，平均亏多少 |
| 组合年化波动率 | 持仓加权协方差矩阵 × 权重 | 组合波动性 |
| 当前回撤 | (当前净值 - 区间最高净值) / 区间最高净值 | 距前高跌了多少 |
| 风险贡献分解 | 每只基金对组合总风险的占比 | 谁在拖累组合 |

**显示位置：**
- 仪表盘顶部新增一行风险指标卡片
- 风险贡献用饼图/条形图展示

**涉及文件：** `backend/fund_analysis.py`, `backend/app.py`, `frontend/js/app.js`

---

## 四、实施路线图

### 第一阶段：修根（交易流水 + XIRR）
- 建 `transactions` 表
- 写交易 CRUD 接口
- 前端交易记录页面
- XIRR 算法实现
- 旧数据迁移

### 第二阶段：加基准（对比 + 风险）
- 沪深300 数据接口
- 超额收益计算 + 曲线
- 组合风险指标计算
- 仪表盘风险卡片

### 第三阶段：进阶（信号 + 优化）
- 信号告警系统
- 相关性矩阵
- 仓位优化引擎

---

## 五、关键风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| 旧数据迁移复杂 | 用户现有持仓可能丢失 | 写迁移脚本，保留旧数据快照 |
| pyxirr 安装依赖 | Docker 构建需要加依赖 | `pip install pyxirr` 加到 requirements.txt |
| 沪深300数据源稳定性 | akshare 可能限流或改API | 加入缓存和降级方案（无基准时隐藏） |
| 前端改动量大 | 持仓页面逻辑全部重写 | 分步上线，交易记录和持仓展示分开做 |
