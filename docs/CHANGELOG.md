# Changelog

---

## [2026-08-27] `python web/app.py` 監聽埠可設定 + 自動避讓（fix/web-cip-concurrency）

- **根因**：`PORT` 寫死 8000，而 NVIDIA Overlay 會間歇性 `bind()` 0.0.0.0:8000（overlay/遊戲啟動時），造成 `python web/app.py` 偶發 `[Errno 10048] 一次只能用一個通訊端位址`
- **修正**：新增 `_resolve_port()`——預設改 8001（避開 NVIDIA Overlay），可用 `--port N` 或環境變數 `CAPAROC_PORT` 覆寫；選定埠若已被佔用，往上探 10 個埠取第一個可用的，並印出實際使用的埠讓瀏覽器開對 URL
- **範圍**：僅影響 `python web/app.py` 直接執行入口；`uvicorn web.app:app` 仍需自帶 `--port`
- TODO 4.3.1（config 合併）落地時可把此邏輯併入統一 config

---

## [2026-08-26] Web CIP 並發修正後續 refactor（fix/web-cip-concurrency，TODO 項目 1–5）

> 承接上一則的 `_cip_lock` 補齊工作，把複查時記錄在 `docs/TODO.md` 的 5 個後續項目一次做完。

### ⚡ 效能與使用體感

**批次設定額定電流：8 通道從最壞 24 秒縮短到約 3 秒（項目 1）**
- **根因**：`app.js` 的 `setAllNominal()`/`setModuleNominal()` 用 `for` 迴圈逐一 `await` 單通道 API，每次呼叫後端都要跑 `sleep(0.5)×6` 的驗證迴圈，8 通道最壞 24 秒；期間每個請求都搶 `_cip_lock`，WebSocket 推送被排隊卡住，而畫面上完全沒有進度提示
- **修正**：新增 `CaparocBackend.set_nominal_current_batch(targets)`——先把所有通道都寫入，最後才統一驗證，且驗證改用「單次 Input Assembly 讀取檢查全部通道」而非每通道各讀一次整份 assembly。8 通道的驗證讀取從 48 次降為最多 6 次
- 新增 `POST /api/channels/nominal`（body: `channel_ids` + `current_amps`），前端兩個批次按鈕改呼叫此端點；後端會自動略過探測判定為 read-only 的模組並回報 `skipped`
- **進度提示**：批次與單筆設定都加上進行中狀態（按鈕文字變「設定中…」、輸入框與按鈕停用、顯示「設定中… (N 個通道)」），完成後顯示成功/失敗/略過筆數

### 🛡️ 設備安全

**額定電流可寫性探測不再每次連線都改寫設備（項目 2）**
- **根因**：`_probe_nominal_writable()` 用「寫入 nominal±1 → 等 0.8 秒 → 讀回驗證 → 還原」判斷模組是否支援遠端設定，而 `connect()` 每次都會跑一遍。每個模組至少 0.8 秒，且**會短暫改變真實設備的額定電流**；若中途斷線或崩潰，設備會被留在 probe 值
- **修正 1（快取）**：探測結果以 Identity Object 序號為索引寫入 `config/nominal_probe_cache.json`（讀不到序號時退回 IP）。同一台設備只在「無快取紀錄」「模組數與快取不符」「明確要求重測」三種情況才重新探測，其餘連線完全不對設備寫入
- **修正 2（還原保證）**：只要送出過 probe 寫入，就在 `finally` 還原原值——包含判定 read-only 與中途例外的情況；還原失敗會記 `ERROR` log
- 新增 `POST /api/device/reprobe-nominal` 作為逃生口（更換模組但總數不變導致快取失準時使用）
- `config/nominal_probe_cache.json` 加入 `.gitignore`（屬本機設備狀態）

### 🧹 重構

**CIP 存取抽出共用方法，消除「新增呼叫點忘記上鎖」的風險類別（項目 5）**
- 新增 `_cip_get()` / `_cip_set()`：內建 `_cip_lock`，呼叫端不需要（也不應該）自行持鎖——正是上一則 `a1951c6` 要修的問題根源
- 新增 `_read_input_assembly()`：一次讀取涵蓋所有模組/通道，供批次驗證使用
- `get_network_info()` / `get_device_info()` 內重複的區域 `_rd()` 改為薄封裝；額定電流讀寫、探測、`_read_and_show_result` 全面改用共用方法
- **刻意保留原始寫法的兩處**：Config Assembly 回退路徑與 `set_channel()` 的寫入＋驗證，兩者的「讀取→修改→寫入」必須在同一次持鎖內完成才具原子性，改用各自獨立上鎖的 helper 反而會破壞語意（已加註解說明）

**合併重複的額定電流讀取方法（項目 3）**
- `_read_nominal_current_silent()` 與 `_verify_nominal_current()` 邏輯完全相同，只差 debug print，且後者是唯一還沒補 `_cip_lock` 的讀取路徑
- 合併為 `_read_nominal_current(module, channel, verbose=False)`（`driver` 參數移除，一律用 `self.driver`）；`caparoc_controller.py` 的 `verify` 指令改呼叫新方法

**修正 `_read_and_show_result()` 位址錯誤，並讓 web 路徑跳過（項目 4）**
- **根因**：用 `instance=0x101`（其他地方一致用 `self.input_instance`=0x65），偏移公式 `20+(channel-1)*2` 也跟 `get_channel_offset()` 對不上，讀出的是無意義的位元組；整段包在 try/except 裡只 `print()`，壞了沒人發現
- **修正**：位址改用 `input_instance` + `get_channel_offset()`，電流取 Byte 2 ÷ 10（與 `_read_current_status` 一致）；簽章加入 `module` 參數
- `set_channel()` 新增 `show_result=True` 參數，`web/app.py` 傳 `False`——web 使用者看不到終端機輸出，卻要為此多花 `sleep(0.5)` 與一次 CIP 往返，而 WebSocket 一秒內就會刷新真實狀態

