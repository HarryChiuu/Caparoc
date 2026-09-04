# CAPAROC 開發技術備忘錄

> **文件目的**: 記錄技術決策、踩坑經驗、不能做的事情
> **面向讀者**: 開發者、技術維護人員
> **補充文件**: TODO.md (功能規劃)、CHANGELOG.md (版本歷史)

**當前版本**: v4.2  
**最後更新**: 2026-08-04  
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

**結論**: 方法仍保留在程式碼中（`_wait_for_config_processing()`）備用，但 `set_nominal_current` 改為直接 `sleep(0.5)` + 輪詢驗證（最多 3 秒），實測 0.5s 內即可確認。

---

### 4. CIP Class 0xF5 寫入 IP（初版錯誤結論 → 已修正）

> ⚠️ **此條目為舊有錯誤紀錄，CIP 0xF5 實際可用，詳見下方「IP 設定成功解決方案」**

舊結論（已作廢）：Attr5 無回應、設備不支援 CIP 0xF5、需用 PROFINET DCP。  
實際原因：unconnected 模式在此設備無效，改用 `connected=True` 後讀寫均成功。

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

### IP 設定（CIP Class 0xF5）

**開發日期**: 2026-08-04  
**分支**: `feature/ip-config-dhcp`  
**相關檔案**: `src/caparoc_backend.py`、`tests/manual/check_ip_config.py`

#### 背景

從 Wireshark 捕獲已知工具（PRONETA）對設備進行 DHCP 切換的封包，逆向分析出 CIP 通訊協議後，以程式實作相同功能。

#### 最終實作方案

**修改靜態 IP**（`set_device_ip()`）：
1. 寫入 Attr 5（IP/Subnet/Gateway）— `connected=True`
2. 寫入 Attr 3 = `0x00000000`（Static 模式）— 設備 IP 改變後連線中斷，此步例外視為成功

**切換 DHCP**（`set_device_dhcp()`）：
1. 寫入 Attr 3 = `0x00000002`（DHCP 模式）— 設備立即 RST 並發出 DHCP Discover

#### 試錯過程

**試錯 1：unconnected vs connected 模式**

```python
# 初版：connected=False（unconnected messaging）
driver.generic_message(..., connected=False)
# 結果：(no resp) — 讀寫均無回應，但不丟例外
# 誤以為失敗，實際上寫入「有時有效」（取決於 pycomm3 行為）

# 修正：connected=True（connected explicit messaging）
driver.generic_message(..., connected=True)
# 結果：正常讀寫，有正確回應
```

**試錯 2：IP bytes 字節序（Byte Order）**

讀取 Attr 5 後發現 IP 顯示為 `221.50.168.192`（倒序），原因：

> CIP 以 **Little-Endian UDINT** 儲存 IP 位址。
> `socket.inet_ntoa()` 期望 Big-Endian（網路位元組序），需先反轉。

```python
# 錯誤：直接 inet_ntoa
socket.inet_ntoa(raw[0:4])          # → 221.50.168.192 ❌

# 正確：反轉後 inet_ntoa
socket.inet_ntoa(raw[0:4][::-1])    # → 192.168.50.221 ✅

# 寫入時同樣反轉
socket.inet_aton("192.168.50.111")[::-1]   # Big→LE
```

**試錯 3：寫入成功但回報失敗（`failed to send message`）**

第一次使用 `connected=True` 時，Attr 5 寫入成功 → 設備 IP 立即改變 → 連線中斷 → Attr 3 第二次寫入拋出 `failed to send message` → 程式誤判為失敗。

解法：Attr 5 寫入成功後先設 `result['success'] = True`，後續連線中斷的例外以 `pass` 略過。

**試錯 4：寫入順序**

初版順序：Attr 3（切 Static）→ Attr 5（寫 IP）  
問題：設備可能在 Attr 3 切換時套用舊 Attr 5，忽略後續寫入。

修正順序：**Attr 5（寫 IP）→ Attr 3（觸發切換）**

#### 關鍵 Wireshark 觀察

