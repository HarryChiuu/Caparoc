# CAPAROC 控制器 - 待實作功能清單

更新日期: 2026-09-04

---

## 🎯 目前的工作佇列

> 本節是**唯一需要先讀的地方**——底下 1600 行是歷史記錄與設計決策，
> 要動手時才往下翻。每次收掉項目請同步更新這裡。

### 下一步（建議順序）

| # | 任務 | 工時 | 章節 |
|---|------|------|------|
| 1 | 4.3.6 通道自訂標籤（Serial Number 綁定，5 個 Step 全未動） | 2-3h | 4.3.6 |
| 2 | 4.4.1 CLI 通道詳細狀態顯示（`s <ch>`、使用率、bit 0-5 解析） | 2-3h | 4.4.1 |
| 3 | 5.3 PyInstaller 打包（前置 5.1 **已完成**） | 2-3h | Phase 5.3 |

~~5.1 路徑抽象化~~ ✅ **已完成（2026-09-04）**——`src/paths.py` 已建立並接上全部
呼叫端，5.3 的前置解除。

> **2026-09-04 清障已完成**（詳見「已完成功能」章節）：測試套件先前因
> `tests/test_network_info.py` 在 import 期間連線實機而**整套 collection error**，
> 25 個測試一個都跑不到；四支互動式工具已移入 `tests/manual/` 並加上 `pytest.ini`，
> 債 #11（`?v=` 版號）與 5.6 版本號管理一併收掉，隨後 5.1 路徑抽象化也已完成。
> 現在 `python -m pytest` 為 **37 passed**。

**5.1 已收掉**（原本排第一的理由：它是 Phase 5 全部項目的前置，且愈晚做愈多新程式碼
會沿用錯誤寫法）。實作時另外發現 TODO 原盤點表**漏列一處**：`web/app.py` 的
`_preload_log_file()` 硬編 `_ROOT_DIR / "logs"`，不但打包後會壞，在開發模式下就已經是
潛伏 bug——使用者一改 `logging.log_dir`，Web 系統日誌頁就靜默空白。已一併修正。

### 中優先（無相依，可插隊）

- 4.3.3 UI 視覺一致性（2-3h）／ 4.3.4 行動裝置支援（1-2h）
- 4.5 數據記錄與分析（6-8h）— ⚠️ 要與已接上的 log 保留機制**共用**清理策略，別長第二套
- 4.6 告警與通知系統（4-5h）
- 5.4 首次執行初始化（0.5h）／ 5.5 Docker（1-2h）　※ 5.6 版本號管理已完成（2026-09-04）

### 低優先

4.7 多設備管理（5-6h）／ 4.8 CI/CD（8-10h）／ Phase 6 企業級功能

### 🧾 零散技術債（無專屬章節，容易被遺忘）

| 債務 | 症狀 | 出處 |
|------|------|------|
| `app.js` 單一 `setup()` 約 870 行 | 全案最大長期債 | 債 #8（**刻意不償還**，需引入 build step） |
| `arp -a` 依賴語系文字（`動態`/`dynamic`） | 非 zh-TW／英文語系找不到項目 | 問題 #6（已知限制） |
| `get_broadcast_addresses()` 硬編 `.255`（假設 /24） | 非 /24 網段廣播位址算錯；多網卡可能漏掉 | 問題 #7（已知限制） |
| `set_device_dhcp()` 任何例外都回 `success=True` | 真失敗與預期斷線無法區分 | 問題 #5（**刻意不改**，真相來源是事後驗證步驟） |
| 每個新端點都要手寫 `_DEMO_MODE` 分支 | 漏寫 → `--demo` 靜默壞掉 | 債 #10（status payload 已有測試把關，其他端點仍人工） |
| 選配：`tests/test_ip_core.py` | 純函式安全網，約 30 行，成本極低。**套件現已可正常執行（28 passed），補測試的成本更低了** | 建議項 |
| `environment.yml` 的環境名 `caparoc_breaker` 與實際使用的 `sv` 不符 | 已在 yml 與 README 註明，但兩者長期並存仍易混淆 | 2026-09-04 記錄 |

---

## ✅ 已完成功能

### Phase 5.1 路徑抽象化（2026-09-04）
- [x] **建立 `src/paths.py`**：`RESOURCE_DIR`／`DATA_DIR`／`CONFIG_DIR`／`LOG_DIR`／`WEB_DIR`
  - 關鍵區分：**內嵌資源**（`sys._MEIPASS`，唯讀）與**外部資料**（`sys.executable` 旁，可讀寫）
    用兩個不同的 base，方向相反，不可共用
  - `resolve_data_dir()` 供設定檔的目錄值解析（相對以 `DATA_DIR` 為基準）
- [x] `src/app_config.py`：`CONFIG_DIR` 改為引用（影響最大，優先做）
- [x] `src/logging_manager.py`：`_resolve_log_dir()` 改為引用（`_setup_logger` 與
      `cleanup_old_logs` 共用同一份，前一次 commit 已統一）
- [x] `src/caparoc_backend.py`：`_PROBE_CACHE_PATH` 改為引用
- [x] `web/app.py`：`WEB_DIR`（內嵌）與 `LOG_DIR`（外部）**分開處理**
- [x] `src/caparoc_controller.py`：確認已透過 `app_config` 取得路徑，無需改動
- [x] **額外修正**：`_preload_log_file()` 原硬編 `"logs"`，改為依 `logging.log_dir` 解析
- [x] `tests/test_paths.py`（9 項）：**模擬 frozen 環境**驗證兩種路徑方向，
      已用反向注入確認能抓到「外部資料誤用 `_MEIPASS`」這個典型錯誤

### 測試套件修復 + 前端版號單一真相來源（2026-09-04）
- [x] **測試套件從 collection error 修回可用**（28 passed in 0.76s）
  - [x] 四支互動式／需實機的工具由 `test_*.py` 改名移入 `tests/manual/`（`git mv`，history 保留）
  - [x] 移深一層後的 `sys.path` 深度修正（`resolve().parent.parent.parent`）
  - [x] 新增 `pytest.ini`：`testpaths` + `norecursedirs`，防止同類問題再發生
  - 根因：`test_network_info.py` 在 module 頂層 `with CIPDriver(IP)` 連線實機，
    沒有設備時 pytest 收集階段即中止，**另外 25 個測試一個都跑不到**
- [x] **債 #11 / 5.6 版本號管理**：`src/version.py` 成為唯一真相來源
  - [x] `index.html` 兩處 app 資源改用 `{{ app_version }}`（vendor 函式庫版號維持寫死）
  - [x] `web/app.py` `_render_index()` 啟動時替換一次；回應型別 `FileResponse` → `HTMLResponse`
  - [x] `tests/test_asset_version.py`（3 項），已用反向驗證確認能抓到漏改
