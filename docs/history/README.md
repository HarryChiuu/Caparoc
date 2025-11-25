# 歷史文檔存檔

此資料夾包含已過時或被新方案取代的歷史文檔，保留作為參考用途。

## 📁 文件說明

### Config Assembly 相關（已棄用）

- **Config_Assembly_驗證報告.md**
  - 狀態: ❌ 已失敗
  - 原因: Config Assembly 在運行時為唯讀，無法用於動態修改參數
  - 替代方案: 使用 Parameter Object (Class 0x0F) 逐個修改參數
  - 保留原因: 記錄測試過程和失敗原因

### 早期測試與分析

- **caparoc_implicit_test_analysis.md**
  - 狀態: ⚠️ 過時
  - 說明: 早期 Implicit Messaging 測試分析
  - 替代方案: 現已整合到主程式架構中
  - 保留原因: 技術參考和學習資料

- **標稱電流設定流程與故障排除.md**
  - 狀態: ⚠️ 過時
  - 說明: 舊版標稱電流設定流程文檔
  - 替代方案: 參考 `INIT_COMMAND_FLOW.md`
  - 保留原因: 記錄功能演進過程

### 早期問題排查

- **TROUBLESHOOTING_CONNECTION.md**
  - 狀態: ⚠️ 過時
  - 說明: 早期連接問題排查指南
  - 替代方案: 已整合到主程式的自動診斷功能
  - 保留原因: 基礎網路除錯參考

- **ISSUE_ANALYSIS_FORWARD_OPEN.md**
  - 狀態: ✅ 已解決
  - 說明: Forward Open 問題分析與解決方案
  - 替代方案: 問題已修復並整合到主程式
  - 保留原因: 記錄問題解決過程

- **PROBLEM_SOLUTION_SUMMARY.md**
  - 狀態: ⚠️ 過時
  - 說明: 早期問題與解決方案摘要
  - 替代方案: 參考各功能的最新文檔
  - 保留原因: 歷史問題追蹤

### 舊版流程文檔

- **PROGRAM_FLOWCHART.md**
  - 狀態: ⚠️ 過時
  - 說明: 舊版程式流程圖（早期版本）
  - 替代方案: 參考 `PROGRAM_FLOW.md`（最新版 v4.0）
  - 保留原因: 記錄架構演進

- **MAIN_PROGRAM_FLOW.md**
  - 狀態: ⚠️ 過時（v1.0, 2025-11-13）
  - 說明: 主程式流程詳解（較舊版本）
  - 替代方案: 參考 `PROGRAM_FLOW.md`（最新版 v4.0）
  - 保留原因: 記錄功能演進過程

- **PROGRAM_FLOW.md**（舊版）
  - 狀態: ⚠️ 過時（v3.5, 2025-10-28）
  - 說明: 程式執行流程樹狀圖（v3.5 版本）
  - 替代方案: 參考 `PROGRAM_FLOW.md`（最新版 v4.0, 已替換）
  - 保留原因: 記錄早期流程設計

## 📚 當前有效文檔

請參考以下最新文檔：

### 核心文檔
- `README.md` - 專案總覽
- `CLI_USER_GUIDE.md` - 使用者指南
- `DEVELOPMENT_NOTES.md` - 開發筆記

### 功能文檔
- `INIT_COMMAND_FLOW.md` - 標稱電流設定流程（最新）
- `NOMINAL_CURRENT_IMPLEMENTATION.md` - 標稱電流實作細節
- `MAIN_PROGRAM_FLOW.md` - 主程式流程
- `PROGRAM_FLOW.md` - 程式流程說明

### 工具與診斷
- `DIAGNOSTIC_TOOLS_GUIDE.md` - 診斷工具指南

### 變更記錄
- `CHANGELOG.md` - 變更日誌
- `changelogs/` - 詳細變更記錄

## ⚠️ 注意事項

這些歷史文檔中的資訊可能已過時或不適用於當前版本。如需參考，請優先查閱當前有效文檔。

---

**最後更新**: 2025年11月25日  
**整理者**: Agent AI
