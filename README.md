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
├── AgentAI_init.md        # Agent AI 的基本規則
├── README.md              # 專案文件
├── .gitignore             # Git 忽略模式
├── requirements.txt       # Python 依賴
├── src/                   # 原始碼 (NEVER put files in root)
│   ├── main.py            # 主要腳本/進入點
│   └── utils.py           # 工具函數
├── tests/                 # 測試文件
│   └── test_main.py       # 基本測試
├── docs/                  # 文件
└── output/                # 產生的輸出文件
```

## 主要功能 (Features)

- ✅ 檢測每一 channel 的電壓值
- ✅ 檢測每一 channel 的電流值
- ✅ 控制每一 channel 的啟閉動作
- ✅ 遠端控制介面

## 安裝 (Installation)

### 1. 創建虛擬環境
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

### 2. 安裝依賴
```bash
pip install -r requirements.txt
```

## 使用方法 (Usage)

### 運行主程式
```bash
python src/main.py
```

### 運行測試
```bash
python -m pytest tests/
```

## 開發指南 (Development Guidelines)

- **永遠先搜索** 再創建新文件
- **擴展現有**功能而不是重複
- **使用任務 Agent** 進行 >30 秒的操作
- **單一事實來源** 適用於所有功能
- **在每個完成的任務後提交**

## 技術堆疊 (Tech Stack)

- **語言**: Python 3.x
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
