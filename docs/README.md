# Documentation 文件目錄

此目錄包含 Caparoc_breaker_control 專案的所有文件。

## 📚 快速導航

### 🎯 使用者文件
- **[CLI_USER_GUIDE.md](CLI_USER_GUIDE.md)** - 命令列使用指南
- **[DIAGNOSTIC_TOOLS_GUIDE.md](DIAGNOSTIC_TOOLS_GUIDE.md)** - 診斷工具使用指南

### 💻 開發文件
- **[PROGRAM_FLOW.md](PROGRAM_FLOW.md)** - 完整程式流程（v4.0，最新）
- **[INIT_COMMAND_FLOW.md](INIT_COMMAND_FLOW.md)** - 額定電流設定流程
- **[NOMINAL_CURRENT_IMPLEMENTATION.md](NOMINAL_CURRENT_IMPLEMENTATION.md)** - 實作細節
- **[DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md)** - 開發筆記

### 🔧 維護文件
- **[CHANGELOG.md](CHANGELOG.md)** - 版本更新歷史
- **[TODO.md](TODO.md)** - 開發計畫與功能路線圖

### 📦 特殊資料夾
- **[vendor/](vendor/)** - 原廠文件與配置檔案（EDS、手冊）
- **[history/](history/)** - 過時文件歸檔
- **[changelogs/](changelogs/)** - 詳細變更記錄

---

## 📂 資料夾說明

### [vendor/](vendor/) 🆕
存放原廠提供的文件和配置檔案
- **CAPAROC_PM_EIP.eds** - EtherNet/IP 設備描述檔
- **manual-Ch6~7.pdf** - 原廠操作手冊（第 6-7 章）
- 詳見: [vendor/README.md](vendor/README.md)

### [history/](history/)
存放已過時或被取代的歷史文件
- 舊版流程圖
- 已失敗的實作方案
- 早期測試分析
- 詳見: [history/README.md](history/README.md)

### [changelogs/](changelogs/)
詳細的版本變更記錄（按主題分類）
- CONNECTION_CHECK_FIX.md
- CONNECTION_CHECK_UPDATE.md
- RECONNECT_FEATURE.md

---

## 🔄 文件關係圖

```
使用者 → CLI_USER_GUIDE.md
  ↓
遇到問題 → DIAGNOSTIC_TOOLS_GUIDE.md

開發人員 → PROGRAM_FLOW.md → 程式碼實作
           (完整流程)

維護人員 → CHANGELOG.md + TODO.md

參考資料 → vendor/ (原廠文件)
歷史記錄 → history/ (過時文件)
```

---

## 📝 文件更新規範

### 更新時機

| 文件 | 更新時機 |
|------|----------|
| **PROGRAM_FLOW.md** | 程式流程邏輯變更時 |
| **CLI_USER_GUIDE.md** | 命令或操作變更時 |
| **DIAGNOSTIC_TOOLS_GUIDE.md** | 診斷工具功能變更時 |
| **CHANGELOG.md** | 每次版本發布時 |
| **TODO.md** | 完成/新增功能時 |

### 撰寫原則
- ✅ 使用清晰的中文說明
- ✅ 提供程式碼範例
- ✅ 包含決策理由
- ✅ 註明更新日期
- ✅ 保持與程式碼同步

---

## 🆕 最近更新

**2025-11-25**
- ✅ 創建 vendor/ 資料夾存放原廠文件
- ✅ 更新 PROGRAM_FLOW.md 至 v4.0
- ✅ 整理過時文件到 history/
- ✅ 簡化文件索引結構

**2025-11-13**
- ✅ 新增 DIAGNOSTIC_TOOLS_GUIDE.md
- ✅ 更新 CLI_USER_GUIDE.md

---

**Last Updated**: 2025年11月25日  
**Maintained by**: Project Team
