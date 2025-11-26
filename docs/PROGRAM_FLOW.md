# CAPAROC Controller 完整程式流程

> **文檔版本**: v4.0  
> **最後更新**: 2025年11月25日  
> **對應程式版本**: caparoc_controller.py v3.7 beta

---

## 📚 目錄

1. [程式架構總覽](#1-程式架構總覽)
2. [完整啟動流程](#2-完整啟動流程)
3. [核心功能詳解](#3-核心功能詳解)
4. [Assembly 通訊機制](#4-assembly-通訊機制)
5. [背景執行緒管理](#5-背景執行緒管理)
6. [錯誤處理與重連](#6-錯誤處理與重連)

---

## 1. 程式架構總覽

### 1.1 核心類別

```python
class CaparocController:
    """CAPAROC 斷路器控制器"""
    
    # 設備配置
    device_ip: str                    # 設備 IP (預設 192.168.2.111)
    module_count: int                 # 模組數量 (動態檢測, 1-16)
    channels_per_module: int = 4      # 每模組通道數
    
    # Assembly Instances
    output_instance: 0x64             # Output Assembly (18 bytes)
    input_instance: 0x65              # Input Assembly (244 bytes)
    config_instance: 0x66             # Config Assembly (唯讀)
    
    # 狀態管理
    channels_initialized: bool        # 通道初始化標記
    help_shown: bool                  # 幫助訊息顯示標記
    
    # 監控系統 (Phase 3-2)
    monitor_running: bool             # 監控執行狀態
    monitor_interval: float = 2.0     # 更新頻率 (秒)
    monitor_mode: str = 'silent'      # 'silent' 或 'display'
    
    # 心跳系統
    heartbeat_running: bool           # 心跳執行狀態
    heartbeat_interval: float = 300.0 # 心跳間隔 (秒)
```

### 1.2 功能模組

| 模組 | 功能 | 狀態 |
|------|------|------|
| **額定電流設定** | Config Assembly Read-Modify-Write | ✅ 完成 |
| **通道控制** | Output Assembly 開關控制 | ✅ 完成 |
| **狀態監控** | Input Assembly 狀態讀取 | ✅ 完成 |
| **即時監控** | 背景執行緒週期更新 | ✅ 完成 |
| **心跳保活** | 防止連線超時 | ✅ 完成 |
| **多模組支援** | 動態檢測 1-16 模組 | ✅ 完成 |
| **IP 配置** | 啟動時可變更 IP | ✅ 完成 |

---

## 2. 完整啟動流程

### 2.1 主程式入口

```
main()
  │
  ├─► CaparocController(device_ip="192.168.2.111")
  │
  └─► while True:  # 重連機制
       │
       ├─► result = controller.run()
       │
       ├─► if result == 'reconnect':
       │    └─► continue  # 重新執行完整初始化
       │
       └─► else:
            └─► break  # 退出或錯誤
```

### 2.2 run() 方法完整流程圖

```
run()
 │
 ├─► 【顯示啟動訊息】
 │    ├─ 版本資訊 (v3.7 beta)
 │    ├─ 已完成功能列表
 │    └─ 待實作功能列表
 │
 ├─► 【Step 0: 裝置連線檢查】
 │    │
 │    └─► check_device_connection(driver)
 │         │
 │         ├─► 讀取 Input Assembly (0x65)
 │         │    └─ Service: 0x0E, Instance: 0x65
 │         │
 │         ├─► 驗證資料長度 >= 6 bytes
 │         │
 │         ├─► 解析設備資訊
 │         │    ├─ Byte 1: 模組數量
 │         │    ├─ Byte 4-5: 系統電壓
 │         │    └─ device_type: 'CAPAROC PM EIP'
 │         │
 │         ├─► [成功]
 │         │    └─ 顯示: ✅ 連線成功
 │         │             IP: xxx.xxx.xxx.xxx
 │         │             模組: X 個 (Y 通道)
 │         │             電壓: XX.XV
 │         │
 │         └─► [失敗]
 │              └─ 顯示錯誤訊息
 │                 提供選項: [R]重新連線 / [Q]退出
 │                 └─ R → return 'reconnect'
 │                    Q → return None
 │
 ├─► 【Step 1: IP 配置設定】
 │    │
 │    ├─► 顯示當前 IP
 │    │
 │    ├─► 詢問: "是否要變更設備 IP? [Y/N]"
 │    │
 │    ├─► [Y] _configure_device_ip()
 │    │    │
 │    │    ├─► 輸入新 IP
 │    │    ├─► 驗證 IP 格式 (_validate_ip)
 │    │    ├─► 確認變更 [Y/N]
 │    │    │
 │    │    └─► [確認] 
 │    │         └─ self.device_ip = new_ip
 │    │            return 'reconnect'  # 使用新 IP 重連
 │    │
 │    └─► [N] 繼續使用當前 IP
 │
 ├─► 【Step 2: 全域系統狀態檢查】
 │    │
 │    └─► check_global_system_status()
 │         │
 │         ├─► 讀取 Input Assembly (0x65)
 │         │
 │         ├─► 解析 Byte 0: 全域狀態位元組
 │         │    ├─ bit 0: Undervoltage (欠壓)
 │         │    ├─ bit 1: Overvoltage (過壓)
 │         │    ├─ bit 2: System Error (系統錯誤)
 │         │    ├─ bit 3: 80% Warning
 │         │    ├─ bit 4: Total Shutdown (總電流關斷)
 │         │    └─ bit 7: Config Processing
 │         │
 │         ├─► 解析 Byte 1: 模組數量 (0-16)
 │         │    └─ self.module_count = module_count
 │         │
 │         ├─► 解析 Byte 2-3: 總電流 (÷10.0)
 │         │
 │         ├─► 解析 Byte 4-5: 系統電壓 (÷100.0)
 │         │
 │         ├─► 驗證電壓範圍
 │         │    ├─ < 9.0V  → 錯誤: 電壓過低
 │         │    ├─ > 30.5V → 錯誤: 電壓過高
 │         │    ├─ < 18.0V → 警告: 電壓偏低
 │         │    └─ > 26.0V → 警告: 電壓偏高
 │         │
 │         ├─► 檢查錯誤狀態
 │         │    ├─ Undervoltage → errors[]
 │         │    ├─ Overvoltage  → errors[]
 │         │    └─ System Error → errors[]
 │         │
 │         ├─► 檢查警告狀態
 │         │    ├─ 80% Warning → warnings[]
 │         │    ├─ Total Shutdown → warnings[]
 │         │    └─ Config Processing → warnings[]
 │         │
 │         ├─► 顯示檢查結果
 │         │    ├─ 📊 系統狀態
 │         │    │   ├─ 電壓: XX.XXV
 │         │    │   ├─ 總電流: XX.XXA
 │         │    │   └─ 模組數量: X 個
 │         │    │
 │         │    ├─ ❌ 錯誤列表 (如果有)
 │         │    ├─ ⚠️  警告列表 (如果有)
 │         │    └─ ✅ 系統狀態正常
 │         │
 │         └─► [分支] 如果 safe == False
 │              │
 │              └─► 詢問: "是否仍要繼續? [y/N]"
 │                   ├─ y → 繼續執行 (風險自負)
 │                   └─ N → return None (安全退出)
 │
 ├─► 【Step 3: 讀取並同步設備狀態】
 │    │
 │    ├─► 讀取 Input Assembly (0x65)
 │    │
 │    ├─► 解析各通道實際狀態
 │    │    │
 │    │    └─► for module in (1 to module_count):
 │    │         └─► for ch in (1 to 4):
 │    │              ├─ offset = get_channel_offset(module, ch)
 │    │              ├─ status_byte = data[offset]
 │    │              ├─ is_on = status_byte & 0x01
 │    │              ├─ current = data[offset+2] / 10.0
 │    │              └─ 顯示: MX.CHY: 🟢 開 (Z.ZA)
 │    │
 │    ├─► 重建 Output Assembly buffer
 │    │    ├─ current_output_data = bytearray(18)
 │    │    ├─ byte1_value = 0x80
 │    │    │
 │    │    └─► for 每個開啟的通道:
 │    │         └─ byte1_value |= (1 << (ch-1))
 │    │
 │    ├─► 同步完成
 │    │    └─ channels_initialized = True
 │    │
 │    └─► 顯示: ✅ 已同步控制狀態
 │              現在可以安全地控制通道
 │
 ├─► 【Step 4: 啟動 CIP 連線與心跳】
 │    │
 │    ├─► _activate_connection_state(driver)
 │    │    └─ 建立 CIP Forward Open 連線
 │    │
 │    └─► _start_heartbeat(driver)
 │         └─ 啟動心跳背景執行緒 (300秒週期)
 │
 ├─► 【Step 5: 顯示幫助訊息】
 │    │
 │    ├─► [首次連線] help_shown == False
 │    │    └─ _show_help_message()  # 完整幫助
 │    │       help_shown = True
 │    │
 │    └─► [重新連線] help_shown == True
 │         └─ 簡短提示: "輸入 'h' 查看幫助"
 │
 └─► 【Step 6: 進入命令迴圈】
      │
      └─► while True:
           │
           ├─► 等待用戶輸入: input("\n> ")
           │
           ├─► 【命令: q / quit】
           │    │
           │    ├─ print("🛑 正在退出程式...")
           │    ├─ if monitor_running: stop_monitor()
           │    ├─ _stop_heartbeat()
           │    ├─ print("✅ 退出程式")
           │    └─ break
           │
           ├─► 【命令: h / help】
           │    └─ _show_help_message()
           │
           ├─► 【命令: reconnect】
           │    │
           │    ├─ if monitor_running: stop_monitor()
           │    ├─ _stop_heartbeat()
           │    └─ return 'reconnect'
           │
           ├─► 【命令: s / status】
           │    └─ show_status()
           │
           ├─► 【命令: init <ch> <amps>】
           │    └─ 詳見 3.1 額定電流設定
           │
           ├─► 【命令: verify <ch>】
           │    └─ _verify_nominal_current(driver, module, channel)
           │
           ├─► 【命令: on <ch>】
           │    └─ set_channel(ch, True)
           │
           ├─► 【命令: off <ch>】
           │    └─ set_channel(ch, False)
           │
           ├─► 【命令: monitor start/stop/status】
           │    └─ 詳見 3.4 即時監控
           │
           ├─► 【異常處理】
           │    ├─ KeyboardInterrupt → 停止監控、心跳
           │    └─ Exception → 顯示錯誤訊息
           │
           └─► 繼續等待下一個命令
```

---

## 3. 核心功能詳解

### 3.1 額定電流設定 (init 命令)

**命令格式**: `init <ch> <amps>`  
**範例**: `init 2 6` (設定 CH2 為 6A)

#### 完整流程

```
init <ch> <amps>
 │
 ├─► 【參數驗證】
 │    ├─ 檢查參數數量 (必須 3 個)
 │    ├─ 驗證通道範圍 (1 ~ total_channels)
 │    ├─ 驗證電流範圍 (1-20A)
 │    └─ 計算模組/通道編號
 │
 ├─► set_nominal_current(module, channel, current_amps, verify=True)
 │    │
 │    └─► 【使用 Config Assembly Read-Modify-Write】
 │         │
 │         ├─► 修改前讀取當前值
 │         │    └─ current_value = _read_nominal_current_silent()
 │         │       └─ 顯示: ⚠️  變更警告: CHX 目前為 YA，修改設定為 ZA
 │         │
 │         ├─► STEP 1: 讀取 Config Assembly (0x66)
 │         │    │
 │         │    └─► Service: 0x0E (Get Attribute Single)
 │         │         Class: 0x04 (Assembly Object)
 │         │         Instance: 0x66
 │         │         Attribute: 3
 │         │         └─ 讀取 244 bytes
 │         │
 │         ├─► STEP 2: 修改設定
 │         │    │
 │         │    ├─► 計算 Config Offset
 │         │    │    ├─ header = 6 bytes
 │         │    │    ├─ module_offset = (module-1) × 12
 │         │    │    ├─ channel_offset = (channel-1) × 3
 │         │    │    └─ offset_current = header + module_offset + channel_offset
 │         │    │       offset_status = offset_current + 2
 │         │    │
 │         │    ├─► 修改 Nominal Current
 │         │    │    └─ config_data[offset_current] = current_amps
 │         │    │
 │         │    ├─► 設定 Status = 2 (No Change)
 │         │    │    └─ config_data[offset_status] = 2
 │         │    │
 │         │    └─► 🔒 保護所有通道 (Status = 2)
 │         │         │
 │         │         └─► for 所有模組和通道:
 │         │              └─ 設定 Status Byte = 2 (No Change)
 │         │
 │         ├─► STEP 3: 寫回 Config Assembly
 │         │    │
 │         │    └─► Service: 0x10 (Set Attribute Single)
 │         │         Class: 0x04
 │         │         Instance: 0x66
 │         │         Attribute: 3
 │         │         Data: 244 bytes (修改後的完整資料)
 │         │
 │         └─► STEP 4: 漸進式重試驗證
 │              │
 │              └─► for attempt in (1 to 6):  # 最多 6 次
 │                   │
 │                   ├─► time.sleep(0.5)  # 等待 500ms
 │                   │
 │                   ├─► actual = _read_nominal_current_silent()
 │                   │
 │                   ├─► if actual == current_amps:
 │                   │    │
 │                   │    ├─ elapsed = attempt × 0.5
 │                   │    ├─ 顯示: ✅ 變更已執行: CHX 目前為 YA (耗時: Z.Zs)
 │                   │    └─ return True  # 成功，立即返回
 │                   │
 │                   └─► 繼續下一次嘗試...
 │
 └─► [失敗] 顯示錯誤訊息
```

**關鍵機制**:
- ✅ **Read-Modify-Write**: 保護 Reserved 欄位不被破壞
- ✅ **Status Byte = 2**: 使用 "No Change" 保護所有通道
- ✅ **漸進式重試**: 最快 0.5s，最慢 3s，平衡速度與可靠性

---

### 3.2 通道控制 (on/off 命令)

**命令格式**: `on <ch>` 或 `off <ch>`  
**範例**: `on 1`, `off 3`

#### 完整流程

```
on/off <ch>
 │
 ├─► set_channel(channel, state)
 │    │
 │    ├─► 檢查初始化狀態
 │    │    └─ if not channels_initialized: return False
 │    │
 │    ├─► 【位元操作計算】
 │    │    │
 │    │    └─► with io_data_lock:
 │    │         │
 │    │         ├─ byte_offset = 1
 │    │         ├─ bit_position = channel - 1
 │    │         ├─ current_value = current_output_data[1]
 │    │         │
 │    │         └─► if state (開啟):
 │    │              ├─ new_value = current_value | (1 << bit_position) | 0x80
 │    │              └─ current_output_data[1] = new_value
 │    │             else (關閉):
 │    │              ├─ new_value = (current_value & ~(1 << bit_position)) | 0x80
 │    │              └─ current_output_data[1] = new_value
 │    │
 │    ├─► 【寫入 Output Assembly】
 │    │    │
 │    │    └─► driver.generic_message(
 │    │         service=0x10,
 │    │         class_code=0x04,
 │    │         instance=0x64,
 │    │         attribute=3,
 │    │         request_data=current_output_data,
 │    │         connected=True
 │    │         )
 │    │
 │    ├─► time.sleep(0.5)  # 等待設備反應
 │    │
 │    └─► _read_and_show_result(channel, state)
 │         │
 │         └─► 讀取 Input Assembly (0x65)
 │              ├─ 顯示通道狀態
 │              ├─ 顯示實際電流
 │              └─ 顯示警告 (如果有)
 │
 └─► 完成
```

**Output Assembly Byte 1 位元對應**:
```
Bit 7  Bit 6  Bit 5  Bit 4  Bit 3  Bit 2  Bit 1  Bit 0
 0x80   -      -      -     CH4    CH3    CH2    CH1

範例:
0x81 = 0b10000001 → CH1 開啟
0x83 = 0b10000011 → CH1, CH2 開啟
0x8F = 0b10001111 → 全部開啟
0x80 = 0b10000000 → 全部關閉
```

---

### 3.3 狀態顯示 (s 命令)

```
show_status()
 │
 ├─► 讀取 Input Assembly (0x65)
 │    └─ Service: 0x0E, Instance: 0x65, Attribute: 3
 │
 ├─► 【1. 全域系統狀態】(Byte 0)
 │    │
 │    └─► 解析狀態位元
 │         ├─ bit 0: Undervoltage
 │         ├─ bit 1: Overvoltage
 │         ├─ bit 2: System Error
 │         ├─ bit 3: 80% Warning
 │         ├─ bit 4: Total Shutdown
 │         └─ bit 7: Config Processing
 │
 ├─► 【2. 系統參數】
 │    ├─ Byte 1: 模組數量
 │    ├─ Byte 2-3: 總電流 (÷10.0)
 │    └─ Byte 4-5: 電壓 (÷100.0)
 │
 ├─► 【3. 各通道狀態】
 │    │
 │    └─► for module in (1 to module_count):
 │         │
 │         ├─► 顯示模組標題 (如果多模組)
 │         │
 │         └─► for ch in (1 to 4):
 │              │
 │              ├─► 計算偏移
 │              │    └─ offset = 6 + (module-1)×12 + (ch-1)×3
 │              │
 │              ├─► 解析通道資料
 │              │    ├─ Byte 0: Status byte
 │              │    ├─ Byte 1: Nominal current (1-20A)
 │              │    └─ Byte 2: Flowing current (÷10.0)
 │              │
 │              ├─► 解析狀態位元
 │              │    ├─ bit 0: On/Off
 │              │    ├─ bit 1: 80% warning
 │              │    ├─ bit 2: Overload
 │              │    ├─ bit 3: Short circuit
 │              │    ├─ bit 4: Hardware fault
 │              │    └─ bit 5: Total shutdown
 │              │
 │              └─► 顯示通道狀態
 │                   ├─ 單模組: CH1: 🟢 開 2.3A / 4A
 │                   └─ 多模組: M1.CH1 (#1): 🟢 開 2.3A / 4A
 │
 └─► 完成
```

**顯示格式**:
```
🌐 全域系統狀態:
   ✅ 正常

📊 系統參數:
   電壓: 24.00 V
   全域總電流: 5.2 A
   模組數量: 2 個

📊 通道狀態:

   📦 模組 1:
   ────────────────────────────────────────
   M1.CH1 (#1): 🟢 開  2.3A / 4A  ✅
   M1.CH2 (#2): 🔴 關  0.0A / 4A  ✅
   M1.CH3 (#3): 🟢 開  1.5A / 4A  ✅
   M1.CH4 (#4): 🔴 關  0.0A / 4A  ✅

   📦 模組 2:
   ────────────────────────────────────────
   M2.CH1 (#5): 🟢 開  1.4A / 4A  ✅
   M2.CH2 (#6): 🔴 關  0.0A / 4A  ✅
   M2.CH3 (#7): 🔴 關  0.0A / 4A  ✅
   M2.CH4 (#8): 🔴 關  0.0A / 4A  ✅
```

---

### 3.4 即時監控 (monitor 命令)

**命令格式**:
- `monitor start [interval] [mode]` - 啟動監控
- `monitor stop` - 停止監控
- `monitor status` - 顯示監控狀態

**參數說明**:
- `interval`: 更新頻率（秒），預設 2.0，範圍 0.5-60
- `mode`: `silent`（靜默，僅警報）或 `display`（持續顯示），預設 `silent`

#### 完整流程

```
monitor start [interval] [mode]
 │
 ├─► start_monitor(interval, mode)
 │    │
 │    ├─► 檢查是否已運行
 │    │    └─ if monitor_running: return False
 │    │
 │    ├─► 驗證參數
 │    │    ├─ interval: 0.5 ~ 60.0 秒
 │    │    └─ mode: 'silent' 或 'display'
 │    │
 │    ├─► 初始化快照
 │    │    └─ last_status_snapshot = {}
 │    │
 │    ├─► 啟動背景執行緒
 │    │    │
 │    │    └─► monitor_thread = Thread(target=_monitor_worker)
 │    │         monitor_running = True
 │    │         monitor_thread.start()
 │    │
 │    └─► 顯示: ✅ 即時監控已啟動
 │              更新頻率: Xs
 │              模式: silent/display
 │
 └─► 背景執行緒: _monitor_worker()
      │
      └─► while monitor_running:
           │
           ├─► 【讀取當前狀態】
           │    │
           │    └─► _read_current_status()
           │         │
           │         ├─► 讀取 Input Assembly (0x65)
           │         │
           │         ├─► 解析全域狀態
           │         │    ├─ 模組數量
           │         │    ├─ 總電流
           │         │    └─ 系統電壓
           │         │
           │         └─► 解析各通道狀態
           │              ├─ is_on
           │              ├─ flowing_current
           │              ├─ nominal_current
           │              └─ 警告/錯誤狀態
           │
           ├─► 【檢測變化】
           │    │
           │    └─► _detect_changes(current_status)
           │         │
           │         ├─► 通道狀態變化
           │         │    └─ 開啟 ↔ 關閉
           │         │
           │         ├─► 電流異常變化
           │         │    └─ 變化 > 30%
           │         │
           │         ├─► 新出現的警告
           │         │    ├─ 80% warning
           │         │    ├─ Overload
           │         │    └─ Short circuit
           │         │
           │         └─► 系統電壓變化
           │              └─ 變化 > 1.0V
           │
           ├─► 【根據模式顯示】
           │    │
           │    ├─► [mode == 'display']
           │    │    └─ _show_monitor_status(status, changes)
           │    │       └─ 顯示完整狀態表格 + 變化
           │    │
           │    └─► [mode == 'silent']
           │         └─ if 有變化:
           │            └─ _show_monitor_alerts(changes)
           │               └─ 只顯示變化警報
           │
           ├─► 【更新快照】
           │    └─ last_status_snapshot = current_status
           │
           └─► time.sleep(monitor_interval)
```

**顯示範例**:

**Display 模式**:
```
======================================================================
🔄 即時監控 [14:23:15] - 更新頻率: 2s
======================================================================
📊 系統: 24.0V | 5.2A | 2 模組

通道           狀態     電流         警告/錯誤
----------------------------------------------------------------------
M1.CH1 (#1)    🟢 開   2.3A / 4A    ✅
M1.CH2 (#2)    🔴 關   0.0A / 4A    ✅
M1.CH3 (#3)    🟢 開   1.5A / 4A    ✅
M1.CH4 (#4)    🔴 關   0.0A / 4A    ✅

🔔 檢測到變化:
  ▸ M1.CH2: 關閉 → 開啟
  ▸ M1.CH3: 電流異常 (1.2A → 3.5A, +191.7%)
======================================================================
```

**Silent 模式**:
```
======================================================================
🔔 監控警報 [14:23:15]
======================================================================
  ▸ M1.CH2: 關閉 → 開啟
  ▸ M1.CH3: 電流異常 (1.2A → 3.5A, +191.7%)
  ▸ M1.CH1: ⚠️ 80% 警告
======================================================================
```

---

## 4. Assembly 通訊機制

### 4.1 Assembly Instances 總覽

| Instance | 名稱 | 大小 | 方向 | 用途 | 讀寫權限 |
|----------|------|------|------|------|----------|
| **0x64** | Output Assembly | 18 bytes | PC → 設備 | 控制輸出 | 讀寫 |
| **0x65** | Input Assembly | 244 bytes | 設備 → PC | 狀態輸入 | 唯讀 |
| **0x66** | Config Assembly | 244 bytes | PC ↔ 設備 | 配置資料 | 讀寫* |

\* Config Assembly 理論可寫，實際使用 Read-Modify-Write 模式

### 4.2 Output Assembly (0x64) - 18 bytes

**結構**:
```
Byte 0:    Global control
Byte 1:    Channel control (bit 0-3 = CH1-4, bit 7 = release)
Byte 2-17: Reserved (固定 0)
```

**通道控制位元 (Byte 1)**:
```
Bit 7: Release (必須為 1)
Bit 6: Reserved
Bit 5: Reserved
Bit 4: Reserved
Bit 3: CH4 (1=開, 0=關)
Bit 2: CH3
Bit 1: CH2
Bit 0: CH1
```

**CIP 訊息格式**:
```python
driver.generic_message(
    service=0x10,           # Set Attribute Single
    class_code=0x04,        # Assembly Object
    instance=0x64,          # Output Assembly
    attribute=3,            # Data
    request_data=bytes(18), # 18 bytes
    connected=True          # 使用已建立的連線
)
```

---

### 4.3 Input Assembly (0x65) - 244 bytes

**全域資訊 (6 bytes)**:
```
Byte 0:   Global status (位元遮罩)
Byte 1:   Module count (0-16)
Byte 2-3: Total current (Little Endian, ×0.1A)
Byte 4-5: System voltage (Little Endian, ×0.01V)
```

**Global Status Byte 0**:
```
Bit 0: Undervoltage
Bit 1: Overvoltage
Bit 2: System error
Bit 3: 80% warning
Bit 4: Total current shutdown
Bit 5: Reserved
Bit 6: Reserved
Bit 7: Config processing
```

**通道資訊 (每通道 3 bytes, 從 Byte 6 開始)**:
```
模組 1:
  CH1: Byte 6-8
  CH2: Byte 9-11
  CH3: Byte 12-14
  CH4: Byte 15-17

模組 2:
  CH1: Byte 18-20
  CH2: Byte 21-23
  CH3: Byte 24-26
  CH4: Byte 27-29

...

每個通道 3 bytes:
  Byte 0: Channel status (位元遮罩)
  Byte 1: Nominal current (1-20A)
  Byte 2: Flowing current (×0.1A, 0-255 → 0.0-25.5A)
```

**Channel Status Byte**:
```
Bit 0: On/Off (1=開, 0=關)
Bit 1: 80% warning
Bit 2: Overload
Bit 3: Short circuit
Bit 4: Hardware fault
Bit 5: Total shutdown
Bit 6: Reserved
Bit 7: Reserved
```

**Offset 計算公式**:
```python
def get_channel_offset(module, channel):
    """計算通道在 Input Assembly 中的位置"""
    header = 6  # 全域資訊
    module_offset = (module - 1) * 12  # 每模組 12 bytes
    channel_offset = (channel - 1) * 3  # 每通道 3 bytes
    return header + module_offset + channel_offset

範例:
  M1.CH1: 6 + 0×12 + 0×3 = 6
  M1.CH4: 6 + 0×12 + 3×3 = 15
  M2.CH1: 6 + 1×12 + 0×3 = 18
  M2.CH4: 6 + 1×12 + 3×3 = 27
```

---

### 4.4 Config Assembly (0x66) - 244 bytes

**結構**:
```
Header (6 bytes):
  Byte 0-1: Param1-2 (Global locks)
  Byte 2-3: Param3 (Global switch-on delay, INT)
  Byte 4-5: Param4-5 (Operating mode, Reserved)

通道參數 (每通道 3 bytes, 最多 64 通道):
  Module 1, CH1: Byte 6-8
    Byte 0: Nominal current (1-20A)
    Byte 1: Programming lock (0=unlocked, 2=locked)
    Byte 2: Status (0=Off, 1=On, 2=No Change)
  
  Module 1, CH2: Byte 9-11
  Module 1, CH3: Byte 12-14
  Module 1, CH4: Byte 15-17
  Module 2, CH1: Byte 18-20
  ...
```

**Config Offset 計算**:
```python
def get_config_channel_offset(module, channel):
    """計算通道在 Config Assembly 中的位置"""
    header = 6
    module_offset = (module - 1) * 12
    channel_offset = (channel - 1) * 3
    return header + module_offset + channel_offset
```

**Read-Modify-Write 流程**:
```
1. 讀取完整 244 bytes
2. 修改目標參數
3. 設定所有 Status = 2 (No Change)
4. 寫回完整 244 bytes
```

---

## 5. 背景執行緒管理

### 5.1 心跳執行緒

**目的**: 防止 CIP 連線超時（閒置 300 秒自動斷開）

```
_heartbeat_worker(driver)
 │
 └─► while heartbeat_running:
      │
      ├─► 計算閒置時間
      │    └─ idle = time.time() - last_activity_time
      │
      ├─► if idle >= heartbeat_interval (300s):
      │    │
      │    └─► 發送心跳訊息
      │         └─ driver.generic_message(
      │              service=0x0E,  # Get Attribute
      │              instance=0x65,
      │              connected=False
      │            )
      │         └─ 顯示: 💓 心跳訊息 (閒置: Xs)
      │
      └─► time.sleep(10)  # 每 10 秒檢查一次
```

**啟動**: `_start_heartbeat(driver)`  
**停止**: `_stop_heartbeat()`

---

### 5.2 監控執行緒

**目的**: 週期性讀取設備狀態，檢測變化

```
_monitor_worker()
 │
 └─► while monitor_running:
      │
      ├─► 讀取狀態: _read_current_status()
      │
      ├─► 檢測變化: _detect_changes(current_status)
      │
      ├─► 根據模式顯示:
      │    ├─ display: 完整狀態
      │    └─ silent: 僅警報
      │
      ├─► 更新快照: last_status_snapshot = current_status
      │
      └─► time.sleep(monitor_interval)
```

**啟動**: `start_monitor(interval, mode)`  
**停止**: `stop_monitor()`  
**狀態**: `show_monitor_info()`

---

### 5.3 執行緒安全

**鎖機制**:
```python
# I/O 資料鎖
with self.io_data_lock:
    # 安全訪問 current_output_data
    # 安全訪問 current_input_data

# 監控資料鎖
with self.monitor_lock:
    # 安全訪問 last_status_snapshot
```

**停止流程**:
```
1. 設定標誌: monitor_running = False
2. 等待執行緒: thread.join(timeout=1)
3. 確認停止
```

---

## 6. 錯誤處理與重連

### 6.1 連線失敗處理

```
連線失敗
 │
 ├─► 顯示錯誤訊息
 │    ├─ IP 位址
 │    ├─ 錯誤原因
 │    └─ 檢查清單
 │
 └─► 提供選項
      ├─ [R] 重新連線 → return 'reconnect'
      └─ [Q] 退出程式 → return None
```

**檢查清單**:
1. 設備是否已開機
2. 網路線是否正確連接
3. IP 位址是否正確
4. 電腦與設備是否在同一網段
5. 防火牆是否阻擋連線

---

### 6.2 重新連線機制

```
main() 循環
 │
 └─► while True:
      │
      ├─► result = controller.run()
      │
      ├─► if result == 'reconnect':
      │    │
      │    ├─ 停止所有背景執行緒
      │    │   ├─ stop_monitor()
      │    │   └─ _stop_heartbeat()
      │    │
      │    ├─ 重置狀態
      │    │   └─ channels_initialized = False
      │    │
      │    └─ continue  # 重新執行 run()
      │
      └─► else:
           └─ break  # 退出或錯誤
```

**保留狀態**:
- ✅ `help_shown` - 避免重複顯示幫助
- ✅ `device_ip` - IP 設定

**重置狀態**:
- ❌ `channels_initialized` - 重新初始化
- ❌ `monitor_running` - 停止監控
- ❌ `heartbeat_running` - 停止心跳

---

### 6.3 命令錯誤處理

```python
try:
    # 執行命令
    if cmd.startswith('init '):
        # 額定電流設定
        ...
    elif cmd.startswith('on '):
        # 開啟通道
        ...
    # ...

except ValueError:
    print("⚠️  參數格式錯誤")
    print("   用法: ...")
    
except IndexError:
    print("⚠️  參數數量不足")
    
except Exception as e:
    print(f"❌ 執行錯誤: {e}")
```

---

## 📊 重要常數與配置

```python
# Assembly Instances
OUTPUT_INSTANCE = 0x64
INPUT_INSTANCE = 0x65
CONFIG_INSTANCE = 0x66

# 資料大小
OUTPUT_SIZE = 18    # ⚠️ 實際為 18 bytes（非 EDS 標示的 20）
INPUT_SIZE = 244
CONFIG_SIZE = 244

# 通道配置
CHANNELS_PER_MODULE = 4
MAX_MODULES = 16
MAX_CHANNELS = 64  # 16 × 4

# 電流範圍
MIN_CURRENT = 1    # A
MAX_CURRENT = 20   # A

# 電壓範圍
MIN_VOLTAGE = 9.0   # V
MAX_VOLTAGE = 30.5  # V
NOMINAL_VOLTAGE = 24.0  # V

# 監控配置
DEFAULT_MONITOR_INTERVAL = 2.0   # 秒
MIN_MONITOR_INTERVAL = 0.5
MAX_MONITOR_INTERVAL = 60.0

# 心跳配置
HEARTBEAT_INTERVAL = 300.0  # 秒（5 分鐘）
HEARTBEAT_CHECK_INTERVAL = 10.0  # 秒
```

---

## 🔍 除錯建議

**當遇到問題時**:

1. **連線問題** 
   - 執行 `reconnect` 命令
   - 檢查網路與 IP 設定
   
2. **控制失效**
   - 確認通道已初始化
   - 使用 `s` 查看狀態
   - 檢查額定電流設定
   
3. **狀態異常**
   - 使用 `s` 顯示完整狀態
   - 檢查 Global Status Byte
   - 查看系統電壓是否正常
   
4. **監控問題**
   - 使用 `monitor status` 查看狀態
   - 確認更新頻率設定
   - 檢查是否有錯誤訊息

---

## 📚 相關文檔

- [CLI 使用者指南](CLI_USER_GUIDE.md) - 命令使用說明
- [額定電流設定流程](INIT_COMMAND_FLOW.md) - init 命令詳解
- [診斷工具指南](DIAGNOSTIC_TOOLS_GUIDE.md) - 問題診斷
- [開發筆記](DEVELOPMENT_NOTES.md) - 技術細節

---

## 📝 版本歷史

- **v4.0** (2025-11-25): 完整流程重寫，整合所有功能
- **v3.7** (2025-11-13): 額定電流設定優化（漸進式重試）
- **v3.6** (2025-11-12): 監控功能完成
- **v3.5** (2025-10-28): 多模組支援
- **v3.0** (2025-10-27): 基於手冊規範重構

---

**文檔結束**
