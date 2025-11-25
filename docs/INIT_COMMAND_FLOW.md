# Init 命令執行流程

## 📋 概述

`init` 命令用於修改通道的標稱電流設定，並在修改前後即時顯示當前值。

## 🔄 執行流程

### 命令格式

```bash
init <通道編號> <電流值>
```

**範例**：
```bash
init 4 10    # 設定 CH4 為 10A
```

### 執行步驟

```
┌─────────────────────────────────────────────────────┐
│  Step 1: 讀取當前標稱電流值                          │
│  ├─ 使用 _read_nominal_current_silent()             │
│  └─ 靜默讀取，不顯示 Debug 訊息                      │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Step 2: 顯示變更警告                               │
│  ⚠️  變更警告: CH4 目前為 5A，修改設定為 10A         │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Step 3: 執行 Read-Modify-Write                     │
│  ├─ 讀取 Config Assembly (Instance 0x66)            │
│  ├─ 修改目標通道的 Nominal Current                   │
│  ├─ 設定 Status Byte = 2 (No Change)                │
│  └─ 寫回 Config Assembly                            │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Step 4: 短暫等待應用配置 (0.3秒)                   │
│  └─ 給設備時間應用（實測發現幾乎是即時的）           │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Step 5: 讀取修改後的標稱電流值                      │
│  ├─ 使用 _read_nominal_current_silent()              │
│  └─ 驗證設定是否成功                                 │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│  Step 6: 顯示變更結果                               │
│  ✅ 變更已執行: CH4 目前為 10A                       │
└─────────────────────────────────────────────────────┘
```

## 📺 輸出範例

### 成功案例

```
> init 4 10

[標稱電流設定] CH4
⚠️  變更警告: CH4 目前為 5A，修改設定為 10A
   Config Offset: Byte 15 (Current), 17 (Status)
   [步驟1] 讀取 Config Assembly...
   ✅ 讀取成功 (長度: 244 bytes)
   [步驟2] 修改設定...
   Nominal Current: 5A -> 10A
   Status: 0 -> 2 (No Change - 保持現狀)
   [保護] 設定所有通道 Status = 2 (No Change)...
   ✅ 所有通道已保護
   [步驟3] 寫回 Config Assembly...
   ✅ Config Assembly 已更新

   💡 機制說明:
   - 使用 Status Byte = 2 (No Change) 保護所有通道
   - 只會修改 CH4 的標稱電流
   - 其他通道的開關狀態不會被影響！

   [驗證] 讀取修改後的標稱電流...
✅ 變更已執行: CH4 目前為 10A
```

### 首次設定（無舊值）

```
> init 1 8

[標稱電流設定] CH1
   目標電流: 8A
   Config Offset: Byte 6 (Current), 8 (Status)
   [步驟1] 讀取 Config Assembly...
   ...
✅ 變更已執行: CH1 目前為 8A
```

### 驗證失敗（但設定已寫入）

```
> init 2 15

[標稱電流設定] CH2
⚠️  變更警告: CH2 目前為 10A，修改設定為 15A
   ...
   ✅ Config Assembly 已更新

   [驗證] 等待設備應用設定...
⚠️  無法驗證（讀取失敗），但設定已寫入
```

## 🔍 關鍵方法

## 🔍 關鍵方法

### `_read_nominal_current_silent()`

**用途**: 靜默讀取標稱電流值，不顯示調試訊息

**調用時機**:
1. 修改前：讀取舊值並顯示警告
2. 修改後：讀取新值並確認

### ~~`_wait_for_config_processing()`~~ (已移除)

**原本用途**: 監測 Input Assembly Byte 0 Bit 7

**移除原因**:
- 監測耗時 5 秒（太慢）
- 實測發現 Config Assembly 寫入後設備立即應用
- 使用 `status` 命令可立即看到新值
- 改用 `sleep(0.3)` + 直接驗證更快

**保留方法**: 代碼中保留了 `_wait_for_config_processing()` 方法以備將來需要

### `_verify_nominal_current()`

**用途**: 驗證標稱電流值，顯示詳細調試訊息