### ⚠️ 待驗證

以上修正通過 mock driver 測試（模擬 2 模組 6 通道，驗證批次耗時、驗證讀取次數、快取命中時零寫入、probe 值還原、開關路徑電流讀取正確）與 `--demo` 模式的 API smoke test，**尚未接實機驗證**。

---

## [2026-08-26] Web CIP 並發鎖補齊 + 通道開關錯誤回報（fix/web-cip-concurrency，a1951c6, f721f30, 20db324）

### 🐛 Bug 修正

**寫入類 CIP 呼叫完全沒上鎖，與 WebSocket 讀取並發（a1951c6）**
- **根因**：`_cip_lock` 自 2026-05-25（b779752）加入後只覆蓋了讀取類方法（`_read_current_status`、`get_network_info`、`get_device_info`），但 web 使用者實際會觸發寫入的 `set_channel`、`set_nominal_current`（含其驗證讀取）與心跳執行緒完全沒有上鎖，會與 WebSocket 每秒一次的狀態讀取並發送出 `generic_message`，直接違反鎖原本要防的情境
- **心跳格外確定會踩到**：`_update_activity()` 定義後從未被任何地方呼叫，`last_activity_time` 永遠不會更新，閒置時間必然在 300 秒後觸發心跳，與 WebSocket 讀取並發——推測是「儀表板開著一段時間後偶爾莫名失聯」的成因之一
- **修正**：`set_channel()` 的寫入與驗證讀取、`_read_and_show_result()`、`set_nominal_current()` 的主要／備用寫入路徑、`_read_nominal_current_silent()`、`_heartbeat_worker()` 皆補上 `_cip_lock`；`set_channel()`／`set_nominal_current()`／`_read_current_status()` 成功路徑補上 `_update_activity()` 呼叫，讓心跳正確反映實際閒置時間
- **鎖順序**：已確認全程一致（`io_data_lock → _cip_lock`，僅 `set_channel` 一處巢狀，其餘皆各自獨立取得、不重入），不會死鎖
- **連帶修正**：`set_channel`／`set_nominal_current` 失敗分支補上 `self.logger.error()`——原本只有 `print()` 到終端機 stdout，web 的 log 面板完全看不到失敗原因

**通道開關失敗仍回報成功（f721f30）**
- **根因**：`web/app.py` 的 `channel_on`/`channel_off` 呼叫 `backend.set_channel()` 後沒有檢查回傳值，失敗時前端仍收到 `{"success": true}`；`set_nominal` 原本就有正確檢查
- **修正**：`channel_on`/`channel_off` 檢查回傳值，失敗時回傳 HTTP 500 而非謊報成功
- **連帶修正**：`_format_status(None)` 補上 `device_ip` 欄位，與其他分支一致；WebSocket 迴圈的 `except (WebSocketDisconnect, Exception): pass` 拆開為正常斷線（不記錄）與其他例外（記錄 warning），原本一律吞掉，真正的錯誤完全無跡可查

**前端 `toggleCh()` 完全不檢查回應，後端剛補的 500 形同虛設（20db324）**
- **根因**：後端 `channel_on`/`channel_off` 改回傳 500 後，前端 `toggleCh()` 仍然 `await fetch(...)` 就結束，不管成功失敗，使用者點了開關沒反應也看不出原因；隔壁 `setNominal()` 早就有完整的 `r.ok` 檢查與回饋機制，只有這裡漏掉
- **修正**：`toggleCh()` 補上 `r.ok` 檢查與 try/catch，失敗時設定 `channelToggleError[ch.id]`（2.5 秒後自動清除）；新增 `channelToggling` 旗標避免同一通道在請求進行中被連續點擊
- **連帶修正**：通道卡片新增 `.toggle-err` 短暫紅色邊框閃爍動畫，與 `.fault`（硬體故障，持續顯示）視覺區隔；按鈕在請求進行中停用

### ⚠️ 待驗證

以上鎖相關修正僅通過 `--demo` 模式的 in-process smoke test（demo 模式不會經過 `set_channel` 的真實 CIP 路徑），尚未接實機、開著儀表板同時操作驗證是否真的解決並發失聯問題。

---

## [2026-08-11] IP 設定功能完整實作（feature/ip-config-dhcp）

### ✨ 新功能

**CIP 0xF5 TCP/IP Interface Object 讀寫（`caparoc_backend.py`）**
- `set_device_ip()`：靜態 IP 設定（Attr5 + Attr3）；修正 CIP Little-Endian 字節序
- `set_device_dhcp()`：切換 DHCP 模式（Attr3=0x02）
- 修正：IP 使用 `connected=True`（此設備不支援 Unconnected Send 0x52）
- 修正：Attr5 寫入成功後標記 success，Attr3 連線中斷視為正常

**整合式 IP 設定工具（`src/caparoc_ip_config.py`，正式版）**
- `[1]` 讀取設備網路設定（IP/Subnet/GW/Mode）
- `[2]` 設定靜態 IP
- `[3]` 切換為 DHCP 模式
- `[4]` 從 DHCP 模式配置靜態 IP（新裝置初始設定）：mini DHCP server

**測試工具（`tests/`）**
- `test_ip_config.py`：互動式 IP 設定 + EtherNet/IP List Identity 自動探索 + ARP fallback
- `test_dcp_ip_config.py`：PROFINET DCP 工具 + DHCP Discover 監聽 + mini DHCP server [5]

### 🔍 關鍵技術發現（Wireshark 封包分析）

