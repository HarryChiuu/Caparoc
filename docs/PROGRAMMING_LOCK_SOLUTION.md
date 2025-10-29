# Programming Lock 解決方案

## 問題診斷

### 觀察到的行為
```
[Config] Step 1: 讀取 Config Assembly 0x66...
✅ 讀取成功: 244 bytes
[Config] Step 2: 修改 offset 9: 0A -> 4A
[Config] Step 3: 寫回 Config Assembly (244 bytes)...
❌ 寫入失敗: Too much data
```

### 關鍵發現

1. **Config Assembly 可讀但不可寫**:
   - Config Assembly (0x66) 主要用於**建立連線時**的配置
   - 運行時無法直接寫入 (會出現 "Too much data" 錯誤)
   - 這是 EtherNet/IP 的設計限制

2. **Programming Lock 的影響**:
   根據 EDS 檔案 (Line 454-466):
   ```
   Param7 = "Mod 1 Ch 1 programming lock"
   Param10 = "Mod 1 Ch 2 programming lock"
   Param13 = "Mod 1 Ch 3 programming lock"
   Param16 = "Mod 1 Ch 4 programming lock"
   ```
   
   Lock 值:
   - `0` = Unlocked (允許修改)
   - `1` = Locked via button
   - `2` = Locked via communication (**預設值**)

3. **正確的寫入方式**:
   - 必須使用 **Parameter Object (Class 0x0F)** 直接寫入
   - 但需要**先解鎖** programming lock

## 實作的解決方案

### Step 1: 檢查並解鎖 Programming Lock

```python
def _check_and_unlock_programming(driver, module, channel):
    """
    檢查並解鎖通道的 programming lock
    """
    # 計算 lock 參數編號
    # Param6 = M1.CH1 nominal current
    # Param7 = M1.CH1 programming lock
    # 每個通道間隔 3 個參數
    base_param = 6 + (module - 1) * 12 + (channel - 1) * 3
    lock_param = base_param + 1  # nominal current 的下一個參數
    
    # 讀取當前 lock 狀態
    read_response = driver.generic_message(
        service=0x0E,          # Get Attribute Single
        class_code=0x0F,       # Parameter Object
        instance=lock_param,   # Param7/10/13/16...
        attribute=1,           # Value
        connected=False
    )
    
    if lock_value != 0:
        # 解鎖
        unlock_response = driver.generic_message(
            service=0x10,          # Set Attribute Single
            class_code=0x0F,       # Parameter Object
            instance=lock_param,
            attribute=1,
            request_data=bytes([0]),  # 0 = Unlocked
            connected=False
        )
```

### Step 2: 寫入 Nominal Current

嘗試兩種方法:

#### 方法 A: Config Assembly (可能失敗)
```python
# 讀取 244 bytes
config_data = read_config_assembly()

# 修改對應 byte
config_data[offset] = current_amps

# 寫回 244 bytes (可能失敗: "Too much data")
write_config_assembly(config_data)
```

#### 方法 B: Parameter Object (解鎖後應該成功)
```python
# 直接寫入 Parameter
response = driver.generic_message(
    service=0x10,          # Set Attribute Single
    class_code=0x0F,       # Parameter Object
    instance=param_number, # Param6/9/12/15...
    attribute=1,           # Value
    request_data=bytes([current_amps]),
    connected=False
)
```

### Step 3: 驗證結果

```python
# 從 Input Assembly 讀取實際值
actual_current = read_nominal_current_from_input_assembly()

if actual_current == current_amps:
    print("✅ 驗證成功")
else:
    print(f"⚠️  驗證失敗: 期望 {current_amps}A, 實際 {actual_current}A")
```

## 參數對應表

| 通道 | Nominal Current Param | Programming Lock Param | Config Offset |
|------|----------------------|------------------------|---------------|
| M1.CH1 | Param6 | Param7 | 6 |
| M1.CH2 | Param9 | Param10 | 9 |
| M1.CH3 | Param12 | Param13 | 12 |
| M1.CH4 | Param15 | Param16 | 15 |