| 操作 | 連線關閉方式 | 後續行為 |
|---|---|---|
| 修改靜態 IP | FIN,ACK（正常關閉） | ARP Probe × 4 → ARP Announcement → 新 IP 可連 |
| 切換 DHCP | RST,ACK（強制重置） | DHCP Discover → Offer → ACK |

ARP Probe 序列（修改靜態 IP 後設備自動執行）：
```
PhoenixConta → Broadcast  ARP Probe "Who has 192.168.50.111?" × 4
PhoenixConta → Broadcast  ARP Announcement for 192.168.50.111  × 2
```

#### 待實作

- [ ] DHCP → 靜態 IP 切換（目前寫入後設備行為待驗證）
- [ ] 整合進主程式 CLI（`setting [4]` 選單）

---

### 主機名稱（CIP Class 0xF5 Attr 6）

**開發日期**: 2026-09-04
**相關檔案**: `src/caparoc_backend.py`、`tests/manual/check_hostname.py`、`tests/test_hostname.py`

#### 名稱存在 Attr 6，不是 Attr 5

實機讀取（192.168.50.111）：

```
Attr 5 raw: 6F 32 A8 C0 00 FE FF FF 01 32 A8 C0 00 00 00 00 00 00 00 00 00 00
            └ IP ──────┘└ Subnet ─┘└ Gateway ┘└ DNS1 ───┘└ DNS2 ───┘└ 00 00
                                                                       ↑ Domain Name 長度前綴 = 0（空）
Attr 6 raw: 08 00 63 61 70 61 72 6F 63 31
            └len=8┘└─ "caparoc1" ───────┘
```

`get_network_info()` 是「Attr 5 的 Domain Name 優先、空的才退回 Attr 6」，
所以畫面上的值實際來自 **Attr 6**。

#### ⚠️ 兩者風險等級差很多，改名務必走 Attr 6

| | Attr 5 | Attr 6 |
|---|---|---|
| 內容 | **整包** IP / 遮罩 / 閘道 / DNS / Domain Name | 單一 CIP STRING |
| 改法 | read-modify-write 整包回寫 | 直接寫 |
| 寫錯的後果 | **連 IP 一起改掉，設備失聯** | 只是名字不對 |

Attr 5 與 `set_device_ip()` 是同一個 attribute。`test_set_hostname_never_touches_attr5`
就是守這條界線的，動這塊程式時不要拿掉。

#### CIP STRING 格式

2-byte LE UINT 長度前綴 + ASCII chars（**不是** IP 那種 LE-UDINT，別混用）。
長度 0 為合法值，等於清除名稱。

#### 寫入行為（實機驗證）

**Attr 6 立即生效，不需要重啟設備。** 寫入後回讀即為新值，重新整理頁面
設備上仍是新名稱。

`set_device_hostname()` 仍保留「回讀到舊值 → `applied=False`（需重啟）」的分支：
EDS 未載明此行為，不能假設所有韌體版本都一樣。該分支在本機從未被觸發過。

與改 IP 不同，改名**不會**造成連線中斷，因此可以安心等回應、也能安心回讀驗證——
不需要 `set_device_ip()` 那套「例外即視為成功」的特殊處理。

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

## 🏗️ 現行架構（2026-05-25 更新）

> 重構過程與動機詳見 `CHANGELOG.md` Phase 3.5 條目。

### 模組結構

```
src/
├── caparoc_backend.py     ← CaparocBackend（裝置邏輯，~750 行）
├── caparoc_controller.py  ← CaparocController(CaparocBackend)（CLI 包裝層，~874 行）
└── logging_manager.py     ← 日誌管理

web/
├── app.py                 ← FastAPI 服務（~550 行）
├── templates/index.html   ← Vue 3 CDN 頁面（~600 行）
└── static/
    ├── js/app.js          ← Vue 3 應用邏輯（~900 行）
    └── css/style.css      ← 樣式
```

**繼承關係**：`CaparocController → CaparocBackend → object`

**職責分工**：

