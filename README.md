# CAPAROC PM EIP ECB 控制系統

> **版本**: v4.15.0（唯一真相來源：`src/version.py`）  
> **更新日期**: 2026-09-04
> **維護者**: Harry Chiu

CAPAROC 電子斷路器遠端控制程式，基於 EtherNet/IP 協議，支援多模組、多通道電流監控與控制。提供 **Web UI**（瀏覽器操作）與 **CLI** 兩種操作介面。

---

## 🚀 快速開始

### 1. 環境準備

```bash
# 啟動 Conda 環境（本機開發環境名為 sv；用 environment.yml 全新建立的話是 caparoc_breaker）
conda activate sv

# 安裝依賴
pip install -r requirements.txt

# 驗證環境可用（應輸出 81 passed，不需連接設備）
python -m pytest
```

> ⚠️ **一定要先 `conda activate`。** 直接用系統 Python 執行 `python -m pytest` 會
> 在收集階段就失敗（`ModuleNotFoundError: No module named 'pycomm3'`），
> 這不是測試壞掉，是跑錯直譯器。

### 2. 啟動程式

```bash
# 進入專案目錄
cd c:\Users\harry\Project\Caparoc5

# 建議：Web UI（瀏覽器操作）
python web/app.py
# 開啟瀏覽器 → http://localhost:8000

# 或：CLI
python src/caparoc_controller.py
```

### 3. Web UI 基本操作

側邊欄由上而下即操作流程：

| # | 頁面 | 功能 |
|---|------|------|
| 1 | 通道控制 | 通道卡片、開關按鈕、即時電流 |
| 2 | 設備監控 | 30 分鐘歷史曲線、zoom |
| 3 | 通道設定 | 額定電流設定、通道自訂名稱 |
| 4 | 系統狀態 | 設備識別與全域設定、設備自訂名稱 |
| 5 | 系統日誌 | 即時日誌、等級篩選 |
| 6 | 連線設定 | IP 表單、最近連線清單、網段掃描 |
| 7 | 初始設定 | 設備 IP 變更、DHCP 切換、新裝置初始配置 |

### 4. CLI 基本操作

```bash
init 1 4             # 設定 CH1 額定電流為 4A
on 1                 # 開啟通道 1
off 1                # 關閉通道 1
s                    # 顯示完整狀態
monitor start        # 啟動即時監控
h                    # 顯示幫助
q                    # 退出程式
```

**📖 完整使用說明**: [使用者指南](docs/USER_GUIDE.md)

---

## ⚙️ 設定檔

所有設定集中在 `config/config.json`（首次使用請複製 `config/config.example.json`）。
**所有鍵都在啟動時讀入，沒有熱重載——改完必須重啟。**

| 區塊 | 常用鍵 | 說明 |
|------|--------|------|
| `device` | `default_ip` | 啟動時嘗試連線的設備 IP |
| `web` | `port` | ⚠️ **僅 `python web/app.py` 生效**（見下） |
| `web` | `ws_push_interval` / `ws_idle_shutdown` | WebSocket 推送間隔／閒置自動關閉秒數 |
| `logging` | `log_level` / `log_dir` | 日誌等級與輸出目錄（相對路徑由 `src/paths.py` 的 `resolve_data_dir()` 解析：開發模式為專案根目錄，打包後為 exe 所在目錄） |
| `logging` | `retention_days` | 保留最近 N 天，**於 Web 服務啟動時**清除更舊的檔；`0` = 永不清除。CLI 不會觸發清除 |
| `nominal_current` | `min` / `max` | 額定電流可設定範圍（安培） |

### ⚠️ `web.port` 只在直接執行時生效

```bash
python web/app.py                  # ✅ 讀 config.json 的 web.port
uvicorn web.app:app --port 8001    # ❌ 完全忽略 web.port，須自行帶 --port
```

覆寫優先序（僅前者）：`--port N` > 環境變數 `CAPAROC_PORT` > `config.json` 的 `web.port`。

### 🚧 尚未實作的設定

- **`logging.remote.*`** — `RemoteHandler.emit()` 是空實作。`enabled` 改成 `true` 也不會推送任何東西，該區塊六個鍵全部無作用，僅為未來擴充保留的骨架。

---

## 📚 文件導覽

### 用戶文件
- **[使用者指南](docs/USER_GUIDE.md)** - Web UI 與 CLI 完整操作說明
- **[診斷工具指南](docs/DIAGNOSTIC_TOOLS_GUIDE.md)** - 連線診斷與問題排查

