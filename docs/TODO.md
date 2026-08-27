# CAPAROC 控制器 - 待實作功能清單

更新日期: 2026-08-27

## ✅ 已完成功能

### IP 設定功能（2026-08-11）
- [x] **CIP 0xF5 IP 讀寫**（`caparoc_backend.py`）
  - [x] `set_device_ip()`：靜態 IP 設定（Attr5 + Attr3，LE 字節序）
  - [x] `set_device_dhcp()`：切換 DHCP 模式
  - [x] 確認 `connected=True`（設備不支援 Unconnected Send 0x52）
- [x] **整合工具 `src/caparoc_ip_config.py`**
  - [x] `[1]` 讀取設備網路設定
  - [x] `[2]` 設定靜態 IP
  - [x] `[3]` 切換為 DHCP 模式
  - [x] `[4]` 從 DHCP 模式配置靜態 IP（新裝置初始設定）
- [x] **EtherNet/IP List Identity 設備探索**（UDP 廣播，無需管理員）
- [x] **ARP table fallback 探索**（port 44818 連線測試）
- [x] **mini DHCP server**（port 67，綁定指定 IP，廣播走子網路廣播）

---

## 🔧 caparoc_ip_config.py 改善項目 ✅ 已完成（2026-08-13）

> 本節記錄對 `src/caparoc_ip_config.py` 的改善項目，比對 `tests/test_dcp_ip_config.py`（DCP/DHCP 實驗工具）後確認並實作。

### 已完成項目

| # | 優先 | 說明 |
|---|---|---|
| 1 | 低 | **Typo 修正**：`run_discovery()` 輸出 `廣播0：` → `廣播：`（程式碼中已無此 typo，僅 TODO 記錄未勾）✅ |
| 2 | 高 | **Server IP 選擇**：新增 `_pick_iface()`（移植自 test_dcp_ip_config.py），列出可用網卡含 MAC/IP 讓使用者選擇，取代不可靠的 `gethostbyname()` ✅ |
| 3 | 高 | **固化完整寫入**：`_provision_new_device()` 改呼叫 `backend.set_device_ip(driver, assign_ip, subnet, gateway)`，DHCP ACK 後正確寫入 Attr5（IP/Subnet/GW）+ Attr3（Static），不再只寫 Attr3 ✅ |
| 4 | 中 | **從主連線迴圈獨立**：新增頂層選單 [1]連線設備 / [2]新裝置初始設定，`_provision_new_device()` 不再掛在已連線設備的選單下 ✅ |
| 5 | 低 | **前置說明**：`_provision_new_device()` 開頭顯示前提條件（其他 DHCP/BOOTP 工具已關閉）✅ |
| 6 | 中 | **自動 MAC 偵測**：新增 `_listen_dhcp_discover()`（移植自 test_dcp_ip_config.py，UDP port 67 → Raw Socket 混雜模式 → scapy sniff 三層 fallback），新裝置設定時可自動監聽 DHCP Discover 取得 MAC，不需手動輸入 ✅ |

**未搬入的功能**：PROFINET DCP Layer 2 Identify/Set IP（test_dcp_ip_config.py 選項 [1]-[3]）— 程式註解確認對此設備硬體無效，故意不整合。

---

## 🔧 Web CIP 並發修正後續 refactor ✅ 已完成（2026-08-26，分支 fix/web-cip-concurrency）

> 背景：2026-08-26 補齊了 `_cip_lock` 到所有寫入路徑（`a1951c6`）、修正通道開關失敗誤報成功（`f721f30`, `20db324`）。過程中複查 `caparoc_backend.py` / `web/app.py` 發現的 5 個項目已全數處理，細節見 `docs/CHANGELOG.md`。

| # | 優先 | 說明 | 處理方式 |
|---|---|---|---|
| 1 | 中 | 批次設定額定電流無進度提示，8 通道最長等 24 秒且搶 `_cip_lock` | ✅ 新增 `set_nominal_current_batch()` + `POST /api/channels/nominal`（先全部寫入再單次讀取驗證，約 3 秒）；前端加進行中狀態與筆數提示 |
| 2 | 中 | `_probe_all_modules` 每次連線都寫入真實設備做探測 | ✅ 結果以序號為索引快取至 `config/nominal_probe_cache.json`，命中時零寫入；probe 值改在 `finally` 保證還原；新增 `POST /api/device/reprobe-nominal` 逃生口 |
| 3 | 低 | `_read_nominal_current_silent()` 與 `_verify_nominal_current()` 邏輯重複 | ✅ 合併為 `_read_nominal_current(module, channel, verbose=False)`，controller `verify` 指令一併更新 |
| 4 | 低 | `_read_and_show_result` 位址算錯（`instance=0x101`）、對 web 無意義 | ✅ 改用 `input_instance` + `get_channel_offset()`；`set_channel()` 加 `show_result` 參數，web 傳 `False` 省下 0.5 秒與一次 CIP 往返 |
| 5 | 低 | 30 處 `generic_message` 重複、易漏上鎖 | ✅ 抽出內建 `_cip_lock` 的 `_cip_get()`/`_cip_set()`/`_read_input_assembly()`；需要原子性的兩處（Config Assembly 回退、`set_channel` 寫入+驗證）刻意保留單次持鎖寫法並加註解 |

**⚠️ 尚未實機驗證**：以上皆通過 mock driver 測試與 `--demo` 模式 API smoke test，接實機後需確認批次設定、連線探測快取、通道開關三條路徑。

---

## 🌐 Web「IP 設定」側邊欄分頁 ✅ 已完成（2026-08-27，分支 fix/web-cip-concurrency）

> **背景**：`src/caparoc_ip_config.py` 是一支純互動式 CLI——每個函式都綁死 `input()` / `print(end='\r')`，
> web 層完全無法呼叫，導致設備 IP 設定能力至今只存在於終端機。使用者得離開 web UI、
> 另開終端機、記住 IP 才能改設備網路設定。
>
> **本次範圍**：側邊欄新增獨立一項「🌐 IP 設定」，涵蓋兩項能力——
> **(A) 網段搜尋設備**（List Identity 廣播 + ARP 後援）、**(B) 已連線設備的 IP 設定**（讀取／改靜態 IP／切 DHCP）。
>
> **明確不含**：「全新設備配置精靈」（迷你 DHCP server + MAC 偵測）——需管理員權限與 Npcap、
> 單次流程最長約 6 分鐘、需進度串流與取消機制，留在 CLI。列為未來項目（見本節末）。

### 實作步驟

| Step | 檔案 | 內容 | 狀態 |
|---|---|---|---|
| 1a | `src/caparoc_ip_core.py`（新檔） | 抽出**不含 `input()`/`print()`** 的核心層：`is_valid_ip`／`same_subnet`／`parse_list_identity`／`get_broadcast_addresses`／`eip_port_open`／`probe_eip_hosts`／`discover_devices`／`discover_by_arp`／`wait_for_device`（改用 `on_progress` callback），外加組合函式 `discover()` 統一 EIP→ARP fallback | ✅ 已完成 |
| 1b | `src/caparoc_ip_config.py` | 改具名 import 核心層、**刪除已搬走的函式本體**（9 個函式 + 重複常數）、呼叫點去底線前綴、新增 `_wait_for_device()` CLI 包裝補回進度與結果訊息、`run_discovery()` 改用 `core.discover(on_stage=...)` | ✅ 已完成 |
| 2 | `src/caparoc_backend.py` | `_cip_get`/`_cip_set` 加 `driver=None` 參數；三個 0xF5 方法（`read_device_network_config`/`set_device_ip`/`set_device_dhcp`）改走 wrapper，補上 `_cip_lock`；`set_device_ip` 新增 `ctrl_written` 欄位 | ✅ 已完成 |
| 3 | `web/app.py` | 新增 `GET /api/ipconfig/current`、`POST /api/ipconfig/discover`（含 `_discover_lock` 防並發，409）、`POST /api/ipconfig/static`（含伺服器端自動重連）、`POST /api/ipconfig/dhcp`；四支都有 `_DEMO_MODE` 分支 | ✅ 已完成 |
| 4 | `app.js` / `index.html` / `?v=` | `navItems` 加一項、新增 `currentPage === 'ip-config'` 三面板 + 確認 modal、`refreshIpCurrent()` 併入 `_cipReadInFlight` 旗標、同網段警示、兩處版號 bump 至 `?v=4.3.0`。**零新增 CSS**（19 個類別全部沿用既有樣式） | ✅ 已完成 |
| 5 | `docs/` | CHANGELOG 新增 2026-08-27 條目；`WEB_UI_FEATURE_REFERENCE.md` 頁面表改正（原本用的 `#dashboard` 錨點實際不存在）並補 `ip-config` 列與兩支端點的分工說明 | ✅ 已完成 |

