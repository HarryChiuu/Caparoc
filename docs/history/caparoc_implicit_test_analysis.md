# CAPAROC Implicit Messaging 測試程式分析

## 📋 程式概述

`caparoc_implicit_test.py` 是一個完整的 CAPAROC 四通道斷路器測試程式，使用 **Implicit Messaging** 技術進行實時 I/O 控制。

---

## 🔧 使用的套件分析

### 核心套件

1. **pycomm3** - EtherNet/IP 和 CIP (Common Industrial Protocol) 通訊
   - `CIPDriver`: 用於建立與工業設備的 EtherNet/IP 連接
   - 支援讀寫 Assembly Objects
   - 支援 Generic Messaging

2. **struct** (Python 內建)
   - 用於二進制資料的打包/解包
   - 處理電壓、電流等數值的轉換

3. **time** (Python 內建)
   - 控制時序和延遲
   - 用於 I/O 週期控制

4. **threading** (Python 內建)
   - 建立背景 I/O 更新執行緒
   - 實現持續的資料交換

---

## 🏗️ 核心架構

### 主要類別：`CaparocImplicitTester`

```
CaparocImplicitTester
├── 連接管理
│   ├── device_ip (預設: 192.168.2.111)
│   ├── input_instance (0x65 - 輸入 Assembly)
│   └── output_instance (0x64 - 輸出 Assembly)
│
├── Implicit Messaging 狀態
│   ├── implicit_mode_enabled
│   ├── cip_connection_established
│   └── io_update_thread (背景執行緒)
│
├── I/O 緩存
│   ├── current_output_data (20 bytes - 輸出緩存)
│   └── current_input_data (20 bytes - 輸入緩存)
│
└── 執行緒同步
    └── io_lock (threading.Lock)
```

---

## 🔄 核心工作流程

### 1. 建立 Implicit Messaging 連接

**方法**: `establish_implicit_messaging(caparoc, verbose=False)`

**流程**:
```
1. 建立 Forward Open 請求
   ├── Connection Serial Number
   ├── Vendor ID (0x009A)
   ├── Connection Timeout (2000ms)
   └── RPI (Requested Packet Interval): 20ms

2. 發送 CIP Forward Open
   ├── Service: 0x52 (Forward Open)
   ├── Class: 0x06 (Connection Manager)
   └── Instance: 0x01

3. 啟動背景 I/O 執行緒
   └── _implicit_io_worker()
      ├── 每 50ms (20Hz) 執行一次
      ├── 寫入 Output Assembly
      ├── 讀取 Input Assembly
      └── 更新 I/O 緩存
```

**關鍵特性**:
- 使用 **連接模式** (connected=True)
- 建立持續的 I/O 資料交換通道
- 背景執行緒確保實時更新

---

### 2. 背景 I/O 工作執行緒

**方法**: `_implicit_io_worker(caparoc)`

**週期性操作** (每 50ms):
```python
while self.io_thread_running:
    # 1. 讀取當前輸出資料
    with self.io_lock:
        output_data = bytes(self.current_output_data)
    
    # 2. 寫入到設備 Output Assembly
    caparoc.write(f"Assembly.{self.output_instance}", output_data)
    
    # 3. 讀取設備 Input Assembly
    input_response = caparoc.read(f"Assembly.{self.input_instance}")
    
    # 4. 更新輸入緩存
    with self.io_lock:
        self.current_input_data = bytearray(input_response.value)
    
    # 5. 等待下一週期 (50ms)
    time.sleep(0.05)
```

**執行緒安全**:
- 使用 `io_lock` 保護共享資料
- 避免讀寫衝突

---

### 3. 通道控制機制

**方法**: `set_channel(caparoc, module, channel, state, verbose=False)`

**控制流程**:
```
1. 檢查 Implicit 模式是否啟用

2. 設定額定電流 (如果開啟)
   └── set_nominal_current_4ch() - 設定為 4A

3. 計算位元位置
   ├── byte_offset = 1 (控制字節)
   └── bit_position = channel - 1 (通道位元)

4. 修改輸出緩存
   ├── 開啟: 設定對應位元為 1 + bit7=1
   └── 關閉: 清除對應位元 + 保持 bit7=1

5. 等待 I/O 執行緒更新
   └── 背景執行緒自動將變更寫入設備

6. 驗證結果
   ├── 讀取通道電流
   └── 確認開啟/關閉狀態
```

