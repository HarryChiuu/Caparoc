# CAPAROC 標稱電流寫入限制分析

## 測試總結

經過詳盡測試,**無法透過 pycomm3/EtherNet/IP 寫入標稱電流參數**。

## 已測試的方法

### 1. Parameter Object - Service 0x10 (Set Attribute Single)
```python
driver.generic_message(
    service=0x10,
    class_code=0x0F,  # Parameter Object
    instance=9,        # Param9 (M1.CH2)
    attribute=1,
    request_data=bytes([4]),  # 4A
    connected=False
)
```
**結果**: ❌ "Too much data"

### 2. Parameter Object - Service 0x4B (Set Parameters)
```python
request_data = bytes([
    0x01, 0x00,  # Count = 1
    0x09, 0x00,  # Param 9
    0x04         # Value = 4A
])
driver.generic_message(
    service=0x4B,
    class_code=0x0F,
    instance=0,
    request_data=request_data,
    connected=False
)
```
**結果**: ❌ "Service not supported"

### 3. Config Assembly (讀取-修改-寫入)
```python
# 讀取 244 bytes
config_data = read_config_assembly()

# 解鎖全域鎖定
config_data[0] = 0  # Param1 (Global nominal current lock)
config_data[1] = 0  # Param2 (Global UI lock)

# 修改標稱電流
config_data[9] = 4  # Param9 @ offset 9

# 寫回 244 bytes
write_config_assembly(config_data)
```
**結果**: ❌ "Too much data"

### 4. LED 按鈕模擬
```python
# 進入程式模式 → 按鈕按 4 次 → 儲存 → 退出
```
**結果**: ⚠️ 設定 4A,但驗證顯示 3A (不準確)

## 鎖定狀態檢查

### ✅ 所有鎖定都已解除

| 鎖定類型 | 位置 | 狀態 | 值 |
|---------|------|------|---|
| 硬體鎖 | PWR 按鈕 | ✅ 已解除 | LED 閃爍綠色 3 次 |
| 通道 Programming Lock | Param10 | ✅ Unlocked | 0 |
| 全域 Nominal Current Lock | Param1 (Byte 0) | ✅ Unlocked | 0 |
| 全域 UI Lock | Param2 (Byte 1) | ✅ Unlocked | 0 |

## 讀取測試

### ✅ 讀取功能正常

| 測試項目 | 方法 | 結果 |
|---------|------|------|
| Parameter Object | Service 0x0E, Class 0x0F, Instance 9, Attr 1 | ✅ 成功 (值=3) |
| Config Assembly | Service 0x0E, Class 0x04, Instance 0x66, Attr 3 | ✅ 成功 (244 bytes) |
| Input Assembly | Service 0x0E, Class 0x04, Instance 0x65, Attr 3 | ✅ 成功 (208 bytes) |

## "Too much data" 錯誤分析

### 問題特徵
- 錯誤訊息: "Too much data"
- 發生在: 所有寫入操作
- 即使: 發送正確的資料大小 (1 byte for Parameter, 244 bytes for Config)

### 可能原因

1. **韌體限制**: 
   - 設備韌體可能禁止透過 EtherNet/IP 修改這些參數
   - 僅允許透過硬體按鈕或專用軟體修改

2. **連線狀態限制**:
   - 可能需要在特定的連線狀態下才能寫入
   - 例如: 需要關閉 I/O 連線,或使用特定的連線類型

3. **CIP 實作差異**:
   - 設備的 CIP 實作可能與標準不完全一致
   - pycomm3 發送的封包格式可能與設備期望的不同

4. **安全機制**:
   - 設備可能要求額外的安全認證或握手程序
   - 可能需要特定的 Vendor Specific Service

## EDS 文件分析

### Param9 定義 (M1.CH2 Nominal Current)
```
Param9 =
    0,                      $ reserved
    6,"20 0F 24 09 30 01",  $ Link Path
    0x0000,                 $ Descriptor (無特殊限制)
    0xC6,                   $ Data Type (USINT)
    1,                      $ Data Size (1 byte)
    "Mod 1 Ch 2 nominal current",
    "A",                    $ units
    "",                     $ help string
    0,20,0,                 $ min, max, default
```

