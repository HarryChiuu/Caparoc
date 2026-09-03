# Changelog

---

## [2026-09-03] 修正 stdout 導向時 cp950 編碼錯誤被誤判為「設備連線失敗」

> 上一則的真機驗證途中撞到：設備 ping 通、`CaparocBackend` 直連也成功，
> 但 `python web/app.py > run.log` 啟動時 `connect()` 回報失敗，log 只留

```
[ERROR] [CONN] connect() 例外: 'cp950' codec can't encode character '❌'
```

### 🐛 根因

本專案有 **400+ 處帶 emoji 的 `print()`**（`src/caparoc_controller.py` 211、
`src/caparoc_backend.py` 101、`src/caparoc_ip_config.py` 81…）。

- Windows **真實主控台**在 Python 3.6+ 走 Unicode API（PEP 528），emoji 印得出來
  ——所以平常手動執行不會發現。
- stdout 一旦**被導向檔案或 pipe**（打包 exe 由排程／服務啟動、`> run.log`、
  被其他程式包起來執行），編碼退回地區編碼，繁中 Windows = **cp950**，
  裝不下任何 emoji。

致命的不是印不出來，而是**這些 print 多半在 `try` 內**：
`UnicodeEncodeError` 被外層 `except Exception` 當成「操作失敗」吞掉。
`connect()` 印到 `✅ CIP 連線已建立` 那一行就炸，於是**設備完全正常卻回報連不上**。

### 🔧 修法：`src/console_io.py` 的 `force_safe_stdio()`

在進入點把 stdout/stderr 的 `errors` 改成 `replace`，裝不下的字元退化成 `?`。
三個進入點（`web/app.py`、`src/caparoc_controller.py`、`src/caparoc_ip_config.py`）
都在**任何輸出之前**呼叫。

⚠️ **刻意只改 `errors`、不改 `encoding`**：改成 UTF-8 會讓 cp950 主控台的
**中文**變亂碼——為了救裝飾用的 emoji 去弄壞真正重要的訊息，是賠本生意。

### ✅ 真機驗證（同一台設備、同一時間，只差有沒有掛防護）

| | `connect()` | stdout |
|---|---|---|
| 修復前 | `False` | 印到 `[CIP 連線] 正在建立…` 就中斷 |
| 修復後 | `True`（讀得到 `CAPAROC PM EIP`） | `? CIP 連線已建立 (WEB UI 應顯示 'connected')` — emoji 退化成 `?`，**中文完好** |

`PYTHONIOENCODING=cp950` 下以 uvicorn 啟動 Web 服務同樣正常連線，
最近連線清單也照常寫入。

### 🧪 `tests/test_console_encoding.py`（5 項，不需設備與網路）

| 測試 | 擋下的問題 |
|---|---|
| `test_cp950_stream_raises_without_protection` | **前提驗證**——若哪天環境不再重現，其餘測試就該視為失效而非「修好了」 |
| `test_reconfigure_replaces_instead_of_raising` | 防護後不得再拋例外 |
| `test_cjk_still_readable_after_protection` | 釘住「只改 errors 不改 encoding」——中文不得被犧牲 |
| `test_force_safe_stdio_is_idempotent_and_never_raises` | 重複呼叫、`sys.stdout is None`（pythonw）都不得炸 |
| `test_entry_points_call_force_safe_stdio` | 新進入點漏掛防護，且必須**早於** `caparoc_backend` 匯入 |

---

## [2026-09-03] 連線設定頁：最近連線過的 IP 下拉 + 頁內網段掃描

> 現場每次要連設備都得手動 key 一次 IP。Web 連線成功後**不會**把 IP 寫回設定檔
>（只有 CLI 的 `setting [3]` 會），所以連過的位址下次一樣要重打。

### ✨ 減少手動輸入的兩條路（兩者互補，缺一不可）

| 情境 | 解法 |
|---|---|
| 連過的設備要再連一次 | 連線設定頁 IP 欄改為**可輸入的下拉**，列出最近成功連線過的設備 |
| 第一次接觸的設備，手邊沒有 IP | 把既有的**網段掃描**搬一份到連線設定頁，掃到直接一鍵連線 |

歷史清單只解決前者；真正的「零輸入」是後者。掃描 API（`POST /api/ipconfig/discover`）
早就寫好了，只是入口埋在「IP 設定」頁——這次讓它出現在最需要它的地方，
兩頁共用同一份掃描狀態，掃過一次兩邊都看得到。

### 🗄️ 清單存後端 `config.json`，**不是** localStorage

`config/config.json` 的 `device.recent`（`src/app_config.py`）。理由：

- 現場換一台筆電、換瀏覽器、清快取都不該讓清單消失——這是**設備資產**，不是瀏覽器偏好。
- `default_ip` 本來就住在這裡，兩者放同一區塊才不會各記各的。
- 打包成 exe 後跟著 `config/` 一起走。

行為：

- **只在連線成功後寫入**（`web/app.py` 的 `_remember_connection()`）。
  打錯的位址不該污染下拉清單——那正是這個功能要省掉的麻煩。
- 寫入時**一併更新 `default_ip`**，順帶補上「Web 連線後不記得 IP」這個既有缺口。
- 設備名／序號取自 Identity Object，**整段包在 try 內**：讀不到就留 `null`，
  絕不能因為一個顯示用的標籤讓連線流程失敗。
- 同 IP 只留一筆（重連即移到最前，未帶 name 時沿用舊值）；上限 `device.recent_max`（預設 5）。
- 單筆刪除（`DELETE /api/connect/recent/{ip}`）**刻意不動 `default_ip`**：
  「這台不想再出現在下拉」與「換開機預設值」是兩件事。

`_sanitize_recent()` 會把使用者手改壞的設定檔（塞字串、缺 `ip`、重複、非法 IP）
全部吸收掉，API 與前端永遠拿到乾淨清單。

### 🎨 下拉是自繪的，不是原生 `<select>`

要同時容納「可自由輸入」「一列顯示 IP + 設備名 + 相對時間」「單筆刪除」三件事，
原生 `<select>` 與 `<datalist>` 都做不到。

