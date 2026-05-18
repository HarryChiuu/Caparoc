const { createApp, reactive, ref, onMounted, onUnmounted } = Vue;

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

        const ipInput = ref('192.168.2.111');
        let ws = null;
        let wsRetryTimer = null;

        function fmt(v) {
            return (v != null) ? Number(v).toFixed(2) : '—';
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
            state.error         = state.connected ? '' : (data.error ?? '');
            state.voltage       = data.voltage ?? 0;
            state.total_current = data.total_current ?? 0;
            state.module_count  = data.module_count ?? 0;
            state.channels      = data.channels ?? [];
            state.undervoltage  = data.undervoltage ?? false;
            state.overvoltage   = data.overvoltage ?? false;
            state.system_error  = data.system_error ?? false;
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
            }
        }

        async function doDisconnect() {
            await fetch('/api/disconnect', { method: 'POST' });
        }

        async function toggleCh(ch) {
            const action = ch.on ? 'off' : 'on';
            await fetch(`/api/channel/${ch.id}/${action}`, { method: 'POST' });
        }

        onMounted(connectWs);
        onUnmounted(() => {
            clearTimeout(wsRetryTimer);
            if (ws) ws.close();
        });

        return {
            state, ipInput,
            currentPage, sidebarCollapsed, navItems,
            navigate, toggleSidebar,
            fmt, barPct, cardClass, barClass,
            doConnect, doDisconnect, toggleCh,
        };
    }
}).mount('#app');
