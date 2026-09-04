const { createApp, reactive, ref, computed, watch, onMounted, onUnmounted, nextTick } = Vue;

createApp({
    setup() {

        // -- 頁面導覽 --
        const currentPage = ref('dashboard');
        const sidebarCollapsed = ref(false);

        // 順序＝現場的操作流程：先看狀態（1-2）、再調參數（3）、
        // 出問題才查（4-5）、最後才是連線與初次架設（6-7）。
        const navItems = [
            { page: 'dashboard', icon: '📊', label: '通道控制' },
            { page: 'charts', icon: '📈', label: '設備監控' },
            { page: 'channel-settings', icon: '⚡', label: '通道設定' },
            { page: 'system-status', icon: '🖧', label: '系統狀態' },
            { page: 'logs', icon: '📋', label: '系統日誌' },
            { page: 'connection', icon: '🔌', label: '連線設定' },
            { page: 'ip-config', icon: '⚙️', label: '初始設定' },
        ];

        function navigate(page) {
            currentPage.value = page;
            if (window.innerWidth < 640) sidebarCollapsed.value = true;
        }

        function toggleSidebar() {
            sidebarCollapsed.value = !sidebarCollapsed.value;
        }

        // -- 主題（夜間 / 白天）--
        // 預設白天模式——現場多在明亮環境操作。使用者切換過就以 localStorage 為準。
        // ⚠️ 這個值必須與 index.html <head> 裡開頁前腳本的預設一致，
        //    否則首屏會先套一種主題、載入 app.js 後再跳成另一種（閃爍）。
        const DEFAULT_THEME = 'light';
        const theme = ref(DEFAULT_THEME);
        try {
            theme.value = localStorage.getItem('caparoc_theme') || DEFAULT_THEME;
        } catch (_) { /* 私密模式等情境讀不到，維持預設 */ }

        function applyTheme(t) {
            document.documentElement.setAttribute('data-theme', t);
        }
        applyTheme(theme.value);

        function toggleTheme() {
            theme.value = theme.value === 'dark' ? 'light' : 'dark';
            applyTheme(theme.value);
            try { localStorage.setItem('caparoc_theme', theme.value); } catch (_) { }
            // 圖表色是建立時寫死的，切主題要重建才會套用新色
            if (currentPage.value === 'charts' && (state.connected || wasEverConnected.value)) {
                nextTick(_initCharts);
            }
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
        // 設備識別與全域設定：從 localStorage 恢復
        const deviceInfo = ref((() => {
            try {
                const s = localStorage.getItem('caparoc_device_info');
                return s ? JSON.parse(s) : null;
            } catch (_) { return null; }
        })());
        // 原廠 Web 介面資訊（HTTP/80，與 CIP 獨立）：從 localStorage 恢復
        const webifInfo = ref((() => {
            try {
                const s = localStorage.getItem('caparoc_webif_info');
                return s ? JSON.parse(s) : null;
            } catch (_) { return null; }
        })());
        let ws = null;
        let wsRetryTimer = null;
        let _wasConnected = false;  // 連線狀態變化偵測
        const wasEverConnected = ref(false);  // 曾成功連線過（斷線後保留資料供查看）

        // 圖表監控 - 狀態 & 歷史緩衝（宣告於 applyStatus 之前）
        const chartWindow = ref(30);
        const chartPaused = ref(false);
        const chartHistoryMode = ref(false);
        const chartChannelVisible = reactive({});
        const _chartHistory = { timestamps: [], voltage: [], totalCurrent: [], channels: {} };
        const CHART_MAX_PTS = 1800;
        const CHART_COLORS = ['#3b82f6', '#10b981', '#f97316', '#8b5cf6', '#ef4444', '#06b6d4', '#84cc16', '#ec4899'];
        let _globalChart = null;
        const _moduleCharts = {};

        function fmt(v) {
            return (v != null) ? Number(v).toFixed(1) : '—';
        }

        function barPct(ch) {
            if (!ch.nominal_amps) return 0;
            return Math.min(100, (ch.current_amps / ch.nominal_amps) * 100);
        }

        function cardClass(ch) {
            if (ch.overload || ch.short_circuit || ch.hardware_fault || ch.total_shutdown) return 'fault';
            if (ch.warn_80) return 'warn';
            if (ch.on) return 'on';
            return 'off';
        }

        function barClass(ch) {
            if (ch.overload || ch.short_circuit || ch.total_shutdown) return 'bar-fault';
            if (ch.warn_80) return 'bar-warn';
            return 'bar-ok';
        }

        function applyStatus(data) {
            const isConnected = data.connected ?? false;

            if (isConnected) {
                // 已連線：完整更新所有狀態
                wasEverConnected.value = true;
                state.device_ip = data.device_ip ?? '';
                if (!ipInput.value && state.device_ip) { ipInput.value = state.device_ip; }
                state.error = '';
                state.voltage = data.voltage ?? 0;
                state.total_current = data.total_current ?? 0;
                state.module_count = data.module_count ?? 0;
                state.channels = data.channels ?? [];
                // 初始化新通道的可見性（預設全部顯示）
                for (const ch of state.channels) {
                    if (chartChannelVisible[ch.id] === undefined) chartChannelVisible[ch.id] = true;
                }
                state.undervoltage = data.undervoltage ?? false;
                state.overvoltage = data.overvoltage ?? false;
                state.system_error = data.system_error ?? false;
            } else {
                // 斷線：只更新 error，其餘資料保留供查看（UI 凍結）
                state.error = data.error ?? '';
            }

            state.connected = isConnected;

            // 連線狀態變化偵測（斷→通時重新讀取設備資訊）
            if (!_wasConnected && state.connected) {
                fetchNetworkInfo();
                fetchDeviceInfo();
                // 標籤以設備序號綁定，連上才知道要查哪一台（故不放 onMounted）
                fetchLabels();
            }
            _wasConnected = state.connected;

            // 圖表歷史累積（只在已連線且未暫停時）
            if (state.connected && !chartPaused.value) {
                const t = new Date();
                const lbl = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}:${String(t.getSeconds()).padStart(2, '0')}`;
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
            if (ws) { try { ws.close(); } catch (_) { } }
            ws = new WebSocket(`ws://${location.host}/ws/status`);
            ws.onmessage = (e) => applyStatus(JSON.parse(e.data));
            ws.onclose = () => { wsRetryTimer = setTimeout(connectWs, 3000); };
            ws.onerror = () => { ws.close(); };
        }

        async function doConnect() {
            if (connecting.value) return;   // 防止重複點擊
            connecting.value = true;
            state.error = '';
            const ip = ipInput.value.trim();
            const qs = ip ? `?ip=${encodeURIComponent(ip)}` : '';
            try {
                const r = await fetch(`/api/connect${qs}`, { method: 'POST' });
                const body = await r.json().catch(() => ({}));
                if (r.ok) {
                    // 後端連線成功時順手回傳更新後的清單，省一次 round trip
                    if (body.recent) recentIps.value = body.recent;
                } else {
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

        // -- 最近連線過的設備（來源是後端 config.json，不是 localStorage）--
        // 放伺服器端的理由：現場換一台筆電、換瀏覽器或清快取都不該讓清單消失。
        const recentIps = ref([]);
        const ipPickerOpen = ref(false);

        async function fetchRecent() {
            try {
                const r = await fetch('/api/connect/recent');
                if (!r.ok) return;
                const body = await r.json();
                recentIps.value = body.recent ?? [];
                // 未連線時預填最近一次的位址，開頁即可直接按「連線」
                if (!ipInput.value && recentIps.value.length)
                    ipInput.value = recentIps.value[0].ip;
            } catch (_) { }
        }

        function pickRecent(ip) {
            ipInput.value = ip;
            ipPickerOpen.value = false;
            // 刻意不自動連線：已連線時換 IP 需先斷線，靜靜幫使用者做會很意外
        }

        async function forgetRecent(ip) {
            try {
                const r = await fetch('/api/connect/recent/' + encodeURIComponent(ip),
                                      { method: 'DELETE' });
                const body = await r.json().catch(() => ({}));
                if (r.ok) recentIps.value = body.recent ?? [];
            } catch (_) { }
        }

        // ISO 時間 → 「剛剛 / 12 分鐘前 / 今天 14:22 / 昨天 14:22 / 8/28」
        // 後端寫的是不帶時區的本地時間，瀏覽器會以本地時區解讀，兩邊同一台機器故一致。
        function relTime(iso) {
            if (!iso) return '';
            const t = new Date(iso);
            if (isNaN(t.getTime())) return '';
            const now = new Date();
            const mins = Math.floor((now - t) / 60000);
            if (mins < 1) return '剛剛';
            if (mins < 60) return mins + ' 分鐘前';
            const hhmm = String(t.getHours()).padStart(2, '0') + ':'
                       + String(t.getMinutes()).padStart(2, '0');
            const days = Math.round(
                (new Date(now.getFullYear(), now.getMonth(), now.getDate())
                 - new Date(t.getFullYear(), t.getMonth(), t.getDate())) / 86400000);
            if (days <= 0) return '今天 ' + hhmm;
            if (days === 1) return '昨天 ' + hhmm;
            return (t.getMonth() + 1) + '/' + t.getDate();
        }

        // 點選單以外的任何地方就收起（下拉是自繪的，沒有原生 select 的行為）
        function _closeIpPicker(e) {
            if (!e.target.closest || !e.target.closest('.ip-picker'))
                ipPickerOpen.value = false;
        }

        const networkInfoRefreshing = ref(false);

        // 全域旗標：任一 CIP on-demand 讀取進行中時為 true，防止前端並發觸發
        let _cipReadInFlight = false;

        async function fetchNetworkInfo() {
            try {
                const r = await fetch('/api/device/network');
                if (r.ok) {
                    const data = await r.json();
                    // 只在有至少一個有效欄位時才更新，避免以全 null 覆蓋快取
                    if (data.ip != null || data.mac != null) {
                        networkInfo.value = data;
                        try { localStorage.setItem('caparoc_network_info', JSON.stringify(data)); } catch (_) { }
                        return true;
                    }
                }
            } catch (_) { }
            return false;
        }

        async function refreshNetworkInfo() {
            if (!state.connected || networkInfoRefreshing.value || _cipReadInFlight) return;
            _cipReadInFlight = true;
            networkInfoRefreshing.value = true;
            const prev = networkInfo.value;
            networkInfo.value = null;          // 顯示「讀取中...」
            const ok = await fetchNetworkInfo();
            if (!ok) networkInfo.value = prev; // 失敗時恢復舊值
            networkInfoRefreshing.value = false;
            _cipReadInFlight = false;
        }

        const deviceInfoRefreshing = ref(false);

        async function fetchDeviceInfo() {
            try {
                const r = await fetch('/api/device/info');
                if (r.ok) {
                    const data = await r.json();
                    // 只在有至少一個有效識別欄位時才更新，避免以全 null 覆蓋快取
                    const hasData = data.identity && Object.values(data.identity).some(v => v != null);
                    if (hasData) {
                        deviceInfo.value = data;
                        try { localStorage.setItem('caparoc_device_info', JSON.stringify(data)); } catch (_) { }
                        return true;
                    }
                }
            } catch (_) { }
            return false;
        }

        async function refreshDeviceInfo() {
            if (!state.connected || deviceInfoRefreshing.value || _cipReadInFlight) return;
            _cipReadInFlight = true;
            deviceInfoRefreshing.value = true;
            const prev = deviceInfo.value;  // 備份目前值
            deviceInfo.value = null;        // 清空，讓頁面顯示「讀取中...」
            const ok = await fetchDeviceInfo();
            if (!ok) deviceInfo.value = prev;  // 失敗時恢復，不讓頁面一片空白
            deviceInfoRefreshing.value = false;
            _cipReadInFlight = false;
        }

        // ---- 原廠 Web 介面（webif）----------------------------------------
        // 走 HTTP/80，與 CIP 完全獨立：刻意不看 state.connected、不佔 _cipReadInFlight。
        // CIP 斷線時仍可讀，故障事件記憶在那個時候最有用。
        const webifInfoRefreshing = ref(false);
        // 讀過一次但設備無回應（用來區分「還沒讀」與「讀了沒有」）
        const webifUnavailable = ref(false);
        // 燈號說明視窗開關（表格只畫燈點，顏色語意集中在此視窗）
        const showLedHelp = ref(false);

        async function fetchWebifInfo() {
            try {
                const r = await fetch('/api/device/webif');
                if (r.ok) {
                    const data = await r.json();
                    if (data.available) {
                        webifInfo.value = data;
                        webifUnavailable.value = false;
                        try { localStorage.setItem('caparoc_webif_info', JSON.stringify(data)); } catch (_) { }
                        return true;
                    }
                }
            } catch (_) { }
            webifUnavailable.value = true;
            return false;
        }

        async function refreshWebifInfo() {
            if (webifInfoRefreshing.value) return;
            webifInfoRefreshing.value = true;
            await fetchWebifInfo();   // 失敗時保留舊值（快取），由 webifUnavailable 標示
            webifInfoRefreshing.value = false;
        }

        // webif 的模組故障記憶／通道錯誤是否有任何一筆（決定故障面板顯示「無紀錄」與否）
        const webifHasFaults = computed(() => {
            const mods = webifInfo.value?.modules || [];
            return mods.some(m => (m.fault_events || []).length > 0
                || (m.channels_data || []).some(c => c.errorid || c.errorcounter));
        });

        // ==================== IP 設定頁 ====================
        // 本區塊的 state 與函式刻意集中在一起，日後若要抽成 composable 可整段搬走。

        const ipCurrent = ref(null);            // 設備目前網路設定（0xF5 Attr1/3/5）
        const ipCurrentRefreshing = ref(false);
        const ipScanBusy = ref(false);
        const ipScanResult = ref(null);         // { devices, via, broadcasts }
        const ipScanError = ref('');
        const ipIfaces = ref([]);               // 本機網卡清單
        const ipIfaceSel = ref('');             // 選定網卡的 IP；'' = 全部網卡

        // -- 失聯設備救援（設備切成 DHCP 但網段沒有 DHCP server）--
        const macBusy = ref(false);
        const macList = ref(null);              // [{mac, count}]
        const macError = ref('');
        const rescueMac = ref('');
        const rescueIp = ref('');
        const rescueSubnet = ref('255.255.255.0');
        const rescueGateway = ref('');
        const rescueBusy = ref(false);
        const rescueFeedback = ref({ ok: false, msg: '' });
        const dhcpCancelBusy = ref(false);   // 中斷鈕本身送出中，避免連點
        const ipMode = ref('static');           // 'static' | 'dhcp'
        const ipForm = reactive({ ip: '', subnet: '255.255.255.0', gateway: '' });
        const ipApplyBusy = ref(false);
        const ipApplyFeedback = ref({ ok: false, msg: '' });
        const ipConfirmOpen = ref(false);

        async function fetchIpCurrent() {
            try {
                const r = await fetch('/api/ipconfig/current');
                if (!r.ok) return false;
                const data = await r.json();
                ipCurrent.value = data;
                // 表單預填設備現值，讓使用者只需改動想改的欄位
                if (data.ip) ipForm.ip = data.ip;
                if (data.subnet) ipForm.subnet = data.subnet;
                if (data.gateway && data.gateway !== '0.0.0.0') ipForm.gateway = data.gateway;
                // 讓「設定方式」單選反映設備目前實際模式，避免畫面自相矛盾
                // （資訊表顯示 DHCP，下方 radio 卻停在靜態 IP）
                if (data.config_control === 2) ipMode.value = 'dhcp';
                else if (data.config_control === 0) ipMode.value = 'static';
                return true;
            } catch (_) { }
            return false;
        }

        async function refreshIpCurrent() {
            // 併入全域 CIP 讀取旗標，避免與 refreshNetworkInfo/refreshDeviceInfo 並發
            if (!state.connected || ipCurrentRefreshing.value || _cipReadInFlight) return;
            _cipReadInFlight = true;
            ipCurrentRefreshing.value = true;
            const prev = ipCurrent.value;
            ipCurrent.value = null;
            const ok = await fetchIpCurrent();
            if (!ok) ipCurrent.value = prev;   // 失敗時恢復舊值，不留空白畫面
            ipCurrentRefreshing.value = false;
            _cipReadInFlight = false;
        }

        async function fetchIfaces() {
            try {
                const r = await fetch('/api/ipconfig/interfaces');
                if (!r.ok) return;
                const body = await r.json();
                ipIfaces.value = body.interfaces ?? [];
            } catch (_) { }
        }

        async function scanDevices() {
            if (ipScanBusy.value) return;
            ipScanBusy.value = true;
            ipScanError.value = '';
            try {
                const q = ipIfaceSel.value
                    ? ('?iface_ip=' + encodeURIComponent(ipIfaceSel.value)) : '';
                const r = await fetch('/api/ipconfig/discover' + q, { method: 'POST' });
                const body = await r.json().catch(() => ({}));
                if (r.ok) {
                    ipScanResult.value = body;
                } else {
                    ipScanError.value = body.detail ?? ('掃描失敗 (HTTP ' + r.status + ')');
                }
            } catch (e) {
                ipScanError.value = '無法連線至伺服器';
            } finally {
                ipScanBusy.value = false;
            }
        }

        async function cancelDhcpOp() {
            // 只中止伺服器端的背景作業；前端的 fetch 會在對方回應後自然結束，
            // 不需要（也不該）在這裡 abort() ——那樣伺服器執行緒仍會占著 UDP/67 直到逾時。
            if (dhcpCancelBusy.value) return;
            dhcpCancelBusy.value = true;
            try {
                await fetch('/api/ipconfig/dhcp-cancel', { method: 'POST' });
            } catch (_) { }
            finally {
                dhcpCancelBusy.value = false;
            }
        }

        async function detectMac() {
            if (macBusy.value) return;
            if (!ipIfaceSel.value) {
                macError.value = '請先在上方選擇設備所在的網卡（不能用「全部網卡」）';
                return;
            }
            macBusy.value = true;
            macError.value = '';
            macList.value = null;
            try {
                const r = await fetch('/api/ipconfig/detect-mac?iface_ip='
                    + encodeURIComponent(ipIfaceSel.value) + '&timeout=90',
                    { method: 'POST' });
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    macError.value = body.detail ?? ('偵測失敗 (HTTP ' + r.status + ')');
                    return;
                }
                macList.value = body.macs ?? [];
                if (body.cancelled) macError.value = '已手動中斷';
                if (macList.value.length === 1) rescueMac.value = macList.value[0].mac;
            } catch (e) {
                macError.value = '無法連線至伺服器';
            } finally {
                macBusy.value = false;
            }
        }

        async function rescueDevice() {
            if (rescueBusy.value) return;
            if (!rescueMac.value || !_isValidIpStr(rescueIp.value)) {
                rescueFeedback.value = { ok: false, msg: '請選擇 MAC 並填入合法的指派 IP' };
                return;
            }
            rescueBusy.value = true;
            rescueFeedback.value = { ok: true, msg: '等待設備送出 DHCP 請求…最長 2 分鐘（可重插設備網路線強制重試）' };
            try {
                const r = await fetch('/api/ipconfig/assign', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        iface_ip: ipIfaceSel.value,
                        mac: rescueMac.value,
                        ip: rescueIp.value,
                        subnet: rescueSubnet.value || '255.255.255.0',
                        gateway: rescueGateway.value || '',
                        timeout: 120,
                    }),
                });
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    rescueFeedback.value = { ok: false, msg: body.detail ?? ('救援失敗 (HTTP ' + r.status + ')') };
                    return;
                }
                if (body.static_set && body.connected) {
                    rescueFeedback.value = { ok: true, msg: '✓ 設備已取得 ' + body.ip + '，已固化為靜態 IP 並重新連線' };
                    refreshIpCurrent();
                } else if (body.online) {
                    rescueFeedback.value = { ok: false, msg: '設備已取得 ' + body.ip + ' 並上線，但固化靜態或重連未完成，請至「連線設定」手動連線' };
                } else {
                    rescueFeedback.value = { ok: false, msg: '已送出 DHCP ACK，但設備未在時限內上線，請稍後用掃描確認' };
                }
            } catch (e) {
                rescueFeedback.value = { ok: false, msg: '無法連線至伺服器' };
            } finally {
                rescueBusy.value = false;
            }
        }

        function useFoundIp(ip) {
            ipForm.ip = ip;
            ipMode.value = 'static';
        }

        async function connectToFound(ip) {
            ipInput.value = ip;
            await doConnect();
            if (state.connected) refreshIpCurrent();
        }

        // IPv4 字串 → 32 位元整數；格式不合回傳 null
        function _ip2int(str) {
            const parts = String(str).split('.');
            if (parts.length !== 4) return null;
            let v = 0;
            for (const x of parts) {
                if (!/^\d{1,3}$/.test(x)) return null;
                const n = Number(x);
                if (n < 0 || n > 255) return null;
                v = (v * 256) + n;
            }
            return v;
        }

        function _isValidIpStr(str) {
            return _ip2int(str) !== null;
        }

        // 新 IP 是否與設備目前網段相同；不同只警告不擋（比照 CLI same_subnet 的語意）
        const ipSubnetWarning = computed(() => {
            const cur = ipCurrent.value;
            if (!cur || !cur.ip || !ipForm.ip || ipMode.value !== 'static') return '';
            const mask = ipForm.subnet || cur.subnet;
            if (!mask) return '';
            const a = _ip2int(ipForm.ip), b = _ip2int(cur.ip), m = _ip2int(mask);
            if (a === null || b === null || m === null) return '';
            if (((a & m) >>> 0) !== ((b & m) >>> 0))
                return '⚠ 新 IP 與設備目前網段（' + cur.ip + ' / ' + mask + '）不同，套用後可能無法從本機連線';
            return '';
        });

        function openIpConfirm() {
            ipApplyFeedback.value = { ok: false, msg: '' };
            if (ipMode.value === 'static') {
                if (!_isValidIpStr(ipForm.ip)) {
                    ipApplyFeedback.value = { ok: false, msg: 'IP 格式不正確（需為 x.x.x.x）' };
                    return;
                }
                if (!_isValidIpStr(ipForm.subnet)) {
                    ipApplyFeedback.value = { ok: false, msg: '子網路遮罩格式不正確' };
                    return;
                }
                if (ipForm.gateway && !_isValidIpStr(ipForm.gateway)) {
                    ipApplyFeedback.value = { ok: false, msg: '預設閘道格式不正確' };
                    return;
                }
            }
            ipConfirmOpen.value = true;
        }

        async function applyIpChange() {
            ipConfirmOpen.value = false;
            if (ipApplyBusy.value) return;
            ipApplyBusy.value = true;
            const isStatic = ipMode.value === 'static';
            ipApplyFeedback.value = {
                ok: true,
                msg: isStatic ? '寫入中…設備將重啟網路，請稍候（最長 30 秒）' : '切換中…',
            };
            try {
                const url = isStatic ? '/api/ipconfig/static' : '/api/ipconfig/dhcp';
                const opts = isStatic
                    ? {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            ip: ipForm.ip, subnet: ipForm.subnet, gateway: ipForm.gateway,
                        }),
                    }
                    : { method: 'POST' };
                const r = await fetch(url, opts);
                const body = await r.json().catch(() => ({}));
                if (!r.ok) {
                    ipApplyFeedback.value = { ok: false, msg: body.detail ?? ('失敗 (HTTP ' + r.status + ')') };
                    return;
                }
                if (isStatic) {
                    if (body.reconnected) {
                        ipApplyFeedback.value = { ok: true, msg: '✓ 已設定為 ' + body.new_ip + ' 並自動重新連線' };
                        refreshIpCurrent();
                    } else if (body.online) {
                        ipApplyFeedback.value = { ok: false, msg: 'IP 已改為 ' + body.new_ip + '，設備已上線但自動重連失敗，請至「連線設定」手動連線' };
                    } else {
                        ipApplyFeedback.value = { ok: false, msg: 'IP 已寫入 ' + body.new_ip + '，但 30 秒內未偵測到設備上線；請確認本機與新 IP 同網段後手動連線' };
                    }
                } else {
                    ipApplyFeedback.value = { ok: true, msg: body.note ?? '已切換為 DHCP' };
                    ipCurrent.value = null;
                }
            } catch (e) {
                ipApplyFeedback.value = { ok: false, msg: '無法連線至伺服器' };
            } finally {
                ipApplyBusy.value = false;
            }
        }

        // 通道開關：進行中旗標（防止連續點擊）與失敗提示（短暫顯示於卡片上）
        const channelToggling = reactive({});
        const channelToggleError = reactive({});

        async function toggleCh(ch) {
            if (channelToggling[ch.id]) return;  // 上一個請求還沒回來，避免重複送出
            channelToggling[ch.id] = true;
            const action = ch.on ? 'off' : 'on';
            try {
                const r = await fetch(`/api/channel/${ch.id}/${action}`, { method: 'POST' });
                if (!r.ok) throw new Error(String(r.status));
            } catch (e) {
                channelToggleError[ch.id] = true;
                setTimeout(() => { channelToggleError[ch.id] = false; }, 2500);
            } finally {
                channelToggling[ch.id] = false;
            }
        }

        // -- 可調上下限（來源：config/config.json，經 GET /api/config/limits）--
        // 額定電流範圍原本寫死在 index.html 三處 input 與 app.js 三處驗證，
        // 改設定檔要同步六個地方。現在只有這一份，模板與驗證都引用它。
        const limits = reactive({ nominalMin: 1, nominalMax: 20 });

        async function fetchLimits() {
            try {
                const r = await fetch('/api/config/limits');
                if (!r.ok) return;                       // 取不到就沿用內建預設
                const d = await r.json();
                if (d?.nominal_current) {
                    limits.nominalMin = d.nominal_current.min;
                    limits.nominalMax = d.nominal_current.max;
                }
            } catch (e) { /* 設定值非關鍵路徑，失敗沿用預設即可 */ }
        }

        // ── 通道自訂標籤（4.3.6）─────────────────────────────
        // 標籤刻意**不放進每秒的 WebSocket payload**：那是靜態文字，每天推 8.6 萬次
        // 沒有意義，而且後端為了填 label 得每秒多讀一次 CIP 取序號去搶 _cip_lock。
        // 改由獨立端點取一次，前端在渲染時與 state.channels 合併。
        const channelLabels = reactive({});     // {chId: '主機電源'} — 已存檔的值
        const deviceLabel = ref('');
        const labelBusy = reactive({});         // {chId | '_device': true}
        const labelFeedback = reactive({});     // {chId | '_device': {ok, msg}}
        const LABEL_MAX_LEN = 32;               // 與 app_config.LABEL_MAX_LEN 一致

        // 編輯中的暫存值（{chId | '_device': '打到一半的字'}）。
        //
        // ⚠️ 這一層不能省。輸入框若直接綁 `:value="channelLabels[id]"`，那是**單向綁定**：
        // WebSocket 每秒推一次狀態 → state.channels 重新賦值 → v-for 重新算 →
        // :value 被拉回尚未存檔的舊值，使用者打的字**一秒內就被清掉**。
        // 改用 v-model 綁這份草稿，輸入框在編輯期間由前端自己作主，
        // 只有 focus（載入現值）與 blur（存檔後清除）兩個時點跟 channelLabels 同步。
        const labelDrafts = reactive({});

        function labelValue(slot) {
            return labelDrafts[slot] ?? (slot === '_device' ? deviceLabel.value
                                                            : (channelLabels[slot] ?? ''));
        }

        function onLabelFocus(slot) {
            labelDrafts[slot] = labelValue(slot);
        }

        // 狀態以輸入框內的小圖示呈現，不用文字訊息——名稱欄只有 190px，
        // 放不下「輸入框 + 文字」並排，擠成兩行會把整張表推長（實測回報）。
        // 完整訊息（尤其是錯誤原因）留在 title，hover 看得到。
        function labelStateIcon(slot) {
            const f = labelFeedback[slot];
            if (!f?.msg) return '';
            if (f.busy) return '⋯';
            return f.ok ? '✓' : '⚠';
        }

        function labelStateClass(slot) {
            const f = labelFeedback[slot];
            if (f?.busy) return 'busy';
            return f?.ok ? 'ok' : 'err';
        }

        function _applyLabels(d) {
            Object.keys(channelLabels).forEach(k => delete channelLabels[k]);
            Object.entries(d?.channels ?? {}).forEach(([k, v]) => { channelLabels[k] = v; });
            deviceLabel.value = d?.device_label ?? '';
        }

        async function fetchLabels() {
            try {
                const r = await fetch('/api/labels');
                if (!r.ok) return;              // 取不到就維持空白，不擋其他功能
                _applyLabels(await r.json());
            } catch (e) { /* 標籤非關鍵路徑 */ }
        }

        // 存檔沿用 setNominal() 的 busy + feedback 慣例（3 秒後自動清訊息）
        async function _postLabel(slot, url, text) {
            // 不再因 busy 就早退。輸入框原本綁 :disabled="labelBusy[...]"，
            // Vue 一停用聚焦中的輸入框，瀏覽器就會補一次 blur → 再次進到這裡 →
            // 撞上早退後 feedback 永遠停在「儲存中…」（實測回報的卡住現象）。
            // 現在輸入框不再被停用，這裡也就不需要早退；同一格重複送出由
            // saveLabel() 的「值沒變就不打 API」擋掉。
            labelBusy[slot] = true;
            labelFeedback[slot] = { ok: true, busy: true, msg: '儲存中…' };
            try {
                const r = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text }),
                });
                const body = await r.json().catch(() => ({}));
                if (r.ok) {
                    _applyLabels(body);         // 以後端回傳為準（已 trim／截斷）
                    labelFeedback[slot] = { ok: true, msg: '✓ 已儲存' };
                    setTimeout(() => { labelFeedback[slot] = { ok: false, msg: '' }; }, 3000);
                } else {
                    labelFeedback[slot] = { ok: false, msg: body.detail ?? '儲存失敗' };
                }
            } catch (e) {
                labelFeedback[slot] = { ok: false, msg: '無法連線' };
            } finally {
                labelBusy[slot] = false;
            }
        }

        // @blur 觸發。值沒變就不打 API——點進點出不該產生寫檔。
        //
        // 無論存不存檔都要清掉草稿：草稿留著的話，輸入框會一直顯示前端的暫存值，
        // 之後 fetchLabels() 從後端拿到的新值就蓋不上去了（labelValue 草稿優先）。
        async function saveLabel(chId, text) {
            const val = (text ?? '').trim().slice(0, LABEL_MAX_LEN);
            const unchanged = val === (channelLabels[chId] ?? '');
            if (!unchanged) {
                await _postLabel(chId, `/api/labels/channel/${chId}`, val);
            }
            delete labelDrafts[chId];
        }

        async function saveDeviceLabel(text) {
            const val = (text ?? '').trim().slice(0, LABEL_MAX_LEN);
            const unchanged = val === deviceLabel.value;
            if (!unchanged) {
                await _postLabel('_device', '/api/labels/device', val);
            }
            delete labelDrafts['_device'];
        }

        // 模組型號標示的可調範圍；型號讀不到時回全域 limits（軟性降級）
        function modRange(mod) {
            const ch = channelsByModule.value[mod]?.[0];
            return (ch?.nominal_min != null && ch?.nominal_max != null)
                ? { min: ch.nominal_min, max: ch.nominal_max }
                : { min: limits.nominalMin, max: limits.nominalMax };
        }

        // 額定電流輸入驗證：合法回 null，否則回錯誤訊息字串。
        // 傳入 mod 時用該模組型號範圍（較嚴），否則用全域範圍。
        // 空白不是「輸入錯誤」——使用者只是還沒填。
        //
        // 這一項刻意**不併進 validateNominal()**：那支有三個呼叫端（單通道、全域批次、
        // 模組批次），改動它的契約就有三處迴歸風險。改為在各呼叫端前置檢查，
        // validateNominal 一字不動，超出範圍的行為逐位元相同。
        //
        // 為什麼要分開：紅色在本專案是失敗訊號（設定失敗／無法連線／後端 detail），
        // 花在「你還沒填」會稀釋它——工控介面裡真正的紅字代表對現場斷路器的 CIP
        // 寫入失敗了。而且「新值」欄的 placeholder 顯示的正是目前額定電流，
        // 看起來就像已經填好了，使用者按下「設定」收到紅字只會困惑。
        function isBlankNominal(raw) {
            return raw == null || String(raw).trim() === '';
        }

        function validateNominal(raw, mod) {
            const { min, max } = mod != null
                ? modRange(mod)
                : { min: limits.nominalMin, max: limits.nominalMax };
            const val = Math.round(parseFloat(raw));
            if (isNaN(val) || val < min || val > max) {
                return `請輸入 ${min}–${max} A`;
            }
            return null;
        }

        // -- 通道設定 --
        const nominalInputs = reactive({});
        const nominalFeedback = reactive({});
        const nominalBusy = reactive({});      // {chId: true} 單通道設定進行中
        const batchNominal = ref('');
        const batchStatus = reactive({ ok: false, hint: false, msg: '' });

        // batchStatus 是**持續存在**的 reactive 物件（模板直接綁欄位，不能整個取代，
        // 否則斷掉反應性）。正因為不取代，未指定的欄位會沿用上一次的值——
        // 若某個錯誤路徑忘了清 hint，紅字就會被上一次的提示態染成灰色。
        // 統一走這支 setter，未傳的欄位一律回預設，六個寫入點都不必各自記得。
        function setBatchStatus({ ok = false, hint = false, msg = '' }) {
            batchStatus.ok = ok;
            batchStatus.hint = hint;
            batchStatus.msg = msg;
        }
        const batchBusy = ref(false);          // 全域批次進行中

        async function setNominal(chId) {
            if (nominalBusy[chId]) return;
            // 沒填新值就按「設定」：給中性提示，不給紅字。
            // 同一列還有「名稱」欄（blur 自動存檔、沒有按鈕），使用者設定完名稱後
            // 很自然會來按這顆按鈕，不該因此收到一則關於額定電流的錯誤。
            if (isBlankNominal(nominalInputs[chId])) {
                nominalFeedback[chId] = { ok: false, hint: true, msg: '請先輸入新的額定電流' };
                setTimeout(() => { nominalFeedback[chId] = { ok: false, msg: '' }; }, 3000);
                return;
            }
            const val = Math.round(parseFloat(nominalInputs[chId]));
            const err = validateNominal(nominalInputs[chId],
                                        state.channels.find(c => c.id === chId)?.module);
            if (err) {
                nominalFeedback[chId] = { ok: false, msg: err };
                return;
            }
            // 後端寫入後最長等 3 秒驗證，期間給明確進度提示
            nominalBusy[chId] = true;
            nominalFeedback[chId] = { ok: true, msg: '設定中…' };
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
            } finally {
                nominalBusy[chId] = false;
            }
        }

        // 批次設定：一次 POST 全部通道，後端寫完再統一驗證（總計約 3 秒）。
        // 先前是前端 for 迴圈逐一 await，8 通道最壞要 24 秒，
        // 期間每個請求都搶後端的 _cip_lock，WebSocket 推送會被排隊卡住。
        async function postNominalBatch(channelIds, val) {
            const r = await fetch('/api/channels/nominal', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ channel_ids: channelIds, current_amps: val }),
            });
            const body = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(body.detail ?? `設定失敗 (HTTP ${r.status})`);
            return body;
        }

        function batchResultMsg(body) {
            const parts = [
                body.fail === 0 ? `✓ ${body.ok} 個通道設定完成`
                                : `${body.ok} 成功，${body.fail} 失敗`,
            ];
            if (body.skipped?.length) parts.push(`${body.skipped.length} 個通道不支援遠端設定，已略過`);
            return parts.join('；');
        }

        async function setAllNominal() {
            if (batchBusy.value) return;
            if (isBlankNominal(batchNominal.value)) {
                setBatchStatus({ hint: true, msg: '請先輸入要套用到全部通道的額定電流' });
                setTimeout(() => setBatchStatus({ msg: '' }), 4000);
                return;
            }
            const val = Math.round(parseFloat(batchNominal.value));
            const errAll = validateNominal(batchNominal.value);
            if (errAll) {
                setBatchStatus({ msg: errAll });
                return;
            }
            // 各模組型號範圍可能不同（例如 E4 1-4A 與 E2 2-10A），
            // 全域套用時要逐模組檢查，否則會對超出範圍的模組白跑一趟 CIP 寫入。
            const outOfRange = [...new Set(
                state.channels
                    .filter(ch => !isModNominalReadOnly(ch.module))
                    .filter(ch => {
                        const { min, max } = modRange(ch.module);
                        return val < min || val > max;
                    })
                    .map(ch => ch.module)
            )].sort((a, b) => a - b);
            if (outOfRange.length) {
                const detail = outOfRange
                    .map(m => { const r = modRange(m); return `M${m} ${r.min}-${r.max}A`; })
                    .join('、');
                setBatchStatus({ msg: `${val}A 超出這些模組的型號範圍：${detail}` });
                return;
            }
            // 前端先濾掉鎖定模組（後端也會擋），但要讓使用者知道少做了哪些，
            // 否則「套用至全部通道」看起來全部成功、實際漏掉旋鈕未轉 RC 的模組。
            const lockedMods = [...new Set(
                state.channels.filter(ch => isModNominalReadOnly(ch.module)).map(ch => ch.module)
            )].sort((a, b) => a - b);
            const ids = state.channels
                .filter(ch => !isModNominalReadOnly(ch.module))
                .map(ch => ch.id);
            if (!ids.length) {
                setBatchStatus({ msg: '沒有可遠端設定的通道——請先將旋鈕轉到 RC（見模組說明）' });
                return;
            }
            batchBusy.value = true;
            setBatchStatus({ ok: true, msg: `設定中… (${ids.length} 個通道)` });
            try {
                const body = await postNominalBatch(ids, val);
                setBatchStatus({
                    ok: body.fail === 0,
                    msg: batchResultMsg(body)
                        + (lockedMods.length
                            ? `；模組 ${lockedMods.join('、')} 旋鈕未轉 RC，未套用`
                            : ''),
                });
                batchNominal.value = '';
            } catch (e) {
                setBatchStatus({ msg: e.message || '設定失敗' });
            } finally {
                batchBusy.value = false;
                setTimeout(() => setBatchStatus({ msg: '' }), 4000);
            }
        }

        // Per-module 批次設定
        const batchNominalByMod = reactive({});
        const batchStatusByMod = reactive({});
        const batchBusyByMod = reactive({});

        // 判斷模組的 nominal 是否為 read-only（從硬體探測結果）
        function isModNominalReadOnly(mod) {
            return channelsByModule.value[mod]?.[0]?.nominal_readonly ?? false;
        }

        // 旋鈕型模組（2 通道）判定。
        // 協定沒有「模組是否為旋鈕型」的欄位，也讀不到旋鈕位置（含 RC），
        // 因此以通道數推定：2 通道 = E2 旋鈕型。用途僅為顯示 RC 說明入口。
        // 固定額定型號沒有旋鈕，先排除。
        function isModRotary(mod) {
            return modFixedNominal(mod) == null
                && (channelsByModule.value[mod]?.length ?? 0) === 2;
        }

        // 固定額定型號的安培數（如 E1 12-24DC/16A 回 16）；可調型回 null。
        // 反灰的兩種原因由此區分：不可調 vs 旋鈕未轉 RC。
        function modFixedNominal(mod) {
            return channelsByModule.value[mod]?.[0]?.nominal_fixed ?? null;
        }

        // 手動設定說明視窗開關；helpMod 記錄由哪個模組開啟，
        // 讓 Modal 依模組型別顯示對應說明（固定型 vs 旋鈕型）
        const showNominalHelp = ref(false);
        const helpMod = ref(null);

        function openNominalHelp(mod) {
            helpMod.value = mod;
            showNominalHelp.value = true;
        }

        // 重新探測額定電流可寫性（使用者轉動 RC 旋鈕後需手動觸發）
        const reprobeBusy = ref(false);
        const reprobeStatus = reactive({ ok: true, msg: '' });

        async function reprobeNominal() {
            if (reprobeBusy.value) return;
            reprobeBusy.value = true;
            reprobeStatus.ok = true;
            reprobeStatus.msg = '偵測中…';
            try {
                const r = await fetch('/api/device/reprobe-nominal', { method: 'POST' });
                const body = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(body.detail ?? `偵測失敗 (HTTP ${r.status})`);
                const ro = body.readonly_modules ?? [];
                reprobeStatus.ok = true;
                reprobeStatus.msg = ro.length
                    ? `完成：模組 ${ro.join('、')} 仍無法遠端設定`
                    : '完成：所有模組都可遠端設定';
            } catch (e) {
                reprobeStatus.ok = false;
                reprobeStatus.msg = e.message || '偵測失敗';
            } finally {
                reprobeBusy.value = false;
                setTimeout(() => { reprobeStatus.msg = ''; }, 6000);
            }
        }

        async function setModuleNominal(mod) {
            if (batchBusyByMod[mod]) return;
            if (isBlankNominal(batchNominalByMod[mod])) {
                batchStatusByMod[mod] = { ok: false, hint: true, msg: '請先輸入本模組要套用的額定電流' };
                setTimeout(() => { batchStatusByMod[mod] = { ok: false, msg: '' }; }, 4000);
                return;
            }
            const val = Math.round(parseFloat(batchNominalByMod[mod]));
            const errMod = validateNominal(batchNominalByMod[mod], mod);
            if (errMod) {
                batchStatusByMod[mod] = { ok: false, msg: errMod };
                return;
            }
            const ids = (channelsByModule.value[mod] || []).map(ch => ch.id);
            if (!ids.length) {
                batchStatusByMod[mod] = { ok: false, msg: '本模組無可設定通道' };
                return;
            }
            batchBusyByMod[mod] = true;
            batchStatusByMod[mod] = { ok: true, msg: `設定中… (${ids.length} 個通道)` };
            try {
                const body = await postNominalBatch(ids, val);
                batchStatusByMod[mod] = { ok: body.fail === 0, msg: batchResultMsg(body) };
                batchNominalByMod[mod] = '';
            } catch (e) {
                batchStatusByMod[mod] = { ok: false, msg: e.message || '設定失敗' };
            } finally {
                batchBusyByMod[mod] = false;
                setTimeout(() => { batchStatusByMod[mod] = { ok: false, msg: '' }; }, 4000);
            }
        }


        // -- 系統日誌 --
        const logEntries = ref([]);
        const logTotal = ref(0);
        const logPage = ref(0);
        const logPageSize = ref(20);
        const logFilter = ref('all');
        const logAutoScroll = ref(true);
        let _logTimer = null;

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
                    logTotal.value = data.total;
                    logEntries.value = data.entries;
                    // 頁碼超出範圍時自動修正
                    const maxPage = Math.max(0, logTotalPages.value - 1);
                    if (logPage.value > maxPage) logPage.value = maxPage;
                }
            } catch (_) { }
        }

        async function clearLogs() {
            await fetch('/api/logs/clear', { method: 'POST' });
            logEntries.value = [];
            logTotal.value = 0;
            logPage.value = 0;
        }

        function setPageSize(n) {
            logPageSize.value = n;
            logPage.value = 0;
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
                labels: _chartHistory.timestamps.slice(-n),
                voltage: _chartHistory.voltage.slice(-n),
                totalCurrent: _chartHistory.totalCurrent.slice(-n),
            };
        }

        // 圖表的格線/刻度/圖例色隨主題切換（曲線本身的語意色兩種主題都適用）
        function _chartTheme() {
            const light = document.documentElement.dataset.theme === 'light';
            return {
                grid: light ? 'rgba(0,0,0,0.10)' : 'rgba(255,255,255,0.05)',
                tick: light ? '#414d64' : '#9aaac4',
                legend: light ? '#1b2432' : '#c5d0e6',
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
                    _chartHistory.timestamps = hist.timestamps || [];
                    _chartHistory.voltage = hist.voltage || [];
                    _chartHistory.totalCurrent = hist.total_current || [];
                    _chartHistory.channels = {};
                    for (const [id, vals] of Object.entries(hist.channels || {}))
                        _chartHistory.channels[parseInt(id)] = vals;
                }
            } catch (_) { }

            // 確認仍在圖表頁（fetch 期間可能已離頁）
            if (currentPage.value !== 'charts') return;
            const gcEl = document.getElementById('globalChart');
            if (!gcEl) return;

            const zoomCfg = {
                pan: {
                    enabled: true, mode: 'x',
                    onPanComplete: () => { chartHistoryMode.value = true; }
                },
                zoom: {
                    wheel: { enabled: true }, mode: 'x',
                    onZoomComplete: () => { chartHistoryMode.value = true; }
                },
            };
            const slice = _getChartSlice();
            const t = _chartTheme();

            _globalChart = new Chart(gcEl.getContext('2d'), {
                type: 'line',
                data: {
                    labels: slice.labels,
                    datasets: [
                        {
                            label: '電壓 (V)', data: slice.voltage, yAxisID: 'yV',
                            borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.08)',
                            tension: 0.3, pointRadius: 0, borderWidth: 2
                        },
                        {
                            label: '總電流 (A)', data: slice.totalCurrent, yAxisID: 'yA',
                            borderColor: '#f97316', backgroundColor: 'rgba(249,115,22,0.08)',
                            tension: 0.3, pointRadius: 0, borderWidth: 2
                        },
                    ],
                },
                options: {
                    animation: false, responsive: true, maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    scales: {
                        yV: {
                            type: 'linear', position: 'left',
                            title: { display: true, text: '電壓 (V)', color: '#3b82f6' },
                            grid: { color: t.grid },
                            ticks: { color: '#3b82f6', callback: v => Number(v).toFixed(2) }
                        },
                        yA: {
                            type: 'linear', position: 'right', min: 0,
                            title: { display: true, text: '電流 (A)', color: '#f97316' },
                            grid: { drawOnChartArea: false }, ticks: { color: '#f97316' }
                        },
                        x: {
                            grid: { color: t.grid },
                            ticks: { maxTicksLimit: 6, color: t.tick, maxRotation: 0 }
                        },
                    },
                    plugins: {
                        legend: { labels: { color: t.legend, usePointStyle: true } },
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
                    data: (_chartHistory.channels[ch.id] || []).slice(-n),
                    borderColor: CHART_COLORS[i % CHART_COLORS.length],
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
                            y: {
                                min: 0,
                                title: { display: true, text: '電流 (A)', color: t.tick },
                                grid: { color: t.grid }, ticks: { color: t.tick }
                            },
                            x: {
                                grid: { color: t.grid },
                                ticks: { maxTicksLimit: 6, color: t.tick, maxRotation: 0 }
                            },
                        },
                        plugins: {
                            legend: { labels: { color: t.legend, usePointStyle: true } },
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
            _globalChart.data.labels = slice.labels;
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
            if (ws) { try { ws.close(); } catch (_) { } }
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
            if (page === 'charts') { nextTick(_initCharts); }
            if (prevPage === 'charts') { _destroyCharts(); }
            // 進入系統狀態頁且已連線 → 自動重新讀取最新設定
            // webif 走 HTTP/80 與 CIP 無關，未連線也讀（此時故障事件記憶最有價值）
            if (page === 'system-status') {
                if (state.connected) refreshDeviceInfo();
                refreshWebifInfo();
            }
            // 進入連線設定頁：網卡列舉供頁內掃描用（不需連線）；已連線則刷新網路資訊
            if (page === 'connection') {
                if (!ipIfaces.value.length) fetchIfaces();
                if (state.connected) refreshNetworkInfo();
            }
            // 進入 IP 設定頁且已連線 → 自動讀取目前網路設定
            if (page === 'ip-config') {
                if (!ipIfaces.value.length) fetchIfaces();   // 網卡列舉不需連線
                if (state.connected) refreshIpCurrent();
            }
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

        // 連線狀態變化時，若在圖表頁且重新連線則重新初始化圖表
        // 斷線時不銷毀圖表——保留最後畫面讓使用者查看歷史資料
        watch(() => state.connected, (connected) => {
            if (currentPage.value !== 'charts') return;
            if (connected) { nextTick(_initCharts); }
        });

        onMounted(() => {
            fetchLimits();      // 設定值與連線無關，不等 WebSocket
            fetchRecent();      // 同上：未連線時更需要這份清單
            connectWs();
            document.addEventListener('click', _closeIpPicker);
        });
        onUnmounted(() => {
            clearTimeout(wsRetryTimer);
            if (ws) ws.close();
            clearInterval(_logTimer);
            document.removeEventListener('click', _closeIpPicker);
            _destroyCharts();
        });

        return {
            state, ipInput, wasEverConnected,
            currentPage, sidebarCollapsed, navItems,
            navigate, toggleSidebar,
            theme, toggleTheme,
            fmt, barPct, cardClass, barClass,
            connecting,
            doConnect, doDisconnect, toggleCh, channelToggling, channelToggleError,
            recentIps, ipPickerOpen, pickRecent, forgetRecent, relTime,
            networkInfo, deviceInfo, deviceInfoRefreshing, networkInfoRefreshing,
            refreshDeviceInfo, refreshNetworkInfo,
            webifInfo, webifInfoRefreshing, webifUnavailable, webifHasFaults, refreshWebifInfo,
            showLedHelp,
            limits,
            nominalInputs, nominalFeedback, nominalBusy, batchNominal, batchStatus, batchBusy,
            setNominal, setAllNominal,
            channelLabels, deviceLabel, labelBusy, labelFeedback, LABEL_MAX_LEN,
            labelDrafts, labelValue, onLabelFocus, saveLabel, saveDeviceLabel,
            labelStateIcon, labelStateClass,
            batchNominalByMod, batchStatusByMod, batchBusyByMod,
            setModuleNominal, isModNominalReadOnly, isModRotary, modRange, modFixedNominal,
            showNominalHelp, helpMod, openNominalHelp,
            reprobeNominal, reprobeBusy, reprobeStatus,
            logEntries, logTotal, logPage, logPageSize, logFilter,
            logAutoScroll, logTotalPages,
            fetchLogs, clearLogs, setPageSize,
            toggleLogAuto, logPrevPage, logNextPage,
            chartWindow, chartPaused, chartHistoryMode, chartChannelVisible,
            activeModules, channelsByModule,
            setChartWindow, toggleChartPause, toggleChannelVisible, jumpToLive,
            doCloseTab, isShuttingDown,
            // IP 設定頁
            ipCurrent, ipCurrentRefreshing, ipScanBusy, ipScanResult, ipScanError,
            ipIfaces, ipIfaceSel, fetchIfaces,
            macBusy, macList, macError, rescueMac, rescueIp,
            rescueSubnet, rescueGateway, rescueBusy, rescueFeedback,
            dhcpCancelBusy, cancelDhcpOp,
            detectMac, rescueDevice,
            ipMode, ipForm, ipApplyBusy, ipApplyFeedback, ipConfirmOpen,
            ipSubnetWarning,
            refreshIpCurrent, scanDevices, useFoundIp, connectToFound,
            openIpConfirm, applyIpChange,
        };
    }
}).mount('#app');