| 類別 | 職責 | 可被使用 |
|------|------|----------|
| `CaparocBackend` | 裝置通訊、狀態讀取、通道控制、監控 | CLI + Web UI |
| `CaparocController` | CLI 命令迴圈、IP 設定互動、幫助文字 | 僅 CLI |
| `web/app.py` | FastAPI 路由、WebSocket、內容樣板 | 僅 Web UI |

CLI 專屬方法：`_show_help_message()`、`_configure_device_ip()`、`_validate_ip()`、`run()`

> Phase 3.6.2（2026-05-14）：`caparoc_controller.py` 已將全部 shadow 方法刪除，從 2387 行減少至 874 行（-63%）。

---

## 🔮 未來改進方向

### 優先級 1: Web UI 完善（Phase 4.3）

- [ ] 設定值外部化（`config.yaml`）
- [ ] 視覺一致性與元件統一化
- [ ] 行動裝置基本支援

### 優先級 2: CLI 功能補齊（Phase 4.4）

- [ ] `device info` 指令（`get_device_info()`）
- [ ] `network info` 指令（`get_network_info()`）
- [ ] `show channel <n>` 詳細資訊（`show_channel_detail()`）

### 優先級 3: 多設備管理（Phase 4.5）

- [ ] 支援多個 CAPAROC 設備同時連線
- [ ] Web UI 設備切換介面

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
> - `tests/manual/check_scapy_dcp.py`：診斷腳本，已確認 scapy 2.7.0 可在 sv 環境安裝
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

**文件版本**: 2.2  
**建立日期**: 2025-10-29  
**最後更新**: 2026-05-25  
**適用程式版本**: v4.2（Phase 4.2 架構）

---

## 2026-05-18 ── Web UI 開發踩坑：編碼、渲染與快取問題

## 2026-05-18 ── Web UI 編碼與渲染問題紀錄

### 問題一：`index.html` 中文亂碼

**現象**：VS Code 打開 `web/templates/index.html`，所有中文字變成亂碼（如 `?批??`、`撌脤??`）。

**根本原因**：PowerShell 5.x 的 `Get-Content` 在繁體中文 Windows 下，預設使用系統編碼 **CP950（Big5）** 讀取檔案，而非 UTF-8。

```powershell
# ❌ 錯誤做法：Get-Content 用 CP950 讀 UTF-8，中文字節被錯誤解讀
$lines = Get-Content "web\templates\index.html"
$lines[0..178] | Set-Content "web\templates\index.html" -Encoding UTF8
```

執行後，UTF-8 的中文字節被當成 Big5 解讀，再寫回 UTF-8 時變成雙重編碼錯誤。

**解決方法**：凡需要截斷或處理含中文的 UTF-8 檔案，一律改用 Python：

```python
# ✓ 正確做法
import pathlib

out = pathlib.Path("web/templates/index.html")
out.write_text(correct_content, encoding="utf-8")  # Python 預設 UTF-8，無 BOM
```

或 PowerShell 明確指定編碼：

```powershell
# ✓ PowerShell 正確做法
Get-Content "file.html" -Encoding UTF8 | Select-Object -First 179 |
    Set-Content "file.html" -Encoding UTF8
```

---

### 問題二：UTF-8 BOM（EF BB BF）導致 JS 解析失敗

**現象**：網頁白屏、Vue app 無法載入。

**根本原因**：PowerShell 5.x 的 `Set-Content -Encoding UTF8` 會自動在檔案開頭寫入 **UTF-8 BOM（EF BB BF）**。雖然 HTML 允許 BOM，但放在 JavaScript 檔案開頭會干擾部分環境的解析。

```powershell
# ❌ 加 BOM
Set-Content -Path "app.js" -Value $content -Encoding UTF8
```

**解決方法**：用 Python 的 `utf-8-sig` codec 讀取並移除 BOM，再以 `utf-8` 寫回：

```python
import codecs

with codecs.open("app.js", "r", "utf-8-sig") as f:
    content = f.read()
with codecs.open("app.js", "w", "utf-8") as f:
    f.write(content)
```

