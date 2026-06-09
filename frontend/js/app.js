/**
 * 基金驾驶舱 — 前端应用
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
        ctx.strokeStyle = '#b5aea0';
        ctx.lineWidth = 1;
        ctx.moveTo(x, yAxis.top);
        ctx.lineTo(x, yAxis.bottom);
        ctx.stroke();

        // 横虚线
        ctx.beginPath();
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = '#b5aea0';
        ctx.lineWidth = 1;
        ctx.moveTo(xAxis.left, active.element.y);
        ctx.lineTo(xAxis.right, active.element.y);
        ctx.stroke();

        // 交叉点（红色实心小圆）
        ctx.beginPath();
        ctx.arc(x, active.element.y, 3.5, 0, 2 * Math.PI);
        ctx.fillStyle = '#c62828';
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

async function api(url, opts = {}) {
    try {
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
            localStorage.removeItem('fund_token');
            window.location.href = '/login';
            return null;
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
function fmtMoney(n) { return '¥' + fmt(Math.round(n || 0)); }
function cls(val) { return val >= 0 ? 'text-up' : 'text-down'; }
function tagCls(val) { return val >= 0 ? 'tag-up' : 'tag-down'; }

const pageTitles = {
    dashboard: ['概览', '今日数据 · 实时估算'],
    portfolio: ['持仓', '全部持仓一览'],
    analysis: ['分析', '基金深度分析'],
    predict: ['智能预测', '多因子评分模型 · 买卖时机参考'],
    screener: ['基金筛选', '多维度筛选优质基金'],
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
        el.style.background = isActive ? '#c7883c' : '#f0ebe2';
        el.style.color = isActive ? '#fff' : '#5a544a';
    });
}

function setChartPeriod(period) {
    chartPeriod = period;
    if (selectedFund) renderLineChart(selectedFund, period);
    document.querySelectorAll('.period-btn').forEach(el => {
        if (!el.getAttribute('onclick')?.includes('setChartPeriod')) return;
        const isActive = el.dataset.period === period;
        el.style.background = isActive ? '#c7883c' : '#f0ebe2';
        el.style.color = isActive ? '#fff' : '#5a544a';
    });
}

function setDetailPeriod(period) {
    detailPeriod = period;
    renderDetailChart(window._detailNavData, period);
    document.querySelectorAll('.period-btn').forEach(el => {
        if (!el.getAttribute('onclick')?.includes('setDetailPeriod')) return;
        const isActive = el.dataset.period === period;
        el.style.background = isActive ? '#c7883c' : '#f0ebe2';
        el.style.color = isActive ? '#fff' : '#5a544a';
    });
}

function periodBtn(label, period, active) {
    return `<span class="period-btn ${active ? 'active' : ''}" data-period="${period}" onclick="setChartPeriod('${period}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${active ? 'background:#c7883c;color:#fff;' : 'background:#f0ebe2;color:#5a544a;'}margin-left:4px;">${label}</span>`;
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
        portfolio: renderPortfolio,
        analysis: renderAnalysis,
        predict: renderPredict,
        screener: renderScreener,
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
    const data = await api('/api/portfolio');
    if (!data || !data.holdings || data.holdings.length === 0) return;
    const h = data.holdings;
    window._holdingsList = h;
    // 更新统计卡片
    const totalVal = h.reduce((s, x) => s + x.current_total, 0);
    const totalCost = h.reduce((s, x) => s + x.cost_total, 0);
    const totalProfit = totalVal - totalCost;
    const totalPct = totalCost > 0 ? totalProfit / totalCost * 100 : 0;
    const totalDailyProfit = h.reduce((s, x) => s + (x.daily_profit || 0), 0);
    const dailyPct = (totalVal - totalDailyProfit) > 0 ? totalDailyProfit / (totalVal - totalDailyProfit) * 100 : 0;
    const cards = qsa('.stat-value');
    if (cards.length >= 5) {
        cards[0].textContent = fmtMoney(totalVal);
        cards[1].textContent = fmtMoney(totalProfit);
        cards[1].className = 'stat-value ' + cls(totalProfit);
        let changeEl = cards[1].nextElementSibling;
        if (changeEl) { changeEl.textContent = fmtPct(totalPct); changeEl.className = 'stat-change ' + cls(totalProfit); }
        cards[2].textContent = fmtMoney(totalDailyProfit);
        cards[2].className = 'stat-value ' + cls(totalDailyProfit);
        changeEl = cards[2].nextElementSibling;
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
// 返回 { [id]: { startNav, currentNav, expectedInvested, isStopped } }
async function syncDcaHoldings(holdings) {
    const dcaInfo = {};
    for (const x of holdings) {
        if (x.total_invested == null || !x.dca_start_date) continue;
        try {
            const navData = await api(`/api/fund/${x.code}/nav`);
            if (!navData || !navData.data) continue;
            const startIdx = navData.data.findIndex(d => d.日期 >= x.dca_start_date);
            if (startIdx < 0) continue;
            const start = navData.data[startIdx];
            const lastNavDate = navData.data[navData.data.length - 1].日期;
            const cutoffDate = x.dca_end_date || lastNavDate;
            const endIdx = navData.data.findIndex(d => d.日期 > cutoffDate);
            const effectiveNavs = navData.data.slice(startIdx, endIdx >= 0 ? endIdx : navData.data.length);
            let buyCount = 0;
            if (x.dca_amount && x.dca_frequency) {
                if (x.dca_frequency === 'daily') {
                    buyCount = effectiveNavs.length;
                } else if (x.dca_frequency === 'weekly') {
                    buyCount = effectiveNavs.filter((_, i) => i % 5 === 0).length;
                } else if (x.dca_frequency === 'monthly') {
                    const seen = new Set();
                    buyCount = effectiveNavs.filter(d => { const m = d.日期.slice(0,7); if (seen.has(m)) return false; seen.add(m); return true; }).length;
                }
            }
            const expectedInvested = buyCount * (x.dca_amount || 0);
            const row = navData.data[navData.data.length - 1];
            dcaInfo[x.id] = {
                startNav: start ? start.单位净值 : null,
                currentNav: row ? row.单位净值 : null,
                expectedInvested: expectedInvested,
                isStopped: !!x.dca_end_date,
            };
            if (expectedInvested > 0 && Math.abs(expectedInvested - (x.total_invested || 0)) > 0.01) {
                x.total_invested = expectedInvested;
                api(`/api/portfolio/${x.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ total_invested: expectedInvested })
                });
            }
        } catch (e) { /* 单条失败静默跳过 */ }
    }
    return dcaInfo;
}