- **CIP IP 字節序**：TCP/IP Interface Object Attr5 以 Little-Endian UDINT 儲存 IP，需 `[::-1]` 反轉
- **Unconnected Send 不支援**：設備回應 `Service 0x52 not supported`，全部改用 `connected=True`
- **DHCP Offer 送出方式**：`socket.bind((server_ip, 67))` + 廣播到子網路廣播（如 .255），不能用 `255.255.255.255`，否則 Windows 可能走錯介面
- **DCP Set IP 無效**：此 CAPAROC 設備不接受 PROFINET DCP Set IP（PN-DCP Set Req 封包送出但設備忽略）
- **另一支程式（BootP-DHCP Tool）機制**：同時運行 DHCP server（port 67）+ CIP client；先 DHCP 分配已知 IP，再 CIP 固化靜態

---

## [2026-07-23] 多模組支援修彌——通道控制常打模組1、動態通道識別（21deea8, 757a427, af89bd8）

### 🐛 Bug 修正

**按下第 2/3 模組開關都只打到模組 1（21deea8）**
- **根因**：web/app.py 的 `channel_on/off` API 虫`get_module_and_channel()` 得到 `module` 後卻並未傳入下一層；`set_channel(channel, state)` 的 `byte_offset` 永遠寫死為 1（Module 1 對應的 Output byte）
- **修正**：`set_channel` 新增 `module` 參數，簽名改為 `set_channel(module, channel, state)`；`byte_offset = module`（Module N 對應 Output byte N）
- **連帶修彌**：`web/app.py` channel API 補傳 `module`；`caparoc_controller.py` CLI `on/off` 指令先呼叫 `get_module_and_channel` 再傳入

### ✨ 新功能

**2/4 通道混合模組自動識別——過濾空槽通道（757a427）**
- **動機**：安裝 2 通道 BREAKER 的模組，前端仍顯示 4 個卡片（CH3/CH4 無實體）
- **實測依據**：Input Assembly 中空槽的 `nominal_byte`（offset+1）= 0，實體通道必然 ≥ 1A
- **修正**：`_read_current_status` 內 `nominal_byte == 0` 跳過，`global_ch` 改為連續計數（對應實際安裝的通道，不再以等差公式假設模組全满）

**動態通道對應表，完整支援任意 2/4 通道混合模組（af89bd8）**
- **門題**：`get_module_and_channel()` 之前使用等差公式，假設每模組都有慣 4 通道；若 2 通道模組不在最後一個位置，開關 ID 會對應錯誤
- **修正**：新增 `self._ch_id_map: dict[int, tuple[int, int]]`，每次 `_read_current_status` 讀取硬體後即時更新；`get_module_and_channel()` 改為優先查表，fallback 才用公式
- **效果**：新安裝任意模組（2 或 4 通道）自動識別，無需手動設定

---

## [2026-05-25] Bug fixes — CIP 並發斷線、IP 倒序、拔線重連失敗（d726a88, 20e396f, b779752）

### 🐛 Bug 修正

**CIP 並發讀取導致頁面切換斷線（b779752）**
- **根因**：`generic_message()` 非 thread-safe；頁面切換時 `refreshNetworkInfo()` 與 WebSocket 推送同時呼叫，TCP 串流損壞
- **修正**：`caparoc_backend.py` 新增 `self._cip_lock = threading.Lock()`；`get_network_info()`、`get_device_info()`、`_read_current_status()` 全部序列化，共用同一把鎖
- **前端防護**：`app.js` 加入 `_cipReadInFlight` 全域旗標，阻止 `refreshNetworkInfo()` / `refreshDeviceInfo()` 並發觸發

**IP 位址顯示倒序（20e396f）**
- **根因**：CAPAROC CIP 0xF5 以 Little-Endian UDINT 儲存 IP；commit `1f5523e` 誤改為直接順讀 bytes，導致「111.50.168.192」
- **修正**：還原為 `struct.unpack_from('<I', buf, offset)[0]` → bit-shift 逐 octet 取出，正確還原點分十進位
- **教訓**：LE UDINT 絕不能直接順讀 bytes，必須先整數解碼再 bit-shift

**拔網路線後無法重連 + 圖表通道消失（d726a88）**
- **根因**：`_read_current_status()` 的 `try/finally` 讓通訊例外傳播至 WebSocket handler → handler while 迴圈中斷 → `_ws_client_count` 歸零 → 伺服器 shutdown 但 `is_connected` 永遠為 True，`connect()` 成為 no-op
- **修正**：加入 `except Exception` 捕獲通訊例外並 `return None`；`finally` 確保鎖釋放；WebSocket handler 收到 `None` 時自動呼叫 `backend.disconnect()`
- **連帶修正**：圖表通道消失問題由相同根因造成（從未收到 `{connected: false}`），一併解決

---

## [2026-05-22] Phase 4.2.8–4.2.9 頂部關閉按鈕 + 系統狀態頁

### 🔧 頂部列關閉按鈕（4.2.8）
- `topbar-right` 容器整合連線狀態列與「✕」關閉按鈕，以 `|` 分隔線視覺區隔
- `app.js`：新增 `doCloseTab()`（`window.close()`）
- 圖表監控電壓 Y 軸與 tooltip 改為顯示兩位小數（`toFixed(2)`）

### 🖧 系統狀態頁（4.2.9）
- 新增第 6 個導覽頁面「系統狀態」（`system-status`）
- **後端** `get_device_info()`：讀取 Identity Object (0x01:1, attr 1/2/3/4/6/7) + Class 0x0F inst 1-4 attr 1；各屬性獨立 `try/except`；全部 `connected=True` 持 `_cip_lock`
- **Web API** `GET /api/device/info`；未連線時回 HTTP 503
- **前端**：`deviceInfo` ref 使用 localStorage 快取（`caparoc_device_info`）；首次連線自動查詢；未連線時顯示快取並標記「（上次連線資訊）」
- 頁面兩個面板：「設備識別」（廠商/型號/產品代碼/修訂版本/序號/產品名稱）、「全域設定」（param_lock/ui_lock/啟動延遲/操作模式）

---

## [2026-05-21] Phase 4.2.6–4.2.7 圖表監控增強 + 設備網路資訊讀取