- [x] **環境文件對齊實際**：README／USER_GUIDE 的 `your_env_name` → `sv`；
      `environment.yml` 補名稱說明並把 `pytest` 提升為正式相依
- [x] **TODO 債務表清理**：BOOTP `op`（問題 #4）確認已由 `dhcp_msg_type()` 解決並移除

詳見 [CHANGELOG.md](CHANGELOG.md) 的 2026-09-04 條目。

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

## 🔤 主控台編碼防護 ✅ 已完成（2026-09-03）

> **起因**：上一節的真機驗證途中撞到——設備 ping 通、`CaparocBackend` 直連也成功，
> 但 `python web/app.py > run.log` 啟動時 `connect()` 回報失敗，log 只留一行
> `connect() 例外: 'cp950' codec can't encode character '❌'`。
> 使用者看到的是「連不上設備」，設備其實好好的。

### 根因

本專案有 **400+ 處帶 emoji 的 `print()`**：

| 檔案 | 數量 |
|---|---|
| `src/caparoc_controller.py` | 211 |
| `src/caparoc_backend.py` | 101 |
| `src/caparoc_ip_config.py` | 81 |
| 其餘（`web/app.py`、`app_config.py`、`logging_manager.py`、`caparoc_ip_core.py`） | 14 |

- Windows **真實主控台**在 Python 3.6+ 走 Unicode API（PEP 528），emoji 印得出來
  ——**所以平常手動執行永遠不會發現**。
- stdout 一旦**被導向檔案或 pipe**（打包 exe 由排程／服務啟動、`> run.log`、
  被其他程式包起來執行），編碼退回地區編碼，繁中 Windows = **cp950**，
  裝不下任何 emoji。

⚠️ **致命的不是印不出來，而是這些 print 多半在 `try` 內**：`UnicodeEncodeError`
被外層 `except Exception` 當成「操作失敗」吞掉。`connect()` 印到
`✅ CIP 連線已建立` 那一行就炸，於是設備完全正常卻回報連不上。

### 完成項目

- [x] `src/console_io.py`：`force_safe_stdio()`，把 stdout/stderr 的 `errors`
      改成 `replace`，裝不下的字元退化成 `?`
- [x] 三個進入點在**任何輸出之前**呼叫：`web/app.py`、`src/caparoc_controller.py`、
      `src/caparoc_ip_config.py`
- [x] `tests/test_console_encoding.py`（5 項，不需設備與網路）

### ⚠️ 刻意只改 `errors`、不改 `encoding`

改成 UTF-8 會讓 cp950 主控台的**中文**變亂碼。為了救裝飾用的 emoji 去弄壞
真正重要的訊息，是賠本生意。`test_cjk_still_readable_after_protection` 釘住這件事。

### 真機驗證（同一台設備、同一時間，只差有沒有掛防護）

| | `connect()` | stdout |
|---|---|---|
| 修復前 | `False` | 印到 `[CIP 連線] 正在建立…` 就中斷 |
| 修復後 | `True`（讀得到 `CAPAROC PM EIP`） | `? CIP 連線已建立 (WEB UI 應顯示 'connected')` — emoji 退化成 `?`，**中文完好** |

`PYTHONIOENCODING=cp950` 下以 uvicorn 啟動 Web 服務同樣正常連線。

### 📌 與 Phase 5 打包的關係

打包成 exe 後由排程／服務啟動時**沒有真實主控台**，正是本 bug 必然觸發的情境。
Phase 5.1 動路徑抽象化時**不要移除**進入點的 `force_safe_stdio()` 呼叫，
`test_entry_points_call_force_safe_stdio` 會擋。

### 未來項目（低優先）

- [ ] 考慮把 400+ 處 emoji `print()` 收斂到 logging——目前 CLI 的使用者回饋與
      log 記錄混在同一組 `print`，兩者需求不同（前者要好看，後者要可 grep）。
      成本高、收益中，防護已經擋掉致命面，不急。

---

## 🔌 Web 連線設定頁：最近連線 IP 下拉 + 頁內掃描 ✅ 已完成（2026-09-03）

> **起因**：現場每次要連設備都得手動 key 一次 IP。而且 Web 連線成功後**不會**
> 把 IP 寫回設定檔（只有 CLI 的 `setting [3]` 會），連過的位址下次一樣要重打。

### 兩條路互補，缺一不可

| 情境 | 解法 |
|---|---|
| 連過的設備要再連一次 | 連線設定頁 IP 欄改為**可輸入的下拉**，列出最近成功連線過的設備 |
| 第一次接觸的設備，手邊沒有 IP | 把既有的**網段掃描**搬一份到連線設定頁，掃到直接一鍵連線 |

歷史清單只解決前者。真正的「零輸入」是後者——掃描 API（`POST /api/ipconfig/discover`）
早就寫好了，只是入口埋在「IP 設定」頁。兩頁共用同一份掃描狀態，掃過一次兩邊都看得到。

### 完成項目

- [x] `src/app_config.py`：`device.recent` / `device.recent_max`（預設 5）
  - [x] `record_connection(ip, name, serial)`：移到最前 + 更新時間 + 同步 `default_ip`
  - [x] `recent_devices()` / `forget_device_ip(ip)` / `recent_max()`
  - [x] `_sanitize_recent()`：吸收手改壞的設定檔（塞字串、缺 `ip`、重複、非法 IP）
  - [x] 抽出 `_write_config()`，三條寫入路徑共用 read-modify-write
- [x] `web/app.py`：`_remember_connection()`、`GET/DELETE /api/connect/recent`
- [x] 前端：`.ip-picker` 自繪下拉（IP + 設備名/序號 + 相對時間 + 單筆刪除）、頁內掃描區塊
- [x] `config/config.example.json`、`WEB_UI_FEATURE_REFERENCE.md`、`CHANGELOG.md`

### 📌 設計決策：清單存後端 `config.json`，**不是** localStorage

- 現場換一台筆電、換瀏覽器、清快取都不該讓清單消失——這是**設備資產**，不是瀏覽器偏好
- `default_ip` 本來就住在 `device` 區塊，兩者放一起才不會各記各的
- 打包成 exe 後跟著 `config/` 一起走

### ⚠️ 刻意的行為（改動前先讀）

| 行為 | 為什麼 |
|---|---|
| **只在連線成功後**寫入清單 | 打錯的位址進了清單只會變成下次的干擾項——那正是這功能要省掉的麻煩 |
| 寫入時**一併更新 `default_ip`** | 順帶補掉「Web 連線後不記得 IP」這個既有缺口 |
| 設備名／序號讀取**整段包在 try 內** | 那只是顯示用標籤，不能因為它讓連線流程失敗。讀不到就留 `null` |
| `DELETE` **不動 `default_ip`** | 「這台不想再出現在下拉」與「換開機預設值」是兩件事 |
| 選取只填入、**不自動連線** | 已連線時換 IP 需先斷線，靜靜幫使用者做會很意外 |
| 刪除鈕常駐但淡化（`opacity: 0.45`） | 藏到 hover 才出現的話，觸控裝置永遠點不到 |

