# 開發筆記 (Dev Notes)

---

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