- ⚠️ **踩到的坑**：全域 `button:hover { background: var(--btn-bg-hover) }` 特異性
  (0,1,1) 蓋過 `.ip-picker-item` 的 (0,1,0)，hover 時整列會變成藍色按鈕底。
  補 `.ip-picker-item:hover { background: none }` 才讓 `li:hover` 的淡色 highlight 透出來。
  深淺色主題都已實測。
- 刪除鈕常駐但淡化（`opacity: 0.45`），不是藏到 hover 才出現——觸控裝置點不到。

### 📁 異動

| 檔案 | 內容 |
|---|---|
| `src/app_config.py` | `device.recent` / `recent_max` 預設值；`record_connection()`、`recent_devices()`、`forget_device_ip()`、`recent_max()`；抽出 `_write_config()`；`_deep_merge()` 補上 list 複製（否則 DEFAULTS 的可變物件會被共用進快取） |
| `web/app.py` | `_remember_connection()`；`GET/DELETE /api/connect/recent`；`POST /api/connect` 成功時回傳更新後清單；啟動自動連線成功時也記一筆 |
| `web/templates/index.html` | IP 欄改為 `.ip-picker` 下拉；連線設定頁新增掃描區塊；靜態資源版號 `4.11.0` → `4.12.0` |
| `web/static/js/app.js` | `recentIps` / `fetchRecent` / `pickRecent` / `forgetRecent` / `relTime`；點選單外收起 |
| `web/static/css/style.css` | `.ip-picker*`、`.conn-scan`、`.iface-sel` |
| `config/config.example.json` | 補上 `recent` / `recent_max` 與說明 |

---

## [2026-09-01] 新增 demo/真實 payload 結構一致性測試

> `web/app.py` 有兩條產生前端 payload 的路徑必須保持結構一致：
> 真實走 `_read_current_status()` → `_format_status()`，demo 走
> `_generate_demo_payload()`。新增欄位時只改真實路徑、忘了改 demo，
> `--demo` 會**靜默壞掉**——前端讀到 `undefined`，該功能就是不出現，
> 沒有錯誤訊息、沒有 log。`nominal_readonly` 就是這樣潛伏了約一週。
>
> 本測試把「漏寫 demo 分支」從人工複查變成自動偵測。

### ✨ `tests/test_demo_payload.py`（6 項檢查，不需設備與網路）

| 測試 | 擋下的問題 |
|---|---|
| `test_top_level_keys_match` | 頂層欄位漏寫或多寫 |
| `test_channel_keys_match` | 通道欄位漏寫，**逐通道檢查**（漏寫常只發生在某幾列，例如改了模組 1 忘了模組 2） |
| `test_top_level_types_match` | 型別漂移（str vs 數字這類前端會出錯的） |
| `test_channel_types_match` | 同上，通道層級 |
| `test_demo_covers_nominal_readonly_both_ways` | demo 的 `nominal_readonly` 必須**同時有 True 與 False**——只有欄位存在還不夠，全 False 的話 read-only UI 在 `--demo` 下依然看不到 |
| `test_demo_module_count_matches_channels` | `module_count` 與通道實際涵蓋的模組數不符 |

**型別比對用「家族」而非精確型別**：int 與 float 視為同族（真實路徑的
`round()` 與 demo 的字面值可能一邊 int 一邊 float，那不是缺陷），
但 str vs 數字、None vs 值會被抓到。
⚠️ `bool` 必須排在 `int` 之前判斷——Python 的 `bool` 是 `int` 子類別，
順序寫反會讓「布林欄位變成數字」漏檢。

### 🐛 測試立刻抓到的既有漂移：`timestamp` 型別不一致

- 真實路徑：`_read_current_status()` 給 `time.time()` → **float**
- demo：`_datetime.now().isoformat()` → **str**

前端目前沒有讀 `payload.timestamp`（圖表的時間標籤是前端自己產的），
所以是**潛伏而非現行故障**——但正是這支測試該攔的東西。
真實路徑是契約，已改 demo 為 `time.time()` 對齊。

### ✅ 驗證方式

不只跑過就算——**實際注入迴歸驗證測試會失敗**：暫時移除 demo 模組 2 的
`nominal_readonly` 欄位後，測試回報
「demo 通道 id=5（模組 2）欄位不一致 — 只在真實 payload 有（demo 漏寫）：
['nominal_readonly']」，還原後 6/6 通過。

過程中順帶修掉測試自身的兩個弱點：
- `test_demo_covers_nominal_readonly_both_ways` 原本用 `ch["..."]` 直接存取，
  欄位整個消失時會拋 `KeyError` 蓋掉真正的診斷訊息 → 改用 `.get()` 先檢查
- 直接執行的 harness 原本只接 `AssertionError`，一支崩潰會中斷其餘測試 →
  補接一般例外。漏寫欄位通常同時打到好幾支，一次看到全部比逐次修快

### ⚠️ 執行環境

本測試會 `import web/app.py`，**需在裝有 fastapi 的環境執行**（conda env `sv`）。
該環境目前沒有 pytest，所以 `python tests/test_demo_payload.py` 直接執行
是實際驗證過的路徑。

---

## [2026-09-01] 修正 demo 模式看不到 nominal_readonly UI（4.3.5 補完）

> 核對 4.3.5 是否可標記完成時，確認五個 Step 全數實作且超出原計畫
> （badge 做成可點擊的說明 modal、伺服器端也擋 read-only 模組、探測結果快取），
> 但發現兩個缺陷。

### 🐛 demo 模式完全沒有這條路徑

`_generate_demo_payload()` 的 8 個通道**都沒有 `nominal_readonly` 欄位**。
前端 `channelsByModule.value[mod]?.[0]?.nominal_readonly ?? false` 於是恆為
`false`，badge 與輸入欄反灰在 `--demo` 下**永遠不會出現**——
也就是說沒有實機就無法檢視或除錯這個 UI。

> 這正是 `docs/TODO.md` 技術債表第 10 項預言的情況：
> 「每個新端點都要手寫 `_DEMO_MODE` 分支，漏寫 → `--demo` 在該頁靜默壞掉，
> 且無測試會抓到」。**它真的發生了**，從實作到發現隔了約一週。