**位元控制結構**:
```
輸出緩存 byte[1]:
┌──┬──┬──┬──┬──┬──┬──┬──┐
│7 │6 │5 │4 │3 │2 │1 │0 │
└──┴──┴──┴──┴──┴──┴──┴──┘
 │           │  │  │  └─ 通道 1
 │           │  │  └──── 通道 2
 │           │  └─────── 通道 3
 │           └────────── 通道 4
 └────────────────────── 程式模式位元
```

---

### 4. 額定電流設定

**方法**: `set_nominal_current_4ch(caparoc, module, channel, nominal_current, verbose=False)`

**模擬 LED 按鈕操作** (根據手冊 6.1.1):

```
步驟 1: 進入程式模式
├── 模擬長按 LED 按鈕
├── 設定 bit7=1, bit6=1
└── 等待 2.5 秒

步驟 2: 設定額定電流值
├── 模擬按鈕 N 次 (N = 額定電流值)
├── 每次按壓:
│   ├── 設定通道位元 + bit7=1
│   ├── 等待 0.5 秒
│   ├── 釋放按鈕 (只保留 bit7=1)
│   └── 等待 0.3 秒
└── 重複 N 次

步驟 3: 儲存設定
├── 模擬長按 LED 按鈕
├── 設定通道位元 + bit7=1 + bit6=1
├── 等待 3 秒
└── 退出程式模式
```

**回退方案**:
- 嘗試多個 Assembly Instances (0x67, 0x68, 0x69, 0x6A, 0x64)
- 如果失敗，使用通用配置方法

---

### 5. 資料讀取方法

#### 5.1 讀取系統電壓
```python
read_voltage(caparoc)
├── 讀取 Assembly.101[4]
├── 解包 unsigned short (2 bytes)
└── 除以 100 得到實際電壓值
```

#### 5.2 讀取總電壓和總電流
```python
read_breaker_voltage_current(caparoc)
├── 總電壓: Assembly.101[4] / 100
└── 總電流: Assembly.101[6] / 100
```

#### 5.3 讀取通道電流
```python
read_channel_current(caparoc, module, channel)
├── 計算偏移: 20 + (module-1)*16 + (channel-1)*2
├── 讀取 Assembly.101[offset]
└── 除以 100 得到電流值 (A)
```

**資料結構** (Assembly 101):
```
Offset  | 內容
--------|------------------
0-3     | 保留
4-5     | 系統電壓 (×100)
6-7     | 總電流 (×100)
8-19    | 保留
20-21   | 模組1 通道1 電流
22-23   | 模組1 通道2 電流
24-25   | 模組1 通道3 電流
26-27   | 模組1 通道4 電流
...
```

---

## 🧪 測試流程

**主測試函數**: `run_four_channel_test()`

```
測試階段:

階段 1: 建立連接
├── 連接設備 (192.168.2.111)
└── 建立 Implicit Messaging

階段 2: 讀取初始狀態
├── 系統電壓
├── 總電壓/總電流
└── 所有通道電流

階段 3: 四通道控制測試
├── 對每個通道 (1-4):
│   ├── 開啟通道
│   ├── 等待 2 秒
│   ├── 讀取開啟後電流
│   ├── 關閉通道
│   ├── 等待 1 秒
│   └── 讀取關閉後電流
└── 記錄測試結果

階段 4: 安全措施
└── 確保所有通道關閉

階段 5: 最終狀態報告
└── 顯示所有通道狀態

清理階段:
└── cleanup_implicit_messaging()
    ├── 停止 I/O 執行緒
    └── 重置狀態變數
```

---

## 🔑 關鍵技術點

### 1. Implicit Messaging vs Explicit Messaging

| 特性 | Implicit | Explicit |
|------|----------|----------|
| 連接類型 | 持續連接 | 請求/響應 |
| 資料交換 | 自動週期性 | 手動觸發 |
| 實時性 | 高 (20ms) | 低 (依請求) |
| 資源占用 | 較高 | 較低 |
| 適用場景 | 實時控制 | 配置讀寫 |

