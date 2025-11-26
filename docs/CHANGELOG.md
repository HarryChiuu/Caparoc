# Changelog

## [2025-11-26] Phase 3 完成 - CLI 全功能實現 🎉

### 🎯 重大里程碑
Phase 3 開發階段圓滿完成，實現完整的 CLI 控制系統。

### ✅ Phase 3 完成功能總覽

#### 核心功能 (v3.2-v3.7)
1. **標稱電流設定** ✅
   - `init` 命令互動式設定
   - Config Assembly Read-Modify-Write
   - 漸進式重試驗證 (0.5s-3s)
   - 修改前後值顯示與驗證

2. **四通道開關控制** ✅
   - `on <channel>` 開啟通道
   - `off <channel>` 關閉通道
   - 位元運算保留其他通道狀態
   - 智能額定電流管理

3. **狀態監控** ✅
   - `status` 查詢所有通道狀態
   - 全域系統狀態檢測 (7.2.1-7.2.5)
   - 通道電流即時顯示
   - 模組/通道動態識別

4. **即時監控** ✅
   - `monitor start/stop/status` 命令
   - 背景執行緒定期更新 (0.5s-60s 可調)
   - 狀態變化檢測與警報
   - 簡潔監控顯示格式

5. **多模組支援** ✅
   - 自動偵測 1-16 個模組
   - 動態通道管理 (最多 64 通道)
   - 多模組顯示格式 (M1.CH1 #1)
   - 向後兼容單模組環境

6. **連接管理** ✅
   - IP/Port 參數設定
   - 心跳機制維持連接
   - 自動重連機制
   - 完整錯誤處理

### 📊 Phase 3 統計
- **開發時間**: 2025-10-27 - 2025-11-26 (1 個月)
- **版本迭代**: v3.2 → v3.7
- **總工時**: ~20 小時
- **程式碼**: ~2000 行
- **文檔**: 15+ 份

### 🎨 優化與改進
1. **退出程式優化**
   - 顯示退出訊息
   - 減少延遲時間 (7s → 2s)

2. **文檔架構重組**
   - 創建 `docs/history/` 歸檔過時文檔
   - 創建 `docs/vendor/` 存放原廠文檔
   - 更新 PROGRAM_FLOW.md 至 v4.0
   - 簡化 README 和依賴配置

3. **代碼質量提升**
   - 移除重複代碼
   - 改善錯誤處理
   - 增強日誌輸出
   - 註解調試信息

### 🚀 下一步：Phase 4 規劃

**Phase 4 目標**: 進階功能與 GUI 開發

優先級功能：
1. 通道狀態資訊擴增 (2-3h)
2. GUI 圖形介面開發 (10-14h)
3. 數據記錄與分析 (6-8h)
4. 告警通知系統 (4-5h)
5. 多設備管理 (5-6h)
6. 自動化測試與 CI/CD (8-10h)

**Phase 4 預估工時**: 35-46 小時

### 📝 相關文檔
- `docs/TODO.md` - 已更新 Phase 4 規劃
- `docs/PROGRAM_FLOW.md` - v4.0 完整流程
- `docs/CLI_USER_GUIDE.md` - CLI 使用指南
- `docs/INIT_COMMAND_FLOW.md` - 標稱電流設定流程

---

## [2025-11-13] 重構與文檔完善 📚

### 🎯 重大重構
分離診斷工具，精簡主程式，完善文檔體系

### 📝 新增文檔
1. **MAIN_PROGRAM_FLOW.md**
   - 主程式完整流程說明
   - 6 大啟動步驟詳解
   - 核心功能流程（init, on/off, monitor）
   - Assembly 通訊機制
   - 多模組支援機制

2. **PROGRAM_FLOWCHART.md**
   - Mermaid 格式流程圖
   - 主程式啟動流程圖
   - 標稱電流設定流程圖
   - 通道控制流程圖
   - 即時監控流程圖
   - 重連機制流程圖

3. **DIAGNOSTIC_TOOLS_GUIDE.md**
   - 5 個診斷工具完整說明
   - 常見診斷情境與解決方案
   - 輸出解讀指南
   - Assembly 資料格式解析

### 🗂️ 檔案整理
1. **分離診斷工具**
   - 創建 `tests/diagnostic_tools.py` (549 行)
   - 從主程式移除 7 個診斷方法
   - 主程式精簡：3299 → 2090 行 (-36.6%)

2. **檔案重組**
   - ✅ 刪除 `src/caparoc_controller_clean.py` (重複檔案)
   - ✅ 移動 `tests/caparoc_implicit_test.py` → `archive/`
   - ✅ 移動 `check_connection.py` → `tests/`
   - ✅ 保留 `src/caparoc_controller_old.py` (舊版備份)

### 🐛 Bug 修復
**修復幫助信息重複顯示問題**
- 新增 `help_shown` 標記避免重複顯示
- 添加 `h`/`help` 命令隨時查看幫助
- 重新連線時顯示簡短提示

### 🎨 改進項目
1. **主程式精簡**
   - 刪除重複的 `_verify_nominal_current` 方法
   - 移除診斷命令處理（scan, limits, diagnose, compare, testwrite）
   - 更新幫助信息，移除診斷命令說明

2. **文檔體系**
   - 重新組織 docs/README.md
   - 新增快速導航分類
   - 添加文檔關係圖
   - 更新文檔更新規範

### 📂 當前專案結構
```
Caparoc5/
├── src/
│   ├── caparoc_controller.py      # 主程式 (2090 行) ✅
│   └── caparoc_controller_old.py  # 舊版備份
├── tests/
│   ├── diagnostic_tools.py        # 診斷工具 (549 行) 🆕
│   └── check_connection.py        # 連線檢查 🆕
├── archive/
│   └── caparoc_implicit_test.py   # 舊測試 🆕
└── docs/
    ├── MAIN_PROGRAM_FLOW.md       # 主程式流程 🆕
    ├── PROGRAM_FLOWCHART.md       # 流程圖 🆕
    ├── DIAGNOSTIC_TOOLS_GUIDE.md  # 診斷工具指南 🆕
    └── README.md                   # 文檔索引（已更新）
```

### 📊 統計數據
- 主程式代碼減少: 1209 行 (36.6%)
- 新增文檔: 3 份
- 診斷工具獨立: 549 行
- Git commits: 3 個

---

## [2025-10-21 v4] 完整多通道獨立控制 ⭐

### 🎉 重大改進
實現**真正的多通道獨立控制**，解決照搬測試程式導致的問題。

### 🐛 修正的問題

#### 問題 1: 每次開啟都執行完整按鈕模擬 ✅ 已修正
**現象**: 每次 `on 1` 都要等 7-10 秒
**修正**: 額定電流只設定一次，之後快速開關 (<1秒)

#### 問題 2: 無法關閉已開啟的通道 ✅ 已修正
**現象**: `off 1` 無法關閉通道 1
**原因**: `get_channel_current()` 缺少 `module` 參數
**修正**: 所有方法統一加入 `module` 參數

#### 問題 3: 開啟其他通道會關閉已開啟的通道 ✅ 已修正
**現象**: 通道 1 開啟時，`on 2` 會關閉通道 1
**原因**: 照搬測試程式的單通道測試邏輯
**修正**: 使用位元運算，保留其他通道狀態

### 🔧 核心改進

#### 1. 智能額定電流管理
```python
# 新增狀態追蹤
self.nominal_current_configured = {1: False, 2: False, 3: False, 4: False}
self.channel_nominal_current = {1: 0, 2: 0, 3: 0, 4: 0}

# 智能判斷
if not self.nominal_current_configured[channel]:
    # 首次：執行完整按鈕模擬 (7-10秒)
    self._set_nominal_current(module, channel, nominal_current)
    self.nominal_current_configured[channel] = True
else:
    # 之後：直接開啟 (<1秒)
    logger.info("額定電流已設定，直接開啟")
```

#### 2. 正確的位元運算
```python
# 開啟通道（OR 運算，保留其他通道）
self.output_data[1] = current_value | (1 << bit_position) | 0x80

# 關閉通道（AND NOT 運算，保留其他通道）
self.output_data[1] = (current_value & ~(1 << bit_position)) | 0x80
```

#### 3. 統一的 module 參數
所有方法現在都支援 `module` 參數（預設 1）：
- `turn_on_channel(channel, nominal_current=4, module=1)`
- `turn_off_channel(channel, module=1)`
- `get_channel_current(channel, module=1)`
- `get_all_status(module=1)`

### ✨ 新增功能

#### 重置額定電流設定
```python
def reset_nominal_current_config(channel=None):
    """如果需要重新設定額定電流值"""
    # channel=None 重置所有通道
    # channel=1-4 重置特定通道
```

Shell 命令：
```bash
> reset        # 重置所有通道
> reset 1      # 重置通道 1
```

### 📊 實際使用場景

#### 場景 1: 首次開啟通道
```bash
> on 1
首次設定通道 1 額定電流 4A...
[執行按鈕模擬 - 耗時 7-10 秒]
✅ 通道 1 額定電流設定完成
設定控制位元...
✅ 通道 1 開啟成功
```

#### 場景 2: 開啟第二個通道（第一個保持開啟）
```bash
> on 2
首次設定通道 2 額定電流 4A...
[執行按鈕模擬 - 耗時 7-10 秒]
✅ 通道 2 開啟成功

> status
CH1: 🟢 ON  |  0.45 A  ← 保持開啟 ✅
CH2: 🟢 ON  |  0.52 A  ← 新開啟 ✅
```

#### 場景 3: 快速關閉和重新開啟
```bash
> off 1
🔒 關閉通道 1
✅ 通道 1 關閉成功
[耗時 <1 秒]

> on 1
通道 1 額定電流已設定 (4A)，直接開啟
✅ 通道 1 開啟成功
[耗時 <1 秒] ✅ 超快！
```

#### 場景 4: 多通道並行控制
```bash
> on 1    # 首次 - 慢
> on 2    # 首次 - 慢
> on 3    # 首次 - 慢
> status
CH1: 🟢 ON  |  0.45 A
CH2: 🟢 ON  |  0.52 A
CH3: 🟢 ON  |  0.48 A
CH4: ⚫ OFF |  0.00 A

> off 2   # 快速關閉
> status
CH1: 🟢 ON  |  0.45 A  ← 保持開啟 ✅
CH2: ⚫ OFF |  0.00 A  ← 已關閉 ✅
CH3: 🟢 ON  |  0.48 A  ← 保持開啟 ✅
```

### 📖 更新的文件
- **MULTI_CHANNEL_FIX.md**: 詳細的問題分析和解決方案
- **caparoc_shell.py**: 增加 `reset` 命令和提示訊息

### 🎯 性能提升
- **首次開啟**: 7-10 秒（需要按鈕模擬）
- **後續開關**: <1 秒（直接控制） ⚡
- **多通道**: 完全獨立，互不干擾 ✅

### 💡 使用建議
1. 首次使用時，依序開啟需要的通道（會設定額定電流）
2. 之後的開關操作都很快速
3. 如需更改額定電流值，使用 `reset` 命令
4. 可以同時開啟多個通道，完全獨立控制

---

## [2025-10-21 v3] 修正控制失敗問題 - 實作完整按鈕模擬

### 🐛 根本原因
- **問題**: CLI 無法控制通道開關，但測試程式可以
- **原因**: CLI 缺少完整的額定電流設定流程（LED 按鈕模擬）
- **解決方案**: 從測試程式複製完整的按鈕模擬邏輯

### 🔍 關鍵發現

經過詳細對比 `caparoc_implicit_test.py` 和 `breaker_controller.py`，發現：

#### ❌ 原本的錯誤做法
```python
def _set_nominal_current(self, channel: int, current_amps: int):
    # ❌ 只修改記憶體中的 output_data
    position = 13 + (channel - 1)
    with self.io_lock:
        self.output_data[position] = int(current_amps)
    # ❌ 期望 I/O 執行緒自動同步（但設備不支援）
```

#### ✅ 正確的做法（從測試程式學習）
```python
def _set_nominal_current(self, module: int, channel: int, current_amps: int):
    # ✅ 模擬 LED 按鈕行為
    
    # 步驟1: 進入程式模式（長按 LED 2.5秒）
    prog_data[channel_byte] = (1 << 7) | (1 << 6)
    driver.generic_message(service=0x10, instance=instance, ...)
    time.sleep(2.5)
    
    # 步驟2: 按鈕按壓序列（按 current_amps 次）
    for press_count in range(current_amps):
        press_data[channel_byte] = (1 << channel_bit) | (1 << 7)
        driver.generic_message(...)
        time.sleep(0.5)
        
        # 釋放按鈕
        release_data[channel_byte] = (1 << 7)
        driver.generic_message(...)
        time.sleep(0.3)
    
    # 步驟3: 儲存設定（長按 LED 3秒）
    save_data[channel_byte] = (1 << channel_bit) | (1 << 7) | (1 << 6)
    driver.generic_message(...)
    time.sleep(3.0)
    
    # 步驟4: 退出程式模式
    exit_data = bytearray(data_length)
    driver.generic_message(...)
```

### 📝 技術細節

#### CAPAROC 設備特性
- 🔑 **必須模擬硬體 LED 按鈕行為**才能設定額定電流
- 🔑 **無法**透過 Implicit Messaging 的 output buffer 直接設定
- 🔑 **必須使用** `generic_message` 的 unconnected 模式
- 🔑 需要嘗試多個 Assembly Instance (0x67, 0x68, 0x69, 0x6A, 0x64)

#### 按鈕模擬時序
```
進入程式模式:  2.5 秒
按鈕按壓:      0.5 秒
按鈕釋放:      0.3 秒
儲存設定:      3.0 秒
```

### 🔧 主要修改

1. **重寫 `_set_nominal_current()` 方法**
   - 完整實作 LED 按鈕模擬流程
   - 支援多個 Assembly Instance 嘗試
   - 詳細的日誌輸出

2. **更新 `turn_on_channel()` 方法**
   - 增加 `module` 參數（預設 1）
   - 正確呼叫新的 `_set_nominal_current()`
   - 增加等待時間至 0.5 秒

3. **修正 `get_channel_current()` offset 計算**
   - 修正前: `offset = 20 + (channel-1)*2`
   - 修正後: `offset = 20 + (module-1)*16 + (channel-1)*2`

### 📖 新增文件
- **CODE_COMPARISON.md**: 測試程式 vs CLI 詳細對比分析
  - 關鍵差異說明
  - 完整流程對比
  - 問題根因分析

### 🎯 預期改善
- ✅ CLI 現在應該可以成功控制通道開關
- ✅ 額定電流設定會正確發送到設備
- ✅ 完全對齊測試程式的成功邏輯

### ⚠️ 注意事項
- 額定電流設定需要 **約 6-10 秒**（取決於電流值）
- 每次開啟通道前都會執行完整的按鈕模擬
- 如果首次設定後關閉再開啟，可能不需要重新設定額定電流

### 🧪 測試建議
```bash
# 在 Anaconda Prompt 中測試
conda activate your_env_name
cd C:\Users\harry\Project\Caparoc5
python src/caparoc_shell.py --ip 192.168.2.111

# 在 shell 中執行
> on 1    # 開啟通道 1（會執行完整的按鈕模擬）
> status  # 檢查狀態
```

---

## [2025-10-21] 修正 "Too much data" 錯誤

### 🐛 錯誤修正
- **問題**: 執行 `turn_on_channel()` 時出現 `Generic message 'generic' failed: Too much data` 錯誤
- **原因**: `_set_nominal_current()` 方法使用 `generic_message` 發送了過多資料
- **解決方案**: 改為直接透過 Implicit Messaging 的 `output_data` buffer 設定額定電流

### 📝 技術細節

#### 修正前（錯誤方法）
```python
def _set_nominal_current(self, channel: int, current_amps: int):
    config_data = bytearray(20)
    config_data[position] = int(current_amps)
    
    # ❌ 這會導致 "Too much data" 錯誤
    self.driver.generic_message(
        service=0x10,
        class_code=0x04,
        instance=self.output_instance,
        attribute=3,
        request_data=bytes(config_data),
        connected=False
    )
```

#### 修正後（正確方法）
```python
def _set_nominal_current(self, channel: int, current_amps: int):
    # ✅ 直接透過 Implicit Messaging buffer 設定
    position = 13 + (channel - 1)  # 通道 1-4 對應位置 13-16
    
    with self.io_lock:
        self.output_data[position] = int(current_amps)
    
    # I/O 執行緒會自動將資料同步到設備
```

### 🎯 關鍵概念

**Implicit Messaging 資料流**：
1. 程式修改 `output_data` buffer
2. I/O 執行緒 (20Hz) 自動將 buffer 寫入設備
3. 無需使用 `generic_message` 手動發送

**Output Data 結構**：
```
Byte 0:   [保留]
Byte 1:   控制位元 (bit0-3: 通道1-4, bit7: 啟用位元)
Byte 2-12: [其他控制]
Byte 13:  通道1 額定電流
Byte 14:  通道2 額定電流
Byte 15:  通道3 額定電流
Byte 16:  通道4 額定電流
Byte 17-19: [保留]
```

### ✨ 改進項目
- 改善錯誤處理和日誌輸出
- 增加詳細的 debug 追蹤資訊
- 即使感測器讀取失敗也能正常運作

### 📚 參考
- 測試檔案: `tests/caparoc_implicit_test.py`
- Implicit Messaging 技術說明: `docs/caparoc_implicit_test_analysis.md`

---

## [2025-10-20] 初始版本

### ✨ 新功能
- 建立 CAPAROC 斷路器控制器核心類別
- Implicit Messaging 連接管理
- 20Hz I/O 背景更新執行緒
- CLI 命令列工具
- 互動式 Shell
- 完整文件和使用指南

### 📦 模組
- `src/breaker_controller.py` - 核心控制器
- `src/caparoc_cli.py` - CLI 工具
- `src/caparoc_shell.py` - 互動式 Shell

### 📖 文件
- `docs/CLI_USER_GUIDE.md` - 使用手冊
- `docs/caparoc_implicit_test_analysis.md` - 技術分析
- `docs/TROUBLESHOOTING.md` - 疑難排解