- **Descriptor = 0x0000**: 表示沒有 Read-Only 限制
- **Data Type = 0xC6 (USINT)**: 1 byte 無符號整數
- **Range**: 0-20A

### Config Assembly 定義 (Assem102)
```
Assem102 =
    "Configuration Assembly",
    "20 04 24 66 30 03",
    244,                    $ Total size
    ...
    8,Param1,              $ offset 0 (Global nominal current lock)
    8,Param2,              $ offset 1 (Global UI lock)
    16,Param3,             $ offset 2-3
    8,Param4,              $ offset 4
    8,Param5,              $ offset 5
    8,Param6,              $ offset 6 (M1.CH1 nominal)
    ...
    8,Param9,              $ offset 9 (M1.CH2 nominal)
```

- **用途**: 建立連線時的配置
- **手冊說明**: Read/write
- **實際測試**: 可讀,不可寫

## pycomm3 封包分析

### 寫入 Parameter Object 時發送的資料

```
Service: 0x10 (Set Attribute Single)
Path: 20 0F 24 09 30 01
  - 20 0F: Class 0x0F (Parameter Object)
  - 24 09: Instance 9
  - 30 01: Attribute 1
Request Data: 04 (1 byte)
```

### 設備回應
```
Error: "Too much data"
Value: b'' (empty)
```

## 建議的解決方案

### 方案 1: 使用設備網頁介面 (推薦)
如果設備有內建 Web Server:
1. 瀏覽器訪問設備 IP (http://192.168.2.111)
2. 登入設備管理介面
3. 在配置頁面修改標稱電流

### 方案 2: 使用專業 PLC 軟體
使用 Rockwell Automation 或類似軟體:
1. **RSLogix 5000 / Studio 5000**
2. **EtherNet/IP Configuration Tool**
3. 匯入 EDS 文件
4. 離線配置參數
5. 下載到設備

### 方案 3: 聯繫廠商
1. 詢問是否支援透過 EtherNet/IP 修改參數
2. 獲取專用配置軟體
3. 確認正確的寫入程序

### 方案 4: 接受硬體按鈕方式
如果其他方案不可行:
1. 使用設備上的實體按鈕
2. 按照手冊 6.1.3 節的步驟手動設定
3. 在程式中只讀取和監控,不嘗試寫入

## 未來研究方向

### 1. Wireshark 封包分析
- 捕獲 pycomm3 發送的封包
- 與 Studio 5000 的封包比較
- 找出差異點

### 2. 測試不同的連線模式
```python
# 嘗試 connected=True
driver.generic_message(..., connected=True)

# 嘗試關閉 I/O 連線後寫入
driver.close_connection()
driver.generic_message(...)
```

### 3. 嘗試其他 CIP 函式庫
- **cpppo**: Python CIP 函式庫
- **pylogix**: Allen-Bradley PLC 函式庫
- **直接構建 CIP 封包**: 使用 socket

### 4. 韌體更新
- 檢查是否有新版本韌體
- 查看更新說明中是否提到 EtherNet/IP 參數寫入

## 結論

經過全面測試:
- ✅ **可以讀取**: Parameter Object, Config Assembly, Input Assembly
- ✅ **所有鎖定已解除**: 硬體鎖、軟體鎖、全域鎖
- ❌ **無法寫入**: 所有方法都失敗 ("Too much data")

**最可能的原因**: 設備韌體限制,不允許透過 EtherNet/IP 修改標稱電流參數。

**建議**: 
1. 優先嘗試設備網頁介面
2. 如無,使用專業 PLC 軟體
3. 或聯繫廠商獲取技術支援

**程式策略**:
- 移除初始化標稱電流的功能
- 只提供讀取和監控功能
- 在文檔中說明需要手動設定標稱電流