### ⚠️ 踩到的坑：全域 `button:hover` 蓋掉下拉項目

`style.css` 的 `button:hover { background: var(--btn-bg-hover) }` 特異性 (0,1,1)
蓋過 `.ip-picker-item` 的 (0,1,0)，hover 時整列會變成藍色按鈕底、字幾乎看不見。
補 `.ip-picker-item:hover { background: none }` 才讓 `li:hover` 的淡色 highlight 透出來。

> **通則**：這份 CSS 有 `button`／`.btn` 的**裸元素**規則，任何「長得不像按鈕的
> `<button>`」（下拉項目、圖示鈕、卡片）都要記得覆蓋 `:hover`，光蓋 base 狀態不夠。

---

## 🔧 caparoc_ip_config.py 改善項目 ✅ 已完成（2026-08-13）

> 本節記錄對 `src/caparoc_ip_config.py` 的改善項目，比對 `tests/manual/dcp_ip_config_tool.py`（DCP/DHCP 實驗工具）後確認並實作。

### 已完成項目

| # | 優先 | 說明 |
|---|---|---|
| 1 | 低 | **Typo 修正**：`run_discovery()` 輸出 `廣播0：` → `廣播：`（程式碼中已無此 typo，僅 TODO 記錄未勾）✅ |
| 2 | 高 | **Server IP 選擇**：新增 `_pick_iface()`（移植自 manual/dcp_ip_config_tool.py），列出可用網卡含 MAC/IP 讓使用者選擇，取代不可靠的 `gethostbyname()` ✅ |
| 3 | 高 | **固化完整寫入**：`_provision_new_device()` 改呼叫 `backend.set_device_ip(driver, assign_ip, subnet, gateway)`，DHCP ACK 後正確寫入 Attr5（IP/Subnet/GW）+ Attr3（Static），不再只寫 Attr3 ✅ |
| 4 | 中 | **從主連線迴圈獨立**：新增頂層選單 [1]連線設備 / [2]新裝置初始設定，`_provision_new_device()` 不再掛在已連線設備的選單下 ✅ |
| 5 | 低 | **前置說明**：`_provision_new_device()` 開頭顯示前提條件（其他 DHCP/BOOTP 工具已關閉）✅ |
| 6 | 中 | **自動 MAC 偵測**：新增 `_listen_dhcp_discover()`（移植自 manual/dcp_ip_config_tool.py，UDP port 67 → Raw Socket 混雜模式 → scapy sniff 三層 fallback），新裝置設定時可自動監聽 DHCP Discover 取得 MAC，不需手動輸入 ✅ |

**未搬入的功能**：PROFINET DCP Layer 2 Identify/Set IP（manual/dcp_ip_config_tool.py 選項 [1]-[3]）— 程式註解確認對此設備硬體無效，故意不整合。

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

**✅ 實機驗證通過（2026-09-01）**：除 mock driver 測試與 `--demo` 模式 API smoke test 外，
已接實機確認三條路徑——批次設定額定電流、連線時的探測快取命中、通道開關——行為皆符合預期，無需追加修正。

---

---

---

## 🚑 Web DHCP 失聯救援 ✅ 已完成（2026-08-28，分支 fix/web-cip-concurrency）

> 使用者回報「切換成 DHCP 以後，掃描網段還是找不到 MAC」。查明後發現不是顯示問題——
> 設備切成 DHCP 但網段無 DHCP server 時整台掃不到（無 IP → 無 EIP 回應、不進 ARP 表）。
> 唯一能發現它的方法是監聽 UDP/67 的 DHCP Discover，這正是 CLI 有、web 沒有的能力。

| 項目 | 內容 |
|---|---|
| 新端點 | `POST /api/ipconfig/detect-mac`（監聽 DHCP Discover 取得 MAC）、`POST /api/ipconfig/assign`（指派 IP + 固化靜態 + 重連） |
| core 下沉 | `open_dhcp_socket` / `detect_dhcp_macs` / `build_dhcp_reply` / `serve_dhcp` / `dhcp_msg_type` / `normalize_mac` / `iface_mac_for`，print 改 callback，CLI 只留薄包裝 |
| 既有 bug 修正 | DHCP 訊息型別原本誤用 BOOTP `op` 欄位判斷（`data[0]`），會把 REQUEST/RELEASE 誤判成 Discover；改為正確解析 Option 53 |
| 互斥 | 新增 `_dhcp_lock`（UDP/67 獨佔），並發時回 409 |
| 偵測逾時 | 預設 30 秒改為 **90 秒**（實測設備約每 60 秒才送一次 Discover） |
| 手動中斷 | `POST /api/ipconfig/dhcp-cancel` + core 的 `should_stop` callable；前端「✕ 中斷」鈕。**必須是伺服器端取消**——只在前端 abort fetch 的話，執行緒仍佔著 UDP/67 到逾時，使用者只會一直拿到 409 |
| 救援參數 | 救援面板提供獨立的子網路遮罩／閘道欄位，不再沿用下方面板的值 |
| 實機驗證 | 對真正失聯的設備完整走完救援：偵測到 MAC（61 秒）→ 指派 + 固化 + 重連（51 秒）→ 恢復為 192.168.50.111 / Static / 已連線 |

**至此 web 與 CLI 的 IP 設定功能已對等**：設備探索（含網卡選擇與 MAC）、讀取網路設定、
設定靜態 IP、切換 DHCP、失聯救援（迷你 DHCP server）五項齊備。

## 🔧 IP 設定頁實機測試修正 ✅ 已完成（2026-08-28，分支 fix/web-cip-concurrency）

> 使用者實機操作回報 4 項問題，全數重現並修正，細節見 `docs/CHANGELOG.md`。

| # | 問題 | 根因 | 處理 |
|---|---|---|---|
| 1 | 可以切換成 DHCP | —（本來就正常） | 無需處理 |
| 2 | 掃描不到 MAC、無法選網卡 | List Identity 回應不含 MAC；多網卡未綁定 socket 導致廣播送錯介面 | ✅ 新增 `arp_mac_map()` 補 MAC、`list_interfaces()` + `GET /api/ipconfig/interfaces`、`discover(iface_ip=)` 綁定 socket；前端加網卡下拉與 MAC 欄 |
| 3 | 靜態 IP 時頁面顯示成 DHCP | 一半是問題 4 的結果（模式真的沒切成功）；另一半是 `ipMode` 單選不反映設備實際模式 | ✅ 讀取後依 `config_control` 同步 `ipMode` |
| 4 | 無法變更靜態 IP | **`set_device_ip()` 寫入順序反了**——DHCP 模式下設備拒絕寫 Attr5（`Object state conflict`），必須先寫 Attr3 切 Static | ✅ 改為 Attr3 → Attr5；新增 `_cip_set_detail()` 分辨「CIP 拒絕」與「連線中斷」 |

