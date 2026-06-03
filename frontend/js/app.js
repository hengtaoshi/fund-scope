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
        const ctx = chart.ctx;
        const active = chart._active[0];
        const x = active.element.x;
        const yAxis = chart.scales.y;
        const xAxis = chart.scales.x;

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

// 注册插件
Chart.register(crosshairPlugin);

// ====== 工具 ======
function $(id) { return document.getElementById(id); }
function qs(sel, ctx) { return (ctx || document).querySelector(sel); }
function qsa(sel, ctx) { return (ctx || document).querySelectorAll(sel); }

function showToast(msg) {
    const t = $('toast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._timer); t._timer = setTimeout(() => t.classList.remove('show'), 3000);
}

async function api(url, opts = {}) {
    try {
        const res = await fetch(API + url, {
            headers: { 'Content-Type': 'application/json', ...opts.headers },
            ...opts
        });
        return await res.json();
    } catch (e) {
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
    tools: ['工具', '定投计算器'],
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
}

function setDetailPeriod(period) {
    detailPeriod = period;
    renderDetailChart(window._detailNavData, period);
}

function periodBtn(label, period, active) {
    return `<span class="period-btn ${active ? 'active' : ''}" onclick="setChartPeriod('${period}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${active ? 'background:#c7883c;color:#fff;' : 'background:#f0ebe2;color:#5a544a;'}margin-left:4px;">${label}</span>`;
}

async function renderPage(page) {
    currentPage = page;
    const content = $('content');
    const fns = {
        dashboard: renderDashboard,
        portfolio: renderPortfolio,
        analysis: renderAnalysis,
        predict: renderPredict,
        tools: renderTools,
        settings: renderSettings,
    };
    content.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';
    if (fns[page]) await fns[page](content);
}

// ====== 概览 ======
async function renderDashboard(el) {
    const data = await api('/api/portfolio');
    if (!data || !data.holdings || data.holdings.length === 0) {
        el.innerHTML = '<div class="empty"><i class="fas fa-box-open"></i><p>还没有持仓，去「持仓」页面添加基金</p></div>';
        return;
    }
    const h = data.holdings;
    const totalVal = h.reduce((s, x) => s + x.current_total, 0);
    const totalCost = h.reduce((s, x) => s + x.cost_total, 0);
    const totalProfit = totalVal - totalCost;
    const totalPct = totalCost > 0 ? totalProfit / totalCost * 100 : 0;

    selectedFund = selectedFund || h[0].code;
    window._holdingsList = h;

    el.innerHTML = `
        <div class="stats">
            <div class="card stat-card"><div class="stat-label">总资产</div><div class="stat-value">${fmtMoney(totalVal)}</div></div>
            <div class="card stat-card"><div class="stat-label">累计收益</div><div class="stat-value ${cls(totalProfit)}">${fmtMoney(totalProfit)}</div><div class="stat-change ${cls(totalProfit)}">${fmtPct(totalPct)}</div></div>
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
            <thead><tr><th>基金名称</th><th>可用份额</th><th>成本单价</th><th>最新净值</th><th>持仓市值</th><th>收益</th><th>收益率</th><th></th></tr></thead>
            <tbody>${h.map(x => `<tr><td><strong>${x.name}</strong></td><td>${fmt(x.shares)}</td><td>${x.cost_nav.toFixed(4)}</td><td class="${cls(x.profit)}">${x.current_nav.toFixed(4)}</td><td class="${cls(x.profit)}">${fmtMoney(x.current_total)}</td><td class="${cls(x.profit)}">${fmtMoney(x.profit)}</td><td><span class="${tagCls(x.profit)}">${fmtPct(x.return_pct)}</span></td><td><button class="btn btn-outline btn-sm" onclick="goAnalysis('${x.code}')">详情</button></td></tr>`).join('')}</tbody>
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
    const canvas = $('pieChart');
    if (!canvas) return;
    if (chartInstances.pie) chartInstances.pie.destroy();
    chartInstances.pie = new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: holdings.map(x => x.name),
            datasets: [{ data: holdings.map(x => x.current_total), backgroundColor: genColors(holdings.length), borderWidth: 0 }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#5a544a', padding: 12, font: { size: 12 } } } }, cutout: '60%' }
    });
}

async function renderLineChart(code, period) {
    const canvas = $('lineChart');
    if (!canvas) return;
    const d = await api(`/api/fund/${code}/nav`);
    if (!d || !d.data) return;
    const data = filterByPeriod(d.data, period || chartPeriod);
    const labels = data.map(x => x.日期);
    const values = data.map(x => x.单位净值);

    if (chartInstances.line) {
        // 更新数据，不销毁重建
        chartInstances.line.data.labels = labels;
        chartInstances.line.data.datasets[0].data = values;
        chartInstances.line.update();
        return;
    }

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
                        maxTicksLimit: 8,
                        maxRotation: 0,
                        callback: function(val, idx) {
                            const label = this.getLabelForValue(val);
                            if (!label) return '';
                            // 只显示每月第一个标签（取日期前7位 YYYY-MM 判断是否变化）
                            const m = label.slice(0, 7);
                            if (idx === 0 || m !== this.getLabelForValue(this.ticks[idx-1]?.value || 0)?.slice(0,7)) {
                                return label.slice(5); // MM-DD
                            }
                            return '';
                        }
                    },
                    title: { display: true, text: '日期', color: '#8a847a', font: { size: 12 } }
                }
            }
        }
    });
}

// ====== 持仓 ======
async function renderPortfolio(el) {
    const data = await api('/api/portfolio');
    const h = data && data.holdings ? data.holdings : [];

    el.innerHTML = `
        <div style="margin-bottom:16px"><button class="btn btn-primary" onclick="showAddHolding()"><i class="fas fa-plus"></i> 添加持仓</button></div>
        ${h.length === 0 ? '<div class="empty"><i class="fas fa-box-open"></i><p>暂无持仓，点击上方按钮添加</p></div>' : `
        <div class="card"><table>
            <thead><tr><th>代码</th><th>名称</th><th>可用份额</th><th>成本单价</th><th>最新净值</th><th>市值</th><th>收益</th><th>收益率</th><th></th></tr></thead>
            <tbody>${h.map(x => `<tr>
                <td>${x.code}</td><td><strong>${x.name}</strong></td>
                <td>${fmt(x.shares)}</td><td>${x.cost_nav.toFixed(4)}</td>
                <td class="${cls(x.profit)}">${x.current_nav.toFixed(4)}</td>
                <td class="${cls(x.profit)}">${fmtMoney(x.current_total)}</td>
                <td class="${cls(x.profit)}">${fmtMoney(x.profit)}</td>
                <td><span class="${tagCls(x.profit)}">${fmtPct(x.return_pct)}</span></td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="showEditHolding(${x.id})" style="margin-right:4px"><i class="fas fa-edit"></i></button>
                    <button class="btn btn-outline btn-sm" onclick="deleteHolding(${x.id})"><i class="fas fa-trash"></i></button>
                </td>
            </tr>`).join('')}</tbody>
        </table></div>
        <div class="stats">
            <div class="card stat-card"><div class="stat-label">总投资成本</div><div class="stat-value" style="font-size:20px;">${fmtMoney(h.reduce((s,x)=>s+x.cost_total,0))}</div></div>
            <div class="card stat-card"><div class="stat-label">总市值</div><div class="stat-value" style="font-size:20px;">${fmtMoney(h.reduce((s,x)=>s+x.current_total,0))}</div></div>
            <div class="card stat-card"><div class="stat-label">总收益</div><div class="stat-value ${cls(h.reduce((s,x)=>s+x.profit,0))}" style="font-size:20px;">${fmtMoney(h.reduce((s,x)=>s+x.profit,0))}</div></div>
        </div>`}`;
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
            <div class="form-row">
                <div class="form-group"><label>可用份额</label><input id="addShares" type="number" step="0.01" min="0.01" /></div>
                <div class="form-group"><label>成本单价</label><input id="addCost" type="number" step="0.0001" min="0.001" placeholder="你买入时的净值" /></div>
            </div>
        </div>
        <div class="modal-footer"><button class="btn btn-outline" onclick="closeModal('addModal')">取消</button><button class="btn btn-primary" onclick="submitHolding()">确认添加</button></div>
    </div>`;
    document.body.appendChild(modal);
}

function closeModal(id) {
    const m = $(id); if (m) m.remove();
}

async function submitHolding() {
    const code = $('addCode').value.trim();
    const shares = parseFloat($('addShares').value);
    const cost = parseFloat($('addCost').value);
    if (!code || !shares || !cost) { showToast('请填写完整信息'); return; }
    const res = await api('/api/portfolio', { method: 'POST', body: JSON.stringify({ code, shares, cost_nav: cost }) });
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
    modal.innerHTML = `
    <div class="modal-box">
        <div class="modal-header">
            <div class="modal-title"><i class="fas fa-edit"></i> 修改持仓</div>
            <button class="modal-close" onclick="closeModal('editModal')">&times;</button>
        </div>
        <div class="modal-body">
            <div style="margin-bottom:16px">
                <strong>${item.name}</strong> <span style="color:#b5aea0;font-size:13px;">${item.code}</span>
            </div>
            <div class="form-row">
                <div class="form-group"><label>可用份额</label><input id="editShares" type="number" step="0.01" min="0.01" value="${item.shares}" /></div>
                <div class="form-group"><label>成本单价</label><input id="editCost" type="number" step="0.0001" min="0.001" value="${item.cost_nav}" /></div>
            </div>
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
    if (!shares || !cost) { showToast('请填写完整信息'); return; }
    const res = await api(`/api/portfolio/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ shares, cost_nav: cost, notes })
    });
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
        <span style="margin-left:auto">${['1月','3月','6月','1年'].map((l,i) => `<span class="period-btn ${detailPeriod === ['1m','3m','6m','1y'][i] ? 'active' : ''}" onclick="setDetailPeriod('${['1m','3m','6m','1y'][i]}')" style="cursor:pointer;padding:2px 10px;border-radius:4px;font-size:12px;${detailPeriod === ['1m','3m','6m','1y'][i] ? 'background:#c7883c;color:#fff;' : 'background:#f0ebe2;color:#5a544a;'}margin-left:4px;">${l}</span>`).join('')}</span>
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

    setTimeout(() => renderDetailChart(nav.data, detailPeriod), 50);
}

