# CAPAROC 開發技術備忘錄

> **文件目的**: 記錄技術決策、踩坑經驗、不能做的事情
> **面向讀者**: 開發者、技術維護人員
> **補充文件**: TODO.md (功能規劃)、CHANGELOG.md (版本歷史)

**當前版本**: v3.7  
**最後更新**: 2025-11-26  
**主要開發者**: Harry Chiu



---

## ❌ 已證實無法實作的功能

### 1. Config Assembly 寫入

**結論**: **Config Assembly (0x66) 是唯讀的**

**實驗過程**:
- ✅ 可以**讀取** 244 bytes 完整資料
- ❌ **無法寫入** - 所有寫入嘗試都返回 "Too much data"
- ❌ 即使使用完整 244 bytes 讀取-修改-寫回方式也失敗

**測試記錄**:
```python
# 方法 1: Set Attribute Single (Service 0x10)
response = driver.generic_message(
    service=0x10,
    class_code=0x04,
    instance=0x66,
    attribute=3,
    request_data=bytes(244)  # 完整 244 bytes
)
# 結果: "Too much data"

# 方法 2: Set Attribute List (Service 0x03)
# 結果: "Too much data"

# 方法 3: 不同的 Attribute
# 結果: "Too much data"
```

**原因**: 設備韌體禁止運行時修改配置

---

### 2. Parameter Object 寫入

**結論**: **Parameter Object (Class 0x0F) 也是唯讀的**

**實驗過程**:
- ✅ 可以**讀取** 參數值
- ❌ **無法寫入** - 所有寫入嘗試都失敗
- ❌ 即使先解鎖 (Param1, Param2) 也無法寫入

**測試記錄**:
```python
# 嘗試 1: 寫入額定電流 (Param6, 9, 12, 15...)
response = driver.generic_message(
    service=0x10,
    class_code=0x0F,
    instance=6,
    attribute=1,
    request_data=bytes([4])  # 4A
)
# 結果: "Too much data"

# 嘗試 2: 解鎖全域鎖定 (Param1, Param2)
# 結果: "Too much data"

# 嘗試 3: 寫入 1 byte
# 結果: "Too much data"
```

**錯誤訊息**: "Too much data" (即使只寫入 1 byte!)

**結論**: 韌體級別的寫入保護

---

## 🔍 關鍵技術發現

### Assembly Instance 映射

| Instance | 類型 | 大小 | 可讀 | 可寫 | 說明 |
|----------|------|------|------|------|------|
| 0x64 (100) | Output | 18 bytes | ✅ | ✅ | 控制資料 |
| 0x65 (101) | Input | 244 bytes | ✅ | ❌ | 狀態資料 |
| 0x66 (102) | Config | 244 bytes | ✅ | ❌ | 配置資料（唯讀）|

### Output Assembly 結構 (Byte 0-17, 共 18 bytes)

```
Byte 0:   [Main Power]
  bit 7: Release (1=正常操作)
  bit 0: Main power (1=開, 0=關)
  
Byte 1:   [CH1-4 控制]
  bit 7: Release (1=正常操作)
  bit 3: CH4 (1=開, 0=關)
  bit 2: CH3 (1=開, 0=關)
  bit 1: CH2 (1=開, 0=關)
  bit 0: CH1 (1=開, 0=關)

Byte 2-17: 保留/其他模組
```

### Input Assembly 結構 (Byte 0-243, 共 244 bytes)

```
Byte 0:   全域狀態
  bit 0: Undervoltage (欠壓)
  bit 1: Overvoltage (過壓)
  bit 2: System error (系統錯誤)
  bit 3: 80% warning (80%警告)
  bit 4: Total shutdown (總電流關斷)
  bit 7: Config processing (配置處理中)

Byte 1:   模組數量 (0-16)

Byte 2-3: 總電流 (little-endian, 單位 0.1A)
          例如: 0x0066 = 102 = 10.2A

Byte 4-5: 系統電壓 (little-endian, 單位 0.01V)
          例如: 0x0960 = 2400 = 24.00V

Byte 6+:  通道狀態 (每個通道 3 bytes)
  Byte 0: 狀態
    bit 0: Channel status (1=開, 0=關)
    bit 1: 80% warning
    bit 2: Overload tripping (過載)
    bit 3: Short-circuit tripping (短路)
    bit 4: Hardware fault (硬體故障)
    bit 5: Total current shutdown (總電流關斷)
  Byte 1: 額定電流 (1-20A)
  Byte 2: 實際電流 (0.1A 單位, 0-255 = 0.0-25.5A)

模組 1 通道偏移:
  CH1: Byte 6-8
  CH2: Byte 9-11
  CH3: Byte 12-14
  CH4: Byte 15-17

模組 2 通道偏移:
  CH1: Byte 18-20
  CH2: Byte 21-23
  ...
```

