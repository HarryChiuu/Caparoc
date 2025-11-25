# Caparoc Breaker Control

CAPAROC 電子斷路器遠端控制程式，支援多通道電流監控與控制。

---

## 🚀 快速開始

### 1. 安裝依賴

```bash
# 使用 pip 安裝（推薦）
pip install -r requirements.txt

# 或使用 Conda 環境
conda env create -f environment.yml
conda activate caparoc_breaker
```

### 2. 運行程式

```bash
python src/caparoc_controller.py
```

### 3. 基本命令

```bash
s                    # 顯示狀態
on <ch>              # 開啟通道 (例: on 1)
off <ch>             # 關閉通道
monitor start        # 啟動即時監控
q                    # 退出
```

**詳細使用說明**: 參閱 [CLI 使用指南](docs/CLI_USER_GUIDE.md)

---

## 📚 文檔

- **[CLI 使用指南](docs/CLI_USER_GUIDE.md)** - 命令使用說明
- **[程式流程文檔](docs/PROGRAM_FLOW.md)** - 完整程式流程
- **[診斷工具指南](docs/DIAGNOSTIC_TOOLS_GUIDE.md)** - 問題診斷
- **[開發筆記](docs/DEVELOPMENT_NOTES.md)** - 技術細節

---

## ✨ 主要功能

### ✅ 已實作

- **多通道控制** - 支援 1-16 個模組（最多 64 通道）
- **即時監控** - 背景監控，狀態變化自動警報
  - 靜默模式：不干擾命令輸入，僅警報
  - 顯示模式：定期顯示完整狀態
- **標稱電流設定** - Config Assembly Read-Modify-Write（1-20A）
- **完整狀態顯示** - 系統電壓、總電流、各通道詳細狀態
- **心跳保活機制** - 防止 CIP 連線超時
- **動態模組檢測** - 自動識別模組數量

### ⚠️ 重要說明

- **標稱電流參數為唯讀** - 使用 Config Assembly Read-Modify-Write 方法設定
- **支援運行時配置** - 不需重啟設備即可修改參數
- **自動狀態同步** - 啟動時讀取設備實際狀態

---

## 🔧 連接問題排查

如果遇到連接錯誤：

```bash
python tests/check_connection.py
```

詳細排查請參閱 [診斷工具指南](docs/DIAGNOSTIC_TOOLS_GUIDE.md)

---

## 📊 專案結構

```
Caparoc5/
├── src/
│   └── caparoc_controller.py    # 主控制程式
├── tests/
│   ├── diagnostic_tools.py      # 診斷工具集
│   └── check_connection.py      # 連線檢查
├── docs/                        # 完整文檔
│   ├── CLI_USER_GUIDE.md        # 使用者指南
│   ├── PROGRAM_FLOW.md          # 程式流程
│   ├── DIAGNOSTIC_TOOLS_GUIDE.md # 診斷指南
│   └── ...
├── requirements.txt             # Python 依賴
└── environment.yml              # Conda 環境配置
```

---

## 💻 即時監控範例

### 靜默模式（推薦）

```bash
> monitor start 2 silent

✅ 即時監控已啟動
   更新頻率: 2.0s
   模式: 靜默模式 (僅警報)

> on 2    # 可以正常輸入指令

======================================================================
🔔 監控警報 [14:32:17]
======================================================================
  ▸ CH2 狀態變更: 開啟
  ▸ 電流變化: 0.0A → 3.5A
======================================================================
```

---

## 🔄 版本歷史

- **v3.7** (2025-11-25) - 標稱電流設定優化（漸進式重試驗證）
- **v3.6** (2025-10-28) - 即時監控功能
- **v3.5** (2025-10-28) - 多模組架構支援（1-16 模組）
- **v3.0** (2025-10-27) - 基於手冊規範重構

詳見 [CHANGELOG.md](docs/CHANGELOG.md)

---

## 🛠️ 技術堆疊

- **Python** 3.11
- **pycomm3** - EtherNet/IP 通訊
- **CIP 協議** - 工業設備通訊標準

---

## 📝 授權

MIT License

---

**專案維護**: Harry Chiu  
**文檔更新**: 2025年11月25日



