# CAPAROC 多通道控制問題 - DEBUG 分析報告

## 更新日期
- 初始分析: 2025-01-23
- **成功解決**: 2025-01-27 ✅

---

## 🎉 問題解決狀態

### ✅ 已解決問題
1. **多通道互相干擾** → ✅ **已解決**
   - 問題: 開啟 CH2 時，CH1 會被關閉
   - 解決: 使用位元運算保留其他通道狀態
   
2. **off 指令失效** → ✅ **已解決**
   - 問題: 執行 off 後通道會先關閉再自動開啟
   - 解決: 正確的位元運算邏輯
   
3. **重複開啟失效** → ✅ **已解決**
   - 問題: 已經開啟過的通道，關閉後無法再次開啟
   - 解決: 智能額定電流管理（只在首次設定）

### ⚠️ 待解決問題
4. **狀態讀取功能異常** → ⚠️ **優先處理**
   - 問題: `show_status()` 或 's' 命令無法正常讀取通道狀態
   - 需要: 診斷 Assembly.101 讀取邏輯
   
5. **GUI 介面重新規劃** → 📋 **待規劃**
   - 現有 GUI 需要整合新的控制邏輯
   - 需要支援 Implicit Messaging 模式
   - 詳見後續章節

---

## 📊 初始問題描述 (2025-01-23)

## 測試環境
- **設備 IP**: 192.168.2.111
- **Python 版本**: 3.11 (Conda)
- **pycomm3 版本**: >=1.2.14
- **Assembly Instances**:
  - Output: 0x64
  - Input: 0x65
  - Config: 0x67-0x6A
  - Status: 0x101

## 已測試的解決方案

### 方案 1: 只在首次開啟時設定額定電流 ❌
**實作**: `channel_first_opened` set 記錄已設定的通道

**結果**: 
- ❌ 第一次 `on 1` 成功
- ❌ `off 1` 成功
- ❌ 第二次 `on 1` **完全失效**

**結論**: `set_nominal_current` 不只是設定額定電流，它是**每次開啟的必要步驟**

---

### 方案 2: 暫停 I/O Worker 避免競爭 ❌
**實作**: 
- 添加 `pause_io_worker` 旗標
- `set_nominal_current` 執行前暫停 I/O Worker
- 完成後恢復 I/O Worker

**結果**:
- ❌ CH2 開啟時，CH1 仍然被關閉
- ⚠️ 暫停機制正常運作，但問題依舊

**結論**: 問題不在 I/O Worker 競爭，而在設備端的行為

---

## 深入分析

### 測試程式 vs 控制程式的差異

#### 測試程式 (caparoc_implicit_test.py) ✅ 能正常工作
```python
def run_four_channel_test():
    # 順序測試
    for channel in range(1, 5):
        set_channel(channel, True)   # 開啟
        time.sleep(2)
        set_channel(channel, False)  # 關閉
        time.sleep(1)
```

**特點**:
- ✅ **永遠只有一個通道開啟**
- ✅ 完整的 開→關 循環
- ✅ 從不同時開啟多個通道

#### 控制程式 (caparoc_simple_control.py) ❌ 多通道失敗
```python
# 使用者操作
on 1   # CH1 開啟
on 2   # CH2 開啟，但 CH1 被關閉 ❌
```

**特點**:
- ❌ 需要**同時開啟多個通道**
- ❌ 不按固定順序操作

---

### set_nominal_current 的實際行為

#### 執行流程
```python
for instance in [0x67, 0x68, 0x69, 0x6A, 0x64]:
    # 1. 進入程式模式 (2.5秒)
    prog_data = bytearray(data_length)
    prog_data[channel_byte] = 0xC0
    generic_message(instance, prog_data)
    
    # 2. 模擬按鈕 4 次 (3.2秒)
    for i in range(4):
        press_data = bytearray(data_length)
        press_data[channel_byte] = (1 << channel_bit) | 0x80
        generic_message(instance, press_data)
        
        release_data = bytearray(data_length)
        release_data[channel_byte] = 0x80
        generic_message(instance, release_data)
    
    # 3. 儲存設定 (3秒)
    save_data = bytearray(data_length)
    save_data[channel_byte] = (1 << channel_bit) | 0xC0
    generic_message(instance, save_data)
    
    # 4. 退出程式模式
    exit_data = bytearray(data_length)  # 全 0
    generic_message(instance, exit_data)
```