### 2. 執行緒同步機制

```python
# 使用 Lock 保護共享資料
with self.io_lock:
    # 安全訪問 current_output_data
    # 安全訪問 current_input_data
```

### 3. CIP Assembly Objects

- **Output Assembly (0x64)**: 主機 → 設備 (控制命令)
- **Input Assembly (0x65)**: 設備 → 主機 (狀態回饋)
- **Config Assembly (0x67-0x6A)**: 配置資料

### 4. 錯誤處理策略

```python
# 多重回退方案
嘗試方案 1 (Implicit 內建)
├── 失敗 ↓
嘗試方案 2 (連接模式 generic_message)
├── 失敗 ↓
嘗試方案 3 (多個 Assembly Instances)
├── 失敗 ↓
使用通用配置方法
```

---

## 📊 資料流圖

```
┌─────────────────────────────────────────────────────┐
│                    主程式                            │
│  ┌──────────────────────────────────────────┐      │
│  │  establish_implicit_messaging()          │      │
│  │  ├── 建立 Forward Open                   │      │
│  │  └── 啟動 I/O 執行緒                     │      │
│  └──────────────────────────────────────────┘      │
│                      ↓                              │
│  ┌──────────────────────────────────────────┐      │
│  │  背景 I/O 執行緒 (50ms 週期)            │      │
│  │  ┌────────────────────────────────┐     │      │
│  │  │  寫入 Output Assembly (0x64)   │ ────┼──→ 設備
│  │  └────────────────────────────────┘     │      │
│  │  ┌────────────────────────────────┐     │      │
│  │  │  讀取 Input Assembly (0x65)    │ ←───┼──── 設備
│  │  └────────────────────────────────┘     │      │
│  └──────────────────────────────────────────┘      │
│                      ↑                              │
│  ┌──────────────────────────────────────────┐      │
│  │  set_channel()                           │      │
│  │  └── 修改 current_output_data            │      │
│  └──────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────┘
```

---

## 💡 優勢與特點

### ✅ 優勢

1. **實時控制**: 20Hz 更新頻率，50ms 響應時間
2. **執行緒安全**: 使用 Lock 保護共享資料
3. **自動重試**: 多重回退方案確保連接成功
4. **詳細日誌**: verbose 模式提供完整除錯資訊
5. **安全機制**: 測試結束自動關閉所有通道

### 📈 可改進之處

1. **錯誤恢復**: I/O 執行緒錯誤時自動重連
2. **狀態監控**: 增加連接健康度檢查
3. **配置檔**: 將 IP、Instance 等參數移至配置檔
4. **日誌系統**: 使用 logging 模組替代 print
5. **單元測試**: 增加模擬測試和邊界條件測試

---

## 🎯 建議的重構方向

### 1. 模組化分離

```
breaker_control/
├── connection/
│   ├── implicit_messaging.py  # Implicit 連接管理
│   └── cip_protocol.py        # CIP 協議封裝
├── control/
│   ├── channel_controller.py  # 通道控制
│   └── current_setter.py      # 額定電流設定
├── monitoring/
│   ├── voltage_reader.py      # 電壓讀取
│   └── current_reader.py      # 電流讀取
└── utils/
    ├── data_converter.py      # 資料轉換
    └── thread_manager.py      # 執行緒管理
```

### 2. 配置管理

```python
# config.yaml
device:
  ip: "192.168.2.111"
  input_instance: 0x65
  output_instance: 0x64

io:
  update_rate_hz: 20
  timeout_ms: 2000
  
channels:
  default_current: 4  # Amps
```

### 3. 日誌系統

```python
import logging

logger = logging.getLogger('caparoc')
logger.info("Implicit messaging established")
logger.debug(f"I/O update cycle: {cycle_count}")
logger.error(f"Connection failed: {error}")
```

---

## 📚 參考資料

- **CIP 規範**: ODVA Common Industrial Protocol
- **EtherNet/IP**: Industrial Ethernet Protocol
- **pycomm3 文件**: https://docs.pycomm3.dev/
- **CAPAROC 手冊**: Section 6.1.1 - LED 按鈕程式設定

---

**文件版本**: 1.0  
**分析日期**: 2025年10月21日  
**分析者**: Agent AI