### 1. 安裝依賴### 步驟 1: 檢查連接



```bash**如果遇到連接問題 ("failed to send message"):**

pip install -r requirements.txt

``````bash

# 運行診斷工具

### 2. 運行程式python check_connection.py

```

```bash

python src/caparoc_controller.py**詳細排查指南:** 請參閱 [連接問題排查指南](docs/TROUBLESHOOTING_CONNECTION.md)

```

### 步驟 2: 安裝依賴

程式會自動檢測系統狀態並進入互動模式。

```bash

### 3. 常用命令pip install -r requirements.txt

```

```bash

### 步驟 3: 運行主程式

```bash
python src/caparoc_controller.py
```

選擇選項 **2** (互動控制模式)，然後可以使用以下命令：

**可用命令：**
- `on 1` / `off 1` - 控制個別通道
- `s` - 查看完整狀態
- `monitor start` - 啟動即時監控

詳細命令請參閱 [互動式測試指南](INTERACTIVE_TEST_GUIDE.md)

---

# 退出

q                               # 退出程式## 文件與指南

```

1. **[互動式測試指南](INTERACTIVE_TEST_GUIDE.md)** - 完整測試流程與命令

## 🔧 連接問題排查2. **[主開關控制說明](docs/MAIN_POWER_CONTROL.md)** - 總電源控制技術細節

3. **[連接問題排查](docs/TROUBLESHOOTING_CONNECTION.md)** - 網路連接診斷

如果遇到 "failed to send message" 錯誤：4. **[AIagent_init.md](AIagent_init.md)** - Agent AI 的基本規則



```bash---

# 運行診斷工具

python check_connection.py## 專案結構 (Project Structure)

```

此專案使用 **Simple** 結構，適合基本腳本和工具：

詳細排查步驟請參閱 [連接問題排查指南](docs/TROUBLESHOOTING_CONNECTION.md)

```

## ⚙️ 標稱電流設定Caparoc_breaker_control/

├── AIagent_init.md        # AI Agent 的基本規則

**重要：無法透過 EtherNet/IP 修改標稱電流**├── README.md              # 專案文件

├── .gitignore             # Git 忽略模式

CAPAROC 設備的標稱電流參數為**唯讀**，必須透過設備本身設定：├── requirements.txt       # Python 依賴 (pip)

├── environment.yml        # Conda 環境配置

### 方法：使用設備按鈕├── src/                   # 原始碼 (NEVER put files in root)

│   ├── main.py            # 主要腳本/進入點

1. 長按 **PWR** 鍵 3 秒（LED 閃綠光 3 次，解除硬體鎖）│   └── utils.py           # 工具函數

2. 短按對應通道按鈕進入編程模式├── tests/                 # 測試文件

3. 按 **+** 或 **-** 調整電流值（1-20A）│   └── test_main.py       # 基本測試

4. 短按通道按鈕確認├── docs/                  # 文件

5. 長按 **PWR** 鍵 3 秒退出└── output/                # 產生的輸出文件

```

### 驗證設定

## 主要功能 (Features)

```bash

> verify 2### ✅ V3.6 - 即時監控 (2025-10-28)

✅ CH2 標稱電流: 4A- ✅ **即時監控功能** - Phase 3-2 完成

```  - 背景執行緒定期讀取狀態 (0.5s-60s 可調)

  - **靜默模式** (預設) - 不干擾命令輸入,僅警報通知

程式中的 `init` 命令會顯示完整的手動設定指引。  - 顯示模式 - 定期顯示完整狀態

  - 狀態變化即時檢測與警報

## 📊 主要功能  - 通道開關變化偵測

  - 電流異常變化警報 (>30%)

### ✅ 已實作  - 系統電壓變化提醒

  - 新指令: `monitor start [interval] [mode]`

- **主開關控制** - 控制總電源開關（緊急停止用）

- **通道控制** - 個別通道開關控制### ✅ V3.5 - 多模組架構 (2025-10-28)