### 📈 圖表監控頁增強（4.2.6, a4750d8 + 3174cba）
- 後端新增 `_history_buffer = deque(maxlen=1800)`（30 分鐘）；`GET /api/history?minutes=N` endpoint
- 前端 `_initCharts()` 先 fetch `/api/history` 預填歷史資料，再銜接即時 WebSocket 串流
- 改為每模組一張 Chart.js 實例（`_moduleCharts` dict）；`v-for="mod in activeModules"` 動態生成
- 加入 chartjs-plugin-zoom + Hammer.js：滑鼠拖曳/滾輪縮放查看歷史；「▶ 即時」按鈕跳回即時模式
- Bug fix：`jumpToLive()` 中 `resetZoom()` 同步觸發 `onZoomComplete` 導致 `chartHistoryMode` 誤為 true，修正執行順序

### 🌐 設備網路資訊讀取（4.2.7）
- 後端新增 `get_network_info()`：TCP/IP Interface (CIP 0xF5, Inst 1, Attr 3) + Ethernet Link (0xF6, Attr 3)
  - IP、子網路遮罩、預設閘道（LE UDINT 格式）；MAC（6 bytes → `XX:XX:XX:XX:XX:XX`）
  - 各屬性獨立 `try/except`；全部 `connected=True` 持 `_cip_lock`
- Web API `GET /api/device/network`；未連線時回 HTTP 503
- 前端連線設定頁新增「設備網路資訊」面板，連線成功後自動查詢，含 ↻ 手動重新整理

---

## [2026-05-18] Phase 4.2.1–4.2.2 Web UI 導覽列骨架 + 通道設定頁

### 🏗️ 左側導覽列骨架（4.2.1）
- 重構 `index.html` / `app.js`：加入左側 sidebar（☰ 按鈕可收合）
- 5 個頁面（Vue `currentPage` ref 條件渲染）：儀表板 / 圖表監控 / 通道設定 / 系統日誌 / 連線設定
- 頂部固定列保留：連線狀態指示燈、設備 IP、連線/斷線按鈕
- `style.css` 新增 sidebar / layout / placeholder 樣式

### ⚡ 通道設定頁（4.2.2）
- `channel-settings` 頁：通道表格（編號、模組、目前額定電流、輸入欄位 1–20 A、設定按鈕）
- 「全部套用」按鈕：批次設定所有通道為相同額定電流
- 表格資料從 WebSocket 狀態自動填入目前值；設定成功 3 秒後自動清除提示訊息
- Bug fixes：API 回傳值檢查（`set_nominal_current()` false → HTTP 500）、float 輸入 `int(round(...))` 修正型別錯誤

---

## [2026-05-20] Phase 4.2.3–4.2.4 Web UI 系統日誌頁與多項 Bug 修正

### 🔧 系統日誌頁功能（4.2.3）
- 新增「系統日誌」分頁：等級篩選（ALL/WARN+/ERROR）、10/20 分頁、⏸/▶ 自動更新、清空
- 後端 `GET /api/logs`（分頁+篩選）、`POST /api/logs/clear`
- `_CaparocLogHandler` 攔截 `caparoc` logger → 記憶體 buffer；啟動時 `_preload_log_file()` 預載今日 .log
- log 顏色編碼：INFO 藍、SYSTEM 紫、WARNING 橙、ERROR 紅

### 🐛 Bug 修正（4.2.4）
- **連線按鈕重複觸發**：`doConnect()` 加 `connecting` 旗標，請求進行中按鈕 disabled 並顯示「連線中...」
- **日誌自動更新失效**：進入日誌頁與自動刷新皆重置至第 0 頁（最新），避免停在舊頁無法看到新紀錄
- **新增 🔄 手動重新整理按鈕**：log toolbar 加入，可在暫停自動更新時手動觸發 `fetchLogs()`
- **IP 輸入框預設值錯誤**：改從首次 WebSocket 資料初始化，不再寫死 `192.168.2.111`
- **設備失聯後無法重連**：WebSocket 偵測到讀取失敗時自動呼叫 `disconnect()`，清除 `_connected` 旗標使重連可行
- **log 寫入路徑依賴 CWD**：`logging_manager.py` 改以專案根目錄為基準，不再因啟動目錄不同而散落至 `web/logs/` 或 `src/logs/`
- **設備失聯無 log**：`_read_current_status` 失聯首次寫 `[CONN] WARNING`，恢復後寫 `[CONN] INFO`；heartbeat 失敗同樣記錄
- **app.js 版本快取**：`index.html` 引用改為 `?v=4.2.4`，破除瀏覽器快取

---

## [2026-05-15] Phase 3.6.1 - CaparocBackend 長駐連線管理（Web UI 前置）

### 🎯 動機
現有連線生命週期完全綁定在 `with CIPDriver(...) as driver:` 區塊內，Web 服務無法在請求之間保持連線長駐，必須先抽出可手動控制的連線 API。

### 🔧 實作內容

**`src/caparoc_backend.py` — 新增 5 個方法**

| 方法 | 類型 | 說明 |
|------|------|------|
| `is_connected` | property | `True` = driver 已開啟且連線旗標有效 |
| `connect()` | method | 開啟 CIPDriver → 驗證裝置 → sync output buffer → activate state → 啟動 heartbeat |
| `disconnect()` | method | 停監控 → 停心跳 → `_cleanup_driver()` → 清除 `channels_initialized` |
| `_cleanup_driver()` | 內部 | 關閉 CIPDriver（`__exit__`）、清空 `driver` / `_cip_driver` 參考 |
| `_sync_output_from_device()` | 內部 | 讀取 Input Assembly，重建 output_data buffer，**防止首次連線誤關正在運作的通道** |

**`__init__` 新增兩個屬性**
```python
self._cip_driver = None   # CIPDriver 實例（長駐模式用）
self._connected = False   # 連線狀態旗標
```