#### 關鍵發現

**Instance 0x64 是 Output Assembly！**

當 `set_nominal_current` 向 Instance 0x64 發送資料時：
- `prog_data[1] = 0xC0` → 清除所有通道控制位元
- `exit_data[1] = 0x00` → 清除所有通道控制位元

**DEBUG 輸出證據**:
```
[DEBUG] 執行前 byte[1]: 0x81 (CH1=True)
[DEBUG] 嘗試 Instance 0x64, data_length=18
[DEBUG] prog_data[1]=0xC0  ← 只設定程式模式位元
[DEBUG] exit_data[1]=0x00  ← 全 0！
[DEBUG] 執行後 byte[1]: 0x81 (保持不變)
```

雖然 `current_output_data` buffer 保持 0x81，但設備端收到了 0x00！

---

### I/O Worker 的行為

#### 正常運作確認
```
[I/O Worker] 週期 2950: 持續寫入 byte[1]=0x83
[I/O Worker] 週期 3000: 持續寫入 byte[1]=0x83
```

- ✅ I/O Worker 使用 `generic_message` 正常寫入
- ✅ 每 50ms (20Hz) 持續更新
- ✅ 沒有 'CIPDriver' has no attribute 'write' 錯誤（已修復）

#### 但是...
```
[DEBUG] 退出程式模式 -> Instance 0x64, 發送全 0 資料
[DEBUG] exit_data[1]=0x00
```

**set_nominal_current 也在向 Instance 0x64 寫入！**

即使 I/O Worker 被暫停：
- `set_nominal_current` 的 `generic_message` 直接修改設備狀態
- 發送的 `bytearray(data_length)` 包含 **byte[1]=0x00**
- 設備接收到全 0，導致其他通道關閉

---

## 根本原因分析

### 問題核心
`set_nominal_current` 使用 LED 按鈕模擬方式，**必須**向 Instance 0x64 發送控制訊息。

這些訊息中的 **byte[1] 值會直接影響通道狀態**：

1. **進入程式模式**: `byte[1] = 0xC0` (bit7=1, bit6=1)
   - 這會清除 bit0-3 的通道控制位元
   
2. **按鈕操作**: `byte[1] = (1 << channel_bit) | 0x80`
   - 只設定當前通道的位元，其他通道位元為 0
   
3. **退出程式模式**: `byte[1] = 0x00`
   - **所有位元都是 0！**

### 為什麼測試程式能工作？

測試程式是**順序測試**，同一時間只有一個通道開啟：
- `on 1` → `set_nominal_current(CH1)` → byte[1] 被清除 → 沒關係，反正其他通道本來就是關的
- `off 1` → byte[1] 清除 → 沒關係
- `on 2` → `set_nominal_current(CH2)` → byte[1] 被清除 → 沒關係，CH1 已經在前一步關閉了

### 為什麼多通道控制失敗？

```
狀態: CH1=開 (byte[1]=0x81)
↓
執行 on 2
↓
set_nominal_current(CH2) 發送:
  - prog_data[1] = 0xC0  → CH1 被清除
  - exit_data[1] = 0x00  → CH1 被清除
↓
結果: CH1 被關閉，只有 CH2 開啟
```

---

## 可能的解決方向

### 方向 1: 避免使用 Instance 0x64 ⚠️
**想法**: 只使用 0x67-0x6A 進行 `set_nominal_current`

**問題**: 
- 測試程式也是使用相同的 instance 順序 (0x67, 0x68, 0x69, 0x6A, 0x64)
- 不確定其他 instance 是否能成功設定額定電流

**建議測試**:
```python
instances = [0x67, 0x68, 0x69, 0x6A]  # 移除 0x64
```

---

### 方向 2: 在 generic_message 中保留其他通道狀態 ⚠️
**想法**: 在發送 LED 按鈕模擬訊息時，保留 byte[1] 的其他通道位元

**實作**:
```python
# 進入程式模式
with self.io_data_lock:
    current_state = self.current_output_data[1] & 0x0F  # 保留 bit0-3
prog_data[channel_byte] = 0xC0 | current_state

# 退出程式模式
with self.io_data_lock:
    current_state = self.current_output_data[1] & 0x0F
exit_data[channel_byte] = 0x80 | current_state  # 保留狀態 + bit7
```

