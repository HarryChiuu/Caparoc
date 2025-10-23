# CAPAROC 多通道控制問題 - DEBUG 分析報告

## 日期
2025-01-23

## 問題描述

### 主要問題
1. **多通道互相干擾**：開啟 CH2 時，CH1 會被關閉
2. **off 指令失效**：執行 off 後通道會先關閉再自動開啟
3. **重複開啟失效**：已經開啟過的通道，關閉後無法再次開啟

### 次要問題
4. **狀態讀取錯誤**：讀取的電流值不是實際值（但原廠 Web UI 顯示正確）

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

## 下一步行動建議

1. **優先嘗試方向 2**: 在 LED 按鈕模擬時保留其他通道狀態
   - 風險相對較低
   - 如果成功，能完全解決問題
   
2. **備選方案 1**: 只使用 Instance 0x67-0x6A
   - 快速測試
   - 可能無法設定額定電流
   
3. **備選方案 5**: 聯繫廠商或深入研究協議
   - 最根本的解決方式
   - 但需要更多時間

4. **最後手段**: 實作順序控制（方向 4）
   - 確保功能可用
   - 犧牲使用者體驗

---

## Git 提交資訊

本次提交包含:
1. `caparoc_simple_control_debug.py` - DEBUG 版本（包含 I/O Worker 暫停機制）
2. `DEBUG_ANALYSIS.md` - 本分析報告

已知問題:
- 多通道控制互相干擾（CH2 開啟時 CH1 被關閉）
- 重複開啟失效（關閉後無法再次開啟）
- off 指令異常（關閉後自動重新開啟）
