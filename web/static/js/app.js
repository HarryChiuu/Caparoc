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

        // -- 通道設定 --
        const nominalInputs = reactive({});
        const nominalFeedback = reactive({});
        const batchNominal = ref('');
        const batchStatus = reactive({ ok: false, msg: '' });

        async function setNominal(chId) {
            const val = parseFloat(nominalInputs[chId]);
            if (isNaN(val) || val < 0.5 || val > 25.5) {
                nominalFeedback[chId] = { ok: false, msg: '請輸入 0.5–25.5' };
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
            const val = parseFloat(batchNominal.value);
            if (isNaN(val) || val < 0.5 || val > 25.5) {
                batchStatus.ok = false;
                batchStatus.msg = '請輸入 0.5–25.5';
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
            nominalInputs, nominalFeedback, batchNominal, batchStatus,
            setNominal, setAllNominal,
        };
    }
}).mount('#app');
