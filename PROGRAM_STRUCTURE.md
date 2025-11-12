# CAPAROC Controller 程式結構概覽

## 檔案資訊
- 主程式：`src/caparoc_controller.py` (3630 行)
- 版本：v3.7 beta
- 協議：EtherNet/IP (CIP) - pycomm3

## 核心架構

### 1. CaparocController 類別

#### 初始化 (`__init__`)
- 設備 IP：預設 192.168.2.111
- Assembly 定義：
  * Output (0x64): 18 bytes
  * Input (0x65): 208 bytes  
  * Config (0x66): 244 bytes
- 多模組支援：1-16 個模組，每模組 4 通道

#### 核心功能模組

**A. 標稱電流設定 (3 種方法)**
1. `_set_nominal_current_config_assembly()` - Config Assembly 方法 (失敗)
   - 244-byte 一次寫入
   - 問題：Too much data / 無回應
   - 狀態：❌ 已廢棄

2. `_set_nominal_current_parameter_object()` - Parameter Object 方法
   - Class 0x0F，個別參數寫入
   - 步驟：解鎖 Param1/2 → 設定目標參數
   - 狀態：✅ 已實作，未啟用

3. `_set_nominal_current_led_button_method()` - LED 按鈕模擬
   - 狀態：⚠️ 僅用於初始化

**B. Implicit Messaging (I/O Connection)** - ⚠️ 開發中，暫停
1. `_establish_implicit_messaging()` - 建立 Forward Open
   - 嘗試 1: 手動建構 Large Forward Open (失敗 - 封包結構錯誤)
   - 嘗試 2: pycomm3 內建 API (不存在)
   - 狀態：❌ 失敗，需要其他方案

2. `_build_forward_open_request()` - Forward Open 封包建構
   - 狀態：❌ 結構錯誤，設備丟棄封包

3. `_build_default_config_assembly()` - 預設 Config 資料
   - 狀態：✅ 正常

4. `_io_worker()` / `_io_worker_pycomm3()` - I/O 週期更新
   - 狀態：⚠️ 未測試

**C. 通道控制 (Explicit Messaging)** - ✅ 正常運作
1. `set_channel()` - 開關控制
   - 使用 Output Assembly (0x64)
   - Byte[0]: 控制字
   - Byte[1]: 通道開關位元 (Bit 7 = Release)

2. `read_channel_status()` - 狀態讀取
   - 從 Input Assembly (0x65) 讀取
   - 解析電壓、電流、狀態

**D. 全域狀態管理** - ✅ 正常運作
1. `check_global_system_status()` - 系統狀態檢查
   - Byte 0: 欠壓/過壓/系統錯誤/80%警告/總電流關斷
   - Byte 1: 模組數量
   - Byte 2-3: 總電流
   - Byte 4-5: 系統電壓

2. `show_status()` - 顯示所有通道狀態

**E. 即時監控** - ✅ 正常運作
1. `start_monitor()` / `stop_monitor()` - 監控控制
2. `_monitor_worker()` - 背景執行緒
   - 週期：可設定 (預設 2 秒)
   - 模式：silent (僅警報) / display (持續顯示)

**F. 診斷工具** - ✅ 已實作
1. `compare_assemblies()` - 對照 Input/Output/Config
2. `test_config_write_methods()` - 測試寫入方法
3. `diagnose_config_assembly_write()` - 診斷 Config 寫入
4. `scan_assemblies()` - 掃描 Assembly Instance
5. `show_channel_limits()` - 顯示通道配置

### 2. 輔助方法

**多模組支援**
- `get_channel_offset()` - 計算通道在 Input Assembly 的位置
- `get_total_channels()` - 總通道數
- `get_module_and_channel()` - 全域通道 ↔ 模組/通道轉換
- `_get_config_param_number()` - 計算 Config 參數編號

**連線管理**
- `check_device_connection()` - 檢查連線
- `_configure_device_ip()` - IP 配置
- `_validate_ip()` - IP 驗證

### 3. 主程式流程 (`run()`)

```
1. 啟動資訊顯示
2. 裝置連線檢查
   └─ 讀取 Input Assembly 驗證連線
3. IP 配置 (可選)
4. 全域系統狀態檢查
   └─ 電壓、欠壓/過壓、系統錯誤檢測
5. 讀取實際狀態並同步
   └─ 避免控制時影響其他通道
6. ⚠️ 嘗試建立 Implicit Messaging (目前失敗)
7. 進入命令循環
```

## 當前問題分析

### ❌ 失敗的功能
1. **Config Assembly 寫入**
   - 原因：PC/設備無法處理 244-byte Explicit 寫入
   - 錯誤：Too much data / 無回應

2. **Forward Open (Implicit Messaging)**
   - 手動建構：封包結構錯誤，設備丟棄
   - pycomm3 API：不支援 Configuration Data
   - 結論：pycomm3 v1.2.14 無法滿足需求

### ✅ 正常運作的功能
1. Output Assembly 寫入 (18 bytes) - 通道控制
2. Input Assembly 讀取 (208 bytes) - 狀態查詢
3. 全域系統狀態檢查
4. 即時監控
5. 診斷工具

### ⚠️ 未充分測試的功能
1. Parameter Object 方法 (Class 0x0F)
   - 狀態：已實作但未啟用
   - 潛力：可繞過 244-byte 限制

## 程式碼優化建議

### 立即可做的清理

1. **移除失敗的方法**
   - `_set_nominal_current_config_assembly()` (856+ 行)
   - `_establish_implicit_messaging()` 中的 Forward Open 部分
   - `_build_forward_open_request()` (整個方法)
   - `_io_worker()` / `_io_worker_pycomm3()` (未使用)

2. **簡化結構**
   - 將診斷工具移至獨立檔案
   - 將多模組計算方法整理成獨立模組

3. **啟用可行方案**
   - 將 `_set_nominal_current_parameter_object()` 設為主要方法
   - 移除 Config Assembly 相關邏輯

### 預估可減少行數
- 移除 Forward Open 相關：~300 行
- 移除失敗的 Config Assembly 方法：~200 行
- 移除診斷工具（移至獨立檔案）：~400 行
- **總計可減少：~900 行 → 剩餘 ~2700 行**

## 下一步建議

### 方案 A：清理並專注於可行方案
1. 移除所有失敗的 Implicit Messaging 代碼
2. 啟用 Parameter Object 方法
3. 測試標稱電流設定功能
4. 保留診斷工具於獨立模組

### 方案 B：暫停標稱電流功能
1. 移除所有標稱電流相關代碼
2. 專注於通道控制和監控功能
3. 標稱電流由人工在設備上設定

### 方案 C：尋找其他函式庫
1. 測試 cpppo (支援 Forward Open)
2. 測試 pylogix
3. 評估切換成本

## 建議採用方案 A
- 最快速解決問題
- 保留所有功能
- 程式碼清晰度提升
