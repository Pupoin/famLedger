/**
 * Standalone JavaScript Engine for CMB Bill Dashboard
 */

const DashboardUI = {
    // Shared State for Interactions
    state: {
        currentRecords: [],
        currentSort: { key: 'amount', asc: false },
        lastHover: { type: null, idx: -1, name: '', data: null },
        isLockingScroll: false,
        longpressTimer: null,
        isLongPressTriggered: false,
        startPos: { x: 0, y: 0 },
        lastTapTime: 0
    },

    // Universal Mobile Tooltip Position Helper
    getMobileTooltipPos: function(point, size, containerId) {
        const isMobile = window.innerWidth <= 768;
        if (!isMobile) return null;

        const dom = document.getElementById(containerId);
        const chartRect = dom.getBoundingClientRect();
        
        let x = point[0] - size.contentSize[0] / 2;
        let y = point[1] - size.contentSize[1] - 40;

        const globalX = chartRect.left + x;
        const globalY = chartRect.top + y;

        if (globalX < 10) x = 10 - chartRect.left;
        if (globalX + size.contentSize[0] > window.innerWidth - 10) {
            x = window.innerWidth - 10 - chartRect.left - size.contentSize[0];
        }
        if (globalY < 60) y = point[1] + 20;

        return [x, y];
    },

    renderSortedTable: function() {
        const ovBody = document.getElementById('ov-body-table');
        if (!ovBody) return;

        const arrow = (key) => {
            if (this.state.currentSort.key !== key) return '<span style="color:var(--btn-ghost-text);margin-left:4px;">↕</span>';
            return this.state.currentSort.asc ? '<span style="margin-left:4px;">▲</span>' : '<span style="margin-left:4px;">▼</span>';
        };
        const isMobile = window.innerWidth <= 768;
        const tWidth = isMobile ? '' : 'width:130px;';
        const aWidth = isMobile ? '' : 'width:90px;';
        const actWidth = isMobile ? '' : 'width:60px;';
        
        let html = `
            <table class="responsive-table" style="width:100%; border-collapse:collapse; font-size:13px; table-layout:fixed; color: var(--ov-text);">
                <thead>
                    <tr style="border-bottom:2px solid var(--table-border); position:sticky; top:0; background:var(--ov-bg); z-index:10;">
                        <th class="col-time" style="text-align:left; cursor:pointer; ${tWidth}" onclick="DashboardUI.handleSort('time')">时间 ${arrow('time')}</th>
                        <th class="col-action" style="text-align:left; ${actWidth}">行为</th>
                        <th style="text-align:left;">商户/交易</th>
                        <th class="col-amount" style="text-align:right; cursor:pointer; ${aWidth}" onclick="DashboardUI.handleSort('amount')">金额 ${arrow('amount')}</th>
                    </tr>
                </thead>
                <tbody>
                    ${this.state.currentRecords.map(item => {
                        let rmk = item.remark || '';
                        if (rmk === 'None' || rmk === 'nan' || rmk === 'NaN') rmk = '';
                        const safeRemark = rmk.replace(/'/g, "\\'").replace(/"/g, '&quot;');
                        return `
                        <tr style="border-bottom:1px solid var(--table-row);">
                            <td style="white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.time}</td>
                            <td>${item.behaviour}</td>
                            <td style="word-break:break-all; cursor:pointer;" onclick="event.stopPropagation(); window.DashboardUI.editRemark(${item.id}, '${safeRemark}')">
                                ${item.business}
                                <span style="font-size:0.85em; color:gray; margin-left:4px;" title="编辑备注">
                                    📝 ${rmk}
                                </span>
                            </td>
                            <td style="text-align:right; font-weight:600;">
                                ${parseFloat(item.amount).toLocaleString('zh-CN', {minimumFractionDigits: 2})}
                            </td>
                        </tr>
                        `;
                    }).join('')}
                </tbody>
            </table>`;
        ovBody.innerHTML = html;
    },

    handleSort: function(key) {
        if (this.state.currentSort.key === key) { this.state.currentSort.asc = !this.state.currentSort.asc; } 
        else { this.state.currentSort.key = key; this.state.currentSort.asc = false; }
        
        this.state.currentRecords.sort((a, b) => {
            let v1 = a[key], v2 = b[key];
            if (key === 'amount') return this.state.currentSort.asc ? v1 - v2 : v2 - v1;
            return this.state.currentSort.asc ? String(v1).localeCompare(String(v2)) : String(v2).localeCompare(String(v1));
        });
        this.renderSortedTable();
    },

    editRemark: async function(id, currentRemark) {
        if (!id) return;
        const newRemark = prompt("编辑备注 (留空以清除)：", currentRemark || "");
        if (newRemark === null) return; // User cancelled

        try {
            const res = await fetch(`/api/remark/${id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ remark: newRemark.trim() })
            });
            if (res.ok) {
                // Update local state and re-render
                const idx = this.state.currentRecords.findIndex(r => Number(r.id) === Number(id));
                if (idx !== -1) {
                    this.state.currentRecords[idx].remark = newRemark.trim();
                    this.renderSortedTable();
                }
                
                // Also trigger a global update so the feed gets the new remark if we fetch again
                if (typeof window.getRawData === 'function') {
                    const globalData = window.getRawData();
                    if (globalData && globalData.feed) {
                        const feedIdx = globalData.feed.findIndex(r => Number(r.id) === Number(id));
                        if (feedIdx !== -1) {
                            globalData.feed[feedIdx].remark = newRemark.trim();
                            if (typeof window.updateFeedGlobal === 'function') {
                                window.updateFeedGlobal();
                            }
                        }
                    }
                }
            } else {
                alert("保存备注失败");
            }
        } catch (e) {
            console.error("Save remark error", e);
            alert("保存备注失败: " + e.message);
        }
    },

    showOverlay: function(records, title, color) {
        if (!records) return;
        this.state.currentRecords = [...records];
        this.state.currentSort = { key: 'time', asc: false };
        this.state.currentRecords.sort((a, b) => String(b.time).localeCompare(String(a.time)));
        
        const overlay = document.getElementById('overlay-container');
        const ovTitle = document.getElementById('ov-title');
        const ovColorDot = document.getElementById('ov-color-dot');
        const ovSum = document.getElementById('ov-sum');

        if (ovTitle) ovTitle.textContent = title;
        if (ovColorDot) ovColorDot.style.backgroundColor = color || '#ccc';
        
        let totalCost = this.state.currentRecords.reduce((s, i) => s + (parseFloat(i.amount) || 0), 0);
        if (ovSum) ovSum.textContent = "· ¥" + totalCost.toLocaleString(undefined, {minimumFractionDigits: 2});
        
        this.renderSortedTable();
        if (overlay) overlay.classList.add('show');
    },

    initSankey: function(containerId, overlayId, config, theme) {
        const chartDom = document.getElementById(containerId);
        if (!chartDom) return;

        const height = config.sankey_chart_height || 700;
        chartDom.style.height = (height - 50) + 'px';
        if (chartDom.parentElement) chartDom.parentElement.style.height = height + 'px';

        const isDark = theme === 'dark';
        const myChart = echarts.init(chartDom, isDark ? 'dark' : null);
        let option = config.sankey_option;

        const ttBg = isDark ? 'rgba(31, 41, 55, 0.95)' : 'rgba(255, 255, 255, 0.95)';
        const ttBorder = isDark ? '#4b5563' : '#eee';
        const ttText = isDark ? '#f9fafb' : '#374151';
        const ttSubText = isDark ? '#9ca3af' : '#666';

        function activateJsCode(obj) {
            for (let key in obj) {
                if (typeof obj[key] === 'string') {
                    let str = obj[key].replace(/--x_x--0_0--/g, '');
                    const isHtml = str.trim().startsWith('<');
                    if (key === 'click_html' || key === 'detail' || isHtml) { obj[key] = str; continue; }
                    if (str.includes('function') || str.includes('=>')) {
                        try { obj[key] = new Function('return ' + str)(); } 
                        catch (e) { obj[key] = str; }
                    } else { obj[key] = str; }
                } else if (typeof obj[key] === 'object' && obj[key] !== null) { activateJsCode(obj[key]); }
            }
        }
        
        if (JSON.stringify(option).includes("__js_code__")) activateJsCode(option);

        if (option.series && option.series[0]) {
            if (window.innerWidth <= 768) option.series[0].nodeWidth = 10;
            option.tooltip = {
                trigger: 'item', backgroundColor: ttBg, borderColor: ttBorder, borderWidth: 1, textStyle: { color: ttText, fontSize: 13 },
                position: (point, params, dom, rect, size) => this.getMobileTooltipPos(point, size, containerId),
                formatter: (params) => {
                    const isMobile = window.innerWidth <= 768;
                    const fs = isMobile ? '10px' : '13px';
                    const detailFs = isMobile ? '8.5px' : '12px';
                    const lh = isMobile ? '1.1' : '1.4';
                    if(params.dataType === 'node'){
                        const d = params.data || {};
                        const color = d.side === 'left' ? '#22c55e' : (d.side === 'right' ? '#ef4444' : (d.total < 0 ? '#ef4444' : '#22c55e'));
                        const label = d.side === 'left' ? '(流入)' : (d.side === 'right' ? '(支出)' : (d.total < 0 ? '(净支出)' : '(净流入/退款)'));
                        const total = Number(d.total || 0).toLocaleString('zh-CN', {minimumFractionDigits: 2});
                        const percent = Number(d.percent || 0).toFixed(1);
                        return `<div style="max-width:min(400px, 80vw); font-size:${fs}; color:${ttText}; line-height:${lh};">
                            <b>${d.display || params.name}</b> · <span style="color:${color}">${total}</span> ${label} · <b>${percent}%</b><br>
                            <div style="font-size:${detailFs}; color:${ttSubText}; margin-top:${isMobile?'1px':'4px'}; line-height:1.1;">${d.detail || '暂无明细'}</div>
                        </div>`;
                    }
                    return `<div style="font-size:${fs}; color:${ttText};">商户: ${params.data.business || '-'}<br>金额: ¥${Number(params.value).toLocaleString('zh-CN', {minimumFractionDigits: 2})}</div>`;
                }
            };
            option.series[0].label = {
                show: true, fontSize: 12,
                formatter: (params) => {
                    const name = params.name || '';
                    if (name.toLowerCase().includes('placeholder')) return '';
                    return params.data.display || name;
                }
            };
        }

        myChart.setOption(option);
        
        myChart.on('mouseover', (params) => {
            this.state.lastHover = { type: params.dataType === 'node' ? 'node' : 'link', idx: params.dataIndex, name: params.name, data: params.data };
        });

        myChart.getZr().on('mousedown', (e) => {
            this.state.isLongPressTriggered = false;
            const ev = e.event;
            this.state.startPos = { x: ev.clientX || (ev.touches && ev.touches[0].clientX), y: ev.clientY || (ev.touches && ev.touches[0].clientY) };
            if (e.target) {
                let ecData = null;
                for (let key in e.target) { if (key.indexOf('__ec_inner') !== -1) { ecData = e.target[key]; break; } }
                if (ecData && ecData.dataType === 'node') {
                    this.state.isLockingScroll = true;
                    this.state.longpressTimer = setTimeout(() => {
                        this.state.isLongPressTriggered = true;
                        myChart.dispatchAction({ type: 'hideTip' });
                        const node = myChart.getOption().series[0].data[ecData.dataIndex];
                        this.showOverlay(node.click_html ? node.click_html.records : [], node.display || node.name, node.itemStyle ? node.itemStyle.color : null);
                    }, 400);
                }
            }
        });

        myChart.getZr().on('mouseup', () => { if (this.state.longpressTimer) { clearTimeout(this.state.longpressTimer); this.state.longpressTimer = null; } this.state.isLockingScroll = false; });
        myChart.getZr().on('mousemove', (e) => {
            if (this.state.longpressTimer) {
                const ev = e.event;
                const currX = ev.clientX || (ev.touches && ev.touches[0].clientX);
                const currY = ev.clientY || (ev.touches && ev.touches[0].clientY);
                const dist = Math.sqrt(Math.pow(currX - this.state.startPos.x, 2) + Math.pow(currY - this.state.startPos.y, 2));
                if (dist > 8) { clearTimeout(this.state.longpressTimer); this.state.longpressTimer = null; }
            }
        });

        chartDom.addEventListener('click', (e) => {
            if (this.state.isLongPressTriggered) {
                e.stopPropagation();
                this.state.isLongPressTriggered = false;
            }
        });

        myChart.on('click', (params) => {
            if (window.innerWidth > 768 && params.dataType === 'node' && params.data && params.data.click_html) {
                if (params.event && params.event.event) {
                    params.event.event.stopPropagation();
                }
                myChart.dispatchAction({ type: 'hideTip' });
                this.showOverlay(params.data.click_html.records || [], params.data.display || params.name, params.data.itemStyle ? params.data.itemStyle.color : null);
            }
        });

        window.addEventListener('resize', () => myChart.resize());
        return myChart;
    }
};

window.DashboardUI = DashboardUI;
window.handleSort = (key) => DashboardUI.handleSort(key); // For legacy HTML onclicks
