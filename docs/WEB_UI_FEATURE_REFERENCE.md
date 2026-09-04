# CAPAROC 控制器 — 功能與 API 參考

> **用途**：Web UI 與 CLI 功能參考，整理後端 API、HTTP REST 端點、WebSocket 資料結構與 CIP 通訊細節。  
> **版本**：v4.2（2026-05-25）  
> **架構**：`CaparocBackend` (caparoc_backend.py) ← `CaparocController(CaparocBackend)` (caparoc_controller.py) + `web/app.py` (FastAPI)

---

## 1. CLI 指令總覽

### 1.1 額定電流設定

| 指令 | 說明 | 範例 |
|------|------|------|
| `init <ch> <amps>` | 設定通道額定電流（1–20A），使用 Read-Modify-Write 安全更新 | `init 2 4` |
| `verify <ch>` | 驗證通道目前的額定電流設定值 | `verify 1` |

- `<ch>`：全域通道編號（1–總通道數，多模組時自動轉換為模組/通道）
- `<amps>`：額定電流整數值（1–20A）
- 設定後自動驗證，最多重試 6 次（每次 0.5s）

---

### 1.2 通道開關控制

| 指令 | 說明 | 範例 |
|------|------|------|
| `on <ch>` | 開啟指定通道 | `on 1` |
| `off <ch>` | 關閉指定通道 | `off 3` |

- 每次控制後自動等待 0.5s 並回讀電流確認
- 使用 Output Assembly 0x64，Byte[1] 控制開關位元（bit0=CH1 … bit3=CH4），Bit7 固定=1（release）

---

### 1.3 狀態查詢

| 指令 | 說明 |
|------|------|
| `s` 或 `status` | 顯示完整狀態（全域系統 + 所有通道） |

**顯示內容**：
- 全域系統狀態位元組（欠壓/過壓/系統錯誤/80%警告/總電流關斷/Config處理中）
- 系統電壓（V）、全域總電流（A）、模組數量
- 每個通道：開關狀態、實際電流（A）、額定電流（A）、警告旗標

---

### 1.4 即時監控

| 指令 | 說明 | 範例 |
|------|------|------|
| `monitor start [interval] [mode]` | 啟動監控背景執行緒 | `monitor start 5 silent` |
| `monitor stop` | 停止監控 | — |
| `monitor status` | 顯示監控目前狀態 | — |

**參數**：
- `interval`：更新頻率（秒），最低 0.5s，預設 2s
- `mode`：
  - `silent`（預設）— 背景執行，僅有變化時輸出警報
  - `display` — 每次輪詢都輸出完整狀態表格

**偵測事件**：
- 通道開/關狀態變化
- 電流異常變化（> 30%）
- 電壓變化（> 1V）
- 新出現的 80% 警告 / 過載 / 短路

---

### 1.5 連線設定（setting 選單）

```
setting
```

進入互動式選單後有 4 個子選項：

| 選項 | 說明 |
|------|------|
| `[1]` 變更並連線 | 輸入新 IP 後立即重連，log 記錄 [SETTING] |
| `[2]` 恢復預設值 | 從 `config/device_config.json` 讀取預設 IP 並重連 |
| `[3]` 存為預設值 | 將目前連線 IP 寫入 `config/device_config.json`（不重連） |
| `[4]` 硬體 IP 修改 | 透過 CIP Class 0xF5 硬寫設備 IP、雙重確認、成功後自動存檔並重連 |

---

### 1.6 系統指令

| 指令 | 說明 |
|------|------|
| `h` 或 `help` | 顯示全部指令說明 |
| `reconnect` | 停止監控與心跳，重新觸發連線流程 |
| `q` 或 `quit` | 安全退出（停止監控、心跳，記錄 log） |

---

## 2. 後端 API（`CaparocBackend`）

> Web UI 直接呼叫這些方法，不需要 CLI 互動層。

### 2.1 連線管理

#### `check_device_connection(driver) → dict`
驗證裝置是否可連線（讀取 Input Assembly 0x65）。

```python
{
    'connected':   bool,
    'error':       str | None,
    'device_info': {
        'device_type':    'CAPAROC PM EIP',
        'module_count':   int,          # 偵測到的模組數（0–16）
        'total_channels': int,          # 模組數 × 4
        'voltage':        '24.0V'       # 字串格式
    }
}
```

