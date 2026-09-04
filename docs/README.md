# Documentation 文件目錄

此目錄包含 **CAPAROC PM EIP ECB 控制系統**（`Caparoc5`）的所有文件。

## 📚 快速導航

### 🎯 使用者文件
- **[USER_GUIDE.md](USER_GUIDE.md)** - 使用者操作指南（Web UI + CLI）
- **[DIAGNOSTIC_TOOLS_GUIDE.md](DIAGNOSTIC_TOOLS_GUIDE.md)** - 診斷工具使用指南

### 💻 開發文件
- **[CLI_PROGRAM_FLOW.md](CLI_PROGRAM_FLOW.md)** - CLI 完整程式流程（caparoc_controller + backend）
- **[WEB_UI_FEATURE_REFERENCE.md](WEB_UI_FEATURE_REFERENCE.md)** - Web UI 頁面、HTTP REST API 與 WebSocket 參考
- **[NOMINAL_CURRENT_IMPLEMENTATION.md](NOMINAL_CURRENT_IMPLEMENTATION.md)** - 額定電流設定實作細節
- **[DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md)** - 開發技術備忘錄
- **[CHANNEL_LABELS_PLAN.md](CHANNEL_LABELS_PLAN.md)** - 通道自訂標籤（4.3.6）實作規劃與設計決策

### 🔧 維護文件
- **[CHANGELOG.md](CHANGELOG.md)** - 版本更新歷史
- **[TODO.md](TODO.md)** - 開發計畫與功能路線圖

### 📦 特殊資料夾
- **[vendor/](vendor/)** - 原廠文件與配置檔案（EDS、手冊）
- **[history/](history/)** - 過時文件歸檔
- **[diagrams/](diagrams/)** - 架構圖與流程圖（HTML + PNG）

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

### [diagrams/](diagrams/)
架構圖與流程圖，每張都有 HTML（可互動、深淺色主題）與 PNG 兩種格式
- **caparoc-architecture** - 系統架構圖
- **caparoc-cli-workflow** - CLI 操作流程圖

---

## 🔄 文件關係圖

```
使用者 → USER_GUIDE.md（Web UI 主要操作方式）
  ↓
遇到問題 → DIAGNOSTIC_TOOLS_GUIDE.md

開發人員 → CLI_PROGRAM_FLOW.md → 程式碼實作
           WEB_UI_FEATURE_REFERENCE.md → HTTP API / WebSocket

維護人員 → CHANGELOG.md + TODO.md

參考資料 → vendor/ (原廠文件)
架構圖   → diagrams/ (系統架構、CLI 流程)
歷史記錄 → history/ (過時文件)
```

---

## 📝 文件更新規範

### 更新時機

| 文件 | 更新時機 |
|------|----------|
| **CLI_PROGRAM_FLOW.md** | 程式流程邏輯變更時 |
| **USER_GUIDE.md** | 命令、頁面或操作方式變更時 |
| **WEB_UI_FEATURE_REFERENCE.md** | 新增 API 端點或頁面時 |
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

文件與程式碼的變更一律記錄在 **[CHANGELOG.md](CHANGELOG.md)**（以日期分節）。

> 這裡**刻意不再維護第二份變更清單**。原本的「最近更新」章節停在 2026-05-25、
> 落後三個多月都沒人發現，正說明重複的來源只會過期。要查最近改了什麼，
> 一律看 CHANGELOG。

---

**Maintained by**: Harry Chiu
