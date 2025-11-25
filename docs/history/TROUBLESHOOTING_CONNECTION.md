# 連接問題排查指南

## ❌ 錯誤: "failed to send message"

這個錯誤表示無法與設備建立網路連接。

## 🔍 快速診斷

### 步驟 1: 運行診斷工具
```bash
python check_connection.py
```

這會自動檢查:
- ✅ 網路連通性 (ping)
- ✅ EtherNet/IP 埠號 (44818)
- ✅ pycomm3 安裝
- ✅ CIP 連接測試

### 步驟 2: 手動檢查

#### 2.1 檢查網路連通性
```bash
ping 192.168.2.111
```

**預期結果:**
```
Reply from 192.168.2.111: bytes=32 time<1ms TTL=128
```

**如果失敗:**
- ❌ 檢查網路線是否插好
- ❌ 檢查設備電源
- ❌ 確認 IP 位址正確
- ❌ 檢查電腦與設備是否在同一網段

#### 2.2 檢查 IP 設定

**電腦 IP 設定應該是:**
- IP: 192.168.2.xxx (例如 192.168.2.100)
- 子網路遮罩: 255.255.255.0
- 預設閘道: 192.168.2.1 (或留空)

**設備 IP:**
- IP: 192.168.2.111

#### 2.3 檢查防火牆

**Windows 防火牆:**
1. 控制台 → Windows Defender 防火牆
2. 進階設定 → 輸入規則
3. 新增規則 → 連接埠
4. TCP/UDP Port 44818
5. 允許連線

**或暫時關閉防火牆測試:**
```powershell
# PowerShell (需要管理員權限)
Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False
```

## 📋 常見問題與解決方案

### 問題 1: Ping 失敗
```
❌ Request timed out
```

**解決方案:**
1. 檢查網路線連接
2. 檢查設備電源開關
3. 確認設備 IP 設定 (192.168.2.111)
4. 檢查電腦 IP 是否在同一網段 (192.168.2.x)

### 問題 2: Port 44818 未開放
```
❌ 埠號未開放 (Port 44818)
```

**解決方案:**
1. 重啟設備 (完全斷電再開機)
2. 檢查設備是否啟用 EtherNet/IP
3. 檢查防火牆設定
4. 使用官方工具測試 (如 RSLinx)

### 問題 3: pycomm3 未安裝
```
❌ ModuleNotFoundError: No module named 'pycomm3'
```

**解決方案:**
```bash
pip install pycomm3
```

### 問題 4: CIP 連接失敗
```
❌ failed to send message
```

**解決方案:**
1. 確認前面的 ping 和 port 檢查都通過
2. 重啟設備
3. 檢查 EDS 檔案是否正確
4. 嘗試使用其他 EtherNet/IP 工具測試

## 🔧 進階排查

### 使用 Wireshark 抓包

1. **安裝 Wireshark**
   - https://www.wireshark.org/

2. **抓取 EtherNet/IP 封包**
   - 篩選器: `tcp.port == 44818 || udp.port == 44818`
   - 或: `enip`

3. **檢查封包內容**
   - 查看是否有 "Register Session" 訊息
   - 查看設備回應

### 檢查網路卡設定

**Windows:**
```powershell
# 查看網路卡設定
ipconfig /all

# 查看路由表
route print
```

**確認:**
- IP 位址在 192.168.2.x 範圍
- 子網路遮罩是 255.255.255.0
- 沒有衝突的路由

## 📞 設備設定檢查

### 預設 IP 設定

**CAPAROC 預設 IP 可能是:**
- 192.168.1.111
- 或需要透過 DIP 開關設定

**如果 IP 不對:**
1. 查看設備手冊
2. 使用官方設定工具
3. 檢查 DIP 開關設定

## ✅ 驗證連接成功

**成功連接的標誌:**
```
✅ 網路連通 (ping 成功)
✅ 埠號開放 (Port 44818)
✅ pycomm3 已安裝
✅ CIP 連接成功!
```

**然後可以運行:**
```bash
python example_main_power_control.py
```

## 🆘 仍然失敗?

### 最後手段檢查清單

- [ ] 設備電源確實開啟
- [ ] 網路線確實插好 (兩端都亮燈)
- [ ] 電腦 IP 設定正確 (192.168.2.x)
- [ ] 設備 IP 設定正確 (192.168.2.111)
- [ ] 防火牆已關閉或允許 Port 44818
- [ ] 沒有其他程式佔用該設備
- [ ] 設備支援 EtherNet/IP (檢查 EDS 檔案)
- [ ] Python 環境正確 (python --version)
- [ ] pycomm3 已安裝 (pip list | grep pycomm3)

### 替代方案

如果仍然無法連接:
1. 使用官方工具 (如 Rockwell RSLinx) 測試
2. 檢查設備韌體版本
3. 聯絡設備供應商技術支援
4. 檢查設備是否需要特殊設定

## 📚 相關工具

- `check_connection.py` - 自動診斷工具
- `example_main_power_control.py` - 主開關控制範例
- Wireshark - 網路封包分析
- RSLinx - Rockwell 官方工具 (如果適用)
