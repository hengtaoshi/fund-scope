/**
 * 基金范围 — 前端应用
 * 纯前端单页应用，通过 Flask API 获取真实数据
 */
const API = '';

// ====== Chart.js 十字光标插件 ======
const crosshairPlugin = {
    id: 'crosshair',
    afterDraw: function(chart) {
        if (!chart._active || !chart._active.length) return;
        const active = chart._active[0];
        if (!active || !active.element || typeof active.element.x !== 'number') return;
        const ctx = chart.ctx;
        if (!ctx) return;
        const yAxis = chart.scales.y;
        const xAxis = chart.scales.x;
        if (!yAxis || !xAxis || typeof yAxis.top !== 'number' || typeof xAxis.left !== 'number') return;
        if (typeof active.element.y !== 'number') return;

        const x = active.element.x;
        ctx.save();
        // 竖虚线
        ctx.beginPath();
        ctx.setLineDash([4, 3]);
        ctx.strokeStyle = '#94A3B8';
        ctx.lineWidth = 1;
        ctx.moveTo(x, yAxis.top);
        ctx.lineTo(x, yAxis.bottom);
        ctx.stroke();

        // 横虚线
        ctx.beginPath();
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = '#94A3B8';
        ctx.lineWidth = 1;
        ctx.moveTo(xAxis.left, active.element.y);
        ctx.lineTo(xAxis.right, active.element.y);
        ctx.stroke();

        // 交叉点（红色实心小圆）
        ctx.beginPath();
        ctx.arc(x, active.element.y, 3.5, 0, 2 * Math.PI);
        ctx.fillStyle = '#F04444';
        ctx.fill();

        ctx.restore();
    }
};

// 注册插件（Chart.js 可能从 CDN 异步加载，防御性处理）
if (typeof Chart !== 'undefined') {
    try { Chart.register(crosshairPlugin); } catch(e) { console.warn('Chart.register 失败:', e); }
}

// ====== 工具 ======
function $(id) { return document.getElementById(id); }
function qs(sel, ctx) { return (ctx || document).querySelector(sel); }
function qsa(sel, ctx) { return (ctx || document).querySelectorAll(sel); }

async function _parseJsonSafe(res) {
    try { return await res.json(); } catch (e) { return null; }
}

function esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function showToast(msg) {
    const t = $('toast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._timer); t._timer = setTimeout(() => t.classList.remove('show'), 3000);
}

function getToken() {
    return localStorage.getItem('fund_token') || '';
}

let _abortController = null;
let _renderGeneration = 0;

// ====== Token 管理（自动刷新 + 静默续期）======

let _refreshPromise = null;  // 防止并发刷新

function _parseJwtPayload(token) {
    try {
        const base64 = token.split('.')[1];
        return JSON.parse(atob(base64));
    } catch (e) {
        return null;
    }
}

function _isTokenNearExpiry(token, minutes = 5) {
    const payload = _parseJwtPayload(token);
    if (!payload || !payload.exp) return true;
    const expMs = payload.exp * 1000;
    return (expMs - Date.now()) < minutes * 60 * 1000;
}

async function _refreshToken() {
    // 防止并发：同一时间只发一次刷新请求
    if (_refreshPromise) return _refreshPromise;
    _refreshPromise = (async () => {
        try {
            const token = getToken();
            if (!token) return false;
            const res = await fetch(API + '/api/auth/refresh', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token,
                },
            });
            if (!res.ok) return false;
            const data = await res.json();
            if (data && data.token) {
                localStorage.setItem('fund_token', data.token);
                return true;
            }
            return false;
        } catch (e) {
            console.warn('[token] 刷新失败:', e.message);
            return false;
        } finally {
            _refreshPromise = null;
        }
    })();
    return _refreshPromise;
}

async function _ensureToken() {
    const token = getToken();
    if (!token) return false;
    // Token 即将过期（< 5 分钟）时主动预刷新
    if (_isTokenNearExpiry(token, 5)) {
        const ok = await _refreshToken();
        if (!ok) {
            // 预刷新失败，但现有 token 可能还能用几分钟，不销毁
            console.warn('[token] 预刷新失败，现有 token 继续使用');
        }
    }
    return true;
}

async function api(url, opts = {}) {
    try {
        // 先确保 token 有效（预刷新）
        if (url !== '/api/auth/refresh') {
            await _ensureToken();
        }

        const headers = {
            'Content-Type': 'application/json',
            ...opts.headers,
        };
        const token = getToken();
        if (token) headers['Authorization'] = 'Bearer ' + token;
        // 附加当前页面的取消信号，快速切换时自动中断旧请求
        if (_abortController && !opts.signal) {
            opts.signal = _abortController.signal;
        }
        const res = await fetch(API + url, {
            headers,
            ...opts
        });
        if (res.status === 401) {
            // 401：尝试刷新 token，刷新成功则重试原请求
            const refreshed = await _refreshToken();
            if (refreshed) {
                // 用新 token 重试
                const newToken = getToken();
                headers['Authorization'] = 'Bearer ' + newToken;
                const retryRes = await fetch(API + url, { headers, ...opts });
                if (retryRes.ok) return await retryRes.json();
                if (retryRes.status === 401) {
                    // 重试仍然 401 → token 彻底失效
                    localStorage.removeItem('fund_token');
                    window.location.href = '/login';
                    return null;
                }
                return await _parseJsonSafe(retryRes);
            }
            // 刷新失败 → 跳登录
            localStorage.removeItem('fund_token');
            window.location.href = '/login';
            return null;
        }
        if (!res.ok) {
            // 非 200/401 响应：尝试解析 JSON 错误，否则返回通用错误
            const errData = await _parseJsonSafe(res);
            return errData || { error: `请求失败 (HTTP ${res.status})` };
        }
        return await res.json();
    } catch (e) {
        if (e.name === 'AbortError') throw e;  // 请求被取消，向上传递
        showToast('网络错误: ' + e.message);
        return null;
    }
}

function fmt(n) { return (n || 0).toLocaleString(); }
function fmtPct(n) { return (n >= 0 ? '+' : '') + (n || 0).toFixed(2) + '%'; }
function fmtMoney(n) { return '¥' + (n || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}); }
function cls(val) { return val >= 0 ? 'text-up' : 'text-down'; }
function tagCls(val) { return val >= 0 ? 'tag-up' : 'tag-down'; }

const pageTitles = {
    dashboard: ['概览', '今日数据 · 实时估算'],
    watchlist: ['自选', '感兴趣的基金 · 先跟踪再买入'],
    portfolio: ['持仓', '全部持仓一览'],
    transactions: ['交易记录', '每一笔买入/卖出/分红'],
    analysis: ['分析', '基金深度分析'],
    predict: ['智能预测', '多因子评分模型 · 买卖时机参考'],
    screener: ['基金筛选', '多维度筛选优质基金'],
    compare: ['对比', '多基金关键指标对比'],
    penetration: ['组合穿透', '风格分析与行业分布'],
    dca: ['定投规划', '智能定投模拟计算'],
    tools: ['工具', '定投计算器'],
    ai: ['AI 助手', '智能持仓问答'],
    settings: ['设置', '系统设置'],
};

// ====== 导航 ======
qsa('.nav-item').forEach(item => {
    item.addEventListener('click', function () {
        qsa('.nav-item').forEach(n => n.classList.remove('active'));
        qsa('.page').forEach(p => p.classList.remove('active'));
        this.classList.add('active');
        const page = this.dataset.page;
        const t = pageTitles[page] || ['', ''];
        $('pageTitle').textContent = t[0];
        $('pageSubtitle').textContent = t[1];
        if (window.innerWidth <= 640) $('sidebar').classList.remove('open');
        renderPage(page);
    });
});

// ====== 渲染 ======
let chartInstances = {};
let currentPage = 'dashboard';
let chartPeriod = '1y';
let detailPeriod = '1y';
let portfolioHistoryPeriod = '1y';
let selectedFund = ''; // 当前折线图选中的基金代码

function getPeriodDays(period) {
    return { '1m': 21, '3m': 63, '6m': 126, '1y': 252 }[period] || 252;
}

function filterByPeriod(data, period) {
    const days = getPeriodDays(period);
    return data.length > days ? data.slice(-days) : data;
}

function switchFund(code) {
    selectedFund = code;
    // 强制刷新获取新数据（不走缓存）
    renderLineChart(code, chartPeriod);
    // 更新标签高亮
    document.querySelectorAll('.fund-tab').forEach(el => {
        const isActive = el.dataset.code === code;
        el.style.background = isActive ? '#F0B90B' : '#1E293B';
        el.style.color = isActive ? '#fff' : '#E2E8F0';
    });
}

function setChartPeriod(period) {
    chartPeriod = period;
    if (selectedFund) renderLineChart(selectedFund, period);
    document.querySelectorAll('.period-btn').forEach(el => {
        if (!el.getAttribute('onclick')?.includes('setChartPeriod')) return;
        const isActive = el.dataset.period === period;
        el.style.background = isActive ? '#F0B90B' : '#1E293B';
        el.style.color = isActive ? '#fff' : '#E2E8F0';
    });
}

function setDetailPeriod(period) {
    detailPeriod = period;
    renderDetailChart(window._detailNavData, period);
    document.querySelectorAll('.period-btn').forEach(el => {
        if (!el.getAttribute('onclick')?.includes('setDetailPeriod')) return;
        const isActive = el.dataset.period === period;
        el.style.background = isActive ? '#F0B90B' : '#1E293B';
        el.style.color = isActive ? '#fff' : '#E2E8F0';
    });
}

function periodBtn(label, period, active) {
    return `<span class="period-btn ${active ? 'active' : ''}" data-period="${period}" onclick="setChartPeriod('${period}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${active ? 'background:#F0B90B;color:#fff;' : 'background:#1E293B;color:#E2E8F0;'}margin-left:4px;">${label}</span>`;
}

let _refreshTimer = null;
let _lastForceRefreshTime = 0;

function updateLastRefreshTime() {
    const el = $('lastRefreshTime');
    if (el) {
        const now = new Date();
        el.textContent = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }
}

async function autoRefresh(force) {
    if (force) {
        // 先清缓存
        await api('/api/clear-cache');
    }
    // 重新渲染当前页面
    await renderPage(currentPage);
}

async function renderPage(page) {
    // 取消上一个页面的所有未完成请求
    if (_abortController) { _abortController.abort(); }
    _abortController = new AbortController();
    const generation = ++_renderGeneration;

    currentPage = page;
    // 清除旧定时器
    if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
    const content = $('content');
    const fns = {
        dashboard: renderDashboard,
        watchlist: renderWatchlist,
        portfolio: renderPortfolio,
        transactions: renderTransactions,
        analysis: renderAnalysis,
        predict: renderPredict,
        screener: renderScreener,
        compare: renderCompare,
        penetration: renderPenetration,
        dca: renderDca,
        tools: renderTools,
        ai: renderAI,
        settings: renderSettings,
    };
    content.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
    if (fns[page]) {
        try {
            await fns[page](content);
        } catch (e) {
            if (e.name === 'AbortError') return;  // 请求已被取消，忽略
            throw e;
        }
    }
    // 如果在此等待期间触发了新的渲染，丢弃本次结果
    if (generation !== _renderGeneration) return;
    // 更新最后刷新时间
    updateLastRefreshTime();
    // 所有页面开启自动刷新：每 5 分钟自动更新数据
    // 每 30 分钟强制清除缓存重新抓取
    _refreshTimer = setInterval(() => {
        const now = Date.now();
        const force = (now - _lastForceRefreshTime) > 1800000; // 30分钟
        if (force) _lastForceRefreshTime = now;
        autoRefresh(force);
    }, 300000); // 5分钟
}