### 開發文件
- **[TODO.md](docs/TODO.md)** - 功能規劃與待實作項目
- **[通道自訂標籤規劃](docs/CHANNEL_LABELS_PLAN.md)** - 4.3.6 實作規劃與設計決策
- **[CHANGELOG.md](docs/CHANGELOG.md)** - 版本更新歷史
- **[WEB UI / API 參考](docs/WEB_UI_FEATURE_REFERENCE.md)** - Web UI 頁面、HTTP REST API、WebSocket 資料結構
- **[開發技術備忘錄](docs/DEVELOPMENT_NOTES.md)** - CIP lock 設計、IP LE-UDINT、WebSocket 斷線等技術細節
- **[程式流程說明](docs/CLI_PROGRAM_FLOW.md)** - 程式運作流程架構

### 技術文件
- **[額定電流實作指南](docs/NOMINAL_CURRENT_IMPLEMENTATION.md)** - Config Assembly 操作細節

---

## ✨ 主要功能

### Phase 3 已完成 ✅ (v3.2 - v3.7)

| 功能 | 說明 | 命令 |
|------|------|------|
| **額定電流設定** | Config Assembly Read-Modify-Write (1-20A) | `init <ch> <amps>` |
| **通道控制** | 開關控制，支援 1-64 通道 (多模組) | `on <ch>` / `off <ch>` |
| **狀態查詢** | 全域系統狀態與通道詳細資訊 | `s` / `status` |
| **即時監控** | 背景監控，支援靜默/顯示模式 | `monitor start/stop` |
| **多模組支援** | 自動檢測 1-16 個模組 (最多 64 通道) | 自動 |
| **IP 配置** | 啟動時可變更設備 IP | 互動式設定 |
| **自動重連** | 連線中斷時自動重試 | `reconnect` |

### Phase 4.0–4.2 已完成 ✅ (v4.0 - v4.2)

| 功能 | 說明 |
|------|------|
| **Web UI 基礎架構** | FastAPI + Vue 3（前端資源已 vendor 化至本地，可離線運行），7 個功能頁面 |
| **通道設定頁** | 額定電流表格，直接在瀏覽器操作 |
| **圖表監控頁** | 雙 Y 軸、模組分圖、zoom、30 分鐘歷史 |
| **系統日誌頁** | 等級篩選、顏色編碼、預載今日記錄 |
| **系統狀態頁** | Identity Object + Class 0x0F |
| **連線設定頁** | IP 表單 + 網路資訊面板（IP / MAC / 閘道） |
| **多執行緒安全** | `_cip_lock` 序列化所有 generic_message 呼叫 |

### Phase 4.3–5.1 已完成 ✅ (2026-08 ~ 2026-09)

| 功能 | 說明 |
|------|------|
| **初始設定頁** | 設備 IP 變更、DHCP 切換、新裝置初始配置（BOOTP），含失聯救援指引 |
| **設備主機名稱** | CIP 0xF5 **Attr 6** 讀寫，寫入後回讀驗證；實機確認立即生效不需重啟 |
| **通道自訂標籤** | 以設備序號綁定的通道／設備命名，存於 `config.json` 的 `labels` 區塊 |
| **最近連線 IP** | 連線設定頁下拉清單 + 頁內網段掃描，兩條路互補 |
| **額定電流型號驗證** | 依模組型號判定可設定範圍，區分「固定額定型號」與「旋鈕未轉 RC」 |
| **日誌保留機制** | `retention_days` 接上 `cleanup_old_logs()`，Web 服務啟動時清除逾期檔 |
| **主控台編碼防護** | 修正 stdout 導向時 cp950 編碼錯誤被誤判為設備連線失敗 |
| **路徑抽象化** | `src/paths.py` 區分內嵌資源（唯讀）與外部資料（可讀寫），為打包鋪路 |
| **版本號單一真相來源** | `src/version.py` 驅動前端資源 `?v=` cache-busting |
| **UI 調整** | 側邊欄依現場流程重排、預設白天主題、關閉鈕改為明確文字 |

> ⚠️ **Attr 5 vs Attr 6**：主機名稱是 Attr 6；Attr 5 是整包 IP/遮罩/閘道/DNS，
> 與 `set_device_ip()` 同一個 attribute，誤寫會讓設備失聯。
> 詳見 [DEVELOPMENT_NOTES.md](docs/DEVELOPMENT_NOTES.md)。