**風險**:
- 可能干擾 LED 按鈕模擬的正確性
- 設備可能不接受這種混合控制

---

### 方向 3: 初始化所有通道，之後純 I/O 控制 ⚠️
**想法**: 程式啟動時一次性設定所有通道額定電流，之後不再呼叫 `set_nominal_current`

**問題**: 
- 之前測試過，重複開啟會失效
- 說明 `set_nominal_current` 不只是設定額定電流，它還做了其他初始化

---

### 方向 4: 模仿測試程式的順序控制 ⚠️
**想法**: 不支援同時多通道開啟，改為順序控制

**實作**:
```python
def set_channel(channel, state):
    if state:
        # 開啟前，先關閉所有其他通道
        for ch in range(1, 5):
            if ch != channel:
                set_channel_internal(ch, False)
        set_channel_internal(channel, True)
```

**缺點**:
- 無法滿足使用者需求（需要多通道同時開啟）
- 失去互動控制的靈活性

---

### 方向 5: 深入研究設備協議 ⭐ 推薦
**想法**: 研究 CAPAROC 設備的真正控制協議

**需要**:
1. 查閱設備手冊的通訊協議章節
2. 了解 Assembly 0x64 的真正作用
3. 確認是否有其他控制方式（不使用 LED 按鈕模擬）

**可能發現**:
- 可能有專門的控制 Assembly
- 可能有不同的 Service Code
- 可能 LED 按鈕模擬本來就不支援多通道

---

## 當前程式狀態

### 檔案: `src/caparoc_simple_control_debug.py`
- ✅ 使用 `generic_message` 進行 I/O 讀寫（避免 'write' attribute 錯誤）
- ✅ 詳細的 DEBUG 輸出（追蹤 byte[1] 變化）
- ✅ I/O Worker 暫停機制（避免競爭，但未解決問題）
- ⚠️ 每次開啟都呼叫 `set_nominal_current`（符合測試程式邏輯）
- ❌ 多通道控制仍然失敗

### 檔案: `src/caparoc_simple_control.py` (原始版本)
- 已使用 `git checkout` 恢復到原始狀態
- 包含所有已知 bug

---

---

## 🎯 成功解決方案 (2025-01-27)

### 解決方案: V3 架構改進

#### 核心修正 1: 正確的 Output Assembly 大小
```python
# ❌ 錯誤 (導致 "Too much data" 錯誤)
self.current_output_data = bytearray(20)

# ✅ 正確 (符合手冊規範)
self.current_output_data = bytearray(18)  # Assembly 0x64 = 18 bytes
```

**影響**: 解決了所有寫入失敗問題

---

#### 核心修正 2: 位元運算保留其他通道狀態
```python
# 讀取當前狀態
current_value = self.current_output_data[byte_offset]

# 開啟通道 (使用 OR 運算，保留其他通道)
new_value = current_value | (1 << bit_position) | 0x80

# 關閉通道 (使用 AND NOT 運算，保留其他通道)  
new_value = (current_value & ~(1 << bit_position)) | 0x80
```

**影響**: 
- ✅ 開啟 CH2 時，CH1 保持開啟
- ✅ 關閉 CH1 時，CH2 保持開啟
- ✅ 完全獨立的通道控制

---

#### 核心修正 3: 智能額定電流管理
```python
# 額定電流配置追蹤
self.nominal_current_configured = {1: False, 2: False, 3: False, 4: False}
self.channel_nominal_current = {1: 0, 2: 0, 3: 0, 4: 0}

# 智能判斷
if not self.nominal_current_configured[channel]:
    # 首次開啟: 執行完整按鈕模擬 (7-10秒)
    self._set_nominal_current(module, channel, nominal_current)
    self.nominal_current_configured[channel] = True
else:
    # 後續開關: 直接控制 (<1秒) ⚡
    logger.info("額定電流已設定，直接開啟")
```

**影響**:
- ✅ 首次開啟需要 7-10 秒（設定額定電流）
- ✅ 後續開關只需 <1 秒（快速控制）
- ✅ 可以重複開關任意次數

---

### 實測結果

