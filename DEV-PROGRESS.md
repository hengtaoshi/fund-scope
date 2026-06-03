# 基金驾驶舱 — 开发进度文档

> 最后更新：2025-07-14 | 下次开发从这里继续

---

## 一、项目概述

个人基金量化分析平台，通过多因子评分模型对基金进行综合评价，提供买卖参考建议。

### 技术栈

| 层 | 技术 |
|------|------|
| 后端 | Python Flask |
| 数据源 | akshare（天天基金/东方财富） |
| 数据库 | SQLite |
| 前端 | 纯 HTML/CSS/JS（无框架） |
| 图表 | Chart.js |
| 邮件 | smtplib |

### 启动方式

```bash
# 启动后端（自动 serve 前端页面）
python fund-platform/backend/app.py
# 浏览器打开 http://localhost:5000
```

---

## 二、已完成功能 ✅

### 2.1 数据层

| 功能 | 文件 | 说明 |
|------|------|------|
| 基金历史净值 | `fund_data.py` | 从 akshare 获取日线净值，4小时缓存 |
| 基金基本信息 | `fund_data.py` | 名称、类型、成立日、规模、经理 |
| 基金经理信息 | `fund_data.py` | 从全量经理数据筛选 |
| 基金搜索 | `fund_data.py` | 按代码/名称关键词搜索 |
| 请求频率限制 | `fund_data.py` | 间隔 ≥ 1s，避免触发反爬 |

### 2.2 分析引擎

| 功能 | 文件 | 说明 |
|------|------|------|
| 年化收益率 | `fund_analysis.py` | `(latest/oldest)^(252/n) - 1` |
| 年化波动率 | `fund_analysis.py` | `std(daily_return) × √252` |
| 最大回撤 | `fund_analysis.py` | `max((peak - trough)/peak)` |
| 夏普比率 | `fund_analysis.py` | 无风险利率 2.5% |
| 索提诺比率 | `fund_analysis.py` | 只考虑下行风险 |
| 卡玛比率 | `fund_analysis.py` | 收益/回撤比 |
| Alpha / Beta | `fund_analysis.py` | 简化版（需要沪深300数据改进） |
| 多因子评分 | `fund_analysis.py` | 5维度加权（收益30%+风控25%+性价比20%+技术面15%+稳定性10%） |
| 技术信号 | `fund_analysis.py` | RSI(14)、MACD(12/26/9)、均线(5/20/60)、布林带(20,2σ) |

### 2.3 数据库

| 功能 | 文件 | 说明 |
|------|------|------|
| 持仓CRUD | `database.py` | SQLite 增删改查 |
| 自动补全基金名 | `app.py` | 添加持仓时调用 akshare 获取名称 |

### 2.4 前端页面

| 页面 | 功能 | 状态 |
|------|------|------|
| **概览** | 总资产/收益/持仓数卡片、资产配置饼图、净值走势折线图（支持时段切换+基金选择）、持仓明细表（含详情跳转） | ✅ |
| **持仓** | 添加/修改/删除持仓弹窗、持仓列表、底部汇总统计 | ✅ |
| **分析** | 输入基金代码 → 显示净值/指标/走势图/技术信号/智能评分 | ✅ |
| **智能预测** | 组合综合评分、每只基金多维评分卡片、技术信号标签、等级对照表 | ✅ |
| **工具** | 定投计算器 | ✅ |
| **设置** | 邮箱配置、缓存清除 | ✅ |

### 2.5 API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/fund/<code>` | 基金详情 |
| GET | `/api/fund/<code>/nav` | 基金历史净值 |
| GET | `/api/fund/search?q=` | 搜索基金 |
| GET | `/api/analysis/<code>` | 完整分析 |
| GET | `/api/analysis/<code>/indicators` | 仅指标 |
| GET | `/api/analysis/<code>/signals` | 仅信号 |
| GET | `/api/analysis/<code>/score` | 仅评分 |
| GET | `/api/portfolio` | 持仓列表（含实时市值） |
| POST | `/api/portfolio` | 添加持仓 |
| PUT | `/api/portfolio/<id>` | 更新持仓 |
| DELETE | `/api/portfolio/<id>` | 删除持仓 |
| GET | `/api/portfolio/analysis` | 组合评分 |
| POST | `/api/send-report` | 发送加仓报告（需配置SMTP） |
| POST | `/api/test-email` | 测试SMTP连接 |

