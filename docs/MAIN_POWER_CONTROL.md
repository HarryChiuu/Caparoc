# 主開關控制說明

## ✅ 是的，可以直接控制 Breaker PWR 的主開關！

## 🎯 功能說明

### 主開關 (Main Power Switch)
- **位置**: Output Assembly Byte 0, bit 0
- **功能**: 控制整個系統的總電源
- **用途**: 緊急停止、系統維護、集中控制

### 控制方法

#### 方法 1: 使用新增的 API
```python
from caparoc_controller import CaparocController

controller = CaparocController("192.168.2.111")
controller.driver = driver  # CIPDriver 實例

# 開啟主開關
controller.set_main_power(True)

# 關閉主開關
controller.set_main_power(False)
```

#### 方法 2: 使用範例程式
```bash
python example_main_power_control.py
```

然後在互動式介面中輸入：
- `on` - 開啟主開關
- `off` - 關閉主開關
- `s` - 查看狀態

## 📊 Output Assembly 結構

```
Byte 0 (主開關控制):
  bit 7 = 1: Release (必須設為 1)
  bit 0 = 1: 主開關開啟
  bit 0 = 0: 主開關關閉

Byte 1 (個別通道控制):
  bit 7 = 1: Release (必須設為 1)
  bit 3 = CH4 開關
  bit 2 = CH3 開關
  bit 1 = CH2 開關
  bit 0 = CH1 開關
```

## 🔍 主開關 vs 個別通道

### 主開關關閉時
- ❌ 所有通道都會停止供電
- ❌ 無論個別通道設定如何
- ✅ 用於緊急停止

### 主開關開啟時
- ✅ 系統可以供電
- ⚠️ 個別通道仍需個別開啟
- ✅ 正常操作模式

## 📝 使用範例

### 緊急停止場景
```python
# 緊急情況 - 立即停止所有供電
controller.set_main_power(False)
```

### 系統維護場景
```python
# 1. 關閉主開關
controller.set_main_power(False)

# 2. 進行維護工作...

# 3. 維護完成後開啟主開關
controller.set_main_power(True)

# 4. 個別開啟需要的通道
controller.set_channel(1, True)
controller.set_channel(2, True)
```

### 正常操作場景
```python
# 1. 確保主開關開啟
controller.set_main_power(True)

# 2. 控制個別通道
controller.set_channel(1, True)   # 開啟 CH1
controller.set_channel(2, False)  # 關閉 CH2
```

## ⚙️ 技術細節

### Output Assembly 寫入值

**開啟主開關:**
```
Byte 0 = 0x81  (0b10000001)
  bit 7 = 1 (Release)
  bit 0 = 1 (Power ON)
```

**關閉主開關:**
```
Byte 0 = 0x80  (0b10000000)
  bit 7 = 1 (Release)
  bit 0 = 0 (Power OFF)
```

### CIP 訊息格式
```python
driver.generic_message(
    service=0x10,           # Set Attribute Single
    class_code=0x04,        # Assembly Object
    instance=0x64,          # Output Assembly
    attribute=3,            # Data
    request_data=output_data,  # 18 bytes (Byte 0 控制主開關)
    connected=False
)
```

## 🚀 快速開始

1. **安裝依賴**
   ```bash
   pip install pycomm3
   ```

2. **運行範例程式**
   ```bash
   python example_main_power_control.py
   ```

3. **測試命令**
   ```
   > on    # 開啟主開關
   > off   # 關閉主開關
   > s     # 查看狀態
   ```

## ⚠️ 注意事項

1. **主開關優先級最高**
   - 主開關關閉時，所有通道都會斷電
   - 即使個別通道設定為開啟也無效

2. **開啟流程**
   - 先開啟主開關
   - 再開啟個別需要的通道

3. **安全考量**
   - 緊急情況使用主開關立即斷電
   - 系統維護前務必關閉主開關

## 📚 相關文件

- `src/caparoc_controller.py` - 主程式 (新增 `set_main_power()` 方法)
- `example_main_power_control.py` - 主開關控制範例
- `INTERACTIVE_TEST_GUIDE.md` - 互動式測試指南