---

## 🚫 已放棄的方法

### 1. LED 按鈕模擬

**原理**: 模擬設備前面板的 LED 按鈕操作

**流程**:
1. 寫入 "進入程式模式" (bit 6+7)
2. 模擬按鈕按壓 N 次（設定 N A）
3. 寫入 "儲存" (bit 6+7 + 通道 bit)
4. 退出程式模式

**問題**:
- ❌ 設備不響應 LED 按鈕模擬命令
- ❌ 即使嘗試多個 Assembly Instance (0x67-0x6A, 0x64) 都失敗
- ❌ 可能需要特殊的時序或設備必須處於特定模式

**結論**: 放棄此方法

---

### 2. Implicit Messaging

**原理**: 建立 Forward Open 連接，使用 I/O 模式通訊

**問題**:
- ⚠️ CAPAROC 設備不支援 Forward Open
- ⚠️ 僅支援 Explicit Messaging (Unconnected Send)

**結論**: 
- 程式中保留嘗試邏輯（靜默失敗）
- 實際使用 Explicit Messaging (`generic_message`)

---

### 3. Config Processing 監測（`_wait_for_config_processing`）

**原理**: 監測 Input Assembly Byte 0 Bit 7，等待設備完成配置處理後再驗證。

**問題**:
- ❌ 監測等待耗時最多 5 秒（太慢）
- ❌ 實測發現 Config Assembly 寫入後設備幾乎是即時應用的，Bit 7 根本不會被設為 1

**結論**: 方法仍保留在代碼中（`_wait_for_config_processing()`）備用，但 `set_nominal_current` 改為直接 `sleep(0.5)` + 輪詢驗證（最多 3 秒），實測 0.5s 內即可確認。

---

### 4. CIP Class 0xF5 寫入 IP（`set_device_ip` 初版）

**原理**: 透過 CIP TCP/IP Interface Object（Class 0xF5）寫入設備 IP：
1. Set_Attribute_Single Attr 3 = `0x00`（強制 Static IP 模式）
2. Set_Attribute_Single Attr 5（IP + Subnet + Gateway + NS + DomainName）

**問題**:
- ❌ Attr 5 讀取無回應（`read_device_network_config` 回傳「Attr 5 無回應」）
- ❌ 設備不支援 CIP Class 0xF5 的標準 Get/Set，嘗試 Attr 1/3/5 均失敗
- ❌ 原廠確認 CAPAROC 設備不透過 CIP 管理 IP，需改用 PROFINET DCP 協議

**結論**: 放棄 CIP 0xF5 方案，改用 PROFINET DCP Layer 2 封包（`scapy` 實作）。現有程式碼（`set_device_ip()`、`read_device_network_config()`）將保留簽名、改寫函式體，不影響 CLI 呼叫層。

---

## ✅ 成功的解決方案

### 額定電流設定

**最終方案**: **手動設定 + 程式驗證**

1. **設定步驟（在設備上）**:
   - 長按 PWR 鍵 3 秒（解鎖）
   - 短按通道按鈕進入編程模式
   - 按 +/- 調整電流值
   - 短按通道按鈕確認
   - 長按 PWR 鍵 3 秒退出

2. **程式驗證**:
   ```bash
   > verify 2
   ✅ CH2 額定電流: 4A
   ```

3. **程式中的 `init` 命令**:
   - **不會**自動設定電流
   - **僅顯示**手動設定指引
   - 這是最實用的方式

---

## 📊 重要數據結構

### 通道偏移計算公式

```python
def get_channel_offset(module, channel):
    """
    Args:
        module: 1-16
        channel: 1-4
    
    Returns:
        Input Assembly 中的 byte 偏移
    """
    global_bytes = 6
    bytes_per_module = 12
    bytes_per_channel = 3
    
    module_offset = global_bytes + (module - 1) * bytes_per_module
    channel_offset = module_offset + (channel - 1) * bytes_per_channel
    
    return channel_offset

# 範例:
# M1.CH1: 6 + 0*12 + 0*3 = 6
# M1.CH4: 6 + 0*12 + 3*3 = 15
# M2.CH1: 6 + 1*12 + 0*3 = 18
```