### ⚠️ 實測踩到的風險：切 DHCP 會讓設備失聯

192.168.50.x 是**電腦直連網段、沒有 DHCP server**。測試時把設備切成 DHCP 後，
設備完全失聯（廣播/ARP/直接探測舊位址全無回應），最後用專案自帶的迷你 DHCP server
指派位址才救回。

- [x] UI 的 DHCP 警告已改為顯眼樣式，寫明失聯風險、救援指令與「先記下 MAC」
- [x] **把「迷你 DHCP server 救援」做進 web**（2026-08-28 完成）——
      新增 `POST /api/ipconfig/detect-mac` 與 `POST /api/ipconfig/assign`，
      前端「找不到設備？（DHCP 失聯救援）」面板。**已用它實際救回失聯的設備**
- [ ] **後續可考慮**：切 DHCP 前先偵測網段上是否存在 DHCP server（送一個 Discover 看有無 Offer），
      沒有就擋下或要求二次確認——比事後救援可靠得多

### 📌 設備行為備忘（實機實測，CAPAROC PM EIP v1.1）

| 行為 | 實測結果 |
|---|---|
| 0xF5 讀取（Attr 1/3/5） | **只接受 `connected=True`**；`connected=False` 一律回 `Too much data` |
| DHCP 模式下寫 Attr5 | 拒絕，回 `Object state conflict` |
| 寫入順序 | 必須 Attr3（模式）→ Attr5（位址） |
| 改 IP 後恢復時間 | 約 2 秒即可重新連線（`wait_for_device` 30 秒上限相當寬裕） |
| 切 DHCP 但無 DHCP server | 不會退回舊靜態 IP，直接失聯 |
| 失聯後的 DHCP Discover 間隔 | 約 **60 秒**一次（重試間隔逐次拉長）；MAC 偵測至少要等 90 秒 |
| 失聯狀態下的唯一發現方式 | 監聽 UDP/67 的 DHCP Discover（EIP 廣播與 ARP 都無效） |

### ⚠️ 踩過的坑：`is_valid_ip()` 曾被改成 `return false`（小寫）

工作區中一度出現小寫 `false`，使**所有格式驗證失敗的路徑**改拋 `NameError` → HTTP 500，
而不是預期的 422。合法輸入走 `return True` 完全正常，所以只有「使用者輸入錯誤」時才會炸——
這種只在錯誤分支發作的 bug 特別容易漏測。已修正，並全檔掃描確認無其他小寫 `true`/`false`。

- [x] **已導入 ruff（2026-09-01）**：專案根目錄新增 `ruff.toml`，規則聚焦真實缺陷
      （`E4`/`E7`/`E9`/`F`/`B`，不收風格規則、不導入 formatter），涵蓋全專案而非只有
      `caparoc_ip_core.py`。首次掃描 63 條全部修畢（無 `F821`，但揪出 `web/app.py` 重複
      import `_date`、`caparoc_ip_config.py` 11 個下沉後殘留 import 等）。細節見 CHANGELOG。

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
| 10 | 每個新端點都要手寫 `_DEMO_MODE` 分支 | 漏寫 → `--demo` 在該頁靜默壞掉，且無測試會抓到 | ~~既有慣例的固定稅，無法迴避。列入驗證清單逐項點過~~ **已部分償還（2026-09-01）**：新增 `tests/test_demo_payload.py`，自動比對 demo 與真實 payload 的欄位集合與型別，漏寫 status 欄位會被擋下（已用注入迴歸驗證）。⚠️ 僅涵蓋 **status payload**；其他端點的 `_DEMO_MODE` 分支仍是人工把關 |
| 11 | `?v=` 版號在 `index.html:8` 與 `:553` **兩處手動更新** | 漏改 → 使用者拿到舊 JS，回報「新功能沒出現」，除錯成本高 | 本次照舊手動改。未來可改由 `/` 路由注入單一版號常數——但那要把 `FileResponse` 換成模板渲染，超出本次範圍。**2026-09-03 又手動付了一次**（`4.11.0` → `4.12.0`）：這筆債每次動前端都要繳，且**沒有任何機制會提醒**——漏繳的症狀是「使用者說新功能沒出現」，最難查 |

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

##### 4.3.1 設定值外部化（config 合併）✅ **已完成（2026-09-01）**

> **目的**：將散落的多個 config 檔案合併為單一 `config/config.json`，集中管理所有可調參數  
> **實際工時**：1.5 小時（多出的 0.5 小時花在遷移機制與 `save_device_ip` 的區塊保留）

**規劃時的結構與實際不符**，已依實際程式碼修正：原規劃寫的 `logging.max_bytes` /
`backup_count` 在本專案並不存在（`logging_manager.py` 用的是 `retention_days` /
`log_dir` / `remote` 區塊）；`web.port` 預設是 **8001** 而非 8000（避開 NVIDIA Overlay）。

**實際的 `config/config.json` 結構**：見 `config/config.example.json`（含逐區塊 `_comment` 說明）。
權威來源是 `src/app_config.py` 的 `DEFAULTS`，新增可調參數時先加在那裡。

**工作項目**：
- [x] **新增 `src/app_config.py`（統一載入器）** — 規劃時沒有這一項，但三個模組各自
      開檔 parse 同一個檔案會是三份重複邏輯，且合併後 `save_device_ip()` 必須
      read-modify-write 才不會洗掉其他區塊。只依賴標準函式庫（`logging_manager`
      會 import 它，不能反向依賴）
- [x] 建立 `config/config.json`，合併 device + logging + web + nominal_current
- [x] **自動遷移**：`config.json` 不存在但舊檔存在時，開機自動合併產生，
      舊檔改名為 `.migrated` 保留（不直接刪除，遷移萬一有誤還救得回來）。
      實測 `default_ip=192.168.50.111` 正確保留
- [x] `web/app.py` 改讀 `config.json`：`default_ip` / `web.port` / `ws_push_interval`
      （原本 `asyncio.sleep(1.0)` 寫死）/ `ws_idle_shutdown`（原本 `_WS_IDLE_TIMEOUT = 10.0` 寫死）
