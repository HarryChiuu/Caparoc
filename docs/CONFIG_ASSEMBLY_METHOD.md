# Config Assembly 寫入方法說明

## 問題分析

### 原先的問題
使用 Parameter Object (Class 0x0F) 時出現 "Too much data" 錯誤:
```
[Param] 嘗試方法 3: 使用 class_code 方式...
❌ 方法 3 失敗: Too much data
```

### 根本原因
1. **錯誤的假設**: 以為可以用 Parameter Object 直接寫入單一參數
2. **實際情況**: pycomm3 的 `generic_message()` 可能不完全支援 Parameter Object (Class 0x0F)
3. **"Too much data" 錯誤**: 
   - 嘗試寫入 1 byte 到 Parameter Object
   - 設備可能期望不同的資料格式
   - 或 pycomm3 在幕後加了額外的 header/metadata

## 正確方法: Config Assembly 讀取-修改-寫入

### EDS 檔案分析

根據 `CAPAROC_PM_EIP.eds` 第 8274 行:

```
Assem102 =
    "Configuration Assembly",
    "20 04 24 66 30 03",  # Class 0x04, Instance 0x66, Attribute 3
    244,                  # Total size: 244 bytes
    0x0000,
    ,,
    8,Param1,            # offset 0, 1 byte
    8,Param2,            # offset 1, 1 byte
    16,Param3,           # offset 2-3, 2 bytes
    8,Param4,            # offset 4, 1 byte
    8,Param5,            # offset 5, 1 byte
    8,Param6,            # offset 6, 1 byte ← M1.CH1 標稱電流
    8,Param7,            # offset 7, 1 byte
    8,Param8,            # offset 8, 1 byte
    8,Param9,            # offset 9, 1 byte ← M1.CH2 標稱電流
    8,Param10,           # offset 10, 1 byte
    8,Param11,           # offset 11, 1 byte
    8,Param12,           # offset 12, 1 byte ← M1.CH3 標稱電流
    8,Param13,           # offset 13, 1 byte
    8,Param14,           # offset 14, 1 byte
    8,Param15,           # offset 15, 1 byte ← M1.CH4 標稱電流
    ...
```

### 參數位置對應表

| 參數 | Offset | 用途 | 範圍 |
|------|--------|------|------|
| Param1 | 0 | 全域設定 | - |
| Param2 | 1 | 全域設定 | - |
| Param3 | 2-3 | 全域設定 (16-bit) | - |
| Param4 | 4 | 全域設定 | - |
| Param5 | 5 | 全域設定 | - |
| **Param6** | **6** | **M1.CH1 標稱電流** | **1-20A** |
| Param7 | 7 | - | - |
| Param8 | 8 | - | - |
| **Param9** | **9** | **M1.CH2 標稱電流** | **1-20A** |
| Param10 | 10 | - | - |
| Param11 | 11 | - | - |
| **Param12** | **12** | **M1.CH3 標稱電流** | **1-20A** |
| Param13 | 13 | - | - |
| Param14 | 14 | - | - |
| **Param15** | **15** | **M1.CH4 標稱電流** | **1-20A** |

### 實作步驟

```python
def _set_nominal_current_config_assembly(driver, module, channel, current_amps):
    """
    使用 Config Assembly 讀取-修改-寫入方法
    """
    # Step 1: 計算 offset
    param_number = 6 + (module-1)*12 + (channel-1)*3
    config_offset = param_number  # 對於已知參數,offset = param_number
    
    # Step 2: 讀取整個 Config Assembly (244 bytes)
    read_response = driver.generic_message(
        service=0x0E,        # Get Attribute Single
        class_code=0x04,     # Assembly Object
        instance=0x66,       # Config Assembly
        attribute=3,         # Data
        connected=False
    )
    
    config_data = bytearray(read_response.value)  # 244 bytes
    
    # Step 3: 修改對應的 byte
    config_data[config_offset] = current_amps
    
    # Step 4: 寫回整個 Config Assembly (244 bytes)
    write_response = driver.generic_message(
        service=0x10,        # Set Attribute Single
        class_code=0x04,     # Assembly Object
        instance=0x66,       # Config Assembly
        attribute=3,         # Data
        request_data=bytes(config_data),  # 完整的 244 bytes
        connected=False
    )
    
    # Step 5: 驗證
    time.sleep(1.0)
    actual = verify_nominal_current(driver, module, channel)
    return actual == current_amps
```

## 為什麼這個方法可以運作?

### Set Attribute Single 的特性
- Service 0x10 (Set Attribute Single) 會**完整覆寫**整個 Attribute
- Config Assembly Attribute 3 的大小 = 244 bytes
- 必須提供完整的 244 bytes,不能只提供部分

### 與 Parameter Object 的比較

| 方法 | Class | Instance | Attribute | Data Size | 問題 |
|------|-------|----------|-----------|-----------|------|
| Parameter Object | 0x0F | Param# (6,9...) | 1 | 1 byte | ❌ pycomm3 不支援 |
| Config Assembly | 0x04 | 0x66 | 3 | 244 bytes | ✅ 完整讀寫 |

### 優缺點分析

**Config Assembly 方法:**
- ✅ 可靠性高 (Assembly Object 是標準 CIP 物件)
- ✅ pycomm3 完全支援
- ✅ 可以一次修改多個參數
- ⚠️ 需要讀取-修改-寫入三步驟
- ⚠️ 寫入 244 bytes (較大的封包)

**Parameter Object 方法:**
- ✅ 理論上更優雅 (只寫 1 byte)
- ✅ EDS 文件支援
- ❌ pycomm3 可能不完全支援 Class 0x0F
- ❌ 實測出現 "Too much data" 錯誤

## 測試方法

### 1. 測試 Config Assembly 讀取
```bash
python src/caparoc_controller.py
> verify 2
```
觀察是否能正確讀取 CH2 的標稱電流。

### 2. 測試 Config Assembly 寫入
```bash
python src/caparoc_controller.py
> init 2 4
```

預期輸出:
```
[初始化] CH2: 設定額定電流 4A
       [Config] 使用 Config Assembly 讀取-修改-寫入方法
       [Config] Param9 (M1.CH2) @ offset 9
       [Config] Step 1: 讀取 Config Assembly 0x66...
       ✅ 讀取成功: 244 bytes
       [Config] Step 2: 修改 offset 9: 3A -> 4A
       [Config] Step 3: 寫回 Config Assembly (244 bytes)...
       ✅ Config Assembly 寫入成功
       ✅ 驗證成功: 設備回報 4A
✅ CH2 完成
```

### 3. 驗證結果
```bash
> verify 2
```

預期輸出:
```
CH2: 標稱電流 = 4A
```

## 後續改進

### 可能的優化
1. **快取 Config Assembly**: 一次讀取,多次修改
2. **批次寫入**: 一次設定多個通道
3. **差異檢測**: 只在值改變時寫入

### 如果 Parameter Object 能用
如果找到正確的 pycomm3 API 使用方式,可以改回:
```python
# 更簡潔的寫法 (如果可行)
driver.write(f"Param{param_number}", current_amps)
# 或
driver.generic_message(
    service=0x10,
    class_code=0x0F,
    instance=param_number,
    attribute=1,
    request_data=bytes([current_amps])
)
```

但目前 Config Assembly 方法是**最可靠的選擇**。

## 參考資料
- EDS 檔案: `CAPAROC_PM_EIP.eds` 第 8274 行
- CIP Specification: Assembly Object (Class 0x04)
- pycomm3 文件: https://github.com/ottowayi/pycomm3
