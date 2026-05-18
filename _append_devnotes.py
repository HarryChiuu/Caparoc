"""
append_devnotes.py - 一次性：追加 4.2.3 開發備忘錄
"""
import pathlib

ROOT = pathlib.Path(__file__).parent
notes_path = ROOT / "docs" / "DEVELOPMENT_NOTES.md"

NEW_SECTION = """

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
"""

existing = notes_path.read_text(encoding="utf-8")
notes_path.write_text(existing.rstrip() + NEW_SECTION + "\n", encoding="utf-8")
print(f"✓ 追加 DEVELOPMENT_NOTES.md（{len(existing.splitlines())} → {len((existing.rstrip() + NEW_SECTION).splitlines())} 行）")
