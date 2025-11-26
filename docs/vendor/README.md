# 原廠文檔與配置檔案

此資料夾存放 CAPAROC 設備的原廠提供文檔和配置檔案。

## 📁 檔案說明

### EDS 檔案

**CAPAROC_PM_EIP.eds**
- 用途: EtherNet/IP 設備描述檔 (Electronic Data Sheet)
- 說明: 定義設備的 CIP 物件模型、Assembly 結構、參數定義
- 用於: RSLinx、Studio 5000 等工具識別設備
- 版本: 原廠提供

### 手冊文檔

**manual-Ch6~7.pdf**
- 用途: CAPAROC PM EIP 原廠操作手冊（第 6-7 章）
- 內容:
  * Chapter 6: LED 按鈕程式設定
  * Chapter 7: EtherNet/IP 通訊協議
    - 7.1: Output Assembly (控制)
    - 7.2: Input Assembly (狀態)
    - 7.3: Config Assembly (配置)
- 重要性: ⭐⭐⭐⭐⭐ (程式開發的主要參考依據)

## 📝 使用說明

### EDS 檔案用途

1. **設備識別**
   - 使用 Rockwell 工具（RSLinx、Studio 5000）時自動識別設備
   - 提供設備名稱、型號、版本資訊

2. **參數定義**
   - Assembly Instance 編號 (0x64, 0x65, 0x66)
   - Parameter Object 結構
   - 資料型態與範圍

3. **通訊配置**
   - Connection 參數
   - RPI (Requested Packet Interval)
   - I/O 資料大小

### 手冊重點章節

#### Chapter 7.1 - Output Assembly
- 控制通道開關的方法
- Byte 1 位元對應 (CH1-4)
- Release bit (bit 7) 的用途

#### Chapter 7.2 - Input Assembly
- 全域系統狀態 (7.2.1)
- 模組計數器 (7.2.2)
- 總電流與電壓 (7.2.3, 7.2.4)
- 通道狀態結構 (7.2.5)

#### Chapter 7.3 - Config Assembly
- 244 bytes 完整結構
- Parameter 編號對照
- "No Change" 設定值
- Read-Modify-Write 流程

## 🔗 相關程式碼

本專案實作基於這些文檔的規範：

- **Assembly 定義**: 參考 EDS 檔案
  - Output Assembly: 0x64 (18 bytes)
  - Input Assembly: 0x65 (244 bytes)
  - Config Assembly: 0x66 (244 bytes)

- **通訊協議**: 參考手冊 Chapter 7
  - 位元操作: `src/caparoc_controller.py` - `set_channel()`
  - 狀態讀取: `src/caparoc_controller.py` - `show_status()`
  - 配置修改: `src/caparoc_controller.py` - `set_nominal_current()`

## ⚠️ 重要發現

### EDS 檔案與實際差異

1. **Output Assembly 大小**
   - EDS 標示: 20 bytes
   - 實際大小: 18 bytes ✅
   - 程式已修正

2. **Config Assembly 權限**
   - EDS 標示: Read/Write
   - 實際行為: 運行時唯讀 ❌
   - 解決方案: 使用 Read-Modify-Write

### 手冊補充說明

- Parameter Object (Class 0x0F) 未在手冊中詳細說明
- Bit 7 監測機制耗時約 5 秒（設備內部流程）
- 額定電流修改後需等待 0.5-3 秒才能驗證

## 📚 延伸資料

- [程式流程文檔](../PROGRAM_FLOW.md) - 基於手冊實作的完整流程
- [診斷工具指南](../DIAGNOSTIC_TOOLS_GUIDE.md) - 問題排查
- [開發筆記](../DEVELOPMENT_NOTES.md) - 實作過程中的發現

---

**最後更新**: 2025年11月25日  
**維護者**: Caparoc_breaker_control 專案團隊