- demo 的**模組 2 標記為 read-only**（對應實機 M2 正是這種 2 通道模組；
  `nominal_probe_cache.json` 記錄實機為 3 模組、M2 read-only）
- `POST /api/device/reprobe-nominal` 的 demo 分支從回 `[]` 改為 `[2]`
  ——原本會讓「重新探測」看起來把 M2 變回可寫，與狀態推送前後矛盾
- 抽出 `_DEMO_READONLY_MODULES` 常數，讓兩處共用同一份定義

### 🐛 說明 modal 的錯字

「通道 LED 開始閃**激**綠色」「LED 停止閃**激**」共 2 處，應為「閃**爍**」。
這是使用者實際會照著操作的步驟文字。

### ✅ 驗證

`--demo` 下 `/api/status` 的 M1 四通道回 `false`、M2 四通道回 `true`；
`/api/device/reprobe-nominal` 回 `{"readonly_modules":[2]}`；
首頁帶新版號且錯字已清除。`ruff check .` 全過。

**版號**：`?v=4.10.0 → 4.11.0`

---

## [2026-09-01] CLI 新增 `device info` / `network info` 指令（4.4.2 / 4.4.3）

> 後端的 `get_device_info()`（2026-05-22）與 `get_network_info()`（2026-05-21）
> 早已完成並供 Web UI 使用，但 CLI 一直沒有對應指令——同一份資料只有網頁看得到。
> 本次補上兩支純顯示方法，CLI 與 Web 在設備資訊上功能對等。

### ✨ `device info`（別名 `device` / `devinfo`）

顯示產品名稱、廠商 ID、裝置類型、產品代碼、韌體版本、序號，以及全域設定
（運作模式 / 通道循序啟動延遲 / 電流參數鎖定 / 按鈕介面鎖定）。

### ✨ `network info`（別名 `network` / `netinfo`）

顯示 IP、子網路遮罩、預設閘道、DNS1/DNS2、主機名稱、MAC 位址。

- **設備回報的 IP 與連線位址不同時明確警示** — 例如設備剛改過 IP 但我們還連在
  舊 session 上，這種不一致靜默顯示會誤導
- 結尾提示變更設備 IP 要走 `setting` → [4]，避免使用者以為這頁可編輯

### 🎯 設計取捨

- **用語與 Web UI 系統狀態頁的面板逐字一致**（「通道循序啟動延遲」「電流參數鎖定」
  等），避免同一個欄位在兩個介面叫不同名字
- 未知列舉值顯示 `原始值 (未知)` 而非猜測或留白——不同韌體版本可能有新值
- 讀取失敗的欄位一律顯示 `—`；整批失敗時額外提示可能原因（不支援該 CIP class
  或連線已中斷），與 backend「單一屬性失敗不影響其他欄位」的設計相呼應

### 🐛 開發中抓到的 bug：合法的 0 被當成缺值

整批讀取失敗的判斷原本寫成 `not any(sysc.values())`。但 `param_lock` / `ui_lock` /
`operating_mode` / `switch_on_delay_ms` **四者同時為 0 是完全正常的設備狀態**
（未鎖定 + 無延遲 + Independent 模式），`any()` 會把這種合法狀態誤判成
「所有欄位皆讀取失敗」並印出誤導的警告。

改為 `all(v is None for v in ...)`，並加上迴歸斷言（全 0 不得觸發警告、
全 None 仍須觸發）。這類「合法的 0 被 Python 真值判斷當成缺值」是經典陷阱，
和先前 `is_valid_ip()` 那個 bug 一樣**只在特定資料下才發作**。

### ✅ 驗證

以 mock 覆蓋 9 個分支：全欄位正常、未連線、全部讀取失敗、部分失敗、
未知列舉值 `operating_mode=7`、設備 IP 與連線位址不一致，加上前述兩條迴歸斷言。
`ruff check .` 全過；`h` 說明選單正確列出兩個新指令。

**⚠️ 尚未實機驗證**：以上皆為 mock 驗證，接實機後需確認實際讀回的欄位值合理。

---

## [2026-09-01] 設定值外部化：合併為單一 `config/config.json`（4.3.1）

> 原本設定散在 `config/device_config.json`（只有 `default_ip`）與
> `config/logging_config.json`，另有一批寫死在程式碼裡的可調值
> （WebSocket 推送間隔、閒置關閉秒數、監聽埠、額定電流範圍）。
> 合併為單一 `config/config.json`，使用者只需編輯一個檔案。

### ✨ 新增 `src/app_config.py`（統一載入器）

規劃時沒有這一項——但三個模組各自開檔 parse 同一個檔案會是三份重複邏輯，
且合併後 `save_device_ip()` **必須 read-modify-write**，否則寫 IP 會洗掉
使用者的 logging/web 設定（舊架構每檔只有一個區塊，沒有這個問題）。

- `DEFAULTS` 是所有設定的**權威來源**；使用者的 `config.json` 只需寫想改的鍵，
  缺鍵深層合併補上，設定檔不存在或 JSON 壞掉都不會讓程式起不來
- **只依賴標準函式庫** — `logging_manager` 會 import 本模組，不得反向依賴
- API：`load()` / `section(name)` / `get(section, key)` / `nominal_range()` / `save_device_ip(ip)`

### ✨ 自動遷移舊設定檔

`config.json` 不存在但舊檔存在時，開機自動合併產生，**舊檔改名為 `.migrated` 保留**
而非直接刪除（遷移邏輯萬一有誤，使用者還救得回來）。
實測既有的 `default_ip = 192.168.50.111` 正確保留。

順帶不遷移 `write_jsonl` — JSONL handler 已於 2026-05-14 移除，該設定無人讀取。

### ♻️ 四個讀取端改接

