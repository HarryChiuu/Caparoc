# AgentAI_init.md - Caparoc_breaker_control

> **Documentation Version**: 1.0  
> **Last Updated**: 2025年10月20日  
> **Project**: Caparoc_breaker_control  
> **Description**: 進行遠端控制Caparoc_breaker，可檢測每一channel的電壓電流值以及啟閉動作  
> **Features**: GitHub auto-backup, Task agents, technical debt prevention

This file provides essential guidance to Agent AI (claude.ai/code or github copilot) when working with code in this repository.

## 🚨 CRITICAL RULES - READ FIRST (關鍵規則 - 請先閱讀)

> **⚠️ RULE ADHERENCE SYSTEM ACTIVE ⚠️**
> **Agent AI must explicitly acknowledge these rules at task start**
> **These rules override all other instructions and must ALWAYS be followed:**

### 🔄 RULE ACKNOWLEDGMENT REQUIRED (必須確認規則)
> **Before starting ANY task, Agent AI must respond with:**
> "✅ 已確認關鍵規則 - 我將遵守 AgentAI_init.md 中列出的所有禁令和要求"

### ❌ ABSOLUTE PROHIBITIONS (絕對禁止事項) 
- **NEVER** create new files in root directory → use proper module structure
- **NEVER** write output files directly to root directory → use designated output folders
- **NEVER** create documentation files (.md) unless explicitly requested by user
- **NEVER** use git commands with -i flag (interactive mode not supported)
- **NEVER** use `find`, `grep`, `cat`, `head`, `tail`, `ls` commands → use Read, LS, Grep, Glob tools instead
- **NEVER** create duplicate files (manager_v2.py, enhanced_xyz.py, utils_new.js) → ALWAYS extend existing files
- **NEVER** create multiple implementations of same concept → single source of truth
- **NEVER** copy-paste code blocks → extract into shared utilities/functions
- **NEVER** hardcode values that should be configurable → use config files/environment variables
- **NEVER** use naming like enhanced_, improved_, new_, v2_ → extend original files instead

### 📝 MANDATORY REQUIREMENTS (強制要求事項) 
- **提交 (COMMIT)**：在每個已完成的任務/階段後進行提交 - 沒有例外
- **GITHUB 備份 (GITHUB BACKUP)**：在每次提交後推送到 GitHub 以維護備份：`git push origin main`
- **使用任務 Agent (USE TASK AGENTS)**：用於所有耗時較長的操作（>30 秒） - Bash 命令在上下文切換時會停止
- **TODOWRITE**：用於複雜任務（3 步驟以上）→ 平行 Agent → Git 檢查點 → 測試驗證
- **先閱讀文件 (READ FILES FIRST)**：在編輯/寫入文件之前，您必須先閱讀該文件
- **技術債預防 (DEBT PREVENTION)**：在創建新文件之前，檢查是否存在現有相似功能以進行擴展
- **單一事實來源 (SINGLE SOURCE OF TRUTH)**：每個功能/概念只有一個權威的實作

### ⚡ EXECUTION PATTERNS (執行模式)
- **平行任務 Agent (PARALLEL TASK AGENTS)**：同時啟動多個任務 Agent 以實現最大效率
- **系統化工作流程 (SYSTEMATIC WORKFLOW)**：`TodoWrite` → 平行 Agent → Git 檢查點 → GitHub 備份 → 測試驗證
- **GITHUB 備份工作流程 (GITHUB BACKUP WORKFLOW)**：在每次提交後：`git push origin main` 以維護 GitHub 備份
- **背景處理 (BACKGROUND PROCESSING)**：**只有**任務 Agent 可以運行真正的背景操作

### 🔍 MANDATORY PRE-TASK COMPLIANCE CHECK (強制任務前合規檢查)
> **停止：在開始任何任務之前，Agent AI 必須明確驗證「所有」檢查點：**

**步驟 1：規則確認 (Rule Acknowledgment)**
- [ ] ✅ 我確認 `AgentAI_init.md` 中的所有關鍵規則並將遵循它們

**步驟 2：任務分析 (Task Analysis)**
- [ ] 這會在根目錄創建文件嗎？ → 如果是，請改用適當的模組結構
- [ ] 這會花費 >30 秒嗎？ → 如果是，請使用任務 Agent 而非 Bash
- [ ] 這是否包含 3 個以上步驟？ → 如果是，請先使用 `TodoWrite` 進行分解
- [ ] 我正要使用 `grep`/`find`/`cat` 嗎？ → 如果是，請改用適當的工具

