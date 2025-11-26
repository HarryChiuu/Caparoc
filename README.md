# CAPAROC 電子斷路器控制系統

> **版本**: v3.7  
> **更新日期**: 2025-11-26  
> **維護者**: Harry Chiu

CAPAROC 電子斷路器遠端控制程式，基於 EtherNet/IP 協議，支援多模組、多通道電流監控與控制。

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

# 啟動控制器
python src/caparoc_controller.py

# 或指定 IP 位址
python src/caparoc_controller.py --ip 192.168.1.100
```

### 3. 基本操作

```bash
init 1 4             # 設定 CH1 額定電流為 4A
on 1                 # 開啟通道 1
off 1                # 關閉通道 1
s                    # 顯示完整狀態
monitor start        # 啟動即時監控
h                    # 顯示幫助
q                    # 退出程式
```

**📖 完整使用說明**: [CLI 使用指南](docs/CLI_USER_GUIDE.md)

---

## 📚 文檔導覽

### 用戶文檔
- **[CLI 使用指南](docs/CLI_USER_GUIDE.md)** - 完整命令說明與使用範例
- **[程式流程說明](docs/PROGRAM_FLOW.md)** - 程式運作流程

### 開發文檔
- **[TODO.md](docs/TODO.md)** - 功能規劃與待實作項目
- **[CHANGELOG.md](docs/CHANGELOG.md)** - 版本更新歷史
- **[開發技術備忘錄](docs/DEVELOPMENT_NOTES.md)** - 技術決策與經驗教訓
- **[診斷工具指南](docs/DIAGNOSTIC_TOOLS_GUIDE.md)** - 問題診斷與排查

### 技術文檔
- **[額定電流實作指南](docs/NOMINAL_CURRENT_IMPLEMENTATION.md)** - Config Assembly 操作細節
- **[初始化命令流程](docs/INIT_COMMAND_FLOW.md)** - init 命令實作流程

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

### Phase 4 規劃中 🚧

詳見 [TODO.md](docs/TODO.md)：
- 通道狀態資訊擴增
- GUI 圖形介面開發
- 數據記錄與分析
- 告警通知系統
- 多設備管理
- 自動化測試與 CI/CD

---

## 💻 使用範例

### 場景 1: 首次使用

```bash
# 啟動程式
python src/caparoc_controller.py

# 程式啟動後
🎮 > s              # 檢查當前狀態
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
│   └── caparoc_controller.py     # 主控制程式 (v3.7)
├── tests/
│   ├── diagnostic_tools.py       # 診斷工具集
│   └── check_connection.py       # 連線檢查工具
├── docs/                         # 完整文檔
│   ├── CLI_USER_GUIDE.md         # 使用者指南 ⭐
│   ├── TODO.md                   # 功能規劃
│   ├── CHANGELOG.md              # 版本歷史
│   ├── DEVELOPMENT_NOTES.md      # 技術備忘錄
│   ├── PROGRAM_FLOW.md           # 程式流程
│   ├── DIAGNOSTIC_TOOLS_GUIDE.md # 診斷指南
│   ├── NOMINAL_CURRENT_IMPLEMENTATION.md  # 額定電流設定實作
│   ├── INIT_COMMAND_FLOW.md      # init 命令流程
│   ├── history/                  # 歷史文檔
│   └── vendor/                   # 原廠文檔
├── archive/                      # 舊版本程式碼
├── output/                       # 輸出文件
├── .gitmessage                   # Git commit 模板
├── requirements.txt              # Python 依賴
└── environment.yml               # Conda 環境配置
```

---

## 🔄 版本歷史

- **v3.7** (2025-11-26) - 額定電流設定優化、文檔重組
- **v3.6** (2025-10-28) - 即時監控功能 (靜默/顯示模式)
- **v3.5** (2025-10-28) - 多模組架構支援 (1-16 模組)
- **v3.4** (2025-10-28) - 全域系統狀態檢查
- **v3.3** (2025-10-27) - 狀態顯示增強
- **v3.2** (2025-10-27) - 互動式額定電流設定

詳見 [CHANGELOG.md](docs/CHANGELOG.md)

---

## 🛠️ 技術規格

- **通訊協議**: EtherNet/IP (CIP)
- **Python 版本**: 3.11+
- **主要依賴**: pycomm3 >= 1.2.14
- **支援設備**: CAPAROC PM (EtherNet/IP)
- **支援模組**: 1-16 個 (每模組 4 通道)
- **總通道數**: 最多 64 個
- **電流範圍**: 0-25.5A (讀取), 1-20A (設定)
- **電壓範圍**: 9.0-30.5V

---

## 📝 授權

MIT License

---

## 🆘 取得協助

### 文檔
- 使用問題 → [CLI_USER_GUIDE.md](docs/CLI_USER_GUIDE.md)
- 連接問題 → [DIAGNOSTIC_TOOLS_GUIDE.md](docs/DIAGNOSTIC_TOOLS_GUIDE.md)
- 開發問題 → [DEVELOPMENT_NOTES.md](docs/DEVELOPMENT_NOTES.md)

### GitHub
- 提交 Issue: https://github.com/cFuuu/Caparoc
- 查看規劃: [TODO.md](docs/TODO.md)

---

**專案維護**: Harry Chiu  
**最後更新**: 2025年11月26日