| 檔案 | 改動 |
|---|---|
| `web/app.py` | `default_ip`、`web.port`（`_resolve_port()` 的預設）、`ws_push_interval`（原 `asyncio.sleep(1.0)` 寫死）、`ws_idle_shutdown`（原 `_WS_IDLE_TIMEOUT = 10.0` 寫死） |
| `src/logging_manager.py` | `_load_config()` 改走 `app_config.section('logging')`；`config_path` 參數保留以相容舊呼叫方式 |
| `src/caparoc_backend.py` | `_validate_nominal_args()` 的 1-20A 改用 config 的 `nominal_current` |
| `src/caparoc_controller.py` | `_load_default_ip()` / `_save_default_ip()` 縮為 `app_config` 的薄包裝（原本各自開檔讀寫） |

### ✨ `GET /api/config/limits` — 前端不再寫死 1/20

額定電流範圍原本寫死在**六個地方**：`index.html` 三個 input 的 `min`/`max`、
`app.js` 三處 `val < 1 || val > 20` 驗證。改設定檔要同步六處，必漏。

- 新增 `GET /api/config/limits`（**不檢查 `is_connected`** — 純設定值與連線無關，
  未連線時前端仍要能正確渲染輸入欄）
- `app.js` 新增 `limits` reactive + `fetchLimits()`（`onMounted` 呼叫，不等 WebSocket），
  三處驗證合併為單一 `validateNominal()`
- `index.html` 三個 input 改綁 `:min="limits.nominalMin" :max="limits.nominalMax"`
- `?v=4.9.0 → 4.10.0`

### 🧹 `.gitignore`

改為忽略 `config/config.json`（含站點專屬 IP）與 `config/*.migrated`，只追蹤
`config.example.json` 範本。原本 `logging_config.json` 是被追蹤的，與
`device_config.json` 不進版控的慣例不一致，一併統一。

### ✅ 驗證

- 暫時改寫 `config.json`（range 2-16、port 8123、push 2.5、idle 45）→ 四項皆生效
- `save_device_ip()` 寫入後 web / logging / nominal_current 三個區塊**完整保留**
- demo 模式：`/api/config/limits` 回 200、`/api/status` 正常、`/` 帶新版號 4.10.0
- `node --check app.js` 通過；`ruff check .` 全過
  （**順帶抓到重構遺留的 3 個死 import** — 導入 ruff 當天就回本）

### ⚠️ 尚未實機驗證

以上皆為 demo 模式與單元層級驗證。接實機後需確認 CLI 的 `setting [3] 存為預設值`
寫入 `config.json` 後重啟仍讀得到。

---

## [2026-09-01] 導入 ruff 靜態檢查

> **動機**：2026-08-28 `caparoc_ip_core.py` 的 `is_valid_ip()` 例外分支被寫成小寫 `false`，
> 使所有「輸入格式錯誤」的路徑從預期的 HTTP 422 變成 `NameError` → HTTP 500。
> 合法輸入走 `return True` 完全正常，只有錯誤分支才發作，人工測試極易漏掉。
> `F821 undefined-name` 一秒就能抓到這類問題，本專案先前沒有任何 linter。

### ✨ 新增 `ruff.toml`

規則選擇原則：**只收會指出真實缺陷的規則，不收風格規則**。

- `select = ["E4", "E7", "E9", "F", "B"]` — import 錯誤、語句層級錯誤、語法錯誤、
  pyflakes（含 `F821`）、bugbear（可變預設引數、迴圈變數綁定等）
- `ignore` 掉 `F541`（無佔位符 f-string，本專案刻意用於視覺一致的輸出樣板）與
  `E701`/`E702`/`E731`/`E741` 四項實為風格的規則
- 不啟用 `E1`/`E2`/`E3`/`E5`（縮排、空白、行長）與 `I`（import 排序），
  也**刻意不導入 formatter** — 既有風格一致，全檔重排會淹沒 git blame
- `web/app.py` per-file 忽略 `E402`：`sys.path.insert(0, ROOT/"src")` 必須先執行，
  之後才 import 得到 `caparoc_backend`，import 順序是架構要求而非疏漏
- 排除 `archive/`（歷史版本存檔，不再維護）、`output/`、`logs/`

### 🧹 首次掃描修掉的實際問題（63 → 0）

**掃描結果沒有 `F821`** — 目前無未定義名稱潛伏。修正的是以下幾類：

- `web/app.py`：`from datetime import date as _date` **重複 import 兩次**（第 25 與 65 行，F811）；
  `fastapi.requests.Request` 未使用
- `src/caparoc_ip_config.py`：**11 個殘留 import** — `SVC_SET` / `EIP_PORT` /
  `DHCP_CLIENT_PORT` / `DHCP_LEASE_SECONDS` / `DHCP_LIMITED_BROADCAST` / `DHCP_OFFER` /
  `DHCP_REQUEST` / `DHCP_ACK` / `dhcp_msg_type` / `normalize_mac` / `iface_mac_for`，
  外加 `subprocess`。皆為 2026-08-27 把函式下沉到 `caparoc_ip_core` 後遺留
  （確認全 repo 無人 `import caparoc_ip_config`，它只作為 CLI 執行，故非 re-export）
- `src/caparoc_controller.py`：`struct` 未使用（2026-05-14 刪除 1513 行冗餘方法後遺留）
- `src/caparoc_ip_core.py:161`：`zip(ips, results)` 補上 `strict=True`（B905）。
  `results` 由 `ex.map` 對 `ips` 產生，長度恆等，加 `strict` 零風險且能防未來改動
- `src/caparoc_backend.py:776`：`_probe_nominal_writable()` 內未使用的迴圈變數 `gch` → `_gch`（B007）
- `tests/check_connection.py:84`：bare `except:` → `except Exception:`（E722）

### ✅ 驗證

- `python -m ruff check .` → All checks passed
- `pytest tests/test_caparoc_http.py` → 8 passed
- conda `sv` env 下 `src/` 五個模組與 `web/app.py` 全部匯入成功（30 條路由）

---

## [2026-09-01] 實機驗證：webif 三面板、CIP 並發 refactor、白天模式

> 本則不含程式碼變更，記錄三批「已寫好但尚未實機確認」的功能通過驗證，
> 並把 `docs/TODO.md` 與本檔中過時的「尚未實機驗證 / 尚未 commit」字樣清掉。