#### `_activate_connection_state(driver) → bool`
建立 CIP 連線狀態（`connected=True`），**必須在第一次控制前執行**，否則 set_channel / set_nominal_current 無效。

#### `_start_heartbeat(driver)` / `_stop_heartbeat()`
啟動/停止心跳執行緒（閒置 300s 自動發送一次 CIP 請求保活）。

---

### 2.2 系統狀態

#### `check_global_system_status() → dict`
讀取 Input Assembly Byte 0–5，解析全域狀態。

```python
{
    'safe':               bool,   # True = 無嚴重錯誤
    'warning':           list,   # 警告訊息列表（字串）
    'error':             list,   # 錯誤訊息列表（字串）
    'voltage':            float,  # 系統電壓（V）
    'total_current':      float,  # 全域總電流（A）
    'module_count':       int,    # 偵測到的模組數量
    'global_status_byte': int     # 原始 Byte 0 值
}
```

**`global_status_byte` 位元定義**：

| Bit | 意義 |
|-----|------|
| 0 | 欠壓（Undervoltage） |
| 1 | 過壓（Overvoltage） |
| 2 | 系統錯誤（System Error） |
| 3 | 80% 總電流警告 |
| 4 | 總電流關斷 |
| 7 | Config Assembly 處理中 |

---

### 2.3 即時狀態（監控用）

#### `_read_current_status() → dict | None`
輕量化狀態讀取，供監控執行緒或 Web 輪詢使用。

```python
{
    'timestamp':          float,   # time.time()
    'global_status_byte': int,
    'module_count':       int,
    'total_current':      float,   # A
    'voltage':            float,   # V
    'channels': {
        1: {
            'module':           int,    # 模組編號
            'channel':          int,    # 模組內通道編號
            'is_on':            bool,
            'flowing_current':  float,  # 實際電流（A），解析度 0.1A
            'nominal_current':  float,  # 額定電流（A）
            'warning_80':       bool,
            'overload':         bool,
            'short_circuit':    bool,
            'hardware_fault':   bool,
            'total_shutdown':   bool
        },
        2: { ... },   # 依模組數量動態生成
        ...
    }
}
```

---

### 2.4 通道控制

#### `set_channel(channel, state) → bool`
控制單一通道開關。

```python
set_channel(1, True)   # 開啟 CH1
set_channel(3, False)  # 關閉 CH3
```

- `channel`：全域通道編號（1–`get_total_channels()`）
- `state`：`True` = 開啟 / `False` = 關閉
- 寫入後等待 0.5s 並回讀確認
- 回傳 `True` = 成功，`False` = 失敗（Driver 未初始化或 CIP 寫入錯誤）

---

### 2.5 額定電流設定

#### `set_nominal_current(module, channel, current_amps, verify=True) → bool`
透過 Config Assembly Read-Modify-Write 安全設定額定電流。

```python
set_nominal_current(1, 2, 4, verify=True)   # 模組1 通道2 設為 4A
```

- `module`：1–16
- `channel`：1–4
- `current_amps`：1–20（整數）
- `verify=True`：設定後輪詢最多 6 次驗證（每 0.5s），確認設備已應用

#### `_verify_nominal_current(driver, module, channel) → int | None`
從 Input Assembly 讀取實際額定電流值（含 debug 輸出）。

---

### 2.6 網路設定（硬體 IP）

#### `read_device_network_config(driver) → dict`
透過 CIP Class 0xF5 讀取設備目前網路設定。

```python
{
    'success':            bool,
    'ip':                 str,   # e.g. '192.168.2.111'
    'subnet':             str,   # e.g. '255.255.255.0'
    'gateway':            str,   # e.g. '0.0.0.0'（未設定時）
    'config_control':     int,   # 0=Static, 1=BOOTP, 2=DHCP
    'config_control_str': str,   # 'Static IP' / 'BOOTP' / 'DHCP'
    'status':             int,   # CIP Attr 1 原始值（-1=未讀取）
    'error':              str | None
}
```

#### `set_device_ip(driver, new_ip, subnet, gateway) → dict`
透過 CIP Class 0xF5 硬寫設備 IP（寫入後設備 IP 立即改變，連線中斷為正常現象）。

```python
{
    'success': bool,
    'error':   str | None
}
```

---

### 2.7 工具方法

