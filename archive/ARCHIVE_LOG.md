# Archive 文件移動記錄

## 最後更新
2025-11-26

## 歸檔說明
本資料夾存放開發過程中的舊版本程式碼和測試工具。
當前可用版本為 `src/caparoc_controller.py` (v3.7+)，已整合所有成功的控制邏輯。

---

## 📂 目錄結構

```
archive/
├── ARCHIVE_LOG.md (本文件)
├── test_byte_values.py (byte 值測試工具)
└── old_versions/ (舊版本程式碼)
    ├── README.md
    ├── caparoc_controller_old.py (舊版主控制器)
    ├── caparoc_unified_edit.py (統一控制器實驗版)
    ├── caparoc_implicit_test.py (Implicit Messaging 測試)
    ├── caparoc_simple_control.py (初版簡化控制)
    └── caparoc_simple_control_debug.py (調試版)
```

---

## 歸檔文件清單

### 1. `test_byte_values.py`
- **原路徑**: `src/test_byte_values.py`
- **歸檔日期**: 2025-10-27
- **當前路徑**: `archive/test_byte_values.py`
- **說明**: 系統化測試不同 byte[1] 值的工具
- **狀態**: 開發階段的測試工具
- **用途**: 了解每個 bit 的作用，找出正確控制方式
- **成果**: 已完成任務，成功邏輯已整合到主程式

### 2. `old_versions/` 目錄
- **最後更新**: 2025-11-26
- **說明**: 包含早期開發版本的程式碼
- **文件數量**: 5 個 Python 檔案

#### 2.1 `caparoc_controller_old.py`
- **原路徑**: `src/caparoc_controller_old.py`
- **歸檔日期**: 2025-11-26
- **說明**: 舊版主控制器
- **狀態**: 已被當前版本取代

#### 2.2 `caparoc_unified_edit.py`
- **原路徑**: `archive/caparoc_unified_edit.py`
- **歸檔日期**: 2025-11-26
- **說明**: 統一控制器實驗版本
- **問題**: 代碼過於複雜，整合不完整
- **狀態**: 部分概念已應用到主程式

#### 2.3 `caparoc_implicit_test.py`
- **原路徑**: `archive/caparoc_implicit_test.py`
- **歸檔日期**: 2025-11-26
- **說明**: Implicit Messaging 測試程式
- **狀態**: 實驗性工具，協助驗證概念

#### 2.4 `caparoc_simple_control.py`
- **歸檔日期**: 2025-10-27
- **說明**: 最初的簡化控制程式
- **問題**: 
  - ❌ 多通道互相干擾
  - ❌ 重複開啟失效
  - ❌ off 指令異常
- **狀態**: 已被後續版本完全取代

#### 2.5 `caparoc_simple_control_debug.py`
- **歸檔日期**: 2025-10-27
- **說明**: DEBUG 版本，添加了詳細日誌
- **特色**: 
  - I/O Worker 暫停機制
  - 詳細的 byte[1] 追蹤
  - DEBUG 輸出
- **問題**: 雖然增加了調試功能，但未解決根本問題
- **狀態**: 協助發現問題，已完成任務

---

## 當前可用版本

### ✅ `src/caparoc_controller.py` (v3.7+)
**主要功能**:
- ✅ 額定電流設定 (init 命令) - Config Assembly Read-Modify-Write
- ✅ 四通道獨立控制 (on/off 命令)
- ✅ 即時監控模式 (monitor 命令)
- ✅ 心跳機制維持連接
- ✅ 完整的 CLI 互動介面
- ✅ 漸進式重試驗證 (0.5s-3s)

**核心改進**:
1. 額定電流設定流程完整實現
2. Output Assembly 正確使用 (18 bytes)
3. 位元運算保留其他通道狀態
4. 退出程式優化 (顯示訊息 + 減少延遲)

**測試狀態**:
- ✅ 4 通道完全獨立控制
- ✅ 額定電流設定穩定可靠
- ✅ 監控功能正常運作
- ✅ 所有命令均已測試驗證

---

## 開發歷程回顧

### 階段 1: 初始開發 (2025-10-23)
- 創建基本控制程式 (`caparoc_simple_control.py`)
- 發現多通道干擾問題
- 嘗試各種解決方案

### 階段 2: 深入調試 (2025-10-23)
- 添加詳細 DEBUG 輸出 (`caparoc_simple_control_debug.py`)
- 分析 `set_nominal_current` 行為
- 發現 Instance 0x64 衝突問題

### 階段 3: 系統測試 (2025-10-23 - 2025-10-27)
- 創建 `test_byte_values.py` 系統化測試
- 研究手冊規範
- 確認正確的控制方式

### 階段 4: 多通道控制成功 (2025-10-27) ✅
- 實作 V3 版本
- 修正 Assembly 大小錯誤 (18 bytes)
- 實現位元運算保護邏輯
- 四通道獨立控制成功

### 階段 5: 額定電流整合 (2025-11-xx) ✅
- 實現完整的額定電流設定流程
- Config Assembly Read-Modify-Write 機制
- 漸進式重試驗證
- 整合到主程式 (`caparoc_controller.py`)

### 階段 6: 優化與文件整理 (2025-11-26) ✅
- 退出程式優化
- 文件架構重組 (history/, vendor/)
- 流程文件更新至 v4.0
- 根目錄清理與依賴優化

---

## 技術總結

### 失敗的嘗試
1. ❌ 只在首次開啟時設定額定電流
2. ❌ 暫停 I/O Worker 避免競爭
3. ❌ 避免使用 Instance 0x64
4. ❌ 在 generic_message 中保留其他通道狀態（當時的實作方式）

### 成功的關鍵
1. ✅ **正確的資料結構**: 18 bytes Assembly（不是 20）
2. ✅ **精確的位元控制**: OR/AND 運算保護其他 bit
3. ✅ **智能初始化**: 額定電流只設定一次，後續快速控制
4. ✅ **仔細閱讀手冊**: 理解 bit7 (Release bit) 的作用

---

## 參考文件
- `../docs/PROGRAM_FLOW.md` - 程式流程文件 v4.0
- `../docs/INIT_COMMAND_FLOW.md` - 額定電流設定流程
- `../docs/CLI_USER_GUIDE.md` - CLI 使用指南
- `../docs/history/` - 過時文件歸檔
- `../docs/vendor/` - 原廠手冊與 EDS 檔案
- CAPAROC 設備手冊 7.1.2 節 - Output Assembly 控制規範

---

## 已完成功能 ✅
- ✅ 額定電流設定 (init 命令)
- ✅ 四通道獨立控制 (on/off 命令)
- ✅ 即時監控功能 (monitor 命令)
- ✅ 心跳機制維持連接
- ✅ 完整的 CLI 介面
- ✅ 退出程式優化
- ✅ 文件架構整理

---

## 未來規劃
- 📋 GUI 介面開發
- 🔧 代碼進一步優化
- 📊 數據記錄與分析功能
- 🧪 更多自動化測試
