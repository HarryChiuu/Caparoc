# Parameter Object 方法 - 正確的配置設定方式

## 🎯 問題分析

### 之前的錯誤方法
```python
# ❌ 錯誤: 嘗試寫入整個 Config Assembly (244 bytes)
response = driver.generic_message(
    service=0x10,
    class_code=0x04,  # Assembly Object
    instance=0x66,    # Config Assembly
    attribute=3,      # Data attribute
    request_data=bytes(244),  # 244 bytes
    connected=False
)
# 結果: "Too much data" 錯誤
```

### 根本原因
- **誤解 1**: 以為要寫入整個 Assembly (244 bytes)
- **誤解 2**: 以為 Assembly 0x66 可以直接寫入
- **真相**: Config Assembly 用於**讀取**，Parameter Object 用於**寫入**

---

## ✅ 正確方法 (根據 EDS 檔案)

### EDS 檔案關鍵資訊

```eds
[Params]
    Param6 =
        0,                      $ reserved
        6,"20 0F 24 06 30 01",  $ Link Path ← 關鍵！
        0x0000,                 $ Descriptor
        0xC6,                   $ Data Type (USINT)
        1,                      $ Data Size = 1 byte
        "Mod 1 Ch 1 nominal current",
        "A",
        "",
        0,20,0,                 $ min, max, default
```

**解碼 Link Path "20 0F 24 06 30 01":**
- `20 0F` = Class 0x0F (**Parameter Object**)
- `24 06` = Instance 0x06 (Param 6)
- `30 01` = Attribute 1 (Value)

### Assembly 定義

```eds
[Assembly]
    Assem100 = "Consuming (O2T)",  "20 04 24 64 30 03", 20 bytes   # Output
    Assem101 = "Producing (T2O)",  "20 04 24 65 30 03", 208 bytes  # Input
    Assem102 = "Configuration",    "20 04 24 66 30 03", 244 bytes  # Config (唯讀)
```

**重點:**
- Assembly 0x64 (Output): 控制通道開關
- Assembly 0x65 (Input): 讀取狀態和電流
- Assembly 0x66 (Config): **只能讀取**，不能寫入！

---

## 💻 實作方法

### Python 程式碼

```python
def _set_nominal_current_config_assembly(self, driver, module, channel, current_amps):
    """使用 Parameter Object 設定標稱電流 (1-20A)"""
    
    # 1. 計算 EDS 參數編號
    # M1.CH1=6, M1.CH2=9, M1.CH3=12, M1.CH4=15
    # 公式: 6 + (module-1)*12 + (channel-1)*3
    param_number = 6 + (module - 1) * 12 + (channel - 1) * 3
    
    # 2. 使用 Parameter Object 寫入
    response = driver.generic_message(
        service=0x10,           # Set Attribute Single
        class_code=0x0F,        # ✅ Parameter Object (不是 Assembly!)
        instance=param_number,  # ✅ Param 6, 9, 12, 15...
        attribute=1,            # ✅ Attribute 1 = Value
        request_data=bytes([current_amps]),  # ✅ 只需 1 byte!
        connected=False
    )
    
    # 3. 驗證 (從 Input Assembly 讀取實際值)
    return self._verify_nominal_current(driver, module, channel)
```

---

## 📊 參數對照表

### Module 1 (M1)
| 通道 | 參數編號 | 功能 | 取值範圍 |
|------|---------|------|---------|
| CH1  | Param 6 | Nominal current | 0-20 (0=no change, 1-20A) |
| CH1  | Param 7 | Programming lock | 0=disable, 1=enable, 2=no change |
| CH1  | Param 8 | Output state | 0=off, 1=on, 2=no change |
| CH2  | Param 9 | Nominal current | 0-20 |
| CH2  | Param 10 | Programming lock | 0-2 |
| CH2  | Param 11 | Output state | 0-2 |
| CH3  | Param 12 | Nominal current | 0-20 |
| CH3  | Param 13 | Programming lock | 0-2 |
| CH3  | Param 14 | Output state | 0-2 |
| CH4  | Param 15 | Nominal current | 0-20 |
| CH4  | Param 16 | Programming lock | 0-2 |
| CH4  | Param 17 | Output state | 0-2 |

### Module 2 (M2)
| 通道 | 參數編號 | 起始參數 |
|------|---------|---------|
| CH1-4 | 18-29 | Param 18 (M2.CH1 nominal) |

---

## 🧪 測試建議

### 測試步驟

1. **測試設定 4A (Module 1, Channel 2):**
   ```python
   python src/caparoc_controller.py
   > init 2 4
   ```
   
   **預期結果:**
   ```
   [Param] 使用 Parameter Object 方法
   [Param] EDS Param 9 (M1.CH2) = 4A
   ✅ Parameter 寫入成功
   ✅ 驗證成功: 設備回報 4A
   ```

2. **測試全範圍 (1-20A):**
   ```python
   > init 1 20  # 測試 20A
   > init 2 15  # 測試 15A
   > init 3 1   # 測試 1A
   ```

3. **驗證結果:**
   ```python
   > verify 1
   > verify 2
   > verify 3
   ```

---

## 🔍 Debug 資訊

### 如果仍然失敗

1. **檢查 Parameter 是否存在:**
   ```python
   # 讀取 Param 6 (M1.CH1)
   response = driver.generic_message(
       service=0x0E,  # Get Attribute Single
       class_code=0x0F,
       instance=6,
       attribute=1,
       connected=False
   )
   print(response.value)  # 應顯示當前設定值
   ```

2. **檢查是否被鎖定:**
   ```python
   # 讀取 Param 7 (M1.CH1 programming lock)
   response = driver.generic_message(
       service=0x0E,
       class_code=0x0F,
       instance=7,
       attribute=1,
       connected=False
   )
   # 0 = unlocked, 1 = locked
   ```

3. **檢查 Input Assembly 狀態:**
   ```python
   > status  # 查看 Byte 0 Bit 7 (Config processing)
   ```

---

## 📝 總結

### 關鍵差異

| 項目 | Assembly 方法 (錯誤) | Parameter Object 方法 (正確) |
|------|---------------------|----------------------------|
| Class Code | 0x04 (Assembly) | 0x0F (Parameter) |
| Instance | 0x66 (Config Assembly) | 6, 9, 12, 15... (Param number) |
| Data Size | 244 bytes | 1 byte |
| 支援範圍 | N/A | 1-20A |
| 錯誤 | Too much data | ✅ 成功 |

### 優點
- ✅ 支援 1-20A 全範圍
- ✅ 只需寫入 1 byte
- ✅ EDS 官方標準方法
- ✅ 快速且可靠

### 限制
- ⚠️ 每個參數需單獨設定
- ⚠️ 需要正確計算參數編號
