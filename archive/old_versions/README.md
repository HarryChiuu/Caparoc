# 舊版本程式碼存檔

## 📁 資料夾說明
本資料夾存放早期開發版本的程式碼，已被新版本取代但保留供參考。

**最後更新**: 2025-11-26

---

## 📄 文件清單

### 1. `caparoc_controller_old.py`
- **原路徑**: `src/caparoc_controller_old.py`
- **歸檔日期**: 2025-11-26
- **說明**: 舊版主控制器
- **狀態**: 已廢棄
- **取代者**: `src/caparoc_controller.py` (v3.7+)
- **主要問題**: 缺少額定電流設定、多通道控制邏輯不完整

### 2. `caparoc_unified_edit.py`
- **原路徑**: `archive/caparoc_unified_edit.py`
- **歸檔日期**: 2025-11-26
- **說明**: 統一控制器，整合多種控制模式的實驗版本
- **狀態**: 代碼過於複雜，未完成整合
- **問題**: 
  - 未整合成功的控制邏輯
  - Implicit Messaging 實現不完整
  - 缺少智能額定電流管理
- **特色**: 包含 GUI 模式、硬體偵測、多種控制模式嘗試

### 3. `caparoc_implicit_test.py`
- **原路徑**: `archive/caparoc_implicit_test.py`
- **歸檔日期**: 2025-11-26
- **說明**: Implicit Messaging 四通道測試程式
- **狀態**: 實驗性測試工具
- **用途**: 測試 Implicit Messaging 連接和四通道控制
- **成果**: 協助驗證 Implicit Messaging 概念，部分邏輯已整合到主程式

### 4. `caparoc_simple_control.py`
- **歸檔日期**: 2025-10-27
- **說明**: 最初的簡化控制程式
- **問題**: 
  - ❌ 多通道互相干擾
  - ❌ 重複開啟失效
  - ❌ off 指令異常
- **狀態**: 已被後續版本完全取代

### 5. `caparoc_simple_control_debug.py`
- **歸檔日期**: 2025-10-27
- **說明**: DEBUG 版本，添加了詳細日誌
- **特色**: 
  - I/O Worker 暫停機制
  - 詳細的 byte[1] 追蹤
  - DEBUG 輸出
- **狀態**: 協助發現問題，已完成歷史任務

---

## 📊 當前可用版本

### ✅ `src/caparoc_controller.py` (v3.7+)
**主要功能**:
- ✅ 額定電流設定 (init 命令)
- ✅ 四通道獨立控制
- ✅ 即時監控模式
- ✅ 心跳機制維持連接
- ✅ Config Assembly Read-Modify-Write
- ✅ 完整的命令列介面 (CLI)

**測試狀態**:
- ✅ 4 通道完全獨立控制
- ✅ 額定電流設定穩定
- ✅ 監控功能正常

---

## 🔗 相關文件
- `../ARCHIVE_LOG.md` - 完整的歸檔記錄與開發歷程
- `../test_byte_values.py` - byte 值測試工具 (已歸檔)
- `../../docs/history/` - 過時文件歸檔
- `../../docs/PROGRAM_FLOW.md` - 程式流程文件 (v4.0)
- `../../docs/INIT_COMMAND_FLOW.md` - init 命令流程

---

## ⚠️ 注意事項
- 這些文件僅供參考，**不應在生產環境使用**
- 已知問題未修復
- 建議使用 `src/caparoc_controller.py` 最新版本
- 所有成功的邏輯已整合到主程式

---

## 📝 版本演進
```
2025-10-23: caparoc_simple_control.py (初版)
            ↓
2025-10-23: caparoc_simple_control_debug.py (調試版)
            ↓
2025-10-27: caparoc_simple_v3.py (多通道控制成功)
            ↓
2025-11-xx: caparoc_controller.py (整合版 + 額定電流)
            ↓
2025-11-26: 當前版本 v3.7+ (穩定版)
```
