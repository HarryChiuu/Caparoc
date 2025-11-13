# Documentation 文件目錄

此目錄包含 Caparoc_breaker_control 專案的所有文件。

## 📚 快速導航

### 🎯 使用者文檔
適合一般操作人員查閱
- **[CLI_USER_GUIDE.md](CLI_USER_GUIDE.md)** - 命令列使用指南
- **[DIAGNOSTIC_TOOLS_GUIDE.md](DIAGNOSTIC_TOOLS_GUIDE.md)** - 診斷工具使用指南 🆕

### 💻 開發文檔
適合開發人員和技術人員
- **[MAIN_PROGRAM_FLOW.md](MAIN_PROGRAM_FLOW.md)** - 主程式運作流程詳解 🆕
- **[PROGRAM_FLOWCHART.md](PROGRAM_FLOWCHART.md)** - 程式流程圖（Mermaid） 🆕
- **[PROGRAM_FLOW.md](PROGRAM_FLOW.md)** - 程式執行流程圖（舊版）
- **[DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md)** - 開發筆記

### 🔧 維護文檔
適合專案維護
- **[CHANGELOG.md](CHANGELOG.md)** - 版本更新歷史
- **[TODO.md](TODO.md)** - 開發計畫與功能路線圖
- **[TROUBLESHOOTING_CONNECTION.md](TROUBLESHOOTING_CONNECTION.md)** - 連線故障排除

---

## 📖 詳細文件清單

### 使用者文檔

#### [CLI_USER_GUIDE.md](CLI_USER_GUIDE.md)
主程式命令列操作指南
- ✅ 互動式命令說明
- ✅ 使用範例與情境
- ✅ 常見問題排除
- **適用對象**: 一般操作人員
- **更新日期**: 2025-11-13

#### [DIAGNOSTIC_TOOLS_GUIDE.md](DIAGNOSTIC_TOOLS_GUIDE.md) 🆕
診斷工具完整使用指南
- ✅ 5 個診斷工具詳細說明
- ✅ 常見診斷情境與解決方案
- ✅ 輸出解讀指南
- ✅ Assembly 資料格式解析
- **適用對象**: 技術人員、除錯人員
- **更新日期**: 2025-11-13

---

### 開發文檔

#### [MAIN_PROGRAM_FLOW.md](MAIN_PROGRAM_FLOW.md) 🆕
主控制程式完整流程說明
- ✅ 程式架構概述
- ✅ 啟動流程 6 大步驟詳解
- ✅ 核心功能流程（init, on/off, monitor）
- ✅ Assembly 通訊機制
- ✅ 多模組支援機制
- **適用對象**: 開發人員
- **更新日期**: 2025-11-13

#### [PROGRAM_FLOWCHART.md](PROGRAM_FLOWCHART.md) 🆕
程式流程圖（Mermaid 格式）
- ✅ 主程式啟動流程圖
- ✅ 標稱電流設定流程圖
- ✅ 通道控制流程圖
- ✅ 即時監控流程圖
- ✅ 重連機制流程圖
- ✅ Assembly 通訊架構圖
- **適用對象**: 開發人員、視覺化學習
- **更新日期**: 2025-11-13

#### [PROGRAM_FLOW.md](PROGRAM_FLOW.md)
程式執行流程圖（舊版）
- ⚠️ 部分內容可能已過時
- 📋 建議參考新版 MAIN_PROGRAM_FLOW.md
- **更新日期**: 2025-10-28

#### [DEVELOPMENT_NOTES.md](DEVELOPMENT_NOTES.md)
開發過程記錄與筆記
- 技術決策理由
- 實作細節
- 已知限制

#### [Config_Assembly_驗證報告.md](Config_Assembly_驗證報告.md)
Config Assembly 寫入測試報告
- 測試結果記錄
- Parameter Object 方法驗證
- 最佳實踐建議

#### [caparoc_implicit_test_analysis.md](caparoc_implicit_test_analysis.md)
Implicit Messaging 測試分析
- 功能測試記錄
- 效能分析
- 最佳實踐建議

