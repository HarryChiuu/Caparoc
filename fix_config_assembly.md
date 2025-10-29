# Config Assembly 問題分析與修正

## 問題根源

### 我的錯誤假設
- ❌ 假設 Config Assembly = 0x66 (244 bytes)
- ❌ 假設手冊 7.3.5 指的是 instance 0x66
- ❌ 嘗試寫入完整 244 bytes → "Too much data" 錯誤

### 實際情況
- ✅ 手冊提到的「Config Assembly」可能指的是**概念**，不是特定 instance
- ✅ 實際應該使用 **LED 按鈕模擬**方式
- ✅ 使用 instances **0x67, 0x68, 0x69, 0x6A** (20 bytes buffer)
- ✅ 0x64 也可嘗試 (18 bytes buffer)

## 正確實作

### 方法: LED 按鈕模擬 (已驗證可運作)

```python
# 步驟 1: 進入程式模式 (模擬長按)
prog_data = bytearray(20)  # 或 18 for 0x64
prog_data[module] = (1 << 7) | (1 << 6)  # 設定程式模式位元

# 步驟 2: 選擇通道
select_data = bytearray(20)
select_data[module] = (1 << (channel-1)) | (1 << 7)

# 步驟 3: 設定電流 (1-10A，重複短按)
for i in range(current_amps):
    press_data = bytearray(20)
    press_data[module] = (1 << 4) | (1 << 7)
    # 發送...
    
# 步驟 4: 確認 (長按)
confirm_data = bytearray(20)
confirm_data[module] = (1 << 5) | (1 << 7)
```

### 限制
- ⚠️  僅支援 **1-10A** 範圍
- ⚠️  需要嘗試多個 instance (0x67-0x6A, 0x64)
- ⚠️  無法直接設定 11-20A

## 手冊理解修正

### 7.3.5 節可能的意思
- **Config Assembly** = 配置資料結構的**抽象概念**
- **不是** 單一固定的 Assembly Instance 0x66
- **實際存取** 透過 LED 按鈕模擬協議 (使用 0x67-0x6A)

### EDS 參數表
- 參數編號 (6, 9, 12, 15...) 可能是:
  1. 文件說明用的編號
  2. **不能**直接當作 API 的 attribute 使用
  3. 需要透過 LED 模擬協議間接設定

## 下一步

1. ✅ 移除 Config Assembly 0x66 的實作
2. ✅ 改用 LED 按鈕模擬 (0x67-0x6A)
3. ✅ 保留僅支援 1-10A 的限制
4. ⚠️  如需 11-20A，可能需要其他方法