- [x] `src/logging_manager.py` 改讀 `logging` 區塊（`config_path` 參數保留相容舊呼叫）
- [x] `src/caparoc_backend.py` 的 `_validate_nominal_args()` 改用 config 的 nominal range
- [x] 新增 `GET /api/config/limits`；`app.js` 新增 `limits` reactive + `fetchLimits()`，
      **6 處寫死的 1/20 收斂為一份**（`index.html` 三個 input 的 `min`/`max`、
      `app.js` 三處驗證合併為 `validateNominal()`）
- [x] 建立 `config/config.example.json`（含註解說明）
- [x] `.gitignore`：改為忽略 `config/config.json` 與 `config/*.migrated`，只追蹤範本
- [x] `?v=4.9.0 → 4.10.0`

**驗證**：暫時改寫 `config.json`（range 2-16、port 8123、push 2.5、idle 45）確認四項皆生效；
`save_device_ip()` 寫入後 web/logging/nominal 三個區塊完整保留；demo 模式
`/api/config/limits` 回 200、`/` 帶新版號；`ruff check .` 全過（順帶抓到重構遺留的 3 個死 import）。

**⚠️ 尚未實機驗證**：以上皆為 demo 模式與單元層級驗證。接實機後需確認 CLI 的
`setting [3] 存為預設值` 寫入 `config.json` 後重啟仍讀得到。

---

##### 4.3.1-audit 設定鍵生效範圍稽核 ✅ **已完成（2026-09-03）**

> 起因：使用者把 `retention_days` 改成 10，問「程式一啟動就會刪舊 log 嗎」。
> 逐鍵追蹤呼叫點後發現**兩個鍵是死設定**，另有一個鍵只在特定啟動方式下生效。
> 以下為實測結果（把 config 換成可辨識的測試值實跑一遍，非只讀碼）。

**實測方式**：暫時寫入 `default_ip=10.99.99.99` / `port=8765` / `ws_push_interval=3.5`
/ `ws_idle_shutdown=99` / `log_level=DEBUG` / `log_dir=logs_probe` / `retention_days=10`
/ `nominal_current=3~7`，啟動後檢查各常數與端點回應，事後還原。

| 鍵 | 實測結果 | 生效 |
|---|---|---|
| `device.default_ip` | 解析出 `10.99.99.99` | ✅ 重啟後 |
| `web.port` | 伺服器實際綁在 8765 | ⚠️ **僅限 `python web/app.py`**（見下） |
| `web.ws_push_interval` | 解析 3.5 | ✅ 重啟後 |
| `web.ws_idle_shutdown` | 解析 99.0 | ✅ 重啟後 |
| `nominal_current.min/max` | backend 常數 =(3,7)、`/api/config/limits` 回 `min:3,max:7` | ✅ 重啟後 |
| `logging.log_level` | `caparoc` logger level = DEBUG | ✅ 重啟後 |
| `logging.log_dir` | 真的建立 `logs_probe/` 並寫入當日檔 | ✅ 重啟後 |
| `logging.retention_days` | 稽核時：設 10，`logs/` 內 25 個檔（最舊 2026-05-25）**一個都沒刪** | ✅ **已修復**（見下） |
| `logging.remote.*` | `RemoteHandler.emit()` 內容是 `pass` | ❌ **無效**（已標註為未實作） |

**所有鍵都是啟動時讀入 module-level 常數，沒有熱重載**——改完必須重啟。

###### ✅ 死設定 1：`logging.retention_days` — 已接上（選項 a）

`cleanup_old_logs()`（`logging_manager.py`）原本**全 repo 沒有任何呼叫者**——
不在啟動流程、沒有排程器、CLI 與 web 都沒接。docstring 寫「手動呼叫或由排程觸發」，
但兩者都不存在。功能寫好了卻沒接上觸發點。

**完成內容**：
- [x] `web/app.py` lifespan 啟動段呼叫，**放在 `_DEMO_MODE` early return 之前**
      （log 保留策略與有沒有接設備無關），包 try/except——清不掉舊 log 不該擋住服務啟動
- [x] `logging_manager.cleanup_old_logs()` 模組層入口（呼叫端不需持有實例；尚未 `setup()` 時回空列表）
- [x] 修復 `log_dir` 相對轉絕對缺陷：抽出 `_resolve_log_dir()`，`_setup_logger()` 與
      `cleanup_old_logs()` **共用同一份解析**（原本前者有轉、後者沒有 → 從不同工作目錄
      啟動會「寫入 A 目錄、清除 B 目錄」）
- [x] `tests/test_log_retention.py`（6 項，不需設備與網路）

**🐛 修復過程中發現的第三個缺陷（原稽核未察覺）**：
`cutoff = datetime.now() - timedelta(days=N)` 帶著**當下時刻**，但檔名只有日期（零時）。
於是「剛好第 N 天」的檔案會因為**啟動時刻不同而時留時刪**——早上開服存活、晚上開服被刪。
已改為以當日零時為界，語意變成穩定的「保留最近 N 天」。測試的邊界案例釘住這件事。

**驗證**：`tests/test_log_retention.py` 6/6 通過；demo 模式實跑 lifespan，
`log_dir=logs_probe` / `retention_days=10` 下播種的 4 個檔（0/3/20/90 天）
確實只剩 0 天與 3 天兩個。真實 `logs/` 全程未被觸碰（用另開目錄測試）。

> ⚠️ **給維護者**：這是目前**唯一**的清除觸發點，而且只在 **Web 服務啟動**時執行——
> CLI 不會清。長時間不重啟 web 就不會清。

###### ✅ 死設定 2：`logging.remote.*` — 已標註為未實作（選項 b）

`RemoteHandler.emit()` 是 `pass` + 一段註解範例。`enabled: true` 也不會推送任何東西，
六個子鍵（`url` / `token` / `batch_size` / `flush_interval_sec` / `type` / `enabled`）全部無作用。

- [x] `config.example.json` 的 `_comment` 加上「🚧 尚未實作，設定無效」
- [x] README 新增「🚧 尚未實作的設定」小節

**未來若要真的實作**：骨架保留在 `logging_manager.RemoteHandler`，emit() 內有註解版範例。

###### ✅ `web.port` 只在直接執行時生效 — 已註明

`_resolve_port()` 定義在 `if __name__ == "__main__":` 之前但**只在該區塊內被呼叫**。
用 `uvicorn web.app:app --port N` 啟動時整個函式不會執行，`config.json` 的 `web.port`
被完全忽略。

- [x] `config.example.json` 的 `web._comment` 註明「僅 `python web/app.py` 適用」
- [x] README 新增「⚙️ 設定檔」小節，含兩種啟動方式的 ✅/❌ 對照與覆寫優先序表

**刻意不改行為**：把 `_resolve_port()` 搬到 module level 會讓 `uvicorn` 啟動時也去
探測／佔用埠，與 uvicorn 自己的 `--port` 打架。註明限制比讓兩套埠邏輯互搶安全。

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