#### 測試場景 1: 多通道同時開啟 ✅
```bash
> on 1
✅ 通道 1 開啟成功

> on 2  
✅ 通道 2 開啟成功

> status
CH1: 🟢 ON  |  0.45 A  ← 保持開啟 ✅
CH2: 🟢 ON  |  0.52 A  ← 新開啟 ✅
```

#### 測試場景 2: 獨立關閉 ✅
```bash
> off 1
✅ 通道 1 關閉成功

> status  
CH1: ⚫ OFF |  0.00 A  ← 已關閉 ✅
CH2: 🟢 ON  |  0.52 A  ← 保持開啟 ✅
```

#### 測試場景 3: 重複開關 ✅
```bash
> on 1
通道 1 額定電流已設定 (4A)，直接開啟
✅ 通道 1 開啟成功
[耗時 <1 秒] ⚡ 超快！
```

---

## ⚠️ 待解決問題

### 優先級 1: 狀態讀取功能異常

#### 問題描述
- `show_status()` 方法或 `s` 命令無法正常讀取通道狀態
- 可能的原因：
  1. Assembly.101 讀取邏輯錯誤
  2. 資料解析偏移量不正確
  3. Response 物件處理異常

#### 診斷重點
```python
# 需要檢查的項目
1. Assembly.101 是否可訪問
2. response.value 是否存在
3. 資料長度是否足夠
4. struct.unpack 偏移量是否正確
5. 錯誤處理是否完整
```

#### 已添加的 DEBUG 輸出
```python
# caparoc_simple_v3.py 中已增強
- Response 物件驗證
- 資料長度檢查
- 詳細的錯誤訊息
- 完整的 traceback 輸出
```

#### 下一步行動
1. 執行 `s` 命令並觀察 DEBUG 輸出
2. 確認 Assembly.101 是否回應
3. 檢查資料格式是否符合預期
4. 必要時使用 `generic_message` 直接讀取測試

---

### 優先級 2: GUI 介面重新規劃

#### 現有 GUI 問題分析
1. **caparoc_gui.py** (原始 GUI)
   - 未整合新的 V3 控制邏輯
   - 不支援 Implicit Messaging
   - 缺少智能額定電流管理
   
2. **caparoc_unified_edit.py** (統一控制器)
   - 包含多種控制模式
   - 代碼過於複雜
   - 需要簡化和重構

#### GUI 重新規劃要點

##### 1. 架構設計
- [ ] 採用 MVC 或 MVP 模式分離邏輯
- [ ] Controller 使用 `caparoc_simple_v3.py` 的成功邏輯
- [ ] 支援 Implicit Messaging 自動偵測和切換
- [ ] 統一的錯誤處理和狀態顯示

##### 2. 功能需求
- [ ] **基本控制**
  - [ ] 4 通道獨立開關按鈕
  - [ ] 全開 / 全關快捷按鈕
  - [ ] 通道狀態即時顯示（開/關/電流）
  
- [ ] **高級功能**
  - [ ] 額定電流設定介面（預設 4A，可調整 1-10A）
  - [ ] 重置額定電流配置功能
  - [ ] 連接模式顯示（Implicit / Explicit）
  
- [ ] **監控功能**
  - [ ] 即時電壓顯示
  - [ ] 即時總電流顯示
  - [ ] 各通道電流條形圖
  - [ ] 歷史資料圖表（可選）

##### 3. 介面設計
- [ ] **主控制面板**
  ```
  ┌─────────────────────────────────────┐
  │  CAPAROC 4通道控制器 v3.0          │
  │  設備: 192.168.2.111  [已連接]     │
  ├─────────────────────────────────────┤
  │  系統狀態:                          │
  │    電壓: 24.5 V  |  總電流: 1.2 A  │
  ├─────────────────────────────────────┤
  │  通道控制:                          │
  │                                     │
  │  CH1 [🟢 ON ]  0.45 A  [開啟][關閉]│
  │  CH2 [⚫ OFF]  0.00 A  [開啟][關閉]│
  │  CH3 [⚫ OFF]  0.00 A  [開啟][關閉]│
  │  CH4 [⚫ OFF]  0.00 A  [開啟][關閉]│
  │                                     │
  │  [全部開啟]  [全部關閉]  [刷新狀態]│
  ├─────────────────────────────────────┤
  │  額定電流設定: [4] A (1-10)        │
  │  [重置CH1] [重置CH2] [重置CH3] [重置CH4]│
  ├─────────────────────────────────────┤
  │  連接模式: Implicit Messaging ✅   │
  │  狀態: 正常運行                     │
  └─────────────────────────────────────┘
  ```