### ✅ 4.9 原廠 Web 介面（webif）三面板

對實機 192.168.50.111 確認四項，全數符合：

- webif 讀回的 voltage / current 與同刻 `/api/status` 的 CIP 值一致（換算係數正確）
- 硬體與韌體面板的模組清單與實體機櫃相符
- LED 狀態面板的燈色與設備面板實況相符
- **CIP 斷線狀態下此頁仍讀得到** — 驗證了 `/api/device/webif` 刻意不檢查 `is_connected`
  的設計決策：webif 走 HTTP/80、免認證，與 CIP（44818）是兩條獨立傳輸，
  CIP session 掉了但設備還活著時，故障事件記憶正是最有價值的時候

### ✅ Web CIP 並發修正後續 refactor（2026-08-26 的 5 項）

先前僅通過 mock driver 與 `--demo` smoke test，本次接實機確認三條路徑行為符合預期，
無需追加修正：批次設定額定電流（`POST /api/channels/nominal`）、
連線時的 `nominal_probe_cache.json` 快取命中（零寫入）、通道開關。

### ✅ 4.3.7 白天模式對比度

已在瀏覽器實際切換白天/夜間主題檢查畫面，兩主題皆無對比度不足或跳版問題。
程式碼本身已於 `dfa1fa6` 提交（下方 2026-08-31 條目原記為「尚未提交」，本次更正）。

---

## [2026-08-31] 通道設定頁排版穩定化 + 白天模式對比度改善（`dfa1fa6`）

> 細節見 `docs/TODO.md` 4.3.7。

### 🐛 「設定中…」時整列/整表會跳動

- **根因**：額定電流表格與批次列沒有固定欄寬/按鈕寬度，按鈕文字從「設定」變成「設定中…」、
  或回饋訊息（`✓ 已設定` / 錯誤訊息）出現時，內容寬度改變會推擠整列甚至整個表格重排；
  主內容區也沒有預留捲軸槽，內容變高變矮時捲軸出現/消失會讓置中面板左右位移
- **修正**：`.ch-table` 改 `table-layout: fixed` + `colgroup` 固定欄寬；操作欄改用 `.td-action`
  （flex row，按鈕 `min-width` 固定，回饋訊息單行截斷 + `title` 提示完整文字）；
  批次列比照辦理；主內容區加 `scrollbar-gutter: stable`

### 🎨 白天模式對比度不足

- **根因**：白天模式的文字/強調色沿用了原本為深色底調校的色階，部分文字對比度偏低
- **修正**：`--text*` / `--accent*` / `--ok` / `--err` / `--warn` / `--amber` / `--sysconf-*` /
  `--purple` 全數加深，目標 `--text-dim` 以上（含）皆 ≥ 6:1、最淡的 `--text-fainter` 也有 ~4.6:1；
  系統日誌各等級配色、圖表格線/刻度/圖例（`app.js` 的 `_chartTheme()`）同步加深；
  通道開關「開啟」狀態新增白天模式專屬配色（原本沿用暗色模式配色，白天對比不足）
- 版號 `?v=4.7.0 → 4.8.0`

### ✅ 已驗證（2026-09-01 補記）

- [x] 已在瀏覽器實際切換白天/夜間模式檢查畫面
- [x] 已提交（`dfa1fa6`）

---

## [2026-08-28] IP 設定：DHCP 作業可手動中斷、救援可自訂遮罩與閘道（fix/web-cip-concurrency）

### ✨ DHCP 監聽／救援可手動中斷

- **問題**：MAC 偵測最長 90 秒、指派最長 2 分鐘，中途沒有退出的方法。
  **只在前端 abort fetch 是不夠的**——伺服器執行緒仍會佔著 UDP/67 與 `_dhcp_lock`
  跑到逾時，使用者按什麼都只會拿到 409，等於卡死
- **修正**：伺服器端真正的取消。`detect_dhcp_macs()` / `serve_dhcp()` 新增
  `should_stop` callable，迴圈每輪（監聽約 0.25 秒、指派約 1 秒）檢查一次；
  新增 `POST /api/ipconfig/dhcp-cancel` 設定共用的 `_dhcp_cancel` 事件旗標
- 前端在作業進行中顯示「✕ 中斷」按鈕；偵測回應新增 `cancelled` 欄位，
  指派被中斷時回 HTTP 499「已手動中斷」
- **實測**：90 秒監聽在送出中斷後 **5.1 秒**結束、標記 `cancelled: true`，
  且鎖立即釋放（隨後的偵測請求回 200 而非 409）；指派中斷同樣回 499 並釋放鎖

### ✨ 救援面板可自訂子網路遮罩與閘道

原本指派 IP 時遮罩／閘道是沿用下方「變更設備 IP」面板的欄位，隱晦且容易搞錯。
改為在救援面板中提供獨立的「子網路遮罩」「預設閘道」輸入框，
`POST /api/ipconfig/assign` 本來就接受這兩個參數，現在前端有對應 UI。

### 🐛 `is_valid_ip()` 寫成 `return false`（小寫）

- **現象**：任何格式錯誤的 IP／遮罩／閘道都會回 **HTTP 500**，而不是預期的 422
- **根因**：`caparoc_ip_core.py` 的 `is_valid_ip()` 例外分支寫成小寫 `false`
  （Python 沒有這個名字）→ 拋 `NameError`。
  合法 IP 走 `return True` 不受影響，所以只有「輸入錯誤」時才會炸，容易漏測
- **影響範圍**：`/api/ipconfig/static`、`/api/ipconfig/assign`、
  `/api/ipconfig/discover?iface_ip=` 的所有驗證路徑
- **修正**：改回 `False`，並全檔掃描確認無其他小寫 `true`/`false`。
  修正後五條驗證路徑全部正確回 422 並附中文訊息

### 🐛 補回 CLI 的 Ctrl+C 行為（前次重構的回歸）

DHCP 原語下沉到 core 時，漏掉了原本 `_detect_mac_via_socket()` 內的
`except KeyboardInterrupt: pass`，導致 CLI 在 MAC 偵測階段按 Ctrl+C 會拋出 traceback
而非回傳已收集到的部分結果。已在 `detect_dhcp_macs()` 補回。