### 💡 設計說明
- `connect()` / `disconnect()` 只在 `CaparocBackend` 層實作；`CaparocController` 繼承後自動擁有，**CLI `run()` 保持不變，完全向後相容**
- `_sync_output_from_device()` 安全性：若讀取失敗則靜默略過，使用空白初始狀態（避免阻斷連線流程）
- Web 服務啟動時呼叫 `backend.connect()`，停止時呼叫 `backend.disconnect()`，中間所有請求共用同一 driver 實例

### 📊 統計
- **修改檔案**: `src/caparoc_backend.py`（+115 行，新增連線管理區塊 L217–L343）
- **工時**: 0.5 小時

---

## [2026-05-14] setting 選單重設計（職責分離與使用流程優化）

### 🎯 動機
舊版 `setting [1]`（不重連）與 `setting [2]`（重連）讓使用者容易混淆；
`setting [3]`（重設為預設）只恢復不重連，連線失敗時無法一鍵救回；
硬體 IP 寫入成功後詢問是否存檔，存在操作不一致風險。

### 🔧 實作內容

**`_handle_setting_connip` 全面改版（`src/caparoc_controller.py`）**

| 選項 | 新功能 | 舊功能 | 差異 |
|------|--------|--------|------|
| `[1]` | 變更並連線（輸入新 IP → 立即重連） | 變更 IP（不重連） | 舊 [1] 移除，合併為唯一變更入口 |
| `[2]` | 恢復預設值（config.json IP → 立即重連） | 變更 IP 並重連 | 改為「救回按鈕」，取回最後成功的 IP |
| `[3]` | 存為預設值（將目前連線 IP 寫入 config.json） | 重設為預設 IP（不重連） | 方向對調：主動存入而非被動恢復 |
| `[4]` | 硬體 IP 修改（CIP 0xF5，**成功後自動存檔**） | 同左，但寫入後詢問是否存檔 | 自動存檔，消除詢問環節 |

**`_handle_write_device_ip` 寫入成功後自動存檔（`src/caparoc_controller.py`）**
- 移除舊版 `_ask_save_default_ip` 詢問
- 寫入成功後直接呼叫 `_save_default_ip(new_ip)` 並顯示確認訊息

**help message 更新（`_show_help_message`）**
- `setting [1]`～`[4]` 說明同步更新為新邏輯

### 💡 設計意圖
- `[1]` 變更並連線：唯一的 IP 切換入口，確保 UI 最常用路徑最短
- `[2]` 恢復預設值：連線失敗時的「救回鍵」，切回最後一次成功記錄的 IP
- `[3]` 存為預設值：連線成功後主動確認「這個 IP 是對的」，風險最低
- `[4]` 硬體改 IP 後程式記憶必然同步，不允許遺漏存檔

---

## [2026-05-13] Phase 3.6.3 - 連線 IP 管理與設備設定重構

### 🎯 動機
連線失敗時無法直接修改連線 IP（只能重連或退出）；預設 IP 硬寫在程式碼中，無法持久化。

### 🔧 實作內容

**連線失敗選單擴充**
- 連線失敗時由原本 `[R]/[Q]` 改為 `[R]/[C]/[Q]`
- `[C]` 變更 IP：呼叫 `_configure_device_ip()` 輸入新 IP 後立即 reconnect

**預設 IP 持久化（`config/device_config.json`）**
- 新建 `config/device_config.json`：儲存 `default_ip`
- `config/device_config.json.example`：版本控管用範本（預設 `192.168.2.111`）
- `device_config.json` 加入 `.gitignore`，个人 IP 設定不入 git
- `__init__` 改從設定檔讀取預設 IP
- 確認 IP 時新增詢問是否存為預設（`_ask_save_default_ip()`）

**CLI 指令重構**
- `setting`：程式層連線 IP 管理
  - `[1]` 變更連線 IP（不重連）
  - `[2]` 變更連線 IP 並立即重連
  - `[3]` 重設為預設 IP
- `settingdeviceip`：設備硬體 IP 設定（原 `setting` 內容）
  - `[1]` 讀取設備網路設定（CIP Class 0xF5）
  - `[2]` 寫入新 IP 至設備（硬寫，目前尚需 PRONETA/Npcap）

**其他 CLI 修後**
- 勹除啟動時陰變的 IP 配置對話（連線成功後再詢問）
- `setting` / `settingdeviceip` 返回主選單後顯示提示文字
- 啟動說明文字更新，移除過時的「待實作功能」清單

**暫緩功能（PROFINET DCP）**
- 已探索 CIP Class 0xF5 寫入（Attr 5 無回應，設備不支援）
- PROFINET DCP 方案需 Npcap 驅動，影響程式可攜性，暫緩開發
- `tests/test_scapy_dcp.py`：已建診斷腳本保留

---

## [2026-04-02] Phase 3.5 - 前後端分離架構重構

### 🎯 動機
規劃 GUI 時發現，CLI 與 Web GUI 無法共用裝置邏輯（所有邏輯混在單一 `CaparocController` 類別中），必須先抽離純裝置邏輯層。

### 🔧 實作內容

**新建 `src/caparoc_backend.py`**

建立 `CaparocBackend` 類別，只含裝置操作邏輯，不含任何 CLI 互動。包含 27 個方法，約 1250 行：

| 分類 | 方法 |
|------|------|
| 通道偏移 | `get_channel_offset`, `get_total_channels`, `get_module_and_channel` |
| 連線管理 | `_activate_connection_state`, `_heartbeat_worker`, `_start_heartbeat`, `_stop_heartbeat`, `_update_activity` |
| Config | `get_config_channel_offset`, `update_config_parameter`, `set_nominal_current`, `_read_nominal_current_silent`, `_wait_for_config_processing`, `_verify_nominal_current` |
| 通道控制 | `set_channel`, `_read_and_show_result`, `read_channel_status` |
| 系統狀態 | `check_global_system_status`, `check_device_connection` |
| 監控 | `_monitor_worker`, `_read_current_status`, `_detect_changes`, `_show_monitor_status`, `_show_monitor_alerts`, `start_monitor`, `stop_monitor`, `show_monitor_info`, `show_status` |