PowerShell 寫無 BOM 的 UTF-8 正確方法：

```powershell
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($path, $content, $utf8NoBom)
```

---

### 問題三：`index.html` 殘留舊 HTML，Vue 雙重 mount

**現象**：頁面載入後，新版 sidebar 導覽列不顯示，內容渲染異常。

**根本原因**：在修改 `index.html` 時，舊版內容沒有被完全移除，導致正確的 `</html>` 之後還有舊版的 HTML 片段，其中包含**第二組** `<script src="vue...">` 和 `<script src="app.js">` 標籤。瀏覽器繼續解析這些 script，Vue 被載入兩次，第二個 `createApp().mount('#app')` 覆蓋了第一個，所有 reactive 狀態與事件綁定失效。

**解決方法**：確保 `index.html` 只有一組 `<script>` 標籤。截斷操作需精確到第一個 `</html>` 為止：

```python
lines = pathlib.Path("index.html").read_text(encoding="utf-8").splitlines()
end = next(i for i, l in enumerate(lines) if l.strip() == "</html>")
pathlib.Path("index.html").write_text("\n".join(lines[:end+1]) + "\n", encoding="utf-8")
```

---

### 問題四：瀏覽器快取舊版 CSS / JS

**現象**：伺服器已回傳新版 HTML，但樣式與行為仍是舊版。

**根本原因**：`StaticFiles` 會設定 `ETag` 與 `Last-Modified`，瀏覽器根據這些 header 快取靜態資源。更新檔案但不重整時，瀏覽器繼續使用快取版本。

**解決方法**：

1. 對主頁路由加入 `Cache-Control: no-cache`（已套用至 `app.py`）：
   ```python
   resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
   ```

2. 在 HTML 中對靜態資源加入版本查詢參數（cache busting）：
   ```html
   <link rel="stylesheet" href="/static/css/style.css?v=4.2.2" />
   <script src="/static/js/app.js?v=4.2.2"></script>
   ```

3. 緊急處理：瀏覽器按 `Ctrl+Shift+R` 強制重整（繞過快取）。

---

### 通用規範（後續開發）

| 操作 | ❌ 避免 | ✓ 使用 |
|------|---------|--------|
| 寫含中文的 UTF-8 檔案 | PowerShell `Set-Content -Encoding UTF8` | Python `Path.write_text(encoding="utf-8")` |
| 讀含中文的 UTF-8 檔案 | PowerShell `Get-Content`（不帶參數） | Python `open(encoding="utf-8")` 或 PowerShell `Get-Content -Encoding UTF8` |
| 移除 BOM | 直接截斷 | Python `codecs.open('utf-8-sig')` 讀取再 `'utf-8'` 寫回 |
| 靜態資源更新後快取 | 不處理 | 更新 `?v=X.X.X` 版本參數 |

---

## 2026-05-18 ── Web UI 系統日誌頁（4.2.3）：架構設計與問題排查

### 背景

Task 4.2.3 實作「系統日誌頁」，讓使用者在網頁上查看 backend 運作日誌，取代需要開終端機的問題。

---

### 問題：網頁日誌頁顯示空白

#### 症狀

- .log 檔（`logs/caparoc_YYYY-MM-DD.log`）確實有記錄
- 網頁上「系統日誌」頁顯示「目前無日誌記錄」

#### 根本原因

In-memory buffer（`_LOG_BUFFER: deque`）**只從 web server 啟動那一刻開始收集**。

- server 啟動前的歷史記錄不在 buffer 中
- 若連線失敗，啟動後幾秒內 buffer 幾乎是空的
- 使用者一進去就看到空白屬於正常現象，但體驗不佳

#### 設計選擇

| 方案 | 說明 | 缺點 |
|------|------|------|
| 只用 in-memory | 即時收集，快速 | 重啟後歷史消失，初次進去是空的 |
| 每次讀 .log 檔 | 有完整歷史 | 每次 request 都 file I/O + 解析格式 |
| **混合（採用）** | 啟動時一次性預載 → 後續即時收集 | 多一點啟動時間（可忽略） |