// ====== 概览 ======
async function autoRefreshDashboard() {
    const data = await api('/api/portfolio/dashboard');
    if (!data || !data.holdings || data.holdings.length === 0) return;
    const h = data.holdings;
    const s = data.summary;
    window._holdingsList = h;
    const cards = qsa('.stat-value');
    if (cards.length >= 5) {
        cards[0].textContent = fmtMoney(s.total_value);
        cards[1].textContent = fmtMoney(s.total_cost);
        cards[2].textContent = fmtMoney(s.total_profit);
        cards[2].className = 'stat-value ' + cls(s.total_profit);
        let changeEl = cards[2].nextElementSibling;
        if (changeEl) { changeEl.textContent = fmtPct(s.total_return_pct); changeEl.className = 'stat-change ' + cls(s.total_profit); }
        cards[3].textContent = fmtMoney(s.total_daily_profit);
        cards[3].className = 'stat-value ' + cls(s.total_daily_profit);
        const dailyPct = (s.total_value - s.total_daily_profit) > 0 ? s.total_daily_profit / (s.total_value - s.total_daily_profit) * 100 : 0;
        changeEl = cards[3].nextElementSibling;
        if (changeEl) { changeEl.textContent = fmtPct(dailyPct); changeEl.className = 'stat-change ' + cls(s.total_daily_profit); }
    }
    if (cards.length >= 5) {
        cards[0].textContent = fmtMoney(totalVal);
        cards[1].textContent = fmtMoney(totalPrincipal);
        cards[2].textContent = fmtMoney(totalProfit);
        cards[2].className = 'stat-value ' + cls(totalProfit);
        let changeEl = cards[2].nextElementSibling;
        if (changeEl) { changeEl.textContent = fmtPct(totalPct); changeEl.className = 'stat-change ' + cls(totalProfit); }
        cards[3].textContent = fmtMoney(totalDailyProfit);
        cards[3].className = 'stat-value ' + cls(totalDailyProfit);
        changeEl = cards[3].nextElementSibling;
        if (changeEl) { changeEl.textContent = fmtPct(dailyPct); changeEl.className = 'stat-change ' + cls(totalDailyProfit); }
    }
    // 更新饼图
    renderPieChart(h);
    // 更新折线图（强制刷新缓存）
    if (selectedFund) {
        const canvas = $('lineChart');
        if (canvas) renderLineChart(selectedFund, chartPeriod, true);
    }
}
// 同步所有定投持仓的累计投入到当前日期（静默更新数据库 + 本地值）
// 用净值交易日数量算期数，最后交易日 < 今天且今天是交易日时补 1 期
// 返回 { [id]: { startNav, currentNav, expectedInvested, isStopped } }
async function syncDcaHoldings(holdings) {
    const dcaInfo = {};
    const today = new Date();
    const y = today.getFullYear(), m = today.getMonth() + 1, d = today.getDate();
    const todayLocal = y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');

    // 批量获取所有定投基金的净值（并行，一次请求）
    const dcaHoldings = holdings.filter(x => x.total_invested != null && x.dca_start_date);
    const codes = dcaHoldings.map(x => x.code).join(',');
    let navsBatch = {};
    if (codes) {
        try {
            const batchResp = await api(`/api/fund/navs?codes=${encodeURIComponent(codes)}`);
            if (batchResp && batchResp.navs) {
                navsBatch = batchResp.navs;
            }
        } catch (e) { /* 静默失败 */ }
    }

    for (const x of dcaHoldings) {
        try {
            const navData = navsBatch[x.code];
            const startStr = x.dca_start_date.slice(0, 10);
            const endStr = x.dca_end_date || todayLocal;
            const endDate = new Date(endStr);

            let buyCount = 0;
            if (navData && navData.data && navData.data.length && x.dca_amount && x.dca_frequency) {
                const records = navData.data.filter(r => r.日期 >= startStr && r.日期 <= endStr);
                if (x.dca_frequency === 'daily') {
                    buyCount = records.length;
                    // QDII 基金 T+2 确认，最后 2 个交易日还未确认到账
                    // 非 QDII 基金 T+1，但减 2 最多只少算 1 天，安全
                    buyCount = Math.max(0, buyCount - 2);
                } else if (x.dca_frequency === 'weekly') {
                    buyCount = Math.max(0, Math.ceil(records.length / 5));
                } else if (x.dca_frequency === 'monthly') {
                    const months = new Set(records.map(r => r.日期.slice(0, 7)));
                    buyCount = months.size;
                }
            }

            // 初始投入（定投前的单笔买入）→ 默认10元，自动保存到数据库
            const dcaInitial = x.dca_initial || 10;
            const dcaOnlyInvested = buyCount * (x.dca_amount || 0);
            const expectedInvested = dcaInitial + dcaOnlyInvested;

            let startNav = null, currentNav = null;
            let startIdx = -1;
            if (navData && navData.data && navData.data.length) {
                startIdx = navData.data.findIndex(r => r.日期 >= startStr);
                startNav = startIdx >= 0 ? navData.data[startIdx].单位净值 : null;
                currentNav = navData.data[navData.data.length - 1].单位净值;
            }

            // 逐期计算份额（与 submitHolding 逻辑一致，只算已确认的 buyCount 期）
            let dcaShares = 0;
            if (startIdx >= 0 && x.dca_amount && navData && navData.data && buyCount > 0) {
                const navs = navData.data.slice(startIdx, startIdx + buyCount);
                if (x.dca_frequency === 'daily') {
                    navs.forEach(d => { dcaShares += x.dca_amount / d.单位净值; });
                } else if (x.dca_frequency === 'weekly') {
                    navs.filter((_, i) => i % 5 === 0).forEach(d => { dcaShares += x.dca_amount / d.单位净值; });
                } else if (x.dca_frequency === 'monthly') {
                    const seen = new Set();
                    navs.filter(d => { const mo = d.日期.slice(0,7); if (seen.has(mo)) return false; seen.add(mo); return true; })
                        .forEach(d => { dcaShares += x.dca_amount / d.单位净值; });
                }
            }
            // 初始投入对应的份额：用首日净值估算（取第一个已确认交易日的净值）
            let initialShares = 0;
            if (dcaInitial > 0 && navData && navData.data && startIdx >= 0) {
                // 已确认范围的首个净值 = 从 startIdx 开始取 buyCount 个中的第一个
                const confirmedIdx = startIdx;
                const initialNav = navData.data[confirmedIdx]?.单位净值 || x.cost_nav || 1;
                initialShares = dcaInitial / initialNav;
            }
            const totalShares = Math.round((dcaShares + initialShares) * 100) / 100;
            const syncedCostNav = totalShares > 0 ? Math.round(expectedInvested / totalShares * 10000) / 10000 : 0;

            // 有新定投周期 → 自动同步
            const dbCostTotal = Math.round((x.shares || 0) * (x.cost_nav || 0) * 100) / 100;
            const dbShares = x.shares || 0;
            // 份额偏差超过0.1份也触发修复（成本对但份额不对的情况）
            const needsSharesFix = Math.abs(dbShares - totalShares) > 0.1;
            // dca_initial 未设 或 定投有增长 或 总成本/份额与预期不符 时同步
            const needsDcaInitialFix = dcaInitial > 0 && !x.dca_initial;
            const needsSync = needsDcaInitialFix || needsSharesFix || dcaOnlyInvested > ((x.total_invested || 0) - dcaInitial) || Math.abs(dbCostTotal - expectedInvested) > 0.1;
            if (needsSync && totalShares > 0) {
                try {
                    const syncRes = await api(`/api/portfolio/${x.id}/sync-dca`, {
                        method: 'POST',
                        body: JSON.stringify({ shares: totalShares, total_invested: expectedInvested, cost_nav: syncedCostNav, dca_initial: dcaInitial })
                    });
                    if (syncRes && syncRes.synced) {
                        // 更新本地 holdings 数据，让后续的总资产计算使用新份额
                        x.shares = totalShares;
                        x.total_invested = expectedInvested;
                        x.cost_nav = syncedCostNav;
                        x.cost_total = Math.round(expectedInvested * 100) / 100;
                        x.current_total = currentNav ? Math.round(totalShares * currentNav * 100) / 100 : x.current_total;
                        x.profit = Math.round(((x.current_total || 0) - (x.cost_total || 0)) * 100) / 100;
                    }
                } catch (e) { /* 同步失败不影响显示 */ }
            }

            dcaInfo[x.id] = {
                startNav: startNav,
                currentNav: currentNav,
                expectedInvested: expectedInvested,
                isStopped: !!x.dca_end_date,
            };
        } catch (e) { /* 单条失败静默跳过 */ }
    }
    return dcaInfo;
}