---

## [2026-08-28] IP 設定頁：DHCP 失聯救援（MAC 偵測 + 指派 IP）（fix/web-cip-concurrency）

> 承上一則。使用者回報「切換成 DHCP 以後，掃描網段還是找不到 MAC」，
> 補上 web 相對於 CLI 缺的最後一塊：**設備失聯時的發現與救援**。

### 🐛 為什麼切成 DHCP 後就「找不到 MAC」

不是 MAC 顯示的問題——是**整台設備都掃不到**。設備切成 DHCP 但網段上沒有 DHCP server 時：

- 它拿不到 IP → EIP List Identity 廣播收不到回應
- 它沒有 IP → 不會出現在本機 ARP 表，ARP 後援也查不到
- 上一版的 MAC 補齊機制靠的正是 ARP 表，所以一樣是空的

**但設備並沒有死**：它會持續送出 DHCP Discover 廣播，封包裡就帶著自己的 MAC。
監聽 UDP/67 是這種狀態下**唯一**能發現設備的方法——CLI 的 `_detect_mac_via_socket()`
一直都做得到，web 卻沒有，這才是功能落差所在。

### ✨ 新增：DHCP 失聯救援（等同 CLI 的「[2] 新裝置初始設定」）

| 方法 | 路徑 | 說明 |
|---|---|---|
| `POST` | `/api/ipconfig/detect-mac` | 監聽 UDP/67 的 DHCP Discover，回傳偵測到的 MAC 清單 |
| `POST` | `/api/ipconfig/assign` | 開迷你 DHCP server 指派 IP 給指定 MAC，設備上線後再固化為靜態 IP 並自動重連 |

- 前端新增「找不到設備？（DHCP 失聯救援）」面板：偵測 MAC → 單選要救的 MAC →
  填入要指派的 IP → 一鍵完成「指派 + 固化靜態 + 重新連線」
- 新增 `_dhcp_lock`：UDP/67 是獨佔資源，MAC 偵測與迷你 DHCP server 必須互斥（並發回 409）
- 綁定 port 67 在 Windows 上**不需要管理員權限**；被 BootP-DHCP Tool 之類占用時回 503 並指出占用行程

### 🏗️ DHCP 原語下沉到 core，CLI 與 web 共用

`open_dhcp_socket` / `detect_dhcp_macs` / `build_dhcp_reply` / `serve_dhcp` /
`dhcp_msg_type` / `normalize_mac` / `iface_mac_for` 移入 `caparoc_ip_core.py`，
print 一律改為 callback（`on_found` / `on_progress` / `on_event`）。
`caparoc_ip_config.py` 只留印畫面的薄包裝，CLI 輸出逐字不變（`caparoc_ip_config.py` 少約 90 行）。

### 🐛 順手修掉：DHCP 訊息型別判斷錯誤（既有 bug）

- **根因**：`_detect_mac_via_socket()` 用 `data[0] != DHCP_DISCOVER` 判斷訊息型別，
  但 `data[0]` 是 BOOTP 的 `op` 欄位（1 = BOOTREQUEST），**不是 Option 53**。
  因為 `DHCP_DISCOVER` 剛好也等於 1 才「看起來能動」，實際上會把
  REQUEST / RELEASE / INFORM 全部誤判成 Discover
- **修正**：新增 `dhcp_msg_type()` 正確走 Option 迴圈解析，偵測與 serve 兩條路徑統一使用。
  單元驗證：`op=1 + Option53=3(REQUEST)` 現在正確回傳 3（舊碼會回報成 Discover）
- 這在 web 上更要緊——UI 會把「偵測到設備 MAC」當成確認步驟顯示給使用者

### ⏱️ 偵測預設時間 30 秒 → 90 秒

實機實測設備約**每 60 秒**才送一次 DHCP Discover（重試間隔會逐次拉長），
30 秒會誤以為偵測不到。預設改 90 秒、上限 180 秒，UI 也說明可再按一次或重插網路線。

### ✅ 實機驗證（用新功能救回真的失聯的設備）

測試期間設備確實處於「DHCP 模式 + 無 DHCP server」的失聯狀態，
掃描、ARP、舊位址探測全部無回應。完整走過 web 救援流程：

| 步驟 | 結果 |
|---|---|
| 掃描 | `devices: []`（重現使用者回報的現象） |
| `POST /api/ipconfig/detect-mac`（90 秒） | 偵測到 `cc:cc:ea:9f:c9:72`，約 61 秒 |
| `POST /api/ipconfig/assign` | `assigned/online/static_set/connected` 全為 true，耗時 51 秒 |
| 事後確認 | `192.168.50.111 / 255.255.255.0 / Static IP`，已連線，3 模組 24.24V |
| 事後掃描 | EIP 掃到設備且帶 MAC |
| CLI 迴歸 | 探索路徑與 [2] 新裝置設定選單輸出皆與改動前一致 |

---

## [2026-08-28] IP 設定頁實機測試修正：4 項問題（fix/web-cip-concurrency）

> 使用者實機操作後回報 4 項問題，逐一重現並修正。全部已在實機（CAPAROC PM EIP，
> 192.168.50.111，S/N 522F0E7A）驗證通過。

### 🐛 無法變更靜態 IP —— 寫入順序反了（最嚴重）

- **現象**：Web 按下「套用靜態 IP」永遠失敗；連帶「目前網路設定」一直顯示 DHCP
  （因為模式根本沒切成功，畫面顯示的其實是事實）
- **根因**：`set_device_ip()` 的順序是「先寫 Attr5（IP）再寫 Attr3（模式）」。
  但設備處於 DHCP 模式時**會拒絕寫入 Attr5**，回 CIP 錯誤 `Object state conflict`
  ——介面設定由 DHCP 掌控，不接受手動改。實機用相同值測試 Attr5 寫入即可穩定重現