#### 解法：啟動時預載 .log 檔

```python
def _preload_log_file(max_lines: int = 400) -> None:
    today = date.today().strftime("%Y-%m-%d")
    log_path = ROOT_DIR / "logs" / f"caparoc_{today}.log"
    if not log_path.exists():
        return
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-max_lines:]:   # 只取最後 400 行
        m = _LOG_LINE_RE.match(line)  # 解析 "2026-05-18 14:30:00 [INFO] [SYS] msg"
        if m:
            _LOG_BUFFER.append({...})
```

**關鍵時序**：`_preload_log_file()` 必須在 `addHandler` **前**呼叫，否則預載的記錄會被 `_CaparocLogHandler.emit()` 重複寫入。

---

### 問題：CLI 與 WEB 啟動 log 無法區分

#### 症狀

.log 檔裡的連線相關記錄無法判斷是 CLI 啟動還是 Web 服務啟動。

#### 原因

`_WEB_LOGGER.log(...)` 呼叫未帶 `extra={'log_module': ...}`，導致格式化後顯示 `[---]`。

```
# 修改前
2026-05-18 10:00:00 [SYSTEM] [---] Web 服務啟動，嘗試連線至 192.168.50.111...
2026-05-18 10:00:01 [INFO]   [CONN] 連線成功: 192.168.50.111, 2 模組...
2026-05-18 10:30:00 [INFO]   [SYS]  CAPAROC PM EIP Controller v3.8 啟動    ← [SYS] 看不出是 CLI
```

#### 解法

| 程式 | 舊標籤 | 新標籤 | 說明 |
|------|--------|--------|------|
| `web/app.py` 所有 `_WEB_LOGGER` | 無（顯示 `[---]`） | `WEB` | Web 服務生命週期事件 |
| `caparoc_controller.py` 啟動訊息 | `SYS` | `CLI` | CLI 程式啟動標記 |

修改後的 .log 記錄：
```
# 修改後
2026-05-18 10:00:00 [SYSTEM] [WEB]  Web 服務啟動，嘗試連線至 192.168.50.111...
2026-05-18 10:00:01 [INFO]   [CONN] 連線成功: 192.168.50.111, 2 模組...    ← 後端共用，CLI/WEB 都會出現
2026-05-18 10:00:01 [SYSTEM] [WEB]  設備連線成功 (192.168.50.111)           ← WEB 確認
...
2026-05-18 10:30:00 [INFO]   [CLI]  CAPAROC PM EIP Controller v3.8 啟動    ← CLI 明確標記
2026-05-18 10:30:01 [INFO]   [CONN] 連線成功: 192.168.50.111, 2 模組...
```

---

### Log Module 標籤慣例

| `log_module` | 意義 | 出處 |
|---|---|---|
| `CLI`  | CLI 程式生命週期 | `caparoc_controller.py` |
| `WEB`  | Web 服務生命週期（啟動、手動連線/斷線） | `web/app.py` |
| `CONN` | 設備連線/斷線操作（CLI 與 WEB 共用） | `caparoc_backend.py` |
| `CTRL` | 通道開關操作 | `caparoc_backend.py` |
| `INIT` | 額定電流初始化 | `caparoc_backend.py` |
| `SETTING` | IP 設定變更 | `caparoc_controller.py` |
| `SYS` | 系統層級（log 啟動訊息等） | `logging_manager.py` |

---

### Web Log API 設計

```
GET  /api/logs?level=all|warn|error&limit=N&offset=N
POST /api/logs/clear
```

- buffer 大小：`deque(maxlen=500)`（400 預載 + 100 即時）
- 最新在前（server 端 `.reverse()`）
- 自訂等級 `SYSTEM = 25`（介於 INFO=20 與 WARNING=30 之間），用於服務生命週期事件

---

## 🔐 Phase 4.x 技術備忘（2026-05-25）

### 1. CIPDriver 非 thread-safe — `_cip_lock` 設計

