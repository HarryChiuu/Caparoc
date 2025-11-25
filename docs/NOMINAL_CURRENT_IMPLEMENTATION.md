# 標稱電流修改功能實作指南

## 📋 目錄
- [概述](#概述)
- [問題分析](#問題分析)
- [解決方案](#解決方案)
- [核心代碼](#核心代碼)
- [關鍵發現](#關鍵發現)
- [測試驗證](#測試驗證)
- [最佳實踐](#最佳實踐)

---

## 概述

### 功能目標
實作安全可靠的標稱電流修改功能，允許用戶動態調整通道的電流保護閾值（1-20A），而不影響其他通道的運作狀態。

### 實作日期
2025年11月19日 - 2025年11月25日

### 開發分支
`feature/nominal-current-modification`

### 相關手冊章節
- **Table 7-11**: Structure of the config assembly
- **Table 7-18**: Config assembly, channel status
- **Section 7.1.2**: 控制方式規範

---

## 問題分析

### 初始問題
在實作標稱電流修改功能時，遇到以下關鍵問題：

**問題 1: 修改後所有通道關閉**
```
現象：執行 init 1 4 後，CH1/CH2/CH3/CH4 全部關閉
原因：Config Assembly 寫入時未正確處理 Status Byte
```

**問題 2: 不清楚正確的寫入方式**
```
疑問：是否需要先關閉所有通道才能修改配置？
疑問：如何只修改單一通道的電流而不影響其他通道？
```

### 根本原因

根據手冊 **Table 7-11** 和 **Table 7-18**，Config Assembly 的結構如下：

**Header (Global Settings) - 6 bytes**
```
Byte 0: Global nominal current lock (USINT)
Byte 1: Global user interface lock (USINT)
Byte 2-3: Global switch-on delay (INT, 2 bytes)
Byte 4: Global operating mode (USINT)
Byte 5: Reserved (USINT)
```

**Body (每個通道 3 bytes)**
```
Byte 0: Nominal Current (USINT, 1-20A)
Byte 1: Programming Lock (USINT)
Byte 2: Status (USINT) ⚠️ 關鍵！
```

**Status Byte 的值（Table 7-18）：**
- `0` = Channel off（強制關閉）❌
- `1` = Channel on（強制開啟）
- `2` = **No change (EDS standard)**（保持現狀）✅

**問題的真相：**
當我們使用 `bytearray` 初始化或讀取 Config Assembly 時，如果 Status Byte 的值為 `0`，設備會將該通道強制關閉！

---

## 解決方案

### 核心策略：Read-Modify-Write + Status Byte Protection

#### 步驟 1: Read（讀取完整配置）
```python
response = driver.generic_message(
    service=0x0E,  # Get Attribute Single
    class_code=0x04,
    instance=0x66,  # Config Assembly
    attribute=3,
    connected=True
)
config_data = bytearray(response.value)
```

#### 步驟 2: Modify（只修改目標 + 保護 Status）
```python
# 修改 Nominal Current
struct.pack_into('<B', config_data, offset_current, current_amps)

# ⚠️ 關鍵：將 Status 設為 2 (No Change)
struct.pack_into('<B', config_data, offset_status, 2)

# 進階保護：遍歷所有通道，確保沒有意外的 0
for m in range(1, 17):
    for ch in range(1, 5):
        ch_status_offset = get_config_channel_offset(m, ch) + 2
        if ch_status_offset < len(config_data):
            if config_data[ch_status_offset] == 0:
                struct.pack_into('<B', config_data, ch_status_offset, 2)
```

#### 步驟 3: Write（寫回完整配置）
```python
write_response = driver.generic_message(
    service=0x10,  # Set Attribute Single
    class_code=0x04,
    instance=0x66,
    attribute=3,
    request_data=bytes(config_data),
    connected=True
)
```

---

## 核心代碼

### 1. 計算通道偏移量

```python
def get_config_channel_offset(self, module, channel):
    """
    計算通道在 Config Assembly 中的 Nominal Current 位置
    
    根據手冊 Table 7-11:
    - Header: 6 bytes
    - 每個模組: 12 bytes (4 channels × 3 bytes)
    - 每個通道: 3 bytes (Nominal Current, Lock, Status)
    
    範例:
        Module 1, CH1: offset = 6 + 0*12 + 0*3 = 6
        Module 1, CH4: offset = 6 + 0*12 + 3*3 = 15
        Module 2, CH1: offset = 6 + 1*12 + 0*3 = 18
    """
    header_bytes = 6
    bytes_per_module = 12
    bytes_per_channel = 3
    
    module_offset = header_bytes + (module - 1) * bytes_per_module
    channel_offset = module_offset + (channel - 1) * bytes_per_channel
    
    return channel_offset
```

### 2. 設定標稱電流（完整版）

```python
def set_nominal_current(self, module, channel, current_amps, verify=True):
    """
    安全設定通道標稱電流，使用 Status Byte = 2 保護機制
    """
    try:
        # 計算偏移量
        base_offset = self.get_config_channel_offset(module, channel)
        offset_current = base_offset      # Nominal Current
        offset_lock = base_offset + 1     # Programming Lock
        offset_status = base_offset + 2   # Status (關鍵！)
        
        # STEP 1: READ
        response = self.driver.generic_message(
            service=0x0E,
            class_code=0x04,
            instance=self.config_instance,  # 0x66
            attribute=3,
            connected=True
        )
        
        if not response or (hasattr(response, 'error') and response.error):
            return False
        
        config_data = bytearray(response.value)
        
        # STEP 2: MODIFY
        # 修改 Nominal Current
        struct.pack_into('<B', config_data, offset_current, current_amps)
        
        # ⚠️ 關鍵：Status = 2 (No Change)
        struct.pack_into('<B', config_data, offset_status, 2)
        
        # 進階保護：所有通道的 Status 都設為 2
        for m in range(1, 17):
            for ch in range(1, 5):
                ch_offset = self.get_config_channel_offset(m, ch)
                ch_status_offset = ch_offset + 2
                
                if ch_status_offset < len(config_data):
                    if config_data[ch_status_offset] == 0:
                        struct.pack_into('<B', config_data, ch_status_offset, 2)
        
        # STEP 3: WRITE
        write_response = self.driver.generic_message(
            service=0x10,
            class_code=0x04,
            instance=self.config_instance,
            attribute=3,
            request_data=bytes(config_data),
            connected=True
        )
        
        if hasattr(write_response, 'error') and write_response.error:
            return False
        
        return True
        
    except Exception as e:
        print(f"錯誤: {e}")
        return False
```

### 3. 驗證標稱電流

```python
def _verify_nominal_current(self, driver, module, channel):
    """
    從 Input Assembly 讀取實際標稱電流值
    """
    try:
        response = driver.generic_message(
            service=0x0E,
            class_code=0x04,
            instance=self.input_instance,  # 0x65
            attribute=3,
            connected=False
        )
        
        if response and hasattr(response, 'value'):
            data = response.value
            offset = self.get_channel_offset(module, channel)
            
            if len(data) > offset + 1:
                # Byte 1: Nominal current
                nominal_current = data[offset + 1]
                return int(nominal_current)
        
        return None
        
    except Exception as e:
        return None
```

---

## 關鍵發現

### 🔑 核心機制：Status Byte = 2 (No Change)

這是整個解決方案的關鍵！根據手冊 **Table 7-18**：

| 值 | 意義 | 效果 |
|---|------|------|
| 0 | Channel off | ❌ 強制關閉通道 |
| 1 | Channel on | 強制開啟通道 |
| 2 | **No change** | ✅ 保持現狀（推薦） |

**為什麼使用 2？**
1. **安全性**：不會意外改變通道的開關狀態
2. **獨立性**：只修改電流，不影響其他配置
3. **標準性**：符合 EDS (Electronic Data Sheet) 標準

### 📊 Config Assembly 結構總結

```
Offset  | 內容                        | 大小    | 說明
--------|----------------------------|---------|------------------
0       | Global nominal current lock| 1 byte  | 全域電流鎖定
1       | Global UI lock             | 1 byte  | 全域介面鎖定
2-3     | Global switch-on delay     | 2 bytes | 開啟延遲
4       | Global operating mode      | 1 byte  | 運作模式
5       | Reserved                   | 1 byte  | 保留（不可修改）
--------|----------------------------|---------|------------------
6       | M1 CH1 Nominal Current     | 1 byte  | 模組1通道1電流
7       | M1 CH1 Programming Lock    | 1 byte  | 程式鎖定
8       | M1 CH1 Status              | 1 byte  | 狀態（⚠️關鍵）
9       | M1 CH2 Nominal Current     | 1 byte  |
...     | ...                        | ...     |
15      | M1 CH4 Status              | 1 byte  |
18      | M2 CH1 Nominal Current     | 1 byte  |
...     | ...                        | ...     |
```

### 🛡️ 保護機制

**為什麼要遍歷所有通道？**
```python
for m in range(1, 17):
    for ch in range(1, 5):
        if config_data[ch_status_offset] == 0:
            struct.pack_into('<B', config_data, ch_status_offset, 2)
```

**原因：**
1. **防止意外的 0 值**：讀取回來的 Config 可能包含未初始化的 0
2. **確保全域保護**：不只是目標通道，所有通道都受保護
3. **降低風險**：即使邏輯有 bug，也不會關閉正在運作的通道

---

## 測試驗證

### 測試場景 1: 單通道修改

**步驟：**
```bash
# 1. 開啟多個通道
on 1
on 2
on 3

# 2. 查看初始狀態
s

# 3. 修改 CH2 的標稱電流
init 2 8

# 4. 再次查看狀態
s
```

**預期結果：**
- ✅ CH1 保持開啟
- ✅ CH2 電流改為 8A，保持開啟
- ✅ CH3 保持開啟
- ✅ CH4 保持關閉

**實際結果：**
```
[標稱電流設定] CH2
   目標電流: 8A
   Config Offset: Byte 9 (Current), 11 (Status)
   [步驟1] 讀取 Config Assembly...
   ✅ 讀取成功 (長度: 204 bytes)
   [步驟2] 修改設定...
   Nominal Current: 4A -> 8A
   Status: 0 -> 2 (No Change - 保持現狀)
   [保護] 設定所有通道 Status = 2 (No Change)...
   ✅ 所有通道已保護
   [步驟3] 寫回 Config Assembly...
   ✅ Config Assembly 已更新

   💡 機制說明:
   - 使用 Status Byte = 2 (No Change) 保護所有通道
   - 只會修改 CH2 的標稱電流
   - 其他通道的開關狀態不會被影響！
```

### 測試場景 2: 批次設定

**步驟：**
```bash
# 設定所有通道
init 1 4
init 2 6
init 3 8
init 4 10

# 查看結果
s
```

**預期結果：**
- ✅ 所有通道電流已更新
- ✅ 開關狀態保持不變

### 測試場景 3: 驗證機制

**步驟：**
```bash
# 設定並驗證
init 1 5
verify 1
```

**輸出：**
```
[標稱電流設定] CH1
   ...
   [驗證] 等待設備應用設定...
   ✅ 驗證成功: 5A
```

---

## 最佳實踐

### ✅ 推薦做法

**1. 使用 Read-Modify-Write**
```python
# ✅ 正確：先讀取、修改、再寫回
response = read_config()
config_data = bytearray(response.value)
config_data[offset] = new_value
write_config(config_data)
```

**2. 永遠使用 Status = 2**
```python
# ✅ 正確：保持現狀
struct.pack_into('<B', config_data, offset_status, 2)

# ❌ 錯誤：可能意外關閉通道
# struct.pack_into('<B', config_data, offset_status, 0)
```

**3. 保護所有通道**
```python
# ✅ 正確：遍歷並保護
for m in range(1, 17):
    for ch in range(1, 5):
        if config_data[offset] == 0:
            config_data[offset] = 2
```

**4. 驗證設定結果**
```python
# ✅ 正確：設定後驗證
set_nominal_current(1, 1, 5)
actual = verify_nominal_current(1, 1)
assert actual == 5
```

### ❌ 常見錯誤

**錯誤 1: 只修改單一 Byte**
```python
# ❌ 錯誤：沒有使用 Read-Modify-Write
config_data = bytearray(204)  # 全是 0
config_data[6] = 5  # 只設定電流
# 結果：Status = 0，通道會被關閉！
```

**錯誤 2: 忽略 Status Byte**
```python
# ❌ 錯誤：沒有設定 Status
struct.pack_into('<B', config_data, offset_current, 5)
# 忘記設定 offset_status
```

**錯誤 3: 使用錯誤的 Instance**
```python
# ❌ 錯誤：使用 Input Assembly
instance = 0x65  # 這是 Input，不是 Config

# ✅ 正確：使用 Config Assembly
instance = 0x66  # 或 self.config_instance
```

### 📝 程式碼審查檢查清單

在提交代碼前，請確認：

- [ ] 使用 Read-Modify-Write 流程
- [ ] Status Byte 設為 2 (No Change)
- [ ] 遍歷所有通道進行保護
- [ ] 正確使用 Config Assembly (0x66)
- [ ] 參數範圍檢查（1-20A）
- [ ] 錯誤處理完善
- [ ] 添加驗證機制
- [ ] 提供清晰的用戶提示

---

## 技術細節

### EtherNet/IP 通訊

**Service Codes:**
- `0x0E` - Get Attribute Single (讀取)
- `0x10` - Set Attribute Single (寫入)

**Class Code:**
- `0x04` - Assembly Object

**Instances:**
- `0x64` - Output Assembly (控制開關)
- `0x65` - Input Assembly (讀取狀態)
- `0x66` - Config Assembly (配置參數)

**Attribute:**
- `3` - Assembly Data

### 資料型態

**Little Endian 格式：**
```python
# USINT (1 byte)
struct.pack_into('<B', data, offset, value)

# INT (2 bytes)
struct.pack_into('<H', data, offset, value)

# DINT (4 bytes)
struct.pack_into('<I', data, offset, value)
```

---

## 故障排除

### 問題 1: 設定後通道全部關閉

**症狀：**
```
執行 init 1 4 後，所有通道都關閉了
```

**診斷：**
```python
# 檢查 Status Byte
print(f"Status: {config_data[offset_status]}")
# 如果是 0，就會關閉！
```

**解決：**
```python
# 確保 Status = 2
struct.pack_into('<B', config_data, offset_status, 2)
```

### 問題 2: 驗證失敗

**症狀：**
```
設定 5A，但驗證顯示 0A
```

**診斷：**
1. 檢查 offset 計算是否正確
2. 檢查是否使用正確的 Instance (0x66 vs 0x65)
3. 增加等待時間讓設備應用設定

**解決：**
```python
time.sleep(1.0)  # 增加等待時間
```

### 問題 3: 寫入失敗

**症狀：**
```
❌ 寫入失敗: Path segment error
```

**診斷：**
檢查 Instance ID 是否正確

**解決：**
```python
# 確認使用 Config Assembly
instance = 0x66  # 不是 0x01
```

---

## 版本歷史

### v1.0 (2025-11-19)
- ✅ 初始實作 Read-Modify-Write
- ❌ 問題：修改後所有通道關閉

### v1.1 (2025-11-24)
- ✅ 添加警告訊息說明保護機制
- ⚠️ 仍存在通道關閉問題

### v2.0 (2025-11-25) - 最終版本
- ✅ **關鍵修正：使用 Status Byte = 2 (No Change)**
- ✅ 添加所有通道保護機制
- ✅ 完美解決通道關閉問題
- ✅ 通過所有測試場景

---

## 參考資料

### 手冊章節
- **Table 7-11**: Structure of the config assembly
- **Table 7-18**: Config assembly, channel status
- **Table 7-14**: Config assembly, global switch-on delay

### 相關文檔
- `docs/Config_Assembly_驗證報告.md`
- `docs/標稱電流設定流程與故障排除.md`
- `docs/DEVELOPMENT_NOTES.md`

### Git 提交記錄
- `38518cb` - feat: 實作標稱電流修改功能 (Phase 3-3)
- `1e0bd48` - docs: 添加 Config Assembly 安全保護機制說明
- `67fbf69` - fix: 使用 Status Byte = 2 (No Change) 保護通道開關狀態

---

## 總結

### 🎯 核心要點

1. **Config Assembly 結構理解**
   - Header (6 bytes) + Body (每通道 3 bytes) + Footer
   - 每個通道：Nominal Current, Lock, **Status**

2. **Status Byte 是關鍵**
   - `0` = Off（危險！）
   - `1` = On
   - `2` = **No Change**（最安全）

3. **Read-Modify-Write 是必須的**
   - 保護 Reserved 欄位
   - 保護其他通道配置
   - 確保數據完整性

4. **全通道保護機制**
   - 遍歷所有通道
   - 將 Status = 0 改為 2
   - 防止意外關閉

### 🚀 成果

- ✅ 功能完整實作
- ✅ 通道保護機制完善
- ✅ 通過所有測試
- ✅ 代碼已合併到功能分支
- ✅ 文檔完整記錄

### 🔮 未來改進

1. **批次設定優化**
   - 一次設定多個通道
   - 減少 Config Assembly 寫入次數

2. **GUI 介面**
   - 視覺化電流設定
   - 即時顯示設定結果

3. **配置模板**
   - 保存常用配置
   - 快速載入設定

---

**文檔版本**: 1.0  
**最後更新**: 2025-11-25  
**作者**: CAPAROC 開發團隊  
**狀態**: ✅ 已完成並測試通過
