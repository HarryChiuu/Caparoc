# CAPAROC 電子斷路器控制系統

> **版本**: v4.2  
> **更新日期**: 2026-05-25  
> **維護者**: Harry Chiu

CAPAROC 電子斷路器遠端控制程式，基於 EtherNet/IP 協議，支援多模組、多通道電流監控與控制。提供 **Web UI**（瀏覽器操作）與 **CLI** 兩種操作介面。

---

## 🚀 快速開始

### 1. 環境準備

```bash
# 啟動 Conda 環境
conda activate your_env_name

# 安裝依賴
pip install -r requirements.txt
```

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

| 頁面 | 功能 |
|------|------|
| 儀表板 | 通道卡片、開關按鈕、即時電流 |
| 通道設定 | 額定電流設定 |
| 圖表監控 | 30 分鐘歷史曲線、zoom |
| 系統日誌 | 即時日誌、等級篩選 |
| 系統狀態 | 設備識別與全域設定 |
| 連線設定 | IP 表單、網路資訊 |

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

## 📚 文件導覽

### 用戶文件
- **[使用者指南](docs/USER_GUIDE.md)** - Web UI 與 CLI 完整操作說明
- **[診斷工具指南](docs/DIAGNOSTIC_TOOLS_GUIDE.md)** - 連線診斷與問題排查

### 開發文件
- **[TODO.md](docs/TODO.md)** - 功能規劃與待實作項目
- **[CHANGELOG.md](docs/CHANGELOG.md)** - 版本更新歷史
- **[WEB UI / API 參考](docs/WEB_UI_FEATURE_REFERENCE.md)** - Web UI 頁面、HTTP REST API、WebSocket 資料結構
- **[開發技術備忘錄](docs/DEVELOPMENT_NOTES.md)** - CIP lock 設計、IP LE-UDINT、WebSocket 斷線等技術細節
- **[程式流程說明](docs/PROGRAM_FLOW.md)** - 程式運作流程架構

### 技術文件
- **[額定電流實作指南](docs/NOMINAL_CURRENT_IMPLEMENTATION.md)** - Config Assembly 操作細節

---

## ✨ 主要功能

### Phase 3 已完成 ✅ (v3.2 - v3.7)

| 功能 | 說明 | 命令 |
|------|------|------|
| **額定電流設定** | Config Assembly Read-Modify-Write (1-10A) | `init <ch> <amps>` |
| **通道控制** | 開關控制，支援 1-64 通道 (多模組) | `on <ch>` / `off <ch>` |
| **狀態查詢** | 全域系統狀態與通道詳細資訊 | `s` / `status` |
| **即時監控** | 背景監控，支援靜默/顯示模式 | `monitor start/stop` |
| **多模組支援** | 自動檢測 1-16 個模組 (最多 64 通道) | 自動 |
| **IP 配置** | 啟動時可變更設備 IP | 互動式設定 |
| **自動重連** | 連線中斷時自動重試 | `reconnect` |

### Phase 4.0–4.2 已完成 ✅ (v4.0 - v4.2)

| 功能 | 說明 |
|------|------|
| **Web UI 基礎架構** | FastAPI + Vue 3 CDN，6 個功能頁面 |
| **通道設定頁** | 額定電流表格，直接在瀏覽器操作 |
| **圖表監控頁** | 雙 Y 軸、模組分圖、zoom、30 分鐘歷史 |
| **系統日誌頁** | 等級篩選、顏色編碼、預載今日記錄 |
| **系統狀態頁** | Identity Object + Class 0x0F |
| **連線設定頁** | IP 表單 + 網路資訊面板（IP / MAC / 閘道） |
| **多執行緒安全** | `_cip_lock` 序列化所有 generic_message 呼叫 |

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
│   ├── caparoc_backend.py        # 裝置邏輯層（CIP 通訊，~750 行）
│   ├── caparoc_controller.py     # CLI 包裝層（繼承 backend，~874 行）
│   └── logging_manager.py        # 日誌管理
├── web/
│   ├── app.py                    # FastAPI 服務（~550 行）
│   ├── templates/index.html      # Vue 3 CDN 頁面
│   └── static/                   # JS / CSS
├── tests/
│   ├── diagnostic_tools.py       # 診斷工具集
│   └── check_connection.py       # 連線檢查工具
├── docs/                         # 完整文件
│   ├── USER_GUIDE.md             # 使用者指南 ⭐
│   ├── WEB_UI_FEATURE_REFERENCE.md  # API / WebSocket 參考
│   ├── TODO.md                   # 功能規劃
│   ├── CHANGELOG.md              # 版本歷史
│   ├── DEVELOPMENT_NOTES.md      # 技術備忘錄
│   ├── PROGRAM_FLOW.md           # 程式流程
│   ├── DIAGNOSTIC_TOOLS_GUIDE.md # 診斷指南
│   ├── NOMINAL_CURRENT_IMPLEMENTATION.md
│   ├── history/                  # 歷史文件
│   └── vendor/                   # 原廠文件
├── archive/                      # 封存檔案
├── config/                       # 設定檔（device_ip 等）
├── logs/                         # 執行日誌
├── .gitmessage                   # Git commit 模板
├── requirements.txt              # Python 套件需求
└── environment.yml               # Conda 環境配置
```

---

## 🔄 版本歷史

- **v4.2** (2026-05-25) - 系統狀態頁、連線設定頁、頂部關閉按鈕、Bug fixes（CIP 鎖、IP 做變、重連）
- **v4.1** (2026-05-21) - 圖表監控頁（Chart.js + zoom）、設備網路資訊 API
- **v4.0** (2026-05-18) - Web UI 基礎架構（FastAPI + Vue 3）、導覽列、通道設定頁、系統日誌頁
- **v3.8** (2026-05-14) - controller.py 延负 shadow 方法清除
- **v3.7** (2025-11-26) - 額定電流設定測化、文件重組
- **v3.5–3.6** (2025-10-28) - 多模組、即時監控、內部重構

詳見 [CHANGELOG.md](docs/CHANGELOG.md)

---

## 🛠️ 技術規格

- **通訊協議**: EtherNet/IP (CIP)
- **Python 版本**: 3.11+
- **主要依賴**: pycomm3 >= 1.2.14
- **支援設備**: CAPAROC PM EIP(EtherNet/IP)
- **支援模組**: 1-16 個 (每模組 4 通道)
- **總通道數**: 最多 64 個
- **電流範圍**: 0-25.5A (讀取), 1-20A (設定)
- **電壓範圍**: 9.0-30.5V

---

## 📝 授權


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