計算公式:
```python
# Nominal current parameter
nominal_param = 6 + (module-1)*12 + (channel-1)*3

# Programming lock parameter
lock_param = nominal_param + 1

# Config Assembly offset (for reference only, writing not supported)
config_offset = nominal_param
```

## 測試步驟

### 1. 測試 Programming Lock 讀取
```bash
python src/caparoc_controller.py
> init 2 4
```

預期輸出:
```
[初始化] CH2: 設定額定電流 4A
       [Lock] 檢查 Param10 (M1.CH2 programming lock)...
       [Lock] 當前狀態: Locked(Comm)
       [Lock] 嘗試解鎖...
       ✅ 解鎖成功
       [Config] Step 1: 讀取 Config Assembly 0x66...
       ✅ 讀取成功: 244 bytes
       [Config] Step 2: 修改 offset 9: 0A -> 4A
       [Config] Step 3: 寫回 Config Assembly (244 bytes)...
       ❌ Config Assembly 寫入失敗: Too much data
       [Param] 嘗試直接寫入 Parameter Object...
       ✅ Parameter Object 寫入成功!
       ✅ 驗證成功: 設備回報 4A
✅ CH2 完成
```

### 2. 驗證結果
```bash
> verify 2
```

預期輸出:
```
CH2: 標稱電流 = 4A
```

## 可能的結果

### 情況 1: Programming Lock 解鎖成功,Parameter Object 寫入成功
```
✅ 最佳結果
- Lock 解鎖成功
- Parameter Object 寫入成功
- 驗證顯示正確值
```

### 情況 2: Programming Lock 解鎖失敗
```
⚠️  Lock 可能被硬體開關保護
- 需要檢查設備上的實體開關
- 或透過設備網頁介面解鎖
```

### 情況 3: Parameter Object 仍然失敗
```
❌ pycomm3 可能不支援 Parameter Object 寫入
- 回退到 LED 按鈕模擬
- 限制範圍 1-10A
```

### 情況 4: Config Assembly 意外成功
```
✅ 某些設備可能允許運行時修改 Config
- 這將是最理想的情況
- 可以簡化程式碼
```

## 後續改進方向

### 如果 Parameter Object 方法成功
1. **移除 Config Assembly 嘗試** (節省時間)
2. **優化 Lock 檢查** (快取 lock 狀態)
3. **批次解鎖** (一次解鎖所有通道)

### 如果仍然失敗
1. **研究 pycomm3 原始碼** (了解路徑構建)
2. **使用 Wireshark 抓包** (比較正確的 CIP 封包格式)
3. **嘗試其他 CIP 庫** (例如 cpppo)
4. **接受 LED 按鈕方法** (可靠但有限制)

## 技術參考

### EDS 文件關鍵資訊
- **Line 429-453**: Param6 (M1.CH1 nominal current)
- **Line 454-466**: Param7 (M1.CH1 programming lock)
- **Line 8274-8370**: Assem102 (Config Assembly 結構)
- **Line 8493-8502**: Connection1 (Config Assembly 用途)

### CIP Services
- `0x0E` = Get Attribute Single (讀取單一屬性)
- `0x10` = Set Attribute Single (寫入單一屬性)
- `0x4B` = Set Parameters (可能的替代方案,未測試)

### pycomm3 API
```python
driver.generic_message(
    service=0x10,       # CIP Service Code
    class_code=0x0F,    # CIP Class (0x04=Assembly, 0x0F=Parameter)
    instance=param_num, # Object Instance Number
    attribute=1,        # Attribute Number
    request_data=bytes([value]),
    connected=False     # Use unconnected messaging
)
```

## 預期成果

執行 `init 2 4` 後:
- ✅ Programming lock 被解鎖
- ✅ Nominal current 設定為 4A
- ✅ Input Assembly 回報 4A
- ✅ 通道可以正常開關
- ✅ 電流限制正確應用

這將解決之前 "Too much data" 的問題,並實現完整的 1-20A 範圍設定! 🎯
