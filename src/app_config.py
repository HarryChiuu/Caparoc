"""
CAPAROC 統一設定載入器
======================

**單一設定檔** `config/config.json`，取代原本散落的 `device_config.json` 與
`logging_config.json`。所有可調參數集中一處，使用者只需要編輯一個檔案。

設計要點
--------
1. **只依賴標準函式庫** — `logging_manager` 會 import 本模組，本模組不得反向
   依賴任何專案模組，否則產生循環 import。
2. **深層合併預設值** — 使用者的 `config.json` 只需寫想改的鍵，缺的一律取
   `DEFAULTS`。因此舊設定檔升級、或使用者手動刪掉某一區塊，都不會炸。
3. **讀寫分離、寫入保留其他區塊** — `save_device_ip()` 走 read-modify-write，
   不會把使用者的 logging/web 設定洗掉（舊的 `_save_default_ip()` 因為每個
   設定檔只有一個區塊，沒有這個問題；合併後必須處理）。
4. **自動遷移** — 若 `config.json` 不存在但舊檔存在，開機時自動合併產生，
   使用者不會因為升級而遺失已設定的 `default_ip`。

用法
----
    import app_config
    ip   = app_config.get("device", "default_ip")
    port = app_config.get("web", "port")
    log  = app_config.section("logging")        # 整個區塊（已合併預設值）
    app_config.save_device_ip("192.168.50.222")
    app_config.record_connection("192.168.50.222", name="CAPAROC-PM-EIP")
    hist = app_config.recent_devices()          # 最近連線過的設備，最新在前
"""

import ipaddress
import json
import shutil
from datetime import datetime
from pathlib import Path

# ─── 路徑 ────────────────────────────────────────────────────────────────────
# Phase 5.1 導入 src/paths.py 後，這三行改為引用該模組（打包成 exe 時 __file__
# 會指向暫存解壓路徑，config 必須落在 exe 旁邊）。
_ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = _ROOT_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"

# 遷移來源（合併完成後即可刪除；保留判斷是為了讓舊安裝能無痛升級）
_LEGACY_DEVICE = CONFIG_DIR / "device_config.json"
_LEGACY_LOGGING = CONFIG_DIR / "logging_config.json"


# ─── 預設值 ──────────────────────────────────────────────────────────────────
# 這裡是**所有設定的權威來源**。新增可調參數時先加在這裡，再更新
# config/config.example.json 與 docs/。
DEFAULTS: dict = {
    "device": {
        # 啟動時嘗試連線的 IP。CLI 的 `setting [3]` 與 Web 連線設定頁會寫回這裡。
        "default_ip": "192.168.2.111",
        # 最近**成功**連線過的設備，最新在前。Web 連線設定頁的 IP 下拉清單來源。
        # 每筆 {"ip", "name", "serial", "last_connected"}；後三者可為 null。
        # 放伺服器端而非 localStorage：現場換一台筆電或清瀏覽器快取就不該遺失，
        # 且打包成 exe 後這份清單跟著 config/ 一起走。
        "recent": [],
        # recent 保留筆數上限，超出淘汰最舊的一筆。
        "recent_max": 5,
    },
    "web": {
        # 預設 8001（避開 NVIDIA Overlay 間歇佔用的 8000）。
        # 覆寫優先序：--port N > 環境變數 CAPAROC_PORT > 本設定。
        "port": 8001,
        # WebSocket 狀態推送間隔（秒）。設備每次讀取約 0.3 秒，低於 0.5 意義不大。
        "ws_push_interval": 1.0,
        # 最後一個前端分頁離線後，多久自動關閉伺服器（秒）。0 = 不自動關閉。
        "ws_idle_shutdown": 10.0,
    },
    "logging": {
        "log_level": "INFO",
        "retention_days": 0,       # 0 = 永不自動清除
        "log_dir": "logs",         # 相對路徑以專案根目錄為基準，不受 CWD 影響
        "remote": {
            # 未來擴充：推送 log 到 Linux 主機。enabled 改 true 並填 url 即生效。
            "enabled": False,
            "type": "http",
            "url": "",
            "batch_size": 50,
            "flush_interval_sec": 60,
            "token": "",
        },
    },
    "nominal_current": {
        # 額定電流可設定範圍（安培，整數）。依手冊 Table 7-11 & 7-18 為 1-20A。
        # backend 的參數驗證與 Web UI 輸入欄的 min/max 都以此為準。
        "min": 1,
        "max": 20,
    },
}