---

### 維護文檔

#### [CHANGELOG.md](CHANGELOG.md)
版本更新歷史
- ✅ 所有版本的變更記錄
- ✅ Bug 修復追蹤
- ✅ 功能新增歷史
- **更新日期**: 2025-11-13

#### [TODO.md](TODO.md)
開發計畫與功能路線圖
- Phase 1 ✅ (V3.2): 互動式電流設定
- Phase 2 ✅ (V3.3): 增強狀態顯示
- Phase 3 📋: 進階功能規劃
- **更新日期**: 2025-10-28

#### [TROUBLESHOOTING_CONNECTION.md](TROUBLESHOOTING_CONNECTION.md)
連線問題故障排除
- 常見連線問題
- 診斷步驟
- 解決方案

#### [標稱電流設定流程與故障排除.md](標稱電流設定流程與故障排除.md)
標稱電流設定專題文檔
- 設定流程詳解
- 故障排除指南

---

## 📂 子目錄

### [changelogs/](changelogs/)
版本變更詳細記錄
- CONNECTION_CHECK_FIX.md
- CONNECTION_CHECK_UPDATE.md
- RECONNECT_FEATURE.md

---

## 🔄 文件關係圖

```
使用者 → CLI_USER_GUIDE.md ─────┐
  ↓                              │
遇到問題                         │
  ↓                              ↓
TROUBLESHOOTING_CONNECTION.md → DIAGNOSTIC_TOOLS_GUIDE.md
                                  
開發人員 → MAIN_PROGRAM_FLOW.md ─┬─→ PROGRAM_FLOWCHART.md
           (文字說明)             │   (視覺化圖表)
                                  │
                                  └─→ 程式碼實作
```

---

## � 文件更新規範

### 何時更新文件

| 文檔 | 更新時機 | 負責人 |
|------|----------|--------|
| **MAIN_PROGRAM_FLOW.md** | 程式流程邏輯變更時 | 開發人員 |
| **PROGRAM_FLOWCHART.md** | 流程圖需要更新時 | 開發人員 |
| **DIAGNOSTIC_TOOLS_GUIDE.md** | 診斷工具功能變更時 | 技術人員 |
| **CLI_USER_GUIDE.md** | 命令或操作變更時 | 文檔維護人員 |
| **TODO.md** | 完成/新增功能時 | 專案負責人 |
| **CHANGELOG.md** | 每次版本發布時 | 開發人員 |

### 文件撰寫原則
- ✅ 使用清晰的中文說明
- ✅ 提供程式碼範例
- ✅ 包含決策理由
- ✅ 註明更新日期和版本
- ✅ 保持與程式碼同步

### 新增文檔檢查清單
- [ ] 文檔標題和目的明確
- [ ] 目錄結構完整
- [ ] 包含實際範例
- [ ] 更新日期已註明
- [ ] 已加入 docs/README.md 索引
- [ ] 相關連結已更新

## 🔗 相關連結

- [專案主 README](../README.md)
- [AI Agent 規則](../AIagent_init.md)
- [原始碼目錄](../src/)
- [測試工具目錄](../tests/)
- [歷史歸檔](../archive/)

---

## 🆕 最近更新

**2025-11-13**
- ✅ 新增 MAIN_PROGRAM_FLOW.md - 主程式完整流程說明
- ✅ 新增 PROGRAM_FLOWCHART.md - Mermaid 流程圖
- ✅ 新增 DIAGNOSTIC_TOOLS_GUIDE.md - 診斷工具使用指南
- ✅ 更新 README.md - 重新組織文檔結構
- ✅ 重構主程式 - 分離診斷工具到 tests/

**2025-10-28**
- 更新 TODO.md - Phase 3 功能規劃
- 更新 CHANGELOG.md - V3.3 版本記錄

---
**Last Updated**: 2025年11月13日  
**Maintained by**: Project Team