**設計決策**：
- 改 IP 後的**自動重連放在伺服器端**（`POST /api/ipconfig/static` 內：寫入 → `disconnect()` → 換 `device_ip` → `wait_for_device()` 驗證 → `connect()`），
  比讓瀏覽器各自輪詢重連可靠，且 WebSocket 1 Hz 推送會自然把新狀態廣播到所有分頁。
- **已評估並否決**：讓 CLI 改用 `backend.connect()` 以移除 `driver=` 參數。理由是 `connect()` 很重——會
  `_activate_connection_state`、啟動 heartbeat、跑 `_probe_all_modules()`（**探測時會暫時改寫設備額定電流**），
  對一台剛開機、只想改 IP 的設備做這些事既不必要也有風險。

---

### 🔍 Step 2 附帶發現：`_cip_lock` 覆蓋率盤點（修正先前敘述）

規劃時記載「三個 0xF5 方法是全專案**唯三**未上鎖的 `generic_message` 呼叫」——**這個說法不正確**。
實際盤點 `caparoc_backend.py` 全部 14 處 `generic_message` 後，結果是：

| 類別 | 位置 | 判定 |
|---|---|---|
| ✅ 已上鎖 | `_cip_get`、`_cip_set`、`_heartbeat_worker`、`_write_nominal_current`（×2）、`set_channel`（×2）、`_read_current_status` | 正常 |
| ✅ **本次修復** | `read_device_network_config`、`set_device_ip`、`set_device_dhcp` | 改走 `_cip_get`/`_cip_set`，已驗證呼叫期間 `_cip_lock.locked() == True` |
| 🟢 未上鎖但安全 | `check_device_connection`、`_sync_output_from_device`、`_activate_connection_state` | 三者**只在 `connect()` 內執行，且都排在 `_start_heartbeat()` 之前**；WebSocket 讀取又以 `is_connected`（需 `_connected=True`，在 `connect()` 最後一行才設定）為前提。故此期間沒有任何其他執行緒會碰 driver |
| ⚪ 未上鎖但無呼叫者 | `update_config_parameter`、`_wait_for_config_processing` | 全 repo 搜尋確認**無任何呼叫端**，等同 dead code |

**正確的結論**：三個 0xF5 方法是唯三「**web 執行期可達且未上鎖**」的路徑，本次已補齊。
其餘未上鎖處要不是 connect() 期間的單執行緒區段，就是無人呼叫的死碼。

⚠️ **但「connect() 期間安全」是一個沒被寫下來的隱性不變式**——它依賴「heartbeat 尚未啟動」+
「`_connected` 尚未設為 True」兩件事同時成立。日後若有人調動 `connect()` 內的步驟順序
（例如把 `_start_heartbeat()` 提前），這三處會立刻變成真正的競態且極難察覺。

- [ ] **建議後續處理**：在 `connect()` 內這三個呼叫點加註解說明此不變式；或索性把它們也改走
      `_cip_get`/`_cip_set`（此時無競爭，取鎖成本為零，卻能讓規則變成無例外）。
- [ ] **建議後續處理**：確認 `update_config_parameter` / `_wait_for_config_processing` 是否真的可刪。

---

### 🐛 Step 3 附帶發現：`read_device_network_config()` 是**壞的**（既有 bug，非本次造成）

實機測試 `GET /api/ipconfig/current` 時發現它回 `success: false` / `error: "Attr 5 無回應"`。
直接對設備 192.168.50.111 逐一測試三種讀法後確認：

| 讀法 | Attr1 | Attr3 | Attr5 |
|---|---|---|---|
| `connected=False, unconnected_send=False` | ❌ `Too much data` | ❌ | ❌ |
| `connected=False`（pycomm3 預設） | ❌ `Too much data` | ❌ | ❌ |
| `connected=True` | ✅ 4 bytes | ✅ 4 bytes | ✅ 22 bytes |

**本設備三個 0xF5 屬性都只接受 `connected=True`**（它不支援 Unconnected Send 0x52，
這點本專案早有記載，見本檔「IP 設定功能」節）。而 `read_device_network_config()`
從 2026-08-11 寫成以來**一直是寫死 `connected=False`**，也就是說：

> **這個方法自誕生起在這台設備上就從未成功過。**
> 之所以沒被發現，是因為它**在本次之前沒有任何呼叫端**——
> CLI 的 `read_config()` 走的是自己的 `_read_attr()`，那支有 `connected=False → True` 的退回機制。

- [x] **已修復**：`read_device_network_config()` 內新增 `_read_f5(attr)`，比照 CLI `_read_attr()`
      做兩段式嘗試（先 False 再 True）。不寫死 `True` 是為了相容其他韌體/型號。
- [x] **實機驗證通過**：讀回 `ip=192.168.50.111 / subnet=255.255.254.0 / gateway=192.168.50.1 /
      config_control_str=Static IP`，IP 與連線位址相符。

💡 **順帶佐證**：實機遮罩是 `255.255.254.0`（**/23**），正好對應 `caparoc_ip_config.py` 中
`DHCP_LIMITED_BROADCAST` 那段註解描述的真實情境（網卡 /24、設備回報 /23），該註解所述並非假設性問題。

---

### ⚠️ 目前改動後的問題清單

#### A. 本次改動新產生的問題 — ✅ 已於 Step 1b 全數收掉

| # | 嚴重度 | 問題 | 結果 |
|---|---|---|---|
| 1 | 🔴 高 | **邏輯一度出現兩份複本**：核心層建立後、Step 1b 執行前，`caparoc_ip_config.py` 內 9 個同名函式本體仍存在 | ✅ 已刪除全部重複本體，`grep` 確認全 repo 無殘留舊名（`_is_valid_ip`／`_discover_devices` 等） |
| 2 | 🟡 中 | 兩份複本行為不一致（core 的 `discover_by_arp()` 多包 `except FileNotFoundError`；`wait_for_device()` 不再自行 print） | ✅ 舊本體已刪，只剩一份。CLI 新增 `_wait_for_device()` 包裝補回 `⏳ 剩餘 Ns` 進度與 ✅/⚠️ 結果訊息，輸出與改動前一致 |
| 3 | 🟢 低 | 核心層一度無任何呼叫者（dead code） | ✅ CLI 已改為呼叫核心層；web（Step 3）尚未接上，但已非孤兒 |

**Step 1b 額外設計決策**：`core.discover()` 新增 `on_stage` callback。原本 CLI 會在**開始 ARP 掃描前**印
「List Identity 無回應，改用 ARP table...」，但 fallback 邏輯移進核心層後就印不出來了——ARP 掃描可能耗時數秒，
等結束才提示會讓使用者對著空畫面等待。改用 callback 讓核心層在每個階段**開始前**通知呼叫端，
維持 CLI 輸出時序不變，web 則可直接忽略此參數。

**Step 1 驗收結果**（`python src/caparoc_ip_config.py`，conda `sv` env）：
- ✅ 無參數 → 主選單正常，`[0]` 離開正常
- ✅ `999.1.1.1` → 印格式錯誤 + docstring
- ✅ `[1]` 探索 → 廣播訊息 → ARP fallback 訊息（順序正確）→ 找到實機 `192.168.50.111`，列表格式與改動前一致
- ⚠️ 已知既有現象（非本次造成）：輸出被導向 pipe 時，emoji 在 cp950 下會 `UnicodeEncodeError`；
  正常終端機或 `PYTHONIOENCODING=utf-8` 下無此問題

#### B. 本次**確認存在但不在範圍內**的既有問題（記錄備查，不在本分支修）

| # | 位置 | 問題 | 判斷 |
|---|---|---|---|
| 4 | `caparoc_ip_config.py:418`、`:467` | **把 BOOTP `op` 欄位當成 DHCP message type**：`if data[0] != DHCP_DISCOVER`。`data[0]` 是 `op`（1 = BOOTREQUEST），不是 Option 53。因為 `DHCP_DISCOVER == 1 == BOOTREQUEST` 湊巧能動，但它會**匹配任何 client→server 的 BOOTP 訊息**（REQUEST／RELEASE／INFORM），使 `_detect_mac_via_socket()` 可能回報一台正在「續約」而非「首次探索」的設備 MAC。同檔的 `_detect_mac_via_scapy():509` 與 `_serve_dhcp():628` 則是**正確**地走 Option 迴圈解析 | 在 provisioning 路徑上，本次範圍外。但若日後把配置精靈搬上 web、要在 UI 顯示「已偵測到設備 MAC」這種確認步驟，**必須先修這個** |
| 5 | `caparoc_backend.py:2089` | `set_device_dhcp()` 把**任何例外都回報成 `success=True`**。原意是「IP 一變連線就死、拿不到回應屬正常」，但這讓真失敗與預期斷線無法區分 | **刻意不改**——改動它有把「本來會動」變成「回報失敗」的風險。改由寫入後的**實際驗證**補償：靜態 IP 走 `wait_for_device()` 給出確定答案，DHCP 走「搜尋設備找回新 IP」。⚠️ 維護者需知道：**這裡的真相來源是驗證步驟，不是回傳值** |
| 6 | `caparoc_ip_core.py:discover_by_arp()` | 依賴 `arp -a` 輸出的**語系文字**（`'動態'` / `'dynamic'`）判斷動態項目。非 zh-TW／英文語系下會找不到任何項目 | 已知限制，搬移時原樣保留並補了註解。ARP 只是 List Identity 失敗時的後援，影響有限 |
| 7 | `caparoc_ip_core.py:get_broadcast_addresses()` | 用 `socket.getaddrinfo(gethostname())` 推導網卡，並**硬編 `.255`（假設 /24）**。多網卡環境下 hostname 解析不到的網卡會被漏掉；非 /24 網段（如 /23）算出的廣播位址是錯的 | 已知限制，原樣保留。受限廣播 `255.255.255.255` 一律會送，多數情況仍能命中 |