- **修正**：改為 **先 Attr3 = 0（切 Static）、再 Attr5（寫 IP/遮罩/閘道）**。
  兩者仍都要寫——只寫 Attr3 的話設備會沿用舊的 Attr5 值而非使用者輸入的新 IP
- **附帶修正**：新增 `_cip_set_detail()`，回傳 `was_exception` 旗標以分辨
  「設備明確回 CIP 錯誤」（真失敗）與「送出後拿不到回應」（IP 已變、連線中斷，屬正常）。
  舊寫法把兩者都當失敗，導致改 IP 即使成功也會被誤報為失敗
- `set_device_ip()` 回傳新增 `unverified` 欄位，標示「已送出但未取得確認」

### 🐛 掃描不到 MAC、無法選擇網卡

- **根因 1（MAC）**：List Identity 回應**本身不含 MAC**（只有 IP/廠商/序號/產品名），
  只有 ARP 後援路徑才有 MAC；且前端表格根本沒有 MAC 欄位
- **修正 1**：新增 `arp_table()` / `arp_mac_map()`，EIP 探索完成後以 ARP 表補齊 MAC
  （設備剛回應過廣播，本機 ARP 表必然有它），讓兩條探索路徑欄位一致；前端表格加 MAC 欄
- **根因 2（網卡）**：CLI 的 `_pick_iface()` 只用在新裝置配置流程，探索路徑沒有網卡選擇；
  而多網卡機器上不綁定介面時，OS 會依路由表決定導向廣播從哪張網卡送出，很容易送錯而掃不到。
  實測：本機有 5 張網卡，指定 `192.168.50.255` 但不綁定 socket 時掃不到設備
- **修正 2**：新增 `list_interfaces()`（scapy `conf.ifaces`，含友善描述與 MAC）與
  `GET /api/ipconfig/interfaces`；`discover(iface_ip=...)` 會**把 socket 綁到該網卡 IP**
  並同時送導向廣播與受限廣播。前端新增「掃描網卡」下拉選單
- 實測：指定設備所在網卡（192.168.50.1 / Realtek USB GbE）可穩定以 EIP 掃到並帶 MAC

### 🐛 靜態 IP 時「設定方式」單選停在錯誤選項

- **根因**：`ipMode` 單選是獨立 ref，固定預設 `static`，不反映設備實際模式，
  造成上方資訊表顯示 DHCP、下方單選卻停在靜態 IP 的自相矛盾畫面
- **修正**：讀取設定後依 `config_control` 同步 `ipMode`（0→static、2→dhcp）

### ⚠️ 切換 DHCP 的風險警告（實測踩到）

測試過程中把設備切成 DHCP，而 192.168.50.x 是**電腦直連網段、沒有 DHCP server**，
設備隨即完全失聯（廣播、ARP、直接探測舊位址全部無回應）。
最後是用專案自帶的迷你 DHCP server 救回（`_open_dhcp_socket` + `_serve_dhcp`，
指派 192.168.50.111 給 MAC cc:cc:ea:9f:c9:72），設備才重新上線。

- **修正**：UI 的 DHCP 選項警告從一行 `hint-text` 改為顯眼的 `stale-banner`，
  明確寫出「若網段沒有 DHCP server，設備會**完全失聯**」，並附上救援指令
  （`python src/caparoc_ip_config.py` → [2] 新裝置初始設定）與「先記下 MAC」的提醒；
  確認對話框內同步強化

### ✅ 實機驗證

| 項目 | 結果 |
|---|---|
| 網卡列舉 | 5 張網卡，含 IP/MAC/友善描述 |
| 指定網卡掃描 + MAC | EIP 掃到 192.168.50.111，MAC `cc-cc-ea-9f-c9-72` |
| 目前設定顯示 | `config_control=0` → Static IP，與設備一致 |
| 變更靜態 IP `.111 → .112` | 成功，含自動重連，耗時 2.2 秒 |
| 還原 `.112 → .111` | 成功，含自動重連，耗時 2.2 秒 |
| **DHCP → 靜態 IP**（原本失敗的路徑） | **成功**，`config_control` 2 → 0 |
| CLI 迴歸（探索） | 輸出與改動前一致 |

---

## [2026-08-27] Web 新增「IP 設定」分頁 + 0xF5 讀寫補鎖（fix/web-cip-concurrency）

> 把 `src/caparoc_ip_config.py` 的設備探索與 IP 設定能力搬上 Web UI，側邊欄新增獨立一項「🌐 IP 設定」。
> 不含「全新設備配置精靈」（迷你 DHCP server + MAC 偵測）——該路徑需管理員權限與 Npcap、
> 單次流程最長約 6 分鐘，仍留在 CLI。

### 🏗️ 架構：抽出非互動核心層 `src/caparoc_ip_core.py`

- **根因**：`caparoc_ip_config.py` 每個函式都綁死 `input()` / `print(end='\r')`，web 層完全無法呼叫，
  導致設備 IP 設定至今只能在終端機操作
- **修正**：新增 `src/caparoc_ip_core.py`，收納 9 個不含互動 I/O 的函式
  （`is_valid_ip` / `same_subnet` / `parse_list_identity` / `get_broadcast_addresses` /
  `eip_port_open` / `probe_eip_hosts` / `discover_devices` / `discover_by_arp` / `wait_for_device`），
  另加組合函式 `discover()` 統一「List Identity 廣播 → ARP 後援」的退回邏輯。
  CLI 與 `web/app.py` **共用同一份實作**，日後修改探索行為只需改一個檔案
- **CLI 行為完全不變**：新增 `_wait_for_device()` 包裝補回 `⏳ 剩餘 Ns` 進度與 ✅/⚠️ 結果訊息；
  `discover()` 加 `on_stage` callback，讓 CLI 仍能在**開始 ARP 掃描前**就印出「改用 ARP table...」
  （ARP 掃描可能數秒，等結束才提示會讓使用者對著空畫面等）
- `discover_by_arp()` 補 `except (FileNotFoundError, OSError) → []`（原本在無 `arp.exe` 的系統會拋例外）

### 🐛 `read_device_network_config()` 自誕生起就是壞的（既有 bug）