### 2.6 UI 设计定稿

- 暖色系（琥珀金 `#c7883c` + 暖灰底 `#f5f5f0` + 白色卡片）
- 红涨绿跌（中国股市标准）
- 无蓝色、无渐变色、无深色主题
- 白色侧边栏 + 琥珀金选中高亮
- 响应式布局（640px / 900px 断点）

---

## 三、项目文件结构

```
fund-platform/
├── backend/
│   ├── app.py                 # Flask 主入口 + API 路由
│   ├── fund_data.py           # akshare 数据层
│   ├── fund_analysis.py       # 分析引擎
│   ├── database.py            # SQLite 持仓管理
│   ├── email_sender.py        # SMTP 邮件发送
│   ├── config.py              # 环境变量配置
│   ├── verify_data.py         # 数据验证脚本（测试用）
│   ├── requirements.txt       # Python 依赖
│   └── data/
│       ├── portfolio.db       # 持仓数据库
│       └── cache/             # akshare 数据缓存
├── frontend/
│   ├── index.html             # 主页面
│   ├── css/style.css          # 样式表
│   └── js/app.js              # 前端应用逻辑
├── PLAN.md                    # 整体方案文档
├── REVIEW.md                  # 代码审查报告
└── FIX-PLAN.md                # 修复跟踪
```

---

## 四、待办 / 下次开发方向

### P0 - 紧急

| 任务 | 说明 | 原因 |
|------|------|------|
| 折线图横坐标日期显示优化 | 按月标签有时不准确 | 用户体验 |

### P1 - 重要

| 任务 | 说明 | 涉及文件 |
|------|------|------|
| SMTP 配置接入 | 配置环境变量后真正能发邮件 | `config.py`, `email_sender.py` |
| 持仓导入/导出 | CSV 批量导入导出 | `app.py`, `app.js` |
| 前端错误处理 | API 调用失败时给出友好提示 | `app.js` |
| 数据缓存管理 | 设置页缓存清除调用后端接口 | `app.py`, `app.js` |
| 沪深300基准对比 | 折线图叠加沪深300走势线 | `fund_data.py`, `app.js` |

### P2 - 改进

| 任务 | 说明 |
|------|------|
| 基金对比功能 | 多只基金同台对比 |
| 组合优化 | 马科维茨有效前沿计算 |
| 定投回测 | 历史数据回溯定投收益 |
| 移动端适配优化 | 窄屏下的交互改进 |
| 多账户支持 | 切换不同持仓组合 |
| 基金详情弹窗 | 点击持仓名称弹出完整详情（现跳转到分析页） |
| 折线图多基金叠加 | 同时显示多只基金净值对比 |

### P3 - 远期

| 任务 | 说明 |
|------|------|
| 更多技术指标 | KDJ, OBV, 量价关系 |
| 机器学习预测 | 基于历史数据的趋势预测（仅供参考） |
| 用户登录 | 简单账号系统 |

---

## 五、已知问题 / REVIEW 遗留

| 问题 | 状态 | 说明 |
|------|------|------|
| Alpha/Beta 计算 | ⚠️ 简化版 | 当前用基金自身收益近似代替市场基准，需要接入沪深300数据改进 |
| 净值数据排序 | ⚠️ 需注意 | akshare 返回的净值数据从旧到新排列，前端和 API 都需正确处理 |
| SMTP 未配置 | ⚠️ 预期行为 | 未设环境变量时返回友好错误，功能正常 |
| HTML Demo 文件 | 📦 归档 | `frontend/index.html` 和 `fund-platform/index.html` 已不维护 |

---

## 六、开发指南

### 添加新 API 端点

1. 在 `app.py` 添加路由函数
2. 如果涉及新数据逻辑，在 `fund_data.py` 或新建模块实现
3. 在前端 `app.js` 添加对应的 `renderXxx()` 函数
4. 在 `index.html` 添加导航项（如需）

### 依赖

```
flask>=3.0
akshare>=1.14
pandas>=2.0
numpy>=1.24
```

### 配置 SMTP

```bash
# Windows
set SMTP_SERVER=smtp.qq.com
set SMTP_PORT=465
set SMTP_USER=your@qq.com
set SMTP_PASS=your_auth_code
set EMAIL_FROM=your@qq.com
```