| 方法 | 說明 | 回傳 |
|------|------|------|
| `get_total_channels()` | 取得系統總通道數（module_count × 4） | `int` |
| `get_module_and_channel(global_ch)` | 全域通道編號 → (模組, 通道) | `(int, int)` |
| `get_channel_offset(module, channel)` | 計算通道在 Input Assembly 中的 byte offset | `int` |
| `get_config_channel_offset(module, channel)` | 計算通道在 Config Assembly 中的 Nominal Current byte offset | `int` |
| `start_monitor(interval, mode)` | 啟動監控背景執行緒 | `bool` |
| `stop_monitor()` | 停止監控 | `bool` |
| `show_monitor_info()` | 輸出監控狀態（終端顯示用） | — |

---

## 3. 關鍵資料結構

### 3.1 Input Assembly（0x65，244 bytes）

| Byte | 說明 |
|------|------|
| 0 | 全域系統狀態（bit 0–4, 7） |
| 1 | 模組計數器（0–16） |
| 2–3 | 全域總電流（little-endian uint16, ÷10 = A） |
| 4–5 | 輸入電壓（little-endian uint16, ÷100 = V） |
| 6+ | 通道資料區塊（每模組 12 bytes，每通道 3 bytes） |

**通道 3-byte 結構**（offset = `6 + (module-1)*12 + (channel-1)*3`）：

| Byte | 說明 |
|------|------|
| +0 | Status（bit0=開關、bit1=80%警告、bit2=過載、bit3=短路、bit4=硬體故障、bit5=總電流關斷） |
| +1 | 額定電流（USINT，A） |
| +2 | 實際電流（USINT，÷10 = A） |

---

### 3.2 Output Assembly（0x64，18 bytes）

| Byte | 說明 |
|------|------|
| 0 | 通常為 0 |
| 1 | 通道開關控制（bit7=release 恆=1；bit0–3 = CH1–CH4 開關） |
| 2–17 | 保留 |

---

### 3.3 Config Assembly（0x66，讀/寫）

| Byte 區段 | 說明 |
|-----------|------|
| 0–5 | Header（保留） |
| 6+ | 每通道 3 bytes：[Nominal Current] [Programming Lock] [Status: 0=Off/1=On/2=NoChange] |

---

## 4. Web UI 頁面一覽（Phase 4.2）

> **導覽機制**：SPA 式 `v-if` 分頁切換，由 `app.js` 的 `currentPage` ref 控制。
> **沒有 router、沒有 hash、不寫入瀏覽歷史**——下表的「頁面代號」是 `navItems` 裡的 `page` 值，
> 不是可直接輸入的網址錨點。

| 頁面 | 頁面代號 | 對應後端 | 說明 |
|------|----------|----------|------|
側邊欄由上而下即操作流程（2026-09-04 重排）。**頁面代號未隨顯示名稱更動**，
改代號要連 `currentPage` 的所有判斷一起改，不值得。

| # | 頁面 | 頁面代號 | 對應後端 | 說明 |
|---|------|----------|----------|------|
| 1 | 通道控制 | `dashboard` | `_read_current_status()` / WebSocket | 通道卡片、開關按鈕、即時電流 |
| 2 | 設備監控 | `charts` | `GET /api/history?minutes=N` | 雙 Y 軸、模組分圖、zoom、30 分鐘歷史 |
| 3 | 通道設定 | `channel-settings` | `set_nominal_current()` / `POST /api/channels/nominal`、`GET/POST /api/labels/*` | 額定電流表格（依模組分區，可編輯）+ 通道自訂名稱（存本機 config.json） |
| 4 | 系統狀態 | `system-status` | `GET /api/device/info`、`GET /api/device/webif` | 上半：Identity Object + Class 0x0F（CIP）；下半三個「原廠介面」面板：硬體與韌體、LED 狀態、故障事件記憶（HTTP） |
| 5 | 系統日誌 | `logs` | `GET /api/logs` | 等級篩選、顏色編碼、分頁、自動更新 |
| 6 | 連線設定 | `connection` | `GET /api/device/network`、`POST /api/connect`、`GET/DELETE /api/connect/recent` | IP 連線表單（可下拉最近連線過的 IP）+ 頁內網段掃描 + 網路資訊面板（MAC / hostname） |
| 7 | 初始設定 | `ip-config` | `GET /api/ipconfig/{current,interfaces,hostname}`、`POST /api/ipconfig/{discover,static,dhcp,detect-mac,assign,hostname}` | 網卡選擇 + 網段搜尋（含 MAC）、讀取/變更設備 IP、切換 DHCP、**設備主機名稱**、DHCP 失聯救援 |