#### C. 本次會**新欠下**的技術債（已評估，接受）

| # | 債務 | 影響 | 處置 |
|---|---|---|---|
| 8 | `app.js` 的單一巨型 `setup()` 會從 751 行漲到約 870 行，`return {}` 再多約 17 個鍵 | 全案最大長期債，本次讓它更肥 | **不在本次償還**（引入 build step / SFC 是另一層級改動）。折衷：IP 設定的 state 與函式集中在**單一 banner 註解區塊**、`return {}` 也集中成一個群組，讓日後抽 composable 時是「一刀切」而非大海撈針 |
| 9 | `/api/device/network`（`get_network_info`，MAC/hostname）與 `/api/ipconfig/current`（`read_device_network_config`，0xF5 Attr1/3/5 含 Static/DHCP 模式）**語意重疊** | 日後易搞混、或在錯的端點加欄位 | 不合併（新頁面**必須**有 `config_control`，舊端點沒有）。改為兩者 docstring 互相指路 + `WEB_UI_FEATURE_REFERENCE.md` 表格明列差異 |
| 10 | 每個新端點都要手寫 `_DEMO_MODE` 分支 | 漏寫 → `--demo` 在該頁靜默壞掉，且無測試會抓到 | 既有慣例的固定稅，無法迴避。列入驗證清單逐項點過 |
| 11 | `?v=` 版號在 `index.html:8` 與 `:553` **兩處手動更新** | 漏改 → 使用者拿到舊 JS，回報「新功能沒出現」，除錯成本高 | 本次照舊手動改。未來可改由 `/` 路由注入單一版號常數——但那要把 `FileResponse` 換成模板渲染，超出本次範圍 |

---

### 建議順手做的低成本保險（選配）

核心層抽出後，`is_valid_ip` / `same_subnet` / `parse_list_identity` / `get_broadcast_addresses`
成了本專案**第一批無副作用、可無痛單元測試的純函式**。建議加 `tests/test_ip_core.py`（約 30 行，
含 `parse_list_identity` 對固定 bytes 的解析斷言），成本極低卻能給日後動探索邏輯的人一張安全網。
不做也不影響本節其餘部分。

### 未來項目

- [ ] **全新設備配置精靈上 web**（迷你 DHCP server + MAC 偵測）。前置條件：先修問題 #4；
      並需設計進度串流（現有進度是 `print(end='\r')`，web 完全看不到）與取消機制。

---

### V3.6 (2025-10-28) - Phase 3-2 完成
- [x] **即時監控功能** ✅
  - [x] 背景執行緒定期讀取狀態 (可設定0.5s-60s)
  - [x] 簡潔監控顯示格式 (通道電流即時更新)
  - [x] 狀態變化檢測與警報系統
  - [x] 通道開關狀態變化偵測
  - [x] 電流異常變化偵測 (>30%)
  - [x] 系統電壓變化偵測 (>1V)
  - [x] 新警告/錯誤即時通知
  - [x] 多模組環境完全支援
  - [x] 新增監控指令:
    - [x] `monitor start [interval]` - 啟動監控
    - [x] `monitor stop` - 停止監控
    - [x] `monitor status` - 查看監控狀態

