# Caparoc_breaker_control

進行遠端控制Caparoc_breaker，可檢測每一channel的電壓電流值以及啟閉動作

## 快速開始 (Quick Start)

1. **首先閱讀 AgentAI_init.md** - 包含 Agent AI 的基本規則
2. 在開始任何工作之前，遵循任務前合規檢查表
3. 在 `src/` 下使用正確的模組結構
4. 在每個已完成的功能之後提交

## 專案結構 (Project Structure)

此專案使用 **Simple** 結構，適合基本腳本和工具：

```
Caparoc_breaker_control/
├── AIagent_init.md        # AI Agent 的基本規則
├── README.md              # 專案文件
├── .gitignore             # Git 忽略模式
├── requirements.txt       # Python 依賴 (pip)
├── environment.yml        # Conda 環境配置
├── src/                   # 原始碼 (NEVER put files in root)
│   ├── main.py            # 主要腳本/進入點
│   └── utils.py           # 工具函數
├── tests/                 # 測試文件
│   └── test_main.py       # 基本測試
├── docs/                  # 文件
└── output/                # 產生的輸出文件
```

## 主要功能 (Features)

### ✅ 已實作 (V3.1)
- ✅ 多通道獨立控制 (on/off)
- ✅ 即時狀態讀取 (電壓、電流)
- ✅ 通道額定電流初始化
- ✅ Implicit Messaging 自動檢測
- ✅ 命令列互動介面

### ⚠️ 待實作
- [ ] 全域狀態監測 (持續背景監控)
- [ ] GUI 規劃設計 (圖形化介面)

詳見 [docs/TODO.md](docs/TODO.md) 完整開發計畫

## 📚 文檔 (Documentation)

- [TODO.md](docs/TODO.md) - 待實作功能與開發計畫
- [CHANGELOG.md](docs/CHANGELOG.md) - 版本更新歷史
- [DEBUG_ANALYSIS.md](docs/DEBUG_ANALYSIS.md) - 開發除錯記錄

## 安裝 (Installation)

### 使用現有的 Conda 環境（推薦）

#### 1. 啟動您的 Conda 環境
```bash
# 啟動您現有的 Conda 環境（替換為您的環境名稱）
conda activate your_env_name
```

#### 2. 安裝專案依賴
```bash
# 安裝 requirements.txt 中的套件
pip install -r requirements.txt
```

#### 3. 驗證安裝
```bash
python --version
python src/main.py
```

#### 4. 當您安裝新套件時
```bash
# 安裝新套件（例如 pyserial）
pip install pyserial

# 匯出當前環境的所有套件（可選）
pip freeze > requirements_full.txt

# 或者手動更新 requirements.txt
# Agent AI 會協助您維護 requirements.txt
```

### 創建新的 Conda 環境（可選）

如果需要創建新環境：
```bash
# 使用 environment.yml 創建環境
conda env create -f environment.yml

# 或手動創建環境
conda create -n caparoc_breaker python=3.11
conda activate caparoc_breaker
pip install -r requirements.txt
```

## 使用方法 (Usage)

### 運行控制器
```bash
# 確保已啟動 Conda 環境
conda activate caparoc_breaker

# 運行主控制器
python src/caparoc_controller.py
```

### 可用指令
```
on <ch>   - 開啟通道 (例: on 1)
off <ch>  - 關閉通道 (例: off 2)
s         - 顯示狀態
q         - 退出
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