##### 4.3.7 通道設定頁排版穩定化 + 白天模式對比度改善 ✅ 已完成（2026-08-31，`dfa1fa6`）

> **目的**：修「設定中…」狀態切換時整列/整表跳動的問題，並提高白天模式下文字與強調色的對比度。
> **狀態**：`style.css` / `app.js` / `index.html` 已提交於 `dfa1fa6`，並經瀏覽器實際切換主題確認。

**排版穩定化**（按鈕文字在「設定」↔「設定中…」間切換、回饋訊息出現/消失時，不應牽動版面）：
- [x] `.ch-table` 改 `table-layout: fixed`，新增 `colgroup`（`col-ch` / `col-nominal` / `col-input` 固定寬度）
- [x] 通道列操作欄改用 `.td-action`（flex row）：按鈕 `min-width` 固定，回饋訊息單行截斷（`text-overflow: ellipsis`）+ `title` 屬性顯示完整文字
- [x] `.batch-bar` / `.mod-batch-bar` 的按鈕加 `min-width`，回饋訊息同樣截斷不換行
- [x] `.batch-label`：抽出原本寫死在 `index.html` inline `style="color:#7a8aaa"` 的欄位標題樣式成獨立 class（順便修正白天模式過淡的問題）
- [x] 主內容區 `scrollbar-gutter: stable`：內容變高變矮時捲軸出現/消失不再讓置中面板左右位移

**白天模式對比度**（`--text*` / `--accent*` / `--ok` / `--err` / `--warn` / `--amber` / `--sysconf-*` / `--purple` 全數加深）：
- [x] 目標對比：`--text-dim` 以上（含）皆 ≥ 6:1，最淡的 `--text-fainter` 也有 ~4.6:1（見 `style.css` 註解）
- [x] 系統日誌各等級（debug/info/system/warning/error/critical）白天模式配色同步加深
- [x] 通道開關「開啟」狀態新增白天模式專屬配色（淺綠底、深綠字），不再沿用暗色模式配色
- [x] `app.js` 圖表主題（`_chartTheme()`）的白天模式格線/刻度/圖例顏色同步加深
- [x] `index.html` 版號 `?v=4.7.0 → 4.8.0`

**✅ 驗證與提交（2026-09-01 補記）**：
- [x] 已在瀏覽器實際切換白天/夜間模式檢查畫面，兩主題皆無對比度或跳版問題
- [x] 已提交（`dfa1fa6`）

---

##### 4.3.5 通道設定頁 nominal_readonly 主動探測（2 通道模組反灰 + 說明）✅ **已完成**（實作於 2026-08-26 前後，2026-09-01 補記）

> **背景**：CAPAROC 2 通道斷路器模組的額定電流無法透過 EIP CIP 遠端設定（Config Assembly / Parameter Object 寫入均被靜默忽略），需在 UI 明確標示並禁用輸入。  
> **設計**：連線後自動探測每個模組是否支援 CIP nominal 寫入，結果記錄為 `nominal_readonly` 欄位隨 WebSocket 推送到前端。  
> **實際狀態**：五個 Step 全數完成且**超出原計畫**（見下方「計畫外的追加」）。
> 本節先前一直未勾選，是文件落後於程式碼，非未實作。

**實作步驟**：

**Step 1 — `src/caparoc_backend.py`** ✅
- [x] `__init__` 新增 `self._nominal_readonly_modules: set = set()`（`caparoc_backend.py:61`）
- [x] `_probe_nominal_writable(module)`（`:761`）：寫入 probe 值 → 等待 → 讀回驗證 → `finally` 還原
- [x] `_probe_all_modules(force=False)`（`:864`）
- [x] `connect()` 成功後呼叫（`:327`）
- [x] `is_module_nominal_readonly(module)`（`:757`）

**Step 2 — `web/app.py`** ✅
- [x] `_format_status()` 加入 `nominal_readonly`（`:220`）

**Step 3 — `web/static/js/app.js`** ✅
- [x] `isModNominalReadOnly(mod)`（`:741`）
- [x] `setAllNominal` 的 filter（`:711`）
- [x] `return {}` 已納入（`:1143`）
- [x] 無 `length < 4` 殘留（grep 確認）——**readonly 與通道數刻意解耦**，
      判斷依據是探測結果而非模組通道數

**Step 4 — `web/templates/index.html`** ✅
- [x] 模組標題列 badge（`:243`）、模組批次列反灰（`:254`/`:256`）、通道列反灰（`:287`/`:292`）

**Step 5 — `web/static/css/style.css`** ✅
- [x] `.mod-readonly-badge`（`:689`）

### 計畫外的追加（比原規劃更完整）

| 項目 | 說明 |
|---|---|
| Badge 可點擊 | 原規劃只要靜態標籤；實際做成按鈕，點擊開啟說明 modal，內含**旋鈕 + 長按 LED > 2 秒**的完整操作步驟與「僅轉旋鈕不會儲存」的警告 |
| 伺服器端也擋 | `POST /api/channels/nominal`（`web/app.py:508`）會跳過 read-only 模組並回報 `skipped`；前端反灰之外多一層防護，全部被跳過時回 422 |
| 探測結果快取 | 以序號為索引存於 `config/nominal_probe_cache.json`，命中時零寫入（見本檔「Web CIP 並發修正」節）。實機快取內容：3 模組、M2 為 read-only |
| 重新探測逃生口 | `POST /api/device/reprobe-nominal` |

### 🐛 2026-09-01 補記時發現的兩個缺陷（已修）

**1. demo 模式完全沒有這條路徑** — `_generate_demo_payload()` 的 8 個通道
**都沒有 `nominal_readonly` 欄位**，前端 `?? false` 讓 badge 與反灰在 `--demo`
下永遠不出現。也就是說**沒有實機就無法檢視或除錯這個 UI**。

> 這正是本檔技術債表第 10 項預言的情況：「每個新端點都要手寫 `_DEMO_MODE` 分支，
> 漏寫 → `--demo` 在該頁靜默壞掉，且無測試會抓到」。**它真的發生了**，
> 而且從實作到發現隔了約一週。

修正：demo 的模組 2 標記為 read-only（對應實機 M2 正是這種模組），
`POST /api/device/reprobe-nominal` 的 demo 分支也從回 `[]` 改為 `[2]`
（原本會讓「重新探測」看起來把 M2 變回可寫，前後矛盾）。

**2. 說明 modal 的錯字** — 「通道 LED 開始閃**激**綠色」「LED 停止閃**激**」
（2 處，應為「閃**爍**」）。這是使用者會讀到的操作步驟文字。

**版號**：`?v=4.10.0 → 4.11.0`

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

##### 4.4.2 設備識別資訊指令 ✅ **已完成（2026-09-01）**