async function renderDashboard(el) {
    const data = await api('/api/portfolio');
    if (!data || !data.holdings || data.holdings.length === 0) {
        el.innerHTML = '<div class="empty"><i class="fas fa-box-open"></i><p>还没有持仓，去「持仓」页面添加基金</p></div>';
        return;
    }
    const h = data.holdings;
    // 先同步定投金额到当前日期
    const dcaInfo = await syncDcaHoldings(h);
    const totalVal = h.reduce((s, x) => s + x.current_total, 0);
    const totalCost = h.reduce((s, x) => s + x.cost_total, 0);
    const totalProfit = totalVal - totalCost;
    const totalPct = totalCost > 0 ? totalProfit / totalCost * 100 : 0;
    const totalDailyProfit = h.reduce((s, x) => s + (x.daily_profit || 0), 0);

    selectedFund = selectedFund || h[0].code;
    window._holdingsList = h;

    el.innerHTML = `
        <div class="stats">
            <div class="card stat-card"><div class="stat-label">总资产</div><div class="stat-value">${fmtMoney(totalVal)}</div></div>
            <div class="card stat-card"><div class="stat-label">累计收益</div><div class="stat-value ${cls(totalProfit)}">${fmtMoney(totalProfit)}</div><div class="stat-change ${cls(totalProfit)}">${fmtPct(totalPct)}</div></div>
            <div class="card stat-card"><div class="stat-label">昨日收益</div><div class="stat-value ${cls(totalDailyProfit)}">${fmtMoney(totalDailyProfit)}</div><div class="stat-change ${cls(totalDailyProfit)}">${fmtPct(totalDailyProfit ? totalDailyProfit / (totalVal - totalDailyProfit) * 100 : 0)}</div></div>
            <div class="card stat-card"><div class="stat-label">持仓数量</div><div class="stat-value">${h.length}</div></div>
            <div class="card stat-card"><div class="stat-label">数据来源</div><div class="stat-value" style="font-size:18px;color:#c7883c;">akshare</div></div>
        </div>
        <div class="charts">
            <div class="card"><div class="card-title"><i class="fas fa-chart-pie"></i> 资产配置</div><div class="chart-wrapper"><canvas id="pieChart"></canvas></div></div>
            <div class="card"><div class="card-title"><i class="fas fa-chart-line"></i> 
            <span style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                <span style="font-size:14px;font-weight:600;color:#2d2a26;margin-right:4px;">净值走势</span>
                ${h.map(x => `<span class="fund-tab" data-code="${x.code}" onclick="switchFund('${x.code}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${selectedFund === x.code ? 'background:#c7883c;color:#fff;' : 'background:#f0ebe2;color:#5a544a;'}">${x.name.length > 6 ? x.name.slice(0,6)+'..' : x.name}</span>`).join('')}
                <span style="margin-left:4px;">${['1月','3月','6月','1年'].map((l,i) => periodBtn(l, ['1m','3m','6m','1y'][i], chartPeriod === ['1m','3m','6m','1y'][i])).join('')}</span>
            </span>
            </div><div class="chart-wrapper"><canvas id="lineChart"></canvas></div></div>
        </div>
        <div class="card"><div class="card-title"><i class="fas fa-list"></i> 持仓明细</div>
        <table>
            <thead><tr><th>基金名称</th><th>可用份额</th><th>平均成本</th><th>累计投入</th><th>最新净值</th><th>持仓市值</th><th>收益</th><th>收益率</th><th>较昨日</th><th></th></tr></thead>
            <tbody>${h.map(x => {
                const isDca = x.total_invested != null;
                const info = dcaInfo[x.id];
                const invested = (isDca && info && info.expectedInvested > 0) ? info.expectedInvested : (isDca ? x.total_invested : x.cost_total);
                const stopped = isDca && info && info.isStopped;
                const statusTag = isDca
                    ? (stopped ? ' <span style="font-size:10px;color:#9e9e9e;">⏸</span>' : ' <span style="font-size:10px;color:#4caf50;">●</span>')
                    : '';
                const dcaSub = isDca
                    ? '<br><span style="font-size:10px;color:#b5aea0;">' + (stopped ? '已终止' : '定投中') + ' · 从' + (x.dca_start_date ? x.dca_start_date.slice(0,10) : '') + (stopped && x.dca_end_date ? '至' + x.dca_end_date.slice(0,10) : '') + '</span>'
                    : '';
                const daily = x.daily_profit || 0;
                return `<tr><td><strong>${x.name}</strong>${statusTag}${dcaSub}</td><td>${fmt(x.shares)}</td><td>${x.cost_nav.toFixed(4)}</td><td>${fmtMoney(invested)}</td><td class="${cls(x.profit)}">${x.current_nav.toFixed(4)}</td><td class="${cls(x.profit)}">${fmtMoney(x.current_total)}</td><td class="${cls(x.profit)}">${fmtMoney(x.profit)}</td><td><span class="${tagCls(x.profit)}">${fmtPct(x.return_pct)}</span></td><td class="${cls(daily)}"><span style="font-size:13px;">${fmtMoney(daily)}</span><br><span style="font-size:10px;" class="${cls(daily)}">${fmtPct(x.daily_return_pct || 0)}</span></td><td><button class="btn btn-outline btn-sm" onclick="goAnalysis('${x.code}')">详情</button></td></tr>`;
            }).join('')}</tbody>
        </table></div>`;

    setTimeout(() => {
        renderPieChart(h);
        renderLineChart(selectedFund, chartPeriod);
    }, 50);
}