> ⚠️ **三種「名稱」別搞混**：
> - **主機名稱**（`/api/ipconfig/hostname`）— 寫在**設備**裡（CIP 0xF5 **Attr 6**），換一台電腦連線也看得到
> - **通道／設備自訂名稱**（`/api/labels/*`）— 只存在**這台電腦**的 `config.json`，以序號綁定
> - **產品名稱**（`/api/device/info` 的 `product_name`）— Identity Object，唯讀

> ⚠️ **`/api/device/network` 與 `/api/ipconfig/current` 容易混淆**：
> 前者走 `get_network_info()`（0xF5 + 0xF6），提供 **MAC / hostname**，但**沒有** IP 取得方式；
> 後者走 `read_device_network_config()`（0xF5 Attr1/3/5），提供 **`config_control`
> （Static / BOOTP / DHCP）**，是「IP 設定」頁判斷目前模式所必需。
> 兩者用途不同，**新增欄位前先確認要加在哪一支**。
>
> 主機名稱又是第三種：`get_network_info()` 讀的是「Attr 5 的 Domain Name 優先、
> 空的才退回 Attr 6」，而 `/api/ipconfig/hostname` **只讀寫 Attr 6**。
> 實機確認名稱存在 Attr 6（Attr 5 的 Domain Name 是空的），且 **Attr 6 立即生效、
> 不需重啟設備**。⚠️ 改名絕不可寫 Attr 5——那是整包 IP/遮罩/閘道/DNS，
> 與 `set_device_ip()` 同一個 attribute，寫錯會讓設備失聯。

> ⚠️ **系統狀態頁有兩個獨立資料源，別把欄位加錯邊**：
> 上半部（設備識別／全域設定）走 **CIP**（`/api/device/info`，需 `is_connected`）；
> 下半部三個「原廠介面」面板走 **HTTP/80**（`/api/device/webif`，**不需 CIP 連線**）。
> 兩邊都有「韌體版本」但**意義不同**：CIP 那個是 Identity Object 的 revision（如 `1.3`），
> webif 那個是原廠 Web 介面回報的 `fwversion`（如 `1.0.0`）。UI 已加註說明，勿合併。

---

## 5. HTTP REST API（`web/app.py`）

### 5.1 Phase 4.2 新增端點

| 端點 | 方法 | 說明 | 對應後端方法 |
|------|------|------|-------------|
| `/api/device/network` | GET | 讀取設備網路資訊（IP / MAC / 閘道 / 子網路遮罩） | `get_network_info()` |
| `/api/device/info` | GET | 讀取設備識別與全域設定（廠商 ID、CIP 版本、序號等） | `get_device_info()` |
| `/api/history` | GET | 讀取最近 N 分鐘歷史資料，最多 30 分鐘 | `_history_buffer` |
| `/api/connect/recent` | GET | 最近**成功**連線過的設備（最新在前），連線設定頁 IP 下拉來源 | `app_config.recent_devices()` |
| `/api/connect/recent/{ip}` | DELETE | 從最近連線清單移除一筆（不影響 `default_ip`） | `app_config.forget_device_ip()` |
| `/api/labels` | GET | 目前設備的通道／設備自訂標籤 | `app_config.device_labels()` |
| `/api/labels/channel/{id}` | POST | 設定單一通道標籤（body `{"text": ...}`，空字串＝清除） | `app_config.save_channel_label()` |
| `/api/labels/device` | POST | 設定設備層級標籤（同上） | `app_config.save_device_label()` |

#### 通道自訂標籤（4.3.6）

標籤存在 **`config/config.json` 的 `labels` 區塊**，以設備識別字串為 key，
格式與 backend 的 `_probe_cache_key()` 一致：讀得到序號用 `sn:<serial>`，
讀不到退回 `ip:<ip>`。

- ⚠️ **純本機資料**：CAPAROC 的 CIP 物件沒有可寫的通道名稱欄位，標籤不會、也無法
  同步到設備。換一台電腦要重新輸入，或把 `config.json` 一起帶走。
  通道設定頁有一行說明告知使用者這件事。