### 🚧 進行中 / 下一步

| 項目 | 說明 |
|------|------|
| **4.4.1 CLI 通道詳細狀態** | `s <ch>` 單通道詳細、電流使用率、狀態 bit 0-5 解析 |
| **5.3 PyInstaller 打包** | 產出單一 `caparoc.exe`（前置 5.1 路徑抽象化已完成） |

詳見 [TODO.md](docs/TODO.md) 及 [CHANGELOG.md](docs/CHANGELOG.md)

---

## 💻 使用範例

### 場景 1: 首次使用

```bash
# 啟動程式
python src/caparoc_controller.py

# 程式啟動後
🎮 > s             # 檢查當前狀態
🎮 > init 1 4      # 設定 CH1 額定電流 4A
🎮 > init 2 4      # 設定 CH2 額定電流 4A
🎮 > on 1          # 開啟 CH1
🎮 > on 2          # 開啟 CH2
🎮 > s             # 確認狀態
```

### 場景 2: 長時間監控

```bash
# 啟動靜默監控（推薦）
🎮 > monitor start 5 silent

✅ 監控已啟動 (5秒更新, 靜默模式)
   只在狀態變化時顯示警報

# 可以繼續輸入其他命令
🎮 > s

# 有變化時自動提示
⚠️  [14:32:15] 通道狀態變化:
   - CH1: OFF → ON (0.45A)

# 結束時停止監控
🎮 > monitor stop
🎮 > q
```

### 場景 3: 多模組環境

```bash
🎮 > s

============================================================
  📊 系統狀態
============================================================
  模組數量: 2 個 (8 通道)
  系統電壓: 24.18 V
  總電流:   2.35 A
------------------------------------------------------------
【模組 1】
  M1.CH1 (#1): 🟢 ON  |   0.45 A
  M1.CH2 (#2): ⚫ OFF |   0.00 A
  M1.CH3 (#3): 🟢 ON  |   0.75 A
  M1.CH4 (#4): ⚫ OFF |   0.00 A

【模組 2】
  M2.CH1 (#5): 🟢 ON  |   0.52 A
  M2.CH2 (#6): 🟢 ON  |   0.63 A
  M2.CH3 (#7): ⚫ OFF |   0.00 A
  M2.CH4 (#8): ⚫ OFF |   0.00 A
============================================================

# 分別控制不同模組的通道
🎮 > init 5 6      # 設定模組2通道1 (全域#5) 為 6A
🎮 > on 5          # 開啟模組2通道1
```

---

## 🔧 連接問題排查

如果遇到連接錯誤，可以使用診斷工具：

```bash
# 執行連接診斷
python tests/check_connection.py
```

常見問題與解決方案請參閱 [診斷工具指南](docs/DIAGNOSTIC_TOOLS_GUIDE.md)

---

## 📊 專案結構

```
Caparoc5/
├── src/
│   ├── caparoc_backend.py        # 裝置邏輯層（CIP 通訊，~2370 行）
│   ├── caparoc_controller.py     # CLI 包裝層（繼承 backend，~975 行）
│   ├── caparoc_ip_config.py      # 新裝置初始設定 CLI（BOOTP / IP 變更）
│   ├── caparoc_ip_core.py        # IP / 網段 / 掃描的純函式層
│   ├── caparoc_http.py           # 設備 HTTP 介面輔助
│   ├── app_config.py             # config.json 讀寫（含 labels 區塊）
│   ├── paths.py                  # 路徑解析（內嵌資源 vs 外部資料，打包相容）
│   ├── version.py                # 版本號唯一真相來源
│   ├── console_io.py             # 主控台編碼防護
│   └── logging_manager.py        # 日誌管理
├── web/
│   ├── app.py                    # FastAPI 服務（~1350 行）
│   ├── templates/index.html      # Vue 3 頁面（7 個功能頁）
│   └── static/                   # JS / CSS / vendor（離線資源）
├── tests/                        # 自動化測試（`python -m pytest`，不需實機）
│   ├── test_*.py                 # pytest 測試，81 項
│   ├── diagnostic_tools.py       # 診斷工具集
│   ├── check_connection.py       # 連線檢查工具
│   └── manual/                   # 需實機／需管理員權限的互動式工具，pytest 不收集
├── docs/                         # 完整文件
│   ├── USER_GUIDE.md             # 使用者指南 ⭐
│   ├── WEB_UI_FEATURE_REFERENCE.md  # API / WebSocket 參考
│   ├── TODO.md                   # 功能規劃
│   ├── CHANGELOG.md              # 版本歷史
│   ├── DEVELOPMENT_NOTES.md      # 技術備忘錄
│   ├── CLI_PROGRAM_FLOW.md       # CLI 程式流程
│   ├── CHANNEL_LABELS_PLAN.md    # 4.3.6 通道標籤規劃
│   ├── DIAGNOSTIC_TOOLS_GUIDE.md # 診斷指南
│   ├── NOMINAL_CURRENT_IMPLEMENTATION.md
│   ├── diagrams/                 # 架構圖
│   ├── history/                  # 歷史文件
│   └── vendor/                   # 原廠文件
├── archive/                      # 封存檔案
├── config/                       # 設定檔（config.json，複製自 config.example.json）
├── logs/                         # 執行日誌
├── .gitmessage                   # Git commit 模板
├── requirements.txt              # Python 套件需求
└── environment.yml               # Conda 環境配置
```

