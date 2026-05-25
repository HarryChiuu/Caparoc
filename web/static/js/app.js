const { createApp, reactive, ref, computed, watch, onMounted, onUnmounted, nextTick } = Vue;

createApp({
    setup() {

        // -- 頁面導覽 --
        const currentPage = ref('dashboard');
        const sidebarCollapsed = ref(false);

        const navItems = [
            { page: 'dashboard',        icon: '📊', label: '儀表板' },
            { page: 'charts',           icon: '📈', label: '圖表監控' },
            { page: 'channel-settings', icon: '⚙️',  label: '通道設定' },
            { page: 'logs',             icon: '📋', label: '系統日誌' },
            { page: 'connection',       icon: '🔧', label: '連線設定' },
        ];

        function navigate(page) {
            currentPage.value = page;
            if (window.innerWidth < 640) sidebarCollapsed.value = true;
        }

        function toggleSidebar() {
            sidebarCollapsed.value = !sidebarCollapsed.value;
        }

        // -- 設備狀態 --
        const state = reactive({
            connected: false,
            device_ip: '',
            voltage: 0,
            total_current: 0,
            module_count: 0,
            channels: [],
            undervoltage: false,
            overvoltage: false,
            system_error: false,
            error: '',
        });

        const ipInput = ref('');
        const connecting = ref(false);  // 防止重複點擊連線
        const isShuttingDown = ref(false);  // 關閉中過渡狀態
        // 設備網路資訊：從 localStorage 恢復（斷線後保留上次資料）
        const networkInfo = ref((() => {
            try {
                const s = localStorage.getItem('caparoc_network_info');
                return s ? JSON.parse(s) : null;
            } catch (_) { return null; }
        })());
        let ws = null;
        let wsRetryTimer = null;
        let _wasConnected = false;  // 連線狀態變化偵測

        // 圖表監控 - 狀態 & 歷史緩衝（宣告於 applyStatus 之前）
        const chartWindow        = ref(30);
        const chartPaused        = ref(false);
        const chartHistoryMode   = ref(false);
        const chartChannelVisible = reactive({});
        const _chartHistory = { timestamps: [], voltage: [], totalCurrent: [], channels: {} };
        const CHART_MAX_PTS = 1800;
        const CHART_COLORS  = ['#3b82f6','#10b981','#f97316','#8b5cf6','#ef4444','#06b6d4','#84cc16','#ec4899'];
        let   _globalChart  = null;
        const _moduleCharts = {};

        function fmt(v) {
            return (v != null) ? Number(v).toFixed(1) : '—';
        }

        function barPct(ch) {
            if (!ch.nominal_amps) return 0;
            return Math.min(100, (ch.current_amps / ch.nominal_amps) * 100);
        }

        function cardClass(ch) {
            if (ch.overload || ch.short_circuit || ch.hardware_fault) return 'fault';
            if (ch.warn_80) return 'warn';
            if (ch.on) return 'on';
            return 'off';
        }

        function barClass(ch) {
            if (ch.overload || ch.short_circuit) return 'bar-fault';
            if (ch.warn_80) return 'bar-warn';
            return 'bar-ok';
        }

        function applyStatus(data) {
            state.connected     = data.connected ?? false;
            state.device_ip     = data.device_ip ?? '';
            // 首次收到 WebSocket 資料時，用實際 IP 初始化輸入框
            if (!ipInput.value && state.device_ip) { ipInput.value = state.device_ip; }
            state.error         = state.connected ? '' : (data.error ?? '');
            state.voltage       = data.voltage ?? 0;
            state.total_current = data.total_current ?? 0;
            state.module_count  = data.module_count ?? 0;
            state.channels      = data.channels ?? [];
            // 初始化新通道的可見性（預設全部顯示）
            for (const ch of state.channels) {
                if (chartChannelVisible[ch.id] === undefined) chartChannelVisible[ch.id] = true;
            }
            state.undervoltage  = data.undervoltage ?? false;
            state.overvoltage   = data.overvoltage ?? false;
            state.system_error  = data.system_error ?? false;
            // 連線狀態變化偵測
            if (!_wasConnected && state.connected) fetchNetworkInfo();
            _wasConnected = state.connected;
            // 圖表歷史累積（不論是否在圖表頁都持續記錄）
            if (!chartPaused.value) {
                const t = new Date();
                const lbl = `${String(t.getHours()).padStart(2,'0')}:${String(t.getMinutes()).padStart(2,'0')}:${String(t.getSeconds()).padStart(2,'0')}`;
                _chartHistory.timestamps.push(lbl);
                _chartHistory.voltage.push(data.voltage ?? 0);
                _chartHistory.totalCurrent.push(data.total_current ?? 0);
                for (const ch of (data.channels ?? [])) {
                    if (!_chartHistory.channels[ch.id]) _chartHistory.channels[ch.id] = [];
                    _chartHistory.channels[ch.id].push(ch.current_amps ?? 0);
                }
                if (_chartHistory.timestamps.length > CHART_MAX_PTS) {
                    _chartHistory.timestamps.shift();
                    _chartHistory.voltage.shift();
                    _chartHistory.totalCurrent.shift();
                    for (const id in _chartHistory.channels)
                        if (_chartHistory.channels[id].length > CHART_MAX_PTS) _chartHistory.channels[id].shift();
                }
                if (currentPage.value === 'charts' && !chartHistoryMode.value && _globalChart) _updateCharts();
            }
        }

        function connectWs() {
            clearTimeout(wsRetryTimer);
            if (ws) { try { ws.close(); } catch (_) {} }
            ws = new WebSocket(`ws://${location.host}/ws/status`);
            ws.onmessage = (e) => applyStatus(JSON.parse(e.data));
            ws.onclose   = () => { wsRetryTimer = setTimeout(connectWs, 3000); };
            ws.onerror   = () => { ws.close(); };
        }

        async function doConnect() {
            if (connecting.value) return;   // 防止重複點擊
            connecting.value = true;
            state.error = '';
            const ip = ipInput.value.trim();
            const qs = ip ? `?ip=${encodeURIComponent(ip)}` : '';
            try {
                const r = await fetch(`/api/connect${qs}`, { method: 'POST' });
                if (!r.ok) {
                    const body = await r.json();
                    state.error = body.detail ?? '連線失敗';
                }
            } catch (e) {
                state.error = '無法連線到伺服器';
            } finally {
                connecting.value = false;
            }
        }

        async function doDisconnect() {
            await fetch('/api/disconnect', { method: 'POST' });
        }

        async function fetchNetworkInfo() {
            try {
                const r = await fetch('/api/device/network');
                if (r.ok) {
                    const data = await r.json();
                    networkInfo.value = data;
                    try { localStorage.setItem('caparoc_network_info', JSON.stringify(data)); } catch (_) {}
                }
            } catch (_) {}
        }

        async function toggleCh(ch) {
            const action = ch.on ? 'off' : 'on';
            await fetch(`/api/channel/${ch.id}/${action}`, { method: 'POST' });
        }

        // -- 通道設定 --
        const nominalInputs = reactive({});
        const nominalFeedback = reactive({});
        const batchNominal = ref('');
        const batchStatus = reactive({ ok: false, msg: '' });

        async function setNominal(chId) {
            const val = Math.round(parseFloat(nominalInputs[chId]));
            if (isNaN(val) || val < 1 || val > 20) {
                nominalFeedback[chId] = { ok: false, msg: '請輸入 1–20 A' };
                return;
            }
            try {
                const r = await fetch(`/api/channel/${chId}/nominal?current_amps=${val}`, { method: 'POST' });
                if (r.ok) {
                    nominalFeedback[chId] = { ok: true, msg: '✓ 已設定' };
                    nominalInputs[chId] = '';
                    setTimeout(() => { nominalFeedback[chId] = { ok: false, msg: '' }; }, 3000);
                } else {
                    const body = await r.json().catch(() => ({}));
                    nominalFeedback[chId] = { ok: false, msg: body.detail ?? '設定失敗' };
                }
            } catch (e) {
                nominalFeedback[chId] = { ok: false, msg: '無法連線' };
            }
        }

        async function setAllNominal() {
            const val = Math.round(parseFloat(batchNominal.value));
            if (isNaN(val) || val < 1 || val > 20) {
                batchStatus.ok = false;
                batchStatus.msg = '請輸入 1–20 A';
                return;
            }
            let ok = 0, fail = 0;
            for (const ch of state.channels) {
                const r = await fetch(`/api/channel/${ch.id}/nominal?current_amps=${val}`, { method: 'POST' });
                r.ok ? ok++ : fail++;
            }
            batchStatus.ok = fail === 0;
            batchStatus.msg = fail === 0 ? `✓ 全部 ${ok} 個通道設定完成` : `${ok} 成功，${fail} 失敗`;
            batchNominal.value = '';
            setTimeout(() => { batchStatus.msg = ''; }, 4000);
        }


        // -- 系統日誌 --
        const logEntries   = ref([]);
        const logTotal     = ref(0);
        const logPage      = ref(0);
        const logPageSize  = ref(20);
        const logFilter    = ref('all');
        const logAutoScroll = ref(true);
        let   _logTimer    = null;

        const logTotalPages = computed(() =>
            Math.max(1, Math.ceil(logTotal.value / logPageSize.value))
        );

        async function fetchLogs() {
            const offset = logPage.value * logPageSize.value;
            try {
                const r = await fetch(
                    `/api/logs?level=${logFilter.value}&limit=${logPageSize.value}&offset=${offset}`
                );
                if (r.ok) {
                    const data = await r.json();
                    logTotal.value   = data.total;
                    logEntries.value = data.entries;
                    // 頁碼超出範圍時自動修正
                    const maxPage = Math.max(0, logTotalPages.value - 1);
                    if (logPage.value > maxPage) logPage.value = maxPage;
                }
            } catch (_) {}
        }

        async function clearLogs() {
            await fetch('/api/logs/clear', { method: 'POST' });
            logEntries.value = [];
            logTotal.value   = 0;
            logPage.value    = 0;
        }

        function setPageSize(n) {
            logPageSize.value = n;
            logPage.value     = 0;
            fetchLogs();
        }

        function toggleLogAuto() {
            logAutoScroll.value = !logAutoScroll.value;
        }

        function logPrevPage() {
            if (logPage.value > 0) { logPage.value--; fetchLogs(); }
        }

        function logNextPage() {
            if (logPage.value < logTotalPages.value - 1) { logPage.value++; fetchLogs(); }
        }

        // -- 圖表監控 computed --
        const activeModules = computed(() =>
            [...new Set(state.channels.map(ch => ch.module))].sort((a, b) => a - b)
        );
        const channelsByModule = computed(() => {
            const map = {};
            for (const ch of state.channels) {
                if (!map[ch.module]) map[ch.module] = [];
                map[ch.module].push(ch);
            }
            return map;
        });

        // -- 圖表監控函式 --
        function _getChartSlice() {
            const n = chartWindow.value;
            return {
                labels:       _chartHistory.timestamps.slice(-n),
                voltage:      _chartHistory.voltage.slice(-n),
                totalCurrent: _chartHistory.totalCurrent.slice(-n),
            };
        }

        function _destroyCharts() {
            if (_globalChart) { _globalChart.destroy(); _globalChart = null; }
            for (const mod of Object.keys(_moduleCharts)) {
                if (_moduleCharts[mod]) _moduleCharts[mod].destroy();
                delete _moduleCharts[mod];
            }
        }

        async function _initCharts() {
            _destroyCharts();
            chartHistoryMode.value = false;
            // 從後端載入歷史資料
            try {
                const r = await fetch('/api/history?minutes=30');
                if (r.ok) {
                    const hist = await r.json();
                    _chartHistory.timestamps   = hist.timestamps    || [];
                    _chartHistory.voltage      = hist.voltage       || [];
                    _chartHistory.totalCurrent = hist.total_current || [];
                    _chartHistory.channels     = {};
                    for (const [id, vals] of Object.entries(hist.channels || {}))
                        _chartHistory.channels[parseInt(id)] = vals;
                }
            } catch (_) {}

            // 確認仍在圖表頁（fetch 期間可能已離頁）
            if (currentPage.value !== 'charts') return;
            const gcEl = document.getElementById('globalChart');
            if (!gcEl) return;

            const zoomCfg = {
                pan:  { enabled: true,  mode: 'x',
                        onPanComplete:  () => { chartHistoryMode.value = true; } },
                zoom: { wheel: { enabled: true }, mode: 'x',
                        onZoomComplete: () => { chartHistoryMode.value = true; } },
            };
            const slice = _getChartSlice();

            _globalChart = new Chart(gcEl.getContext('2d'), {
                type: 'line',
                data: {
                    labels: slice.labels,
                    datasets: [
                        { label: '電壓 (V)',   data: slice.voltage,       yAxisID: 'yV',
                          borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.08)',
                          tension: 0.3, pointRadius: 0, borderWidth: 2 },
                        { label: '總電流 (A)', data: slice.totalCurrent,  yAxisID: 'yA',
                          borderColor: '#f97316', backgroundColor: 'rgba(249,115,22,0.08)',
                          tension: 0.3, pointRadius: 0, borderWidth: 2 },
                    ],
                },
                options: {
                    animation: false, responsive: true, maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        yV: { type: 'linear', position: 'left',
                              title: { display: true, text: '電壓 (V)', color: '#3b82f6' },
                              grid: { color: 'rgba(255,255,255,0.05)' },
                              ticks: { color: '#3b82f6', callback: v => Number(v).toFixed(2) } },
                        yA: { type: 'linear', position: 'right', min: 0,
                              title: { display: true, text: '電流 (A)', color: '#f97316' },
                              grid: { drawOnChartArea: false }, ticks: { color: '#f97316' } },
                        x:  { grid: { color: 'rgba(255,255,255,0.05)' },
                              ticks: { maxTicksLimit: 6, color: '#9aaac4', maxRotation: 0 } },
                    },
                    plugins: {
                        legend: { labels: { color: '#c5d0e6', usePointStyle: true } },
                        tooltip: {
                            callbacks: {
                                label: ctx => {
                                    const v = ctx.parsed.y;
                                    if (ctx.dataset.yAxisID === 'yV')
                                        return `電壓: ${Number(v).toFixed(2)} V`;
                                    return `總電流: ${Number(v).toFixed(1)} A`;
                                },
                            },
                        },
                        zoom: zoomCfg,
                    },
                },
            });

            // 各模組獨立電流圖
            const n = chartWindow.value;
            for (const mod of activeModules.value) {
                const el = document.getElementById(`moduleChart-${mod}`);
                if (!el) continue;
                const modChannels = channelsByModule.value[mod] || [];
                const datasets = modChannels.map((ch, i) => ({
                    label: `CH${ch.channel}`,
                    data:  (_chartHistory.channels[ch.id] || []).slice(-n),
                    borderColor:     CHART_COLORS[i % CHART_COLORS.length],
                    backgroundColor: 'transparent',
                    tension: 0.3, pointRadius: 0, borderWidth: 1.5,
                    hidden: chartChannelVisible[ch.id] === false,
                }));
                _moduleCharts[mod] = new Chart(el.getContext('2d'), {
                    type: 'line',
                    data: { labels: slice.labels, datasets },
                    options: {
                        animation: false, responsive: true, maintainAspectRatio: false,
                        interaction: { mode: 'index', intersect: false },
                        scales: {
                            y: { min: 0,
                                 title: { display: true, text: '電流 (A)', color: '#9aaac4' },
                                 grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#9aaac4' } },
                            x: { grid: { color: 'rgba(255,255,255,0.05)' },
                                 ticks: { maxTicksLimit: 6, color: '#9aaac4', maxRotation: 0 } },
                        },
                        plugins: {
                            legend: { labels: { color: '#c5d0e6', usePointStyle: true } },
                            zoom: zoomCfg,
                        },
                    },
                });
            }
        }

        function _updateCharts() {
            if (!_globalChart) return;
            const n = chartWindow.value;
            const slice = _getChartSlice();
            _globalChart.data.labels           = slice.labels;
            _globalChart.data.datasets[0].data = slice.voltage;
            _globalChart.data.datasets[1].data = slice.totalCurrent;
            _globalChart.update('none');
            for (const [modStr, modChart] of Object.entries(_moduleCharts)) {
                if (!modChart) continue;
                const mod = parseInt(modStr);
                modChart.data.labels = slice.labels;
                for (const ch of (channelsByModule.value[mod] || [])) {
                    const ds = modChart.data.datasets.find(d => d.label === `CH${ch.channel}`);
                    if (ds) ds.data = (_chartHistory.channels[ch.id] || []).slice(-n);
                }
                modChart.update('none');
            }
        }

        function toggleChannelVisible(chId) {
            chartChannelVisible[chId] = !chartChannelVisible[chId];
            const ch = state.channels.find(c => c.id === chId);
            if (!ch) return;
            const modChart = _moduleCharts[ch.module];
            if (!modChart) return;
            const ds = modChart.data.datasets.find(d => d.label === `CH${ch.channel}`);
            if (ds) { ds.hidden = !chartChannelVisible[chId]; modChart.update('none'); }
        }

        function jumpToLive() {
            if (_globalChart) _globalChart.resetZoom();
            for (const chart of Object.values(_moduleCharts)) {
                if (chart) chart.resetZoom();
            }
            // 必須在 resetZoom() 之後設定，否則 onZoomComplete callback 會把它改回 true
            chartHistoryMode.value = false;
            if (_globalChart) _updateCharts();
        }

        function setChartWindow(n) {
            chartWindow.value = n;
            jumpToLive();
        }

        function toggleChartPause() { chartPaused.value = !chartPaused.value; }

        async function doCloseTab() {
            if (isShuttingDown.value) return;
            isShuttingDown.value = true;
            // 停止 WebSocket 重連
            clearTimeout(wsRetryTimer);
            if (ws) { try { ws.close(); } catch (_) {} }
            // 呼叫後端關閉
            try {
                await fetch('/api/shutdown', { method: 'POST' });
                // 嘗試關閉分頁（window.open 開啟時有效）
                setTimeout(() => window.close(), 400);
            } catch (_) {
                // API 呼叫失敗（網路問題），恢復按鈕可用
                isShuttingDown.value = false;
            }
        }

        // 切換到 logs 頁時啟動輪詢；離開時停止
        watch(currentPage, (page, prevPage) => {
            clearInterval(_logTimer);
            _logTimer = null;
            if (page === 'logs') {
                logPage.value = 0;   // 進入日誌頁永遠先看最新
                fetchLogs();
                if (logAutoScroll.value)
                    _logTimer = setInterval(() => { logPage.value = 0; fetchLogs(); }, 2000);
            }
            if (page === 'charts')     { nextTick(_initCharts); }
            if (prevPage === 'charts') { _destroyCharts(); }
        });

        // 自動更新開關
        watch(logAutoScroll, (auto) => {
            clearInterval(_logTimer);
            _logTimer = null;
            if (auto && currentPage.value === 'logs') {
                logPage.value = 0;
                fetchLogs();
                _logTimer = setInterval(() => { logPage.value = 0; fetchLogs(); }, 2000);
            }
        });

        // 篩選條件變更 → 回到第 0 頁重新取
        watch(logFilter, () => {
            logPage.value = 0;
            fetchLogs();
        });

        // 連線狀態變化時，若在圖表頁則重新初始化或銷毀圖表
        watch(() => state.connected, (connected) => {
            if (currentPage.value !== 'charts') return;
            if (connected) { nextTick(_initCharts); } else { _destroyCharts(); }
        });

        onMounted(connectWs);
        onUnmounted(() => {
            clearTimeout(wsRetryTimer);
            if (ws) ws.close();
            clearInterval(_logTimer);
            _destroyCharts();
        });

        return {
            state, ipInput,
            currentPage, sidebarCollapsed, navItems,
            navigate, toggleSidebar,
            fmt, barPct, cardClass, barClass,
            connecting,
            doConnect, doDisconnect, toggleCh,
            networkInfo,
            nominalInputs, nominalFeedback, batchNominal, batchStatus,
            setNominal, setAllNominal,
            logEntries, logTotal, logPage, logPageSize, logFilter,
            logAutoScroll, logTotalPages,
            fetchLogs, clearLogs, setPageSize,
            toggleLogAuto, logPrevPage, logNextPage,
            chartWindow, chartPaused, chartHistoryMode, chartChannelVisible,
            activeModules, channelsByModule,
            setChartWindow, toggleChartPause, toggleChannelVisible, jumpToLive,
            doCloseTab, isShuttingDown,
        };
    }
}).mount('#app');