**改造 `src/caparoc_controller.py`**

`CaparocController` 從獨立類別改為繼承 `CaparocBackend`：

```python
from caparoc_backend import CaparocBackend

class CaparocController(CaparocBackend):
    def __init__(self, device_ip="192.168.2.111"):
        super().__init__(device_ip)
        self.help_shown = False  # CLI 專用
```

CLI 專屬方法保留：`_show_help_message()`、`_configure_device_ip()`、`_validate_ip()`、`run()`

MRO 驗證：`CaparocController → CaparocBackend → object` ✅

### ⚠️ 過渡期已知問題
`caparoc_controller.py` 目前仍保留所有後端方法的完整複本（約 1500 行 shadow 方法），為過渡期安全備份。Phase 3.6.2 將執行清除，目標縮減至 ~250 行。

### 📊 統計
- **新增檔案**: `src/caparoc_backend.py`（~1250 行）
- **修改檔案**: `src/caparoc_controller.py`（繼承架構）、`src/logging_manager.py`（log 格式調整）
- **工時**: ~8 小時

---

## [2025-11-26] Phase 3 完成 - CLI 全功能實現 🎉

### 🎯 重大里程碑
Phase 3 開發階段圓滿完成，實現完整的 CLI 控制系統。

### ✅ 核心功能 (v3.2-v3.7)

1. **額定電流設定** - 互動式設定介面，支援 0.5-25.5A
2. **四通道開關控制** - 位元運算保留其他通道狀態
3. **狀態監控** - 全域系統狀態與通道詳細資訊
4. **即時監控** - 背景執行緒定期更新，支援靜默/顯示模式
5. **多模組支援** - 自動偵測 1-16 個模組，最多 64 通道
6. **連接管理** - IP 配置、心跳機制、自動重連

### 📊 統計
- **開發時間**: 2025-10-27 - 2025-11-26 (1 個月)
- **版本迭代**: v3.2 → v3.7
- **總工時**: ~20 小時
- **程式碼**: ~2100 行
- **文件**: 15+ 份

### 🚀 下一步：Phase 4 規劃

詳見 `docs/TODO.md`

**Phase 4 目標**: 進階功能與 GUI 開發  
**預估工時**: 35-46 小時

---

## [2025-11-13] 重構與文件完善 📚

### 🎯 重大重構
分離診斷工具，精簡主程式，完善文件體系

### 📝 新增文件
1. **MAIN_PROGRAM_FLOW.md**
   - 主程式完整流程說明
   - 6 大啟動步驟詳解
   - 核心功能流程（init, on/off, monitor）
   - Assembly 通訊機制
   - 多模組支援機制

2. **PROGRAM_FLOWCHART.md**
   - Mermaid 格式流程圖
   - 主程式啟動流程圖
   - 額定電流設定流程圖
   - 通道控制流程圖
   - 即時監控流程圖
   - 重連機制流程圖

3. **DIAGNOSTIC_TOOLS_GUIDE.md**
   - 5 個診斷工具完整說明
   - 常見診斷情境與解決方案
   - 輸出解讀指南
   - Assembly 資料格式解析

### 🗂️ 檔案整理
1. **分離診斷工具**
   - 創建 `tests/diagnostic_tools.py` (549 行)
   - 從主程式移除 7 個診斷方法
   - 主程式精簡：3299 → 2090 行 (-36.6%)

2. **檔案重組**
   - ✅ 刪除 `src/caparoc_controller_clean.py` (重複檔案)
   - ✅ 移動 `tests/caparoc_implicit_test.py` → `archive/`
   - ✅ 移動 `check_connection.py` → `tests/`
   - ✅ 保留 `src/caparoc_controller_old.py` (舊版備份)

### 🐛 Bug 修復
**修復幫助信息重複顯示問題**
- 新增 `help_shown` 標記避免重複顯示
- 添加 `h`/`help` 命令隨時查看幫助
- 重新連線時顯示簡短提示

### 🎨 改進項目
1. **主程式精簡**
   - 刪除重複的 `_verify_nominal_current` 方法
   - 移除診斷命令處理（scan, limits, diagnose, compare, testwrite）
   - 更新幫助信息，移除診斷命令說明

2. **文件體系**
   - 重新組織 docs/README.md
   - 新增快速導航分類
   - 添加文件關係圖
   - 更新文件更新規範

### 📂 當前專案結構
```
Caparoc5/
├── src/
│   ├── caparoc_controller.py      # 主程式 (2090 行) ✅
│   └── caparoc_controller_old.py  # 舊版備份
├── tests/
│   ├── diagnostic_tools.py        # 診斷工具 (549 行) 🆕
│   └── check_connection.py        # 連線檢查 🆕
├── archive/
│   └── caparoc_implicit_test.py   # 舊測試 🆕
└── docs/
    ├── MAIN_PROGRAM_FLOW.md       # 主程式流程 🆕
    ├── PROGRAM_FLOWCHART.md       # 流程圖 🆕
    ├── DIAGNOSTIC_TOOLS_GUIDE.md  # 診斷工具指南 🆕
    └── README.md                   # 文件索引（已更新）
```

### 📊 統計數據
- 主程式程式碼減少: 1209 行 (36.6%)
- 新增文件: 3 份
- 診斷工具獨立: 549 行
- Git commits: 3 個

---

## [2025-10-21 v4] 完整多通道獨立控制 ⭐

### 🎉 重大改進
實現**真正的多通道獨立控制**，解決照搬測試程式導致的問題。

### 🐛 修正的問題

#### 問題 1: 每次開啟都執行完整按鈕模擬 ✅ 已修正
**現象**: 每次 `on 1` 都要等 7-10 秒
**修正**: 額定電流只設定一次，之後快速開關 (<1秒)