### V3.5 (2025-10-28) - 多模組架構
- [x] **動態多模組支援** ✅
  - [x] 自動偵測模組數量 (1-16 個模組)
  - [x] 動態通道管理 (最多 64 通道)
  - [x] 多模組顯示格式 (M1.CH1 #1)
  - [x] 向後兼容單模組環境
  - [x] 動態位移計算函數 `get_channel_offset(module, channel)`
  - [x] 總通道數查詢函數 `get_total_channels()`
  - [x] 全域通道轉換函數 `get_module_and_channel(global_ch)`
  - [x] 多模組互動式電流設定
  - [x] 多模組批次初始化支援
  - [x] 更新 PROGRAM_FLOW.md 多模組架構說明

### V3.4 (2025-10-28) - Phase 3-1 完成
- [x] **程式啟動全域狀態檢查** ✅
  - [x] 系統電壓檢查 (9.0-30.5V,建議24V)
  - [x] 欠壓/過壓狀態檢測與警告
  - [x] 系統錯誤檢測
  - [x] 80%總電流警告檢測
  - [x] 總電流關斷狀態檢測
  - [x] 配置處理中狀態顯示
  - [x] 異常狀態時提示使用者是否繼續
  - [x] 結構化狀態回報 (errors, warnings, safe)
  - [x] **完整手冊 7.2.1-7.2.5 實作**:
    - [x] 7.2.1: 全域系統狀態 (Byte 0, 6 位元)
    - [x] 7.2.2: 模組計數器 (Byte 1, 0-16 模組)
    - [x] 7.2.3: 總電流讀取 (Byte 2-3, 0-50.0A)
    - [x] 7.2.4: 輸入電壓讀取 (Byte 4-5, 9.0-30.5V)
    - [x] 7.2.5: 通道資料區塊 (每通道 3 bytes × 4 × N 模組)
      - Byte 0: 6 個狀態位元 (開/關, 80%警告, 過載, 短路, 硬體故障, 總電流關斷)
      - Byte 1: 額定電流 (0.5-10A)
      - Byte 2: 實際流動電流 (0-25.5A)

### V3.3 (2025-10-27) - Phase 2 完成
- [x] **狀態顯示增強** ✅
  - [x] 全域系統狀態顯示 (Byte 0: 欠壓/過壓/系統錯誤/80%警告/總電流關斷)
  - [x] 修正電壓讀取 (Byte 4-5 / 100.0)
  - [x] 修正總電流讀取 (Byte 2-3 / 10.0)
  - [x] 通道電流總和與全域總電流比對驗證
  - [x] 設備復電狀態同步修復 (從 Input Assembly 讀取實際狀態)

### V3.2 (2025-10-27) - Phase 1 完成
- [x] **初始化電流值設定 (可配置)** ✅
  - [x] 互動式設定介面
  - [x] 每個通道獨立設定 (0.5A - 25.5A)
  - [x] 按 Enter 使用預設值 (4A)
  - [x] 設定摘要與確認機制
  - [x] 輸入驗證與錯誤處理
  - [x] 跳過初始化選項 (保持設備當前狀態)

### V3.1 (2025-10-27)
- [x] 多通道獨立控制 (on/off)
- [x] 即時狀態讀取 (電壓、電流)
- [x] 通道額定電流初始化 (LED按鈕模擬)
- [x] Implicit Messaging 自動檢測
- [x] 狀態讀取完全修復 (根據手冊 Table 7-4)
- [x] UI 優化 (簡潔輸出)

---

## ⚠️ 待實作功能

### Phase 3: 進階功能開發

#### 1. ~~Step 1 全域系統狀態確認功能~~ ✅ **已完成 (V3.4)**

**目標**: 在初始化前檢查系統是否正常

**功能需求**:
- [x] 在 `prompt_channel_currents()` 之前新增系統檢查
- [x] **完整涵蓋手冊 7.2.1-7.2.4 功能**:
  - [x] **7.2.1**: 讀取並解析全域系統狀態 (Byte 0)
    - 欠壓 (Undervoltage) - bit 0
    - 過壓 (Overvoltage) - bit 1
    - 系統錯誤 (System Error) - bit 2
    - 80% 額定電流警告 - bit 3
    - 總電流關斷 - bit 4
    - Config assembly 處理狀態 - bit 7
  - [x] **7.2.2**: 讀取模組計數器 (Byte 1) - 偵測安裝的斷路器模組數量
  - [x] **7.2.3**: 讀取全域總電流 (Byte 2-3) - 0-50.0A
  - [x] **7.2.4**: 讀取全域輸入電壓 (Byte 4-5) - 9.0-30.5V
- [x] 如果有異常,警告用戶並詢問是否繼續
- [x] 在 `show_status()` 中也顯示完整全域狀態
- [x] 更新文件 (PROGRAM_FLOW.md 加入 Step 0)

**完成時間**: 2025-10-28  
**實際工時**: 2 小時

---

#### 2. ~~即時監控 (Real-time Status Monitoring)~~ ✅ **已完成 (V3.6)**

**目標**: 定期自動回傳設備狀態

**功能需求**:
- [x] 背景執行緒定期讀取狀態 (可設定間隔: 0.5s-60s)
- [x] 即時顯示模式 (定期輸出通道電流)
- [x] 新增指令:
  - [x] `monitor start [interval]` - 啟動監控 (預設2s)
  - [x] `monitor stop` - 停止監控
  - [x] `monitor status` - 顯示監控狀態
- [x] 狀態變化檢測與警報:
  - [x] 通道開關狀態變化偵測
  - [x] 電流異常變化偵測 (>30%變化)
  - [x] 系統電壓變化偵測 (>1V)
  - [x] 新出現的警告/錯誤即時顯示
- [x] 簡潔監控顯示格式
- [x] 多模組環境支援

**實作方法**:
```python
def start_monitor(self, interval=None):
    """啟動即時監控 (背景執行緒)"""
    
def stop_monitor(self):
    """停止即時監控"""
    
def _monitor_worker(self):
    """監控背景執行緒"""
    
def _read_current_status(self):
    """讀取當前狀態"""
    
def _detect_changes(self, current_status):
    """檢測狀態變化"""
    
def _show_monitor_status(self, status, changes):
    """顯示監控狀態"""
```

**完成時間**: 2025-10-28  
**實際工時**: 2.5 小時

---

#### 3. ~~初始化 IP 設定~~ ✅ **已完成 (v3.7)**

**目標**: 支援多設備或動態 IP

**功能需求**:
- [x] 命令列參數支援 (`--ip`, `--port`)
- [x] 預設 IP 設定 (192.168.2.111:44818)
- [x] 連接測試與錯誤處理
- [x] 啟動時顯示連接資訊

**完成時間**: 2025-11-26 (程式啟動時已實現)
**實際工時**: 已包含在主程式開發中

---

## 📅 開發優先順序

### 已完成階段
1. **Phase 1**: 初始化電流值設定 ✅ **已完成** (V3.2, 2025-10-27)
   - 互動式命令列設定
   - 提升使用便利性

2. **Phase 2**: 狀態顯示增強 ✅ **已完成** (V3.3, 2025-10-27)
   - 全域系統狀態顯示
   - 設備復電狀態同步修復
   - 電壓/電流讀取修正

3. **Phase 3**: CLI 完整功能實現 ✅ **已完成** (V3.2-V3.7, 2025-10-27 - 2025-11-26)
   - ✅ 額定電流設定 (init 命令)
   - ✅ 四通道開關控制 (on/off 命令)
   - ✅ 全域系統狀態監控
   - ✅ 通道狀態查詢 (status 命令)
   - ✅ 即時監控功能 (monitor 命令)
   - ✅ 多模組支援 (1-16 模組)
   - ✅ IP 設定支援
   - ✅ 心跳機制維持連接
   - ✅ 完整的錯誤處理與重連機制

**Phase 3 總工時**: ~20 小時  
**Phase 3 成果**: 完整可用的 CLI 控制系統

4. **Phase 3.5（補充）**: 架構重構 ✅ **已完成** (v3.8, 2026-04-02)
   - ✅ 前後端分離 (`caparoc_backend.py` + `CaparocController` 繼承架構)
   - ✅ Log 系統 (`logging_manager.py` + `config/logging_config.json`)
   - ✅ CLI 保留（`python caparoc_controller.py` 仍可正常使用）

5. **Phase 3.6.x**：連線 IP 管理、setting 重設計、logging 修復 ✅ **已完成** (v3.8, 2026-05-14)
   - ✅ `config/device_config.json` 預設 IP 持久化
   - ✅ `setting` 選單重設計（[1]變更重連 / [2]恢復 / [3]存檔 / [4]硬體 IP）
   - ✅ logging KeyError 修復，移除 JSONL
   - ✅ setting 操作寫入 log（`[SETTING]` 模組）

---

### Phase 3.6: GUI 前置準備 🔧（**開始 GUI 前必須完成**）

> GUI 框架決策：**FastAPI + Vue 3 CDN + WebSocket**（前後端分離，頁面設計可獨立開發）  
> 進入方式：`uvicorn web.app:app`，瀏覽器開啟 `http://localhost:8000`  
> 資料夾結構：`web/app.py` + `web/templates/` + `web/static/`

#### 3.6.1 CaparocBackend 連線管理重構 ✅ **已完成（2026-05-15）**

**問題**: 目前連線生命週期綁定在 `with CIPDriver(...) as driver:` 內，Web 服務無法長駐使用。

**完成內容**:
- [x] `connect()` — 開啟 CIPDriver、驗證連線、同步 output buffer、activate state、啟動 heartbeat
- [x] `disconnect()` — 停止監控與心跳、關閉 CIPDriver
- [x] `is_connected` — property，回傳 `bool`（True = driver 已開啟且旗標有效）
- [x] `_cleanup_driver()` — 內部資源清理輔助方法
- [x] `_sync_output_from_device()` — 讀取設備實際通道狀態，重建 output buffer（防誤關正在運作的通道）
- [x] CLI（`caparoc_controller.py`）繼承這些方法，完全向後相容

**實際工時**: 0.5 小時

---

#### 3.6.2 caparoc_controller.py 冗餘方法清除 ✅ **已完成（2026-05-14）**

**問題**: controller 繼承 CaparocBackend，但仍保留所有後端方法完整複本（shadow 父類別）。

**完成內容**:
- [x] `CaparocController` 中 29 個與 `CaparocBackend` 重複的方法全數刪除（1513 行）
- [x] 保留：`__init__`、`_show_help_message`、`_configure_device_ip`、`_validate_ip`、`_ask_save_default_ip`、`_handle_setting_connip`、`_handle_settingdeviceip_command`、`_handle_write_device_ip`、`run()`
- [x] controller 從 2387 行縮減至 874 行（-63%）
- [x] 驗證：繼承 CaparocBackend 的 30 個方法全部可正常存取

**實際工時**: 1 小時

---

#### 3.6.3 設備 IP 位址寫入功能（硬寫設備 IP）⏸️ **暫不開發**

> **完成部分**：連線 IP 管理、預設 IP 持久化、CLI 重構  
> **暫緩部分**：設備硬體 IP 寫入（CIP 0xF5 / PROFINET DCP）— **目前不列入開發計畫，待未來有需求再評估**

- [x] 連線失敗時加入 `[C]` 變更 IP 選項
- [x] `config/device_config.json` 預設 IP 持久化
- [x] `setting` 指令重設計（[1]變更並連線 / [2]恢復預設 / [3]存為預設 / [4]硬體 IP）
- [x] `settingdeviceip` 整合至 `setting [4]`
- [ ] ~~設備硬體 IP 寫入（PROFINET DCP 需 Npcap，暫不開發）~~
  - 替代方案：使用 Phoenix Contact PRONETA Basic 設定設備 IP

---

**Phase 3.6 剩餘工時**: ✅ 全部完成（3.6.1 + 3.6.2）

---

### Phase 4: Web UI 與進階功能 🚀

#### 4.0 Web 服務骨架建立 ✅ **已完成（2026-05-15）**

**完成內容**:
- [x] 建立 `web/` 目錄（`web/app.py`, `web/templates/index.html`, `web/static/css/style.css`, `web/static/js/app.js`）
- [x] 安裝 `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`，更新 `requirements.txt`
- [x] `web/app.py`：FastAPI 實例，`lifespan` 事件呼叫 `backend.connect()` / `disconnect()`
- [x] `/api/status` endpoint（回傳設備完整狀態 JSON）
- [x] `/api/connect`, `/api/disconnect` endpoint
- [x] `/api/channel/{id}/on`, `/api/channel/{id}/off`, `/api/channel/{id}/nominal` endpoint
- [x] WebSocket `/ws/status`（每秒推送 `_read_current_status()` 資料）
- [x] `web/templates/index.html`：Vue 3 CDN 骨架，顯示連線狀態 / 系統資訊 / 通道面板
- [x] `web/static/js/app.js`：Vue 3 應用邏輯，WebSocket 自動重連
- [x] 驗證：`http://localhost:8000` 正常開啟，API 讀到真實設備 24.04V，CH1/CH3 ON

**實際工時**: 1 小時

---

#### 4.2 Web UI 頁面設計

> 前置條件：Phase 4.0 骨架完成 ✅  
> 可與 Phase 4.1（CLI 增強）**並行開發**，依賴 API Contract 定義，頁面設計不需等待 Python 函式全部完成

**完成狀態：4.2.1–4.2.9 全部 ✅ 已完成（4.2.5 設定值外部化 已移至 4.3.1）**

---

##### 4.2.1 左側導覽列骨架（頁面結構重構）✅ **已完成（2026-05-18）**

> **目的**：建立整體頁面框架，後續所有功能都建立在此結構上

- [x] 重構 `index.html` / `app.js`，加入左側 sidebar 導覽列（☰ 按鈕可收合）
- [x] 5 個頁面（Vue `currentPage` ref 控制條件渲染）：
  - `dashboard` — 儀表板（現有通道卡片）
  - `charts` — 圖表監控（placeholder，4.2.4 實作）
  - `channel-settings` — 通道設定（placeholder，4.2.2 實作）
  - `logs` — 系統日誌（placeholder，4.2.3 實作）
  - `connection` — 連線設定（連線表單移入此頁）
- [x] 頂部固定列保留：連線狀態指示燈、設備 IP、連線/斷線按鈕
- [x] `style.css` 加入 sidebar / layout / placeholder 樣式

**實際工時**：1 小時

---

##### 4.2.2 通道設定頁（額定電流 UI）✅ **已完成（2026-05-18）**

> **目的**：補齊 CLI `init` 指令在 Web UI 的對應功能（API 已存在，只缺 UI）  
> **依賴**：4.2.1 完成 ✅  
> **後端 API**：`POST /api/channel/{id}/nominal?current_amps=X`（已實作）

- [x] `channel-settings` 頁顯示所有通道表格（通道編號、模組、目前額定電流、輸入欄位、操作）
- [x] 每列：整數輸入欄（1–20 A）+ 「設定」按鈕 → 呼叫 `/api/channel/{id}/nominal`
- [x] 設定成功後即時更新顯示值，並顯示成功/失敗提示（3 秒後自動清除）
- [x] 「全部套用」按鈕：批次設定所有通道為相同額定電流
- [x] 表格資料從 WebSocket 狀態自動填入目前值
- [x] **bug fix**：API 加入回傳值檢查（`backend.set_nominal_current()` 回傳 False 時回 HTTP 500）
- [x] **bug fix**：float 輸入先 `int(round(...))` 再傳入，修正 `struct.pack('<B')` 型別錯誤
- [x] **bug fix**：輸入範圍改為 1–20 A（對齊 backend 驗證）

**實際工時**：1.5 小時

---

##### 4.2.3 系統日誌頁 ✅ **已完成（2026-05-18）**

> **目的**：在網頁查看 backend 運作日誌，取代需要看終端機的問題  
> **依賴**：4.2.1 完成 ✅（後端修改獨立於 4.2.2）  
> **後端 API**：`GET /api/logs?level=&limit=&offset=`、`POST /api/logs/clear`

**後端（`web/app.py`）**：
- [x] 新增 `_SYSTEM_LEVEL = 25`（介於 INFO/WARNING），`logging.addLevelName` 註冊
- [x] `_CaparocLogHandler`：繼承 `logging.Handler`，寫入 `deque(maxlen=500)`
- [x] 掛載到 `caparoc` logger（含所有 `caparoc.*` 子層）
- [x] `GET /api/logs?level=all|warn|error&limit=N&offset=N` — offset 分頁，最新在前
- [x] `POST /api/logs/clear` — 清空緩衝
- [x] lifespan / connect / disconnect 事件發出 SYSTEM 等級 log

**前端**：
- [x] `logs` 頁定時輪詢（每 2 秒）`/api/logs`，切換頁面時停止
- [x] 顏色區分：INFO（藍）、WARNING（橘）、ERROR（紅）、SYSTEM（紫）、CRITICAL（深紅）、DEBUG（灰）
- [x] 等級篩選下拉選單（全部 / WARNING+ / ERROR）
- [x] 每頁顯示條數切換（10 / 20），分段按鈕 UI
- [x] 分頁：上一頁 / 第 X / Y 頁 / 下一頁
- [x] 「暫停 / 自動更新」切換按鈕（暫停時停止輪詢，恢復時跳回第 0 頁）
- [x] 「清空」按鈕（呼叫後端 API + 清空前端 buffer）

**實際工時**：1.5 小時

---

##### 4.2.4 圖表監控頁 ✅ **已完成（2026-05-20）**

> **目的**：視覺化顯示電流/電壓歷史趨勢  
> **依賴**：4.2.1 完成 ✅  
> **實際工時**：1 小時  
> **資料來源**：前端 JS 從 WebSocket 資料流累積（滾動 120 秒 buffer，不需後端另存）

**圖表庫**：Chart.js 4.4.6 CDN（`https://cdn.jsdelivr.net/npm/chart.js`）

**全域曲線**（上方大圖）：
- [x] 雙 Y 軸折線圖：電壓（V，左軸，藍色）+ 總電流（A，右軸，橘色），滾動視窗
- [x] 互動提示（crosshair + tooltip 對齊）

**各通道電流曲線**（下方）：
- [x] 每通道一條折線，同一張圖疊加（最多 8 色循環）
- [x] 圖例可點擊顯示/隱藏個別通道（Chart.js 內建）

**控制選項**：
- [x] 視窗大小選擇：30 秒 / 60 秒 / 120 秒
- [x] 暫停/恢復即時更新按鈕（暫停時停止累積歷史，不影響設備狀態顯示）
- [x] 切換連線狀態時自動初始化/銷毀圖表實例

---

**Phase 4.2 進度**：4.2.1–4.2.9 全部 ✅ 已完成

---

##### 4.2.4-bug 告警事件未寫入 log ✅ **已修復（2026-05-20, fa387e0）**

> **問題根源**：`_detect_changes()` 偵測到短路/過載/80% 警告/通道開關/電壓異常後，將結果加入
> `changes['system_alerts']` / `channel_state_changes`，但 `_monitor_worker()` 只把這些資訊
> 傳給 `_show_monitor_status()` / `_show_monitor_alerts()`（CLI print），**完全未呼叫
> `self.logger.warning()`**，導致告警僅出現在終端機，不會寫入 log 檔或 Web 日誌頁。

- [x] `_monitor_worker()` 迴圈中，對 `changes['system_alerts']` 每一則呼叫
  `self.logger.warning(msg, extra={'log_module': 'CONN'})`
- [x] 防 spam：`_detect_changes()` 已做狀態轉換偵測（False→True 才觸發），無需額外 set/dict 追蹤
- [x] `channel_state_changes`（開/關事件）呼叫 `self.logger.info()`
- [x] `current_anomalies`（電流突變 >30%）呼叫 `self.logger.warning()`

**受影響的告警類型**：

| 告警 | `_detect_changes` 已偵測 | 修復後 logger 呼叫 |
|------|------------------------|--------------------|
| 短路 (short_circuit) | ✅ | ✅ WARNING log |
| 過載 (overload) | ✅ | ✅ WARNING log |
| 80% 電流警告 | ✅ | ✅ WARNING log |
| 通道開/關 | ✅ | ✅ INFO log |
| 電流突變 >30% | ✅ | ✅ WARNING log |
| 電壓突變 >1V | ✅ | ✅ WARNING log |

---

##### 4.2.6 圖表監控頁增強（通道圖拆分 + 歷史查詢）✅ **已完成（2026-05-21, a4750d8 + 3174cba）**

> **實作方式**：依模組各建一張折線圖（每模組一個 Chart.js 實例），含 checkbox 控制通道顯示，  
> 支援滑鼠拖曳/滾輪縮放查看歷史（chartjs-plugin-zoom），後端保存最近 30 分鐘資料。

**工作項目**：
- [x] `web/app.py`：新增 `_history_buffer = deque(maxlen=1800)`；WebSocket handler 推送時同步寫入
- [x] `web/app.py`：新增 `GET /api/history?minutes=N` endpoint（N 預設 10，最多 30）
- [x] `app.js`：`_initCharts()` 先 fetch `/api/history` 預填 `_chartHistory`，再開始即時更新
- [x] `app.js`：改為每模組一張 Chart 實例（`_moduleCharts` dict）；`v-for="mod in activeModules"` 動態生成
- [x] `app.js`：加入 chartjs-plugin-zoom（拖曳/滾輪縮放）；歷史模式停止自動更新，「▶ 即時」按鈕跳回實時
- [x] `app.js`：修復 `jumpToLive()` — `resetZoom()` 同步觸發 `onZoomComplete` 把 `chartHistoryMode` 改回 true，改為 resetZoom 後再設 false（3174cba）
- [x] `index.html`：每模組獨立 `<canvas>`（`v-for` 生成）+ 通道 checkbox UI
- [x] `style.css`：模組標題欄（`.chart-section-header`）、checkbox 行（`.chart-ch-checks`）樣式

---

##### 4.2.7 設備網路資訊讀取（TCP/IP Interface + MAC 位址）✅ **已完成（2026-05-21）**

> **目的**：透過 CIP 協議讀取 CAPAROC 設備的網路資訊，顯示於 Web UI 連線設定頁  
> **實際工時**：1.5 小時

- [x] `caparoc_backend.py`：新增 `get_network_info()`（CIP 0xF5 + 0xF6）
  - IP、子網路遮罩、預設閘道（Attr 3 LE UDINT → `struct.unpack('<I')` + bit-shift）
  - MAC 位址（Ethernet Link 0xF6，6 bytes → `XX:XX:XX:XX:XX:XX`）
  - 各屬性獨立 `try/except`，單一失敗不影響其他欄位；全部 `connected=True` 持 `_cip_lock`
- [x] `web/app.py`：新增 `GET /api/device/network` endpoint；未連線時回 HTTP 503
- [x] `app.js`：連線設定頁新增「設備網路資訊」面板；連線成功後自動查詢一次，含 ↻ 手動重新整理按鈕
- [x] Bug fix：IP 轉換必須先 `struct.unpack('<I')` 再 bit-shift，直接順讀 LE bytes 會顯示倒序

---

##### 4.2.8 頂部列關閉按鈕（關閉分頁）✅ **已完成（2026-05-22）**

> **目的**：在頂部列最右方新增「✕」關閉按鈕，讓使用者快速關閉瀏覽器分頁；  
> 同時整理連線/斷線與關閉按鈕的位置邏輯。

**頂部列按鈕佈局**（左 → 右）：

```
[☰  CAPAROC]          [● 已連線 · IP]  [連線 / 斷線]  [✕]
 ← topbar-left →      ←————————— topbar-right ——————————→
```

- `conn-bar`（連線狀態 + 連線/斷線按鈕）與 `✕` 關閉按鈕同屬 `topbar-right`，靠右對齊
- 以 `|` 分隔線視覺區隔兩個操作區域
- 關閉按鈕觸發 `window.close()`，關閉當前瀏覽器分頁

**工作項目**：
- [x] `index.html`：將 `conn-bar` 與關閉按鈕包入 `topbar-right` div，`✕` 置於最右
- [x] `style.css`：新增 `.topbar-right`（flex）、`.topbar-sep`（分隔線）、`.btn-close-tab` 樣式
- [x] `app.js`：新增 `doCloseTab()` 函式（`window.close()`）並加入 return object
- [x] `app.js`：圖表監控電壓 Y 軸 ticks 與 tooltip 顯示小數點後兩位（`toFixed(2)`）

---

##### 4.2.9 系統狀態頁（設備識別 + 全域設定）✅ **已完成（2026-05-22）**

> **目的**：新增「系統狀態」導覽頁，透過 EIP 協議讀取設備識別資訊與全域設定參數，一次性呈現設備身份與配置  
> **實際工時**：2 小時

- [x] `caparoc_backend.py`：新增 `get_device_info()` — Identity Object (0x01:1, attr 1/2/3/4/6/7) + Class 0x0F inst 1-4 attr 1；各屬性獨立 `try/except`；全部 `connected=True` 持 `_cip_lock`
- [x] `web/app.py`：新增 `GET /api/device/info` endpoint；未連線時回 HTTP 503
- [x] `app.js`：`deviceInfo` ref（localStorage 快取 `caparoc_device_info`）；首次連線自動呼叫 `fetchDeviceInfo()`；含 ↻ 手動重新整理按鈕
- [x] `index.html`：新增 `system-status` 頁（「設備識別」面板 + 「全域設定」面板）；未連線時顯示快取並標記「（上次連線資訊）」

---

#### 4.3 Web UI 介面優化、美化

> **目標**：提升 Web UI 的視覺一致性與使用體驗，完善部署彈性

---

##### 4.3.1 設定值外部化（config 合併）

> **目的**：將散落的多個 config 檔案合併為單一 `config/config.json`，集中管理所有可調參數  
> **預估工時**：1 小時

**目前配置檔案現況**：
- `config/device_config.json` — 僅存 `default_ip`
- `config/logging_config.json` — Log 等級、檔案大小、備份數

**合併後 `config/config.json` 結構**：

```json
{
  "device": {
    "default_ip": "192.168.50.111"
  },
  "web": {
    "port": 8000,
    "ws_push_interval": 1.0,
    "ws_idle_shutdown": 10
  },
  "logging": {
    "level": "INFO",
    "max_bytes": 5242880,
    "backup_count": 3
  },
  "nominal_current": {
    "min": 1,
    "max": 20
  }
}
```

**工作項目**：
- [ ] 建立 `config/config.json`，合併 device + logging + web 設定
- [ ] 刪除舊的 `device_config.json`、`logging_config.json`
- [ ] `web/app.py` 改為讀取 `config/config.json`
- [ ] `src/logging_manager.py` 改為讀取 `config/config.json` 的 `logging` 區塊
- [ ] `src/caparoc_backend.py` 從 config 讀取 nominal range
- [ ] `app.js` 從 `GET /api/config/limits` 取得 nominal_current_range，動態設定 input min/max
- [ ] 建立 `config/config.example.json`（含註解說明，供首次部署參考）

**預估工時**：1 小時

---

##### 4.3.2 通道設定頁按模組分區顯示 ✅ **已完成（2026-07-23）**

> **目的**：與儀表板「通道控制」區塊一致，將目前單一大表格改為依模組分區，方便混合模組（2/4 通道）的額定電流設定

**完成內容**：
- [x] `app.js`：新增 `batchNominalByMod`、`batchStatusByMod`、`setModuleNominal(mod)`
- [x] `index.html`：外層 `v-for mod in activeModules`，每模組獨立標題列 + 批次列 + 表格
- [x] 全域批次列保留（套用至全部通道）
- [x] 通道編號改用 `CH{{ ch.channel }}`（模組內序號）
- [x] `style.css`：新增 `.mod-batch-bar` 樣式

---

##### 4.3.5 通道設定頁 nominal_readonly 主動探測（2 通道模組反灰 + 說明）

> **背景**：CAPAROC 2 通道斷路器模組的額定電流無法透過 EIP CIP 遠端設定（Config Assembly / Parameter Object 寫入均被靜默忽略），需在 UI 明確標示並禁用輸入。  
> **設計**：連線後自動探測每個模組是否支援 CIP nominal 寫入，結果記錄為 `nominal_readonly` 欄位隨 WebSocket 推送到前端。  
> **預估工時**：2-3 小時

**實作步驟**：

**Step 1 — `src/caparoc_backend.py`**
- [ ] `__init__` 新增 `self._nominal_readonly_modules: set[int] = set()`
- [ ] 新增 `_probe_nominal_writable(module: int) -> bool`：
  1. 讀取 module 第一個實體通道的目前 nominal（Input Assembly）
  2. 透過 Class 0x0F Parameter Object 寫入 nominal ± 1（probe 值）
  3. 等 0.8 秒
  4. 讀回 Input Assembly 驗證；若已改變 → 可寫（True），立即還原原值
  5. 若未改變 → read-only（False），不需還原
- [ ] 新增 `_probe_all_modules()`：對 module 1..module_count 逐一呼叫，失敗的加入 `_nominal_readonly_modules`，並寫入 log
- [ ] `connect()` 成功後呼叫 `_probe_all_modules()`
- [ ] 新增 `is_module_nominal_readonly(module: int) -> bool`（查 set）

**Step 2 — `web/app.py`**
- [ ] `_format_status()` 每個 channel 物件加入：`"nominal_readonly": backend.is_module_nominal_readonly(ch["module"])`

**Step 3 — `web/static/js/app.js`**
- [ ] 移除 `length < 4` 判斷邏輯（如有）
- [ ] 新增 `isModNominalReadOnly(mod)` function：`return channelsByModule.value[mod]?.[0]?.nominal_readonly ?? false`
- [ ] `setAllNominal` 加 filter：只對 `!isModNominalReadOnly(ch.module)` 的通道呼叫 API
- [ ] `return {}` 加入 `isModNominalReadOnly`

**Step 4 — `web/templates/index.html`**
- [ ] 模組標題列加說明 badge：`v-if="isModNominalReadOnly(mod)"` 顯示「⚙ 額定電流需手動設定（旋鈕）」
- [ ] 模組批次列 input + button：`:disabled` 加入 `|| isModNominalReadOnly(mod)`
- [ ] 通道表格每列 input + button：`:disabled` 加入 `|| isModNominalReadOnly(ch.module)`

**Step 5 — `web/static/css/style.css`**
- [ ] 新增 `.mod-readonly-badge` 樣式：小字灰色標籤（不影響現有版型）

**預估工時**：2-3 小時

---

##### 4.3.3 視覺一致性與元件統一化

> **目的**：統一按鈕、表格、卡片、提示訊息等 UI 元件的外觀語言

**工作項目**：
- [ ] 統一按鈕樣式（primary / secondary / danger 三種語義色彩）
- [ ] 狀態指示色彩系統（正常/警告/錯誤/離線 四種語義）
- [ ] 通道卡片尺寸與間距一致化
- [ ] 頁面載入骨架屏（loading skeleton）取代空白閃爍

**預估工時**：2-3 小時

---

##### 4.3.4 行動裝置基本支援

> **目的**：讓 Web UI 在平板/手機瀏覽器可操作（能顯示與操作即可，不要求完美）

**工作項目**：
- [ ] Sidebar 在窄螢幕自動收合（☰ 按鈕機制驗證）
- [ ] 通道卡片在小螢幕改為單欄佈局
- [ ] 按鈕點擊區域符合觸控規範（最小 44px）

**預估工時**：1-2 小時

---

#### 4.4 CLI 介面功能完善

> **目標**：補齊後端已有但 CLI 尚未實作的功能，使 CLI 與 Web UI 功能對等  
> **後端現況**：`get_device_info()`、`get_network_info()` 已在 `caparoc_backend.py` 實作，CLI 尚未新增對應指令。

---

##### 4.4.1 通道詳細狀態顯示

> **對應後端**：擴充 `show_status()` / 新增 `show_channel_detail(ch)` 方法  
> **預估工時**：2-3 小時

**工作項目**：
- [ ] 擴充 `show_status()` 顯示電流使用率（Flowing / Nominal × 100%）
- [ ] 新增 CLI 指令 `s <ch>`：呼叫 `show_channel_detail(ch)` 顯示單一通道詳細資訊
  - 狀態、實際電流、額定電流、使用率
  - 狀態位元完整解析（bit 0-5：On/Off、80%警告、過載、短路、硬體故障、總電流關斷）

**顯示範例**：
```
🎮 > s 1

📊 CH1 詳細狀態:
   ────────────────────────────────────
   狀態:         🟢 開啟
   實際電流:     2.50 A
   額定電流:     4.00 A
   使用率:       62.5% ✅
   ────────────────────────────────────
   警告/錯誤:    ⚠️  接近 80% 警告閾值 (3.2A)
   ────────────────────────────────────
```

---

##### 4.4.2 設備識別資訊指令

> **對應後端**：`get_device_info()`（Identity Object + Class 0x0F）  
> **預估工時**：0.5 小時（後端已完成，只需加 CLI 指令）

**工作項目**：
- [ ] 新增 CLI 指令 `device info`：呼叫 `get_device_info()`
  - 顯示廠商、型號、產品代碼、修訂版本、序號
  - 顯示全域設定：param_lock / ui_lock / 啟動延遲 / 操作模式

---

##### 4.4.3 網路資訊指令

> **對應後端**：`get_network_info()`（CIP 0xF5/0xF6）  
> **預估工時**：0.5 小時（後端已完成，只需加 CLI 指令）

**工作項目**：
- [ ] 新增 CLI 指令 `network info`：呼叫 `get_network_info()`
  - 顯示 IP、子網路遮罩、預設閘道、MAC 位址、主機名稱

---
#### 4.3.6 通道自訂標籤（設備名稱）🆕

> **目的**：讓使用者為每個通道輸入自訂名稱（例如「主機電源」、「照明迴路」），存檔於本機，下次連線同一台裝置自動載入。  
> **識別方式**：用 PM EIP 的 Serial Number 作為 key，確保標籤綁定到正確的物理裝置。  
> **預估工時**：2-3 對時

**實作步驟**：

**Step 1 — `config/channel_labels.json`**
- [ ] 建立標籤儲存檔，結構：`{ "devices": { "<serial>": { "device_label": "", "channels": { "1": "", "2": "" } } } }`
- [ ] 建立 `channel_labels.json.example`（空模板）

**Step 2 — `web/app.py`**
- [ ] 啟動時讀取 `channel_labels.json`
- [ ] `GET /api/labels`：回傳目前連線裝置的標籤（依 Serial Number 查表）
- [ ] `POST /api/labels/{channel_id}`：寫入對應標籤並存檔
- [ ] `_format_status()`：每個 channel 加入 `"label": str` 欄位
- [ ] 連線成功後依 S/N 自動載入標籤

**Step 3 — `app.js`**
- [ ] `channelLabels = reactive({})` 儲存 `{ch_id: label}`
- [ ] `fetchLabels()` 對應 `/api/labels`，連線後呼叫
- [ ] `saveLabel(chId, text)` 對應 `POST /api/labels/{chId}`
- [ ] `return {}` 加入 `channelLabels`、`saveLabel`

**Step 4 — `index.html`**
- [ ] 儀表板通道卡片：CH 編號下方加可變輸入框（點擊即可編輯，`@blur` 再儲存）
- [ ] 通道設定頁：新增「設備名稱」欄（inline 可編輯）

**Step 5 — `style.css`**
- [ ] 新增 `.ch-label` 樣式（卡片內小字標籤輸入框）

**預估工時**：2-3 對時

---
#### 4.5 數據記錄與分析功能 🆕

**目標**: 記錄設備運行數據，提供歷史分析

**功能需求**:
- [ ] 數據記錄功能:
  - 通道開關事件記錄
  - 電流變化記錄
  - 系統狀態變化記錄
  - 警告/錯誤事件記錄
- [ ] 數據存儲:
  - SQLite 資料庫
  - CSV 匯出功能
  - 自動清理舊數據
- [ ] 數據分析:
  - 通道使用率統計
  - 電流趨勢分析
  - 異常事件統計
  - 運行時間統計
- [ ] 報表生成:
  - 日報/週報/月報
  - PDF 匯出
  - 可視化圖表

**預估工時**: 6-8 小時

---

#### 4.6 告警與通知系統 🆕

**目標**: 主動通知異常狀態，提升系統可靠性

**功能需求**:
- [ ] 告警規則配置:
  - 電流閾值告警
  - 電壓異常告警
  - 通道故障告警
  - 自定義告警規則
- [ ] 通知方式:
  - Email 通知
  - 系統通知 (Windows Toast)
  - 日誌記錄
  - 聲音提示 (可選)
- [ ] 告警管理:
  - 告警歷史查詢
  - 告警確認機制
  - 告警靜默設定

**預估工時**: 4-5 小時

---

#### 4.7 多設備管理 🆕

**目標**: 同時管理多台 CAPAROC 設備

**功能需求**:
- [ ] 設備配置管理:
  - 多設備配置文件
  - 設備分組功能
  - 設備別名設定
- [ ] 批次操作:
  - 批次通道控制
  - 批次狀態查詢
  - 批次監控啟動
- [ ] 設備切換:
  - 快速切換控制對象
  - 多設備狀態總覽
  - 設備連接狀態監控

**預估工時**: 5-6 小時

---

#### 4.8 自動化測試與 CI/CD 🆕

**目標**: 提升程式碼品質，自動化測試流程

**功能需求**:
- [ ] 單元測試:
  - 核心功能測試覆蓋
  - Mock 設備通訊
  - pytest 測試框架
- [ ] 整合測試:
  - 端到端流程測試
  - 多模組測試場景
- [ ] CI/CD 流程:
  - GitHub Actions 配置
  - 自動化測試執行
  - 程式碼品質檢查 (pylint, black)
- [ ] 文件自動化:
  - API 文件生成
  - 使用手冊更新

**預估工時**: 8-10 小時

---

### Phase 5: 打包與部署 📦

> **目標**：將程式打包為可直接執行的形式（Windows .exe / Linux Docker），方便無 Python 環境的使用者部署  
> **前置條件**：Phase 4.3.1 config 合併完成

---

#### 5.1 路徑抽象化（打包前置）

> **目的**：統一所有路徑解析邏輯，使程式在開發環境與 PyInstaller frozen 環境都能正確找到 config / logs / web 資源  
> **預估工時**：1–1.5 小時

**問題**：目前各模組用 `Path(__file__).parent` 定位目錄，打包後 `__file__` 指向暫存解壓路徑（`sys._MEIPASS`），  
config 和 logs 必須在 exe 旁邊（使用者可編輯），不能被打包進去。

**工作項目**：
- [ ] 建立 `src/paths.py`：統一定義 `ROOT_DIR` / `CONFIG_DIR` / `LOG_DIR` / `WEB_DIR`
  - 開發模式：`Path(__file__).resolve().parent.parent`
  - Frozen 模式：`Path(sys.executable).parent`（exe 同層）
  - 內嵌資源：`Path(sys._MEIPASS)` / `"web"`（templates + static）
- [ ] `web/app.py`：`_WEB_DIR`、`_ROOT_DIR` 改為引用 `paths.py`
- [ ] `src/logging_manager.py`：log 目錄改為引用 `paths.py`
- [ ] `src/caparoc_backend.py` / `caparoc_controller.py`：config 路徑改為引用 `paths.py`

---

#### 5.2 CDN 資源離線化

> **目的**：讓 Web UI 在無網路環境（工廠內網）也能正常載入  
> **預估工時**：0.5 小時

**目前 CDN 依賴**：
- Vue 3（`unpkg.com/vue@3`）
- Chart.js 4.4.6（`cdn.jsdelivr.net/npm/chart.js`）
- chartjs-plugin-zoom（`cdn.jsdelivr.net`）
- Hammer.js（`cdn.jsdelivr.net`）

**工作項目**：
- [ ] 下載上述 JS 檔案到 `web/static/vendor/`
- [ ] `index.html` 的 `<script src>` 改為 `/static/vendor/xxx.min.js`
- [ ] 驗證離線環境正常運作

---

#### 5.3 PyInstaller 打包（Windows .exe）

> **目的**：產出單一 `caparoc.exe`，雙擊即啟動 Web UI + 自動開瀏覽器  
> **預估工時**：2–3 小時

**工作項目**：
- [ ] 建立 `build/caparoc.spec`（PyInstaller spec file）
- [ ] 主入口：`web/app.py`
- [ ] `--add-data`：收入 `web/templates`、`web/static`（含 vendor/）
- [ ] `--hidden-import`：`uvicorn.logging`、`uvicorn.lifespan.on`、`uvicorn.protocols.http.auto`、`websockets`、`pycomm3`
- [ ] 排除不需打包的目錄：`tests/`、`docs/`、`archive/`、`logs/`
- [ ] 測試：打包後 exe 可正常啟動、連線設備、操作所有頁面
- [ ] 可選：第二入口 `caparoc_cli.exe`（打包 `caparoc_controller.py`）

**產出目錄結構**：
```
dist/
  caparoc.exe          ← 主程式（Web UI）
  config/
    config.json        ← 使用者可編輯設定
  logs/                ← 執行時產生
```

---

#### 5.4 首次執行初始化

> **目的**：exe 首次執行時自動建立必要的外部目錄與檔案  
> **預估工時**：0.5 小時

**工作項目**：
- [ ] exe 旁無 `config/` → 自動從內嵌 `config.example.json` 複製為 `config/config.json`
- [ ] exe 旁無 `logs/` → 自動建立目錄
- [ ] 啟動時 console 印出路徑資訊（方便使用者找到 config 位置）

---

#### 5.5 Linux 部署方案

> **目的**：提供 Linux 環境的部署選項（工廠 server / 嵌入式設備）  
> **預估工時**：1–2 小時

**方案：Docker**（推薦）
- [ ] 建立 `Dockerfile`（`python:3.12-slim` + pip install + COPY src/web/config）
- [ ] 建立 `docker-compose.yml`（port mapping、volume mount config/ 和 logs/）
- [ ] 文件：`docs/DEPLOYMENT.md` 部署說明

**用法**：
```bash
docker compose up -d
# 瀏覽器開啟 http://<server-ip>:8000
```

**備選方案**：
- PyInstaller 在 Linux 上打包（需 Linux CI 環境）
- systemd service（直接 pip install + `systemctl start caparoc`）

---

#### 5.6 版本號管理

> **目的**：單一來源版本號，打包時自動嵌入，UI 可顯示  
> **預估工時**：0.5 小時

**工作項目**：
- [ ] 建立 `src/version.py`：`__version__ = "4.x.x"`
- [ ] 打包時嵌入 git commit hash（短 hash）
- [ ] Web UI 系統狀態頁顯示版本號
- [ ] `--version` 命令列參數支援

---

**Phase 5 預估總工時**：6–8 小時

---

### Phase 6: 企業級功能 (未來規劃) 💡

#### 6.1 遠端訪問與控制
- [ ] Web API 介面 (RESTful)
- [ ] WebSocket 即時通訊
- [ ] 遠端監控網頁
- [ ] 身份驗證與權限管理

#### 6.2 高可用性設計
- [ ] 斷線自動重連優化
- [ ] 狀態持久化
- [ ] 故障轉移機制
- [ ] 負載均衡支援

#### 6.3 大數據與 AI 分析
- [ ] 時序數據庫整合 (InfluxDB)
- [ ] 異常模式識別 (機器學習)
- [ ] 預測性維護建議
- [ ] 能耗優化建議

---

## 📊 開發里程碑

**Phase 3 已完成** ✅ (2025-10-27 - 2025-11-26)
- CLI 完整功能實現（v3.1–v3.7）：額定電流設定、通道開關控制、狀態查詢、即時監控
- 多模組支援（自動偵測 1-16 模組，最多 64 通道）
- 心跳機制、自動重連、完整錯誤處理
- **Phase 3 總工時**：~20 小時

**Phase 3.5–3.6 已完成** ✅ (2026-04-02 - 2026-05-14)
- 前後端分離架構重構（`CaparocBackend` + `CaparocController` 繼承，controller 縮減 -63%）
- Log 系統建立（`logging_manager.py` + `config/logging_config.json`）
- 連線 IP 管理（`device_config.json` 持久化、`setting` 選單四選項重設計）
- 告警事件寫入 log（短路/過載/80%警告/電壓異常）
- **Phase 3.5–3.6 累計工時**：~10 小時

**Phase 4.0–4.2 已完成** ✅ (2026-05-15 - 2026-05-25)
- Web 服務骨架：FastAPI + Vue 3 CDN + WebSocket 每秒推送
- 6 個 Web UI 頁面：儀表板 / 通道設定 / 圖表監控 / 系統日誌 / 系統狀態 / 連線設定
- 圖表：Chart.js 4.4.6，每模組獨立折線圖，chartjs-plugin-zoom 拖曳/滾輪縮放，後端 30 分鐘歷史 buffer
- 設備識別（CIP Identity Object）+ 網路資訊（CIP 0xF5/0xF6）
- Bug fixes：CIP 並發斷線（`_cip_lock`）、IP 倒序顯示（LE UDINT）、拔線後重連失敗
- **Phase 4.0–4.2 累計工時**：~15 小時

---

**Phase 4 進行中** 🚀

| 優先級 | 任務 | 預估工時 |
|--------|------|---------|
| 高 | 4.3.1 設定值外部化（config 合併） | 1h |
| 高 | **4.3.5 nominal_readonly 主動探測（2 通道模組反灰）** | **2-3h** |
| 高 | **4.3.6 通道自訂標籤（設備名稱）** | **2-3h** |
| 高 | **4.3.6 通道自訂標籤（設備名稱）** | **2-3h** |
| 高 | 4.4.1 CLI 通道詳細狀態顯示 | 2-3h |
| 中 | 4.3.3 UI 視覺一致性與元件統一 | 2-3h |
| 中 | 4.4.2/4.4.3 CLI 設備/網路資訊指令 | 1h |
| 中 | 4.5 數據記錄與分析 | 6-8h |
| 中 | 4.6 告警與通知系統 | 4-5h |
| 低 | 4.7 多設備管理 | 5-6h |
| 低 | 4.8 自動化測試與 CI/CD | 8-10h |

**Phase 4 預估剩餘工時**：29-41 小時

---

**Phase 5 打包與部署** 📦

| 優先級 | 任務 | 預估工時 |
|--------|------|---------|
| 高 | 5.1 路徑抽象化（打包前置） | 1-1.5h |
| 高 | 5.2 CDN 資源離線化 | 0.5h |
| 高 | 5.3 PyInstaller 打包（Windows .exe） | 2-3h |
| 中 | 5.4 首次執行初始化 | 0.5h |
| 中 | 5.5 Linux 部署方案（Docker） | 1-2h |
| 低 | 5.6 版本號管理 | 0.5h |

**Phase 5 預估工時**：6-8 小時

---

**Phase 6 未來願景** 💭
- 企業級遠端管理
- 高可用性部署
- AI 智能分析

---

## 📈 專案統計

**已投入工時**：
- Phase 1-2：~12 小時
- Phase 3：~20 小時
- Phase 3.5-3.6：~10 小時
- Phase 4.0-4.2：~15 小時
- **總計**：~57 小時

**程式碼統計**（截至 2026-05-25）：
- `src/caparoc_backend.py`：~750 行
- `src/caparoc_controller.py`：~874 行
- `web/app.py`：~550 行
- `web/static/js/app.js`：~900 行
- `web/templates/index.html`：~600 行
- 文件：20+ 份

---