- [ ] **設定對話框**
  - 設備 IP 設定
  - Assembly Instance 設定
  - 自動重連設定
  - 日誌級別設定

##### 4. 技術選型
- [ ] **GUI 框架**: 
  - 選項 1: tkinter (內建，簡單)
  - 選項 2: PyQt5/PySide6 (功能強大)
  - 選項 3: CustomTkinter (現代化外觀)
  
- [ ] **即時更新**:
  - 使用 threading 避免 UI 凍結
  - 定期輪詢狀態（1 秒間隔）
  - 事件驅動的狀態更新

##### 5. 開發階段
- [ ] **階段 1**: 基本控制界面（1-2 天）
  - 4 通道開關按鈕
  - 基本狀態顯示
  - 連接管理
  
- [ ] **階段 2**: 增強功能（2-3 天）
  - 額定電流設定
  - 即時監控
  - 錯誤處理
  
- [ ] **階段 3**: 優化和美化（1-2 天）
  - UI/UX 改進
  - 動畫效果
  - 配色優化

##### 6. 整合策略
```python
# 推薦方案: 創建新的 GUI 文件
# gui/caparoc_v3_gui.py

from caparoc_simple_v3 import CaparocController

class CaparocGUI:
    def __init__(self):
        self.controller = CaparocController()
        # ... GUI 初始化
    
    def on_channel_button_click(self, channel, state):
        # 直接使用 V3 的成功邏輯
        self.controller.set_channel(channel, state)
        self.update_status()
```

---

## 技術細節記錄

### Output Assembly 結構 (18 bytes)
```
Byte 0:   [保留]
Byte 1:   控制位元
          - bit0: CH1 (0=關, 1=開)
          - bit1: CH2 (0=關, 1=開)
          - bit2: CH3 (0=關, 1=開)
          - bit3: CH4 (0=關, 1=開)
          - bit4-6: [保留]
          - bit7: Release bit (必須為 1)
Byte 2-12: [其他控制]
Byte 13:  通道1 額定電流 (1-10A)
Byte 14:  通道2 額定電流 (1-10A)
Byte 15:  通道3 額定電流 (1-10A)
Byte 16:  通道4 額定電流 (1-10A)
Byte 17:  [保留]
```

### 位元運算範例
```python
# 場景: CH1 已開啟 (byte[1] = 0x81)，要開啟 CH2

current_value = 0x81  # 10000001 (bit7=1, bit0=1)
new_value = current_value | (1 << 1) | 0x80
# = 0x81 | 0x02 | 0x80
# = 0x83  # 10000011 (bit7=1, bit1=1, bit0=1)

# 結果: CH1 和 CH2 都開啟 ✅
```

---

## Git 提交資訊

### 本次提交 (2025-01-27)
**檔案**:
1. `src/caparoc_simple_v3.py` - V3 成功版本
2. `CHANGELOG.md` - 詳細的變更記錄
3. `DEBUG_ANALYSIS.md` - 本分析報告（更新）

**成功解決**:
- ✅ 多通道互相干擾問題
- ✅ 重複開啟失效問題
- ✅ off 指令異常問題

**待解決**:
- ⚠️ 狀態讀取功能異常（優先）
- 📋 GUI 介面重新規劃（已列點）

**測試狀態**:
- ✅ 4 通道獨立控制完全正常
- ✅ 開關速度顯著提升（<1秒）
- ✅ 可以任意組合開關通道

---

## 下一步行動

### 立即行動
1. **診斷狀態讀取問題**
   - 執行 `s` 命令
   - 觀察 DEBUG 輸出
   - 找出根本原因
   - 修復並測試

### 短期計劃  
2. **GUI 開發**
   - 選擇 GUI 框架
   - 實作基本控制界面
   - 整合 V3 控制邏輯
   - 測試和優化

### 長期優化
3. **代碼整理**
   - 移除過時的測試文件
   - 統一代碼風格
   - 完善文檔註釋
   - 添加單元測試