- **即時監控** - 背景監控，狀態變化自動警報- ✅ **動態多模組支援** - 自動檢測 1-16 個模組 (最多 64 通道)

  - 靜默模式：不干擾命令輸入，僅警報- ✅ **智能通道管理** - 根據模組數量動態調整

  - 顯示模式：定期顯示完整狀態- ✅ **多模組顯示** - M1.CH1 (#1) 格式顯示

- **多模組支援** - 自動檢測 1-16 個模組（最多 64 通道）- ✅ **向後兼容** - 單模組環境無縫運作

- **完整狀態顯示**

  - 系統電壓與總電流### ✅ V3.4 - 完整手冊實作 (2025-10-28)

  - 各通道狀態、電流、警告- ✅ **手冊 7.2.1-7.2.4** - 完整全域狀態檢查

  - 過載、短路、硬體故障檢測  - 系統電壓檢查 (9.0-30.5V)

  - 模組數量檢測 (0-16 個)

### ⚠️ 已知限制  - 總電流讀取 (0-50.0A)

  - 欠壓/過壓/系統錯誤檢測

- **Config Assembly 唯讀** - 無法透過 EtherNet/IP 修改配置- ✅ **手冊 7.2.5** - 完整通道狀態解析

- **Parameter Object 唯讀** - 標稱電流等參數必須手動設定  - 6 個狀態位元 (開/關、80%警告、過載、短路、硬體故障、總電流關斷)

- 設備韌體禁止運行時修改配置參數  - 標稱電流顯示 (1-10A)

  - 實際電流顯示 (0-25.5A)

## 📚 文檔

### ✅ V3.3 - 狀態顯示增強 (2025-10-27)

- **[INTERACTIVE_TEST_GUIDE.md](INTERACTIVE_TEST_GUIDE.md)** - 完整測試流程與命令- ✅ 全域系統狀態顯示

- **[docs/MAIN_POWER_CONTROL.md](docs/MAIN_POWER_CONTROL.md)** - 主開關控制技術細節- ✅ 設備復電狀態同步修復

- **[docs/TROUBLESHOOTING_CONNECTION.md](docs/TROUBLESHOOTING_CONNECTION.md)** - 連接問題診斷- ✅ 完整通道狀態 (開關/電流/警告)



## 🏗️ 專案結構### ✅ V3.2 - 互動式設定 (2025-10-27)

- ✅ 通道額定電流初始化

```- ✅ 互動式電流值設定

Caparoc_breaker_control/- ✅ Implicit Messaging 自動檢測

├── README.md                    # 專案說明- ✅ 命令列互動介面

├── requirements.txt             # Python 依賴

├── check_connection.py          # 連接診斷工具### ⚠️ 待實作

├── src/- [ ] 通道資訊擴展 (Phase 3-3)

│   └── caparoc_controller.py    # 主程式- [ ] IP 配置支援 (Phase 3-4)

├── docs/                        # 文檔- [ ] GUI 規劃設計 (Phase 3-5)

└── tests/                       # 測試

```詳見 [docs/TODO.md](docs/TODO.md) 完整開發計畫



## 💻 即時監控範例## 📚 文檔 (Documentation)



### 靜默模式（推薦）- [TODO.md](docs/TODO.md) - 待實作功能與開發計畫

- [CHANGELOG.md](docs/CHANGELOG.md) - 版本更新歷史

```bash- [DEBUG_ANALYSIS.md](docs/DEBUG_ANALYSIS.md) - 開發除錯記錄

> monitor start 2 silent

## 安裝 (Installation)

✅ 即時監控已啟動

   更新頻率: 2.0s### 使用現有的 Conda 環境（推薦）

   模式: 靜默模式 (僅警報)

   💡 提示: 監控在背景運行，有變化時會自動通知#### 1. 啟動您的 Conda 環境

```bash

> on 2    # 可以正常輸入指令# 啟動您現有的 Conda 環境（替換為您的環境名稱）

conda activate your_env_name

======================================================================```

🔔 監控警報 [14:32:17]

======================================================================#### 2. 安裝專案依賴

  ▸ CH2 狀態變更: 開啟```bash

  ▸ 電流變化: 0.0A → 3.5A# 安裝 requirements.txt 中的套件

======================================================================pip install -r requirements.txt

>         # 自動恢復輸入提示```

```

#### 3. 驗證安裝

### 顯示模式```bash

python --version

```bashpython src/main.py

> monitor start 5 display```



======================================================================#### 4. 當您安裝新套件時

🔄 即時監控 [14:32:15] - 更新頻率: 5.0s```bash

======================================================================# 安裝新套件（例如 pyserial）

📊 系統: 24.0V | 8.5A | 1 模組pip install pyserial



通道            狀態   電流         警告/錯誤# 匯出當前環境的所有套件（可選）

----------------------------------------------------------------------pip freeze > requirements_full.txt

CH1             🟢 開  2.5A / 4.0A  ✅

CH2             🔴 關  0.0A / 10.0A ✅# 或者手動更新 requirements.txt

CH3             🟢 開  6.0A / 10.0A ⚠️80%# Agent AI 會協助您維護 requirements.txt

CH4             🔴 關  0.0A / 6.0A  ✅```

======================================================================

```### 創建新的 Conda 環境（可選）



## 🌐 多模組支援如果需要創建新環境：

```bash

程式自動檢測模組數量（1-16 個，最多 64 通道）：# 使用 environment.yml 創建環境

conda env create -f environment.yml

### 單模組顯示

# 或手動創建環境

```conda create -n caparoc_breaker python=3.11

CH1: ON  2.5A / 4Aconda activate caparoc_breaker

CH2: OFF 0.0A / 10Apip install -r requirements.txt

``````



### 多模組顯示## 使用方法 (Usage)



```### 運行控制器

M1.CH1 (#1):  ON  2.5A / 4A```bash

M1.CH2 (#2):  OFF 0.0A / 10A# 確保已啟動 Conda 環境

M2.CH1 (#5):  ON  3.2A / 5Aconda activate caparoc_breaker

M2.CH2 (#6):  ON  3.5A / 8A

```# 運行主控制器

python src/caparoc_controller.py

## 🔧 開發環境```



- **語言**: Python 3.11### 可用指令

- **主要依賴**: pycomm3 (EtherNet/IP 通訊)```

- **環境管理**: Conda 或 venvinit <ch> <amps>                 - 顯示標稱電流手動設定指引

                                   範例: init 2 4

## 📝 授權on <ch>                          - 開啟通道 (例: on 1)

off <ch>                         - 關閉通道 (例: off 2)

MIT Licenses                                - 顯示完整狀態

verify <ch>                      - 驗證通道標稱電流設定

---monitor start [interval] [mode]  - 啟動即時監控

                                   interval: 更新頻率(秒), 預設2

**專案維護**: Harry Chiu                                     mode: silent(靜默) 或 display(顯示), 預設silent

**技術支援**: 參閱文檔或提交 Issuemonitor stop                     - 停止即時監控

monitor status                   - 顯示監控狀態
q                                - 退出
```

### ⚠️ 重要說明:標稱電流設定

**無法透過 EtherNet/IP 直接修改標稱電流參數**

經測試,CAPAROC 設備不允許透過 EtherNet/IP 修改標稱電流。
請使用以下方法手動設定:

#### 方法 1: 使用設備按鈕 (推薦)
1. 長按 PWR 鍵 3 秒 (LED 閃綠光 3 次,解除硬體鎖)
2. 短按對應通道按鈕進入編程模式
3. 按 + 或 - 按鈕調整電流值 (1-20A)
4. 短按通道按鈕確認
5. 長按 PWR 鍵 3 秒退出

#### 方法 2: 使用設備網頁介面 (如果支援)
- 瀏覽器訪問: `http://192.168.2.111`

#### 驗證設定
設定完成後,使用程式驗證:
```
> verify 2
✅ CH2 標稱電流: 4A
```

### 即時監控範例

#### 模式說明
- **靜默模式 (silent)** ⭐ 推薦
  - 監控在背景運行,**不干擾命令輸入**
  - 僅在偵測到變化時顯示警報
  - 適合長時間監控

- **顯示模式 (display)**
  - 定期顯示完整狀態
  - 會干擾命令輸入
  - 適合短期觀察

#### 啟動靜默監控 (推薦)
```
> monitor start 2 silent

✅ 即時監控已啟動
   更新頻率: 2.0s
   模式: 靜默模式 (僅警報)
   � 提示: 監控在背景運行,有變化時會自動通知

> on 2    # 可以正常輸入指令

======================================================================
🔔 監控警報 [14:32:17]
======================================================================
  ▸ CH2 狀態變更: 開啟
======================================================================
>         # 自動恢復輸入提示
```

#### 啟動顯示監控
```
> monitor start 5 display

✅ 即時監控已啟動
   更新頻率: 5.0s
   模式: 顯示模式 (持續更新)

======================================================================
🔄 即時監控 [14:32:15] - 更新頻率: 5.0s
======================================================================
📊 系統: 24.0V | 8.5A | 1 模組

通道            狀態   電流         警告/錯誤
----------------------------------------------------------------------
CH1             🟢 開  2.5A / 4.0A  ✅
CH2             🔴 關  0.0A / 10.0A ✅
CH3             🟢 開  6.0A / 10.0A ⚠️80%
CH4             🔴 關  0.0A / 6.0A  ✅
======================================================================
```

#### 偵測到變化時 (顯示模式)
```
======================================================================
🔄 即時監控 [14:32:20] - 更新頻率: 5.0s
======================================================================
📊 系統: 24.0V | 11.0A | 1 模組

通道            狀態   電流         警告/錯誤
----------------------------------------------------------------------
CH1             🟢 開  2.5A / 4.0A  ✅
CH2             🟢 開  3.5A / 10.0A ✅
CH3             🟢 開  6.0A / 10.0A ⚠️80%
CH4             🔴 關  0.0A / 6.0A  ✅

🔔 檢測到變化:
  ▸ CH2 狀態變更: 開啟
  ▸ 電壓變化: 24.0V → 23.5V
======================================================================
```

### 多模組環境範例

#### 單模組顯示 (1 個模組)
```
=== 系統狀態 ===
模組數量: 1
總電流: 8.5A
輸入電壓: 24.0V

CH1: ON  2.5A / 4A
CH2: OFF 0.0A / 10A
CH3: ON  6.0A / 10A (⚠️ 80% 警告)
CH4: OFF 0.0A / 6A
```

#### 多模組顯示 (2 個模組)
```
=== 系統狀態 ===
模組數量: 2
總電流: 15.2A
輸入電壓: 24.0V

M1.CH1 (#1):  ON  2.5A / 4A
M1.CH2 (#2):  OFF 0.0A / 10A
M1.CH3 (#3):  ON  6.0A / 10A
M1.CH4 (#4):  OFF 0.0A / 6A
M2.CH1 (#5):  ON  3.2A / 5A
M2.CH2 (#6):  ON  3.5A / 8A
M2.CH3 (#7):  OFF 0.0A / 10A
M2.CH4 (#8):  OFF 0.0A / 4A
```

### 運行測試
```bash
python -m pytest tests/
```

### 常用命令參考
```bash
# 查看當前環境已安裝的套件
pip list

# 查看 pip 安裝的套件（排除 conda 安裝的）
pip freeze

# 安裝新套件並記錄版本
pip install package_name
# 然後將套件添加到 requirements.txt

# 匯出完整環境（包含所有套件）
pip freeze > requirements_full.txt

# 匯出 Conda 環境配置
conda env export > environment_backup.yml
```

## 開發指南 (Development Guidelines)

- **永遠先搜索** 再創建新文件
- **擴展現有**功能而不是重複
- **使用任務 Agent** 進行 >30 秒的操作
- **單一事實來源** 適用於所有功能
- **在每個完成的任務後提交**

## 技術堆疊 (Tech Stack)

- **語言**: Python 3.11
- **環境管理**: Conda
- **專案類型**: Simple (基本腳本/工具)
- **版本控制**: Git + GitHub

## 貢獻 (Contributing)

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 授權 (License)

此專案採用 MIT 授權 - 詳見 LICENSE 文件

## 聯絡方式 (Contact)

Project Link: [https://github.com/yourusername/Caparoc_breaker_control](https://github.com/yourusername/Caparoc_breaker_control)

---

**🎯 Template by**: Harry Chiu | v1.0.1  
**📺 Original Tutorial**: https://youtu.be/8Q1bRZaHH24
