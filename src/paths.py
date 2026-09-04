#!/usr/bin/env python3
"""
路徑解析 — 全專案唯一真相來源（Phase 5.1，打包前置）。

── 為什麼需要這支模組 ──────────────────────────────────────────────
各模組原本各自用 `Path(__file__).parent.parent` 定位專案根目錄。**開發模式下
這些寫法全部正常，問題只在打包成 exe 後才浮現**：PyInstaller 會把程式解壓到
一個每次啟動都不同的暫存目錄，`__file__` 指向那裡，於是

  - config 讀不到使用者在 exe 旁邊編輯的 config.json（設定形同無法修改）
  - log 寫進暫存目錄，程式一關就隨目錄消失（現場出事沒有記錄可查）
  - 額定電流探測快取永不命中 → **每次連線都對真實設備做一輪寫入／還原**

最後一項有實際副作用，不只是「慢一點」。

── 兩種路徑，方向相反（設計時最關鍵的區分）────────────────────────
把兩者混為一談是這類重構最容易犯的錯，因此本模組刻意用兩個不同的 base：

  **內嵌資源** RESOURCE_DIR（跟著 exe 走，唯讀）
      web/templates、web/static（含 vendor/）
      frozen 時 → sys._MEIPASS（PyInstaller 的暫存解壓目錄）

  **外部資料** DATA_DIR（放在 exe 旁邊，使用者可讀寫）
      config/、logs/
      frozen 時 → Path(sys.executable).parent（exe 所在目錄）

開發模式下兩者都等於專案根目錄，所以行為與改動前完全一致。

── 使用方式 ────────────────────────────────────────────────────────
    from paths import CONFIG_DIR, LOG_DIR, WEB_DIR, resource_path, data_path

    CONFIG_DIR / "config.json"      # 外部，使用者可編輯
    WEB_DIR / "templates"           # 內嵌，唯讀

⚠️ 不要在這裡 import 任何專案模組。本模組被 app_config、logging_manager、
caparoc_backend 與 web/app.py 共用，且必須早於它們載入，保持零相依才安全。
"""

import sys
from pathlib import Path

# ─── frozen 偵測 ─────────────────────────────────────────────────────────────
# PyInstaller 會設定 sys.frozen=True 與 sys._MEIPASS。兩者都檢查：
# 其他打包工具（cx_Freeze 等）也設 sys.frozen 但不一定有 _MEIPASS。
IS_FROZEN: bool = getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _resource_base() -> Path:
    """內嵌資源的根目錄（唯讀，跟著執行檔走）。"""
    if IS_FROZEN:
        return Path(sys._MEIPASS)           # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def _data_base() -> Path:
    """外部資料的根目錄（可讀寫，使用者看得到、改得到）。"""
    if IS_FROZEN:
        # exe 所在目錄。用 sys.executable 而非 sys.argv[0]——後者可被呼叫端
        # 改寫，且從捷徑或服務啟動時不一定是完整路徑。
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# ─── 對外常數 ────────────────────────────────────────────────────────────────
RESOURCE_DIR: Path = _resource_base()   # 內嵌資源根目錄
DATA_DIR: Path = _data_base()           # 外部資料根目錄

# 開發模式下 RESOURCE_DIR == DATA_DIR == 專案根目錄。保留 ROOT_DIR 這個名字
# 是為了讓「就是專案根目錄」的既有語意有地方對應；新程式碼請直接用下面四個
# 語意明確的常數，不要再用 ROOT_DIR 自行拼路徑。
ROOT_DIR: Path = DATA_DIR

CONFIG_DIR: Path = DATA_DIR / "config"      # 使用者可編輯的設定
LOG_DIR: Path = DATA_DIR / "logs"           # 預設 log 目錄（可被 config 的 log_dir 覆寫）
WEB_DIR: Path = RESOURCE_DIR / "web"        # templates / static 的所在


def resource_path(*parts: str) -> Path:
    """組出內嵌資源路徑（唯讀）。例：resource_path("web", "static")"""
    return RESOURCE_DIR.joinpath(*parts)


def data_path(*parts: str) -> Path:
    """組出外部資料路徑（可讀寫）。例：data_path("config", "config.json")"""
    return DATA_DIR.joinpath(*parts)


def resolve_data_dir(value: str | Path, default: Path) -> Path:
    """
    把設定檔裡的目錄值解析成絕對路徑。

    絕對路徑原樣採用（使用者明確指定就尊重）；相對路徑一律以 DATA_DIR 為基準，
    **不受當下工作目錄影響**——否則從不同 CWD 啟動會寫到不同地方。
    空值回傳 default。

    logging_manager 的 log_dir 用這支；未來若有其他可設定目錄也走同一套。
    """
    if not value:
        return default
    p = Path(value)
    return p if p.is_absolute() else DATA_DIR / p
