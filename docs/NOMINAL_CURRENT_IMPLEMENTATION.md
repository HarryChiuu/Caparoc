# 額定電流修改功能實作指南

## 📋 目錄
- [概述](#概述)
- [問題分析](#問題分析)
- [解決方案](#解決方案)
- [核心程式碼](#核心程式碼)
- [關鍵發現](#關鍵發現)
- [控制額定電流方法](#控制額定電流方法)
  - [方法 1: 手動控制 - 使用設備按鈕](#方法-1-手動控制---使用設備按鈕-)
  - [方法 2: 程式控制 - 使用 init 指令](#方法-2-程式控制---使用-init-指令-)
- [測試驗證](#測試驗證)
- [最佳實踐](#最佳實踐)
- [技術細節](#技術細節)
- [故障排除](#故障排除)
- [附錄：失敗歷史與成功關鍵對比](#附錄失敗歷史與成功關鍵對比)

---

## 概述

### 功能目標
實作安全可靠的額定電流修改功能，允許用戶動態調整通道的電流保護閾值（1-10A），而不影響其他通道的運作狀態。

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
在實作額定電流修改功能時，遇到以下關鍵問題：

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
Byte 0: Nominal Current (USINT, 1-10A)
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

## 核心程式碼

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

### 2. 設定額定電流（完整版）

```python
def set_nominal_current(self, module, channel, current_amps, verify=True):
    """
    安全設定通道額定電流，使用 Status Byte = 2 保護機制
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

### 3. 驗證額定電流

```python
def _verify_nominal_current(self, driver, module, channel):
    """
    從 Input Assembly 讀取實際額定電流值
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

## 控制額定電流方法

CAPAROC 設備支援兩種額定電流控制方法：手動控制（設備按鈕）和程式控制（init 命令）。

### 方法 1: 手動控制 - 使用設備按鈕 ⭐

適合現場快速調整，不需要電腦或網路連線。

**操作步驟：**

1. **解除硬體鎖定**
   - 長按 **PWR** 鍵 3 秒
   - 觀察：LED 閃綠光 3 次
   - 狀態：硬體保護解除

2. **進入編程模式**
   - 短按對應通道按鈕（CH1/CH2/CH3/CH4）
   - 狀態：該通道 LED 開始閃爍
   - 說明：進入該通道的額定電流編程模式

3. **調整電流值**
   - 按 **+** 按鈕：增加 0.5A
   - 按 **-** 按鈕：減少 0.5A
   - 範圍：1A - 10A
   - 顯示：LED 顯示當前設定值

4. **確認設定**
   - 短按通道按鈕
   - 狀態：LED 停止閃爍
   - 說明：設定已儲存到該通道

5. **退出編程模式**
   - 長按 **PWR** 鍵 3 秒
   - 狀態：恢復硬體鎖定
   - 說明：防止意外修改

**範例：設定 CH2 為 6A**
```
1. 長按 PWR 3秒         → LED 閃綠光 3次
2. 短按 CH2 按鈕        → CH2 LED 閃爍
3. 按 + 或 - 調整到 6A  → 顯示 6A
4. 短按 CH2 按鈕        → CH2 LED 停止閃爍
5. 長按 PWR 3秒         → 完成
```

**注意事項：**
- ⚠️ 設定時通道會自動關閉（安全保護）
- ⚠️ 設定完成後需手動重新開啟通道
- ✅ 設定立即生效，斷電後保持
- ✅ 可在運行中設定（但通道會暫時關閉）

### 方法 2: 程式控制 - 使用 init 指令 🖥️

透過 EtherNet/IP 協議遠端控制，適合自動化和批次設定。

**操作步驟：**

1. **啟動控制程式**
   ```bash
   # 進入專案目錄
   cd c:\Users\harry\Project\Caparoc5
   
   # 啟動控制器
   python src/caparoc_controller.py
   ```

2. **設定額定電流**
   ```bash
   # 語法: init <通道編號> <電流值(1-10A)>
   🎮 > init 1 4      # 設定 CH1 為 4A
   🎮 > init 2 6      # 設定 CH2 為 6A
   🎮 > init 3 8      # 設定 CH3 為 8A
   🎮 > init 4 10     # 設定 CH4 為 10A
   ```

3. **驗證設定**
   ```bash
   # 方法 1: 使用 verify 命令
   🎮 > verify 1
   ✅ CH1 額定電流: 4A
   
   # 方法 2: 使用 status 命令查看所有通道
   🎮 > s
   ```

**技術說明：**
- 使用 **Config Assembly Read-Modify-Write** 方法
- 採用 **Status Byte = 2 (No Change)** 保護機制
- 只修改目標通道的額定電流值
- 不影響其他通道的開關狀態
- 設定立即生效並永久保存

**注意事項：**
- ✅ 設定時通道可保持開啟（不會關閉）
- ✅ 支援批次設定多個通道
- ✅ 設定立即生效，斷電後保持
- ✅ 可整合到自動化測試流程
- ⚠️ 需要 EtherNet/IP 網路連線
- ⚠️ 需要安裝 Python 環境和 pycomm3 套件

### 方法比較

| 項目 | 手動控制（設備按鈕） | 程式控制 (init 命令) |
|------|---------------------|---------------------|
| **設備要求** | 所有型號 | 所有型號（需 EtherNet/IP） |
| **操作難度** | ⭐ 簡單 | ⭐⭐⭐ 需要技術知識 |
| **設定速度** | 慢（單一通道） | 快（程式化） |
| **現場使用** | ✅ 最適合 | ⚠️ 需電腦 + 網路 |
| **批次設定** | ❌ 不適合 | ✅ 最適合 |
| **自動化** | ❌ 不可能 | ✅ 完全支援 |
| **設定保存** | ✅ 立即生效 | ✅ 立即生效 |
| **斷電保持** | ✅ 是 | ✅ 是 |
| **設定時通道狀態** | ⚠️ 會關閉 | ✅ 保持原狀 |

### 驗證設定結果

無論使用哪種方法設定，都建議使用程式驗證：

**使用 verify 命令：**
```bash
# 啟動控制程式
python src/caparoc_controller.py

# 驗證通道額定電流
🎮 > verify 1
✅ CH1 額定電流: 4A

🎮 > verify 2
✅ CH2 額定電流: 6A
```

**使用 status 命令：**
```bash
🎮 > s

============================================================
  📊 系統狀態
============================================================
  模組數量: 1 個 (4 通道)
  系統電壓: 24.18 V
  總電流:   2.35 A
------------------------------------------------------------
  CH1: ⚫ OFF |   0.00 A / 4.0 A   ← 額定電流 4A
  CH2: ⚫ OFF |   0.00 A / 6.0 A   ← 額定電流 6A
  CH3: ⚫ OFF |   0.00 A / 10.0 A  ← 額定電流 10A
  CH4: ⚫ OFF |   0.00 A / 20.0 A  ← 額定電流 20A
============================================================
```

### 選擇建議

**使用場景推薦：**

1. **現場快速調整** → 手動控制（設備按鈕）⭐
   - 不需要電腦或網路
   - 立即可操作
   - 適合單一通道緊急調整
   - 適合非技術人員操作

2. **初始配置/批次設定** → 程式控制（init 命令）⭐
   - 一次設定多個通道
   - 可記錄配置歷史
   - 減少人為錯誤

3. **生產環境/自動化** → 程式控制（init 命令）⭐
   - 整合到測試流程
   - 自動化腳本控制
   - 可程式化管理

4. **開發/測試** → 程式控制（init 命令）⭐
   - 快速測試不同電流值
   - 即時驗證設定結果
   - 方便重複操作

**安全注意事項：**
- ⚠️ 設定額定電流前，建議先關閉通道
- ⚠️ 確認負載電流不超過新設定值
- ⚠️ 記錄設定變更（特別是生產環境）
- ⚠️ 定期檢查設定是否正確
- ✅ 建議建立設定檔案記錄各通道額定電流

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

# 3. 修改 CH2 的額定電流
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
[額定電流設定] CH2
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
   - 只會修改 CH2 的額定電流
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
[額定電流設定] CH1
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

在提交程式碼前，請確認：

- [ ] 使用 Read-Modify-Write 流程
- [ ] Status Byte 設為 2 (No Change)
- [ ] 遍歷所有通道進行保護
- [ ] 正確使用 Config Assembly (0x66)
- [ ] 參數範圍檢查（1-10A）
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

### 相關文件
- `docs/Config_Assembly_驗證報告.md`
- `docs/額定電流設定流程與故障排除.md`
- `docs/DEVELOPMENT_NOTES.md`

### Git 提交記錄
- `38518cb` - feat: 實作額定電流修改功能 (Phase 3-3)
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
- ✅ 程式碼已合併到功能分支
- ✅ 文件完整記錄

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

## 附錄：失敗歷史與成功關鍵對比

### 🔄 開發歷程時間軸

#### **第一階段：初始嘗試（2025-11-10）**

**Commit**: `a8b0842` - feat(config-assembly): 實作標稱 Config Assembly 額定電流設定方法

**方法**：使用 Parameter Object (Class 0x0F)
```python
# 嘗試使用 Parameter Object
service=0x10  # Set Attribute Single
class_code=0x0F  # Parameter Object
instance=param_number
```

**結果**：❌ 失敗
- 錯誤：Path segment error
- 原因：CAPAROC 不支援 Parameter Object 方法

---

#### **第二階段：Config Assembly 建構式方法（2025-11-10）**

**Commit**: `3996300` - feat(config): 實作 Config Assembly 完整六步驟流程與診斷功能

**方法**：從頭建立 244-byte 緩衝區
```python
# Step 1: 建立空緩衝區
config_data = bytearray(244)

# Step 2: 填入 'No Change' 預設值
# Param1-5 全設為 0 (No Change)
# 各通道參數設為預設值

# Step 3: 解除軟體鎖定
config_data[0] = 0  # Global lock
config_data[1] = 0  # UI lock

# Step 4: 設定目標電流值
offset = 6 + (module-1)*12 + (channel-1)*3
config_data[offset] = current_amps

# Step 5: 寫入
driver.generic_message(
    service=0x10,
    class_code=0x04,
    instance=0x66,
    request_data=config_data
)
```

**結果**：❌ 失敗
- 問題 1：244-byte 封包太大
- 問題 2：寫入後所有通道關閉
- 問題 3：不知道為什麼會關閉

**關鍵錯誤**：
```python
# ❌ 錯誤做法：建立空緩衝區
config_data = bytearray(244)  # 全是 0

# 問題：Status Byte 也是 0
# Byte 8, 11, 14, 17... = 0
# 導致所有通道被強制關閉！
```

---

#### **第三階段：放棄與刪除（2025-11-13）**

**Commit**: `d015545` - refactor: 刪除額定電流設定(init)相關的底層方法

**決策**：功能太複雜，暫時放棄
```python
# 刪除了 470 行程式碼
- initialize_all_channels()
- _get_config_param_number()
- _read_config_assembly()
- _check_and_unlock_programming()
- _set_nominal_current_parameter_object()
```

**原因**：
- 不清楚為什麼會關閉所有通道
- 嘗試了多種方法都失敗
- 決定專注在穩定的 on/off 功能

---

#### **第四階段：重新開始（2025-11-19）**

**Commit**: `38518cb` - feat: 實作額定電流修改功能 (Phase 3-3)

**轉捩點**：發現 Read-Modify-Write 方案

**新方法**：
```python
# ✅ 正確做法：先讀取現有配置
response = driver.generic_message(
    service=0x0E,  # 先讀取
    class_code=0x04,
    instance=0x66
)

config_data = bytearray(response.value)

# 只修改目標位置
config_data[offset] = new_value

# 寫回完整數據
driver.generic_message(
    service=0x10,  # 再寫入
    request_data=bytes(config_data)
)
```

**結果**：⚠️ 部分成功
- ✅ 功能可以執行
- ✅ 電流值可以修改
- ❌ 但仍然關閉所有通道！

---

#### **第五階段：添加警告（2025-11-24）**

**Commit**: `1e0bd48` - docs: 添加 Config Assembly 安全保護機制說明

**認知**：以為是 CAPAROC 的安全保護機制

```python
print("⚠️  注意: 設備正在套用新配置...")
print("ℹ️  CAPAROC 安全保護機制可能會關閉所有通道")
print("ℹ️  這是正常行為，請使用 'on' 命令重新開啟需要的通道")
```

**結果**：❌ 錯誤的理解
- 以為關閉通道是設備的「設計行為」
- 實際上是程式碼的 bug
- 用戶每次都要重新開啟，體驗很差

---

#### **第六階段：真相大白（2025-11-25）**

**Commit**: `67fbf69` - fix: 使用 Status Byte = 2 (No Change) 保護通道開關狀態

**關鍵發現**：Status Byte 的秘密！

查閱手冊 **Table 7-18** 才發現：

| Status Byte 值 | 意義 | 效果 |
|---------------|------|------|
| 0 | Channel off | ❌ 強制關閉 |
| 1 | Channel on | 強制開啟 |
| 2 | **No change** | ✅ 保持現狀 |

**真相**：
```python
# 問題根源：
# 即使使用 Read-Modify-Write，讀取回來的 Status Byte 可能是 0
# 寫回時，Status = 0 就會關閉通道！

# 解決方案：
struct.pack_into('<B', config_data, offset_status, 2)  # 設為 2!

# 進階保護：
for m in range(1, 17):
    for ch in range(1, 5):
        if config_data[ch_status_offset] == 0:
            config_data[ch_status_offset] = 2  # 全部改為 2
```

**結果**：✅ **完美解決！**
- 只修改電流值
- 不影響任何通道的開關狀態
- 已開啟的通道保持開啟
- 已關閉的通道保持關閉

---

### 🔍 失敗原因深度分析

#### **為什麼第二階段（建構式方法）失敗？**

```python
# ❌ 錯誤程式碼（2025-11-10）
config_data = bytearray(244)  # 初始化全是 0

# 結構分析：
# Byte 6:  CH1 Nominal Current = 0
# Byte 7:  CH1 Programming Lock = 0
# Byte 8:  CH1 Status = 0  ⚠️ 這會關閉 CH1！
# Byte 9:  CH2 Nominal Current = 0
# Byte 10: CH2 Programming Lock = 0
# Byte 11: CH2 Status = 0  ⚠️ 這會關閉 CH2！
# ...以此類推，所有通道都被關閉
```

**為什麼當時沒發現？**
1. 不知道 Status Byte 的存在
2. 沒有仔細閱讀 Table 7-18
3. 以為只要設定 Nominal Current 就好
4. 沒想到 Status Byte = 0 會關閉通道

#### **為什麼第四階段（Read-Modify-Write）仍然失敗？**

```python
# 看似正確的程式碼（2025-11-19）
response = driver.generic_message(service=0x0E, ...)
config_data = bytearray(response.value)

# 只修改 Nominal Current
config_data[offset_current] = new_value

# 寫回
driver.generic_message(service=0x10, request_data=config_data)
```

**問題**：讀取回來的 Status Byte 可能就是 0！

**為什麼是 0？**
1. 設備出廠預設可能是 0
2. 之前的操作可能寫入了 0
3. Config Assembly 可能沒有保存 Status 狀態
4. 每次讀取都是新的初始值

**關鍵認知**：
> Read-Modify-Write 只能保證「不破壞現有數據」
> 但如果現有數據本身就有問題（Status=0），
> 那寫回去還是會有問題！

---

### ✅ 成功關鍵

#### **關鍵 1：發現 Table 7-18**

沒有這張表，永遠不會知道 Status Byte 有三個值：
- 之前只知道 0 和 1（開/關）
- 不知道有 2（No Change）這個選項
- 這是 EDS 標準的一部分

#### **關鍵 2：理解 "No Change" 的意義**

```python
# Status = 2 的魔力
# 告訴設備：「這個欄位我不想改，保持原樣」
# 就像 SQL 的 UPDATE 不提及某個欄位一樣
```

#### **關鍵 3：主動設定而非被動讀取**

```python
# ❌ 錯誤思維：
# 讀取 Status，保持原值，寫回
# 問題：如果讀回來就是 0 呢？

# ✅ 正確思維：
# 不管讀回來是什麼，都主動設為 2
struct.pack_into('<B', config_data, offset_status, 2)
```

#### **關鍵 4：全通道保護機制**

```python
# 不只保護目標通道，保護所有通道
for m in range(1, 17):
    for ch in range(1, 5):
        if config_data[ch_status_offset] == 0:
            config_data[ch_status_offset] = 2
            
# 這樣即使程式碼有 bug，也不會關閉通道
```

---

### 📊 前後對比

| 項目 | 失敗版本（v1.0-v1.1） | 成功版本（v2.0） |
|------|---------------------|-----------------|
| **方法** | 建構式 / Read-Modify-Write | Read-Modify-Write + Status Protection |
| **Status 處理** | 忽略 / 保持原值 | 主動設為 2 (No Change) |
| **保護範圍** | 只有目標通道 | 所有通道 |
| **程式碼量** | 470 行 → 刪除 → 300 行 | 200 行（精簡） |
| **測試結果** | 關閉所有通道 | 完美運作 ✅ |
| **用戶體驗** | 每次都要重開 ❌ | 無感修改 ✅ |

---

### 💡 經驗教訓

#### **教訓 1：RTFM (Read The F***ing Manual)**

**問題**：
- 沒有仔細閱讀 Table 7-18
- 跳過了 Status Byte 的說明
- 以為只要知道結構就夠了

**正確做法**：
- 每個 byte 的意義都要搞清楚
- 特別注意 "No Change" 這類特殊值
- 手冊的每個表格都有用

#### **教訓 2：不要猜測設備行為**

**問題**：
- 以為「關閉通道」是設備的保護機制
- 沒有深究真正原因
- 用「正常行為」來合理化 bug

**正確做法**：
- 工業設備不應該這麼「智慧」
- 如果行為不合理，一定是程式碼有問題
- 不要用「可能是設計如此」來逃避

#### **教訓 3：從簡單開始**

**問題**：
- 一開始就想建構完整的 244-byte 封包
- 太複雜，容易出錯
- 調試困難

**正確做法**：
- 先用 Read-Modify-Write 確保基本功能
- 再加入保護機制
- 一步一步測試

#### **教訓 4：相信測試結果**

**問題**：
- 測試發現「所有通道關閉」
- 但說服自己「這是正常的」
- 沒有繼續追查

**正確做法**：
- 測試結果不對就是不對
- 不要美化 bug
- 追查到底才是負責任的做法

---

### 🎯 核心差異總結

**失敗的核心原因**：
```python
# 不知道 Status Byte 的存在和意義
# 即使知道，也不知道可以用 2 (No Change)
# 導致每次寫入都關閉通道
```

**成功的核心關鍵**：
```python
# 發現 Table 7-18
# 理解 Status Byte = 2 (No Change) 的魔力
# 主動保護所有通道
struct.pack_into('<B', config_data, offset_status, 2)
```

**一行程式碼的差異**：
```python
# 失敗：
config_data[offset_status] = 0  # 或根本沒設定

# 成功：
config_data[offset_status] = 2  # ⭐ 就是這一行！
```

---

**文件版本**: 1.0  
**最後更新**: 2025-11-25
**作者**: Harry  
**狀態**: ✅ 已完成並測試通過
