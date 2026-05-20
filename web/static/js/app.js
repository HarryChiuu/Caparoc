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
        let ws = null;
        let wsRetryTimer = null;

        // 圖表監控 - 狀態 & 歷史緩衝（宣告於 applyStatus 之前）
        const chartWindow   = ref(60);
        const chartPaused   = ref(false);
        const _chartHistory = { timestamps: [], voltage: [], totalCurrent: [], channels: {} };
        const CHART_MAX_PTS = 120;
        const CHART_COLORS  = ['#3b82f6','#10b981','#f97316','#8b5cf6','#ef4444','#06b6d4','#84cc16','#ec4899'];
        let   _globalChart  = null;
        let   _channelChart = null;

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
            state.undervoltage  = data.undervoltage ?? false;
            state.overvoltage   = data.overvoltage ?? false;
            state.system_error  = data.system_error ?? false;
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
                if (currentPage.value === 'charts' && _globalChart && _channelChart) _updateCharts();
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

        // -- 圖表監控函式 --
        function _getChartSlice() {
            const n = chartWindow.value;
            const sortedIds = Object.keys(_chartHistory.channels).map(Number).sort((a, b) => a - b);
            return {
                labels:       _chartHistory.timestamps.slice(-n),
                voltage:      _chartHistory.voltage.slice(-n),
                totalCurrent: _chartHistory.totalCurrent.slice(-n),
                channelIds:   sortedIds,
                channelData:  Object.fromEntries(sortedIds.map(id => [id, (_chartHistory.channels[id] || []).slice(-n)])),
            };
        }

        function _destroyCharts() {
            if (_globalChart)  { _globalChart.destroy();  _globalChart  = null; }
            if (_channelChart) { _channelChart.destroy(); _channelChart = null; }
        }

        function _initCharts() {
            _destroyCharts();
            const slice = _getChartSlice();
            const gcEl = document.getElementById('globalChart');
            const ccEl = document.getElementById('channelChart');
            if (!gcEl || !ccEl) return;
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
                              grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#3b82f6' } },
                        yA: { type: 'linear', position: 'right', min: 0,
                              title: { display: true, text: '電流 (A)', color: '#f97316' },
                              grid: { drawOnChartArea: false }, ticks: { color: '#f97316' } },
                        x:  { grid: { color: 'rgba(255,255,255,0.05)' },
                              ticks: { maxTicksLimit: 6, color: '#9aaac4', maxRotation: 0 } },
                    },
                    plugins: { legend: { labels: { color: '#c5d0e6', usePointStyle: true } } },
                },
            });
            _channelChart = new Chart(ccEl.getContext('2d'), {
                type: 'line',
                data: {
                    labels: slice.labels,
                    datasets: slice.channelIds.map((id, i) => ({
                        label: `CH${id}`, data: slice.channelData[id] || [],
                        borderColor: CHART_COLORS[i % CHART_COLORS.length],
                        backgroundColor: 'transparent', tension: 0.3, pointRadius: 0, borderWidth: 1.5,
                    })),
                },
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
                    plugins: { legend: { labels: { color: '#c5d0e6', usePointStyle: true } } },
                },
            });
        }

        function _updateCharts() {
            if (!_globalChart || !_channelChart) return;
            const slice = _getChartSlice();
            _globalChart.data.labels           = slice.labels;
            _globalChart.data.datasets[0].data = slice.voltage;
            _globalChart.data.datasets[1].data = slice.totalCurrent;
            _globalChart.update('none');
            slice.channelIds.forEach((id, i) => {
                const ds = _channelChart.data.datasets.find(d => d.label === `CH${id}`);
                if (ds) { ds.data = slice.channelData[id]; }
                else {
                    _channelChart.data.datasets.push({
                        label: `CH${id}`, data: slice.channelData[id],
                        borderColor: CHART_COLORS[i % CHART_COLORS.length],
                        backgroundColor: 'transparent', tension: 0.3, pointRadius: 0, borderWidth: 1.5,
                    });
                }
            });
            _channelChart.data.labels = slice.labels;
            _channelChart.update('none');
        }

        function setChartWindow(n) {
            chartWindow.value = n;
            if (_globalChart && _channelChart) _updateCharts();
        }

        function toggleChartPause() { chartPaused.value = !chartPaused.value; }

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
            nominalInputs, nominalFeedback, batchNominal, batchStatus,
            setNominal, setAllNominal,
            logEntries, logTotal, logPage, logPageSize, logFilter,
            logAutoScroll, logTotalPages,
            fetchLogs, clearLogs, setPageSize,
            toggleLogAuto, logPrevPage, logNextPage,
            chartWindow, chartPaused, setChartWindow, toggleChartPause,
        };
    }
}).mount('#app');
