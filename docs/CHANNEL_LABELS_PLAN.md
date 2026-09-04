# 4.3.6 通道自訂標籤 — 實作規劃

> **狀態**：規劃中（2026-09-04），尚未動工
> **目的**：讓使用者為每個通道命名（「主機電源」「照明迴路」），標籤綁定到**物理設備**，
> 換 IP、換筆電都不會跑掉
> **預估工時**：3-4h（原估 2-3h，見下方「與原規劃的差異」）

---

## 一、現況盤點（動工前已逐一確認）

TODO 的 4.3.6 原規劃寫於 config 架構統一之前，有數項前提已經改變。以下是**實際查證**的結果：

| 項目 | 現況 | 對規劃的影響 |
|---|---|---|
| Serial Number 取得 | `get_device_info()` → `identity.serial_number`（UDINT），走 CIP `0x01/1/attr6` | 可用，但**多次 CIP 讀取，不便宜** |
| 既有 S/N 使用範例 | `_probe_cache_key()`（`caparoc_backend.py`）：`sn:<serial>`，讀不到退回 `ip:<ip>` | **直接沿用這個 key 慣例與 fallback 策略** |
| config 架構 | 已統一為 `config/config.json` + `src/app_config.py` | 原規劃的獨立 `channel_labels.json` **需重新評估** |
| `device.recent` | 已存 `{ip, name, serial, last_connected}`，serial 為**字串** | S/N 已經在 config 裡了，型別要對齊 |
| backend 是否快取 S/N | **否**，每次都重讀 CIP | 這是本規劃最關鍵的限制 |
| `_format_status()` | 在 WebSocket 迴圈中**每秒**執行一次 | 標籤**不可**放進每秒 payload |
| 前端存檔慣例 | `setNominal()`：`busy` + `feedback` + 3 秒後清訊息 | 標籤存檔沿用同一套 UX |
| Demo 模式 | 債 #10：每個端點都要手寫 `_DEMO_MODE` 分支 | 新端點必須一併處理，否則 `--demo` 靜默壞掉 |

實機 S/N 實例（`config.json`）：`"serial": "1378815610"`。

---

## 二、三個關鍵設計決策

原規劃的 5 個 Step 是「做什麼」，但沒回答下面三個「怎麼做才不會出事」。這三項才是實作前真正該定的。

### 決策 1：標籤存哪裡 —— 併入 `config.json`，不另開檔案

原規劃寫 `config/channel_labels.json`（獨立檔）。但 config 架構在那之後已經統一，
**再開一個檔就是回頭走分裂的老路**（`device_config.json` / `logging_config.json` 已經
被合併掉，`config/` 底下還留著兩個 `.migrated` 檔就是證據）。

**採用**：存進 `config.json` 的新區塊 `labels`，經 `app_config` 讀寫。

```jsonc
"labels": {
  "1378815610": {                    // key = Serial Number（字串，與 device.recent 對齊）
    "device_label": "一號配電箱",
    "channels": { "1": "主機電源", "2": "照明迴路" }
  }
}
```

**理由**：
- 沿用既有的 `_write_config()`（已有原子寫入與錯誤處理），不必重寫一套存檔
- 打包成 exe 後跟著 `config/` 一起走，與 `device.recent` 同一份檔，行為一致
- 使用者只需要備份一個檔

**取捨**：標籤多起來會讓 `config.json` 變大。但每台設備最多 64 通道，以每則標籤 20 字估，
單台約 2KB，可接受。若日後真的要拆檔，`app_config` 已是唯一存取點，屆時只改一處。

### 決策 2：標籤**不進**每秒 payload —— 獨立端點 + 前端合併

原規劃的 Step 2 寫「`_format_status()` 每個 channel 加入 `label` 欄位」。
**這一項不採用。**

`_format_status()` 在 WebSocket 迴圈中每秒執行（`ws_push_interval` 預設 1.0），
把靜態文字塞進去等於**每天推 86,400 次不會變的字串**；8 通道每則 20 字約 320 bytes/秒。
更糟的是為了填 label 就得知道 S/N，而 backend 不快取 S/N，
等於**每秒多一次 CIP 讀取**去搶 `_cip_lock`——那正是先前批次設定額定電流時
特意避開的問題（見 `postNominalBatch` 的註解）。

**採用**：
- 標籤走**獨立端點** `GET /api/labels`，只在連線成功後與存檔後各取一次
- 前端以 `channelLabels[chId]` 存放，渲染時與 `state.channels` 合併
- payload 結構完全不動 → `test_demo_payload.py` 的既有把關不受影響

### 決策 3：S/N 讀不到時的行為 —— 沿用 `_probe_cache_key()` 的 fallback

S/N 讀取可能失敗（設備不支援、CIP 逾時）。既有程式已經有一套處理方式，**照抄即可**：

```python
sn:<serial>   # 讀得到 → 綁定物理設備，換 IP 標籤跟著走
ip:<ip>       # 讀不到 → 退回 IP，同一台換 IP 會失聯（可接受，與探測快取同樣的取捨）
```

**但要多做一件 `_probe_cache_key()` 沒做的事**：S/N 讀取成本高，而標籤要頻繁查，
因此**連線成功後把 key 快取在 web 層**（不是 backend），斷線時清掉。
這樣 `GET /api/labels` 與 `POST` 都不必重讀 CIP。

> ⚠️ 快取放 web 層而非 backend，是為了不動 backend 的既有介面。
> backend 目前沒有「當前設備身分」的概念，貿然加會影響 CLI。

---

## 三、實作步驟

> 順序刻意由後端往前端，每一步都可獨立驗證。

