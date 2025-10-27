# CAPAROC 控制器 - 待實作功能清單

更新日期: 2025-10-27

## ✅ 已完成功能

### V3.1 (2025-10-27)
- [x] 多通道獨立控制 (on/off)
- [x] 即時狀態讀取 (電壓、電流)
- [x] 通道額定電流初始化 (LED按鈕模擬)
- [x] Implicit Messaging 自動檢測
- [x] 狀態讀取完全修復 (根據手冊 Table 7-4)
- [x] UI 優化 (簡潔輸出)

---

## ⚠️ 待實作功能

### 1. 全域狀態監測 (Global Status Monitoring)

**目標**: 持續背景監控設備異常狀態

**功能需求**:
- [ ] 背景執行緒持續監控 Input Assembly
- [ ] 偵測異常狀態:
  - 過載 (Overload)
  - 短路 (Short Circuit)
  - 硬體故障 (Hardware Fault)
  - 80% 電流警告
  - 總電流關斷
- [ ] 異常事件記錄與通知
- [ ] 狀態變化歷史記錄
- [ ] 可選的聲音/視覺警報

**參考手冊**:
- Section 7.2.5 (Input Assembly, Status Bytes)
- Table 7-4 (Module Data Block)

**預估工時**: 3-4 小時

---

### 2. 初始化電流值設定 (Configurable Nominal Current)

**目標**: 允許用戶配置通道額定電流

**功能需求**:
- [ ] 配置檔案支援 (JSON/YAML)
  ```yaml
  channels:
    CH1: 4.0  # A
    CH2: 2.5  # A
    CH3: 1.0  # A
    CH4: 5.0  # A
  ```
- [ ] 命令列參數支援
  ```bash
  python caparoc_controller.py --ch1 4.0 --ch2 2.5
  ```
- [ ] 互動式設定模式
- [ ] 驗證範圍 (0.5A - 25.5A)
- [ ] 儲存設定到檔案
- [ ] 啟動時自動載入上次設定

**預估工時**: 2-3 小時

---

### 3. GUI 規劃設計 (Graphical User Interface)

**目標**: 圖形化控制介面,取代命令列

**框架選擇**:
- **推薦**: CustomTkinter (現代化 UI)
- **備選**: PyQt5 / tkinter

**功能需求**:

#### 3.1 主視窗
- [ ] 設備連接狀態顯示
- [ ] IP 位址輸入/連接按鈕
- [ ] 即時系統資訊:
  - 電壓 (V)
  - 總電流 (A)
  - 連接狀態

#### 3.2 通道控制面板 (每個通道)
- [ ] 開/關 切換按鈕
- [ ] 即時電流顯示 (數字 + 進度條)
- [ ] 狀態指示燈:
  - 🟢 正常
  - 🟡 警告 (80%)
  - 🔴 異常 (過載/短路)
- [ ] 額定電流設定按鈕

#### 3.3 進階功能
- [ ] 歷史資料圖表 (matplotlib)
  - 電流趨勢線
  - 時間軸可調整
- [ ] 事件日誌視窗
  - 開關操作記錄
  - 異常事件記錄
  - 匯出 CSV
- [ ] 設定視窗
  - 更新頻率調整
  - 警報閾值設定
  - 外觀主題切換

#### 3.4 技術規劃
```
caparoc_gui/
├── __init__.py
├── main_window.py      # 主視窗
├── channel_panel.py    # 通道控制面板元件
├── status_monitor.py   # 狀態監控執行緒
├── config_dialog.py    # 設定對話框
├── chart_widget.py     # 圖表元件
└── styles.py           # UI 樣式定義
```

**預估工時**: 8-12 小時

---

## 📅 開發優先順序

1. **Phase 1**: 初始化電流值設定 (2-3 小時)
   - 快速提升使用便利性
   - 為 GUI 做準備

2. **Phase 2**: 全域狀態監測 (3-4 小時)
   - 提高系統可靠性
   - GUI 需要此功能

3. **Phase 3**: GUI 設計與實作 (8-12 小時)
   - 整合前兩階段功能
   - 最終用戶友善介面

**總預估工時**: 13-19 小時

---

## 📝 備註

- 所有新功能需與現有 `caparoc_controller.py` 相容
- 保持命令列版本可用 (作為備用/除錯工具)
- GUI 版本可獨立執行: `python caparoc_gui/main_window.py`
- 持續參考手冊確保實作正確性