---

## 🛠️ 開發工具

### check_connection.py

**功能**: 自動診斷連接問題

**檢查項目**:
1. Ping 測試
2. Port 44818 連通性
3. pycomm3 安裝
4. CIP 連接測試

**使用**:
```bash
python check_connection.py
```

---

## 📝 文件結構

```
Caparoc_breaker_control/
├── README.md                           # 專案概述
├── INTERACTIVE_TEST_GUIDE.md           # 互動測試指南
├── check_connection.py                 # 連接診斷工具
├── src/
│   └── caparoc_controller.py           # 主程式 (2438 行)
├── docs/
│   ├── MAIN_POWER_CONTROL.md           # 主開關技術細節
│   ├── TROUBLESHOOTING_CONNECTION.md   # 連接問題排查
│   ├── DEVELOPMENT_NOTES.md            # 本文件
│   ├── CHANGELOG.md                    # 版本歷史
│   └── TODO.md                         # 待辦事項
└── tests/                              # 測試
```

---

## 🏗️ 現行架構（2026-04-02 重構，2026-04-27 更新）

> 重構過程與動機詳見 `CHANGELOG.md` Phase 3.5 條目。

### 模組結構

```
src/
├── caparoc_backend.py     ← CaparocBackend（裝置邏輯，~1250 行，27 個方法）
├── caparoc_controller.py  ← CaparocController(CaparocBackend)（CLI 包裝層）
├── caparoc_web.py         ← 未來：Dash Web 服務（長駐，瀏覽器控制）
└── logging_manager.py     ← 日誌管理
```

**繼承關係**：`CaparocController → CaparocBackend → object`

**職責分工**：

| 類別 | 職責 | 可被使用 |
|------|------|----------|
| `CaparocBackend` | 裝置通訊、狀態讀取、通道控制、監控 | CLI + 未來 GUI |
| `CaparocController` | CLI 命令迴圈、IP 設定互動、幫助文字 | 僅 CLI |

CLI 專屬方法：`_show_help_message()`、`_configure_device_ip()`、`_validate_ip()`、`run()`

### 現行問題：controller.py 仍有冗餘方法（待清除）

`caparoc_controller.py` 目前仍保留所有後端方法的完整複本（約 1500 行 shadow 方法），為過渡期安全備份，尚未執行清除。

```
caparoc_controller.py 現況（2026-04-27）
  ├── __init__                ← 重複初始化（會覆寫父類）
  ├── get_channel_offset      ← shadow（與 CaparocBackend 完全相同）
  ├── get_total_channels      ← shadow
  ├── ... (約 20 個 shadow 方法)
  ├── _show_help_message      ← CLI 專屬 ✅
  ├── _configure_device_ip   ← CLI 專屬 ✅
  ├── _validate_ip            ← CLI 專屬 ✅
  └── run()                   ← CLI 專屬 ✅
總行數：~2100 行，其中 ~1500 行是冗餘複本
```

**Phase 3.6.2 清除目標**：刪除所有 shadow 方法，目標縮減至 ~250 行。  
**清除前必做**：確認 controller 中的 `set_nominal_current`、`set_channel`、`show_status` 版本與 backend 一致（已確認）。

### 目標架構（Phase 3.6 完成後）

```python
# caparoc_web.py（未來）
from caparoc_backend import CaparocBackend
import dash

backend = CaparocBackend("192.168.2.111")
# 直接使用 backend，不透過 CaparocController
```

### GUI 架構決策

| 決策項目 | 選擇 | 理由 |
|----------|------|------|
| GUI 類型 | Browser-based | 手機/任何裝置皆可控制 |
| 框架 | Dash (Plotly) | 純 Python、內建即時更新、無需 HTML/JS |
| 連線模式 | 服務啟動自動連線 | CAPAROC 一直在線，無需手動連線 |
| 服務入口 | `python caparoc_web.py` | 啟動後瀏覽器開 `localhost:8050` |

### GUI 前尚未完成的工作（見 TODO Phase 3.6）

