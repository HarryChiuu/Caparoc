# CAPAROC 控制程式運作流程

> **文檔版本**: v1.0  
> **最後更新**: 2025-11-13  
> **對應程式版本**: caparoc_controller.py v3.7

---

## 📚 目錄

1. [程式架構概述](#1-程式架構概述)
2. [啟動流程詳解](#2-啟動流程詳解)
3. [核心功能流程](#3-核心功能流程)
4. [Assembly 通訊機制](#4-assembly-通訊機制)
5. [錯誤處理與重連](#5-錯誤處理與重連)
6. [多模組支援機制](#6-多模組支援機制)

---

## 1. 程式架構概述

### 1.1 檔案結構

```
Caparoc5/
├── src/
│   ├── caparoc_controller.py      # 主控制程式（2090 行）
│   └── caparoc_controller_old.py  # 舊版備份
├── tests/
│   ├── diagnostic_tools.py        # 診斷工具集
│   └── check_connection.py        # 連線檢查工具
└── docs/
    ├── MAIN_PROGRAM_FLOW.md       # 本文檔
    └── DIAGNOSTIC_TOOLS_GUIDE.md  # 診斷工具指南
```

### 1.2 核心類別: CaparocController

```python
class CaparocController:
    """CAPAROC 斷路器控制器 - 基於手冊規範"""
    
    # 主要屬性
    - device_ip: 設備 IP 位址
    - module_count: 模組數量（動態檢測，1-16）
    - channels_per_module: 每模組通道數（固定 4）
    - monitor_running: 監控執行狀態
    - help_shown: 幫助信息顯示標記
    
    # Assembly 設定
    - output_instance: 0x64 (Output Assembly, 18 bytes)
    - input_instance: 0x65 (Input Assembly, 244 bytes)
    - config_instance: 0x66 (Config Assembly, 唯讀)
```

### 1.3 主要功能模組

| 模組 | 功能 | 主要方法 |
|------|------|----------|
| **連線管理** | 設備連線、斷線重連 | `check_device_connection()`, `run()` |
| **額定電流** | 通道電流初始化 | `_set_nominal_current_parameter_object()` |
| **通道控制** | 開關控制 | `set_channel()`, `_read_and_show_result()` |
| **狀態監控** | 即時狀態讀取 | `show_status()`, `start_monitor()` |
| **系統診斷** | 全域狀態檢查 | `check_global_system_status()` |

---

## 2. 啟動流程詳解

### 2.1 主程式入口

```python
def main():
    controller = CaparocController()
    while True:
        result = controller.run()
        if result == 'reconnect':
            print("\n[系統] 重新啟動連線與初始化流程...\n")
            continue
        break
```

**重連機制**: 當 `run()` 返回 `'reconnect'` 時，重新執行整個初始化流程。

### 2.2 run() 方法完整流程

#### **Step 0: 裝置連線檢查**

```
目的: 驗證設備是否在線
方法: check_device_connection()
檢查項目:
  - 讀取 Input Assembly (0x65)
  - 驗證資料長度 >= 6 bytes
  - 解析模組數量 (Byte 1)
```

**成功條件**: 
- ✅ 連線成功
- ✅ Input Assembly 可讀取
- ✅ 模組數量 > 0

**失敗處理**:
- ❌ 顯示錯誤訊息
- ❌ 提供重連或退出選項

---

#### **Step 1: IP 配置（可選）**

```
提示: "是否要變更設備 IP? [y/N]"
方法: _configure_device_ip()
驗證: _validate_ip()
```

**IP 格式驗證**:
- 必須符合 `xxx.xxx.xxx.xxx` 格式
- 每個數字必須在 0-255 範圍內

---

#### **Step 2: 模組數量檢測**

```
來源: Input Assembly Byte 1
範圍: 0-16 個模組
計算總通道數: module_count × 4
```

**檢測結果範例**:
```
✅ 檢測到 1 個模組 (4 通道)
✅ 檢測到 2 個模組 (8 通道)
```

---

#### **Step 3: 全域系統狀態檢查**

```python
status = self.check_global_system_status()
檢查項目:
  ├── Byte 0: 系統狀態位元組
  │   ├── bit 0: Undervoltage (欠壓)
  │   ├── bit 1: Overvoltage (過壓)
  │   ├── bit 2: System Error (系統錯誤)
  │   ├── bit 3: 80% Warning (80%警告)
  │   └── bit 4: Total Shutdown (總電流關斷)
  │
  ├── Byte 2-3: 總電流 (0.0-50.0A)
  └── Byte 4-5: 系統電壓 (9.0-30.5V)
```

**安全檢查邏輯**:
```python
if 欠壓 or 過壓 or 系統錯誤 or 總電流關斷:
    status['safe'] = False
    提示使用者是否繼續 [y/N]
```

---

#### **Step 4: 讀取並同步設備狀態**

**目的**: 避免誤關閉運行中的通道

```python
從 Input Assembly 讀取各通道實際狀態:
  ├── CH1: Byte 6 (Status)
  ├── CH2: Byte 9 (Status)
  ├── CH3: Byte 12 (Status)
  └── CH4: Byte 15 (Status)

同步到 Output Assembly:
  根據實際狀態重建 output_data buffer
```

**狀態顯示範例**:
```
設備當前狀態:
  CH1: 🟢 開 (2.3A)
  CH2: 🔴 關 (0.0A)
  CH3: 🟢 開 (1.5A)
  CH4: 🔴 關 (0.0A)
```

---

#### **Step 5: 額定電流初始化**

```
提示: "是否要設定通道額定電流? [y/N]"
方法: initialize_all_channels()
```

**互動式設定流程**:
```
1. 選擇設定模式:
   a) 統一設定（所有通道相同）
   b) 個別設定（逐一輸入）

2. 輸入電流值 (1-20A)

3. 確認設定

4. 順序執行設定（每通道約 2 秒）
```

---

#### **Step 6: 進入命令迴圈**

```python
首次連線: 顯示完整幫助信息
重新連線: 顯示簡短提示

while True:
    cmd = input("\n> ")
    處理命令...
```

**幫助信息管理**:
- `self.help_shown = False` → 顯示完整幫助
- `self.help_shown = True` → 顯示簡短提示
- 用戶輸入 `h` 或 `help` → 隨時查看完整幫助

---

## 3. 核心功能流程

### 3.1 額定電流設定 (init 命令)

**使用方式**: `init <ch> <amps>`  
**範例**: `init 2 4` (設定 CH2 為 4A)

#### 5 步驟 Parameter Object 方法

```
Step 1: 解除全域電流鎖定 (Param1)
├── Class: 0x0F, Instance: 0x01, Attribute: 0x01
├── Service: 0x10 (Set Attribute Single)
└── Data: 0x00 (Disable)

Step 2: 解除全域介面鎖定 (Param2)
├── Class: 0x0F, Instance: 0x02, Attribute: 0x01
├── Service: 0x10
└── Data: 0x00 (Disable)

Step 3: 解除目標通道 programming lock
├── 計算參數編號: 6 + (module-1)*12 + (channel-1)*3 + 1
├── Class: 0x0F, Instance: ParamN, Attribute: 0x01
├── Service: 0x10
└── Data: 0x00 (Unlocked)

Step 4: 設定額定電流
├── 計算參數編號: 6 + (module-1)*12 + (channel-1)*3
├── Class: 0x0F, Instance: ParamN, Attribute: 0x01
├── Service: 0x10
└── Data: current_amps (1-20)

Step 5: 雙重驗證
├── 方法1: 讀取 Parameter Object (Param ParamN)
└── 方法2: 讀取 Input Assembly Byte[offset+1]
```

**參數編號計算範例**:
```
Module 1, CH1: Param6  (nominal), Param7  (lock)
Module 1, CH2: Param9  (nominal), Param10 (lock)
Module 1, CH3: Param12 (nominal), Param13 (lock)
Module 1, CH4: Param15 (nominal), Param16 (lock)
Module 2, CH1: Param18 (nominal), Param19 (lock)
...
```

---

### 3.2 通道控制 (on/off 命令)

**使用方式**: `on <ch>` 或 `off <ch>`  
**範例**: `on 1`, `off 3`

#### 控制流程

```python
1. 檢查初始化狀態
   if not self.channels_initialized:
       return False

2. 計算位元操作
   byte_offset = 1  # Output Assembly Byte 1
   bit_position = channel - 1  # CH1=bit0, CH2=bit1, ...
   
3. 執行位元操作
   if state (開啟):
       new_value = current_value | (1 << bit_position)
   else (關閉):
       new_value = current_value & ~(1 << bit_position)

4. 寫入 Output Assembly (0x64)
   Service: 0x10 (Set Attribute Single)
   Class: 0x04 (Assembly Object)
   Instance: 0x64
   Attribute: 3
   Data: output_data (18 bytes)

5. 等待設備反應
   time.sleep(0.5)

6. 讀取驗證結果
   從 Input Assembly 讀取實際狀態與電流
```

**Byte 1 位元對應**:
```
Bit 7  Bit 6  Bit 5  Bit 4  Bit 3  Bit 2  Bit 1  Bit 0
  -      -      -      -     CH4    CH3    CH2    CH1

範例:
0x01 = 0b00000001 → CH1 開啟
0x03 = 0b00000011 → CH1, CH2 開啟
0x0F = 0b00001111 → 全部開啟
```

---

### 3.3 狀態顯示 (s 命令)

#### 顯示內容

```
1. 全域系統狀態 (從 Input Assembly Byte 0-5)
   ├── 系統電壓: XX.XXV
   ├── 總電流: XX.XA
   ├── 模組數量: X
   └── 狀態警告: 欠壓/過壓/系統錯誤/...

2. 各通道詳細狀態
   ├── CH1 [模組M.通道C]:
   │   ├── 狀態: 🟢 開啟 / 🔴 關閉
   │   ├── 額定電流: XXA
   │   ├── 實際電流: XX.XA
   │   └── 警告: 短路/過載/開路/...
   │
   ├── CH2 ...
   └── ...
```

#### 資料來源

```python
Input Assembly (0x65) 結構:

Byte 0: 全域狀態位元組
Byte 1: 模組數量
Byte 2-3: 總電流 (Little Endian, ×0.1)
Byte 4-5: 系統電壓 (Little Endian, ×0.01)

每個通道 3 bytes (從 Byte 6 開始):
  Offset+0: Status byte
  Offset+1: Nominal current (A)
  Offset+2: Flowing current (×0.1A)

通道偏移計算:
  offset = 6 + (module-1)*12 + (channel-1)*3
```

---

### 3.4 即時監控 (monitor 命令)

#### 命令用法

```bash
monitor start [interval] [mode]
  interval: 更新頻率（秒），預設 2.0，範圍 0.5-60
  mode: silent（靜默）或 display（顯示），預設 silent

monitor stop   # 停止監控
monitor status # 顯示監控狀態
```

#### 監控機制

```python
背景執行緒運作:
  while monitor_running:
      1. 讀取當前狀態 (_read_current_status)
      2. 檢測狀態變化 (_detect_changes)
      3. 根據模式顯示:
         - silent: 僅在有變化時顯示警報
         - display: 持續顯示完整狀態
      4. 等待 interval 秒
```

#### 變化檢測

```python
檢測項目:
1. 通道狀態變化
   - 開 → 關 / 關 → 開

2. 電流異常
   - 變化 > 30%
   - 過載 (電流 > 額定電流)

3. 系統警報
   - 欠壓 / 過壓
   - 系統錯誤
   - 總電流關斷
```

**範例輸出（silent 模式）**:
```
🔔 監控警報 [14:23:15]
  🔄 CH2: 關閉 → 開啟
  ⚡ CH1: 電流異常 (1.2A → 3.5A, +191.7%)
  ⚠️  系統: 80% 總電流警告
```

---

## 4. Assembly 通訊機制

### 4.1 Assembly Instance 概述

| Instance | 名稱 | 大小 | 用途 | 讀寫 |
|----------|------|------|------|------|
| **0x64** | Output Assembly | 18 bytes | 控制輸出 | 讀寫 |
| **0x65** | Input Assembly | 244 bytes | 狀態輸入 | 唯讀 |
| **0x66** | Config Assembly | 244 bytes | 配置資料 | 唯讀* |

\* Config Assembly 理論可寫，但實際運行時為唯讀。配置修改請使用 Parameter Object。

### 4.2 Output Assembly (0x64) - 18 bytes

```
結構:
Byte 0: Global control
Byte 1: Channel control (bit 0-3 對應 CH1-4)
Byte 2-17: Reserved

寫入方法:
Service: 0x10 (Set Attribute Single)
Class: 0x04 (Assembly Object)
Instance: 0x64
Attribute: 3
Data: 18 bytes buffer
```

**Channel Control (Byte 1)**:
```
Bit 0: CH1 (1=開啟, 0=關閉)
Bit 1: CH2
Bit 2: CH3
Bit 3: CH4
Bit 4-7: 保留
```

### 4.3 Input Assembly (0x65) - 244 bytes

```
全域資訊 (6 bytes):
  Byte 0: Global status
  Byte 1: Module count
  Byte 2-3: Total current (Little Endian, ×0.1A)
  Byte 4-5: System voltage (Little Endian, ×0.01V)

通道資訊 (每通道 3 bytes, 從 Byte 6 開始):
  M1.CH1: Byte 6-8
  M1.CH2: Byte 9-11
  M1.CH3: Byte 12-14
  M1.CH4: Byte 15-17
  M2.CH1: Byte 18-20
  ...

每個通道結構:
  Byte 0: Status (bit 0=on/off, bit 1-7=warnings)
  Byte 1: Nominal current (0-20A)
  Byte 2: Flowing current (×0.1A, 0-255 → 0.0-25.5A)
```

**Global Status (Byte 0)**:
```
Bit 0: Undervoltage
Bit 1: Overvoltage  
Bit 2: System error
Bit 3: 80% warning
Bit 4: Total current shutdown
Bit 5-6: Reserved
Bit 7: Config processing
```

**Channel Status Byte**:
```
Bit 0: On/Off (1=開, 0=關)
Bit 1: Short circuit
Bit 2: Overload
Bit 3: Open load
Bit 4: Reserved
Bit 5: Reserved
Bit 6: Reserved
Bit 7: Reserved
```

### 4.4 Parameter Object (Class 0x0F)

用於配置寫入的正確方法：

```
參數編號對照:
Param1: Global nominal current lock
Param2: Global user interface lock
Param3: Global switch-on delay
Param4: Global operating mode
Param5: Reserved

Param6:  M1.CH1 nominal current
Param7:  M1.CH1 programming lock
Param8:  M1.CH1 status
Param9:  M1.CH2 nominal current
...

讀取 Parameter:
  Service: 0x0E (Get Attribute Single)
  Class: 0x0F
  Instance: Param Number
  Attribute: 0x01

寫入 Parameter:
  Service: 0x10 (Set Attribute Single)
  Class: 0x0F
  Instance: Param Number
  Attribute: 0x01
  Data: Value (1-4 bytes)
```

---

## 5. 錯誤處理與重連

### 5.1 連線失敗處理

```
連線失敗 → 顯示錯誤訊息
            ↓
         提供選項:
         ├── [R] 重新連線 → 返回 'reconnect'
         └── [Q] 退出程式 → 返回 None
```

### 5.2 重新連線流程

```python
main() 迴圈:
  while True:
      result = controller.run()
      if result == 'reconnect':
          # 重新執行完整初始化
          continue
      else:
          # 正常退出或錯誤
          break
```

**重連時保留的狀態**:
- ✅ `help_shown` - 避免重複顯示幫助
- ✅ 設備 IP 設定

**重連時重置的狀態**:
- ❌ `channels_initialized` - 重新初始化
- ❌ `monitor_running` - 停止監控
- ❌ 連線狀態 - 重新連線

### 5.3 命令錯誤處理

```python
try:
    # 執行命令
    ...
except ValueError:
    print("⚠️  命令格式錯誤")
    print("   用法: ...")
except Exception as e:
    print(f"❌ 執行錯誤: {e}")
```

---

## 6. 多模組支援機制

### 6.1 模組檢測

```python
從 Input Assembly Byte 1 讀取模組數量
module_count = data[1]  # 範圍: 0-16
total_channels = module_count × 4
```

### 6.2 通道編號系統

```
全域通道編號 (1-64):
  CH1-4:   模組 1
  CH5-8:   模組 2
  CH9-12:  模組 3
  ...

轉換函數:
  get_module_and_channel(global_ch)
  
範例:
  1 → (Module 1, Channel 1)
  5 → (Module 2, Channel 1)
  8 → (Module 2, Channel 4)
```

### 6.3 Offset 計算

```python
def get_channel_offset(module, channel):
    """計算通道在 Input Assembly 中的位置"""
    base = 6  # 全域資訊佔 6 bytes
    module_offset = (module - 1) * 12  # 每模組 12 bytes
    channel_offset = (channel - 1) * 3  # 每通道 3 bytes
    return base + module_offset + channel_offset

範例:
  M1.CH1: 6 + 0*12 + 0*3 = 6
  M1.CH4: 6 + 0*12 + 3*3 = 15
  M2.CH1: 6 + 1*12 + 0*3 = 18
  M2.CH4: 6 + 1*12 + 3*3 = 27
```

### 6.4 顯示格式

```python
單模組模式:
  CH1: 🟢 開啟 (2.3A)
  CH2: 🔴 關閉 (0.0A)

多模組模式:
  M1.CH1 (#1): 🟢 開啟 (2.3A)
  M1.CH2 (#2): 🔴 關閉 (0.0A)
  M2.CH1 (#5): 🟢 開啟 (1.5A)
```

---

## 📊 重要常數與配置

```python
# Assembly Instance
OUTPUT_INSTANCE = 0x64
INPUT_INSTANCE = 0x65
CONFIG_INSTANCE = 0x66

# 資料大小
OUTPUT_SIZE = 18
INPUT_SIZE = 244
CONFIG_SIZE = 244

# 通道配置
CHANNELS_PER_MODULE = 4
MAX_MODULES = 16
MAX_CHANNELS = 64

# 電流範圍
MIN_CURRENT = 1   # A
MAX_CURRENT = 20  # A

# 電壓範圍
MIN_VOLTAGE = 9.0   # V
MAX_VOLTAGE = 30.5  # V

# 監控配置
DEFAULT_MONITOR_INTERVAL = 2.0  # 秒
MIN_MONITOR_INTERVAL = 0.5
MAX_MONITOR_INTERVAL = 60.0
```

---

## 🔍 除錯與診斷

**當遇到問題時**:

1. **連線問題** → 使用 `tests/check_connection.py`
2. **配置問題** → 使用 `tests/diagnostic_tools.py`
3. **狀態異常** → 檢查 `show_status()` 輸出
4. **控制失效** → 驗證額定電流是否已設定

**相關文檔**:
- [診斷工具指南](DIAGNOSTIC_TOOLS_GUIDE.md)
- [CLI 使用指南](CLI_USER_GUIDE.md)
- [故障排除](TROUBLESHOOTING_CONNECTION.md)

---

## 📝 附註

- 本文檔基於 CAPAROC PM EIP 手冊 Chapter 7 編寫
- Output Assembly 實際大小為 18 bytes（非 EDS 標示的 20 bytes）
- Config Assembly 在運行時為唯讀，配置修改請使用 Parameter Object
- 流程圖請參考 [PROGRAM_FLOWCHART.md](PROGRAM_FLOWCHART.md)

---

**文檔結束**
