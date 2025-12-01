# CAPAROC 開發技術備忘錄

> **文件目的**: 記錄技術決策、踩坑經驗、不能做的事情
> **面向讀者**: 開發者、技術維護人員
> **補充文件**: TODO.md (功能規劃)、CHANGELOG.md (版本歷史)

**當前版本**: v3.7  
**最後更新**: 2025-11-26  
**主要開發者**: Harry Chiu



---

## ❌ 已證實無法實作的功能

### 1. Config Assembly 寫入

**結論**: **Config Assembly (0x66) 是唯讀的**

**實驗過程**:
- ✅ 可以**讀取** 244 bytes 完整資料
- ❌ **無法寫入** - 所有寫入嘗試都返回 "Too much data"
- ❌ 即使使用完整 244 bytes 讀取-修改-寫回方式也失敗

**測試記錄**:
```python
# 方法 1: Set Attribute Single (Service 0x10)
response = driver.generic_message(
    service=0x10,
    class_code=0x04,
    instance=0x66,
    attribute=3,
    request_data=bytes(244)  # 完整 244 bytes
)
# 結果: "Too much data"

# 方法 2: Set Attribute List (Service 0x03)
# 結果: "Too much data"

# 方法 3: 不同的 Attribute
# 結果: "Too much data"
```

**原因**: 設備韌體禁止運行時修改配置

---

### 2. Parameter Object 寫入

**結論**: **Parameter Object (Class 0x0F) 也是唯讀的**

**實驗過程**:
- ✅ 可以**讀取** 參數值
- ❌ **無法寫入** - 所有寫入嘗試都失敗
- ❌ 即使先解鎖 (Param1, Param2) 也無法寫入

**測試記錄**:
```python
# 嘗試 1: 寫入額定電流 (Param6, 9, 12, 15...)
response = driver.generic_message(
    service=0x10,
    class_code=0x0F,
    instance=6,
    attribute=1,
    request_data=bytes([4])  # 4A
)
# 結果: "Too much data"

# 嘗試 2: 解鎖全域鎖定 (Param1, Param2)
# 結果: "Too much data"

# 嘗試 3: 寫入 1 byte
# 結果: "Too much data"
```

**錯誤訊息**: "Too much data" (即使只寫入 1 byte!)

**結論**: 韌體級別的寫入保護

---

## 🔍 關鍵技術發現

### Assembly Instance 映射

| Instance | 類型 | 大小 | 可讀 | 可寫 | 說明 |
|----------|------|------|------|------|------|
| 0x64 (100) | Output | 18 bytes | ✅ | ✅ | 控制資料 |
| 0x65 (101) | Input | 244 bytes | ✅ | ❌ | 狀態資料 |
| 0x66 (102) | Config | 244 bytes | ✅ | ❌ | 配置資料（唯讀）|

### Output Assembly 結構 (Byte 0-17, 共 18 bytes)

```
Byte 0:   [Main Power]
  bit 7: Release (1=正常操作)
  bit 0: Main power (1=開, 0=關)
  
Byte 1:   [CH1-4 控制]
  bit 7: Release (1=正常操作)
  bit 3: CH4 (1=開, 0=關)
  bit 2: CH3 (1=開, 0=關)
  bit 1: CH2 (1=開, 0=關)
  bit 0: CH1 (1=開, 0=關)

Byte 2-17: 保留/其他模組
```

### Input Assembly 結構 (Byte 0-243, 共 244 bytes)

```
Byte 0:   全域狀態
  bit 0: Undervoltage (欠壓)
  bit 1: Overvoltage (過壓)
  bit 2: System error (系統錯誤)
  bit 3: 80% warning (80%警告)
  bit 4: Total shutdown (總電流關斷)
  bit 7: Config processing (配置處理中)

Byte 1:   模組數量 (0-16)

Byte 2-3: 總電流 (little-endian, 單位 0.1A)
          例如: 0x0066 = 102 = 10.2A

Byte 4-5: 系統電壓 (little-endian, 單位 0.01V)
          例如: 0x0960 = 2400 = 24.00V

Byte 6+:  通道狀態 (每個通道 3 bytes)
  Byte 0: 狀態
    bit 0: Channel status (1=開, 0=關)
    bit 1: 80% warning
    bit 2: Overload tripping (過載)
    bit 3: Short-circuit tripping (短路)
    bit 4: Hardware fault (硬體故障)
    bit 5: Total current shutdown (總電流關斷)
  Byte 1: 額定電流 (1-20A)
  Byte 2: 實際電流 (0.1A 單位, 0-255 = 0.0-25.5A)

模組 1 通道偏移:
  CH1: Byte 6-8
  CH2: Byte 9-11
  CH3: Byte 12-14
  CH4: Byte 15-17

模組 2 通道偏移:
  CH1: Byte 18-20
  CH2: Byte 21-23
  ...
```

---

## 🚫 已放棄的方法

### 1. LED 按鈕模擬

**原理**: 模擬設備前面板的 LED 按鈕操作

**流程**:
1. 寫入 "進入程式模式" (bit 6+7)
2. 模擬按鈕按壓 N 次（設定 N A）
3. 寫入 "儲存" (bit 6+7 + 通道 bit)
4. 退出程式模式

**問題**:
- ❌ 設備不響應 LED 按鈕模擬命令
- ❌ 即使嘗試多個 Assembly Instance (0x67-0x6A, 0x64) 都失敗
- ❌ 可能需要特殊的時序或設備必須處於特定模式

**結論**: 放棄此方法

---

### 2. Implicit Messaging

**原理**: 建立 Forward Open 連接，使用 I/O 模式通訊