async function renderDashboard(el) {
    const [data, excessData, riskData, signalData, portfolioHistoryData] = await Promise.all([
        api('/api/portfolio/dashboard'),
        api('/api/portfolio/excess-return').catch(() => null),
        api('/api/portfolio/risk').catch(() => null),
        api('/api/portfolio/signals').catch(() => null),
        api('/api/portfolio/history?period=' + portfolioHistoryPeriod).catch(() => null),
    ]);
    if (!data || !data.holdings || data.holdings.length === 0) {
        el.innerHTML = '<div class="empty"><i class="fas fa-box-open"></i><p>还没有持仓</p></div>';
        return;
    }
    const h = data.holdings;
    const s = data.summary;
    const excess = excessData && excessData.total_excess_pct != null ? excessData : null;
    const risk = riskData && riskData.risk && riskData.risk.daily_var_95 != null ? riskData.risk : null;
    const alerts = (signalData && signalData.alerts) || [];
    const allSignals = (signalData && signalData.signals) || [];
    // 先同步定投金额到当前日期
    const dcaInfo = await syncDcaHoldings(h);
    const totalVal = s.total_value;
    const totalPrincipal = s.total_cost;
    const totalProfit = s.total_profit;
    const totalPct = s.total_return_pct;
    const totalDailyProfit = s.total_daily_profit;

    selectedFund = selectedFund || h[0].code;
    window._holdingsList = h;

    // 告警横幅
    const alertBanner = alerts.length > 0 ? `
    <div style="margin-bottom:16px;">
        ${alerts.slice(0,3).map(a => {
            const colors = {danger: '#F04444', warning: '#F0B90B', info: '#00C897'};
            return `<div style="display:flex;align-items:center;gap:10px;padding:10px 16px;background:${colors[a.severity]||'#F0B90B'}15;border-left:3px solid ${colors[a.severity]||'#F0B90B'};border-radius:6px;margin-bottom:6px;font-size:13px;">
                <span style="font-size:16px;">${a.severity === 'danger' ? '🔴' : a.severity === 'warning' ? '🟡' : '🔵'}</span>
                <span style="color:#E2E8F0;">${esc(a.message)}</span>
            </div>`;
        }).join('')}
    </div>` : '';

    const portfolioHistoryHtml = portfolioHistoryData && portfolioHistoryData.dates && portfolioHistoryData.dates.length > 1 ? `
    <div class="card card-accent">
        <div class="card-title"><i class="fas fa-chart-area"></i> 组合历史走势
            <span style="margin-left:auto;display:flex;gap:4px;">${['1月','3月','6月','1年','全部'].map((l,i) => {
                const p = ['1m','3m','6m','1y','all'][i];
                return `<span class="period-btn ${portfolioHistoryPeriod === p ? 'active' : ''}" data-period="${p}" onclick="setPortfolioHistoryPeriod('${p}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${portfolioHistoryPeriod === p ? 'background:#F0B90B;color:#fff;' : 'background:#1E293B;color:#E2E8F0;'}margin-left:2px;">${l}</span>`;
            }).join('')}</span>
        </div>
        <div class="chart-wrapper" style="height:300px;"><canvas id="portfolioHistoryChart"></canvas></div>
    </div>` : '';

    el.innerHTML = alertBanner + `
        <div class="stats">
            <div class="card stat-card"><div class="stat-label">总资产</div><div class="stat-value">${fmtMoney(totalVal)}</div></div>
            <div class="card stat-card"><div class="stat-label">投入本金</div><div class="stat-value">${fmtMoney(totalPrincipal)}</div></div>
            <div class="card stat-card"><div class="stat-label">累计收益</div><div class="stat-value ${cls(totalProfit)}">${fmtMoney(totalProfit)}</div><div class="stat-change ${cls(totalProfit)}">${fmtPct(totalPct)}</div></div>
            <div class="card stat-card"><div class="stat-label">昨日收益</div><div class="stat-value ${cls(totalDailyProfit)}">${fmtMoney(totalDailyProfit)}</div><div class="stat-change ${cls(totalDailyProfit)}">${fmtPct(totalDailyProfit ? totalDailyProfit / (totalVal - totalDailyProfit) * 100 : 0)}</div></div>
            <div class="card stat-card"><div class="stat-label">持仓数量</div><div class="stat-value">${h.length}</div></div>
            ${excess ? `<div class="card stat-card"><div class="stat-label">超额收益(沪300)</div><div class="stat-value ${cls(excess.total_excess_pct)}">${fmtPct(excess.total_excess_pct)}</div><div class="stat-change">组合 ${fmtPct(excess.portfolio_return_pct)} vs 基准 ${fmtPct(excess.index_return_pct)}</div></div>` : ''}
            ${risk ? `
            <div class="card stat-card"><div class="stat-label">VaR(95%)</div><div class="stat-value ${cls(-risk.daily_var_95)}">${risk.daily_var_95}%</div><div class="stat-change">年化 ${risk.annual_var_95}%</div></div>
            <div class="card stat-card"><div class="stat-label">年化波动率</div><div class="stat-value">${risk.volatility}%</div><div class="stat-change">夏普 ${risk.sharpe_ratio}</div></div>
            <div class="card stat-card"><div class="stat-label">当前回撤</div><div class="stat-value ${cls(-risk.current_drawdown)}">${risk.current_drawdown}%</div><div class="stat-change">最大 ${risk.max_drawdown}%</div></div>
            ` : ''}
        </div>
        ${portfolioHistoryHtml}
        <div class="charts">
            <div class="card"><div class="card-title"><i class="fas fa-chart-pie"></i> 资产配置</div><div class="chart-wrapper"><canvas id="pieChart"></canvas></div></div>
            <div class="card"><div class="card-title"><i class="fas fa-chart-line"></i> 
            <span style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <span style="font-size:14px;font-weight:600;color:#131A2B;margin-right:4px;">净值走势</span>
                ${h.map(x => `<span class="fund-tab" data-code="${x.code}" onclick="switchFund('${x.code}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${selectedFund === x.code ? 'background:#F0B90B;color:#fff;' : 'background:#1E293B;color:#E2E8F0;'}">${x.name.length > 6 ? x.name.slice(0,6)+'..' : x.name}</span>`).join('')}
                <span style="margin-left:4px;">${['1月','3月','6月','1年'].map((l,i) => periodBtn(l, ['1m','3m','6m','1y'][i], chartPeriod === ['1m','3m','6m','1y'][i])).join('')}</span>
            </span>
            </div><div class="chart-wrapper"><canvas id="lineChart"></canvas></div></div>
        </div>
        ${allSignals.length > 0 ? `
        <div class="card">
            <div class="card-title"><i class="fas fa-chart-bar"></i> 技术信号汇总</div>
            <div class="table-wrap"><table>
                <thead><tr><th>基金</th><th>日涨跌</th><th>RSI</th><th>MACD</th><th>均线</th><th>信号标签</th></tr></thead>
                <tbody>${allSignals.map(s => {
                    const signalTags = (s.signals || []).map(sig => {
                        const t = sig.type === 'up' ? 'tag-up' : sig.type === 'down' ? 'tag-down' : 'tag-neutral';
                        return `<span class="${t}" style="font-size:10px;padding:1px 8px;margin:1px;">${sig.label || ''}</span>`;
                    }).join('');
                    const rsiCls = s.rsi_value != null ? (s.rsi_value < 30 ? 'text-up' : s.rsi_value > 70 ? 'text-down' : '') : '';
                    return `<tr>
                        <td><strong>${esc(s.name)}</strong><br><span style="font-size:11px;color:#94A3B8;">${s.code}</span></td>
                        <td class="${cls(s.daily_change || 0)}">${s.daily_change != null ? fmtPct(s.daily_change) : '--'}</td>
                        <td class="${rsiCls}">${s.rsi_value != null ? s.rsi_value.toFixed(1) : '--'}<br><span style="font-size:10px;color:#94A3B8;">${s.rsi_signal || ''}</span></td>
                        <td><span style="color:${s.macd_signal === '金叉' || s.macd_signal === '多头' ? '#00C853' : '#F04444'}">${s.macd_signal || '--'}</span></td>
                        <td style="color:#94A3B8;">${s.ma_status || '--'}</td>
                        <td>${signalTags || '--'}</td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>
        </div>` : ''}
        <div class="card"><div class="card-title"><i class="fas fa-list"></i> 持仓明细</div>
        <div class="table-wrap"><table>
            <thead><tr><th>基金名称</th><th>可用份额</th><th>平均成本</th><th>累计投入</th><th>最新净值</th><th>持仓市值</th><th>收益</th><th>收益率</th><th>年化</th><th>较昨日</th><th></th></tr></thead>
            <tbody>${h.map(x => {
                const isDca = x.total_invested != null;
                const info = dcaInfo[x.id];
                const invested = (isDca && info && info.expectedInvested > 0) ? info.expectedInvested : (isDca ? x.total_invested : x.cost_total);
                const stopped = isDca && info && info.isStopped;
                const statusTag = isDca
                    ? (stopped ? ' <span style="font-size:10px;color:#64748B;">⏸</span>' : ' <span style="font-size:10px;color:#00C853;">●</span>')
                    : '';
                const dcaSub = isDca
                    ? '<br><span style="font-size:10px;color:#94A3B8;">' + (stopped ? '已终止' : '定投中') + ' · 从' + (x.dca_start_date ? x.dca_start_date.slice(0,10) : '') + (stopped && x.dca_end_date ? '至' + x.dca_end_date.slice(0,10) : '') + '</span>'
                    : '';
                const daily = x.daily_profit || 0;
                const xirrHtml = isDca && x.xirr != null
                    ? `<span class="${tagCls(x.xirr)}">${fmtPct(x.xirr)}</span>`
                    : '<span style="color:#64748B;">--</span>';
                return `<tr><td><strong>${x.name}</strong>${statusTag}${dcaSub}</td><td>${fmt(x.shares)}</td><td>${x.cost_nav.toFixed(4)}</td><td>${fmtMoney(invested)}</td><td class="${cls(x.profit)}">${x.current_nav.toFixed(4)}</td><td class="${cls(x.profit)}">${fmtMoney(x.current_total)}</td><td class="${cls(x.profit)}">${fmtMoney(x.profit)}</td><td><span class="${tagCls(x.profit)}">${fmtPct(x.return_pct)}</span></td><td>${xirrHtml}</td><td class="${cls(daily)}"><span style="font-size:13px;">${fmtMoney(daily)}</span><br><span style="font-size:10px;" class="${cls(daily)}">${fmtPct(x.daily_return_pct || 0)}</span></td><td><button class="btn btn-outline btn-sm" onclick="goAnalysis('${x.code}')">详情</button></td></tr>`;
            }).join('')}</tbody>
        </table></div></div>`;

    setTimeout(() => {
        renderPieChart(h);
        renderLineChart(selectedFund, chartPeriod);
        if (portfolioHistoryData && portfolioHistoryData.dates && portfolioHistoryData.dates.length > 1) {
            renderPortfolioHistoryChart(portfolioHistoryData);
        }
    }, 50);
}

function genColors(n) {
    const palette = ['#F0B90B','#00C897','#3B82F6','#A855F7','#EC4899','#F97316','#14B8A6','#6366F1','#EAB308','#64748B'];
    return n <= palette.length ? palette.slice(0, n) : Array.from({length:n}, (_,i) => palette[i % palette.length]);
}

function setPortfolioHistoryPeriod(period) {
    portfolioHistoryPeriod = period;
    renderPage(currentPage);
}

function renderPortfolioHistoryChart(data) {
    if (typeof Chart === 'undefined') return;
    const canvas = $('portfolioHistoryChart');
    if (!canvas || !data || !data.dates || data.dates.length < 2) return;
    if (chartInstances.portfolioHistory) {
        try { chartInstances.portfolioHistory.destroy(); } catch (e) { /* ignore */ }
        chartInstances.portfolioHistory = null;
    }
    const labels = data.dates;
    const portfolioValues = data.portfolioValues;
    const costLine = Array(labels.length).fill(data.totalInvested);

    chartInstances.portfolioHistory = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '组合市值',
                    data: portfolioValues,
                    borderColor: '#F0B90B',
                    backgroundColor: 'rgba(240,185,11,0.08)',
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    hoverRadius: 5,
                    pointHitRadius: 8,
                    borderWidth: 2,
                },
                {
                    label: '累计投入',
                    data: costLine,
                    borderColor: '#64748B',
                    backgroundColor: 'transparent',
                    borderDash: [6, 4],
                    fill: false,
                    tension: 0,
                    pointRadius: 0,
                    borderWidth: 1.5,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            scales: {
                x: {
                    ticks: {
                        color: '#64748B',
                        font: { size: 10 },
                        maxTicksLimit: 12,
                        maxRotation: 45,
                    },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                },
                y: {
                    ticks: {
                        color: '#64748B',
                        font: { size: 11 },
                        callback: v => '¥' + v.toLocaleString(),
                    },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                },
            },
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#E2E8F0', padding: 16, font: { size: 12 }, usePointStyle: true },
                    onClick: function(e, legendItem, legend) {
                        // 点击图例显示/隐藏对应数据集
                        const index = legendItem.datasetIndex;
                        const ci = legend.chart;
                        const meta = ci.getDatasetMeta(index);
                        meta.hidden = meta.hidden === null ? !ci.data.datasets[index].hidden : null;
                        ci.update();
                    },
                },
                tooltip: {
                    backgroundColor: '#1E293B',
                    titleColor: '#E2E8F0',
                    bodyColor: '#E2E8F0',
                    borderColor: '#1E293B',
                    borderWidth: 1,
                    padding: 12,
                    callbacks: {
                        label: ctx => ctx.dataset.label + ': ¥' + ctx.parsed.y.toLocaleString(undefined, { minimumFractionDigits: 2 }),
                    },
                },
            },
        },
    });
}

function renderPieChart(holdings) {
    if (typeof Chart === 'undefined') return;
    const canvas = $('pieChart');
    if (!canvas) return;
    if (chartInstances.pie) { try { chartInstances.pie.destroy(); } catch (e) { /* ignore */ } chartInstances.pie = null; }
    chartInstances.pie = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: holdings.map(x => x.name),
            datasets: [{ data: holdings.map(x => x.current_total), backgroundColor: genColors(holdings.length), borderWidth: 0 }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#E2E8F0', padding: 12, font: { size: 12 } } } }, cutout: '60%' }
    });
}

async function renderLineChart(code, period, forceRefresh) {
    if (typeof Chart === 'undefined') return;
    const canvas = $('lineChart');
    if (!canvas) return;
    let d;
    try {
        d = await api(`/api/fund/${code}/nav${forceRefresh ? '?force=true' : ''}`);
    } catch (e) {
        if (e.name === 'AbortError') return;
        throw e;
    }
    if (!d || !d.data) return;
    const data = filterByPeriod(d.data, period || chartPeriod);
    const labels = data.map(x => x.日期);
    const values = data.map(x => x.单位净值);
    // 预先计算均分刻度位置（首尾必含，中间均分）
    const targetCount = { '1m': 7, '3m': 10, '6m': 12, '1y': 12 }[period] || 10;
    chartInstances.lineTickSet = new Set();
    for (let i = 0; i < targetCount; i++) {
        chartInstances.lineTickSet.add(Math.round(i * (labels.length - 1) / (targetCount - 1)));
    }

    if (chartInstances.line) {
        // 切页回来画布被 content.innerHTML 重建，旧 Chart 指向幽灵画布，无条件销毁重建
        try { chartInstances.line.destroy(); } catch (e) { /* ignore */ }
        chartInstances.line = null;
    }
    chartInstances.linePeriod = period;

    chartInstances.line = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '单位净值', data: values,
                borderColor: '#F0B90B', backgroundColor: 'rgba(199,136,60,0.06)',
                fill: true, tension: .3, pointRadius: 0, hoverRadius: 5, pointHitRadius: 10, borderWidth: 2,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#131A2B',
                    titleFont: { size: 12 },
                    bodyFont: { size: 13 },
                    padding: 10,
                    callbacks: {
                        label: ctx => ctx.parsed.y !== null ? `净值: ${ctx.parsed.y.toFixed(4)} 元` : ''
                    }
                }
            },
            scales: {
                y: { grid: { color: '#1E293B' }, ticks: { font: { size: 11 }, color: '#94A3B8' }, title: { display: true, text: '净值（元）', color: '#94A3B8', font: { size: 12 } } },
                x: {
                    grid: { display: false },
                    ticks: {
                        font: { size: 10 }, color: '#94A3B8',
                        maxRotation: 0,
                        autoSkip: false,
                        callback: function(val, idx) {
                            const label = this.getLabelForValue(val);
                            if (!label) return '';
                            if (chartInstances.lineTickSet?.has(val)) return label.slice(5);
                            return '';
                        }
                    }
                }
            }
        }
    });
}

// ====== 持仓 ======
async function renderPortfolio(el) {
    const data = await api('/api/portfolio');
    const h = data && data.holdings ? data.holdings : [];

    // 同步定投金额到当前日期（共用函数）
    const dcaInfo = await syncDcaHoldings(h);

    el.innerHTML = `
        <div style="margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap;">
            <button class="btn btn-primary" onclick="showAddHolding()"><i class="fas fa-plus"></i> 添加持仓</button>
            <button class="btn btn-outline" onclick="exportCsv()"><i class="fas fa-download"></i> 导出CSV</button>
        </div>
        ${h.length === 0 ? '<div class="empty"><i class="fas fa-box-open"></i><p>暂无持仓，点击上方按钮添加</p></div>' : `
        <div class="card"><div class="table-wrap"><table>
            <thead><tr><th>代码</th><th>名称</th><th>可用份额</th><th>平均成本</th><th>累计投入</th><th>最新净值</th><th>市值</th><th>收益</th><th>收益率</th><th>年化</th><th></th></tr></thead>
            <tbody>${h.map(x => {
                const isDca = x.total_invested != null;
                const info = dcaInfo[x.id];
                const invested = (isDca && info && info.expectedInvested > 0) ? info.expectedInvested : (isDca ? x.total_invested : x.cost_total);
                const stopped = info && info.isStopped;
                const statusBadge = isDca
                    ? (stopped
                        ? '<span style="font-size:10px;background:#64748B;color:#fff;padding:1px 6px;border-radius:3px;">⏸ 已终止</span>'
                        : '<span style="font-size:10px;background:#00C853;color:#fff;padding:1px 6px;border-radius:3px;">● 定投中</span>')
                    : '';
                const freqLabel = x.dca_frequency === 'daily' ? '天' : x.dca_frequency === 'weekly' ? '周' : '月';
                const dcaActionBtn = isDca
                    ? (stopped
                        ? `<br><button class="btn btn-outline btn-sm" onclick="resumeDca(${x.id})" style="margin-top:4px;font-size:11px;color:#00C853;">▶ 恢复投入</button>`
                        : `<br><button class="btn btn-outline btn-sm" onclick="stopDca(${x.id})" style="margin-top:4px;font-size:11px;color:#F04444;">⏹ 终止投入</button>`)
                    : '';
                const xirrHtml = isDca && x.xirr != null
                    ? `<span class="${tagCls(x.xirr)}">${fmtPct(x.xirr)}</span>`
                    : '<span style="color:#64748B;">--</span>';
                return `<tr>
                <td>${x.code}</td><td><strong>${x.name}</strong> ${statusBadge}<br>
                ${isDca && x.dca_start_date ? `<span style="font-size:11px;color:#94A3B8;">从 ${x.dca_start_date.slice(0,10)} 开始${stopped ? ' · 至 ' + x.dca_end_date.slice(0,10) : ''}</span>` : ''}
                ${isDca && x.dca_amount ? `<br><span style="font-size:11px;color:#94A3B8;">${x.dca_amount}元/${freqLabel}</span>` : ''}
                ${isDca && info && info.startNav ? `<br><span style="font-size:11px;color:#E2E8F0;">净值 ${info.startNav.toFixed(4)} → ${info.currentNav.toFixed(4)} <span class="${cls(info.currentNav - info.startNav)}">${((info.currentNav / info.startNav - 1) * 100).toFixed(1)}%</span></span>` : ''}
                ${dcaActionBtn}
                </td>
                <td>${fmt(x.shares)}</td>
                <td>${x.cost_nav.toFixed(4)}</td>
                <td>${fmtMoney(invested)}</td>
                <td class="${cls(x.profit)}">${x.current_nav.toFixed(4)}</td>
                <td class="${cls(x.profit)}">${fmtMoney(x.current_total)}</td>
                <td class="${cls(x.profit)}">${fmtMoney(x.profit)}</td>
                <td><span class="${tagCls(x.profit)}">${fmtPct(x.return_pct)}</span></td>
                <td>${xirrHtml}</td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="showEditHolding(${x.id})" style="margin-right:4px"><i class="fas fa-edit"></i></button>
                    <button class="btn btn-outline btn-sm" onclick="deleteHolding(${x.id})"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`;
            }).join('')}</tbody>
        </table></div></div>
        <div class="stats">
            <div class="card stat-card"><div class="stat-label">总投资成本</div><div class="stat-value" style="font-size:20px;">${fmtMoney(h.reduce((s,x)=>s+x.cost_total,0))}</div></div>
            <div class="card stat-card"><div class="stat-label">总市值</div><div class="stat-value" style="font-size:20px;">${fmtMoney(h.reduce((s,x)=>s+x.current_total,0))}</div></div>
            <div class="card stat-card"><div class="stat-label">总收益</div><div class="stat-value ${cls(h.reduce((s,x)=>s+x.profit,0))}" style="font-size:20px;">${fmtMoney(h.reduce((s,x)=>s+x.profit,0))}</div></div>
        </div>`}`;
}

// 终止定投
async function stopDca(id) {
    if (!confirm('确认终止该定投计划？终止后累计投入将冻结在当天。')) return;
    const res = await api(`/api/portfolio/${id}/stop-dca`, { method: 'POST' });
    if (res && res.stopped) { showToast('⏸ 定投已终止'); renderPage('portfolio'); }
    else { showToast('❌ 操作失败: ' + (res?.error || '未知错误')); }
}

// 恢复定投
async function resumeDca(id) {
    if (!confirm('确认恢复该定投计划？系统将补算终止期间的所有期数。')) return;
    const res = await api(`/api/portfolio/${id}/resume-dca`, { method: 'POST' });
    if (res && res.resumed) { showToast('▶ 定投已恢复'); renderPage('portfolio'); }
    else { showToast('❌ 操作失败: ' + (res?.error || '未知错误')); }
}

function showAddHolding() {
    const modal = document.createElement('div');
    modal.className = 'modal-overlay show';
    modal.id = 'addModal';
    modal.innerHTML = `
    <div class="modal-box">
        <div class="modal-header"><div class="modal-title"><i class="fas fa-plus"></i> 添加持仓</div><button class="modal-close" onclick="closeModal('addModal')">&times;</button></div>
        <div class="modal-body">
            <div class="form-group"><label>基金代码</label><input id="addCode" placeholder="如 005827" /></div>
            <div class="form-group">
                <label style="display:flex;gap:12px;align-items:center;">
                    <span>买入方式</span>
                    <span onclick="toggleDcaMode()" style="cursor:pointer;padding:2px 12px;border-radius:4px;font-size:12px;background:#1E293B;color:#E2E8F0;" id="dcaToggle">📅 定投模式</span>
                </label>
            </div>
            <div class="form-row">
                <div class="form-group" id="addSharesGroup"><label>可用份额</label><input id="addShares" type="number" step="0.01" min="0.01" /></div>
                <div class="form-group" id="addCostGroup"><label>成本单价</label><input id="addCost" type="number" step="0.0001" min="0.001" placeholder="买入时的净值" /></div>
            </div>
            <div class="form-group" id="addDcaGroup" style="display:none;">
                <div class="form-group"><label>定投前已投入金额（元）</label><input id="addDcaInitial" type="number" step="0.01" min="0" placeholder="如 10（前期单笔买入）" value="0" /></div>
                <div class="form-row">
                    <div class="form-group"><label>每期金额（元）</label><input id="addDcaAmt" type="number" step="1" min="1" placeholder="如 20" /></div>
                    <div class="form-group"><label>定投频率</label><select id="addDcaFreq"><option value="daily">每天</option><option value="weekly" selected>每周</option><option value="monthly">每月</option></select></div>
                </div>
                <div class="form-group"><label>定投开始日期</label><input id="addDcaDate" type="date" /></div>
                <div style="margin-top:8px;padding:10px;background:#1E293B;border-radius:6px;font-size:12px;color:#E2E8F0;">系统将根据定投计划自动计算投入金额和份额。如有之前单笔买入，填入「定投前已投入金额」即可。</div>
            </div>
        </div>
        <div class="modal-footer"><button class="btn btn-outline" onclick="closeModal('addModal')">取消</button><button class="btn btn-primary" onclick="submitHolding()">确认添加</button></div>
    </div>`;
    document.body.appendChild(modal);
    window._dcaMode = false;
}

function toggleDcaMode() {
    window._dcaMode = !window._dcaMode;
    const toggle = $('dcaToggle');
    const sharesGroup = $('addSharesGroup');
    const costGroup = $('addCostGroup');
    const dcaGroup = $('addDcaGroup');
    const costInput = $('addCost');
    if (window._dcaMode) {
        toggle.textContent = '💰 普通买入';
        toggle.style.background = '#F0B90B';
        toggle.style.color = '#fff';
        sharesGroup.style.display = 'none';
        costGroup.style.display = 'none';
        dcaGroup.style.display = 'block';
        costInput.required = false;
    } else {
        toggle.textContent = '📅 定投模式';
        toggle.style.background = '#1E293B';
        toggle.style.color = '#E2E8F0';
        sharesGroup.style.display = 'block';
        costGroup.style.display = 'block';
        dcaGroup.style.display = 'none';
        costInput.required = true;
    }
}

function closeModal(id) {
    const m = $(id); if (m) m.remove();
}

async function submitHolding() {
    const code = $('addCode').value.trim();
    let shares, cost, totalInvested = null, dcaStart = null, dcaAmt = null, dcaFreq = null;
    if (window._dcaMode) {
        dcaStart = $('addDcaDate').value || null;
        dcaAmt = parseFloat($('addDcaAmt').value) || null;
        dcaFreq = $('addDcaFreq').value || null;
        if (!dcaStart || !dcaAmt || !dcaFreq) { showToast('请填写完整的定投计划'); return; }
        showToast('⏳ 正在计算定投数据...');
        const navData = await api(`/api/fund/${code}/nav`);
        if (!navData || !navData.data) { showToast('获取净值失败'); return; }
        const startIdx = navData.data.findIndex(d => d.日期 >= dcaStart);
        if (startIdx < 0) { showToast('开始日期早于基金成立日'); return; }

        // 用净值交易日数量计算总期数（与 syncDcaHoldings 保持一致）
        const dcaToday = new Date();
        const navRecords = navData.data.slice(startIdx);
        let totalPeriods = 0;
        if (dcaFreq === 'daily') {
            totalPeriods = navRecords.length;
            // QDII T+2 确认，最后2个交易日未到账
            totalPeriods = Math.max(0, totalPeriods - 2);
            // 今天净值未公布但已是交易日 → 补 1 期
            if (navRecords.length > 0) {
                const last = navRecords[navRecords.length - 1].日期;
                const y2 = dcaToday.getFullYear(), m2 = dcaToday.getMonth() + 1, d2 = dcaToday.getDate();
                const todayLocal2 = y2 + '-' + String(m2).padStart(2, '0') + '-' + String(d2).padStart(2, '0');
                if (last < todayLocal2) {
                    const dow = dcaToday.getDay();
                    if (dow >= 1 && dow <= 5) totalPeriods += 1;
                }
            }
        } else if (dcaFreq === 'weekly') {
            totalPeriods = Math.max(0, Math.ceil(navRecords.length / 5));
        } else if (dcaFreq === 'monthly') {
            const months = new Set(navRecords.map(r => r.日期.slice(0, 7)));
            totalPeriods = months.size;
            // 本月尚无净值记录 → 补 1 期
            const y2 = dcaToday.getFullYear(), m2 = dcaToday.getMonth() + 1;
            const curMonth2 = y2 + '-' + String(m2).padStart(2, '0');
            if (!months.has(curMonth2)) totalPeriods += 1;
        }

        // 初始投入金额（如定投前单笔买入的 10 元）
        const dcaInitial = parseFloat($('addDcaInitial')?.value) || 0;
        totalInvested = totalPeriods * dcaAmt + dcaInitial;

        // 用净值数据逐期计算份额（只算已确认的 totalPeriods 期）
        let totalShares = 0;
        const confirmedNavs = navData.data.slice(startIdx, startIdx + totalPeriods);
        if (dcaFreq === 'daily') {
            confirmedNavs.forEach(d => { totalShares += dcaAmt / d.单位净值; });
        } else if (dcaFreq === 'weekly') {
            confirmedNavs.filter((_, i) => i % 5 === 0).forEach(d => { totalShares += dcaAmt / d.单位净值; });
        } else if (dcaFreq === 'monthly') {
            const seen = new Set();
            confirmedNavs
                .filter(d => { const m = d.日期.slice(0,7); if (seen.has(m)) return false; seen.add(m); return true; })
                .forEach(d => { totalShares += dcaAmt / d.单位净值; });
        }
        // 初始投入对应的份额：用首日净值估算
        if (dcaInitial > 0 && confirmedNavs.length > 0) {
            const initialNav = confirmedNavs[0]?.单位净值 || 1;
            totalShares += dcaInitial / initialNav;
        }
        shares = Math.round(totalShares * 100) / 100;
        cost = totalInvested / shares;
        showToast('✅ 定投计算完成');
    } else {
        shares = parseFloat($('addShares').value);
        if (!code || !shares) { showToast('请填写完整信息'); return; }
        cost = parseFloat($('addCost').value);
        if (!cost) { showToast('请填写成本单价'); return; }
    }
    const body = { code, shares, cost_nav: cost };
    if (totalInvested) { body.total_invested = totalInvested; body.dca_start_date = dcaStart; body.dca_amount = dcaAmt; body.dca_frequency = dcaFreq; body.dca_initial = dcaInitial; }
    const res = await api('/api/portfolio', { method: 'POST', body: JSON.stringify(body) });
    if (res && res.id) { showToast('✅ 已添加 ' + (res.name || code)); closeModal('addModal'); renderPage(currentPage); }
    else { showToast('❌ 添加失败: ' + (res?.error || '未知错误')); }
}

async function deleteHolding(id) {
    if (!confirm('确认删除该持仓？')) return;
    const res = await api(`/api/portfolio/${id}`, { method: 'DELETE' });
    if (res && res.deleted) { showToast('已删除'); renderPage(currentPage); }
}

async function showEditHolding(id) {
    const data = await api('/api/portfolio');
    if (!data || !data.holdings) return;
    const item = data.holdings.find(h => h.id === id);
    if (!item) return;

    const modal = document.createElement('div');
    modal.className = 'modal-overlay show';
    modal.id = 'editModal';
    const isDca = item.total_invested != null;
    modal.innerHTML = `
    <div class="modal-box">
        <div class="modal-header">
            <div class="modal-title"><i class="fas fa-edit"></i> 修改持仓</div>
            <button class="modal-close" onclick="closeModal('editModal')">&times;</button>
        </div>
        <div class="modal-body">
            <div style="margin-bottom:16px">
                <strong>${item.name}</strong> <span style="color:#94A3B8;font-size:13px;">${item.code}</span>
                ${isDca ? '<span class="tag-neutral" style="font-size:10px;margin-left:6px;">定投</span>' : ''}
            </div>
            <div class="form-row">
                <div class="form-group"><label>可用份额</label><input id="editShares" type="number" step="0.01" min="0.01" value="${item.shares}" /></div>
                <div class="form-group"><label>${isDca ? '平均成本' : '成本单价'}</label><input id="editCost" type="number" step="0.0001" min="0.001" value="${item.cost_nav}" /></div>
            </div>
            ${isDca ? `<div class="form-group"><label>定投前已投入（元）</label><input id="editDcaInitial" type="number" step="0.01" min="0" value="${item.dca_initial || 0}" /></div>
            <div class="form-group"><label>累计投入金额（元）</label><input id="editInvest" type="number" step="0.01" min="0.01" value="${item.total_invested}" /></div>
            <div class="form-row">
                <div class="form-group"><label>每期金额（元）</label><input id="editDcaAmt" type="number" step="1" min="1" value="${item.dca_amount || ''}" /></div>
                <div class="form-group"><label>定投频率</label><select id="editDcaFreq"><option value="daily" ${item.dca_frequency==='daily'?'selected':''}>每天</option><option value="weekly" ${item.dca_frequency==='weekly'?'selected':''}>每周</option><option value="monthly" ${item.dca_frequency==='monthly'?'selected':''}>每月</option></select></div>
            </div>
            <div class="form-group"><label>定投开始日期</label><input id="editDcaDate" type="date" value="${item.dca_start_date || ''}" /></div>` : ''}
            <div class="form-group"><label>备注</label><input id="editNotes" value="${item.notes || ''}" /></div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-outline" onclick="closeModal('editModal')">取消</button>
            <button class="btn btn-primary" onclick="submitEdit(${id})">保存修改</button>
        </div>
    </div>`;
    document.body.appendChild(modal);
}

async function submitEdit(id) {
    const shares = parseFloat($('editShares').value);
    const cost = parseFloat($('editCost').value);
    const notes = $('editNotes')?.value || '';
    const investInput = $('editInvest');
    const totalInvested = investInput ? parseFloat(investInput.value) : null;
    const dcaAmtInput = $('editDcaAmt');
    const dcaAmt = dcaAmtInput ? parseFloat(dcaAmtInput.value) : null;
    const dcaFreqInput = $('editDcaFreq');
    const dcaFreq = dcaFreqInput ? dcaFreqInput.value : null;
    const dcaDateInput = $('editDcaDate');
    const dcaDate = dcaDateInput ? dcaDateInput.value : null;
    if (!shares || !cost) { showToast('请填写完整信息'); return; }
    const body = { shares, cost_nav: cost, notes };
    if (totalInvested) body.total_invested = totalInvested;
    if (dcaAmt) { body.dca_amount = dcaAmt; body.dca_frequency = dcaFreq; body.dca_start_date = dcaDate; }
    const dcaInitialEdit = $('editDcaInitial');
    if (dcaInitialEdit) { body.dca_initial = parseFloat(dcaInitialEdit.value) || 0; }
    const res = await api(`/api/portfolio/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    if (res && res.updated) { showToast('✅ 修改成功'); closeModal('editModal'); renderPage(currentPage); }
    else { showToast('❌ 修改失败'); }
}

// ====== 自选列表 ======
async function renderWatchlist(el) {
    const data = await api('/api/watchlist');
    if (!data || !data.watchlist || data.watchlist.length === 0) {
        el.innerHTML = `
            <div class="empty"><i class="fas fa-star"></i><p>还没有自选基金</p></div>
            <div style="text-align:center;margin-top:16px;">
                <button class="btn btn-primary" onclick="document.querySelector('[data-page=screener]').click()">
                    <i class="fas fa-filter"></i> 去筛选基金
                </button>
            </div>`;
        return;
    }
    const items = data.watchlist;

    el.innerHTML = `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <span style="font-size:13px;color:#94A3B8;">共 ${items.length} 只自选基金</span>
        </div>
        <div class="watchlist-grid">
            ${items.map(w => {
                const chgCls = (w.daily_change || 0) >= 0 ? 'text-up' : 'text-down';
                const chgIcon = (w.daily_change || 0) >= 0 ? '▲' : '▼';
                const targetHtml = w.target_price
                    ? `<span style="font-size:11px;color:#94A3B8;">提醒价: ¥${w.target_price.toFixed(4)}</span>`
                    : '';
                return `<div class="card watchlist-card" data-id="${w.id}">
                    <div class="watchlist-card-header">
                        <div>
                            <strong style="font-size:15px;">${esc(w.name)}</strong>
                            <span style="font-size:12px;color:#94A3B8;margin-left:6px;">${w.code}</span>
                            ${w.fund_type ? `<span class="tag tag-neutral" style="font-size:10px;">${w.fund_type}</span>` : ''}
                        </div>
                        <button class="btn btn-sm btn-outline" onclick="removeWatchlist(${w.id}, '${esc(w.name)}')" style="color:#F04444;border-color:#F04444;">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div class="watchlist-card-body">
                        <div class="watchlist-nav">
                            <div class="watchlist-nav-value ${chgCls}">${w.current_nav != null ? w.current_nav.toFixed(4) : '--'}</div>
                            <div class="watchlist-nav-change ${chgCls}">${chgIcon} ${w.daily_change != null ? Math.abs(w.daily_change).toFixed(2) + '%' : '--'}</div>
                        </div>
                        <div class="watchlist-meta">
                            ${targetHtml}
                            ${w.notes ? `<span style="font-size:11px;color:#64748B;">📝 ${esc(w.notes)}</span>` : ''}
                        </div>
                    </div>
                    <div class="watchlist-card-actions">
                        <button class="btn btn-sm btn-primary" onclick="goWatchlistAnalysis('${w.code}')"><i class="fas fa-search"></i> 分析</button>
                        <button class="btn btn-sm btn-outline" onclick="goWatchlistCompare('${w.code}')"><i class="fas fa-balance-scale"></i> 对比</button>
                        <button class="btn btn-sm btn-ghost" onclick="showWatchlistEdit(${w.id})"><i class="fas fa-pen"></i></button>
                    </div>
                </div>`;
            }).join('')}
        </div>`;
}

function goWatchlistAnalysis(code) {
    goAnalysis(code);
}

function goWatchlistCompare(code) {
    // 切换到对比页，预填 code
    qsa('.nav-item').forEach(n => n.classList.remove('active'));
    qsa('.nav-item[data-page="compare"]')[0].classList.add('active');
    $('pageTitle').textContent = '对比';
    $('pageSubtitle').textContent = '多基金关键指标对比';
    if (window.innerWidth <= 640) $('sidebar').classList.remove('open');
    renderPage('compare');
    setTimeout(() => {
        const input = $('compareCodeInput');
        if (input) { input.value = code; }
    }, 200);
}

async function removeWatchlist(id, name) {
    if (!confirm(`确认移除「${name}」自选？`)) return;
    const res = await api(`/api/watchlist/${id}`, { method: 'DELETE' });
    if (res && res.deleted) {
        showToast('已移除自选');
        renderPage('watchlist');
    }
}

function showWatchlistEdit(id) {
    const card = document.querySelector(`.watchlist-card[data-id="${id}"]`);
    if (!card) return;
    const notesEl = document.createElement('div');
    notesEl.style.cssText = 'margin-top:8px;';
    notesEl.innerHTML = `
        <div style="display:flex;gap:8px;">
            <input id="wlEditNotes" class="watchlist-edit-input" placeholder="备注" value="${card.querySelector('.watchlist-meta span')?.textContent?.replace('📝 ','') || ''}" style="flex:1;padding:6px 12px;border-radius:6px;border:1px solid #1E293B;background:#0B0E17;color:#E2E8F0;font-size:13px;" />
            <input id="wlEditPrice" type="number" step="0.0001" placeholder="提醒价" value="" style="width:100px;padding:6px 12px;border-radius:6px;border:1px solid #1E293B;background:#0B0E17;color:#E2E8F0;font-size:13px;" />
            <button class="btn btn-sm btn-primary" onclick="submitWatchlistEdit(${id})">保存</button>
        </div>`;
    // 替换原有 action 栏
    const actions = card.querySelector('.watchlist-card-actions');
    if (actions) {
        actions.style.display = 'none';
        card.querySelector('.watchlist-card-body').after(notesEl);
    }
}

async function submitWatchlistEdit(id) {
    const notes = $('wlEditNotes')?.value || '';
    const targetPrice = $('wlEditPrice')?.value || null;
    const body = { notes };
    if (targetPrice) body.target_price = parseFloat(targetPrice);
    const res = await api(`/api/watchlist/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    if (res && res.updated) {
        showToast('✅ 已更新');
        renderPage('watchlist');
    } else {
        showToast('更新失败');
    }
}

// ====== 自选列表辅助函数 ======
let _watchlistCache = null;

async function _ensureWatchlistCache() {
    if (_watchlistCache === null) {
        const data = await api('/api/watchlist');
        _watchlistCache = (data && data.watchlist) || [];
    }
    return _watchlistCache;
}

function _isInWatchlist(code) {
    return _watchlistCache ? _watchlistCache.some(w => w.code === code) : false;
}

async function toggleWatchlistCheck(code, name, fundType) {
    const inList = _isInWatchlist(code);
    if (inList) {
        // 从自选移除
        const w = _watchlistCache.find(w => w.code === code);
        if (w) {
            const res = await api(`/api/watchlist/${w.id}`, { method: 'DELETE' });
            if (res && res.deleted) {
                _watchlistCache = _watchlistCache.filter(x => x.code !== code);
                showToast('已移除自选 ❌');
                // 刷新当前页面让按钮状态更新
                const page = currentPage;
                if (page === 'analysis') searchFund();  // 刷新分析页
                else if (page === 'watchlist') renderPage('watchlist');
            }
        }
    } else {
        // 添加自选
        const res = await api('/api/watchlist', {
            method: 'POST',
            body: JSON.stringify({ code, notes: '' }),
        });
        if (res && res.id) {
            _watchlistCache = null;  // 下次重新获取
            showToast('已加入自选 ⭐');
            const page = currentPage;
            if (page === 'analysis') searchFund();
            else if (page === 'watchlist') renderPage('watchlist');
        }
    }
}

function goAnalysis(code) {
    // 切换到分析页面并填入基金代码
    qsa('.nav-item').forEach(n => n.classList.remove('active'));
    qsa('.nav-item[data-page="analysis"]')[0].classList.add('active');
    $('pageTitle').textContent = '分析';
    $('pageSubtitle').textContent = '基金深度分析';
    if (window.innerWidth <= 640) $('sidebar').classList.remove('open');
    renderPage('analysis');
    // 延迟等页面渲染后再填入代码
    setTimeout(() => {
        const input = $('searchCode');
        if (input) { input.value = code; searchFund(); }
    }, 200);
}

// ====== 分析 ======
async function renderAnalysis(el) {
    el.innerHTML = `
        <div class="form-inline" style="margin-bottom:16px">
            <div class="form-group" style="flex:1;max-width:320px;margin-bottom:0"><input id="searchCode" placeholder="输入基金代码，如 005827" onkeydown="if(event.key==='Enter') searchFund()" /></div>
            <button class="btn btn-primary" onclick="searchFund()"><i class="fas fa-search"></i> 查询</button>
        </div>
        <div id="analysisResult"></div>`;
}

async function searchFund() {
    const code = $('searchCode').value.trim();
    if (!code) return;
    const el = $('analysisResult');
    el.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';

    const info = await api(`/api/fund/${code}`);
    if (!info || info.error) { el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-circle"></i><p>未找到该基金</p></div>'; return; }

    const nav = await api(`/api/fund/${code}/nav`);
    if (!nav || !nav.data) { el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-circle"></i><p>获取净值失败</p></div>'; return; }

    const analysis = await api(`/api/analysis/${code}`);

    const latest = nav.data[0];
    const prev = nav.data[1] || latest;
    const chg = latest.单位净值 - prev.单位净值;
    const chgPct = prev.单位净值 > 0 ? chg / prev.单位净值 * 100 : 0;

    el.innerHTML = `
        <div class="card" style="display:flex;justify-content:space-between;align-items:center;">
            <div><div style="font-size:20px;font-weight:700;">${info.fund_name || code}</div>
            <div style="font-size:13px;color:#94A3B8;margin-top:4px;">${code} · ${info.fund_type||''} · 成立 ${info.establish_date||''}</div>
            <div style="font-size:13px;color:#94A3B8;">基金经理: ${info.manager||''}</div></div>
            <div style="text-align:right;">
                <button class="btn btn-sm ${_isInWatchlist(code) ? 'btn-primary' : 'btn-outline'}" onclick="toggleWatchlistCheck('${code}', '${esc(info.fund_name || code)}', '${esc(info.fund_type || '')}')" style="margin-bottom:6px;">
                    <i class="fas fa-star"></i> ${_isInWatchlist(code) ? '已自选' : '自选'}
                </button>
                <div style="font-size:28px;font-weight:700;">${latest.单位净值.toFixed(4)}</div>
                <div style="font-size:15px;${cls(chg)}">${chg >= 0 ? '+' : ''}${chg.toFixed(4)} (${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)</div>
            </div>
        </div>
        ${analysis ? `
        <div class="metrics">
            ${[
                ['年化收益', analysis.indicators.annual_return + '%', cls(analysis.indicators.annual_return)],
                ['年化波动', analysis.indicators.annual_volatility + '%', ''],
                ['最大回撤', analysis.indicators.max_drawdown + '%', 'text-down'],
                ['夏普比率', analysis.indicators.sharpe_ratio, ''],
                ['近1月', (analysis.indicators.return_1m != null ? analysis.indicators.return_1m + '%' : 'N/A'), cls(analysis.indicators.return_1m || 0)],
                ['近3月', (analysis.indicators.return_3m != null ? analysis.indicators.return_3m + '%' : 'N/A'), cls(analysis.indicators.return_3m || 0)],
                ['近1年', (analysis.indicators.return_1y != null ? analysis.indicators.return_1y + '%' : 'N/A'), cls(analysis.indicators.return_1y || 0)],
            ].map(x => `<div class="card metric-card"><div class="stat-label">${x[0]}</div><div class="m-value ${x[2]||''}">${x[1]}</div></div>`).join('')}
        </div>
        ` : ''}
        <div class="card"><div class="card-title"><i class="fas fa-chart-line"></i> 净值走势
        <span style="margin-left:auto">${['1月','3月','6月','1年'].map((l,i) => `<span class="period-btn ${detailPeriod === ['1m','3m','6m','1y'][i] ? 'active' : ''}" data-period="${['1m','3m','6m','1y'][i]}" onclick="setDetailPeriod('${['1m','3m','6m','1y'][i]}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${detailPeriod === ['1m','3m','6m','1y'][i] ? 'background:#F0B90B;color:#fff;' : 'background:#1E293B;color:#E2E8F0;'}margin-left:4px;">${l}</span>`).join('')}</span>
        </div><div class="chart-wrapper"><canvas id="detailChart"></canvas></div></div>
        ${analysis && analysis.signals && analysis.signals.summary ? `
        <div class="card"><div class="card-title"><i class="fas fa-chart-bar"></i> 技术信号</div>
        <div class="pred-signals">${analysis.signals.summary.map(s => `<span class="tag-${s.type === 'up' ? 'up' : s.type === 'down' ? 'down' : 'neutral'}">${s.label}</span>`).join('')}</div></div>
        ` : ''}
        ${analysis && analysis.score ? `
        <div class="card" style="border-left:3px solid ${analysis.score.total_score >= 70 ? '#F04444' : analysis.score.total_score >= 50 ? '#F0B90B' : '#00C853'};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div><div class="card-title" style="margin-bottom:4px;"><i class="fas fa-star"></i> 智能评分</div>
                <div style="font-size:12px;color:#94A3B8;">${analysis.score.stars || ''} ${analysis.score.level || ''}</div></div>
                <div style="text-align:right;"><div style="font-size:28px;font-weight:700;color:#F0B90B;">${analysis.score.total_score}</div><div style="font-size:12px;color:#94A3B8;">/ 100</div></div>
            </div>
            <div style="margin-top:12px;display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:#E2E8F0;">
                ${Object.entries(analysis.score.dimensions || {}).map(([k,v]) => `<span>${k}: <strong>${v.score}</strong> (${v.weight})</span>`).join('')}
            </div>
            <div style="margin-top:8px;font-size:14px;font-weight:500;">建议: <span style="color:${analysis.score.total_score >= 70 ? '#F04444' : analysis.score.total_score >= 50 ? '#F0B90B' : '#00C853'}">${analysis.score.action}</span></div>
        </div>` : ''}`;

    window._detailNavData = nav.data;
    setTimeout(() => renderDetailChart(nav.data, detailPeriod), 50);
}

function renderDetailChart(data, period) {
    if (typeof Chart === 'undefined') return;
    const canvas = $('detailChart');
    if (!canvas) return;
    data = filterByPeriod(data, period || detailPeriod);
    const labels = data.map(x => x.日期);
    const values = data.map(x => x.单位净值);
    // 预先计算均分刻度位置（首尾必含，中间均分）
    const targetCount = { '1m': 7, '3m': 10, '6m': 12, '1y': 12 }[period] || 10;
    chartInstances.detailTickSet = new Set();
    for (let i = 0; i < targetCount; i++) {
        chartInstances.detailTickSet.add(Math.round(i * (labels.length - 1) / (targetCount - 1)));
    }

    if (chartInstances.detail) {
        // 画布可能已被 searchFund 替换（innerHTML 重建），旧 Chart 指向幽灵画布
        if (chartInstances.detail.canvas !== canvas) {
            chartInstances.detail.destroy();
            chartInstances.detail = null;
        } else {
            chartInstances.detailPeriod = period;
            chartInstances.detail.data.labels = labels;
            chartInstances.detail.data.datasets[0].data = values;
            chartInstances.detail.update();
            return;
        }
    }
    chartInstances.detailPeriod = period;
    chartInstances.detail = new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{ label: '单位净值', data: values, borderColor: '#F0B90B', backgroundColor: 'rgba(199,136,60,0.06)', fill: true, tension: .3, pointRadius: 0, hoverRadius: 5, pointHitRadius: 10, borderWidth: 2 }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#131A2B',
                    titleFont: { size: 12 },
                    bodyFont: { size: 13 },
                    padding: 10,
                    callbacks: {
                        label: ctx => ctx.parsed.y !== null ? `净值: ${ctx.parsed.y.toFixed(4)} 元` : ''
                    }
                }
            },
            scales: {
                y: { grid: { color: '#1E293B' }, ticks: { font: { size: 11 }, color: '#94A3B8' }, title: { display: true, text: '净值（元）', color: '#94A3B8', font: { size: 12 } } },
                x: {
                    grid: { display: false },
                    ticks: {
                        font: { size: 10 }, color: '#94A3B8',
                        maxRotation: 0,
                        autoSkip: false,
                        callback: function(val, idx) {
                            const label = this.getLabelForValue(val);
                            if (!label) return '';
                            if (chartInstances.detailTickSet?.has(val)) return label.slice(5);
                            return '';
                        }
                    }
                }
            }
        }
    });
}

// ====== 智能预测 ======
async function renderPredict(el) {
    const data = await api('/api/portfolio');
    if (!data || !data.holdings || data.holdings.length === 0) {
        el.innerHTML = '<div class="empty"><i class="fas fa-box-open"></i><p>暂无持仓，去「持仓」页面添加</p></div>';
        return;
    }

    const scores = [];
    for (const h of data.holdings) {
        const a = await api(`/api/analysis/${h.code}`);
        if (a && a.score) scores.push({ ...h, analysis: a });
    }

    const avg = scores.length > 0 ? Math.round(scores.reduce((s, x) => s + x.analysis.score.total_score, 0) / scores.length) : 0;
    const buyN = scores.filter(x => x.analysis.score.action.includes('买入')).length;

    el.innerHTML = `
        <div class="card" style="display:flex;justify-content:space-between;align-items:center;">
            <div><div class="stat-label">组合综合评分</div><div style="font-size:32px;font-weight:700;color:#F0B90B;">${avg} <span style="font-size:14px;color:#94A3B8;">/ 100</span></div></div>
            <div style="text-align:center;"><div style="font-size:20px;">${avg >= 70 ? '⭐⭐⭐⭐' : avg >= 50 ? '⭐⭐⭐' : '⭐⭐'}</div><div style="font-size:14px;font-weight:600;">${avg >= 70 ? '良好' : avg >= 50 ? '一般' : '较差'}</div></div>
            <div style="text-align:right;">
                <div class="stat-label">建议操作</div><div style="font-size:16px;font-weight:600;color:#F04444;">买入 ${buyN} 只</div>
                <button class="btn btn-primary btn-sm" onclick="sendReport()" style="margin-top:8px;"><i class="fas fa-envelope"></i> 发送报告</button>
            </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        ${scores.map(x => {
            const sc = x.analysis.score;
            const sig = x.analysis.signals;
            const action = sc.action;
            const border = action.includes('买入') ? '#F04444' : action.includes('减仓') || action.includes('卖出') ? '#00C853' : '#F0B90B';
            const badge = action.includes('买入') ? 'tag-up' : action.includes('减仓') || action.includes('卖出') ? 'tag-down' : 'tag-neutral';
            const sigs = sig && sig.summary ? sig.summary.map(s => `<span class="tag-${s.type === 'up' ? 'up' : s.type === 'down' ? 'down' : 'neutral'}" style="margin:2px 4px 2px 0;">${s.label}</span>`).join('') : '';
            const dims = sc.dimensions ? Object.entries(sc.dimensions).map(([k,v]) => `${k} ${v.score}`).join(' · ') : '';
            return `<div class="card" style="border-left:3px solid ${border};">
                <div class="pred-header"><div><strong style="font-size:15px;">${x.name}</strong> <span style="font-size:12px;color:#94A3B8;">${x.code}</span></div>
                <div style="display:flex;align-items:center;gap:12px;"><div class="pred-score"><div class="num">${sc.total_score}</div><div class="stat-label">/100</div></div><span class="${badge}" style="padding:4px 14px;font-size:13px;">${action}</span></div></div>
                <div style="margin:8px 0;font-size:12px;color:#E2E8F0;">${dims}</div>
                <div style="margin:8px 0;font-size:12px;color:#E2E8F0;">年化 ${x.analysis.indicators.annual_return || 'N/A'}% · 回撤 ${x.analysis.indicators.max_drawdown || 'N/A'}%</div>
                ${sigs ? `<div class="pred-signals">${sigs}</div>` : ''}
            </div>`;
        }).join('')}
        </div>
        <div class="card" style="margin-top:16px;">
            <div class="card-title"><i class="fas fa-info-circle"></i> 评分等级对照</div>
            <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;text-align:center;font-size:12px;">
                <div><div style="background:#F04444;color:#fff;padding:4px;border-radius:4px;font-weight:600;">90-100</div><div style="color:#F04444;margin-top:4px;">优质</div><div style="color:#F04444;">强烈买入</div></div>
                <div><div style="background:#F0B90B;color:#fff;padding:4px;border-radius:4px;font-weight:600;">70-89</div><div style="color:#F0B90B;margin-top:4px;">良好</div><div style="color:#F04444;">推荐买入</div></div>
                <div><div style="background:#F0B90B;color:#fff;padding:4px;border-radius:4px;font-weight:600;">50-69</div><div style="color:#F0B90B;margin-top:4px;">一般</div><div style="color:#F0B90B;">观望/定投</div></div>
                <div><div style="background:#00C853;color:#fff;padding:4px;border-radius:4px;font-weight:600;">30-49</div><div style="color:#00C853;margin-top:4px;">较差</div><div style="color:#00C853;">建议减仓</div></div>
                <div><div style="background:#555;color:#fff;padding:4px;border-radius:4px;font-weight:600;">0-29</div><div style="color:#555;margin-top:4px;">差质</div><div style="color:#555;">建议卖出</div></div>
            </div>
        </div>`;
}

let _lastReportTime = 0;
async function sendReport() {
    const email = window._emailAddr || $('emailAddr')?.value;
    if (!email) { showToast('请先在「设置」页面配置接收邮箱'); return; }
    const elapsed = Date.now() - _lastReportTime;
    if (elapsed < 30000) {
        showToast(`⏳ 请 ${Math.ceil((30000 - elapsed)/1000)} 秒后再发送`);
        return;
    }
    _lastReportTime = Date.now();
    const res = await api('/api/send-report', {
        method: 'POST',
        body: JSON.stringify({ email })
    });
    showToast(res?.message || '请求失败');
}

// ====== 工具 ======
function renderTools(el) {
    el.innerHTML = `
    <div class="card" style="max-width:600px;">
        <div class="card-title"><i class="fas fa-calculator"></i> 定投计算器</div>
        <div class="form-group"><label>每月定投金额（元）</label><input id="dcaMonthly" type="number" value="1000" min="1" /></div>
        <div class="form-row">
            <div class="form-group"><label>定投年限</label><input id="dcaYears" type="number" value="5" min="1" /></div>
            <div class="form-group"><label>预期年化收益率（%）</label><input id="dcaRate" type="number" value="8" step="0.5" /></div>
        </div>
        <button class="btn btn-primary" onclick="calcDCA()"><i class="fas fa-calculator"></i> 计算</button>
        <div id="dcaResult" style="text-align:center;padding:20px 0 0;"></div>
    </div>`;
}

function calcDCA() {
    const monthly = parseFloat($('dcaMonthly').value) || 0;
    const years = parseFloat($('dcaYears').value) || 0;
    const rate = parseFloat($('dcaRate').value) || 0;
    if (!monthly || !years) { showToast('请填写完整'); return; }
    const months = years * 12;
    const mr = rate / 100 / 12; let total;
    if (mr > 0) { total = monthly * ((Math.pow(1 + mr, months) - 1) / mr) * (1 + mr); }
    else { total = monthly * months; }
    const principal = monthly * months;
    const profit = total - principal;
    $('dcaResult').innerHTML = `
        <div style="font-size:13px;color:#94A3B8;">预计最终总资产</div>
        <div style="font-size:40px;font-weight:700;color:#F0B90B;">${fmtMoney(total)}</div>
        <div style="font-size:14px;color:#E2E8F0;margin-top:8px;">本金 <strong>${fmtMoney(principal)}</strong> · 收益 <strong style="color:#F04444;">${fmtMoney(profit)}</strong></div>
        <div style="font-size:12px;color:#94A3B8;">月投 ${fmtMoney(monthly)} · ${years}年 · ${rate}%</div>`;
}

// ====== 基金对比 ======
async function renderCompare(el) {
    // 获取当前持仓作为默认候选
    let holdings = [];
    try {
        const portfolioData = await api('/api/portfolio');
        if (portfolioData && portfolioData.holdings) {
            holdings = portfolioData.holdings;
        }
    } catch (e) { /* 静默失败 */ }

    el.innerHTML = `
        <div class="card" style="max-width:800px;">
            <div class="card-title"><i class="fas fa-balance-scale"></i> 选择基金对比</div>
            <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:12px;">
                ${holdings.length > 0 ? holdings.map(h => `
                    <label class="compare-chip" style="display:inline-flex;align-items:center;gap:6px;padding:6px 14px;background:#1E293B;border-radius:20px;cursor:pointer;font-size:13px;transition:all .2s;">
                        <input type="checkbox" class="compare-cb" value="${h.code}" style="accent-color:#F0B90B;" />
                        ${h.name.length > 8 ? h.name.slice(0,8)+'..' : h.name}
                        <span style="color:#94A3B8;font-size:11px;">${h.code}</span>
                    </label>
                `).join('') : '<div style="color:#94A3B8;font-size:13px;">暂无持仓，可手动输入基金代码</div>'}
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
                <input id="compareManual" placeholder="手动输入代码，逗号分隔（如 005827,000001）" style="flex:1;padding:8px 12px;border:1px solid #1E293B;border-radius:6px;font-size:13px;" />
                <button class="btn btn-primary" onclick="doCompare()"><i class="fas fa-chart-bar"></i> 对比</button>
            </div>
        </div>
        <div id="compareResult" style="margin-top:16px;"></div>`;
}

async function doCompare() {
    // 收集选中的持仓代码
    const checked = Array.from(document.querySelectorAll('.compare-cb:checked')).map(cb => cb.value);
    // 收集手动输入的代码
    const manualInput = ($('compareManual') || {}).value || '';
    const manualCodes = manualInput.split(',').map(c => c.trim()).filter(Boolean);

    const codes = [...new Set([...checked, ...manualCodes])];
    if (codes.length < 2) {
        showToast('请至少选择 2 只基金进行对比');
        return;
    }
    if (codes.length > 10) {
        showToast('最多对比 10 只基金');
        return;
    }

    const el = $('compareResult');
    el.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';

    try {
        const data = await api('/api/analysis/compare', {
            method: 'POST',
            body: JSON.stringify({ codes })
        });

        if (!data || !data.results || data.results.length === 0) {
            el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-triangle"></i><p>对比分析失败</p></div>';
            return;
        }

        const r = data.results;
        const n = r.length;

        // 雷达图数据
        const radarLabels = ['年化收益', '夏普比率', '评分', '抗回撤', '性价比'];
        const radarColors = ['#F0B90B','#00C897','#00C853','#2196f3','#9c27b0','#ff5722','#607d8b','#795548','#00bcd4','#e91e63'];

        // 归一化雷达数据
        function normVal(arr, val) {
            if (val == null) return 0;
            const max = Math.max(...arr.filter(v => v != null), 0);
            const min = Math.min(...arr.filter(v => v != null), 0);
            if (max === min) return 50;
            return Math.round((val - min) / (max - min) * 80 + 10);
        }

        const annualReturns = r.map(x => x.annual_return);
        const sharps = r.map(x => x.sharpe_ratio);
        const scores = r.map(x => x.total_score);
        const drawdowns = r.map(x => x.max_drawdown != null ? -x.max_drawdown : null); // 负回撤越小越好
        // 性价比 = 年化收益 / 最大回撤绝对值
        const costEffs = r.map(x => {
            if (x.annual_return != null && x.max_drawdown != null && x.max_drawdown !== 0)
                return x.annual_return / Math.abs(x.max_drawdown);
            return null;
        });

        const datasets = r.map((x, i) => ({
            label: x.name || x.code,
            data: [
                normVal(annualReturns, x.annual_return),
                normVal(sharps, x.sharpe_ratio),
                normVal(scores, x.total_score),
                normVal(drawdowns, x.max_drawdown != null ? -x.max_drawdown : null),
                normVal(costEffs, costEffs[i]),
            ],
            borderColor: radarColors[i % radarColors.length],
            backgroundColor: radarColors[i % radarColors.length] + '20',
            pointBackgroundColor: radarColors[i % radarColors.length],
            borderWidth: 2,
        }));

        // 构建对比表格
        let tableHtml = `
        <div class="card" style="margin-top:16px;">
            <div class="card-title"><i class="fas fa-table"></i> 核心指标对比</div>
            <div class="table-wrap" style="overflow-x:auto;">
            <table class="compare-table">
                <thead><tr>
                    <th style="position:sticky;left:0;background:#1E293B;z-index:1;">指标</th>
                    ${r.map(x => `<th>${esc(x.name || x.code)}<br><span style="font-weight:400;font-size:11px;color:#94A3B8;">${x.code}</span></th>`).join('')}
                </tr></thead>
                <tbody>
                    ${[
                        ['综合评分', 'total_score', v => v != null ? v + '分' : '--', true],
                        ['评级', 'level', v => v || '--', false],
                        ['操作建议', 'action', v => v || '--', false],
                        ['星级', 'stars', v => v || '--', false],
                        ['基金类型', 'type', v => v || '--', false],
                        ['年化收益率', 'annual_return', v => v != null ? fmtPct(v) : '--', true],
                        ['年化波动率', 'annual_volatility', v => v != null ? v.toFixed(2) + '%' : '--', false],
                        ['最大回撤', 'max_drawdown', v => v != null ? v.toFixed(2) + '%' : '--', true],
                        ['夏普比率', 'sharpe_ratio', v => v != null ? v.toFixed(2) : '--', true],
                        ['索提诺比率', 'sortino_ratio', v => v != null ? v.toFixed(2) : '--', false],
                        ['卡玛比率', 'calmar_ratio', v => v != null ? v.toFixed(2) : '--', false],
                        ['近1月收益', 'return_1m', v => v != null ? fmtPct(v) : '--', true],
                        ['近3月收益', 'return_3m', v => v != null ? fmtPct(v) : '--', true],
                        ['近1年收益', 'return_1y', v => v != null ? fmtPct(v) : '--', true],
                        ['RSI', 'rsi', v => v != null ? v.toFixed(1) : '--', false],
                        ['RSI信号', 'rsi_signal', v => v || '--', false],
                    ].map(([label, key, fmt, highlight]) => {
                        const vals = r.map(x => x[key]);
                        const bestIdx = highlight ? vals.reduce((best, v, i, arr) => {
                            if (v == null) return best;
                            if (best === -1) return i;
                            // 回撤、波动率越小越好；其余越大越好
                            const smallerBetter = ['max_drawdown', 'annual_volatility'].includes(key);
                            return smallerBetter ? (v < arr[best] ? i : best) : (v > arr[best] ? i : best);
                        }, -1) : -1;
                        return `<tr>
                            <td style="position:sticky;left:0;background:#0B0E17;z-index:1;font-weight:500;white-space:nowrap;">${label}</td>
                            ${r.map((x, i) => `<td class="${i === bestIdx && highlight ? 'best-val' : ''}" style="${i === bestIdx && highlight ? 'font-weight:700;' : ''}">${fmt(x[key])}</td>`).join('')}
                        </tr>`;
                    }).join('')}
                </tbody>
            </table>
            </div>
        </div>`;

        // 错误提示
        const errorsHtml = data.errors && data.errors.length > 0
            ? `<div class="card" style="margin-top:12px;border-left:3px solid #F0B90B;">
                <div style="font-size:13px;color:#F0B90B;">
                    <i class="fas fa-exclamation-triangle"></i> 以下基金分析失败：
                    ${data.errors.map(e => esc(e.code) + (e.error ? ': ' + esc(e.error) : '')).join('；')}
                </div>
            </div>` : '';

        el.innerHTML = tableHtml + errorsHtml + `<div class="card"><div class="card-title"><i class="fas fa-chart-radar"></i> 指标雷达图</div><div class="chart-wrapper"><canvas id="compareRadar" style="max-height:400px;margin:0 auto;"></canvas></div></div>`;

        // 画雷达图
        setTimeout(() => {
            const canvas = $('compareRadar');
            if (!canvas || typeof Chart === 'undefined') return;
            if (chartInstances.compareRadar) {
                try { chartInstances.compareRadar.destroy(); } catch(e) { /* ignore */ }
            }
            chartInstances.compareRadar = new Chart(canvas, {
                type: 'radar',
                data: {
                    labels: radarLabels,
                    datasets: datasets,
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { color: '#E2E8F0', padding: 12, font: { size: 12 }, usePointStyle: true }
                        },
                        tooltip: {
                            backgroundColor: '#131A2B',
                            bodyFont: { size: 13 },
                            padding: 10,
                        }
                    },
                    scales: {
                        r: {
                            beginAtZero: true,
                            max: 100,
                            ticks: { stepSize: 20, font: { size: 10 }, color: '#94A3B8', backdropColor: 'transparent' },
                            grid: { color: '#1E293B' },
                            angleLines: { color: '#1E293B' },
                            pointLabels: { font: { size: 12 }, color: '#E2E8F0' }
                        }
                    }
                }
            });
        }, 100);

    } catch (e) {
        if (e.name === 'AbortError') return;
        el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-triangle"></i><p>对比分析加载失败</p></div>';
    }
}

// ====== 交易记录 ======
async function renderTransactions(el) {
    el.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
    try {
        const [txData, holdData] = await Promise.all([
            api('/api/transactions'),
            api('/api/portfolio/holdings')
        ]);

        const txs = (txData && txData.transactions) || [];
        const holdings = (holdData && holdData.holdings) || [];
        const summary = (holdData && holdData.summary) || {};

        // 按基金分组的持仓汇总
        let holdingMap = {};
        holdings.forEach(h => { holdingMap[h.code] = h; });

        el.innerHTML = `
        <div style="margin-bottom:16px;display:flex;gap:8px;flex-wrap:wrap;">
            <button class="btn btn-primary" onclick="showAddTx()"><i class="fas fa-plus"></i> 记一笔</button>
            ${holdings.length > 0 ? `<span style="font-size:12px;color:#94A3B8;align-self:center;">${summary.fund_count || 0} 只持仓 · XIRR ${summary.portfolio_xirr != null ? summary.portfolio_xirr + '%' : '--'}</span>` : ''}
        </div>

        ${holdings.length > 0 ? `
        <div class="card" style="margin-bottom:16px;">
            <div class="card-title"><i class="fas fa-wallet"></i> 当前持仓（从交易流水汇总）</div>
            <div class="table-wrap"><table>
                <thead><tr><th>基金</th><th>份额</th><th>成本</th><th>最新净值</th><th>市值</th><th>累计收益</th><th>XIRR年化</th><th>交易笔数</th></tr></thead>
                <tbody>${holdings.map(h => `
                    <tr>
                        <td><strong>${esc(h.name)}</strong><br><span style="font-size:11px;color:#94A3B8;">${h.code}</span></td>
                        <td>${h.shares.toFixed(2)}</td>
                        <td>¥${h.cost_total.toFixed(2)}</td>
                        <td class="${cls(h.profit)}">${h.current_nav.toFixed(4)}</td>
                        <td class="${cls(h.profit)}">¥${h.current_total.toFixed(2)}</td>
                        <td class="${cls(h.profit)}">${fmtPct(h.return_pct)}</td>
                        <td><span class="${cls(h.xirr || 0)}" style="font-weight:600;">${h.xirr != null ? fmtPct(h.xirr) : '--'}</span></td>
                        <td>${h.tx_count || 0}</td>
                    </tr>
                `).join('')}</tbody>
            </table></div>
        </div>` : '<div class="empty"><i class="fas fa-box-open"></i><p>暂无持仓，点击「记一笔」添加第一笔买入</p></div>'}

        <div class="card">
            <div class="card-title"><i class="fas fa-receipt"></i> 交易流水
            <span style="margin-left:auto;font-size:12px;color:#94A3B8;font-weight:400;">共 ${txs.length} 笔</span>
            </div>
            ${txs.length === 0 ? '<div class="empty"><p>暂无记录</p></div>' : `
            <div class="table-wrap"><table>
                <thead><tr><th>日期</th><th>类型</th><th>基金</th><th>份额</th><th>净值</th><th>金额</th><th>手续费</th><th>备注</th><th></th></tr></thead>
                <tbody>${txs.map(tx => {
                    const typeLabel = {buy:'买入',sell:'卖出',dividend:'分红'}[tx.type] || tx.type;
                    const typeColor = tx.type === 'buy' ? '#F0B90B' : tx.type === 'sell' ? '#00C853' : '#94A3B8';
                    const shareDelta = tx.type === 'sell' ? -tx.shares : tx.shares;
                    return `<tr>
                        <td style="white-space:nowrap;">${tx.tx_date ? tx.tx_date.slice(0,10) : '--'}</td>
                        <td><span style="color:${typeColor};font-weight:600;">${typeLabel}</span></td>
                        <td><strong>${esc(tx.fund_name || '')}</strong><br><span style="font-size:11px;color:#94A3B8;">${tx.fund_code}</span></td>
                        <td class="${cls(shareDelta)}">${tx.shares.toFixed(2)}</td>
                        <td>¥${tx.price.toFixed(4)}</td>
                        <td class="${tx.type === 'buy' ? 'text-down' : 'text-up'}">${tx.type === 'buy' ? '-' : '+'}¥${tx.amount.toFixed(2)}</td>
                        <td>${tx.fee ? '¥' + tx.fee.toFixed(2) : '--'}</td>
                        <td style="font-size:12px;color:#94A3B8;max-width:120px;overflow:hidden;text-overflow:ellipsis;">${esc(tx.note || '')}</td>
                        <td><button class="btn btn-outline btn-sm" onclick="deleteTx(${tx.id})"><i class="fas fa-trash"></i></button></td>
                    </tr>`;
                }).join('')}</tbody>
            </table></div>`}
        </div>`;
    } catch (e) {
        if (e.name === 'AbortError') return;
        el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-triangle"></i><p>加载失败</p></div>';
    }
}

async function showAddTx() {
    // 获取已有基金代码供选择
    let holdings = [];
    try {
        const d = await api('/api/portfolio/holdings');
        if (d && d.holdings) holdings = d.holdings;
    } catch(e) {}

    const modal = document.createElement('div');
    modal.className = 'modal-overlay show';
    modal.id = 'addTxModal';
    modal.innerHTML = `
    <div class="modal-box" style="max-width:480px;">
        <div class="modal-header"><div class="modal-title"><i class="fas fa-receipt"></i> 记一笔交易</div><button class="modal-close" onclick="closeModal('addTxModal')">&times;</button></div>
        <div class="modal-body">
            <div class="form-group">
                <label>类型</label>
                <select id="txType" onchange="toggleTxFields()">
                    <option value="buy">买入</option>
                    <option value="sell">卖出</option>
                    <option value="dividend">分红</option>
                </select>
            </div>
            <div class="form-group">
                <label>基金代码</label>
                <div style="display:flex;gap:8px;">
                    <input id="txCode" placeholder="如 005827" list="txFundList" style="flex:1;" />
                    <datalist id="txFundList">${holdings.map(h => `<option value="${h.code}">${h.name}</option>`).join('')}</datalist>
                </div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>份额</label><input id="txShares" type="number" step="0.01" min="0.01" /></div>
                <div class="form-group"><label>成交净值</label><input id="txPrice" type="number" step="0.0001" min="0.001" /></div>
            </div>
            <div class="form-row">
                <div class="form-group"><label>交易日期</label><input id="txDate" type="date" /></div>
                <div class="form-group"><label>手续费</label><input id="txFee" type="number" step="0.01" min="0" value="0" /></div>
            </div>
            <div class="form-group"><label>备注</label><input id="txNote" placeholder="可选" /></div>
        </div>
        <div class="modal-footer">
            <button class="btn btn-outline" onclick="closeModal('addTxModal')">取消</button>
            <button class="btn btn-primary" onclick="submitTx()">确认提交</button>
        </div>
    </div>`;
    document.body.appendChild(modal);
    // 默认日期为今天
    const dateInput = document.getElementById('txDate');
    if (dateInput) {
        const today = new Date();
        dateInput.value = today.getFullYear() + '-' + String(today.getMonth()+1).padStart(2,'0') + '-' + String(today.getDate()).padStart(2,'0');
    }
}

function toggleTxFields() {
    const type = ($('txType') || {}).value || 'buy';
    // 分红时自动填份额=0、净值=0
}

async function submitTx() {
    const type = $('txType').value;
    const code = ($('txCode').value || '').trim();
    const shares = parseFloat($('txShares').value);
    const price = parseFloat($('txPrice').value);
    const txDate = $('txDate').value;
    const fee = parseFloat($('txFee').value) || 0;
    const note = ($('txNote').value || '').trim();

    if (!code) { showToast('请输入基金代码'); return; }
    if (!shares || !price) { showToast('请填写份额和净值'); return; }
    if (!txDate) { showToast('请选择交易日期'); return; }

    const res = await api('/api/transactions', {
        method: 'POST',
        body: JSON.stringify({ fund_code: code, type, shares, price, tx_date: txDate, fee, note }),
    });
    if (res && res.id) {
        showToast('✅ 交易记录已添加');
        closeModal('addTxModal');
        renderPage('transactions');
    } else {
        showToast('❌ 添加失败: ' + (res?.error || '未知错误'));
    }
}

async function deleteTx(id) {
    if (!confirm('确认删除该交易记录？')) return;
    const res = await api(`/api/transactions/${id}`, { method: 'DELETE' });
    if (res && res.deleted) {
        showToast('已删除');
        renderPage('transactions');
    } else {
        showToast('删除失败');
    }
}

// ====== 设置 ======
function renderSettings(el) {
    el.innerHTML = `
    <div class="card" style="max-width:560px;">
        <div class="card-title"><i class="fas fa-database"></i> 数据缓存</div>
        <button class="btn btn-outline" onclick="clearCache()"><i class="fas fa-trash"></i> 清除缓存</button>
    </div>
    </div>
    <div class="card" style="max-width:560px;">
        <div class="card-title"><i class="fas fa-info-circle"></i> 关于</div>
        <div style="font-size:13px;color:#E2E8F0;line-height:1.8;">
            <strong>基金范围</strong> v2.0<br>
            数据来源: akshare（天天基金/东方财富）<br>
            模型: 多因子评分 + 技术指标信号<br>
            声明: 仅供参考，不构成投资建议
        </div>
    </div>`;
}

// ====== 基金筛选 ======
async function renderScreener(el) {
    el.innerHTML = `
        <div class="filter-bar" id="screenerBar">
            <div class="form-group">
                <label>基金类型</label>
                <select id="screenerType" onchange="searchScreener(1)">
                    <option value="全部">全部</option>
                    <option value="股票型">股票型</option>
                    <option value="混合型">混合型</option>
                    <option value="债券型">债券型</option>
                    <option value="指数型">指数型</option>
                    <option value="货币型">货币型</option>
                    <option value="QDII">QDII</option>
                </select>
            </div>
            <div class="form-group">
                <label>排序</label>
                <select id="screenerSort" onchange="searchScreener(1)">
                    <option value="近1月">近1月</option>
                    <option value="近3月">近3月</option>
                    <option value="近6月">近6月</option>
                    <option value="近1年">近1年</option>
                    <option value="近3年">近3年</option>
                </select>
            </div>
            <div class="form-group">
                <label>搜索</label>
                <input id="screenerKeyword" placeholder="基金代码/名称" onkeydown="if(event.key==='Enter') searchScreener(1)" />
            </div>
            <button class="btn btn-primary" onclick="searchScreener(1)"><i class="fas fa-search"></i> 搜索</button>
        </div>
        <div id="screenerResults"><div class="loading"><div class="spinner"></div></div></div>`;

    await searchScreener(1);
}

async function searchScreener(page) {
    const el = $('screenerResults');
    if (!el) return;
    el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const type = ($('screenerType') || {}).value || '全部';
        const sortBy = ($('screenerSort') || {}).value || '近1月';
        const keyword = ($('screenerKeyword') || {}).value || '';
        const order = 'desc';

        const data = await api(`/api/funds/screen?type=${encodeURIComponent(type)}&sort_by=${encodeURIComponent(sortBy)}&order=${order}&keyword=${encodeURIComponent(keyword)}&page=${page}&page_size=30`);

        if (!data || !data.funds || data.funds.length === 0) {
            el.innerHTML = '<div class="empty"><i class="fas fa-filter"></i><p>没有找到匹配的基金</p></div>';
            return;
        }

        const funds = data.funds;
        const total = data.total || funds.length;
        const totalPages = data.total_pages || Math.ceil(total / 30);
        const currentPage = data.page || page;

        el.innerHTML = `
            <div class="table-wrap">
            <table>
                <thead><tr>
                    <th>代码</th><th>名称</th><th>类型</th><th>净值</th>
                    <th>近1月</th><th>近3月</th><th>近6月</th><th>近1年</th><th></th>
                </tr></thead>
                <tbody>${funds.map(f => `
                    <tr>
                        <td>${esc(f.code)}</td>
                        <td><strong>${esc(f.name || '--')}</strong></td>
                        <td>${esc(f.fund_type || '--')}</td>
                        <td>${f.nav != null ? f.nav.toFixed(4) : '--'}</td>
                        <td><span class="${cls(f.return_1m)}">${f.return_1m != null ? fmtPct(f.return_1m) : '--'}</span></td>
                        <td><span class="${cls(f.return_3m)}">${f.return_3m != null ? fmtPct(f.return_3m) : '--'}</span></td>
                        <td><span class="${cls(f.return_6m)}">${f.return_6m != null ? fmtPct(f.return_6m) : '--'}</span></td>
                        <td><span class="${cls(f.return_1y)}">${f.return_1y != null ? fmtPct(f.return_1y) : '--'}</span></td>
                        <td style="white-space:nowrap;">
                            <button class="btn btn-outline btn-sm" onclick="goAnalysis('${esc(f.code)}')" style="margin-right:4px;">分析</button>
                            <button class="btn btn-sm ${_isInWatchlist(f.code) ? 'btn-primary' : 'btn-outline'}" onclick="toggleWatchlistCheck('${esc(f.code)}', '${esc(f.name || '')}', '${esc(f.fund_type || '')}')" style="font-size:10px;padding:4px 8px;">
                                <i class="fas fa-star"></i>
                            </button>
                        </td>
                    </tr>`).join('')}</tbody>
            </table>
            </div>
            <div class="pagination">
                <button class="page-btn" onclick="searchScreener(${currentPage - 1})" ${currentPage <= 1 ? 'disabled style="opacity:0.4;cursor:not-allowed;"' : ''}>上一页</button>
                <span class="page-info">第 ${currentPage} / ${totalPages} 页 · 共 ${total} 条</span>
                <button class="page-btn" onclick="searchScreener(${currentPage + 1})" ${currentPage >= totalPages ? 'disabled style="opacity:0.4;cursor:not-allowed;"' : ''}>下一页</button>
            </div>`;
    } catch (e) {
        if (e.name === 'AbortError') return;
        el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-triangle"></i><p>加载失败</p></div>';
    }
}

// ====== 市场温度 ======

// ====== 组合穿透 ======
async function renderPenetration(el) {
    el.innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    try {
        const data = await api('/api/portfolio/penetration');
        if (!data) {
            el.innerHTML = '<div class="empty"><i class="fas fa-crosshairs"></i><p>暂无持仓数据，请先在「持仓」页面添加基金</p></div>';
            return;
        }

        const totalValue = data.total_value || 0;
        const fundCount = data.fund_count || 0;
        const typeDist = data.type_distribution || [];
        const fundDetails = data.fund_details || [];

        let html = `
            <div class="stats" style="grid-template-columns:repeat(2,1fr);">
                <div class="card stat-card"><div class="stat-label">组合总资产</div><div class="stat-value">${fmtMoney(totalValue)}</div></div>
                <div class="card stat-card"><div class="stat-label">基金数量</div><div class="stat-value">${fundCount}</div></div>
            </div>`;

        if (typeDist.length > 0) {
            html += `
            <div class="penetration-grid">
                <div class="card">
                    <div class="card-title"><i class="fas fa-chart-bar"></i> 类型分布</div>
                    <div class="penetration-chart"><canvas id="penetrationChart"></canvas></div>
                </div>
                <div class="card">
                    <div class="card-title"><i class="fas fa-list"></i> 分布明细</div>
                    <table>
                        <thead><tr><th>类型</th><th>数量</th><th>总市值</th><th>占比</th></tr></thead>
                        <tbody>${typeDist.map(t => `
                            <tr>
                                <td>${esc(t.type || '--')}</td>
                                <td>${t.count || 0}</td>
                                <td>${fmtMoney(t.total_value || 0)}</td>
                                <td>${t.proportion != null ? t.proportion.toFixed(1) + '%' : '--'}</td>
                            </tr>`).join('')}</tbody>
                    </table>
                </div>
            </div>`;
        }

        if (fundDetails.length > 0) {
            html += `
            <div class="card penetration-table">
                <div class="card-title"><i class="fas fa-list"></i> 持仓明细</div>
                <div class="table-wrap">
                <table>
                    <thead><tr><th>代码</th><th>名称</th><th>类型</th><th>市值</th><th>占比</th></tr></thead>
                    <tbody>${fundDetails.map(f => `
                        <tr>
                            <td>${esc(f.code || '--')}</td>
                            <td><strong>${esc(f.name || '--')}</strong></td>
                            <td>${esc(f.fund_type || '--')}</td>
                            <td>${fmtMoney(f.value || 0)}</td>
                            <td>${f.proportion != null ? f.proportion.toFixed(1) + '%' : '--'}</td>
                        </tr>`).join('')}</tbody>
                </table>
                </div>
            </div>`;
        }

        if (typeDist.length === 0 && fundDetails.length === 0) {
            html += '<div class="empty"><i class="fas fa-crosshairs"></i><p>暂无组合穿透数据</p></div>';
        }

        el.innerHTML = html;

        if (typeDist.length > 0 && typeof Chart !== 'undefined') {
            setTimeout(() => {
                const canvas = $('penetrationChart');
                if (!canvas) return;
                if (chartInstances.penetration) {
                    try { chartInstances.penetration.destroy(); } catch (e) { /* ignore */ }
                }
                chartInstances.penetration = new Chart(canvas, {
                    type: 'bar',
                    data: {
                        labels: typeDist.map(t => t.type),
                        datasets: [{
                            label: '市值',
                            data: typeDist.map(t => t.total_value),
                            backgroundColor: genColors(typeDist.length),
                            borderWidth: 0,
                            borderRadius: 4,
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        indexAxis: 'y',
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                backgroundColor: '#131A2B',
                                bodyFont: { size: 13 },
                                padding: 10,
                                callbacks: {
                                    label: ctx => ctx.parsed.x !== null ? fmtMoney(ctx.parsed.x) : ''
                                }
                            }
                        },
                        scales: {
                            x: {
                                grid: { color: '#1E293B' },
                                ticks: { font: { size: 11 }, color: '#94A3B8', callback: function(v) {
                                    if (v >= 10000) return (v / 10000).toFixed(1) + '万';
                                    return v;
                                } }
                            },
                            y: { grid: { display: false }, ticks: { font: { size: 12 }, color: '#E2E8F0' } }
                        }
                    }
                });
            }, 50);
        }
    } catch (e) {
        if (e.name === 'AbortError') throw e;
        el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-triangle"></i><p>加载失败</p></div>';
    }
}

// ====== 定投规划 ======
async function renderDca(el) {
    el.innerHTML = `
        <div class="card dca-form">
            <div class="card-title"><i class="fas fa-calendar-alt"></i> 定投参数设置</div>
            <div class="form-group"><label>基金代码</label><input id="dcaFundCode" placeholder="如 005827" /></div>
            <div class="form-row">
                <div class="form-group"><label>每月定投金额（元）</label><input id="dcaMonthlyAmount" type="number" value="1000" min="1" /></div>
                <div class="form-group"><label>定投月数</label><input id="dcaMonths" type="number" value="12" min="1" /></div>
            </div>
            <div class="form-group"><label>预期年化收益率（%）</label><input id="dcaExpectedRate" type="number" value="8" step="0.5" min="0" /></div>
            <div style="display:flex;gap:10px;">
                <button class="btn btn-primary" onclick="calculateDcaPlan()"><i class="fas fa-calculator"></i> 计算</button>
                <button class="btn btn-outline" onclick="resetDcaForm()"><i class="fas fa-undo"></i> 重置</button>
            </div>
        </div>
        <div id="dcaResultContainer" style="display:none;"></div>`;
}

async function calculateDcaPlan() {
    const fundCode = $('dcaFundCode').value.trim();
    const monthlyAmount = parseFloat($('dcaMonthlyAmount').value);
    const months = parseInt($('dcaMonths').value);
    const expectedRate = parseFloat($('dcaExpectedRate').value);

    if (!fundCode) { showToast('请输入基金代码'); return; }
    if (!monthlyAmount || !months) { showToast('请填写完整信息'); return; }

    const el = $('dcaResultContainer');
    el.style.display = 'block';
    el.innerHTML = '<div class="loading"><div class="spinner"></div>计算中...</div>';

    try {
        const res = await api('/api/dca/project', {
            method: 'POST',
            body: JSON.stringify({
                fund_code: fundCode,
                monthly_amount: monthlyAmount,
                months: months,
                expected_annual_return: expectedRate
            })
        });

        if (!res) {
            el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-triangle"></i><p>计算失败，请稍后重试</p></div>';
            return;
        }

        const totalPrincipal = res.total_principal || (monthlyAmount * months);
        const totalValue = res.estimated_total || 0;
        const totalProfit = res.estimated_profit || (totalValue - totalPrincipal);
        const schedule = res.schedule || [];

        el.innerHTML = `
            <div class="card dca-result">
                <div class="card-title"><i class="fas fa-chart-line"></i> 定投概览</div>
                <div class="dca-stats">
                    <div class="dca-stat"><div class="dca-value">${fmtMoney(monthlyAmount)}</div><div class="dca-label">每月投入</div></div>
                    <div class="dca-stat"><div class="dca-value">${months} 个月</div><div class="dca-label">定投时长</div></div>
                    <div class="dca-stat"><div class="dca-value">${expectedRate}%</div><div class="dca-label">预期年化</div></div>
                    <div class="dca-stat"><div class="dca-value">${fmtMoney(totalPrincipal)}</div><div class="dca-label">累计本金</div></div>
                    <div class="dca-stat"><div class="dca-value" style="color:${totalProfit >= 0 ? '#F04444' : '#00C853'};">${fmtMoney(totalProfit)}</div><div class="dca-label">预计收益</div></div>
                    <div class="dca-stat"><div class="dca-value">${fmtMoney(totalValue)}</div><div class="dca-label">预计总值</div></div>
                </div>
                ${schedule.length > 0 ? `
                <div class="table-wrap" style="max-height:400px;overflow-y:auto;">
                    <table>
                        <thead><tr><th>月份</th><th>投入金额</th><th>累计投入</th><th>累计总值</th><th>收益</th></tr></thead>
                        <tbody>${schedule.map(s => {
                            const profit = s.accumulated_total - s.accumulated_principal;
                            return `<tr>
                                <td>${s.month || '--'}</td>
                                <td>${fmtMoney(s.contribution || 0)}</td>
                                <td>${fmtMoney(s.accumulated_principal || 0)}</td>
                                <td class="${cls(profit)}">${fmtMoney(s.accumulated_total || 0)}</td>
                                <td class="${cls(profit)}">${fmtMoney(profit)}</td>
                            </tr>`;
                        }).join('')}</tbody>
                    </table>
                </div>` : ''}
            </div>`;
    } catch (e) {
        if (e.name === 'AbortError') return;
        el.innerHTML = '<div class="empty"><i class="fas fa-exclamation-triangle"></i><p>计算失败</p></div>';
    }
}

function resetDcaForm() {
    const fc = $('dcaFundCode'); if (fc) fc.value = '';
    const ma = $('dcaMonthlyAmount'); if (ma) ma.value = '1000';
    const mo = $('dcaMonths'); if (mo) mo.value = '12';
    const er = $('dcaExpectedRate'); if (er) er.value = '8';
    const el = $('dcaResultContainer');
    if (el) { el.style.display = 'none'; el.innerHTML = ''; }
}

// ====== AI 助手 ======
let _aiMessages = [];
let _aiLoading = false;

function setAiInputLocked(locked) {
    _aiLoading = locked;
    const input = $('chatInput');
    const btn = input ? input.nextElementSibling : null;
    const chips = qsa('#aiSuggestions .chip');
    if (input) {
        input.disabled = locked;
        input.placeholder = locked ? 'AI 正在回复中...' : '输入您的问题...';
    }
    if (btn) btn.disabled = locked;
    chips.forEach(c => { c.style.pointerEvents = locked ? 'none' : ''; c.style.opacity = locked ? '0.5' : ''; });
}

async function renderAI(el) {
    el.innerHTML = `
        <div class="chat-suggestions" id="aiSuggestions">
            <span class="chip" onclick="suggestQuestion('我的持仓整体怎么样?')">持仓诊断</span>
            <span class="chip" onclick="suggestQuestion('分析我的组合风险和收益特征')">风险收益分析</span>
            <span class="chip" onclick="suggestQuestion('哪只基金表现最好，哪只最差？给出对比')">持仓对比</span>
            <span class="chip" onclick="suggestQuestion('我的组合分散度如何？有什么调整建议？')">调仓建议</span>
            <span class="chip" onclick="suggestQuestion('分析各基金的技术面信号（RSI/MACD/均线）')">技术面分析</span>
        </div>
        <div class="chat-container">
            <div class="chat-messages" id="chatMessages"></div>
            <div class="chat-input-bar">
                <input id="chatInput" placeholder="输入您的问题..." onkeydown="if(event.key==='Enter') sendChatMessage()" />
                <button onclick="sendChatMessage()"><i class="fas fa-paper-plane"></i></button>
            </div>
        </div>`;
    renderChatMessages();
    // 页面切换后恢复锁定状态
    if (_aiLoading) setAiInputLocked(true);
}

function renderChatMessages() {
    const el = $('chatMessages');
    if (!el) return;
    if (_aiMessages.length === 0) {
        el.innerHTML = '<div class="empty" style="padding:30px 20px;"><i class="fas fa-robot"></i><p>有什么可以帮您的？点击上方建议问题开始对话</p></div>';
        return;
    }
    el.innerHTML = _aiMessages.map((m, i) => {
        const timeStr = m.time || new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        const content = m.role === 'ai' && typeof marked !== 'undefined'
            ? DOMPurify.sanitize(marked.parse(m.content), { ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','br','ul','ol','li','table','thead','tbody','tr','th','td','strong','em','del','code','pre','blockquote','hr','a','div','span'], ALLOWED_ATTR: ['href','target','class','style'] })
            : esc(m.content);
        return `<div class="chat-msg ${m.role}">
            <div class="bubble">${content}</div>
            <div class="time">${timeStr}</div>
        </div>`;
    }).join('');
    el.scrollTop = el.scrollHeight;
}

async function sendChatMessage() {
    if (_aiLoading) return;  // AI 回复中，禁止并发提问

    const input = $('chatInput');
    const msg = input ? input.value.trim() : '';
    if (!msg) return;
    if (input) input.value = '';

    // 添加用户消息
    _aiMessages.push({ role: 'user', content: msg, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) });
    // 预创建空的 AI 气泡，流式填充
    const aiIdx = _aiMessages.length;
    _aiMessages.push({ role: 'ai', content: '', time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) });
    renderChatMessages();
    setAiInputLocked(true);

    // 构建历史：排除当前提问（后端单独收 message）和空内容的流式气泡
    const historyToSend = [];
    for (let i = 0; i < _aiMessages.length - 2; i++) {
        const m = _aiMessages[i];
        if (m.content) historyToSend.push({ role: m.role, content: m.content });
    }

    const token = getToken();
    try {
        const response = await fetch('/api/ai/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            },
            body: JSON.stringify({
                message: msg,
                history: historyToSend
            })
        });

        if (response.status === 401) {
            localStorage.removeItem('fund_token');
            window.location.href = '/login';
            return;
        }

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            _aiMessages[aiIdx].content = errData.error || `请求失败 (HTTP ${response.status})`;
            renderChatMessages();
            setAiInputLocked(false);
            return;
        }

        // 读取 SSE 流，逐 chunk 更新 AI 气泡
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();  // 保留未完成的半行

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const dataStr = line.slice(6);
                if (dataStr === '[DONE]') break;
                try {
                    const data = JSON.parse(dataStr);
                    if (data.error) {
                        _aiMessages[aiIdx].content = data.error;
                    } else if (data.content) {
                        _aiMessages[aiIdx].content += data.content;
                    }
                    // data.status === 'started' 忽略
                    renderChatMessages();
                } catch(e) {
                    console.warn('SSE parse error:', dataStr.slice(0, 80), e);
                }
            }
        }

        // 兜底：流正常结束但无内容时给提示
        if (!_aiMessages[aiIdx].content) {
            _aiMessages[aiIdx].content = 'AI 未返回内容，请稍后重试。';
        }
        renderChatMessages();
        setAiInputLocked(false);
    } catch (e) {
        if (e.name === 'AbortError') { setAiInputLocked(false); return; }
        _aiMessages[aiIdx].content = _aiMessages[aiIdx].content || '请求失败，请稍后重试。';
        renderChatMessages();
        setAiInputLocked(false);
    }
}

function suggestQuestion(q) {
    if (_aiLoading) return;
    const input = $('chatInput');
    if (input) input.value = q;
    sendChatMessage();
}

async function exportCsv() {
    try {
        const token = getToken();
        const resp = await fetch(API + '/api/portfolio/export', {
            headers: { 'Authorization': 'Bearer ' + token }
        });
        if (!resp.ok) { showToast('导出失败'); return; }
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'fund_portfolio.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('✅ 导出成功');
    } catch (e) {
        showToast('导出失败: ' + e.message);
    }
}

async function clearCache() {
    const res = await api('/api/clear-cache');
    if (res?.success) {
        showToast('缓存已清除，正在刷新数据...');
        await renderPage(currentPage);
    } else {
        showToast('清除缓存失败');
    }
}


// ====== 退出登录 ======

function logout() {
    localStorage.removeItem('fund_token');
    window.location.href = '/login';
}

// ====== 启动 ======
// 检查登录状态，未登录跳转登录页
(async function() {
    // 启动时预加载自选缓存
    _ensureWatchlistCache().catch(() => {});
    const token = getToken();
    if (!token) {
        // 开发模式：尝试自动登录
        try {
            const devResp = await fetch('/api/auth/dev-login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const devData = await devResp.json();
            if (devData && devData.token) {
                localStorage.setItem('fund_token', devData.token);
                renderPage('dashboard');
                return;
            }
        } catch (e) { /* 非开发模式，继续正常流程 */ }
        // 非开发模式：跳转登录页
        window.location.href = '/login';
        return;
    }
    // 验证 token 有效性
    const res = await api('/api/auth/me');
    if (!res || res.error) {
        window.location.href = '/login';
        return;
    }
    renderPage('dashboard');
})();