function renderDetailChart(data, period) {
    const canvas = $('detailChart');
    if (!canvas) return;
    data = filterByPeriod(data, period || detailPeriod);
    const labels = data.map(x => x.日期);
    const values = data.map(x => x.单位净值);

    if (chartInstances.detail) {
        chartInstances.detail.data.labels = labels;
        chartInstances.detail.data.datasets[0].data = values;
        chartInstances.detail.update();
        return;
    }
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
                        maxTicksLimit: 8, maxRotation: 0,
                        callback: function(val, idx) {
                            const label = this.getLabelForValue(val);
                            if (!label) return '';
                            const m = label.slice(0, 7);
                            if (idx === 0 || m !== this.getLabelForValue(this.ticks[idx-1]?.value || 0)?.slice(0,7)) {
                                return label.slice(5);
                            }
                            return '';
                        }
                    },
                    title: { display: true, text: '日期', color: '#8a847a', font: { size: 12 } }
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
            <div style="text-align:right;"><div class="stat-label">建议操作</div><div style="font-size:16px;font-weight:600;color:#c62828;">买入 ${buyN} 只</div></div>
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
        <div class="card-title"><i class="fas fa-envelope"></i> 邮件通知</div>
        <div class="form-group"><label>接收邮箱</label><input id="emailAddr" placeholder="your@email.com" /></div>
        <button class="btn btn-primary" onclick="sendTestEmail()"><i class="fas fa-paper-plane"></i> 测试邮件</button>
        <div style="margin-top:8px;font-size:12px;color:#b5aea0;">SMTP 配置通过后端环境变量设置</div>
    </div>
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

async function sendTestEmail() {
    const email = $('emailAddr').value;
    if (!email) { showToast('请先填写邮箱'); return; }
    const res = await api('/api/test-email', { method: 'POST' });
    showToast(res?.message || '请求失败');
}

async function clearCache() {
    // Call a special endpoint to clear cache (or just reload)
    showToast('缓存已清除（需后端支持）');
}

// ====== 启动 ======
renderPage('dashboard');
