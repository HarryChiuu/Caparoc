"""
patch_423.py - Task 4.2.3 前端修改：
1. index.html：替換 logs placeholder → 完整日誌頁 UI
2. app.js：加入 log 狀態、fetch、分頁、watch
"""
import pathlib

ROOT = pathlib.Path(__file__).parent

# ─── 1. index.html ──────────────────────────────────────────────────────────
html_path = ROOT / "web" / "templates" / "index.html"
html = html_path.read_text(encoding="utf-8")

OLD_LOGS = """                <!-- 系統日誌 -->
                <template v-if="currentPage === 'logs'">
                    <section class="panel">
                        <h2>系統日誌</h2>
                        <div class="placeholder">
                            <div class="placeholder-icon">📋</div>
                            <div class="placeholder-title">開發中</div>
                            <div class="placeholder-desc">後端日誌查看（4.2.3 實作）</div>
                        </div>
                    </section>
                </template>"""

NEW_LOGS = """                <!-- 系統日誌 -->
                <template v-if="currentPage === 'logs'">
                    <section class="panel">
                        <!-- 標題列 + 工具列 -->
                        <div class="log-header">
                            <h2>系統日誌</h2>
                            <div class="log-toolbar">
                                <select v-model="logFilter" class="log-select">
                                    <option value="all">全部等級</option>
                                    <option value="warn">WARNING+</option>
                                    <option value="error">ERROR</option>
                                </select>
                                <div class="log-pagesize">
                                    <button :class="['btn', 'btn-sm', logPageSize === 10 ? '' : 'btn-ghost']"
                                            @click="setPageSize(10)">10</button>
                                    <button :class="['btn', 'btn-sm', logPageSize === 20 ? '' : 'btn-ghost']"
                                            @click="setPageSize(20)">20</button>
                                </div>
                                <button :class="['btn', 'btn-sm', logAutoScroll ? '' : 'btn-ghost']"
                                        @click="toggleLogAuto"
                                        :title="logAutoScroll ? '點擊暫停自動更新' : '點擊開啟自動更新'">
                                    {{ logAutoScroll ? '⏸ 暫停' : '▶ 自動更新' }}
                                </button>
                                <button class="btn btn-sm btn-danger" @click="clearLogs">清空</button>
                            </div>
                        </div>

                        <!-- 日誌表格 -->
                        <div class="log-table-wrap">
                            <div class="log-empty" v-if="logEntries.length === 0">目前無日誌記錄</div>
                            <table class="log-table" v-else>
                                <colgroup>
                                    <col class="col-time" />
                                    <col class="col-level" />
                                    <col />
                                </colgroup>
                                <thead>
                                    <tr>
                                        <th>時間</th>
                                        <th>等級</th>
                                        <th>訊息</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr v-for="e in logEntries" :key="e.id"
                                        :class="'log-row log-row-' + e.level.toLowerCase()">
                                        <td class="log-time">{{ e.time }}</td>
                                        <td>
                                            <span :class="'log-badge log-' + e.level.toLowerCase()">
                                                {{ e.level }}
                                            </span>
                                        </td>
                                        <td class="log-msg">{{ e.msg }}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>

                        <!-- 分頁列 -->
                        <div class="log-pagination">
                            <span class="log-total">共 {{ logTotal }} 筆</span>
                            <div class="log-pager" v-if="logTotalPages > 1">
                                <button class="btn btn-sm btn-ghost"
                                        @click="logPrevPage" :disabled="logPage === 0">‹</button>
                                <span class="log-page-info">{{ logPage + 1 }} / {{ logTotalPages }}</span>
                                <button class="btn btn-sm btn-ghost"
                                        @click="logNextPage"
                                        :disabled="logPage >= logTotalPages - 1">›</button>
                            </div>
                        </div>
                    </section>
                </template>"""

assert OLD_LOGS in html, "找不到 logs placeholder，請確認 index.html 內容"
html = html.replace(OLD_LOGS, NEW_LOGS)

# 更新版本參數
html = html.replace('style.css?v=4.2.2b"', 'style.css?v=4.2.3"')
html = html.replace('app.js?v=4.2.2b"', 'app.js?v=4.2.3"')

html_path.write_text(html, encoding="utf-8")
print("✓ 更新 index.html")

# ─── 2. app.js ───────────────────────────────────────────────────────────────
js_path = ROOT / "web" / "static" / "js" / "app.js"
js = js_path.read_text(encoding="utf-8")