- **標籤不進 `/api/status` 與 WebSocket payload**：`_format_status()` 在 WS 迴圈中
  每秒執行，塞入靜態文字等於每天推 8.6 萬次，且後端得每秒多讀一次 CIP 取序號去搶
  `_cip_lock`。改由本組端點取一次，前端渲染時合併。
- 序號取自連線時 `_remember_connection()` 已經讀到的值（快取於 `_label_key_cache`，
  以 IP 為索引），標籤端點**不額外做 CIP 讀取**。
- 單則上限 32 字（`app_config.LABEL_MAX_LEN`）；空字串＝刪除該鍵，全部清空時
  連 `labels` 區塊一併移除，不在設定檔留空字串。
- `--demo` 下 key 固定為 `ip:demo`，三個端點都可正常運作。

#### 最近連線清單

清單存在 **`config/config.json` 的 `device.recent`**，不是 localStorage——現場換一台
筆電、換瀏覽器或清快取都不該讓它消失，且打包成 exe 後跟著 `config/` 一起走。

- **只在連線成功後寫入**（`_remember_connection()`）：連不上的位址進了清單只會變成下次的干擾項。
- 寫入時**一併更新 `device.default_ip`**，下次開機自動連最後一台連上的設備。
- 每筆 `{ip, name, serial, last_connected}`；`name`/`serial` 取自 Identity Object，
  讀不到就留 `null`，**絕不讓它影響連線流程**。
- 同 IP 只留一筆（重連即移到最前）；上限 `device.recent_max`（預設 5）。
- `DELETE` 刻意**不動 `default_ip`**：「這台不想再出現在下拉」與「換開機預設值」是兩件事。

#### `GET /api/device/network` 回應範例

```json
{
  "success": true,
  "ip_address": "192.168.50.111",
  "subnet_mask": "255.255.255.0",
  "gateway": "192.168.50.1",
  "mac_address": "CC:CC:EA:8B:5F:18"
}
```

#### `GET /api/device/info` 回應範例

```json
{
  "success": true,
  "vendor_id": 278,
  "device_type": 44,
  "product_code": 33,
  "revision_major": 1,
  "revision_minor": 3,
  "serial_number": "0xABCD1234",
  "product_name": "CAPAROC PM EIP"
}
```

### 5.2 原廠 Web 介面端點（Phase 4.9）

| 端點 | 方法 | 說明 | 對應實作 |
|------|------|------|---------|
| `/api/device/webif` | GET | 原廠 Web 介面的補充唯讀資訊：硬體清單、韌體版本、LED 狀態、每模組故障事件記憶、每通道累計跳脫次數 | `src/caparoc_http.py` 的 `fetch_http_info()` |

**與其他 `/api/device/*` 端點的根本差異**：

| | `/api/device/info`、`/api/device/network` | `/api/device/webif` |
|---|---|---|
| 傳輸 | EtherNet/IP CIP，TCP 44818 | HTTP GET，TCP 80 |
| 狀態性 | 有 session（註冊握手 + heartbeat 維持） | 無狀態、免認證 |
| 併發控制 | 佔用 `CIPDriver` 與 `_cip_lock` | 完全不碰 CIP，可與 CIP 讀寫並行 |
| 前置條件 | **需 `backend.is_connected`**，否則 HTTP 503 | **不需連線**，只要 `backend.device_ip` 可達 |
| 失敗回應 | HTTP 503 | HTTP 200 + `{"available": false}` |

> **為什麼不 gate `is_connected`**：webif 與 CIP 是兩條獨立傳輸。CIP session 掉了但設備還活著時，
> 這裡仍讀得到——而每模組的故障事件記憶正是那個時候最有價值。
> 也因此本端點**不丟 503**：抓不到只是補充資料缺席，不是錯誤路徑。
> 代價是設備真的不見時會等約 5 秒（兩支端點各 2.5 秒逾時），故前端採「進頁面讀一次 + 手動 ↻」，
> **不併入 1 Hz WebSocket 推送**。

> **NET LED 判讀**（ODVA Network Status LED 規範）：綠色恆亮＝至少有一條 CIP 連線在線；
> 綠色閃爍＝已上線但目前無 CIP 連線；紅閃＝連線逾時；紅恆亮＝IP 衝突。
> ⚠️ 它反映的是**任何 client** 的連線，不僅本程式，**不可拿來取代 `backend.is_connected`**。