#### 問題 2: 無法關閉已開啟的通道 ✅ 已修正
**現象**: `off 1` 無法關閉通道 1
**原因**: `get_channel_current()` 缺少 `module` 參數
**修正**: 所有方法統一加入 `module` 參數

#### 問題 3: 開啟其他通道會關閉已開啟的通道 ✅ 已修正
**現象**: 通道 1 開啟時，`on 2` 會關閉通道 1
**原因**: 照搬測試程式的單通道測試邏輯
**修正**: 使用位元運算，保留其他通道狀態

### 🔧 核心改進

#### 1. 智能額定電流管理
```python
# 新增狀態追蹤
self.nominal_current_configured = {1: False, 2: False, 3: False, 4: False}
self.channel_nominal_current = {1: 0, 2: 0, 3: 0, 4: 0}

# 智能判斷
if not self.nominal_current_configured[channel]:
    # 首次：執行完整按鈕模擬 (7-10秒)
    self._set_nominal_current(module, channel, nominal_current)
    self.nominal_current_configured[channel] = True
else:
    # 之後：直接開啟 (<1秒)
    logger.info("額定電流已設定，直接開啟")
```

#### 2. 正確的位元運算
```python
# 開啟通道（OR 運算，保留其他通道）
self.output_data[1] = current_value | (1 << bit_position) | 0x80

# 關閉通道（AND NOT 運算，保留其他通道）
self.output_data[1] = (current_value & ~(1 << bit_position)) | 0x80
```

#### 3. 統一的 module 參數
所有方法現在都支援 `module` 參數（預設 1）：
- `turn_on_channel(channel, nominal_current=4, module=1)`
- `turn_off_channel(channel, module=1)`
- `get_channel_current(channel, module=1)`
- `get_all_status(module=1)`

### ✨ 新增功能

#### 重置額定電流設定
```python
def reset_nominal_current_config(channel=None):
    """如果需要重新設定額定電流值"""
    # channel=None 重置所有通道
    # channel=1-4 重置特定通道
```

Shell 命令：
```bash
> reset        # 重置所有通道
> reset 1      # 重置通道 1
```

### 📊 實際使用場景

#### 場景 1: 首次開啟通道
```bash
> on 1
首次設定通道 1 額定電流 4A...
[執行按鈕模擬 - 耗時 7-10 秒]
✅ 通道 1 額定電流設定完成
設定控制位元...
✅ 通道 1 開啟成功
```

#### 場景 2: 開啟第二個通道（第一個保持開啟）
```bash
> on 2
首次設定通道 2 額定電流 4A...
[執行按鈕模擬 - 耗時 7-10 秒]
✅ 通道 2 開啟成功

> status
CH1: 🟢 ON  |  0.45 A  ← 保持開啟 ✅
CH2: 🟢 ON  |  0.52 A  ← 新開啟 ✅
```

#### 場景 3: 快速關閉和重新開啟
```bash
> off 1
🔒 關閉通道 1
✅ 通道 1 關閉成功
[耗時 <1 秒]

> on 1
通道 1 額定電流已設定 (4A)，直接開啟
✅ 通道 1 開啟成功
[耗時 <1 秒] ✅ 超快！
```

#### 場景 4: 多通道並行控制
```bash
> on 1    # 首次 - 慢
> on 2    # 首次 - 慢
> on 3    # 首次 - 慢
> status
CH1: 🟢 ON  |  0.45 A
CH2: 🟢 ON  |  0.52 A
CH3: 🟢 ON  |  0.48 A
CH4: ⚫ OFF |  0.00 A

> off 2   # 快速關閉
> status
CH1: 🟢 ON  |  0.45 A  ← 保持開啟 ✅
CH2: ⚫ OFF |  0.00 A  ← 已關閉 ✅
CH3: 🟢 ON  |  0.48 A  ← 保持開啟 ✅
```

### 📖 更新的文件
- **MULTI_CHANNEL_FIX.md**: 詳細的問題分析和解決方案
- **caparoc_shell.py**: 增加 `reset` 命令和提示訊息

### 🎯 性能提升
- **首次開啟**: 7-10 秒（需要按鈕模擬）
- **後續開關**: <1 秒（直接控制） ⚡
- **多通道**: 完全獨立，互不干擾 ✅

### 💡 使用建議
1. 首次使用時，依序開啟需要的通道（會設定額定電流）
2. 之後的開關操作都很快速
3. 如需更改額定電流值，使用 `reset` 命令
4. 可以同時開啟多個通道，完全獨立控制

---

## [2025-10-21 v3] 修正控制失敗問題 - 實作完整按鈕模擬

### 🐛 根本原因
- **問題**: CLI 無法控制通道開關，但測試程式可以
- **原因**: CLI 缺少完整的額定電流設定流程（LED 按鈕模擬）
- **解決方案**: 從測試程式複製完整的按鈕模擬邏輯

### 🔍 關鍵發現

經過詳細對比 `caparoc_implicit_test.py` 和 `breaker_controller.py`，發現：

#### ❌ 原本的錯誤做法
```python
def _set_nominal_current(self, channel: int, current_amps: int):
    # ❌ 只修改記憶體中的 output_data
    position = 13 + (channel - 1)
    with self.io_lock:
        self.output_data[position] = int(current_amps)
    # ❌ 期望 I/O 執行緒自動同步（但設備不支援）
```

