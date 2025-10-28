# CAPAROC Controller 程式執行流程

> 📅 最後更新: 2025-10-28  
> 📌 版本: V3.5 (支援多模組架構)

## 🎯 多模組支援說明

**系統支援 1-16 個模組，每個模組 4 通道**

- 程式啟動時自動檢測模組數量 (Byte 1)
- 動態調整通道數量 (module_count × 4)
- 通道編號格式:
  - 單模組: CH1, CH2, CH3, CH4
  - 多模組: M1.CH1 (#1), M1.CH4 (#4), M2.CH1 (#5), M2.CH4 (#8)

## 🌳 程式執行流程樹狀圖

```
main()
 │
 └─► CaparocController()
      │
      └─► run()
           │
           ├─► 🚀 顯示啟動訊息
           │    ├─ Phase 1 完成狀態
           │    ├─ Phase 2 完成狀態
           │    ├─ Phase 3 進行中狀態
           │    └─ 待實作功能列表
           │
           ├─► 建立 CIPDriver 連接
           │    └─ with CIPDriver(192.168.2.111) as driver
           │
           ├─► 【Step 0】全域系統狀態檢查 (Phase 3-1 新增) 🆕
           │    │
           │    └─► check_global_system_status()
           │         │
           │         ├─► 讀取 Input Assembly 0x65
           │         │    └─ service=0x0E, instance=0x65, attribute=3
           │         │
           │         ├─► 解析 Byte 0: 全域狀態位元組
           │         │    ├─ bit 0: 欠壓 (Undervoltage)
           │         │    ├─ bit 1: 過壓 (Overvoltage)
           │         │    ├─ bit 2: 系統錯誤 (System Error)
           │         │    ├─ bit 3: 80% 警告 (Warning 80%)
           │         │    ├─ bit 4: 總電流關斷 (Total Shutdown)
           │         │    └─ bit 7: 配置處理中 (Config Processing)
           │         │
           │         ├─► 解析 Byte 2-3: 總電流 (uint16 / 10.0)
           │         │
           │         ├─► 解析 Byte 4-5: 系統電壓 (uint16 / 100.0)
           │         │
           │         ├─► 分析錯誤狀態
           │         │    ├─ 欠壓: 電壓 < 9.0V
           │         │    ├─ 過壓: 電壓 > 30.5V
           │         │    └─ 系統錯誤: 硬體故障或通訊異常
           │         │
           │         ├─► 分析警告狀態
           │         │    ├─ 電壓偏低: 電壓 < 18.0V
           │         │    ├─ 電壓偏高: 電壓 > 26.0V
           │         │    ├─ 80% 警告: 總電流接近閾值
           │         │    ├─ 總電流關斷: 系統已停止供電
           │         │    └─ 配置處理中: 設備正在變更配置
           │         │
           │         ├─► 顯示檢查結果
           │         │    ├─ 📊 系統狀態 (電壓/電流/狀態位元組)
           │         │    ├─ ❌ 錯誤列表 (如果有)
           │         │    ├─ ⚠️  警告列表 (如果有)
           │         │    └─ ✅ 正常 (無錯誤無警告)
           │         │
           │         ├─► [分支] 如果 safe == False (有嚴重錯誤)
           │         │    │
           │         │    └─► 詢問使用者是否繼續?
           │         │         ├─ y/yes ──► ⚠️  繼續執行 (風險自負)
           │         │         └─ N/Enter ──► ✅ 安全退出
           │         │
           │         └─► 返回: {
           │              'safe': bool,
           │              'warnings': list,
           │              'errors': list,
           │              'voltage': float,
           │              'total_current': float,
           │              'global_status_byte': int
           │              }
           │
           ├─► 【Step 1】互動式設定通道額定電流
           │    │
           │    └─► prompt_channel_currents()
           │         │
           │         ├─► [外層循環] 是否需要初始化?
           │         │    │
           │         │    ├─ 輸入 y/yes ──► [內層循環] 設定電流值
           │         │    │                  │
           │         │    │                  ├─► 輸入 CH1-CH4 額定電流 (0.5-25.5A)
           │         │    │                  │    └─ Enter = 預設 4A
           │         │    │                  │
           │         │    │                  ├─► 顯示設定摘要
           │         │    │                  │
           │         │    │                  └─► 確認設定 [Y/n/b]
           │         │    │                       ├─ Y/Enter ──► 返回 channel_currents
           │         │    │                       ├─ n ──► 重新輸入電流值
           │         │    │                       └─ b ──► 返回外層循環
           │         │    │
           │         │    └─ 輸入 N/Enter ──► 返回 None (跳過初始化)
           │         │
           │         └─► 返回: dict{1:4, 2:4, 3:4, 4:4} 或 None
           │
           ├─► 【Step 2】初始化通道或同步設備狀態
           │    │
           │    ├─► [分支 A] channel_currents != None
           │    │    │
           │    │    └─► initialize_all_channels(driver, channel_currents)
           │    │         │
           │    │         ├─► 顯示設定摘要 (需時 ~40 秒)
           │    │         │
           │    │         ├─► for ch in [1, 2, 3, 4]:
           │    │         │    │
           │    │         │    └─► _set_nominal_current_led_button(driver, 1, ch, current)
           │    │         │         │
           │    │         │         ├─► 嘗試 5 個 Assembly instances [0x67, 0x68, 0x69, 0x6A, 0x64]
           │    │         │         │    │
           │    │         │         │    ├─► 進入程式模式 (bit7=1, bit6=1)
           │    │         │         │    │    └─ 等待 2.5 秒
           │    │         │         │    │
           │    │         │         │    ├─► 按鈕操作 (循環 current_amps 次)
           │    │         │         │    │    ├─ 按下: bit[ch] | bit7
           │    │         │         │    │    ├─ 等待 0.5 秒
           │    │         │         │    │    ├─ 釋放: bit7
           │    │         │         │    │    └─ 等待 0.3 秒
           │    │         │         │    │
           │    │         │         │    ├─► 儲存設定 (bit[ch] | bit7 | bit6)
           │    │         │         │    │    └─ 等待 3.0 秒
           │    │         │         │    │
           │    │         │         │    └─► 退出程式模式 (全 0)
           │    │         │         │
           │    │         │         └─► 返回 True/False
           │    │         │
           │    │         ├─► 通道間隔 1 秒
           │    │         │
           │    │         └─► channels_initialized = True
           │    │
           │    └─► [分支 B] channel_currents == None (跳過初始化)
           │         │
           │         └─► 從設備讀取實際狀態並同步
           │              │
           │              ├─► 讀取 Input Assembly 0x65
           │              │    └─ service=0x0E, instance=0x65
           │              │
           │              ├─► 解析各通道實際狀態
           │              │    │
           │              │    └─► for ch in [1, 2, 3, 4]:
           │              │         ├─ 讀取 status_byte (Byte 6/9/12/15)
           │              │         ├─ is_on = status_byte & 0x01
           │              │         ├─ 讀取 current (Byte 8/11/14/17)
           │              │         └─ 顯示: CH1: 🟢 開 (2.5A)
           │              │
           │              ├─► 重建 Output Assembly buffer
           │              │    ├─ current_output_data = bytearray(18)
           │              │    ├─ byte1_value = 0x80
           │              │    └─ for is_on: byte1_value |= (1 << (ch-1))
           │              │
           │              └─► channels_initialized = True
           │
           ├─► 【Step 3】嘗試建立 Implicit Messaging (靜默執行)
           │    │
           │    └─► _establish_implicit_messaging(driver)
           │         │
           │         ├─► _build_forward_open_request()
           │         │    └─ 建立 Forward Open 請求封包
           │         │
           │         ├─► generic_message(service=0x52, Forward Open)
           │         │
           │         ├─► [成功] 
           │         │    ├─ implicit_mode_enabled = True
           │         │    └─► 啟動 I/O Worker 背景線程
           │         │         └─► _io_worker(driver)
           │         │              └─► while cip_keep_alive:
           │         │                   ├─ 寫入 Output Assembly (20Hz)
           │         │                   ├─ 讀取 Input Assembly
           │         │                   └─ sleep(0.05)
           │         │
           │         └─► [失敗] 使用 Explicit Messaging 模式
           │
           └─► 【Step 4】互動控制循環
                │
                └─► while True:
                     │
                     ├─► 顯示指令列表
                     │    ├─ on <ch>   - 開啟通道
                     │    ├─ off <ch>  - 關閉通道
                     │    ├─ s         - 顯示狀態
                     │    └─ q         - 退出
                     │
                     ├─► 等待用戶輸入
                     │
                     ├─► [指令: on <ch>]
                     │    │
                     │    └─► set_channel(ch, True)
                     │         │
                     │         ├─► 位元運算計算新值
                     │         │    ├─ current_value = current_output_data[1]
                     │         │    ├─ new_value = current_value | (1<<(ch-1)) | 0x80
                     │         │    └─ current_output_data[1] = new_value
                     │         │
                     │         ├─► [Implicit 模式]
                     │         │    └─ I/O Worker 自動寫入 (等待 0.2 秒)
                     │         │
                     │         ├─► [Explicit 模式]
                     │         │    ├─► generic_message(service=0x10, 寫入)
                     │         │    └─► 驗證: 讀取回來確認
                     │         │
                     │         └─► _read_and_show_result(ch, True)
                     │              └─► 讀取 Assembly 0x101 顯示電流
                     │
                     ├─► [指令: off <ch>]
                     │    │
                     │    └─► set_channel(ch, False)
                     │         └─ new_value = (current_value & ~(1<<(ch-1))) | 0x80
                     │
                     ├─► [指令: s]
                     │    │
                     │    └─► show_status()
                     │         │
                     │         ├─► 讀取 Input Assembly 0x65
                     │         │
                     │         ├─► 【1. 全域系統狀態】(Byte 0)
                     │         │    ├─ bit 0: 欠壓
                     │         │    ├─ bit 1: 過壓
                     │         │    ├─ bit 2: 系統錯誤
                     │         │    ├─ bit 3: 80% 警告
                     │         │    ├─ bit 4: 總電流關斷
                     │         │    └─ bit 7: Config 處理中
                     │         │
                     │         ├─► 【2. 系統參數】
                     │         │    ├─ Byte 4-5: 電壓 / 100.0
                     │         │    └─ Byte 2-3: 總電流 / 10.0
                     │         │
                     │         ├─► 【3. 各通道狀態】
                     │         │    │
                     │         │    └─► for ch in [1, 2, 3, 4]:
                     │         │         ├─ offset = [6, 9, 12, 15][ch-1]
                     │         │         ├─ status_byte = data[offset]
                     │         │         ├─ is_on = status_byte & 0x01
                     │         │         ├─ warning_80 = status_byte & 0x02
                     │         │         ├─ overload = status_byte & 0x04
                     │         │         ├─ short_circuit = status_byte & 0x08
                     │         │         ├─ current = data[offset+2] / 10.0
                     │         │         ├─ channels_sum += current
                     │         │         └─ 顯示: CH1: 🟢 開 2.5A (狀態標註)
                     │         │
                     │         └─► 【4. 驗證總和】
                     │              ├─ 顯示通道總和
                     │              └─ 比對全域總電流 (誤差 < 0.1A = 通過)
                     │
                     ├─► [指令: q]
                     │    └─► break (退出循環)
                     │
                     └─► [Ctrl+C / 異常]
                          └─► break / 顯示錯誤訊息

[程式結束]
```

---

## 📊 關鍵決策點

| 步驟 | 決策點 | 選項 A | 選項 B |
|------|--------|--------|--------|
| **Step 0** | 系統狀態安全? | 安全 → 繼續執行 | 不安全 → 詢問使用者 (y=繼續, N=退出) |
| **Step 1** | 是否初始化? | Y → 設定電流值 | N → 跳過初始化 |
| **Step 2** | channel_currents | != None → 初始化通道 | == None → 同步設備狀態 |
| **Step 3** | Implicit Messaging | 成功 → 背景 I/O | 失敗 → Explicit 模式 |
| **Step 4** | 控制模式 | Implicit → Worker 寫入 | Explicit → 直接寫入 |

---

## 🔑 重要特性

1. ✅ **狀態同步**: 跳過初始化時從 Input Assembly 讀取實際狀態
2. ✅ **位元操作**: 控制單一通道不影響其他通道
3. ✅ **雙模式支援**: Implicit (背景) / Explicit (直接) 寫入
4. ✅ **完整驗證**: 電流總和與全域總電流比對
5. ✅ **錯誤處理**: 每個步驟都有異常處理

---

## 📋 Assembly 結構參考

### Input Assembly 0x65 (狀態讀取)

| Byte | 內容 | 格式 | 說明 | 手冊章節 |
|------|------|------|------|----------|
| 0 | Global Status | bit mask | 全域系統狀態 (欠壓/過壓/錯誤等) | 7.2.1 |
| 1 | Module Counter | uint8 | 安裝的斷路器模組數量 (0-16) | 7.2.2 |
| 2-3 | Total Current | uint16 / 10.0 | 全域總電流 (0-50.0A) | 7.2.3 |
| 4-5 | Total Voltage | uint16 / 100.0 | 系統電壓 (9.0-30.5V) | 7.2.4 |
| 6-8 | CH1 Data Block | 3 bytes | 見下方「通道數據塊結構」 | 7.2.5 |
| 9-11 | CH2 Data Block | 3 bytes | 同上 | 7.2.5 |
| 12-14 | CH3 Data Block | 3 bytes | 同上 | 7.2.5 |
| 15-17 | CH4 Data Block | 3 bytes | 同上 | 7.2.5 |

**全域狀態位元 Byte 0 (7.2.1)**:
- bit 0: 欠壓 (Undervoltage)
- bit 1: 過壓 (Overvoltage)
- bit 2: 系統錯誤 (System error)
- bit 3: 80% 標稱電流警告
- bit 4: 總電流關斷 (Total current shutdown)
- bit 7: Config assembly 處理狀態

**通道數據塊結構 (7.2.5) - 每通道 3 bytes**:

| Byte | 內容 | 格式 | 說明 |
|------|------|------|------|
| 0 | Status | bit mask | 通道狀態位元 (見下方) |
| 1 | Nominal Current | uint8 | 標稱電流 (1-10A) |
| 2 | Flowing Current | uint8 / 10.0 | 實際電流 (0-255 = 0-25.5A) |

**通道狀態位元 Byte 0 (7.2.5)**:
- bit 0: Channel status (通道開/關)
- bit 1: 80% warning (80% 警告)
- bit 2: Overload tripping (過載跳脫)
- bit 3: Short-circuit tripping (短路跳脫)
- bit 4: Hardware fault (硬體故障)
- bit 5: Total current shutdown (總電流關斷)

### Output Assembly 0x64 (控制命令)

| Byte | 內容 | 說明 |
|------|------|------|
| 0 | Module control | 模組控制位元 |
| 1 | Channel control | 通道控制位元 (bit0-3=CH1-4, bit7=release) |
| 2-17 | Reserved | 保留 (固定 18 bytes) |

---

## 🔄 版本歷史

- **V3.5** (2025-10-28): 多模組架構支援 (1-16 個模組，最多 64 通道)
- **V3.4.1** (2025-10-28): 補充 7.2.5 完整實作 (bit 4-5 + Nominal current 顯示)
- **V3.4** (2025-10-28): Phase 3-1 完成 - 全域系統狀態檢查 (啟動時 Step 0)
- **V3.3** (2025-10-27): Phase 2 完成 - 狀態顯示增強 + 設備復電狀態同步修復
- **V3.2** (2025-10-27): Phase 1 完成 - 互動式額定電流設定
- **V3.1** (2025-10-27): 多通道控制 + 正確狀態讀取
- **V3.0** (2025-10-27): 重構版本基於手冊規範

---

## 📝 維護說明

**此文件需與程式碼同步更新:**
- 新增功能時更新流程圖
- 修改邏輯時更新決策點
- 變更結構時更新 Assembly 參考表

**相關文件:**
- `TODO.md` - 待實作功能列表
- `CHANGELOG.md` - 詳細版本記錄
- `CLI_USER_GUIDE.md` - 使用者操作手冊