1. **`connect()` / `disconnect()` 實作**（最重要）— 連線生命週期目前綁定在 CLI `with CIPDriver(...) as driver:` 內，Web 服務無法長駐
2. **controller.py 冗餘方法清除** — 約 1500 行重複邏輯（Phase 3.6.2）
3. **設備 IP 硬寫（PROFINET DCP）** — 暫緩（需 Npcap 驅動，影響可攜性）；連線 IP 管理已完成（Phase 3.6.3 部分完成）
4. **Dash 安裝與骨架驗證** — `pip install dash` + 最小可用頁面（Phase 3.6.4）

---

## 🔮 未來改進方向

### 優先級 1: GUI 前置工作（Phase 3.6，立即執行）

- [ ] `CaparocBackend.connect()` / `disconnect()` 實作
- [ ] `caparoc_controller.py` 冗餘方法清除
- [ ] Dash 安裝與基本骨架驗證

### 優先級 2: Browser GUI 開發（Dash）

- [ ] 通道控制面板（開關按鈕 + 即時電流顯示）
- [ ] 系統狀態儀表板（電壓、總電流、全域狀態）
- [ ] 即時監控整合（`dcc.Interval` 定時更新）
- [ ] Log 面板顯示

### 優先級 3: 通道資訊擴展

- [ ] 顯示通道歷史電流曲線
- [ ] 記錄通道開關歷史
- [ ] 通道使用統計

---

## 🔧 暫緩的技術方案

### Phase 3.6.3：PROFINET DCP 寫入設備 IP（scapy 方案）

> **⏸️ 狀態：暫緩開發（2026-05-12）**
>
> **暫緩原因**：
> - Windows 上 scapy Layer 2 raw frame 需要 **Npcap 驅動**（獨立安裝），無法內嵌於 Python 打包
> - Npcap OEM（可靜默安裝）需付費授權
> - 影響程式可攜性：打包後的工具需要使用者額外安裝系統驅動
>
> **目前已完成的探索（保留供日後參考）**：
> - `tests/test_scapy_dcp.py`：診斷腳本，已確認 scapy 2.7.0 可在 sv 環境安裝
> - 設備 MAC 可取得（`cc:cc:ea:8b:5f:18`），ping / ARP 正常
> - DCP Identify 廣播因缺 Npcap 未能測試，設備是否回應 DCP 尚未確認
>
> **替代方案建議**：使用 Phoenix Contact 官方工具 **PRONETA Basic**（免費）設定設備 IP。
> `setting [2]` CLI 選項改為顯示導向說明，不實際寫入。

**背景**: CIP Class 0xF5 實測不可用，原廠建議改用 scapy 發送 PROFINET DCP 封包（Layer 2 Ethernet）。

#### 為何 PROFINET DCP 可行

Phoenix Contact 的 PRONETA / IP Address Wizard 工具即使用此方式，不依賴 TCP/IP 層，直接透過 Ethernet frame 操作設備網路設定。CAPAROC 雖作為 EtherNet/IP 設備，但 Phoenix Contact 硬體通常同時支援 PROFINET DCP 的 IP 設定命令（Layer 2）。

#### 協定結構（PROFINET DCP Set Request）

```
Ethernet Frame:
  dst_mac : 設備 MAC（unicast）
  src_mac : 本機 MAC（scapy 自動填入）
  type    : 0x8892（PROFINET RT）

PROFINET RT Header:
  frame_id: 0xFEFD（DCP unicast request）

DCP Header:
  service_id      : 0x04（Set）
  service_type    : 0x00（Request）
  xid             : 4 bytes（任意 transaction ID）
  response_delay  : 0x0000
  dcp_data_length : 總 block 長度

DCP Block (IP Suite):
  option          : 0x01（IP）
  sub_option      : 0x02（IP Suite）
  block_length    : 14（2+4+4+4）
  block_qualifier : 0x0001（永久儲存）
  ip_addr         : 4 bytes
  subnet          : 4 bytes
  gateway         : 4 bytes
```

#### 程式碼修改計畫（最小範圍）

**僅修改 `caparoc_backend.py`，`caparoc_controller.py` 完全不動。**

| 方法 | 修改內容 |
|------|----------|
| `set_device_ip()` | 函數體完全改寫：移除 CIP 0xF5 邏輯，改用 scapy 發送 DCP Set 封包；簽名不變 |
| `read_device_network_config()` | 新增 fallback：CIP 失敗時改用 scapy 發送 DCP Identify（FrameID 0xFEFF）或回傳已知 `self.device_ip` |
| `_get_mac_address(ip)` | 新增私有 helper：ping 一次後解析 `arp -a` 取得 MAC |

