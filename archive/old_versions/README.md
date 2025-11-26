# 舊版本程式碼存檔

## 📁 資料夾說明
本資料夾存放早期開發版本的程式碼，已被新版本取代但保留供參考。

---

## 📄 文件清單

### 1. `caparoc_controller_old.py`
- **說明**: 舊版主控制器
- **狀態**: 已廢棄
- **取代者**: `src/caparoc_controller.py`

### 2. `caparoc_simple_control.py`
- **說明**: 最初的簡化控制程式
- **問題**: 
  - ❌ 多通道互相干擾
  - ❌ 重複開啟失效
  - ❌ off 指令異常
- **狀態**: 已被 V3 完全取代

### 3. `caparoc_simple_control_debug.py`
- **說明**: DEBUG 版本，添加了詳細日誌
- **特色**: 
  - I/O Worker 暫停機制
  - 詳細的 byte[1] 追蹤
  - DEBUG 輸出
- **狀態**: 協助發現問題，已完成歷史任務

---

## 🔗 相關文件
- `../ARCHIVE_LOG.md` - 完整的歸檔記錄與開發歷程
- `../../docs/history/` - 過時文檔歸檔

---

## ⚠️ 注意事項
- 這些文件僅供參考，**不應在生產環境使用**
- 已知問題未修復
- 建議使用 `src/caparoc_controller.py` 最新版本