**問題**:
- ⚠️ CAPAROC 設備不支援 Forward Open
- ⚠️ 僅支援 Explicit Messaging (Unconnected Send)

**結論**: 
- 程式中保留嘗試邏輯（靜默失敗）
- 實際使用 Explicit Messaging (`generic_message`)

---

## ✅ 成功的解決方案

### 額定電流設定

**最終方案**: **手動設定 + 程式驗證**

1. **設定步驟（在設備上）**:
   - 長按 PWR 鍵 3 秒（解鎖）
   - 短按通道按鈕進入編程模式
   - 按 +/- 調整電流值
   - 短按通道按鈕確認
   - 長按 PWR 鍵 3 秒退出

2. **程式驗證**:
   ```bash
   > verify 2
   ✅ CH2 額定電流: 4A
   ```

3. **程式中的 `init` 命令**:
   - **不會**自動設定電流
   - **僅顯示**手動設定指引
   - 這是最實用的方式

---

## 📊 重要數據結構

### 通道偏移計算公式

```python
def get_channel_offset(module, channel):
    """
    Args:
        module: 1-16
        channel: 1-4
    
    Returns:
        Input Assembly 中的 byte 偏移
    """
    global_bytes = 6
    bytes_per_module = 12
    bytes_per_channel = 3
    
    module_offset = global_bytes + (module - 1) * bytes_per_module
    channel_offset = module_offset + (channel - 1) * bytes_per_channel
    
    return channel_offset

# 範例:
# M1.CH1: 6 + 0*12 + 0*3 = 6
# M1.CH4: 6 + 0*12 + 3*3 = 15
# M2.CH1: 6 + 1*12 + 0*3 = 18
```

---

## 🛠️ 開發工具

### check_connection.py

**功能**: 自動診斷連接問題

**檢查項目**:
1. Ping 測試
2. Port 44818 連通性
3. pycomm3 安裝
4. CIP 連接測試

**使用**:
```bash
python check_connection.py
```

---

## 📝 文件結構

```
Caparoc_breaker_control/
├── README.md                           # 專案概述
├── INTERACTIVE_TEST_GUIDE.md           # 互動測試指南
├── check_connection.py                 # 連接診斷工具
├── src/
│   └── caparoc_controller.py           # 主程式 (2438 行)
├── docs/
│   ├── MAIN_POWER_CONTROL.md           # 主開關技術細節
│   ├── TROUBLESHOOTING_CONNECTION.md   # 連接問題排查
│   ├── DEVELOPMENT_NOTES.md            # 本文件
│   ├── CHANGELOG.md                    # 版本歷史
│   └── TODO.md                         # 待辦事項
└── tests/                              # 測試
```

---

## 🔮 未來改進方向

### 優先級 1: 通道資訊擴展

- [ ] 顯示通道歷史電流曲線
- [ ] 記錄通道開關歷史
- [ ] 通道使用統計

### 優先級 2: IP 配置支援

- [ ] 多設備管理
- [ ] 設備自動發現
- [ ] 配置文件支援

### 優先級 3: GUI 開發

- [ ] PyQt5 圖形界面
- [ ] 即時監控儀表板
- [ ] 通道群組控制

---

## 💡 關鍵經驗教訓

### 1. Config Assembly 的誤解

**原始認知**: PDF 手冊 Table 7-11 標示 "Read and write"

**實際情況**: 
- ✅ 可以讀取 (Read)
- ❌ 無法寫入 (Write)
- 手冊可能指"出廠時可寫入"，但運行時唯讀

**教訓**: 
- 不要完全依賴文件
- 實際測試是最可靠的
- "Too much data" 錯誤可能表示"拒絕寫入"

---

### 2. 錯誤訊息的誤導

**錯誤**: "Too much data"

**最初理解**: 資料太大，需要分段寫入

**實際原因**: 設備拒絕寫入（權限問題）

**證據**:
- 寫入 1 byte 也返回 "Too much data"
- 寫入 244 bytes 也返回 "Too much data"
- 不是大小問題，是**權限**問題

**教訓**: 
- 錯誤訊息可能不準確
- 需要多角度測試
- pycomm3 的錯誤訊息映射可能不完整

---

### 3. 專家建議的局限

**專家說**: "Config Assembly 絕對可以寫入"

**實際測試**: 完全無法寫入

**可能原因**:
- 專家經驗來自不同版本韌體
- 專家指的是"理論上可以"
- 專家使用了不同的設定工具（非 EtherNet/IP）

**教訓**:
- 專家建議是參考，不是絕對
- 始終以實際測試為準
- 記錄所有測試結果

---

### 4. 簡化優於複雜

**原始設計**: 
- 多個範例文件
- 複雜的文件結構
- 分散的功能

**最終設計**:
- 單一主程式
- 整合的互動介面
- 清晰的文件

**教訓**:
- 用戶需要簡單直接的工具
- 整合優於分散
- 文件要反映實際使用方式

---

## 📞 技術支援資訊

### 設備資訊

- **型號**: CAPAROC PM (EtherNet/IP)
- **通訊**: EtherNet/IP (Port 44818)
- **支援模組**: 1-16 個（每個 4 通道）
- **電流範圍**: 1-20A（標稱），0-25.5A（實際）

### 已知問題

1. **Config Assembly 唯讀** - 無法透過網路修改配置
2. **Parameter Object 唯讀** - 額定電流必須手動設定
3. **No Implicit Messaging** - 僅支援 Explicit Messaging

### 聯絡方式

- **開發者**: Harry Chiu
- **GitHub**: cFuuu/Caparoc_breaker_control
- **問題回報**: GitHub Issues

---

**文件版本**: 2.0  
**建立日期**: 2025-10-29  
**最後更新**: 2025-11-26  
**適用程式版本**: v3.7