> **對應後端**：`get_device_info()`（Identity Object + Class 0x0F）  
> **實際工時**：0.5 小時（後端已完成，只需加 CLI 指令）

**工作項目**：
- [x] 新增 CLI 指令 `device info`（別名 `device` / `devinfo`）→ `show_device_info()`
  - 顯示產品名稱、廠商 ID、裝置類型、產品代碼、韌體版本、序號
  - 顯示全域設定：運作模式 / 通道循序啟動延遲 / 電流參數鎖定 / 按鈕介面鎖定
- [x] **用語與 Web UI 系統狀態頁的面板完全一致**，避免同一欄位在兩介面叫不同名字
- [x] 未知列舉值顯示 `原始值 (未知)` 而非猜測或留白（不同韌體可能有新值）
- [x] 讀取失敗的欄位顯示 `—`；整批失敗時額外提示可能原因

---

##### 4.4.3 網路資訊指令 ✅ **已完成（2026-09-01）**

> **對應後端**：`get_network_info()`（CIP 0xF5/0xF6）  
> **實際工時**：0.5 小時（後端已完成，只需加 CLI 指令）

**工作項目**：
- [x] 新增 CLI 指令 `network info`（別名 `network` / `netinfo`）→ `show_network_info()`
  - 顯示 IP、子網路遮罩、預設閘道、DNS1/DNS2、主機名稱、MAC 位址
- [x] 設備回報的 IP 與連線位址不同時明確警示（例如設備剛改過 IP 但仍連在舊 session）
- [x] 結尾提示變更設備 IP 要走 `setting` → [4]，避免使用者以為這頁可編輯

**🐛 開發中抓到的 bug（自己新寫的程式碼）**：整批讀取失敗的判斷原本寫成
`not any(sysc.values())`，但 `param_lock` / `ui_lock` / `operating_mode` /
`switch_on_delay_ms` **四者同時為 0 是完全正常的設備狀態**（未鎖定 + 無延遲 +
Independent 模式），`any()` 會把這種合法狀態誤判成「所有欄位皆讀取失敗」。
已改為 `all(v is None for v in ...)`，並加上迴歸斷言。
⚠️ 這類「合法的 0 被當成缺值」是 Python 真值判斷的經典陷阱，日後寫類似檢查要留意。

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

#### 4.9 原廠 Web 介面資料整合（`caparoc_http.py`）✅ 已完成（2026-08-31 接上 web，2026-09-01 實機驗證通過）

> **目的**：設備除了 EtherNet/IP CIP，還有一個未公開的原廠 Web 介面
> （`GET http://<ip>/webif/systeminfo`、`GET http://<ip>/webif/processdata`，皆無需認證），
> 能拿到 CIP 讀不到的資訊：硬體清單、韌體版本、LED 狀態、故障事件記憶（每模組最近 10 筆）。
> **狀態**：客戶端（`src/caparoc_http.py` 244 行 + 8 個測試）已於 `8085134` 提交；
> 本輪接上 web 層——新增 `GET /api/device/webif` 與系統狀態頁三個「原廠介面」面板。

**已完成（`caparoc_http.py`，純函式，無 class，任何失敗一律回 `None`/部分資料，不 raise）**：
- [x] `fetch_systeminfo(ip)` / `fetch_processdata(ip)` — 各打一支端點，回傳 `data` 區塊或 `None`
- [x] `fetch_http_info(ip)` — 兩支端點都打，合併成單一 dict（`merge_http_info` 負責合併邏輯）
- [x] `errorid_text()` / `errorevent_text()` / `decode_errorevents()` — 錯誤代碼 → 文字
      （docstring 註明原廠韌體內建的 DE/EN 對照表在 index 3/5 互相矛盾，已採用原廠 SPA bundle 的英文版為準）
- [x] `nominal_range_from_name()` — 從模組型號字串解析額定電流範圍（如 `"...1-4A"` → `(1, 4)`）
- [x] 換算係數已對實機 192.168.50.111 與 CIP `/api/status` 同刻交叉驗證（voltage /100、totalcurrent /10、
      per-channel current /10、nominalcurrent 為整數安培不除）
- [x] `tests/test_caparoc_http.py`：8 個測試全過（含 fixtures，無網路依賴）

**已完成（接上 web 層，2026-08-31）**：
- [x] `web/app.py`：**新開 `GET /api/device/webif`**，不併入 `/api/device/info` 或 `/api/device/network`
      （比照本檔「🌐 Web「IP 設定」」節記取的 `/api/device/network` vs `/api/ipconfig/current`
      分工教訓：新資料源用新端點）
- [x] `_DEMO_MODE` 分支：`_demo_webif_info()` 走 `merge_http_info()` 產生，結構與實機一致，
      並刻意涵蓋 80% 警告 / 過載 / 短路 / 硬體故障 / 非空 `fault_events` / 非零 `errorcounter`
- [x] 前端：系統狀態頁下半部三個面板——硬體與韌體、LED 狀態、故障事件記憶
- [x] LED 呈現：狀態欄只畫燈點不寫顏色字（`green`/`blinking-green`…只留 `title`），
      顏色語意集中到「ℹ️ 燈號說明」modal（顏色通則 + NET/MOD/通道燈各自的判讀，
      沿用 `channel-settings` 頁那套 `.modal-*`）；`.webif-ch-table` 用 `table-layout: fixed`
      + `<colgroup>` 鎖欄寬，M1／M2 兩張表對齊、燈點落在「LED」表頭正下方
- [x] LED 配色：拉獨立 token `--led-green`/`--led-red`/`--led-yellow`（不沿用 `--ok`/`--err`/`--amber`
      ——那組在白天模式為文字對比被刻意加深，當小圓點會發灰），兩主題都用飽和發光色 +
      `box-shadow` 柔光暈；熄滅燈在白天模式改為淺灰底（原本全透明幾乎看不到）
- [x] 輪詢頻率：比照 `/api/device/info` 走「進頁面讀一次 + 手動 ↻」，**不併入 1 Hz WebSocket 推送**
      （原廠 API 兩支端點各 2.5 秒逾時，設備不可達時單次最長約 5 秒）
- [x] `?v=4.8.0 → 4.9.0`（`index.html` 兩處）
- [x] `WEB_UI_FEATURE_REFERENCE.md`：端點表、CIP vs webif 對照、NET LED 判讀、回應範例
- [x] `docs/CHANGELOG.md` 條目已於實機驗證後補上（2026-09-01）

**關鍵設計決策：`/api/device/webif` 不檢查 `is_connected`**

