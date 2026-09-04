# tests/manual — 需實機或管理員權限的手動工具

這裡的東西**不是自動化測試**，`pytest` 也不會收集（見專案根目錄的 `pytest.ini`
的 `norecursedirs`）。它們需要真的連上設備、或需要管理員權限、或是互動式選單。

自動化測試在上一層的 `tests/*.py`，不需實機、不需網路，用 `python -m pytest` 執行。

命名慣例：`check_*.py` 為唯讀診斷，`*_tool.py` 為會改動設備的工具。

| 檔案 | 用途 | 會不會改到設備 |
|------|------|----------------|
| `check_hostname.py` | 主機名稱來源診斷：分辨畫面上的名稱來自 attr 5 的 Domain Name 還是 attr 6 的 Host Name | ❌ 唯讀 |
| `check_network_info.py` | 讀取 IP / 遮罩 / 閘道 / MAC / hostname | ❌ 唯讀 |
| `check_ip_config.py` | 互動式選單：讀取網路設定、設定靜態 IP、切換 DHCP | ⚠️ 選項 2/3 會改 |
| `check_scapy_dcp.py` | PROFINET DCP 探測（需**管理員**權限，scapy raw socket） | ❌ 唯讀 |
| `dcp_ip_config_tool.py` | DCP Identify/Set IP + mini DHCP server（需**管理員**權限） | ⚠️ 會改 |

執行方式（在專案根目錄）：

```bash
conda activate sv
python tests/manual/check_hostname.py 192.168.50.111
```

不帶 IP 時預設 `192.168.50.111`。