### Step 1 — `src/app_config.py`（約 40 行）

- [ ] `DEFAULTS` 新增 `"labels": {}` 區塊
- [ ] `device_labels(key: str) -> dict`：讀單一設備的標籤，無資料回 `{"device_label": "", "channels": {}}`
- [ ] `save_channel_label(key: str, channel_id: int, text: str) -> bool`
- [ ] `save_device_label(key: str, text: str) -> bool`
- [ ] 輸入清理：`strip()`、長度上限 **32 字**、空字串等同刪除該鍵（不要在 config 裡留一堆空字串）
- [ ] 沿用既有 `_write_config()`

### Step 2 — `web/app.py`（約 60 行）

- [ ] `_device_label_key()`：回傳 `sn:...` / `ip:...`，**連線後快取**，斷線清除
- [ ] `GET /api/labels` → `{"key": ..., "device_label": ..., "channels": {...}}`
- [ ] `POST /api/labels/channel/{channel_id}`（body: `{"text": ...}`）
- [ ] `POST /api/labels/device`
- [ ] **三個端點都要寫 `_DEMO_MODE` 分支**（債 #10）：demo 下用 `ip:demo` 當 key，
      可正常讀寫，讓 `--demo` 能完整檢視這個 UI
- [ ] `_format_status()` **不動**

### Step 3 — `web/static/js/app.js`（約 50 行）

- [ ] `const channelLabels = reactive({})`、`const deviceLabel = ref('')`
- [ ] `fetchLabels()`：掛在**既有的斷→通轉換點**（`app.js:154` 的
      `if (!_wasConnected && state.connected)`，`fetchNetworkInfo()` / `fetchDeviceInfo()` 旁邊）。
      **不要**放進 `onMounted()`——那裡的 `fetchLimits()` 是刻意不等連線的（純設定值），
      但標籤要先有 S/N 才知道查哪一台，未連線時查不到
- [ ] `saveLabel(chId, text)`：沿用 `setNominal()` 的 `busy` + `feedback` 慣例
- [ ] `labelBusy` / `labelFeedback` 兩個 reactive
- [ ] `return {}` 補上新符號（Vue 3 CDN 無 build step，漏加就是靜默失效）

### Step 4 — `web/templates/index.html`

- [ ] 儀表板卡片：`CH{{ ch.channel }}` 下方加標籤，點擊變輸入框，`@blur` 存檔
- [ ] 通道設定頁：新增「名稱」欄（放在 `td-ch` 之後）
- [ ] 系統狀態頁：設備標籤（`device_label`）
- [ ] **`?v=` 版號不必手動改**——已由 `src/version.py` 統一（債 #11 已收）

### Step 5 — `web/static/css/style.css`

- [ ] `.ch-label`：卡片內小字，未命名時顯示淡色提示文字
- [ ] `.ch-label-input`：編輯態
- [ ] 深色/淺色主題都要試（既有 CSS 有 `data-theme` 切換）

### Step 6 — 測試（`tests/test_channel_labels.py`，約 80 行）

- [ ] `app_config` 層：存讀往返、長度上限、空字串刪除、S/N key 隔離（兩台設備標籤不互相污染）
- [ ] key fallback：有 S/N 用 `sn:`、無 S/N 用 `ip:`
- [ ] **payload 不受污染**：確認 `_format_status()` 沒有多出 `label` 欄位
      （防止日後有人「順手」加回去，把每秒推送撐大）
- [ ] demo 模式：三個端點都不回 500

---

## 四、與原規劃的差異（需確認）

| 項目 | 原規劃 | 本規劃 | 理由 |
|---|---|---|---|
| 儲存位置 | 獨立 `channel_labels.json` | 併入 `config.json` 的 `labels` 區塊 | config 架構已統一，不再分裂 |
| 標籤傳遞 | `_format_status()` 加 `label` 欄位 | 獨立端點，前端合併 | 避免每秒推送靜態文字＋每秒多一次 CIP 讀取 |
| S/N 取得 | 未說明 | 連線後快取 key，沿用 `_probe_cache_key()` 的 fallback | S/N 讀取成本高，且要處理讀不到的情況 |
| Demo 模式 | 未提及 | 三個端點都寫分支 | 債 #10，否則 `--demo` 靜默壞掉 |
| 測試 | 未提及 | 6 類測試 | 本專案慣例（新功能都附測試） |
| 工時 | 2-3h | 3-4h | 多了測試與 demo 分支 |

---

## 五、風險與已知限制

1. **S/N 讀不到時退回 IP**：同一台設備換 IP 後標籤會「不見」（實際是存在舊 key 底下）。
   與額定電流探測快取是同樣的取捨，一致即可，不另做遷移機制。
2. **無多使用者衝突處理**：兩個瀏覽器同時改同一個標籤，後存的贏。
   單機工具，不值得為此加鎖。
3. **標籤不同步到設備**：純本機資料。CAPAROC 的 CIP 物件沒有可寫的通道名稱欄位，
   換一台電腦要重新輸入（或複製 `config.json`）。**這點要寫進使用者文件**，
   否則使用者會期待標籤跟著設備走。

---

## 六、驗證方式

- 開發：`--demo` 模式完整走一遍（三個端點 + 兩個頁面 + 兩種主題）
- 實機：連上 `192.168.50.111`（S/N `1378815610`），確認標籤存檔後重啟仍在
- 換 IP 測試：把設備 IP 改掉再連，標籤應**跟著 S/N 走**（這是本功能的核心賣點，必測）
- 回歸：`python -m pytest`（目前 37 項）、`ruff check .`
