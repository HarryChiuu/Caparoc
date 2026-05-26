# CAPAROC 控制器 - 待實作功能清單

更新日期: 2026-05-25

## ✅ 已完成功能

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

##### 4.3.1 設定值外部化（config 管理）

> **目的**：將散落在程式碼中的硬編碼數字集中到 `config/web_config.json`，方便部署時調整  
> **預估工時**：1 小時

**目前硬編碼、可外部化的項目**：

| 設定項 | 目前位置 | 目前值 | 建議 key |
|--------|---------|--------|---------|
| Web 伺服器 port | `web/app.py` `__main__` | `8000` | `web_port` |
| WebSocket 推送間隔 | `web/app.py` ws_status | `1` 秒 | `ws_push_interval` |
| 額定電流有效範圍 | `src/caparoc_backend.py` | `1–20` A | `nominal_current_min/max` |
| 顯示小數位數（Web） | `web/static/js/app.js` fmt() | `1` 位 | `display_decimal_places` |
| 監控預設輪詢間隔（CLI） | CLI argument default | `2` 秒 | `monitor_interval_s` |

**備註**：`fmt()` 的 `.toFixed(1)` 只影響 Web UI；CLI 的 `:.1f` 在 `caparoc_backend.py` 獨立定義，兩者不共用。`nominal_current_range` 前後端共用，可透過 `GET /api/config/limits` 提供給前端。

**工作項目**：
- [ ] 建立 `config/web_config.json`（web_port, ws_push_interval, display_decimal_places）
- [ ] `web/app.py` 啟動時讀取 web_config.json
- [ ] `app.js` 從 `GET /api/config/limits` 取得 nominal_current_range，動態設定 input min/max
- [ ] `caparoc_backend.py` 從設定檔讀取 nominal range

**預估工時**：1 小時

---

##### 4.3.2 視覺一致性與元件統一化

> **目的**：統一按鈕、表格、卡片、提示訊息等 UI 元件的外觀語言

**工作項目**：
- [ ] 統一按鈕樣式（primary / secondary / danger 三種語義色彩）
- [ ] 狀態指示色彩系統（正常/警告/錯誤/離線 四種語義）
- [ ] 通道卡片尺寸與間距一致化
- [ ] 頁面載入骨架屏（loading skeleton）取代空白閃爍

**預估工時**：2-3 小時

---

##### 4.3.3 行動裝置基本支援

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

### Phase 5: 企業級功能 (未來規劃) 💡

#### 5.1 遠端訪問與控制
- [ ] Web API 介面 (RESTful)
- [ ] WebSocket 即時通訊
- [ ] 遠端監控網頁
- [ ] 身份驗證與權限管理

#### 5.2 高可用性設計
- [ ] 斷線自動重連優化
- [ ] 狀態持久化
- [ ] 故障轉移機制
- [ ] 負載均衡支援

#### 5.3 大數據與 AI 分析
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
| 高 | 4.3.1 設定值外部化（config 管理） | 1h |
| 高 | 4.4.1 CLI 通道詳細狀態顯示 | 2-3h |
| 中 | 4.3.2 UI 視覺一致性與元件統一 | 2-3h |
| 中 | 4.4.2/4.4.3 CLI 設備/網路資訊指令 | 1h |
| 中 | 4.5 數據記錄與分析 | 6-8h |
| 中 | 4.6 告警與通知系統 | 4-5h |
| 低 | 4.7 多設備管理 | 5-6h |
| 低 | 4.8 自動化測試與 CI/CD | 8-10h |

**Phase 4 預估剩餘工時**：29-41 小時

**Phase 5 未來願景** 💭
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