# ─── 內部 ────────────────────────────────────────────────────────────────────
_cache: dict | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    """把 override 疊到 base 上，dict 遞迴合併、其餘型別直接覆寫。回傳新 dict。"""
    out = {}
    for key, val in base.items():
        if key in override and isinstance(val, dict) and isinstance(override[key], dict):
            out[key] = _deep_merge(val, override[key])
        elif key in override:
            out[key] = override[key]
        else:
            # list 也要複製：DEFAULTS 的可變物件若被共用進快取，
            # 任何一次就地修改都會污染預設值（device.recent 就是 list）。
            if isinstance(val, dict):
                out[key] = dict(val)
            elif isinstance(val, list):
                out[key] = list(val)
            else:
                out[key] = val
    # 使用者自行新增、不在 DEFAULTS 中的鍵一併保留（例如手動加的實驗性設定）
    for key, val in override.items():
        if key not in out:
            out[key] = val
    return out


def _read_json(path: Path) -> dict:
    """讀 JSON，失敗一律回空 dict（設定檔壞掉不該讓程式起不來）。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[app_config] 無法讀取 {path.name}: {e}，改用預設值")
        return {}


def _write_config(data: dict) -> bool:
    """
    把完整設定 dict 寫回 config.json 並重新載入快取。

    所有寫入路徑（save_device_ip / record_connection / forget_device_ip）都走這裡，
    避免各自複製一份 mkdir + dump + reload 的流程。
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        load(force_reload=True)
        return True
    except Exception as e:
        print(f"  ⚠️  無法寫入設定檔: {e}")
        return False


def _is_ipv4(value: str) -> bool:
    """IPv4 格式檢查。本模組不得 import 專案模組，故不重用 caparoc_ip_core.is_valid_ip。"""
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


def _sanitize_recent(raw) -> list[dict]:
    """
    把設定檔中的 device.recent 正規化成 [{ip, name, serial, last_connected}]。

    使用者手改設定檔改壞（塞成字串、缺 ip、同一台重複）都在這裡吸收掉，
    讓 API 與前端永遠拿到乾淨、無重複、順序即為新舊的清單。
    """
    out: list[dict] = []
    seen: set[str] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        ip = str(item.get("ip", "")).strip()
        if not _is_ipv4(ip) or ip in seen:
            continue
        seen.add(ip)
        out.append({
            "ip": ip,
            "name": item.get("name") or None,
            "serial": item.get("serial") or None,
            "last_connected": item.get("last_connected") or None,
        })
    return out


def _migrate_legacy() -> dict:
    """
    舊的兩個設定檔 → 合併結構。只在 config.json 不存在時呼叫。

    回傳合併後的 user config（尚未疊上 DEFAULTS）。若兩個舊檔都不存在，回空 dict。
    """
    device = _read_json(_LEGACY_DEVICE)
    logging_cfg = _read_json(_LEGACY_LOGGING)
    if not device and not logging_cfg:
        return {}

    merged: dict = {}
    if device:
        # 舊檔為扁平結構，只有 default_ip 有意義（_comment 是說明文字，丟掉）
        if "default_ip" in device:
            merged["device"] = {"default_ip": device["default_ip"]}
    if logging_cfg:
        section = {k: v for k, v in logging_cfg.items() if not k.startswith("_")}
        # write_jsonl 是死設定：JSONL handler 已於 2026-05-14 移除，無人讀取，不遷移
        section.pop("write_jsonl", None)
        if "remote" in section and isinstance(section["remote"], dict):
            section["remote"] = {k: v for k, v in section["remote"].items()
                                 if not k.startswith("_")}
        merged["logging"] = section

    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=4)
        print(f"[app_config] 已將舊設定檔合併為 {CONFIG_PATH.name}")
        # 舊檔改名保留而非刪除——遷移邏輯萬一有誤，使用者還救得回來
        for legacy in (_LEGACY_DEVICE, _LEGACY_LOGGING):
            if legacy.exists():
                shutil.move(str(legacy), str(legacy.with_suffix(".json.migrated")))
    except Exception as e:
        print(f"[app_config] 寫入合併設定檔失敗: {e}（本次仍以合併結果執行）")

    return merged