# 2a. 擴充 Vue imports（加入 watch, computed）
OLD_IMPORT = "const { createApp, reactive, ref, onMounted, onUnmounted } = Vue;"
NEW_IMPORT = "const { createApp, reactive, ref, computed, watch, onMounted, onUnmounted } = Vue;"
assert OLD_IMPORT in js, "找不到 Vue import 行"
js = js.replace(OLD_IMPORT, NEW_IMPORT)

# 2b. 在 onMounted(connectWs) 前插入 log 邏輯
LOG_BLOCK = """
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

        // 切換到 logs 頁時啟動輪詢；離開時停止
        watch(currentPage, (page) => {
            clearInterval(_logTimer);
            _logTimer = null;
            if (page === 'logs') {
                fetchLogs();
                if (logAutoScroll.value)
                    _logTimer = setInterval(fetchLogs, 2000);
            }
        });

        // 自動更新開關
        watch(logAutoScroll, (auto) => {
            clearInterval(_logTimer);
            _logTimer = null;
            if (auto && currentPage.value === 'logs') {
                logPage.value = 0;
                fetchLogs();
                _logTimer = setInterval(fetchLogs, 2000);
            }
        });

        // 篩選條件變更 → 回到第 0 頁重新取
        watch(logFilter, () => {
            logPage.value = 0;
            fetchLogs();
        });

"""

BEFORE_MOUNTED = "        onMounted(connectWs);"
assert BEFORE_MOUNTED in js, "找不到 onMounted(connectWs)"
js = js.replace(BEFORE_MOUNTED, LOG_BLOCK + BEFORE_MOUNTED)

# 2c. 更新 onUnmounted（加入清除 log timer）
OLD_UNMOUNTED = """        onUnmounted(() => {
            clearTimeout(wsRetryTimer);
            if (ws) ws.close();
        });"""
NEW_UNMOUNTED = """        onUnmounted(() => {
            clearTimeout(wsRetryTimer);
            if (ws) ws.close();
            clearInterval(_logTimer);
        });"""
assert OLD_UNMOUNTED in js, "找不到 onUnmounted"
js = js.replace(OLD_UNMOUNTED, NEW_UNMOUNTED)

# 2d. 更新 return 物件（加入 log 相關）
OLD_RETURN = """        return {
            state, ipInput,
            currentPage, sidebarCollapsed, navItems,
            navigate, toggleSidebar,
            fmt, barPct, cardClass, barClass,
            doConnect, doDisconnect, toggleCh,
            nominalInputs, nominalFeedback, batchNominal, batchStatus,
            setNominal, setAllNominal,
        };"""
NEW_RETURN = """        return {
            state, ipInput,
            currentPage, sidebarCollapsed, navItems,
            navigate, toggleSidebar,
            fmt, barPct, cardClass, barClass,
            doConnect, doDisconnect, toggleCh,
            nominalInputs, nominalFeedback, batchNominal, batchStatus,
            setNominal, setAllNominal,
            logEntries, logTotal, logPage, logPageSize, logFilter,
            logAutoScroll, logTotalPages,
            fetchLogs, clearLogs, setPageSize,
            toggleLogAuto, logPrevPage, logNextPage,
        };"""
assert OLD_RETURN in js, "找不到 return 物件"
js = js.replace(OLD_RETURN, NEW_RETURN)

js_path.write_text(js, encoding="utf-8")
print("✓ 更新 app.js")

# ─── 驗證 ────────────────────────────────────────────────────────────────────
html_new = html_path.read_text(encoding="utf-8")
js_new   = js_path.read_text(encoding="utf-8")
checks = [
    ("HTML: log-table-wrap",   "log-table-wrap" in html_new),
    ("HTML: log-badge",        "log-badge" in html_new),
    ("HTML: log-pagination",   "log-pagination" in html_new),
    ("HTML: v=4.2.3",          "v=4.2.3" in html_new),
    ("HTML: BOM",              html_new.encode("utf-8")[:3] != b"\xef\xbb\xbf"),
    ("JS: computed watch",     "watch, onMounted" in js_new),
    ("JS: logTotalPages",      "logTotalPages" in js_new),
    ("JS: fetchLogs",          "fetchLogs" in js_new),
    ("JS: _logTimer",          "_logTimer" in js_new),
]
all_ok = True
for name, ok in checks:
    print(f"  {'✓' if ok else '✗'} {name}")
    if not ok:
        all_ok = False

print("完成" if all_ok else "⚠ 有驗證失敗！")