function genColors(n) {
    const palette = ['#c7883c','#e8a84c','#f0c878','#d4943a','#b8860b','#a67c52','#c9a96e','#dfb87a','#b8924a','#e6c28a'];
    return n <= palette.length ? palette.slice(0, n) : Array.from({length:n}, (_,i) => palette[i % palette.length]);
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
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#5a544a', padding: 12, font: { size: 12 } } } }, cutout: '60%' }
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
                borderColor: '#c7883c', backgroundColor: 'rgba(199,136,60,0.06)',
                fill: true, tension: .3, pointRadius: 0, hoverRadius: 5, pointHitRadius: 10, borderWidth: 2,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#2d2a26',
                    titleFont: { size: 12 },
                    bodyFont: { size: 13 },
                    padding: 10,
                    callbacks: {
                        label: ctx => ctx.parsed.y !== null ? `净值: ${ctx.parsed.y.toFixed(4)} 元` : ''
                    }
                }
            },
            scales: {
                y: { grid: { color: '#f0ebe2' }, ticks: { font: { size: 11 }, color: '#8a847a' }, title: { display: true, text: '净值（元）', color: '#8a847a', font: { size: 12 } } },
                x: {
                    grid: { display: false },
                    ticks: {
                        font: { size: 10 }, color: '#8a847a',
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
        <div style="margin-bottom:16px"><button class="btn btn-primary" onclick="showAddHolding()"><i class="fas fa-plus"></i> 添加持仓</button></div>
        ${h.length === 0 ? '<div class="empty"><i class="fas fa-box-open"></i><p>暂无持仓，点击上方按钮添加</p></div>' : `
        <div class="card"><table>
            <thead><tr><th>代码</th><th>名称</th><th>可用份额</th><th>平均成本</th><th>累计投入</th><th>最新净值</th><th>市值</th><th>收益</th><th>收益率</th><th></th></tr></thead>
            <tbody>${h.map(x => {
                const isDca = x.total_invested != null;
                const info = dcaInfo[x.id];
                const invested = (isDca && info && info.expectedInvested > 0) ? info.expectedInvested : (isDca ? x.total_invested : x.cost_total);
                const stopped = info && info.isStopped;
                const statusBadge = isDca
                    ? (stopped
                        ? '<span style="font-size:10px;background:#9e9e9e;color:#fff;padding:1px 6px;border-radius:3px;">⏸ 已终止</span>'
                        : '<span style="font-size:10px;background:#4caf50;color:#fff;padding:1px 6px;border-radius:3px;">● 定投中</span>')
                    : '';
                const freqLabel = x.dca_frequency === 'daily' ? '天' : x.dca_frequency === 'weekly' ? '周' : '月';
                const dcaActionBtn = isDca
                    ? (stopped
                        ? `<br><button class="btn btn-outline btn-sm" onclick="resumeDca(${x.id})" style="margin-top:4px;font-size:11px;color:#4caf50;">▶ 恢复投入</button>`
                        : `<br><button class="btn btn-outline btn-sm" onclick="stopDca(${x.id})" style="margin-top:4px;font-size:11px;color:#e57373;">⏹ 终止投入</button>`)
                    : '';
                return `<tr>
                <td>${x.code}</td><td><strong>${x.name}</strong> ${statusBadge}<br>
                ${isDca && x.dca_start_date ? `<span style="font-size:11px;color:#b5aea0;">从 ${x.dca_start_date.slice(0,10)} 开始${stopped ? ' · 至 ' + x.dca_end_date.slice(0,10) : ''}</span>` : ''}
                ${isDca && x.dca_amount ? `<br><span style="font-size:11px;color:#b5aea0;">${x.dca_amount}元/${freqLabel}</span>` : ''}
                ${isDca && info && info.startNav ? `<br><span style="font-size:11px;color:#5a544a;">净值 ${info.startNav.toFixed(4)} → ${info.currentNav.toFixed(4)} <span class="${cls(info.currentNav - info.startNav)}">${((info.currentNav / info.startNav - 1) * 100).toFixed(1)}%</span></span>` : ''}
                ${dcaActionBtn}
                </td>
                <td>${fmt(x.shares)}</td>
                <td>${x.cost_nav.toFixed(4)}</td>
                <td>${fmtMoney(invested)}</td>
                <td class="${cls(x.profit)}">${x.current_nav.toFixed(4)}</td>
                <td class="${cls(x.profit)}">${fmtMoney(x.current_total)}</td>
                <td class="${cls(x.profit)}">${fmtMoney(x.profit)}</td>
                <td><span class="${tagCls(x.profit)}">${fmtPct(x.return_pct)}</span></td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="showEditHolding(${x.id})" style="margin-right:4px"><i class="fas fa-edit"></i></button>
                    <button class="btn btn-outline btn-sm" onclick="deleteHolding(${x.id})"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`;
            }).join('')}</tbody>
        </table></div>
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
                    <span onclick="toggleDcaMode()" style="cursor:pointer;padding:2px 12px;border-radius:4px;font-size:12px;background:#f0ebe2;color:#5a544a;" id="dcaToggle">📅 定投模式</span>
                </label>
            </div>
            <div class="form-row">
                <div class="form-group" id="addSharesGroup"><label>可用份额</label><input id="addShares" type="number" step="0.01" min="0.01" /></div>
                <div class="form-group" id="addCostGroup"><label>成本单价</label><input id="addCost" type="number" step="0.0001" min="0.001" placeholder="买入时的净值" /></div>
            </div>
            <div class="form-group" id="addDcaGroup" style="display:none;">
                <div class="form-row">
                    <div class="form-group"><label>每期金额（元）</label><input id="addDcaAmt" type="number" step="1" min="1" placeholder="如 20" /></div>
                    <div class="form-group"><label>定投频率</label><select id="addDcaFreq"><option value="daily">每天</option><option value="weekly" selected>每周</option><option value="monthly">每月</option></select></div>
                </div>
                <label>定投开始日期</label><input id="addDcaDate" type="date" />
                <div style="margin-top:8px;padding:10px;background:#fdf6ec;border-radius:6px;font-size:12px;color:#5a544a;">系统将根据定投计划自动计算投入金额和份额，无需手动填写。</div>
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
        toggle.style.background = '#c7883c';
        toggle.style.color = '#fff';
        sharesGroup.style.display = 'none';
        costGroup.style.display = 'none';
        dcaGroup.style.display = 'block';
        costInput.required = false;
    } else {
        toggle.textContent = '📅 定投模式';
        toggle.style.background = '#f0ebe2';
        toggle.style.color = '#5a544a';
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
        const navs = navData.data.slice(startIdx);
        let buyNavs = [];
        if (dcaFreq === 'daily') buyNavs = navs;
        else if (dcaFreq === 'weekly') buyNavs = navs.filter((_, i) => i % 5 === 0);
        else if (dcaFreq === 'monthly') {
            const seen = new Set();
            buyNavs = navs.filter(d => { const m = d.日期.slice(0,7); if (seen.has(m)) return false; seen.add(m); return true; });
        }
        totalInvested = buyNavs.length * dcaAmt;
        let totalShares = 0;
        buyNavs.forEach(d => { totalShares += dcaAmt / d.单位净值; });
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
    if (totalInvested) { body.total_invested = totalInvested; body.dca_start_date = dcaStart; body.dca_amount = dcaAmt; body.dca_frequency = dcaFreq; }
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
                <strong>${item.name}</strong> <span style="color:#b5aea0;font-size:13px;">${item.code}</span>
                ${isDca ? '<span class="tag-neutral" style="font-size:10px;margin-left:6px;">定投</span>' : ''}
            </div>
            <div class="form-row">
                <div class="form-group"><label>可用份额</label><input id="editShares" type="number" step="0.01" min="0.01" value="${item.shares}" /></div>
                <div class="form-group"><label>${isDca ? '平均成本' : '成本单价'}</label><input id="editCost" type="number" step="0.0001" min="0.001" value="${item.cost_nav}" /></div>
            </div>
            ${isDca ? `<div class="form-group"><label>累计投入金额（元）</label><input id="editInvest" type="number" step="0.01" min="0.01" value="${item.total_invested}" /></div>
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
    const res = await api(`/api/portfolio/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    if (res && res.updated) { showToast('✅ 修改成功'); closeModal('editModal'); renderPage(currentPage); }
    else { showToast('❌ 修改失败'); }
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
            <div style="font-size:13px;color:#b5aea0;margin-top:4px;">${code} · ${info.fund_type||''} · 成立 ${info.establish_date||''}</div>
            <div style="font-size:13px;color:#b5aea0;">基金经理: ${info.manager||''}</div></div>
            <div style="text-align:right;"><div style="font-size:28px;font-weight:700;">${latest.单位净值.toFixed(4)}</div><div style="font-size:15px;${cls(chg)}">${chg >= 0 ? '+' : ''}${chg.toFixed(4)} (${chgPct >= 0 ? '+' : ''}${chgPct.toFixed(2)}%)</div></div>
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
        <span style="margin-left:auto">${['1月','3月','6月','1年'].map((l,i) => `<span class="period-btn ${detailPeriod === ['1m','3m','6m','1y'][i] ? 'active' : ''}" data-period="${['1m','3m','6m','1y'][i]}" onclick="setDetailPeriod('${['1m','3m','6m','1y'][i]}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${detailPeriod === ['1m','3m','6m','1y'][i] ? 'background:#c7883c;color:#fff;' : 'background:#f0ebe2;color:#5a544a;'}margin-left:4px;">${l}</span>`).join('')}</span>
        </div><div class="chart-wrapper"><canvas id="detailChart"></canvas></div></div>
        ${analysis && analysis.signals && analysis.signals.summary ? `
        <div class="card"><div class="card-title"><i class="fas fa-chart-bar"></i> 技术信号</div>
        <div class="pred-signals">${analysis.signals.summary.map(s => `<span class="tag-${s.type === 'up' ? 'up' : s.type === 'down' ? 'down' : 'neutral'}">${s.label}</span>`).join('')}</div></div>
        ` : ''}
        ${analysis && analysis.score ? `
        <div class="card" style="border-left:3px solid ${analysis.score.total_score >= 70 ? '#c62828' : analysis.score.total_score >= 50 ? '#b8860b' : '#2e7d32'};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div><div class="card-title" style="margin-bottom:4px;"><i class="fas fa-star"></i> 智能评分</div>
                <div style="font-size:12px;color:#b5aea0;">${analysis.score.stars || ''} ${analysis.score.level || ''}</div></div>
                <div style="text-align:right;"><div style="font-size:28px;font-weight:700;color:#c7883c;">${analysis.score.total_score}</div><div style="font-size:12px;color:#b5aea0;">/ 100</div></div>
            </div>
            <div style="margin-top:12px;display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:#5a544a;">
                ${Object.entries(analysis.score.dimensions || {}).map(([k,v]) => `<span>${k}: <strong>${v.score}</strong> (${v.weight})</span>`).join('')}
            </div>
            <div style="margin-top:8px;font-size:14px;font-weight:500;">建议: <span style="color:${analysis.score.total_score >= 70 ? '#c62828' : analysis.score.total_score >= 50 ? '#b8860b' : '#2e7d32'}">${analysis.score.action}</span></div>
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
            datasets: [{ label: '单位净值', data: values, borderColor: '#c7883c', backgroundColor: 'rgba(199,136,60,0.06)', fill: true, tension: .3, pointRadius: 0, hoverRadius: 5, pointHitRadius: 10, borderWidth: 2 }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#2d2a26',
                    titleFont: { size: 12 },
                    bodyFont: { size: 13 },
                    padding: 10,
                    callbacks: {
                        label: ctx => ctx.parsed.y !== null ? `净值: ${ctx.parsed.y.toFixed(4)} 元` : ''
                    }
                }
            },
            scales: {
                y: { grid: { color: '#f0ebe2' }, ticks: { font: { size: 11 }, color: '#8a847a' }, title: { display: true, text: '净值（元）', color: '#8a847a', font: { size: 12 } } },
                x: {
                    grid: { display: false },
                    ticks: {
                        font: { size: 10 }, color: '#8a847a',
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
            <div><div class="stat-label">组合综合评分</div><div style="font-size:32px;font-weight:700;color:#c7883c;">${avg} <span style="font-size:14px;color:#b5aea0;">/ 100</span></div></div>
            <div style="text-align:center;"><div style="font-size:20px;">${avg >= 70 ? '⭐⭐⭐⭐' : avg >= 50 ? '⭐⭐⭐' : '⭐⭐'}</div><div style="font-size:14px;font-weight:600;">${avg >= 70 ? '良好' : avg >= 50 ? '一般' : '较差'}</div></div>
            <div style="text-align:right;">
                <div class="stat-label">建议操作</div><div style="font-size:16px;font-weight:600;color:#c62828;">买入 ${buyN} 只</div>
                <button class="btn btn-primary btn-sm" onclick="sendReport()" style="margin-top:8px;"><i class="fas fa-envelope"></i> 发送报告</button>
            </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        ${scores.map(x => {
            const sc = x.analysis.score;
            const sig = x.analysis.signals;
            const action = sc.action;
            const border = action.includes('买入') ? '#c62828' : action.includes('减仓') || action.includes('卖出') ? '#2e7d32' : '#b8860b';
            const badge = action.includes('买入') ? 'tag-up' : action.includes('减仓') || action.includes('卖出') ? 'tag-down' : 'tag-neutral';
            const sigs = sig && sig.summary ? sig.summary.map(s => `<span class="tag-${s.type === 'up' ? 'up' : s.type === 'down' ? 'down' : 'neutral'}" style="margin:2px 4px 2px 0;">${s.label}</span>`).join('') : '';
            const dims = sc.dimensions ? Object.entries(sc.dimensions).map(([k,v]) => `${k} ${v.score}`).join(' · ') : '';
            return `<div class="card" style="border-left:3px solid ${border};">
                <div class="pred-header"><div><strong style="font-size:15px;">${x.name}</strong> <span style="font-size:12px;color:#b5aea0;">${x.code}</span></div>
                <div style="display:flex;align-items:center;gap:12px;"><div class="pred-score"><div class="num">${sc.total_score}</div><div class="stat-label">/100</div></div><span class="${badge}" style="padding:4px 14px;font-size:13px;">${action}</span></div></div>
                <div style="margin:8px 0;font-size:12px;color:#5a544a;">${dims}</div>
                <div style="margin:8px 0;font-size:12px;color:#5a544a;">年化 ${x.analysis.indicators.annual_return || 'N/A'}% · 回撤 ${x.analysis.indicators.max_drawdown || 'N/A'}%</div>
                ${sigs ? `<div class="pred-signals">${sigs}</div>` : ''}
            </div>`;
        }).join('')}
        </div>
        <div class="card" style="margin-top:16px;">
            <div class="card-title"><i class="fas fa-info-circle"></i> 评分等级对照</div>
            <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;text-align:center;font-size:12px;">
                <div><div style="background:#c62828;color:#fff;padding:4px;border-radius:4px;font-weight:600;">90-100</div><div style="color:#c62828;margin-top:4px;">优质</div><div style="color:#c62828;">强烈买入</div></div>
                <div><div style="background:#c7883c;color:#fff;padding:4px;border-radius:4px;font-weight:600;">70-89</div><div style="color:#c7883c;margin-top:4px;">良好</div><div style="color:#c62828;">推荐买入</div></div>
                <div><div style="background:#b8860b;color:#fff;padding:4px;border-radius:4px;font-weight:600;">50-69</div><div style="color:#b8860b;margin-top:4px;">一般</div><div style="color:#b8860b;">观望/定投</div></div>
                <div><div style="background:#2e7d32;color:#fff;padding:4px;border-radius:4px;font-weight:600;">30-49</div><div style="color:#2e7d32;margin-top:4px;">较差</div><div style="color:#2e7d32;">建议减仓</div></div>
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
        <div style="font-size:13px;color:#b5aea0;">预计最终总资产</div>
        <div style="font-size:40px;font-weight:700;color:#c7883c;">${fmtMoney(total)}</div>
        <div style="font-size:14px;color:#5a544a;margin-top:8px;">本金 <strong>¥${fmt(principal)}</strong> · 收益 <strong style="color:#c62828;">${fmtMoney(profit)}</strong></div>
        <div style="font-size:12px;color:#b5aea0;">月投 ¥${fmt(monthly)} · ${years}年 · ${rate}%</div>`;
}

// ====== 设置 ======
function renderSettings(el) {
    el.innerHTML = `
    <div class="card" style="max-width:560px;">
        <div class="card-title"><i class="fas fa-database"></i> 数据缓存</div>
        <button class="btn btn-outline" onclick="clearCache()"><i class="fas fa-trash"></i> 清除缓存</button>
    </div>
    <div class="card" style="max-width:560px;">
        <div class="card-title"><i class="fas fa-info-circle"></i> 关于</div>
        <div style="font-size:13px;color:#5a544a;line-height:1.8;">
            <strong>基金驾驶舱</strong> v1.0<br>
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
                        <td><button class="btn btn-outline btn-sm" onclick="goAnalysis('${esc(f.code)}')">分析</button></td>
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
                                backgroundColor: '#2d2a26',
                                bodyFont: { size: 13 },
                                padding: 10,
                                callbacks: {
                                    label: ctx => ctx.parsed.x !== null ? fmtMoney(ctx.parsed.x) : ''
                                }
                            }
                        },
                        scales: {
                            x: {
                                grid: { color: '#f0ebe2' },
                                ticks: { font: { size: 11 }, color: '#8a847a', callback: function(v) {
                                    if (v >= 10000) return (v / 10000).toFixed(1) + '万';
                                    return v;
                                } }
                            },
                            y: { grid: { display: false }, ticks: { font: { size: 12 }, color: '#5a544a' } }
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
        const totalValue = res.total_value || 0;
        const totalProfit = res.total_profit || (totalValue - totalPrincipal);
        const schedule = res.schedule || [];

        el.innerHTML = `
            <div class="card dca-result">
                <div class="card-title"><i class="fas fa-chart-line"></i> 定投概览</div>
                <div class="dca-stats">
                    <div class="dca-stat"><div class="dca-value">${fmtMoney(monthlyAmount)}</div><div class="dca-label">每月投入</div></div>
                    <div class="dca-stat"><div class="dca-value">${months} 个月</div><div class="dca-label">定投时长</div></div>
                    <div class="dca-stat"><div class="dca-value">${expectedRate}%</div><div class="dca-label">预期年化</div></div>
                    <div class="dca-stat"><div class="dca-value">${fmtMoney(totalPrincipal)}</div><div class="dca-label">累计本金</div></div>
                    <div class="dca-stat"><div class="dca-value" style="color:${totalProfit >= 0 ? '#c62828' : '#2e7d32'};">${fmtMoney(totalProfit)}</div><div class="dca-label">预计收益</div></div>
                    <div class="dca-stat"><div class="dca-value">${fmtMoney(totalValue)}</div><div class="dca-label">预计总值</div></div>
                </div>
                ${schedule.length > 0 ? `
                <div class="table-wrap" style="max-height:400px;overflow-y:auto;">
                    <table>
                        <thead><tr><th>月份</th><th>投入金额</th><th>累计投入</th><th>累计总值</th><th>收益</th></tr></thead>
                        <tbody>${schedule.map(s => {
                            const profit = s.profit || 0;
                            return `<tr>
                                <td>${s.month || '--'}</td>
                                <td>${fmtMoney(s.investment || 0)}</td>
                                <td>${fmtMoney(s.cumulative_investment || 0)}</td>
                                <td class="${cls(profit)}">${fmtMoney(s.cumulative_value || 0)}</td>
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

async function renderAI(el) {
    el.innerHTML = `
        <div class="chat-suggestions" id="aiSuggestions">
            <span class="chip" onclick="suggestQuestion('我的持仓整体怎么样?')">我的持仓整体怎么样?</span>
            <span class="chip" onclick="suggestQuestion('今天哪只基金表现最好?')">今天哪只基金表现最好?</span>
            <span class="chip" onclick="suggestQuestion('我的组合风险高吗?')">我的组合风险高吗?</span>
        </div>
        <div class="chat-container">
            <div class="chat-messages" id="chatMessages"></div>
            <div class="chat-input-bar">
                <input id="chatInput" placeholder="输入您的问题..." onkeydown="if(event.key==='Enter') sendChatMessage()" />
                <button onclick="sendChatMessage()"><i class="fas fa-paper-plane"></i></button>
            </div>
        </div>`;
    renderChatMessages();
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
        return `<div class="chat-msg ${m.role}">
            <div class="bubble">${esc(m.content)}</div>
            <div class="time">${timeStr}</div>
        </div>`;
    }).join('');
    el.scrollTop = el.scrollHeight;
}

async function sendChatMessage() {
    const input = $('chatInput');
    const msg = input ? input.value.trim() : '';
    if (!msg) return;
    if (input) input.value = '';

    _aiMessages.push({ role: 'user', content: msg, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) });
    renderChatMessages();

    const el = $('chatMessages');
    if (el) {
        const ld = document.createElement('div');
        ld.className = 'chat-loading';
        ld.id = 'chatLoading';
        ld.innerHTML = '<div class="spinner" style="width:18px;height:18px;margin:0 auto 8px;"></div><span>思考中...</span>';
        el.appendChild(ld);
        el.scrollTop = el.scrollHeight;
    }

    try {
        const res = await api('/api/ai/chat', {
            method: 'POST',
            body: JSON.stringify({ message: msg })
        });

        const loadingEl = $('chatLoading');
        if (loadingEl) loadingEl.remove();

        const reply = (res && res.reply) ? res.reply : (res && res.message ? res.message : '抱歉，我没有理解您的问题，请重新描述。');
        _aiMessages.push({ role: 'ai', content: reply, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) });
        renderChatMessages();
    } catch (e) {
        if (e.name === 'AbortError') return;
        const loadingEl = $('chatLoading');
        if (loadingEl) loadingEl.remove();
        _aiMessages.push({ role: 'ai', content: '请求失败，请稍后重试。', time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) });
        renderChatMessages();
    }
}

function suggestQuestion(q) {
    const input = $('chatInput');
    if (input) input.value = q;
    sendChatMessage();
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