```python
def _read_nominal_current_silent(self, driver, module, channel):
    """讀取 Input Assembly (0x65) Byte 1"""
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
        nominal_current = data[offset + 1]  # Byte 1
        return int(nominal_current)
    
    return None
```

**調用時機**:
1. 修改前：讀取舊值並顯示警告
2. 修改後：讀取新值並確認

### `_verify_nominal_current()`

**用途**: 驗證標稱電流值，顯示詳細調試訊息

**調用時機**:
- 使用者手動執行 `verify <ch>` 命令

**輸出範例**:
```
       [驗證Debug] Input Assembly offset 6:
                   Byte 0 (status): 0x01
                   Byte 1 (nominal): 10A
                   Byte 2: 0x00
                   Byte 3: 0x00
```

## 🎯 用戶體驗改進

### 改進前

```
> init 4 10

[標稱電流設定] CH4
   目標電流: 10A
   ...
   ✅ 驗證成功: 10A
```

❌ 問題：
- 看不到修改前的舊值
- 不清楚是否真的改變了

### 改進後

```
> init 4 10

[標稱電流設定] CH4
⚠️  變更警告: CH4 目前為 5A，修改設定為 10A
   ...
✅ 變更已執行: CH4 目前為 10A
```

✅ 優點：
- 清楚顯示舊值 → 新值
- 明確告知變更已執行
- 可立即確認修改結果

## 🔧 技術細節

### Input Assembly 結構 (Instance 0x65)

每個通道佔用 4 bytes：

| Offset | 內容 | 說明 |
|--------|------|------|
| +0 | Status Byte | 通道狀態 (0x00=Off, 0x01=On) |
| +1 | **Nominal Current** | ⭐ 標稱電流值 (0-20A) |
| +2 | Current (Low) | 實際電流低字節 |
| +3 | Current (High) | 實際電流高字節 |

**範例**：
```
CH1: Offset 6  (Header 6 bytes + CH1 0 bytes)
CH2: Offset 10 (Header 6 bytes + CH1 4 bytes)
CH3: Offset 14 (Header 6 bytes + CH1+CH2 8 bytes)
CH4: Offset 18 (Header 6 bytes + CH1+CH2+CH3 12 bytes)
```

### 讀取時機對比

| 時機 | Assembly | Service | Connected | 目的 |
|------|----------|---------|-----------|------|
| **修改前/後** | Input (0x65) | 0x0E (Read) | False | 讀取當前標稱電流 |
| **修改中** | Config (0x66) | 0x0E (Read) | True | 讀取完整配置 |
| **寫入** | Config (0x66) | 0x10 (Write) | True | 寫回修改後配置 |

## 📝 錯誤處理

### 讀取失敗（修改前）

```python
current_value = self._read_nominal_current_silent(...)
if current_value is not None:
    print(f"⚠️  變更警告: CH{x} 目前為 {current_value}A，修改設定為 {y}A")
else:
    print(f"   目標電流: {y}A")  # ← 降級顯示
```

### 驗證失敗（修改後）

```python
actual = self._read_nominal_current_silent(...)
if actual is not None:
    if actual == current_amps:
        print(f"✅ 變更已執行: CH{x} 目前為 {actual}A")
    else:
        print(f"⚠️  驗證警告: 設備顯示 {actual}A，設定值 {current_amps}A")
        print(f"   建議: 請使用 'verify {ch}' 命令再次確認")
else:
    print(f"⚠️  無法驗證（讀取失敗），但設定已寫入")
```

## 🔄 完整調用鏈

```
main()
  └─ run()
      └─ 命令迴圈
          └─ elif cmd.startswith('init '):
              ├─ 解析參數 (channel, current_amps)
              ├─ 驗證範圍
              └─ set_nominal_current(module, channel, current_amps)
                  ├─ [Before] _read_nominal_current_silent()  ← 讀取舊值
                  ├─ [Modify] Read-Modify-Write (Config 0x66)
                  └─ [After]  _read_nominal_current_silent()  ← 讀取新值
```

---

**文檔版本**: 1.0  
**最後更新**: 2025-11-25  
**相關功能**: 標稱電流修改 (Phase 3-3)