- **根因**：該方法寫死 `connected=False`，但本設備（CAPAROC PM EIP）**三個 0xF5 屬性都只接受
  `connected=True`**，`connected=False` 一律回 `Too much data`（設備不支援 Unconnected Send 0x52）。
  實測 Attr1/3/5 三者皆然
- **為何沒被發現**：它在本次之前**沒有任何呼叫端**。CLI 的 `read_config()` 走自己的 `_read_attr()`，
  那支本來就有 `connected=False → True` 的退回機制
- **修正**：內部新增 `_read_f5(attr)`，比照 CLI 做兩段式嘗試。不寫死 `True` 是為了相容其他韌體/型號
- **實機驗證**：讀回 `ip=192.168.50.111 / subnet=255.255.254.0 / gateway=192.168.50.1 / Static IP`

### 🔒 三個 0xF5 方法補上 `_cip_lock`

- **根因**：`read_device_network_config` / `set_device_ip` / `set_device_dhcp` 直接呼叫
  `driver.generic_message()` 而未取 `_cip_lock`。CLI 單執行緒沒事，但 web 有 1 Hz WebSocket
  狀態讀取執行緒，共用 driver 會撞爛 pycomm3 的 TCP 串流
- **修正**：`_cip_get()` / `_cip_set()` 新增 `driver=None` 參數（None = 用 `self.driver`；
  CLI 可傳入自建的短命 driver），三個方法全部改走 wrapper。
  維持既有契約「呼叫端不必也不該自行 `with self._cip_lock`」
- **未採用的替代方案**：讓 CLI 改用 `backend.connect()` 以移除 `driver` 參數——`connect()` 會
  `_activate_connection_state`、啟動 heartbeat、並跑 `_probe_all_modules()`（**探測會暫時改寫設備額定電流**），
  對一台只想改 IP 的設備做這些事既不必要也有風險
- `set_device_ip()` 新增 `ctrl_written` 欄位（Attr3 切 Static 是否寫成功），僅供除錯，不影響 `success`

**附帶盤點**：全檔 14 處 `generic_message` 逐一確認後，其餘未上鎖處分兩類——
`check_device_connection` / `_sync_output_from_device` / `_activate_connection_state` 只在
`connect()` 內、且都排在 `_start_heartbeat()` 之前執行（此時無其他執行緒碰 driver）；
`update_config_parameter` / `_wait_for_config_processing` 則是全 repo 無呼叫者的死碼。
⚠️ 前者的安全性依賴一個沒寫下來的隱性不變式，已記入 `docs/TODO.md`。

### 🌐 Web：新增 4 支 `/api/ipconfig/*` 路由

| 方法 | 路徑 | 說明 |
|---|---|---|
| `GET` | `/api/ipconfig/current` | 讀 0xF5 Attr1/3/5，**含 Static/BOOTP/DHCP 取得方式** |
| `POST` | `/api/ipconfig/discover` | 網段掃描；**刻意不檢查連線**（掃描的用途正是在未連線時找設備）。以 `_discover_lock` 防並發，第二個併發請求回 **409** |
| `POST` | `/api/ipconfig/static` | 設靜態 IP，並在伺服器端完成「寫入 → 斷線 → 換 IP → 等待上線 → 重連」 |
| `POST` | `/api/ipconfig/dhcp` | 切 DHCP；新 IP 無法預知，回傳提示改用掃描找回 |

- **自動重連放在伺服器端**：狀態機只有一份，結果透過既有 1 Hz WebSocket 自然同步到所有分頁；
  若放前端會變成「每個分頁各自輪詢重連」的競態溫床
- `wait_for_device()` 是純 TCP 44818 探測，**不碰 `_cip_lock`**，等待 30 秒期間不會卡住 WebSocket
- 與既有 `/api/device/network` 的分工已寫入雙方 docstring：後者走 `get_network_info()`
  提供 MAC/hostname，但**沒有** `config_control`，故 IP 設定頁必須走前者

### 🖥️ 前端：側邊欄新增「🌐 IP 設定」

- `navItems` 新增一項；新增 `currentPage === 'ip-config'` 分頁，含三個面板：
  **搜尋設備**（結果每列可「連線」或「帶入」表單）、**目前網路設定**（↻ 手動重讀）、**變更設備 IP**
- 靜態/DHCP 以 radio 切換；送出前跳 `.modal-overlay` 確認框，列出「目前 IP → 變更為」對照
- **同網段檢查**：新 IP 與設備現網段不同時顯示警告，但**只警告不擋**（比照 CLI `same_subnet` 語意）
- `refreshIpCurrent()` 併入既有的 `_cipReadInFlight` 旗標，不會與 `refreshNetworkInfo` /
  `refreshDeviceInfo` 並發觸發 CIP 讀取
- **零新增 CSS**：19 個用到的類別全部沿用 `style.css` 既有樣式
- `index.html` 的 CSS 與 JS 版號由 `?v=4.2.10d` 一併 bump 至 `?v=4.3.0`

### ✅ 驗證

- CLI 迴歸：主選單 / `[0]` 離開 / 非法 IP 參數 / `[1]` 探索（實機找到 192.168.50.111，
  廣播訊息與 ARP 後援訊息順序正確）全部與改動前一致
- Mock driver：三個 0xF5 方法回傳結構正確、`set_device_ip` 確認「先寫 Attr5 再寫 Attr3」、
  並實測 `generic_message` 執行期間 `_cip_lock.locked() == True`
- Demo 模式：4 支路由皆 200
- **實機並發測試**（連線 192.168.50.111，3 模組）：WebSocket 推送期間連打 6 次
  `/api/ipconfig/current`，讀取全部成功（0.03 秒）、**推送間隔穩定 1.01 秒、無中斷無逾時**；
  並發掃描正確回 `[200, 409]`
- 前端：`node --check` 語法通過；靜態掃描確認 template 用到的 21 個識別字全部存在於 `setup()` 的 return 物件
- **實機驗證**：實際寫入新 IP →「寫入 → 斷線 → 換 device_ip → 等待上線 → 重連」伺服器端流程 →
  WebSocket 於新 IP 上恢復推送，完整跑通

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