**`set_device_ip()` 新邏輯流程：**
```
1. _get_mac_address(self.device_ip) → 取得設備 MAC
2. 組裝 PROFINET DCP Set Request Ethernet frame（scapy）
3. sendp(frame, iface=None, verbose=False)  ← scapy 發送
4. 等待 ~1 秒（設備套用設定）
5. 回傳 {'success': True/False, 'error': ...}
```

**`read_device_network_config()` 新邏輯流程：**
```
1. 先嘗試 CIP Attr 1/3/5（保留現有邏輯）
2. 若 Attr 5 失敗 → 改送 DCP Identify Request（廣播，FrameID 0xFEFF）
   - 解析回應中的 IP Suite block
3. 若 DCP 也失敗 → 至少回傳 {'ip': self.device_ip, 'success': False, 'error': ...}
```

#### 相依套件

```bash
pip install scapy
```

⚠️ **Windows 需要管理員身份執行**（scapy 使用 raw socket）。  
✅ 若無管理員權限，`set_device_ip()` 應捕捉 PermissionError 並回傳明確錯誤訊息。

#### 預期風險

| 風險 | 處置 |
|------|------|
| CAPAROC 不回應 DCP Set | 記錄為「已知限制」，建議使用者改用 PRONETA |
| Windows 無管理員權限 | 程式捕捉 PermissionError，提示需以管理員身份執行 |
| scapy 未安裝 | try/except ImportError，回傳明確錯誤訊息 |
| 寫錯 IP 導致斷線無法恢復 | 雙重確認（已在 controller CLI 層實作） |

---

## �💡 關鍵經驗教訓

### 1. Config Assembly 的誤解

**原始認知**: PDF 手冊 Table 7-11 標示 "Read and write"

**實際情況**: 
- ✅ 可以讀取 (Read)
- ❌ 無法寫入 (Write)
- 手冊可能指"出廠時可寫入"，但運行時唯讀

**教訓**: 
- 不要完全依賴文件
- 實際測試是最可靠的
- "Too much data" 錯誤可能表示"拒絕寫入"

---

### 2. 錯誤訊息的誤導

**錯誤**: "Too much data"

**最初理解**: 資料太大，需要分段寫入

**實際原因**: 設備拒絕寫入（權限問題）

**證據**:
- 寫入 1 byte 也返回 "Too much data"
- 寫入 244 bytes 也返回 "Too much data"
- 不是大小問題，是**權限**問題

**教訓**: 
- 錯誤訊息可能不準確
- 需要多角度測試
- pycomm3 的錯誤訊息映射可能不完整

---

### 3. 專家建議的局限

**專家說**: "Config Assembly 絕對可以寫入"

**實際測試**: 完全無法寫入

**可能原因**:
- 專家經驗來自不同版本韌體
- 專家指的是"理論上可以"
- 專家使用了不同的設定工具（非 EtherNet/IP）

**教訓**:
- 專家建議是參考，不是絕對
- 始終以實際測試為準
- 記錄所有測試結果

---

### 4. 簡化優於複雜

**原始設計**: 
- 多個範例文件
- 複雜的文件結構
- 分散的功能

**最終設計**:
- 單一主程式
- 整合的互動介面
- 清晰的文件

**教訓**:
- 用戶需要簡單直接的工具
- 整合優於分散
- 文件要反映實際使用方式

---

## 📞 技術支援資訊

### 設備資訊

- **型號**: CAPAROC PM (EtherNet/IP)
- **通訊**: EtherNet/IP (Port 44818)
- **支援模組**: 1-16 個（每個 4 通道）
- **電流範圍**: 1-20A（標稱），0-25.5A（實際）

### 已知問題

1. **Config Assembly 唯讀** - 無法透過網路修改配置
2. **Parameter Object 唯讀** - 額定電流必須手動設定
3. **No Implicit Messaging** - 僅支援 Explicit Messaging

### 聯絡方式

- **開發者**: Harry Chiu
- **GitHub**: cFuuu/Caparoc_breaker_control
- **問題回報**: GitHub Issues

---

**文件版本**: 2.1  
**建立日期**: 2025-10-29  
**最後更新**: 2026-04-27  
**適用程式版本**: v3.7（Phase 3.5 架構）