**「LED 狀態」面板呈現**：狀態欄只畫燈點（`.led-dot`），不寫 `green` / `blinking-green` 等原始字串
（仍保留在 `title` 供除錯）。顏色與閃爍的完整判讀集中在標題列「ℹ️ 燈號說明」按鈕開啟的 modal
（顏色通則 + NET／MOD／通道燈各自意義）。燈色用獨立 token `--led-green` / `--led-red` / `--led-yellow`
（**不沿用** `--ok` / `--err` / `--amber`——那組為白天模式文字對比被加深，當小圓點會發灰），
兩個主題都是飽和發光色。故障面板的每模組通道表用 `table-layout: fixed` + `<colgroup>` 鎖欄寬，
確保多模組時各表對齊。

#### `GET /api/device/webif` 回應範例

```json
{
  "available": true,
  "powermodule": {
    "name": "CAPAROC PM EIP",
    "orderid": "1393553",
    "serialnumber": "1378815610",
    "hwversion": 0,
    "fwversion": "1.0.0",
    "dnsname": "caparoc1",
    "ip": "192.168.50.111",
    "mac": "cc:cc:ea:9f:c9:72",
    "leds": [
      { "name": "NET", "color": "green", "label": "Connected" }
    ],
    "voltage": 24.24,
    "totalcurrent": 0.4,
    "cumulativeerror": "off",
    "percent80error": "off",
    "totalcurrenterror": "off"
  },
  "modules": [
    {
      "index": 1,
      "name": "CAPAROC E4 12-24DC/1-4A",
      "serialnumber": "1378554559",
      "hwversion": 1,
      "fwversion": "1.0.2",
      "channels": 4,
      "nominal_min": 1,
      "nominal_max": 4,
      "nominal_range_label": "1–4 A",
      "fault_events": ["Overload channel 2"],
      "channels_data": [
        {
          "channel": 1, "nominalcurrent": 2, "current": 0.0, "led": "off",
          "errorid": 0, "errorid_text": "-", "errorcounter": 0
        }
      ]
    }
  ],
  "source": { "systeminfo": true, "processdata": true }
}
```

**欄位備註**：
- `percent80error` — 原廠鍵名是 `80percenterror`（開頭數字，JS 端存取不安全），已改名。
- `nominalcurrent` 為**整數安培不除**；`current` ÷10、`voltage` ÷100、`totalcurrent` ÷10。
- `source.processdata: false` 代表 `/webif/processdata` 沒抓到，即時欄位為 `null`、
  `channels_data` 為 `[]`，但靜態的模組清單與 `fault_events` 仍有效。
- `systeminfo` 抓不到 → 整支回 `{"available": false}`（沒有模組清單就沒有意義）。

#### `GET /api/history?minutes=5` 回應範例

```json
{
  "success": true,
  "minutes": 5,
  "data": [
    {
      "timestamp": "2026-05-25T14:30:00",
      "voltage": 24.1,
      "total_current": 3.2,
      "channels": [1.2, 0.8, 0.5, 0.7, ...]
    },
    ...
  ]
}
```

---

## 6. WebSocket 資料結構（`/ws`）

WebSocket 連線建立後，server 每秒推送狀態 JSON。

### 6.1 已連線時（`connected: true`）

```json
{
  "connected": true,
  "voltage": 24.15,
  "total_current": 3.2,
  "module_count": 2,
  "global_status": {
    "undervoltage": false,
    "overvoltage": false,
    "system_error": false,
    "warning_80pct": false,
    "total_current_shutdown": false
  },
  "channels": [
    {
      "channel": 1,
      "module": 1,
      "on": true,
      "current": 1.2,
      "nominal_current": 4,
      "warning_80pct": false,
      "overload": false,
      "short_circuit": false
    }
  ]
}
```

### 6.2 斷線時（`connected: false`）

```json
{
  "connected": false
}
```

**前端處理**：收到 `connected: false` 時顯示斷線橫幅，停止推送；呼叫 `POST /api/connect` 可重新連線。

> ⚠️ 寫入時 Status 欄位務必設為 `2`（No Change），避免誤關其他通道

---

## 4. 連線生命週期