webif 走 HTTP/80、無 session、免認證，與 CIP（44818、有 session、`_cip_lock` 互斥）是兩條獨立傳輸。
CIP session 掉了但設備還活著時這裡仍讀得到，而**每模組的故障事件記憶正是那個時候最有價值**。
因此本端點只要 `backend.device_ip` 有值就試，且**一律回 HTTP 200**——
抓不到回 `{"available": false}`，不丟 503（這是補充資料，不是關鍵路徑）。
前端 `fetchWebifInfo()` 對應地不看 `state.connected`、不佔 `_cipReadInFlight`。

**NET LED 判讀備忘**（實機已確認）：綠色恆亮＝至少一條 CIP 連線在線；綠色閃爍＝已上線但無 CIP 連線；
紅閃＝連線逾時；紅恆亮＝IP 衝突。⚠️ 反映的是**任何 client** 的連線（PLC / 其他工具也算），
**不可拿來取代 `backend.is_connected`** 判斷本程式的連線狀態。

**✅ 實機驗證通過（2026-09-01）**：demo 模式先前已通過（端點回 200、三面板渲染、靜態資源版號正確、
不可達 IP 回 `{"available": false}` 不 raise）。接實機 192.168.50.111 後四項確認全數符合：
webif 讀回的 voltage/current 與同刻 `/api/status` 的 CIP 值一致、模組清單與實體相符、
LED 顏色與面板實況相符、CIP 斷線狀態下此頁仍讀得到（驗證了本節「不檢查 `is_connected`」的設計決策）。

**不在本次範圍**（另立項目）：用 webif 的 `nominal_min`/`nominal_max` 去驅動 4.3.5
通道設定頁的輸入範圍與反灰。本次三個面板皆為唯讀顯示。

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

### 現況盤點（2026-09-03 確認）

**打包相容性目前是零**——全專案搜尋 `sys._MEIPASS` / `sys.frozen` **無任何結果**，
`src/paths.py` 也不存在。以下是打包後會實際壞掉的位置（已逐一確認）：

| 檔案 | 目前寫法 | 打包後的後果 | 嚴重度 |
|---|---|---|---|
| `src/app_config.py:36` | `_ROOT_DIR = Path(__file__).resolve().parent.parent` | config 指向 PyInstaller 暫存解壓目錄。**使用者在 exe 旁邊編輯 `config.json` 完全不會被讀到**，且每次啟動都是全新解壓目錄 → 設定形同無法修改 | 🔴 最高 |
| `src/logging_manager.py:204` | `log_dir = Path(__file__).parent.parent / log_dir` | log 寫進暫存解壓目錄，**程式一關就隨目錄消失**。現場出問題時沒有任何記錄可查 | 🔴 高 |
| `src/caparoc_backend.py:832` | `_PROBE_CACHE_PATH = Path(__file__).resolve().parent.parent / "config" / ...` | 額定電流探測快取每次啟動都落在新的暫存目錄 → **快取永遠不命中**。而探測會短暫改寫設備的額定電流再還原，等於每次連線都對真實設備做一輪寫入 | 🟡 中（有副作用） |
| `web/app.py:39` | `_WEB_DIR = Path(__file__).parent` | templates / static 需改讀 `sys._MEIPASS`（這兩者**應該**打包進去，與 config/logs 相反） | 🟡 中 |

**關鍵區分**（設計 `paths.py` 時必須分清楚，兩者方向相反）：
- **內嵌資源**（跟著 exe 走，唯讀）：`web/templates`、`web/static`（含 `vendor/`）→ `sys._MEIPASS`
- **外部資料**（放在 exe 旁邊，使用者可讀寫）：`config/`、`logs/` → `Path(sys.executable).parent`

**工作項目**：
✅ **本節已於 2026-09-04 完成**，以下保留為實作依據。

- [x] 建立 `src/paths.py`：統一定義 `ROOT_DIR` / `CONFIG_DIR` / `LOG_DIR` / `WEB_DIR` / `RESOURCE_DIR`
  - 開發模式：`Path(__file__).resolve().parent.parent`
  - Frozen 外部資料：`Path(sys.executable).parent`（exe 同層）
  - Frozen 內嵌資源：`Path(sys._MEIPASS)`
- [x] `src/app_config.py`：`_ROOT_DIR` / `CONFIG_DIR` 改為引用（**優先做，影響最大**）
- [x] `src/logging_manager.py`：log 目錄改為引用（含 `_setup_logger` 與 `cleanup_old_logs` **兩處**
      ——後者目前沒做相對轉絕對，見 4.3.1-audit）
- [x] `src/caparoc_backend.py`：`_PROBE_CACHE_PATH` 改為引用
- [x] `web/app.py`：`_WEB_DIR`（內嵌）與 `_ROOT_DIR`（外部）**分開處理**，不可共用同一個 base
- [x] `src/caparoc_controller.py`：config 路徑改為引用
- [x] 驗證：開發模式行為不變（跑一次現有測試 + demo 模式）

---

#### 5.2 CDN 資源離線化

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

> 表格於 2026-09-03 重整（第二次）：4.3.1-audit 的兩個決策點已執行完畢，移出待辦。

**已完成（2026-09-01）**：4.3.1 設定值外部化 ✅、4.3.5 nominal_readonly 探測 ✅、
4.4.2 / 4.4.3 CLI 設備/網路資訊指令 ✅
**已完成（2026-09-03）**：4.3.1-audit (a) 接上 `cleanup_old_logs()` ✅、
(b) 死設定與 `web.port` 限制註明 ✅

| 優先級 | 任務 | 預估工時 |
|--------|------|---------|
| 高 | 4.3.6 通道自訂標籤（設備名稱） | 2-3h |
| 高 | 4.4.1 CLI 通道詳細狀態顯示 | 2-3h |
| 中 | 4.3.3 UI 視覺一致性與元件統一 | 2-3h |
| 中 | 4.3.4 行動裝置基本支援 | 1-2h |
| 中 | 4.5 數據記錄與分析 | 6-8h |
| 中 | 4.6 告警與通知系統 | 4-5h |
| 低 | 4.7 多設備管理 | 5-6h |
| 低 | 4.8 自動化測試與 CI/CD | 8-10h |

**Phase 4 預估剩餘工時**：25-35 小時

> 💡 **4.5 數據記錄與分析**：log 保留已在 2026-09-03 接上
> （web 啟動時依 `retention_days` 清除）。若 4.5 要導入 SQLite 的「自動清理舊數據」，
> **應併入同一套機制**，不要再長出第二套保留策略。

---

**Phase 5 打包與部署** 📦

| 優先級 | 任務 | 預估工時 |
|--------|------|---------|
| 高 | 5.1 路徑抽象化（打包前置）— **打包相容性目前為零，見該節現況盤點** | 1-1.5h |
| ✅ | ~~5.2 CDN 資源離線化~~ — 已於 `c917847` 完成（`web/static/vendor/` 四個檔，`index.html` 已無外部 CDN 連結）；該節內文待補 | ~~0.5h~~ |
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


