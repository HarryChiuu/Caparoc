# 連線檢查修正說明

## 問題
原本的連線檢查使用 CIP Identity Object (Class 0x01) 來驗證連線，但 **CAPAROC 設備不支援此標準物件**，導致連線失敗錯誤：

```
❌ 裝置連線失敗!
   錯誤: 設備無回應或不支援 Identity Object
```

## 原因分析
Identity Object 是 CIP 標準物件，大多數工業設備都支援，但 CAPAROC 是專用設備，只實作了必要的 Assembly Objects，不支援 Identity Object。

## 解決方案
改用 **Input Assembly (0x65)** 來驗證連線，這是 CAPAROC 已知支援且正常運作的方法。

### 修改內容

**修改前：**
```python
# 嘗試讀取 Identity Object (Class 0x01, Instance 1)
response = driver.generic_message(
    service=0x0E,
    class_code=0x01,  # Identity Object ❌ CAPAROC 不支援
    instance=1,
    attribute=1,
    connected=False
)
```

**修改後：**
```python
# 改用讀取 Input Assembly 來驗證連線
response = driver.generic_message(
    service=0x0E,
    class_code=0x04,  # Assembly Object ✅ CAPAROC 支援
    instance=0x65,    # Input Assembly
    attribute=3,
    connected=False
)
```

## 新功能
從 Input Assembly 讀取的設備資訊：
- **模組數量** (Byte 1): 顯示安裝的斷路器模組數
- **總通道數**: 自動計算 (模組數 × 4)
- **系統電壓** (Byte 4-5): 顯示實際系統電壓
- **設備類型**: 標註為 "CAPAROC Circuit Breaker"

## 顯示效果

### ✅ 連線成功
```
============================================================
🔌 檢查裝置連線...
============================================================
✅ 裝置連線成功!
   IP 位址: 192.168.2.111
   設備類型: CAPAROC Circuit Breaker
   模組數量: 1 個 (4 通道)
   系統電壓: 24.0V
============================================================
```

### ❌ 連線失敗（真正無連線）
```
============================================================
🔌 檢查裝置連線...
============================================================

❌ 裝置連線失敗!
   IP 位址: 192.168.2.111
   錯誤: 連線逾時: 192.168.2.111 無回應

💡 請檢查:
   1. 設備是否已開機
   2. 網路線是否正確連接
   3. IP 位址是否正確 (當前: 192.168.2.111)
   4. 電腦與設備是否在同一網段
   5. 防火牆是否阻擋連線
```

## 優點
1. ✅ **相容性**: 使用 CAPAROC 原生支援的 Assembly 方法
2. ✅ **資訊豐富**: 從 Input Assembly 直接讀取實際運行資訊
3. ✅ **可靠性**: 避免依賴可能不支援的標準物件
4. ✅ **效率**: 一次讀取就獲得多項設備資訊

## 技術細節

### Input Assembly (0x65) 資料結構
```
Byte 0:    全域系統狀態
Byte 1:    模組數量 (0-16)
Byte 2-3:  總電流 (16-bit, 0.1A 精度)
Byte 4-5:  系統電壓 (16-bit, 0.01V 精度)
Byte 6+:   各通道詳細資訊...
```

### 連線驗證邏輯
```python
if response and hasattr(response, 'value') and len(response.value) >= 6:
    result['connected'] = True
    # 讀取設備資訊...
```

## 測試確認
請使用實際 CAPAROC 設備測試：
```bash
python src/caparoc_controller.py
```

預期結果：
- 設備在線 → 顯示成功訊息及設備資訊
- 設備離線 → 顯示連線錯誤及故障排除建議

## 相關文件
- `src/caparoc_controller.py` Line ~1919: `check_device_connection()` 方法
- `CONNECTION_CHECK_UPDATE.md`: 原始連線檢查功能說明