```
啟動
  ↓
CIPDriver(ip).__enter__()      ← with 區塊進入
  ↓
check_device_connection()      ← 驗證連線 + 取得模組數
  ↓
check_global_system_status()   ← 初始安全檢查
  ↓
讀取 Input Assembly            ← 同步設備實際通道狀態至 output_data buffer
  ↓
_activate_connection_state()   ← connected=True，WEB UI 顯示 connected
  ↓
_start_heartbeat()             ← 閒置 300s 後自動保活
  ↓
主控制迴圈
  ↓
_stop_heartbeat() + stop_monitor()
  ↓
CIPDriver.__exit__()           ← 連線關閉
```

> ⚠️ **目前限制（3.6.1 尚未完成）**：連線生命週期綁定在 `with CIPDriver(...) as driver:` 區塊內，Web 服務長駐使用需等 3.6.1 重構後才支援。

---

## 5. 設定與 Log

### 5.1 IP 設定檔
- 路徑：`config/config.json` 的 `device` 區塊（舊的 `config/device_config.json` 已於
  設定檔合併時遷移，見 `src/app_config.py`）
- 格式：

  ```json
  "device": {
      "default_ip": "192.168.2.111",
      "recent": [
          {"ip": "192.168.50.111", "name": "CAPAROC-PM-EIP",
           "serial": "305419896", "last_connected": "2026-09-03T11:42:10"}
      ],
      "recent_max": 5
  }
  ```

| 鍵 | 誰寫 | 說明 |
|---|---|---|
| `default_ip` | CLI `setting [3]`、Web 連線成功時 | 開機自動連線的位址 |
| `recent` | **程式自動維護**，連線成功時更新 | Web 連線設定頁 IP 下拉清單，最新在前 |
| `recent_max` | 手動 | `recent` 保留筆數，讀取時夾在 1~50 |

- 讀取：`app_config.get("device", "default_ip")` / `app_config.recent_devices()`
- 寫入：`app_config.save_device_ip(ip)` / `app_config.record_connection(ip, name, serial)`
  / `app_config.forget_device_ip(ip)`
- 所有寫入都走 read-modify-write（`_write_config()`），**不會洗掉 logging/web 等其他區塊**

### 5.2 Log 系統
- 管理：`logging_manager.py`（`setup()` 初始化）
- 格式：`%(asctime)s [%(levelname)s] [%(log_module)s] %(message)s`
- 輸出：`src/logs/*.log`

**log_module 標籤**：

| 模組 | 觸發場景 |
|------|----------|
| `SYS` | 程式啟動/退出 |
| `CONN` | 連線成功/失敗 |
| `CTRL` | 通道開關操作 |
| `INIT` | 額定電流設定 |
| `SETTING` | IP 設定選單操作 |

---

## 6. Web UI 設計建議（參考）

### 6.1 主要顯示區塊

| 區塊 | 資料來源 | 建議更新頻率 |
|------|----------|-------------|
| 連線狀態 / IP | `check_device_connection()` | 初始化時 + 重連 |
| 系統狀態（電壓/電流/模組數） | `_read_current_status()` | 2s 輪詢 |
| 通道狀態（開關/電流/警告） | `_read_current_status()` | 2s 輪詢 |
| 設備網路設定 | `read_device_network_config()` | 按需讀取 |

### 6.2 主要控制動作

| 動作 | 呼叫方法 |
|------|----------|
| 開啟/關閉通道 | `backend.set_channel(ch, True/False)` |
| 設定額定電流 | `backend.set_nominal_current(module, channel, amps)` |
| 重新整理狀態 | `backend._read_current_status()` |
| 變更連線 IP | 修改 `backend.device_ip` + 重建 CIPDriver |
| 讀取設備 IP | `backend.read_device_network_config(driver)` |
| 硬寫設備 IP | `backend.set_device_ip(driver, new_ip, subnet, gateway)` |

### 6.3 連線生命週期（3.6.1 已完成）

Web UI 直接呼叫 `backend.connect()` / `backend.disconnect()` / `backend.is_connected`，無需 `with CIPDriver:` 區塊：

```python
backend = CaparocBackend("192.168.2.111")

# 啟動 Web 服務時
if backend.connect():
    print("已連線，可開始輪詢或 WebSocket 推送")

# 需要重連時
backend.disconnect()
backend.device_ip = "192.168.2.200"
backend.connect()

# 停止服務時
backend.disconnect()
```

---

*最後更新：2026-05-14*