#### ✅ 正確的做法（從測試程式學習）
```python
def _set_nominal_current(self, module: int, channel: int, current_amps: int):
    # ✅ 模擬 LED 按鈕行為
    
    # 步驟1: 進入程式模式（長按 LED 2.5秒）
    prog_data[channel_byte] = (1 << 7) | (1 << 6)
    driver.generic_message(service=0x10, instance=instance, ...)
    time.sleep(2.5)
    
    # 步驟2: 按鈕按壓序列（按 current_amps 次）
    for press_count in range(current_amps):
        press_data[channel_byte] = (1 << channel_bit) | (1 << 7)
        driver.generic_message(...)
        time.sleep(0.5)
        
        # 釋放按鈕
        release_data[channel_byte] = (1 << 7)
        driver.generic_message(...)
        time.sleep(0.3)
    
    # 步驟3: 儲存設定（長按 LED 3秒）
    save_data[channel_byte] = (1 << channel_bit) | (1 << 7) | (1 << 6)
    driver.generic_message(...)
    time.sleep(3.0)
    
    # 步驟4: 退出程式模式
    exit_data = bytearray(data_length)
    driver.generic_message(...)
```

### 📝 技術細節

#### CAPAROC 設備特性
- 🔑 **必須模擬硬體 LED 按鈕行為**才能設定額定電流
- 🔑 **無法**透過 Implicit Messaging 的 output buffer 直接設定
- 🔑 **必須使用** `generic_message` 的 unconnected 模式
- 🔑 需要嘗試多個 Assembly Instance (0x67, 0x68, 0x69, 0x6A, 0x64)

#### 按鈕模擬時序
```
進入程式模式:  2.5 秒
按鈕按壓:      0.5 秒
按鈕釋放:      0.3 秒
儲存設定:      3.0 秒
```

### 🔧 主要修改

1. **重寫 `_set_nominal_current()` 方法**
   - 完整實作 LED 按鈕模擬流程
   - 支援多個 Assembly Instance 嘗試
   - 詳細的日誌輸出

2. **更新 `turn_on_channel()` 方法**
   - 增加 `module` 參數（預設 1）
   - 正確呼叫新的 `_set_nominal_current()`
   - 增加等待時間至 0.5 秒

3. **修正 `get_channel_current()` offset 計算**
   - 修正前: `offset = 20 + (channel-1)*2`
   - 修正後: `offset = 20 + (module-1)*16 + (channel-1)*2`

### 📖 新增文件
- **CODE_COMPARISON.md**: 測試程式 vs CLI 詳細對比分析
  - 關鍵差異說明
  - 完整流程對比
  - 問題根因分析

### 🎯 預期改善
- ✅ CLI 現在應該可以成功控制通道開關
- ✅ 額定電流設定會正確發送到設備
- ✅ 完全對齊測試程式的成功邏輯

### ⚠️ 注意事項
- 額定電流設定需要 **約 6-10 秒**（取決於電流值）
- 每次開啟通道前都會執行完整的按鈕模擬
- 如果首次設定後關閉再開啟，可能不需要重新設定額定電流

### 🧪 測試建議
```bash
# 在 Anaconda Prompt 中測試
conda activate your_env_name
cd C:\Users\harry\Project\Caparoc5
python src/caparoc_shell.py --ip 192.168.2.111

# 在 shell 中執行
> on 1    # 開啟通道 1（會執行完整的按鈕模擬）
> status  # 檢查狀態
```

---

## [2025-10-21] 修正 "Too much data" 錯誤

### 🐛 錯誤修正
- **問題**: 執行 `turn_on_channel()` 時出現 `Generic message 'generic' failed: Too much data` 錯誤
- **原因**: `_set_nominal_current()` 方法使用 `generic_message` 發送了過多資料
- **解決方案**: 改為直接透過 Implicit Messaging 的 `output_data` buffer 設定額定電流

### 📝 技術細節

#### 修正前（錯誤方法）
```python
def _set_nominal_current(self, channel: int, current_amps: int):
    config_data = bytearray(20)
    config_data[position] = int(current_amps)
    
    # ❌ 這會導致 "Too much data" 錯誤
    self.driver.generic_message(
        service=0x10,
        class_code=0x04,
        instance=self.output_instance,
        attribute=3,
        request_data=bytes(config_data),
        connected=False
    )
```

#### 修正後（正確方法）
```python
def _set_nominal_current(self, channel: int, current_amps: int):
    # ✅ 直接透過 Implicit Messaging buffer 設定
    position = 13 + (channel - 1)  # 通道 1-4 對應位置 13-16
    
    with self.io_lock:
        self.output_data[position] = int(current_amps)
    
    # I/O 執行緒會自動將資料同步到設備
```

### 🎯 關鍵概念

**Implicit Messaging 資料流**：
1. 程式修改 `output_data` buffer
2. I/O 執行緒 (20Hz) 自動將 buffer 寫入設備
3. 無需使用 `generic_message` 手動發送

**Output Data 結構**：
```
Byte 0:   [保留]
Byte 1:   控制位元 (bit0-3: 通道1-4, bit7: 啟用位元)
Byte 2-12: [其他控制]
Byte 13:  通道1 額定電流
Byte 14:  通道2 額定電流
Byte 15:  通道3 額定電流
Byte 16:  通道4 額定電流
Byte 17-19: [保留]
```

### ✨ 改進項目
- 改善錯誤處理和日誌輸出
- 增加詳細的 debug 追蹤資訊
- 即使感測器讀取失敗也能正常運作

### 📚 參考
- 測試檔案: `tests/caparoc_implicit_test.py`
- Implicit Messaging 技術說明: `docs/caparoc_implicit_test_analysis.md`

---

## [2025-10-20] 初始版本

### ✨ 新功能
- 建立 CAPAROC 斷路器控制器核心類別
- Implicit Messaging 連接管理
- 20Hz I/O 背景更新執行緒
- CLI 命令列工具
- 互動式 Shell
- 完整文件和使用指南

### 📦 模組
- `src/breaker_controller.py` - 核心控制器
- `src/caparoc_cli.py` - CLI 工具
- `src/caparoc_shell.py` - 互動式 Shell

### 📖 文件
- `docs/CLI_USER_GUIDE.md` - 使用手冊
- `docs/caparoc_implicit_test_analysis.md` - 技術分析
- `docs/TROUBLESHOOTING.md` - 疑難排解