# ─── 公開 API ────────────────────────────────────────────────────────────────
def load(force_reload: bool = False) -> dict:
    """
    載入完整設定（DEFAULTS 疊上使用者的 config.json）。結果會快取。

    Args:
        force_reload: True = 忽略快取重新讀檔（測試或熱重載用）
    """
    global _cache
    if _cache is not None and not force_reload:
        return _cache

    user_cfg = _read_json(CONFIG_PATH)
    if not user_cfg and not CONFIG_PATH.exists():
        user_cfg = _migrate_legacy()

    _cache = _deep_merge(DEFAULTS, user_cfg)
    return _cache


def section(name: str) -> dict:
    """取得一個設定區塊（已合併預設值）。未知區塊回空 dict。"""
    return load().get(name, {})


def get(section_name: str, key: str, default=None):
    """取得單一設定值。區塊或鍵不存在時回 default（None 則回 DEFAULTS 中的值）。"""
    val = section(section_name).get(key, default)
    if val is None and default is None:
        return DEFAULTS.get(section_name, {}).get(key)
    return val


def nominal_range() -> tuple[int, int]:
    """額定電流可設定範圍 (min, max)，安培整數。"""
    cfg = section("nominal_current")
    return int(cfg.get("min", 1)), int(cfg.get("max", 20))


def save_device_ip(ip: str) -> bool:
    """
    將 IP 寫回 config.json 的 device.default_ip。

    走 read-modify-write 並**保留檔案中其他所有區塊**——合併設定檔後，
    直接覆寫整個檔案會洗掉使用者的 logging/web 設定。
    """
    data = _read_json(CONFIG_PATH)
    data.setdefault("device", {})["default_ip"] = ip
    return _write_config(data)


def recent_max() -> int:
    """recent 清單保留筆數。夾在 1~50 之間，避免設定檔填 0 或天文數字。"""
    try:
        n = int(section("device").get("recent_max", 5))
    except (TypeError, ValueError):
        n = 5
    return max(1, min(n, 50))


def recent_devices() -> list[dict]:
    """最近成功連線過的設備，最新在前。清單已正規化，可直接餵給 API。"""
    return _sanitize_recent(section("device").get("recent"))


def record_connection(ip: str, name: str | None = None,
                      serial: str | None = None) -> list[dict]:
    """
    記錄一次**成功**的連線：把該 IP 移到清單最前、更新時間，並同步 default_ip。

    只在連線成功後呼叫——打錯的位址不該污染下拉清單，那正是這個功能要省掉的麻煩。
    同一 IP 永遠只留一筆；未帶 name/serial 時沿用該筆舊值（讀不到識別資訊的
    連線路徑不會把既有的設備名洗成 null）。

    Returns:
        更新後的清單（寫檔失敗時為記憶體中的舊清單，呼叫端不必特別處理）。
    """
    if not _is_ipv4(ip):
        return recent_devices()

    data = _read_json(CONFIG_PATH)
    device = data.setdefault("device", {})
    entries = _sanitize_recent(device.get("recent"))
    prev = next((e for e in entries if e["ip"] == ip), {})

    entries = [e for e in entries if e["ip"] != ip]
    entries.insert(0, {
        "ip": ip,
        "name": name or prev.get("name"),
        "serial": serial or prev.get("serial"),
        # 本地時間、秒精度。前端只拿來顯示「幾分鐘前 / 昨天 14:22」，不做時區換算。
        "last_connected": datetime.now().isoformat(timespec="seconds"),
    })
    device["recent"] = entries[:recent_max()]
    device["default_ip"] = ip
    _write_config(data)
    return recent_devices()


def forget_device_ip(ip: str) -> list[dict]:
    """
    從最近連線清單移除一筆。

    **不動 default_ip**：那是下次開機要連的位址，與「這台不想再出現在下拉清單」
    是兩件事；使用者若要換預設值，連線一次新設備即可。
    """
    data = _read_json(CONFIG_PATH)
    device = data.setdefault("device", {})
    entries = _sanitize_recent(device.get("recent"))
    remaining = [e for e in entries if e["ip"] != ip]
    if len(remaining) != len(entries):
        device["recent"] = remaining
        _write_config(data)
    return recent_devices()