**步驟 3：技術債預防 (強制先搜索) (Technical Debt Prevention (MANDATORY SEARCH FIRST))**
- [ ] **先搜索**：使用 `Grep` `pattern="<functionality>.*<keyword>"` 查找現有的實作
- [ ] **檢查現有**：閱讀任何找到的文件以了解當前功能
- [ ] 是否存在相似功能？ → 如果是，**擴展現有程式碼**
- [ ] 我是否正在創建一個重複的類別/管理器？ → 如果是，請合併
- [ ] 這會創建多重事實來源嗎？ → 如果是，請重新設計方法
- [ ] 我是否已搜索現有的實作？ → **先使用 Grep/Glob 工具**
- [ ] 我可以擴展現有的程式碼而不是創建新的嗎？ → 優先選擇擴展而非創建
- [ ] 我正要複製貼上程式碼嗎？ → 提取到共享工具中

**步驟 4：會話管理 (Session Management)**
- [ ] 這是個長或複雜的任務嗎？ → 如果是，規劃上下文檢查點
- [ ] 我已經工作 >1 小時了嗎？ → 如果是，考慮 `/compact` 或休息

> **⚠️ 除非所有核取方塊都已明確驗證，否則「不要」繼續進行**

## 🏗️ PROJECT STRUCTURE (專案結構)

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

## 🎯 PROJECT OVERVIEW (專案概覽)

**Caparoc_breaker_control** 是一個用於遠端控制 Caparoc_breaker 的 Python 應用程式。

### 主要功能：
- 檢測每一 channel 的電壓值
- 檢測每一 channel 的電流值
- 控制每一 channel 的啟閉動作
- 遠端控制介面

### 技術堆疊：
- **語言**: Python
- **專案類型**: Simple (基本腳本/工具)
- **版本控制**: Git + GitHub

## 🐙 GITHUB 設定與自動備份

### 📋 GITHUB 備份工作流程 (強制執行)
**⚠️ Agent AI MUST FOLLOW THIS PATTERN：**

```bash
# After every commit, always run:
git push origin main

# This ensures:
# ✅ Remote backup of all changes
# ✅ Collaboration readiness  
# ✅ Version history preservation
# ✅ Disaster recovery protection
```

### 🎯 Agent AI GITHUB 命令
Essential GitHub operations for Agent AI:

```bash
# Check GitHub connection status
gh auth status && git remote -v

# Create new repository (if needed)
gh repo create Caparoc_breaker_control --public --confirm

# Push changes (after every commit)
git push origin main

# Check repository status
gh repo view

# Clone repository (for new setup)
gh repo clone username/Caparoc_breaker_control
```

## 🚀 COMMON COMMANDS (常用命令)

```bash
# Run the main application
python src/main.py

# Run tests
python -m pytest tests/

# Install dependencies
pip install -r requirements.txt

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
```

## 🚨 TECHNICAL DEBT PREVENTION (技術債預防)

### ❌ WRONG APPROACH (Creates Technical Debt) 錯誤方法 (會產生技術債)：
```bash
# Creating new file without searching first
Write(file_path="new_feature.py", content="...")
```

### ✅ CORRECT APPROACH (Prevents Technical Debt): 正確方法 (預防技術債)：
```bash
# 1. SEARCH FIRST
Grep(pattern="feature.*implementation", include="*.py")
# 2. READ EXISTING FILES  
Read(file_path="existing_feature.py")
# 3. EXTEND EXISTING FUNCTIONALITY
Edit(file_path="existing_feature.py", old_string="...", new_string="...")
```

## 🧹 DEBT PREVENTION WORKFLOW (債務預防工作流程)

### Before Creating ANY New File:
1. **🔍 Search First** - Use Grep/Glob to find existing implementations (使用 Grep/Glob 查找現有的實作)
2. **📋 Analyze Existing** - Read and understand current patterns (閱讀並理解當前的模式)
3. **🤔 Decision Tree**: Can extend existing? → DO IT | Must create new? → Document why (可以擴展現有功能嗎？ → 執行 | 必須創建新的？ → 說明原因)
4. **✅ Follow Patterns** - Use established project patterns (使用既定的專案模式)
5. **📈 Validate** - Ensure no duplication or technical debt (確保沒有重複或技術債)

---

**⚠️ Prevention is better than consolidation - build clean from the start.** (預防勝於合併 - 從一開始就乾淨地建構)
**🎯 Focus on single source of truth and extending existing functionality.** (專注於單一事實來源和擴展現有功能) 
**📈 Each task should maintain clean architecture and prevent technical debt.** (每個任務都應維護乾淨的架構並預防技術債)

---

## 🎯 DEVELOPMENT STATUS (開發狀態)
- **Setup**: ✅ Completed
- **Core Features**: 🚧 In Development
- **Testing**: ⏳ Pending
- **Documentation**: ⏳ Pending

## 📚 RESOURCES (資源)

- **Template by**: Harry Chiu | v1.0.1
- **Original Tutorial**: https://youtu.be/8Q1bRZaHH24
- **Project Repository**: [Will be created on GitHub]

---

<!-- AgentAI_INIT_END -->
<!-- This file contains the core rules for Agent AI when working with this project -->