**問題**：pycomm3 `CIPDriver.generic_message()` 非 thread-safe。
FastAPI 使用 `asyncio.to_thread()` 時，WebSocket 推送和 HTTP API 請求可能同時呼叫
`generic_message()`，導致 TCP 串流損壞、連線斷開（symptoms：`StaleError` / 靜默掛住）。

**修正**（commit b779752）：`self._cip_lock = threading.Lock()`

```python
# get_network_info()、get_device_info()：每個 _rd() 呼叫都持鎖
def _rd(self, class_id, instance, attr):
    with self._cip_lock:
        return self.driver.generic_message(...)

# _read_current_status()：允許逾時讓出，不阻塞 WebSocket 推送
def _read_current_status(self):
    if not self._cip_lock.acquire(timeout=2.0):
        return self._last_known_status   # 逾時直接回傳舊值
    try:
        ...
    finally:
        self._cip_lock.release()
```

**規則**：任何呼叫 `generic_message()` 的方法都必須持鎖，無例外。

---

### 2. CIP IP 位址轉換（Little-Endian UDINT）

**問題**：CAPAROC CIP Class 0xF5 以 **Little-Endian UDINT** 儲存 IP 位址。

**正確做法**：先以 `struct.unpack` 讀出整數，再 bit-shift 拆成 4 個 octet：

```python
v = struct.unpack_from('<I', buf, offset)[0]
return f"{(v>>24)&0xFF}.{(v>>16)&0xFF}.{(v>>8)&0xFF}.{v&0xFF}"
```

**錯誤做法**（commit 1f5523e 的錯誤，20e396f 還原）：

```python
# 直接順讀 LE bytes → 顯示倒序 "111.50.168.192" 而非 "192.168.50.111"
return f"{buf[offset]}.{buf[offset+1]}.{buf[offset+2]}.{buf[offset+3]}"
```

**教訓**：LE UDINT 的 bytes 排列是 `[111, 50, 168, 192]`，讀出整數後
$v = 111 + 50 \times 256 + 168 \times 65536 + 192 \times 16777216 = 3232248943$，
再 bit-shift 才能得到正確的 `192.168.50.111`。

---

### 3. WebSocket 斷線設計 — 例外必須在 `_read_current_status()` 捕獲

**問題根因**：若 `_read_current_status()` 的通訊例外傳播至 WebSocket handler，
handler 的 `while` 迴圈被中斷 → `_ws_client_count` 歸零 → 伺服器 shutdown，
但 `is_connected` 永遠為 `True`（`disconnect()` 從未被呼叫），使用者無法重新連線。

**修正**（commit d726a88）：在 `_read_current_status()` 內部捕獲所有例外：

```python
except Exception as e:
    # 通訊例外（網路斷線等）必須在此捕獲，不可傳播至 WebSocket handler
    if self._last_read_ok:
        self.logger.warning(f"讀取失敗：{e}")
        self._last_read_ok = False
    return None   # finally 仍會執行，確保鎖被釋放
```

WebSocket handler 收到 `None` 時，自動呼叫 `backend.disconnect()`，讓前端顯示斷線並允許重連。

---

### 4. Chart.js + chartjs-plugin-zoom 整合

**套件版本**（均透過 CDN 載入，無 npm）：

| 套件 | 版本 | CDN |
|------|------|-----|
| Chart.js | 4.4.6 | jsdelivr |
| chartjs-plugin-zoom | 1.2.1 | jsdelivr |
| Hammer.js | 2.0.8 | cdnjs（zoom 的 touch 相依） |

**注意事項**：
- `chartjs-plugin-zoom` 必須在 `Chart.js` **之後**、`Chart.register()` **之前**載入
- Hammer.js 必須先於 chartjs-plugin-zoom 載入（否則觸控縮放失效）
- zoom 重置按鈕：`chartInstance.resetZoom()`
- 雙 Y 軸設定：`scales: { y: { position: 'left' }, y1: { position: 'right', grid: { drawOnChartArea: false } } }`
- 歷史資料來源：`GET /api/history?minutes=N`（最多 30 分鐘，後端 `_history_buffer`）

