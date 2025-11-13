# CAPAROC 診斷工具使用指南

> **文檔版本**: v1.0  
> **最後更新**: 2025-11-13  
> **對應工具**: diagnostic_tools.py v1.0

---

## 📚 目錄

1. [工具概述](#1-工具概述)
2. [安裝與執行](#2-安裝與執行)
3. [診斷工具清單](#3-診斷工具清單)
4. [常見診斷情境](#4-常見診斷情境)
5. [診斷流程範例](#5-診斷流程範例)
6. [輸出解讀指南](#6-輸出解讀指南)

---

## 1. 工具概述

### 1.1 用途說明

`diagnostic_tools.py` 是 CAPAROC 控制系統的**深度診斷工具集**，用於：

- 🔍 **問題定位**: 當主程式出現異常時，深入分析通訊問題
- 🧪 **功能測試**: 測試各種 Assembly 寫入方法的可行性
- 📊 **結構分析**: 掃描並對比 Assembly Instance 結構
- 🔬 **配置診斷**: 診斷 Config Assembly 寫入問題
- 📈 **性能測試**: 測試不同通訊方式的效能

### 1.2 與主程式的關係

```
src/caparoc_controller.py (主程式)
  ├── 日常操作: 通道控制、狀態監控
  ├── 適用場景: 正常使用、生產環境
  └── 使用者: 一般操作人員

tests/diagnostic_tools.py (診斷工具)
  ├── 深度診斷: Assembly 分析、通訊測試
  ├── 適用場景: 故障排除、開發除錯
  └── 使用者: 技術人員、開發者
```

**何時使用診斷工具？**

| 情境 | 主程式 | 診斷工具 |
|------|--------|----------|
| 日常開關控制 | ✅ | ❌ |
| 狀態監控 | ✅ | ❌ |
| 標稱電流設定失敗 | 嘗試 | ✅ 深入診斷 |
| 通道控制無反應 | 嘗試 | ✅ 深入診斷 |
| 連線不穩定 | 嘗試 | ✅ Assembly 掃描 |
| 開發新功能 | ❌ | ✅ 結構分析 |

### 1.3 使用時機

**建議使用診斷工具的情況**：

1. ✅ 主程式的 `init` 命令持續失敗
2. ✅ 通道控制後狀態未改變
3. ✅ 狀態讀取異常或資料不合理
4. ✅ 需要了解 Assembly 內部結構
5. ✅ 測試新的通訊方法
6. ✅ 對比不同 Assembly Instance

**不需要使用診斷工具**：

1. ❌ 正常的日常操作
2. ❌ 基本的狀態查詢
3. ❌ 已知問題的常規處理

---

## 2. 安裝與執行

### 2.1 依賴套件

診斷工具與主程式使用相同的依賴：

```bash
# 確認 Conda 環境
conda activate sv

# 確認已安裝 pycomm3
pip list | grep pycomm3
# pycomm3    1.2.14
```

如果未安裝：
```bash
pip install pycomm3
```

### 2.2 執行方式

#### 方式 1: 互動式選單（推薦）

```bash
cd C:\Users\harry\Project\Caparoc5
python tests/diagnostic_tools.py
```

**執行後會顯示選單**：
```
╔══════════════════════════════════════════════════════════╗
║          CAPAROC 診斷工具集 v1.0                         ║
║                                                          ║
║  此工具用於診斷 CAPAROC 設備的通訊和配置問題             ║
╚══════════════════════════════════════════════════════════╝

正在連接到 192.168.2.111...
✅ 連接成功！

============================================================
CAPAROC 診斷工具選單
============================================================

1. 掃描 Assembly Instance
2. 顯示通道配置限制
3. 對比 Assembly 結構
4. 測試 Config 寫入方法
5. 診斷 Config Assembly 寫入

q. 退出
============================================================

請選擇: 
```

#### 方式 2: 指定 IP 位址

```bash
python tests/diagnostic_tools.py 192.168.1.100
```

#### 方式 3: 整合到 Python 程式

```python
from tests.diagnostic_tools import CaparocDiagnostics

# 創建診斷實例
diag = CaparocDiagnostics(device_ip="192.168.2.111")

# 連接設備
if diag.connect():
    # 執行診斷
    diag.scan_assemblies()
    diag.compare_assemblies()
    
    # 斷開連接
    diag.disconnect()
```

### 2.3 IP 配置

**預設 IP**: `192.168.2.111`

**修改方式**：
1. 命令列參數（方式 2）
2. 修改 `diagnostic_tools.py` 中的預設值：
   ```python
   def __init__(self, device_ip="192.168.2.111"):  # 修改這裡
   ```

---

## 3. 診斷工具清單

### 3.1 Tool 1: scan_assemblies()

#### 功能
掃描所有可能的 Assembly Instance (0x60-0x70)，找出設備支援的 Assembly。

#### 使用方式
```
選單選擇: 1
```

#### 輸出範例
```
============================================================
🔍 Assembly Instance 掃描
============================================================

已知 Assembly:
  Output Assembly: 0x64 (0x64)
  Input Assembly:  0x65 (0x65)
  Config Assembly: 0x66 (0x66)

掃描 Assembly Instance 0x60 - 0x70...
  0x64: 長度  18 bytes - ✅ Output
  0x65: 長度 244 bytes - ✅ Input
  0x66: 長度 244 bytes - ⚙️  Config?
  0x67: 長度  20 bytes - 可用
  0x68: 長度   0 bytes - 空白資料
============================================================
```

#### 輸出解讀
- **✅ Output/Input**: 已知的標準 Assembly
- **⚙️  Config?**: 疑似配置資料
- **可用**: 有資料但用途未知
- **空白資料**: 全為 0x00
- **⚠️  疑似配置資料!**: 包含標稱電流值（3, 4A）

#### 使用情境
1. 驗證設備 Assembly 配置
2. 尋找未知的 Assembly Instance
3. 確認 EDS 檔案的正確性

---

### 3.2 Tool 2: show_channel_limits()

#### 功能
讀取並顯示 Config Assembly 中的所有通道配置限制。

#### 使用方式
```
選單選擇: 2
```

#### 輸出範例
```
============================================================
📊 通道配置診斷 (Config Assembly)
============================================================

✅ 成功讀取 Config Assembly (244 bytes)

前 32 bytes (Hex):
  0000040200020202030202020402020205020202

全域參數 (Param 1-5):
  Param1 (Global nominal current lock): 0
  Param2 (Global user interface lock):  0
  Param3 (Global switch-on delay):      1024
  Param4 (Global operating mode):       2
  Param5 (Reserved):                    0

通道參數 (Param 6+):
  CH1: nominal=3A, lock=2, status=2
  CH2: nominal=2A, lock=2, status=2
  CH3: nominal=2A, lock=2, status=2
  CH4: nominal=5A, lock=2, status=2
============================================================
```

#### 輸出解讀

**全域參數**:
- `Param1 = 0`: 全域電流鎖定解除
- `Param2 = 0`: 全域介面鎖定解除
- `Param3 = 1024`: 開關延遲時間（毫秒）
- `Param4 = 2`: 操作模式
- `Param5`: 保留

**通道參數**:
- `nominal`: 標稱電流（1-20A）
- `lock`: 鎖定狀態
  - `0` = Unlocked
  - `1` = Locked via button
  - `2` = Locked via communication
- `status`: 通道狀態碼

#### 使用情境
1. 查看當前配置
2. 驗證標稱電流設定
3. 檢查鎖定狀態

---

### 3.3 Tool 3: compare_assemblies()

#### 功能
對照比較 Input, Output, Config Assembly 的結構和寫入能力。

#### 使用方式
```
選單選擇: 3
```

#### 輸出範例
```
======================================================================
🔬 Assembly 結構對照診斷
======================================================================

📥 [1/5] 讀取 Input Assembly (0x65)...
  ✅ 成功讀取: 244 bytes

📤 [2/5] 讀取 Output Assembly (0x64)...
  ✅ 成功讀取: 18 bytes

⚙️  [3/5] 讀取 Config Assembly (0x66)...
  ✅ 成功讀取: 244 bytes

🧪 [4/5] 測試 Output Assembly (0x64) 寫入...
  ✅ 寫入成功

🧪 [5/5] 測試 Config Assembly (0x66) 寫入...
  ❌ 寫入失敗: Access Denied

======================================================================
📊 分析結果
======================================================================

🔍 Assembly 大小比較:
  Input Assembly (0x65):  244 bytes ✅
  Output Assembly (0x64):  18 bytes ✅
  Config Assembly (0x66): 244 bytes ✅

🔍 寫入功能測試:
  Output Assembly (0x64): ✅ 可寫入
  Config Assembly (0x66): ❌ 無法寫入

💡 診斷結論:
  ❌ Config Assembly (0x66) 無法寫入
  ✅ 建議使用 Parameter Object (Class 0x0F) 方法
======================================================================
```

#### 輸出解讀

**大小比較**:
- Input: 244 bytes - 狀態資料
- Output: 18 bytes - 控制資料（注意：EDS 標示為 20 bytes 是錯誤的）
- Config: 244 bytes - 配置資料

**寫入測試結果**:
- ✅ Output 可寫入 - 正常，用於通道控制
- ❌ Config 無法寫入 - 預期行為，需用 Parameter Object

**診斷結論**:
- 指示正確的配置方法

#### 使用情境
1. 驗證 Assembly 可用性
2. 診斷寫入失敗原因
3. 確認正確的通訊方法

---

### 3.4 Tool 4: test_config_write_methods()

#### 功能
測試 Config Assembly 的各種寫入方法，找出可行的方式。

#### 使用方式
```
選單選擇: 4
```

#### 輸出範例
```
======================================================================
🧪 Config Assembly 寫入方法測試
======================================================================

📖 讀取當前 Config Assembly...
  ✅ 讀取成功: 244 bytes

🧪 [測試 1] Service 0x10, Attribute 3, 完整 244 bytes
  ❌ 失敗: Access Denied

🧪 [測試 2] Service 0x10, Attribute 3, 前 32 bytes
  ❌ 失敗: Access Denied

======================================================================
📊 測試結果摘要
======================================================================
  full_244: ❌ Access Denied
  partial_32: ❌ Access Denied

💡 所有測試都失敗 - Config Assembly 可能在運行時唯讀
   建議使用 Parameter Object (Class 0x0F) 方法
======================================================================
```

#### 輸出解讀

**測試項目**:
1. 完整 244 bytes 寫入
2. 部分（前 32 bytes）寫入

**可能結果**:
- `Success` - 寫入成功
- `Access Denied` - 拒絕存取
- `Invalid Size` - 大小錯誤
- `Timeout` - 逾時

**診斷結論**:
- 全部失敗 → 使用 Parameter Object
- 部分成功 → 可能支援特定大小

#### 使用情境
1. 測試新的寫入策略
2. 驗證 EDS 檔案資訊
3. 尋找替代方法

---

### 3.5 Tool 5: diagnose_config_assembly_write()

#### 功能
診斷 Config Assembly 寫入問題，測試不同的 Param3（延遲）值。

#### 使用方式
```
選單選擇: 5
```

#### 輸出範例
```
======================================================================
🔬 Config Assembly 寫入診斷測試
======================================================================
測試目標: 找出 Param3 的正確「No Change」值
測試值: [0, 10000, 65535]
======================================================================

🧪 測試 Param3 = 0 (0x0000)
----------------------------------------------------------------------
  前 16 bytes: 00000000000202020302020204020202
  ❌ 寫入失敗: Access Denied

🧪 測試 Param3 = 10000 (0x2710)
----------------------------------------------------------------------
  前 16 bytes: 00001027000202020302020204020202
  ❌ 寫入失敗: Access Denied

🧪 測試 Param3 = 65535 (0xFFFF)
----------------------------------------------------------------------
  前 16 bytes: 0000ffff000202020302020204020202
  ❌ 寫入失敗: Access Denied

======================================================================
📊 測試結果摘要
======================================================================
  Param3 =     0 (0x0000): ❌ 失敗
    錯誤: Access Denied
  Param3 = 10000 (0x2710): ❌ 失敗
    錯誤: Access Denied
  Param3 = 65535 (0xFFFF): ❌ 失敗
    錯誤: Access Denied
======================================================================
```

#### 輸出解讀

**測試目的**:
尋找 Config Assembly 中 Param3 的「No Change」值，該值表示不修改此參數。

**測試值說明**:
- `0` - 最小值
- `10000` - 中間值（10 秒延遲）
- `65535` - 最大值（0xFFFF）

**可能結果**:
- 全部失敗 → Config Assembly 完全唯讀
- 某值成功 → 找到正確的「No Change」值

#### 使用情境
1. 深入診斷 Config Assembly 寫入
2. 研究特殊參數值
3. 驗證設備行為

---

## 4. 常見診斷情境

### 情境 1: 標稱電流設定失敗

**症狀**:
```
主程式 init 命令執行後顯示失敗
```

**診斷步驟**:

1. **檢查通道配置**
   ```
   執行: Tool 2 (show_channel_limits)
   確認: 當前 nominal 值和 lock 狀態
   ```

2. **對比 Assembly**
   ```
   執行: Tool 3 (compare_assemblies)
   確認: Config Assembly 是否可寫入
   ```

3. **測試寫入方法**
   ```
   執行: Tool 4 (test_config_write_methods)
   確認: 哪些方法可行
   ```

**可能原因與解決方案**:

| 原因 | 診斷工具發現 | 解決方案 |
|------|--------------|----------|
| 鎖定狀態 | Tool 2 顯示 lock=1 | 硬體解鎖（長按 PWR 3秒） |
| Config 唯讀 | Tool 3 寫入失敗 | 使用 Parameter Object 方法 |
| 參數錯誤 | Tool 2 顯示異常值 | 重新設定參數 |

---

### 情境 2: 通道控制無反應

**症狀**:
```
on/off 命令執行後，通道狀態未改變
```

**診斷步驟**:

1. **掃描 Assembly**
   ```
   執行: Tool 1 (scan_assemblies)
   確認: Output Assembly (0x64) 存在且可讀取
   ```

2. **對比 Assembly**
   ```
   執行: Tool 3 (compare_assemblies)
   確認: Output Assembly 是否可寫入
   ```

3. **檢查配置**
   ```
   執行: Tool 2 (show_channel_limits)
   確認: 標稱電流是否已設定（不可為 0）
   ```

**可能原因與解決方案**:

| 原因 | 診斷工具發現 | 解決方案 |
|------|--------------|----------|
| 未初始化 | Tool 2 顯示 nominal=0 | 執行標稱電流設定 |
| Output 無法寫入 | Tool 3 寫入失敗 | 檢查連線或設備狀態 |
| Assembly 錯誤 | Tool 1 未找到 0x64 | 檢查 EDS 配置 |

---

### 情境 3: 狀態讀取異常

**症狀**:
```
show_status 顯示的資料不合理或全為 0
```

**診斷步驟**:

1. **掃描 Assembly**
   ```
   執行: Tool 1 (scan_assemblies)
   確認: Input Assembly (0x65) 是否存在
   ```

2. **對比 Assembly**
   ```
   執行: Tool 3 (compare_assemblies)
   檢查: Input Assembly 實際大小和內容
   ```

3. **檢查配置**
   ```
   執行: Tool 2 (show_channel_limits)
   比對: Config 與 Input 的資料是否一致
   ```

**可能原因與解決方案**:

| 原因 | 診斷工具發現 | 解決方案 |
|------|--------------|----------|
| Instance 錯誤 | Tool 1 找到其他 Instance | 修正程式中的 Instance 號碼 |
| 資料格式錯誤 | Tool 3 顯示異常大小 | 檢查 EDS 檔案 |
| 設備未回應 | Tool 3 讀取失敗 | 檢查連線 |

---

### 情境 4: 連線不穩定

**症狀**:
```
間歇性連線失敗或讀寫錯誤
```

**診斷步驟**:

1. **掃描 Assembly（重複執行）**
   ```
   執行: Tool 1 多次
   觀察: 每次結果是否一致
   ```

2. **測試讀寫穩定性**
   ```
   執行: Tool 3 多次
   觀察: 讀寫成功率
   ```

**可能原因與解決方案**:

| 現象 | 可能原因 | 解決方案 |
|------|----------|----------|
| 結果不一致 | 網路不穩 | 檢查網路線、交換器 |
| 間歇性失敗 | 設備負載高 | 增加重試機制 |
| 特定操作失敗 | 通訊逾時 | 調整 timeout 參數 |

---

## 5. 診斷流程範例

### 5.1 完整診斷步驟

當遇到問題時，建議按照以下順序執行：

```
Step 1: 基本連線檢查
  ├── 執行 tests/check_connection.py
  └── 確認: 設備可連線

Step 2: Assembly 結構掃描
  ├── 執行 Tool 1 (scan_assemblies)
  ├── 確認: 0x64, 0x65, 0x66 都存在
  └── 記錄: 任何異常的 Instance

Step 3: 配置狀態檢查
  ├── 執行 Tool 2 (show_channel_limits)
  ├── 確認: nominal 電流值合理
  ├── 確認: lock 狀態正確
  └── 記錄: 異常的配置值

Step 4: 讀寫能力測試
  ├── 執行 Tool 3 (compare_assemblies)
  ├── 確認: Output 可寫入
  ├── 確認: Input 可讀取
  └── 確認: Config 寫入結果（預期失敗）

Step 5: 深入診斷（如有需要）
  ├── 執行 Tool 4 (test_config_write_methods)
  └── 執行 Tool 5 (diagnose_config_assembly_write)
```

### 5.2 問題定位方法

#### 使用「二分法」定位

```python
# 假設問題：某個功能在主程式中失敗

# 1. 在診斷工具中測試基本功能
if 診斷工具也失敗:
    # 問題在設備或通訊層
    檢查硬體連線
    檢查 Assembly 結構
else:
    # 問題在主程式邏輯
    檢查程式碼
    檢查參數設定
```

#### 使用「對比法」診斷

```python
# 對比可行與不可行的操作

可行操作:
  - Output Assembly 寫入 ✅
  - Input Assembly 讀取 ✅

不可行操作:
  - Config Assembly 寫入 ❌

結論:
  - 通訊基本正常
  - Config Assembly 需要特殊方法
  - 改用 Parameter Object
```

---

## 6. 輸出解讀指南

### 6.1 Assembly 資料格式

#### Input Assembly (0x65) 資料解析

```python
# 範例 Hex dump:
# 00 01 1234 5678 03020202 04020202 05020202 ...
# ↓  ↓  ↓    ↓    ↓        ↓        ↓

Byte 0 (0x00): Global Status
  - 0x00 = 正常
  - 0x01 = 欠壓
  - 0x02 = 過壓
  - 0x04 = 系統錯誤

Byte 1 (0x01): Module Count
  - 0x01 = 1 個模組
  - 0x02 = 2 個模組

Bytes 2-3 (0x1234): Total Current
  - Little Endian: 0x3412
  - 值: 13330 → 1333.0A (×0.1)

Bytes 4-5 (0x5678): System Voltage
  - Little Endian: 0x7856
  - 值: 30806 → 308.06V (×0.01)

Bytes 6-8 (0x030202): CH1
  - Byte 6 (0x03): Status = 0b00000011
    * Bit 0 (1): On
    * Bit 1 (1): Short circuit
  - Byte 7 (0x02): Nominal = 2A
  - Byte 8 (0x02): Flowing = 0.2A (×0.1)
```

### 6.2 錯誤代碼對照表

| 錯誤訊息 | 原因 | 解決方案 |
|----------|------|----------|
| `Access Denied` | 無權限寫入 | 使用 Parameter Object |
| `Invalid Size` | 資料大小錯誤 | 確認 Assembly 大小 |
| `Timeout` | 通訊逾時 | 檢查網路連線 |
| `Service Not Supported` | 服務不支援 | 使用正確的 Service Code |
| `Instance Not Found` | Instance 不存在 | 確認 Instance 編號 |
| `Attribute Not Supported` | 屬性不支援 | 確認 Attribute 編號 |

### 6.3 狀態位元組解析

#### Global Status Byte (Input Assembly Byte 0)

```
Bit 位置: 7  6  5  4  3  2  1  0
值範例:   0  0  0  0  1  0  1  0  = 0x0A

解析:
  Bit 0 (0): Undervoltage     - 無
  Bit 1 (1): Overvoltage      - 有 ⚠️
  Bit 2 (0): System Error     - 無
  Bit 3 (1): 80% Warning      - 有 ⚠️
  Bit 4 (0): Total Shutdown   - 無
  Bit 5-6  : Reserved
  Bit 7 (0): Config Processing - 無
```

#### Channel Status Byte (Input Assembly 各通道第一個 Byte)

```
Bit 位置: 7  6  5  4  3  2  1  0
值範例:   0  0  0  0  1  0  1  1  = 0x0B

解析:
  Bit 0 (1): On/Off          - 開啟 ✅
  Bit 1 (1): Short Circuit   - 短路 ⚠️
  Bit 2 (0): Overload        - 無
  Bit 3 (1): Open Load       - 開路 ⚠️
  Bit 4-7  : Reserved
```

---

## 📊 診斷工具速查表

| 工具 | 用途 | 執行時間 | 輸出資訊 |
|------|------|----------|----------|
| Tool 1 | Assembly 掃描 | ~2 秒 | Instance 清單與大小 |
| Tool 2 | 配置檢查 | ~1 秒 | 通道配置值 |
| Tool 3 | 結構對比 | ~3 秒 | 讀寫測試結果 |
| Tool 4 | 寫入測試 | ~2 秒 | 各方法測試結果 |
| Tool 5 | 深度診斷 | ~5 秒 | 參數測試結果 |

---

## 🔍 進階使用技巧

### 技巧 1: 批次診斷腳本

創建自動化診斷腳本：

```python
from tests.diagnostic_tools import CaparocDiagnostics

def full_diagnostic(ip="192.168.2.111"):
    """執行完整診斷流程"""
    diag = CaparocDiagnostics(ip)
    
    if not diag.connect():
        print("連線失敗，終止診斷")
        return
    
    print("\n=== 開始完整診斷 ===\n")
    
    # 1. 掃描 Assembly
    print("[1/5] 掃描 Assembly...")
    diag.scan_assemblies()
    
    # 2. 檢查配置
    print("\n[2/5] 檢查配置...")
    diag.show_channel_limits()
    
    # 3. 對比結構
    print("\n[3/5] 對比結構...")
    diag.compare_assemblies()
    
    # 4. 測試寫入
    print("\n[4/5] 測試寫入...")
    diag.test_config_write_methods()
    
    # 5. 深度診斷
    print("\n[5/5] 深度診斷...")
    diag.diagnose_config_assembly_write()
    
    diag.disconnect()
    print("\n=== 診斷完成 ===")

if __name__ == "__main__":
    full_diagnostic()
```

### 技巧 2: 結果導出

將診斷結果保存到檔案：

```python
import sys
from io import StringIO

# 重定向輸出
old_stdout = sys.stdout
sys.stdout = StringIO()

# 執行診斷
diag.scan_assemblies()

# 獲取輸出
output = sys.stdout.getvalue()
sys.stdout = old_stdout

# 保存到檔案
with open('diagnostic_result.txt', 'w', encoding='utf-8') as f:
    f.write(output)
```

---

## 📝 相關文檔

- [主程式流程詳解](MAIN_PROGRAM_FLOW.md) - 了解主程式運作
- [程式流程圖](PROGRAM_FLOWCHART.md) - 視覺化流程圖
- [CLI 使用指南](CLI_USER_GUIDE.md) - 主程式使用說明
- [故障排除](TROUBLESHOOTING_CONNECTION.md) - 常見問題解決

---

## ⚠️ 注意事項

1. **執行前確認**：診斷工具會進行寫入測試，確保設備處於安全狀態
2. **生產環境**：避免在生產環境中執行 Tool 4 和 Tool 5
3. **網路影響**：診斷過程中會頻繁通訊，可能影響網路效能
4. **設備狀態**：某些診斷可能暫時改變設備狀態

---

**文檔結束**
