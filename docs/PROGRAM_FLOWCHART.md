# CAPAROC 控制程式流程圖

> **文檔版本**: v1.0  
> **最後更新**: 2025-11-13  
> **對應程式**: caparoc_controller.py v3.7

本文檔使用 Mermaid 語法繪製流程圖，可在支援 Mermaid 的 Markdown 檢視器中查看。

---

## 📚 目錄

1. [主程式啟動流程](#1-主程式啟動流程)
2. [標稱電流設定流程](#2-標稱電流設定流程)
3. [通道控制流程](#3-通道控制流程)
4. [即時監控流程](#4-即時監控流程)
5. [重連機制流程](#5-重連機制流程)
6. [Assembly 通訊架構](#6-assembly-通訊架構)

---

## 1. 主程式啟動流程

### 1.1 完整啟動流程

```mermaid
flowchart TD
    Start([程式啟動]) --> Init[創建 CaparocController 實例]
    Init --> MainLoop{主迴圈}
    
    MainLoop --> Run[執行 run 方法]
    Run --> Step0[Step 0: 檢查裝置連線]
    
    Step0 --> CheckConn{連線成功?}
    CheckConn -->|否| ShowError[顯示錯誤訊息]
    ShowError --> UserChoice1{使用者選擇}
    UserChoice1 -->|重新連線| MainLoop
    UserChoice1 -->|退出| End([程式結束])
    
    CheckConn -->|是| Step1[Step 1: IP 配置提示]
    Step1 --> ChangeIP{變更 IP?}
    ChangeIP -->|是| ConfigIP[配置新 IP]
    ConfigIP --> ValidateIP{IP 驗證}
    ValidateIP -->|失敗| ConfigIP
    ValidateIP -->|成功| Step2
    ChangeIP -->|否| Step2
    
    Step2[Step 2: 檢測模組數量] --> ModuleDetect[讀取 Input Assembly Byte 1]
    ModuleDetect --> CalcChannels[計算總通道數 = 模組數 × 4]
    
    CalcChannels --> Step3[Step 3: 全域系統狀態檢查]
    Step3 --> CheckStatus[檢查電壓/電流/警告]
    CheckStatus --> SafeCheck{系統安全?}
    
    SafeCheck -->|異常| ShowWarning[顯示警告訊息]
    ShowWarning --> UserChoice2{繼續?}
    UserChoice2 -->|否| End
    UserChoice2 -->|是| Step4
    SafeCheck -->|正常| Step4
    
    Step4[Step 4: 讀取並同步設備狀態] --> ReadActual[從 Input Assembly 讀取實際狀態]
    ReadActual --> SyncOutput[同步到 Output Assembly buffer]
    
    SyncOutput --> Step5[Step 5: 標稱電流初始化]
    Step5 --> InitPrompt{是否初始化?}
    InitPrompt -->|是| InitProcess[執行初始化流程]
    InitProcess --> Step6
    InitPrompt -->|否| Step6
    
    Step6[Step 6: 進入命令迴圈] --> ShowHelp{首次連線?}
    ShowHelp -->|是| DisplayFullHelp[顯示完整幫助信息]
    ShowHelp -->|否| DisplayShortMsg[顯示簡短提示]
    
    DisplayFullHelp --> CmdLoop[命令迴圈]
    DisplayShortMsg --> CmdLoop
    
    CmdLoop --> WaitCmd[等待使用者輸入]
    WaitCmd --> ProcessCmd{處理命令}
    
    ProcessCmd -->|q| StopMonitor[停止監控]
    StopMonitor --> End
    
    ProcessCmd -->|reconnect| StopMonitor2[停止監控]
    StopMonitor2 --> Return[返回 'reconnect']
    Return --> MainLoop
    
    ProcessCmd -->|init| InitCurrent[標稱電流設定]
    ProcessCmd -->|on/off| ChannelControl[通道控制]
    ProcessCmd -->|s| ShowStatus[狀態顯示]
    ProcessCmd -->|monitor| MonitorCmd[監控命令]
    ProcessCmd -->|h/help| ShowFullHelp[顯示幫助]
    ProcessCmd -->|verify| VerifyCmd[驗證電流]
    
    InitCurrent --> CmdLoop
    ChannelControl --> CmdLoop
    ShowStatus --> CmdLoop
    MonitorCmd --> CmdLoop
    ShowFullHelp --> CmdLoop
    VerifyCmd --> CmdLoop
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style CheckConn fill:#FFE4B5
    style SafeCheck fill:#FFE4B5
    style ProcessCmd fill:#87CEEB
```

### 1.2 連線檢查詳細流程

```mermaid
flowchart TD
    Start([check_device_connection]) --> CreateDriver[創建 CIPDriver 實例]
    CreateDriver --> TryRead[嘗試讀取 Input Assembly]
    
    TryRead --> ReadMsg[Service: 0x0E<br/>Class: 0x04<br/>Instance: 0x65<br/>Attribute: 3]
    ReadMsg --> CheckResp{有回應?}
    
    CheckResp -->|否| Error1[連線失敗]
    Error1 --> Return1[返回 connected=False]
    
    CheckResp -->|是| CheckLen{長度 >= 6?}
    CheckLen -->|否| Error2[資料長度不足]
    Error2 --> Return1
    
    CheckLen -->|是| ParseData[解析資料]
    ParseData --> GetModule[Byte 1 = 模組數量]
    GetModule --> CheckModule{模組數 > 0?}
    
    CheckModule -->|否| Error3[未檢測到模組]
    Error3 --> Return1
    
    CheckModule -->|是| Success[連線成功]
    Success --> StoreInfo[儲存設備資訊]
    StoreInfo --> Return2[返回 connected=True]
    
    Return1 --> End([結束])
    Return2 --> End
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style CheckResp fill:#FFE4B5
    style CheckLen fill:#FFE4B5
    style CheckModule fill:#FFE4B5
```

---

## 2. 標稱電流設定流程

### 2.1 Parameter Object 5 步驟方法

```mermaid
flowchart TD
    Start([init 命令]) --> Parse[解析命令參數]
    Parse --> Validate{驗證參數}
    Validate -->|失敗| ShowUsage[顯示用法]
    ShowUsage --> End([結束])
    
    Validate -->|成功| CalcParam[計算參數編號]
    CalcParam --> Step1[Step 1: 解除全域電流鎖定]
    
    Step1 --> Write1[寫入 Param1 = 0<br/>Class: 0x0F<br/>Instance: 0x01<br/>Service: 0x10]
    Write1 --> Wait1[等待 0.2s]
    
    Wait1 --> Step2[Step 2: 解除全域介面鎖定]
    Step2 --> Write2[寫入 Param2 = 0<br/>Class: 0x0F<br/>Instance: 0x02<br/>Service: 0x10]
    Write2 --> Wait2[等待 0.2s]
    
    Wait2 --> Step3[Step 3: 解除通道 programming lock]
    Step3 --> CalcLock[計算 lock 參數編號<br/>ParamN + 1]
    CalcLock --> Write3[寫入 ParamN+1 = 0<br/>Class: 0x0F<br/>Instance: ParamN+1<br/>Service: 0x10]
    Write3 --> Wait3[等待 0.2s]
    
    Wait3 --> Step4[Step 4: 設定標稱電流]
    Step4 --> Write4[寫入 ParamN = current_amps<br/>Class: 0x0F<br/>Instance: ParamN<br/>Service: 0x10]
    Write4 --> CheckWrite{寫入成功?}
    
    CheckWrite -->|否| Error[顯示錯誤]
    Error --> End
    
    CheckWrite -->|是| Wait4[等待 0.5s]
    Wait4 --> Step5[Step 5: 雙重驗證]
    
    Step5 --> Verify1[方法1: 讀取 Parameter Object]
    Verify1 --> Read1[Service: 0x0E<br/>Class: 0x0F<br/>Instance: ParamN]
    Read1 --> Check1{值正確?}
    
    Check1 -->|是| Success1[✅ Param 驗證通過]
    Check1 -->|否| Warn1[⚠️ Param 驗證未通過]
    
    Success1 --> Verify2
    Warn1 --> Verify2
    
    Verify2[方法2: 讀取 Input Assembly]
    Verify2 --> Read2[讀取 Byte offset+1]
    Read2 --> Check2{值正確?}
    
    Check2 -->|是| Success2[✅ Input Assembly 驗證通過]
    Check2 -->|否| Warn2[⚠️ Input Assembly 驗證未通過]
    
    Success2 --> Final{兩者都通過?}
    Warn2 --> Final
    
    Final -->|是| Complete[✅ 設定完成]
    Final -->|否| Partial[⚠️ 設定可能成功，建議手動確認]
    
    Complete --> End
    Partial --> End
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style CheckWrite fill:#FFE4B5
    style Final fill:#FFE4B5
    style Complete fill:#90EE90
    style Error fill:#FF6B6B
```

### 2.2 參數編號計算

```mermaid
flowchart LR
    Input[輸入: Module, Channel] --> Formula[公式]
    Formula --> Base[基礎參數 = 6]
    Base --> ModuleOff[模組偏移 = module-1 × 12]
    ModuleOff --> ChannelOff[通道偏移 = channel-1 × 3]
    ChannelOff --> Nominal[標稱電流參數 = 6 + 模組偏移 + 通道偏移]
    Nominal --> Lock[Lock 參數 = 標稱電流參數 + 1]
    
    Nominal --> Example1[範例: M1.CH1<br/>6 + 0×12 + 0×3 = 6]
    Nominal --> Example2[範例: M1.CH4<br/>6 + 0×12 + 3×3 = 15]
    Nominal --> Example3[範例: M2.CH1<br/>6 + 1×12 + 0×3 = 18]
    
    style Input fill:#90EE90
    style Nominal fill:#87CEEB
    style Lock fill:#FFE4B5
```

---

## 3. 通道控制流程

### 3.1 on/off 命令處理

```mermaid
flowchart TD
    Start([on/off 命令]) --> Parse[解析通道編號]
    Parse --> CheckInit{已初始化?}
    
    CheckInit -->|否| Error1[錯誤: 請先初始化]
    Error1 --> End([結束])
    
    CheckInit -->|是| CalcBit[計算位元位置]
    CalcBit --> BitPos[byte_offset = 1<br/>bit_position = channel - 1]
    
    BitPos --> GetCurrent[讀取當前 Byte 1 值]
    GetCurrent --> DoBitOp{開啟或關閉?}
    
    DoBitOp -->|開啟| SetBit[new_value = current | 1 << bit]
    DoBitOp -->|關閉| ClearBit[new_value = current & ~1 << bit]
    
    SetBit --> UpdateBuffer
    ClearBit --> UpdateBuffer
    
    UpdateBuffer[更新 output_data buffer]
    UpdateBuffer --> WriteAssembly[寫入 Output Assembly]
    
    WriteAssembly --> WriteMsg[Service: 0x10<br/>Class: 0x04<br/>Instance: 0x64<br/>Attribute: 3<br/>Data: 18 bytes]
    WriteMsg --> Wait[等待 0.5s]
    
    Wait --> ReadResult[讀取驗證結果]
    ReadResult --> ReadInput[從 Input Assembly<br/>讀取實際狀態與電流]
    ReadInput --> ShowResult[顯示控制結果]
    ShowResult --> End
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style CheckInit fill:#FFE4B5
    style DoBitOp fill:#FFE4B5
```

### 3.2 Byte 1 位元操作圖解

```mermaid
flowchart LR
    Byte1[Byte 1: 通道控制] --> Bit0[Bit 0: CH1]
    Byte1 --> Bit1[Bit 1: CH2]
    Byte1 --> Bit2[Bit 2: CH3]
    Byte1 --> Bit3[Bit 3: CH4]
    Byte1 --> Bits47[Bits 4-7: 保留]
    
    subgraph 範例
        Ex1[0x01 = 0b00000001<br/>→ CH1 開啟]
        Ex2[0x03 = 0b00000011<br/>→ CH1, CH2 開啟]
        Ex3[0x0F = 0b00001111<br/>→ 全部開啟]
    end
    
    style Byte1 fill:#87CEEB
    style Bit0 fill:#90EE90
    style Bit1 fill:#90EE90
    style Bit2 fill:#90EE90
    style Bit3 fill:#90EE90
```

---

## 4. 即時監控流程

### 4.1 監控啟動與運作

```mermaid
flowchart TD
    Start([monitor start 命令]) --> CheckRunning{已在運行?}
    CheckRunning -->|是| Error[錯誤: 監控已啟動]
    Error --> End([結束])
    
    CheckRunning -->|否| ParseArgs[解析參數]
    ParseArgs --> SetInterval[設定 interval<br/>預設 2.0s, 範圍 0.5-60s]
    SetInterval --> SetMode[設定 mode<br/>預設 silent]
    
    SetMode --> InitSnapshot[初始化狀態快照]
    InitSnapshot --> CreateThread[創建背景執行緒]
    CreateThread --> StartThread[啟動執行緒]
    StartThread --> ShowMsg[顯示啟動訊息]
    ShowMsg --> End
    
    StartThread -.-> Worker[監控執行緒]
    Worker --> Loop{monitor_running?}
    
    Loop -->|否| ThreadEnd[執行緒結束]
    
    Loop -->|是| ReadStatus[讀取當前狀態]
    ReadStatus --> DetectChanges[檢測狀態變化]
    DetectChanges --> CheckMode{顯示模式?}
    
    CheckMode -->|silent| HasChanges{有變化?}
    HasChanges -->|是| ShowAlerts[顯示警報]
    HasChanges -->|否| Wait
    
    CheckMode -->|display| ShowFull[顯示完整狀態]
    
    ShowAlerts --> UpdateSnapshot[更新狀態快照]
    ShowFull --> UpdateSnapshot
    UpdateSnapshot --> Wait[等待 interval 秒]
    Wait --> Loop
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style ThreadEnd fill:#FFB6C1
    style CheckMode fill:#FFE4B5
    style HasChanges fill:#FFE4B5
```

### 4.2 變化檢測機制

```mermaid
flowchart TD
    Start([檢測狀態變化]) --> Compare[比較當前與上次快照]
    
    Compare --> Check1[檢查通道狀態變化]
    Check1 --> State{開關改變?}
    State -->|是| Record1[記錄: 通道 X 開→關 / 關→開]
    State -->|否| Check2
    Record1 --> Check2
    
    Check2[檢查電流異常]
    Check2 --> Current{電流變化 > 30%?}
    Current -->|是| Record2[記錄: 電流異常警報]
    Current -->|否| Check3
    Record2 --> Check3
    
    Check3[檢查過載]
    Check3 --> Overload{電流 > 標稱電流?}
    Overload -->|是| Record3[記錄: 過載警報]
    Overload -->|否| Check4
    Record3 --> Check4
    
    Check4[檢查系統警報]
    Check4 --> System{欠壓/過壓/錯誤?}
    System -->|是| Record4[記錄: 系統警報]
    System -->|否| Return
    Record4 --> Return
    
    Return[返回變化清單] --> End([結束])
    
    style Start fill:#90EE90
    style End fill:#FFB6C1
    style State fill:#FFE4B5
    style Current fill:#FFE4B5
    style Overload fill:#FFE4B5
    style System fill:#FFE4B5
```

---

## 5. 重連機制流程

### 5.1 重連觸發與處理

```mermaid
flowchart TD
    Trigger1[連線失敗] --> ShowError[顯示錯誤訊息]
    Trigger2[使用者輸入 'reconnect'] --> StopMonitor[停止監控]
    Trigger3[異常斷線] --> ShowError
    
    ShowError --> UserPrompt{使用者選擇}
    StopMonitor --> Return[返回 'reconnect']
    
    UserPrompt -->|R: 重新連線| Return
    UserPrompt -->|Q: 退出| Exit[返回 None]
    
    Return --> MainLoop[main 迴圈檢查]
    MainLoop --> CheckResult{result == 'reconnect'?}
    
    CheckResult -->|是| ResetState[重置部分狀態]
    CheckResult -->|否| End([程式結束])
    
    ResetState --> KeepState[保留: help_shown, device_ip]
    KeepState --> ClearState[清除: channels_initialized,<br/>monitor_running, 連線]
    ClearState --> RunAgain[重新執行 run]
    RunAgain --> Step0[Step 0: 檢查裝置連線...]
    
    Exit --> End
    
    style Trigger1 fill:#FF6B6B
    style Trigger2 fill:#87CEEB
    style Trigger3 fill:#FF6B6B
    style End fill:#FFB6C1
    style CheckResult fill:#FFE4B5
```

### 5.2 幫助信息顯示邏輯

```mermaid
flowchart TD
    Start([進入命令迴圈]) --> CheckFlag{help_shown?}
    
    CheckFlag -->|False| ShowFull[顯示完整幫助信息]
    ShowFull --> SetFlag[help_shown = True]
    SetFlag --> CmdLoop
    
    CheckFlag -->|True| ShowShort[顯示簡短提示:<br/>重新連線成功，輸入 'h' 查看幫助]
    ShowShort --> CmdLoop
    
    CmdLoop[命令迴圈] --> WaitInput[等待輸入]
    WaitInput --> CheckCmd{命令?}
    
    CheckCmd -->|h / help| DisplayHelp[顯示完整幫助]
    DisplayHelp --> CmdLoop
    
    CheckCmd -->|其他| Process[處理其他命令]
    Process --> CmdLoop
    
    style Start fill:#90EE90
    style CheckFlag fill:#FFE4B5
    style CheckCmd fill:#FFE4B5
```

---

## 6. Assembly 通訊架構

### 6.1 三種 Assembly 關係

```mermaid
flowchart TB
    subgraph Controller[控制程式]
        Write[寫入控制]
        Read[讀取狀態]
        Config[配置設定]
    end
    
    subgraph CAPAROC[CAPAROC 設備]
        Output[Output Assembly<br/>0x64, 18 bytes<br/>可讀寫]
        Input[Input Assembly<br/>0x65, 244 bytes<br/>唯讀]
        ConfigAsm[Config Assembly<br/>0x66, 244 bytes<br/>唯讀*]
        ParamObj[Parameter Object<br/>Class 0x0F<br/>可讀寫]
    end
    
    Write -->|Service 0x10| Output
    Output -.->|控制執行| Device[通道硬體]
    Device -.->|狀態回報| Input
    Input -->|Service 0x0E| Read
    
    ConfigAsm -.->|僅供參考| Read
    Config -->|Service 0x10| ParamObj
    ParamObj -.->|配置生效| Device
    
    style Output fill:#90EE90
    style Input fill:#87CEEB
    style ConfigAsm fill:#FFE4B5
    style ParamObj fill:#FFD700
```

### 6.2 Input Assembly 資料結構

```mermaid
flowchart TB
    Input[Input Assembly<br/>0x65, 244 bytes]
    
    Input --> Global[全域資訊<br/>Bytes 0-5]
    Global --> B0[Byte 0: 系統狀態]
    Global --> B1[Byte 1: 模組數量]
    Global --> B23[Bytes 2-3: 總電流]
    Global --> B45[Bytes 4-5: 系統電壓]
    
    Input --> Channels[通道資訊<br/>每通道 3 bytes]
    Channels --> M1CH1[M1.CH1: Bytes 6-8]
    Channels --> M1CH2[M1.CH2: Bytes 9-11]
    Channels --> M1CH3[M1.CH3: Bytes 12-14]
    Channels --> M1CH4[M1.CH4: Bytes 15-17]
    Channels --> M2CH1[M2.CH1: Bytes 18-20]
    Channels --> More[...]
    
    M1CH1 --> CH1B0[Byte 0: Status]
    M1CH1 --> CH1B1[Byte 1: Nominal Current]
    M1CH1 --> CH1B2[Byte 2: Flowing Current]
    
    style Input fill:#87CEEB
    style Global fill:#90EE90
    style Channels fill:#FFE4B5
```

### 6.3 通訊服務代碼

```mermaid
flowchart LR
    Services[CIP Services]
    
    Services --> Read[0x0E: Get Attribute Single<br/>讀取單一屬性]
    Services --> Write[0x10: Set Attribute Single<br/>寫入單一屬性]
    Services --> FwdOpen[0x52: Forward Open<br/>建立連接 不使用]
    
    Read --> UseCase1[用於: 讀取 Assembly,<br/>讀取 Parameter]
    Write --> UseCase2[用於: 寫入 Assembly,<br/>寫入 Parameter]
    
    style Services fill:#87CEEB
    style Read fill:#90EE90
    style Write fill:#FFD700
    style FwdOpen fill:#FFB6C1
```

---

## 📊 流程圖圖例

```mermaid
flowchart LR
    Start([開始/結束]) 
    Process[處理步驟]
    Decision{判斷條件}
    Success[成功狀態]
    Error[錯誤狀態]
    Warning[警告狀態]
    
    style Start fill:#90EE90
    style Process fill:#87CEEB
    style Decision fill:#FFE4B5
    style Success fill:#90EE90
    style Error fill:#FF6B6B
    style Warning fill:#FFD700
```

**說明**:
- 🟢 綠色: 開始/結束/成功
- 🔵 藍色: 一般處理步驟
- 🟡 黃色: 判斷條件/警告
- 🔴 紅色: 錯誤/失敗
- 🟠 橙色: 重要節點

---

## 📝 使用說明

### 如何檢視 Mermaid 圖表

1. **GitHub**: 直接在 GitHub 上檢視此檔案，自動渲染
2. **VS Code**: 安裝 "Markdown Preview Mermaid Support" 擴展
3. **在線工具**: 複製到 [Mermaid Live Editor](https://mermaid.live/)
4. **其他編輯器**: 尋找支援 Mermaid 的 Markdown 預覽外掛

### 相關文檔

- [主程式流程詳解](MAIN_PROGRAM_FLOW.md) - 文字版完整說明
- [診斷工具指南](DIAGNOSTIC_TOOLS_GUIDE.md) - 診斷工具使用
- [CLI 使用指南](CLI_USER_GUIDE.md) - 命令列操作指南

---

**文檔結束**