---

## 🔄 開發里程碑

> ⚠️ **這不是發布版本列表。** 本專案目前**沒有 git tag**，`src/version.py`
> 只保存當前版本號（v4.15.0），[CHANGELOG.md](docs/CHANGELOG.md) 則以**日期**分節、
> 不帶版本號。因此下表只列出**里程碑與日期**，不替歷史變更編造版本號。
> 要查某次改動的細節，請直接看 CHANGELOG 的日期條目。

| 期間 | 里程碑 |
|------|--------|
| 2026-09 | 主機名稱設定（CIP 0xF5 Attr 6）、通道自訂標籤、路徑抽象化（`src/paths.py`）、版本號單一真相來源、測試套件修復 |
| 2026-08 | 初始設定頁（IP／DHCP／BOOTP）、DHCP 失聯救援、CIP 並發修正、額定電流型號驗證、最近連線 IP 與網段掃描 |
| 2026-05 | **v4.0–v4.2** Web UI 基礎架構（FastAPI + Vue 3）、圖表監控頁、系統狀態頁、連線設定頁 |
| 2025-10 ~ 2025-11 | **v3.5–v3.7** 多模組支援、即時監控、額定電流設定強化、文件重組 |

詳見 [CHANGELOG.md](docs/CHANGELOG.md)

---

## 🛠️ 技術規格

- **通訊協議**: EtherNet/IP (CIP)
- **Python 版本**: 3.11+（開發與測試基準為 **3.12**，見 `environment.yml`）
- **主要依賴**: pycomm3 >= 1.2.14
- **支援設備**: CAPAROC PM EIP(EtherNet/IP)
- **支援模組**: 1-16 個 (每模組 4 通道)
- **總通道數**: 最多 64 個
- **電流範圍**: 0-25.5A (讀取), 1-20A (設定)
- **電壓範圍**: 9.0-30.5V

---

## 📝 授權

尚未指定授權條款（專案根目錄無 `LICENSE` 檔）。在補上之前，請視為
**保留所有權利**，對外散布前先與維護者確認。

---

## 🆘 取得協助

### 文件
- **使用問題** → [USER_GUIDE.md](docs/USER_GUIDE.md) - Web UI 與 CLI 操作方式
- **連接問題** → [DIAGNOSTIC_TOOLS_GUIDE.md](docs/DIAGNOSTIC_TOOLS_GUIDE.md) - 連線診斷和問題排查
- **API 查詢** → [WEB_UI_FEATURE_REFERENCE.md](docs/WEB_UI_FEATURE_REFERENCE.md) - HTTP REST 端點與 WebSocket 格式
- **開發問題** → [DEVELOPMENT_NOTES.md](docs/DEVELOPMENT_NOTES.md) - 技術細節和實作說明
- **額定電流** → [NOMINAL_CURRENT_IMPLEMENTATION.md](docs/NOMINAL_CURRENT_IMPLEMENTATION.md) - 額定電流設定完整指南

### GitHub
- 提交 Issue: https://github.com/HarryChiuu/Caparoc
- 查看規劃: [TODO.md](docs/TODO.md) - 功能開發路線圖

---

**專案維護**: Harry Chiu  
**最後更新**: 2026年5月25日
