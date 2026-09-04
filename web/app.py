#!/usr/bin/env python3
"""
CAPAROC Web UI 服務 (Phase 4.0)

直接執行（自動開啟瀏覽器）：
    python web/app.py

Demo 模式（不需要實際設備）：
    python web/app.py --demo

或用 uvicorn（從專案根目錄）：
    uvicorn web.app:app --reload --port 8000
"""

import sys
import os
import math
import time
import signal
import asyncio
import threading
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import date as _date, datetime as _datetime
from pathlib import Path

# ==================== Demo 模式旗標 ====================
_DEMO_MODE: bool = "--demo" in sys.argv
_demo_tick: int = 0  # 每秒遞增，用於電流波形模擬

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ==================== 路徑設定 ====================
# 這兩個只用於 bootstrap（把 src/ 加進 sys.path），不再用於存取任何檔案。
_WEB_DIR = Path(__file__).parent
_ROOT_DIR = _WEB_DIR.parent
sys.path.insert(0, str(_ROOT_DIR / "src"))

# Phase 5.1：上面兩行只用來把 src/ 加進 sys.path（bootstrap，必須先於任何專案
# import）。實際存取檔案一律改用 paths 的常數——**內嵌資源與外部資料方向相反**，
# 打包後不可共用同一個 base：
#   WEB_DIR  (templates/static) → sys._MEIPASS，跟著 exe 走、唯讀
#   LOG_DIR  (logs)             → exe 旁邊，使用者看得到
from paths import WEB_DIR, LOG_DIR, resolve_data_dir  # noqa: E402

# stdout 被導向檔案／pipe 時（排程啟動、`> run.log`）編碼會退回 cp950，
# 任何一個 emoji 都會拋 UnicodeEncodeError 並被外層 except 當成操作失敗。
# 必須早於任何輸出，故緊接在 sys.path 設定之後。
from console_io import force_safe_stdio  # noqa: E402

force_safe_stdio()

from caparoc_backend import CaparocBackend  # noqa: E402
# 設備探索／IP 格式判斷的共用實作（與 src/caparoc_ip_config.py CLI 同一份）
from caparoc_ip_core import (  # noqa: E402
    discover, is_valid_ip, wait_for_device, list_interfaces,
    open_dhcp_socket, detect_dhcp_macs, serve_dhcp, iface_mac_for, normalize_mac,
)
# 原廠 Web 介面（HTTP/80，與 CIP 完全獨立）的補充唯讀資訊：硬體清單 / 韌體版本 /
# LED 狀態 / 每模組故障事件記憶。純函式，任何失敗回 None，不 raise。
import caparoc_http  # noqa: E402
import app_config  # noqa: E402
from logging_manager import cleanup_old_logs as _cleanup_old_logs  # noqa: E402
# 前端資源 cache-busting 版號的唯一真相來源（原本手寫在 index.html 兩處，見 src/version.py）
from version import ASSET_VERSION  # noqa: E402

# 同時只允許一次網段掃描：掃描會開 32 條探測執行緒，兩個分頁同時按會互相干擾
_discover_lock = threading.Lock()
# UDP port 67 是獨佔資源，MAC 偵測與迷你 DHCP server 都要用，必須互斥
_dhcp_lock = threading.Lock()
# 手動中斷旗標：DHCP 監聽／服務都是長時間阻塞作業，只讓前端放棄請求是不夠的——
# 伺服器執行緒會繼續佔著 UDP/67 與 _dhcp_lock 直到逾時，使用者無法重試。
# 每次作業開始前 clear()，由 POST /api/ipconfig/dhcp-cancel 設定。
_dhcp_cancel = threading.Event()

# ==================== Log 攔截器 ====================
import re as _re  # noqa: E402

# 自訂 SYSTEM 等級（25，介於 INFO=20 與 WARNING=30 之間）
_SYSTEM_LEVEL = 25
logging.addLevelName(_SYSTEM_LEVEL, "SYSTEM")

# 記憶體 log 緩衝（最多 500 筆，FIFO）
_LOG_BUFFER: deque = deque(maxlen=500)
_log_serial = 0

# 歷史資料緩衝（30 分鐘 × 1 次/秒 = 1800 筆）
_history_buffer: deque = deque(maxlen=1800)

# 解析 .log 檔行格式：2026-05-18 14:30:00 [INFO] [SYS] 訊息
_LOG_LINE_RE = _re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(\w+)\] \[([^\]]+)\] (.+)$"
)


def _preload_log_file(max_lines: int = 400) -> None:
    """啟動時預載今日 .log 檔（最新 max_lines 筆），讓網頁可看到歷史記錄。"""
    global _log_serial
    today = _date.today().strftime("%Y-%m-%d")
    # 讀的是 logging_manager 寫出來的同一批檔案，因此目錄解析必須一致：
    # 走 config 的 logging.log_dir（相對路徑以 DATA_DIR 為基準），而不是寫死 "logs"。
    # 原本硬編 _ROOT_DIR / "logs"，使用者一旦改了 log_dir，本頁就靜默空白。
    log_path = resolve_data_dir(app_config.get("logging", "log_dir"), LOG_DIR) / f"caparoc_{today}.log"
    if not log_path.exists():
        return
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = lines[-max_lines:]          # 取最後 N 行
        for line in recent:
            m = _LOG_LINE_RE.match(line)
            if not m:
                continue
            date_str, time_str, level, _module, msg = m.groups()
            _log_serial += 1
            _LOG_BUFFER.append({
                "id":     _log_serial,
                "ts":     0,              # 歷史記錄不需要精確 epoch
                "time":   time_str,
                "level":  level,
                "logger": "caparoc",
                "msg":    msg,
            })
    except Exception:
        pass


class _CaparocLogHandler(logging.Handler):
    """攔截 caparoc logger，將記錄寫入記憶體 buffer。"""

    _TIME_FMT = "%H:%M:%S"

    def emit(self, record: logging.LogRecord):
        global _log_serial
        try:
            _log_serial += 1
            _LOG_BUFFER.append({
                "id":     _log_serial,
                "ts":     record.created,
                "time":   _datetime.fromtimestamp(record.created).strftime(self._TIME_FMT),
                "level":  record.levelname,
                "logger": record.name,
                "msg":    record.getMessage(),
            })
        except Exception:
            pass


# 預載今日歷史記錄（在 addHandler 前，避免重複寫入）
_preload_log_file()

_log_handler = _CaparocLogHandler()
_log_handler.setLevel(logging.DEBUG)
# 掛載到 caparoc 根 logger（含 caparoc.web 子層）
logging.getLogger("caparoc").addHandler(_log_handler)

_WEB_LOGGER = logging.getLogger("caparoc.web")

# ==================== 全域設定 ====================
# 統一設定檔 config/config.json（見 src/app_config.py）。缺鍵一律取 DEFAULTS，
# 設定檔不存在或壞掉也不會讓服務起不來。
_default_ip = app_config.get("device", "default_ip")
_WEB_CFG = app_config.section("web")
_WS_PUSH_INTERVAL = float(_WEB_CFG.get("ws_push_interval", 1.0))
_NOMINAL_MIN, _NOMINAL_MAX = app_config.nominal_range()

backend = CaparocBackend(_default_ip)


# ==================== Lifespan ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """服務啟動時清除舊 log 並嘗試連線；停止時安全斷線。"""
    # 舊 log 清除：唯一的觸發點。config 的 logging.retention_days 為 0 時不做事。
    # 放在 demo 判斷之前——log 保留策略與有沒有接設備無關。
    try:
        removed = await asyncio.to_thread(_cleanup_old_logs)
        if removed:
            _WEB_LOGGER.log(_SYSTEM_LEVEL,
                            f"啟動清除 {len(removed)} 個舊 log 檔",
                            extra={'log_module': 'WEB'})
    except Exception as e:
        # 清不掉舊 log 不該擋住服務啟動
        _WEB_LOGGER.warning(f"舊 log 清除失敗: {e}", extra={'log_module': 'WEB'})

    if _DEMO_MODE:
        _WEB_LOGGER.warning("*** DEMO 模式：使用模擬資料，不連線實際設備 ***",
                             extra={'log_module': 'WEB'})
        yield
        return
    _WEB_LOGGER.log(_SYSTEM_LEVEL, f"Web 服務啟動，嘗試連線至 {backend.device_ip}...",
                     extra={'log_module': 'WEB'})
    # 啟動時連線失敗不阻斷服務，可透過 POST /api/connect 手動連線
    try:
        ok = await asyncio.to_thread(backend.connect)
        if ok:
            _WEB_LOGGER.log(_SYSTEM_LEVEL, f"設備連線成功 ({backend.device_ip})",
                             extra={'log_module': 'WEB'})
            # 開機自動連上的也算一次成功連線，更新時間戳讓下拉清單排序正確
            await asyncio.to_thread(_remember_connection)
        else:
            _WEB_LOGGER.warning(f"設備連線失敗 ({backend.device_ip})，可透過連線設定頁手動重試",
                                extra={'log_module': 'WEB'})
    except Exception as e:
        _WEB_LOGGER.error(f"啟動連線例外: {e}", extra={'log_module': 'WEB'})
    yield
    _WEB_LOGGER.log(_SYSTEM_LEVEL, "Web 服務關閉中...", extra={'log_module': 'WEB'})
    # 用 daemon 執行緒執行斷線，避免 pycomm3 socket 阻塞時卡死終端機
    _t = threading.Thread(target=backend.disconnect, daemon=True)
    _t.start()
    try:
        await asyncio.to_thread(_t.join, 3.0)  # 最多等 3 秒；daemon 執行緒不阻止進程退出
    except Exception:
        pass


# ==================== 應用程式實例 ====================
app = FastAPI(
    title="CAPAROC Web UI",
    description="CAPAROC 電子斷路器遠端控制介面",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


# ==================== 狀態格式化輔助 ====================
def _format_status(raw: dict | None) -> dict:
    """將 _read_current_status() 輸出轉換為前端友善格式。"""
    if raw is None:
        return {"connected": False, "device_ip": backend.device_ip, "error": "讀取失敗"}

    global_byte = raw.get("global_status_byte", 0)
    channels_raw = raw.get("channels", {})

    channels = [
        {
            "id":           ch_id,
            "module":       ch["module"],
            "channel":      ch["channel"],
            "on":           ch["is_on"],
            "current_amps": round(ch["flowing_current"], 2),
            "nominal_amps": round(ch["nominal_current"], 1),
            "nominal_readonly": backend.is_module_nominal_readonly(ch["module"]),
            # 型號標示的可調範圍；HTTP 讀不到型號時為 None，前端退回全域 limits
            "nominal_min": (backend.get_module_nominal_range(ch["module"]) or (None, None))[0],
            "nominal_max": (backend.get_module_nominal_range(ch["module"]) or (None, None))[1],
            # 固定額定型號的安培數；可調型為 None。反灰原因由此區分
            "nominal_fixed": backend.get_module_fixed_nominal(ch["module"]),
            "warn_80":      ch["warning_80"],
            "overload":     ch["overload"],
            "short_circuit": ch["short_circuit"],
            "hardware_fault": ch["hardware_fault"],
            "total_shutdown": ch["total_shutdown"],
        }
        for ch_id, ch in sorted(channels_raw.items())
    ]

    return {
        "connected":      True,
        "device_ip":      backend.device_ip,
        "module_count":   raw.get("module_count", 0),
        "voltage":        round(raw.get("voltage", 0.0), 2),
        "total_current":  round(raw.get("total_current", 0.0), 2),
        "undervoltage":   bool(global_byte & 0x01),
        "overvoltage":    bool(global_byte & 0x02),
        "system_error":   bool(global_byte & 0x04),
        "warn_80_global": bool(global_byte & 0x08),
        "total_shutdown": bool(global_byte & 0x10),
        "channels":       channels,
        "timestamp":      raw.get("timestamp"),
    }


# ==================== 頁面路由 ====================
def _render_index() -> str:
    """讀入 index.html 並把 `{{ app_version }}` 換成 src/version.py 的版號。

    只做這一個佔位符的字串替換，**沒有引入 Jinja2**：模板需求僅止於此，
    為了一個變數多背一層樣板引擎（與它的 autoescape 語意）並不划算。

    index.html 本身回應時已帶 no-store（見下方 index()），瀏覽器不會快取頁面，
    因此每次都會拿到最新的 `?v=`；真正被快取的是 style.css 與 app.js，
    它們正是靠這個版號失效。這裡在啟動時算一次並存起來，避免每個請求都讀檔。
    """
    html = (WEB_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    return html.replace("{{ app_version }}", ASSET_VERSION)


# 啟動時算一次。改前端檔案後要看到新版號需重啟服務——與 config.json
# 「所有鍵啟動時讀入、沒有熱重載」的既有行為一致。
_INDEX_HTML: str = _render_index()


@app.get("/", response_class=HTMLResponse)
async def index():
    resp = HTMLResponse(_INDEX_HTML)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ==================== REST API ====================
@app.get("/api/config/limits")
def get_config_limits():
    """
    前端需要的可調上下限，來源為 config/config.json。

    目前只有額定電流範圍。前端據此設定輸入欄的 min/max 與提示文字，
    不再把 1/20 寫死在 index.html 與 app.js 兩處——改設定檔即可同步。

    **不檢查 is_connected**：這是純設定值，與設備連線無關，未連線時前端
    仍要能正確渲染通道設定頁的輸入欄。
    """
    return {
        "nominal_current": {"min": _NOMINAL_MIN, "max": _NOMINAL_MAX},
    }


@app.get("/api/status")
def get_status():
    """取得設備完整狀態快照。"""
    if _DEMO_MODE:
        return _generate_demo_payload()
    if not backend.is_connected:
        return {"connected": False, "device_ip": backend.device_ip}
    raw = backend._read_current_status()
    return _format_status(raw)


@app.post("/api/connect")
async def api_connect(ip: str = Query(default=None)):
    """建立連線。可選傳入新 IP（?ip=192.168.x.x）。"""
    if _DEMO_MODE:
        return {"success": True, "ip": "192.168.2.111 [DEMO]"}
    if ip:
        backend.device_ip = ip
    success = await asyncio.to_thread(backend.connect)
    if success:
        _WEB_LOGGER.log(_SYSTEM_LEVEL, f"手動連線成功 ({backend.device_ip})",
                         extra={'log_module': 'WEB'})
        recent = await asyncio.to_thread(_remember_connection)
        return {"success": True, "ip": backend.device_ip, "recent": recent}
    _WEB_LOGGER.warning(f"手動連線失敗 ({backend.device_ip})", extra={'log_module': 'WEB'})
    raise HTTPException(status_code=503, detail=f"無法連線至 {backend.device_ip}")


@app.post("/api/disconnect")
async def api_disconnect():
    """斷開連線。"""
    await asyncio.to_thread(backend.disconnect)
    _WEB_LOGGER.log(_SYSTEM_LEVEL, f"手動斷線 ({backend.device_ip})", extra={'log_module': 'WEB'})
    return {"success": True}


# ==================== 最近連線設備 ====================
# 清單存在 config.json 的 device.recent（見 src/app_config.py），不是 localStorage：
# 現場換一台筆電、換瀏覽器或清快取都不該遺失，且打包成 exe 後跟著 config/ 一起走。
def _remember_connection() -> list[dict]:
    """
    把剛連上的設備寫進最近連線清單，並同步 device.default_ip。

    只在**連線成功**後呼叫——連不上的位址進了清單只會變成下次的干擾項。
    設備識別資訊純粹用來讓使用者認得出哪台是哪台，讀不到就留 None，
    絕不能因此讓連線流程失敗，故整段包在 try 內。

    同步函式（get_device_info 會做多次 CIP 讀取），呼叫端請包 asyncio.to_thread。
    """
    name = serial = None
    try:
        identity = (backend.get_device_info() or {}).get("identity") or {}
        name = identity.get("product_name")
        sn = identity.get("serial_number")
        serial = str(sn) if sn is not None else None
    except Exception as e:
        _WEB_LOGGER.debug(f"讀取設備識別資訊失敗，最近連線清單僅記錄 IP: {e}",
                          extra={'log_module': 'WEB'})
    return app_config.record_connection(backend.device_ip, name, serial)


@app.get("/api/connect/recent")
def api_recent_list():
    """
    最近成功連線過的設備，最新在前。連線設定頁的 IP 下拉清單來源。

    **不檢查 is_connected**：這支的用途正是在還沒連線時讓使用者挑一個位址。
    """
    if _DEMO_MODE:
        return {"recent": [
            {"ip": "192.168.2.111", "name": "CAPAROC-PM-EIP [DEMO]",
             "serial": "DEMO0001", "last_connected": "2026-01-01T09:30:00"},
            {"ip": "192.168.2.112", "name": "CAPAROC-PM-EIP [DEMO2]",
             "serial": "DEMO0002", "last_connected": "2025-12-30T16:05:00"},
        ]}
    return {"recent": app_config.recent_devices()}


@app.delete("/api/connect/recent/{ip}")
def api_recent_delete(ip: str):
    """從最近連線清單移除一筆（設備退場、或位址已改，留著只會誤點）。"""
    if _DEMO_MODE:
        return {"success": True, "recent": []}
    if not is_valid_ip(ip):
        raise HTTPException(status_code=422, detail=f"「{ip}」不是合法的 IP 格式")
    return {"success": True, "recent": app_config.forget_device_ip(ip)}


@app.get("/api/device/network")
async def api_device_network():
    """讀取設備網路資訊（TCP/IP Interface + MAC）。"""
    if _DEMO_MODE:
        return {"ip": "192.168.2.111", "subnet": "255.255.255.0", "gateway": "192.168.2.1",
                "mac": "00:A0:45:DE:MO:01", "hostname": "CAPAROC-DEMO", "dhcp": False}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="設備未連線")
    info = await asyncio.to_thread(backend.get_network_info)
    return info


@app.get("/api/device/info")
async def api_device_info():
    """讀取設備識別資訊與全域設定參數（Identity Object + Class 0x0F 全域設定）。"""
    if _DEMO_MODE:
        return {"vendor": "Phoenix Contact", "product_name": "CAPAROC-PM-EIP [DEMO]",
                "serial": "DEMO-0000", "revision": "1.0", "firmware": "V1.00"}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="設備未連線")
    info = await asyncio.to_thread(backend.get_device_info)
    return info


def _demo_webif_info() -> dict:
    """--demo 模式的原廠 Web 介面假資料（走 merge_http_info 產生，結構與實機一致）。"""
    si = {
        "powermodule": {
            "generaldata": {
                "name": "CAPAROC PM EIP", "orderid": "1393553",
                "serialnumber": "DEMO-0000", "hwversion": 0, "fwversion": "1.0.0",
            },
            "networkinfo": {
                "dnsname": "caparoc-demo", "ip": "192.168.2.111",
                "subnetmask": "255.255.255.0", "defaultgateway": "192.168.2.1",
                "mac": "00:A0:45:DE:MO:01",
            },
            "leds": [
                {"name": "PWR", "color": "green", "en": "Operating voltage present"},
                {"name": "NET", "color": "green", "en": "Connected"},
                {"name": "MOD", "color": "green", "en": "Device operational"},
                {"name": "RDY", "color": "blinking-green", "en": "Device is ready for operation"},
            ],
        },
        "cbmodules": [
            {"name": "CAPAROC E4 12-24DC/1-4A", "serialnumber": "DEMO-M1",
             "hwversion": 1, "fwversion": "1.0.2", "channels": 4,
             "errorevents": [6, 2, 0, 0, 0, 0, 0, 0, 0, 0]},
            {"name": "CAPAROC E4 12-24DC/1-4A", "serialnumber": "DEMO-M2",
             "hwversion": 1, "fwversion": "1.0.2", "channels": 4,
             "errorevents": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
        ],
    }
    pd = {
        "powermodule": {
            "voltage": 2410, "totalcurrent": 78,
            "cumulativeerror": "off", "80percenterror": "on", "totalcurrenterror": "off",
        },
        "cbmodules": [
            [{"nominalcurrent": 4, "current": 5, "led": "green", "errorid": 0, "errorcounter": 0},
             {"nominalcurrent": 4, "current": 34, "led": "yellow", "errorid": 0, "errorcounter": 1},
             {"nominalcurrent": 4, "current": 46, "led": "red", "errorid": 2, "errorcounter": 3},
             {"nominalcurrent": 4, "current": 255, "led": "blinking-red", "errorid": 1, "errorcounter": 7}],
            [{"nominalcurrent": 4, "current": 0, "led": "off", "errorid": 4, "errorcounter": 2},
             {"nominalcurrent": 4, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0},
             {"nominalcurrent": 2, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0},
             {"nominalcurrent": 4, "current": 12, "led": "green", "errorid": 0, "errorcounter": 0}],
        ],
    }
    return caparoc_http.merge_http_info(si, pd)


@app.get("/api/device/webif")
async def api_device_webif():
    """
    原廠 Web 介面（GET /webif/systeminfo + /webif/processdata）的補充唯讀資訊。

    與 CIP 完全獨立：走 HTTP/80、無 session、免認證，只要 backend.device_ip 可達即可，
    刻意不檢查 backend.is_connected——CIP session 斷了但設備還在時這裡仍讀得到，
    且每模組的故障事件記憶正是此時最有價值。

    抓不到一律回 {"available": false}（HTTP 200），不丟 503——這是補充資料而非關鍵路徑。
    """
    if _DEMO_MODE:
        return {"available": True, **_demo_webif_info()}
    data = await asyncio.to_thread(caparoc_http.fetch_http_info, backend.device_ip)
    if data is None:
        return {"available": False}
    return {"available": True, **data}


@app.post("/api/device/reprobe-nominal")
async def api_reprobe_nominal():
    """
    強制重新探測各模組的額定電流可寫性，並覆寫快取。

    正常情況不需呼叫——連線時會沿用 config/nominal_probe_cache.json 的結果。
    只有更換模組（但模組總數不變）導致快取失準時才需要。
    ⚠️ 探測會短暫改寫設備的額定電流再還原。
    """
    if _DEMO_MODE:
        # 與 _generate_demo_payload() 的 _DEMO_READONLY_MODULES 一致；
        # 回空陣列會讓 demo 下的重新探測看起來「把 M2 變回可寫」，前後矛盾
        return {"success": True, "readonly_modules": [2]}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="設備未連線")
    await asyncio.to_thread(backend._probe_all_modules, True)
    return {"success": True,
            "readonly_modules": sorted(backend._nominal_readonly_modules)}


@app.post("/api/shutdown")
async def api_shutdown():
    """優雅關閉伺服器（斷線設備 + 停止程序）。"""
    _WEB_LOGGER.log(_SYSTEM_LEVEL, "收到關閉請求，伺服器準備停止", extra={'log_module': 'WEB'})

    async def _do_shutdown():
        await asyncio.sleep(0.3)  # 讓 HTTP 回應先送出
        os.kill(os.getpid(), signal.SIGINT)

    asyncio.create_task(_do_shutdown())
    return {"success": True}


@app.post("/api/channel/{channel_id}/on")
def channel_on(channel_id: int):
    """開啟通道（1-based 全域通道編號）。"""
    if _DEMO_MODE:
        return {"success": True, "channel": channel_id, "state": "on"}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    module, ch = backend.get_module_and_channel(channel_id)
    # show_result=False：終端機輸出前端看不到，WebSocket 一秒內就會推送真實狀態
    ok = backend.set_channel(module, ch, True, show_result=False)
    if not ok:
        raise HTTPException(status_code=500, detail="開啟失敗，請確認設備連線")
    return {"success": True, "channel": channel_id, "state": "on"}


@app.post("/api/channel/{channel_id}/off")
def channel_off(channel_id: int):
    """關閉通道（1-based 全域通道編號）。"""
    if _DEMO_MODE:
        return {"success": True, "channel": channel_id, "state": "off"}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    module, ch = backend.get_module_and_channel(channel_id)
    ok = backend.set_channel(module, ch, False, show_result=False)
    if not ok:
        raise HTTPException(status_code=500, detail="關閉失敗，請確認設備連線")
    return {"success": True, "channel": channel_id, "state": "off"}


@app.post("/api/channel/{channel_id}/nominal")
def set_nominal(channel_id: int, current_amps: float = Query(...)):
    """設定通道額定電流（1-based 全域通道編號，1-20 A 整數）。"""
    amps_int = int(round(current_amps))
    if amps_int < 1 or amps_int > 20:
        raise HTTPException(status_code=422, detail="額定電流範圍 1–20 A")
    if _DEMO_MODE:
        return {"success": True, "channel": channel_id, "nominal_amps": amps_int}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    module, ch = backend.get_module_and_channel(channel_id)
    ok = backend.set_nominal_current(module, ch, amps_int)
    if not ok:
        raise HTTPException(status_code=500, detail="設定失敗，請確認設備連線")
    return {"success": True, "channel": channel_id, "nominal_amps": amps_int}


class NominalBatchRequest(BaseModel):
    """批次設定額定電流的請求主體。"""
    channel_ids:  list[int]
    current_amps: float


@app.post("/api/channels/nominal")
async def set_nominal_batch(req: NominalBatchRequest):
    """
    批次設定多個通道的額定電流。

    後端會先寫入全部通道再統一驗證，總耗時約 3 秒；
    若前端改用 for 迴圈逐一呼叫 /api/channel/{id}/nominal，
    8 通道最壞情況要等 24 秒，期間 WebSocket 推送會被 _cip_lock 卡住。
    """
    amps_int = int(round(req.current_amps))
    if amps_int < 1 or amps_int > 20:
        raise HTTPException(status_code=422, detail="額定電流範圍 1–20 A")
    if not req.channel_ids:
        raise HTTPException(status_code=422, detail="未指定通道")
    if _DEMO_MODE:
        return {"ok": len(req.channel_ids), "fail": 0, "nominal_amps": amps_int,
                "skipped": [],
                "results": [{"channel": c, "ok": True} for c in req.channel_ids]}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")

    # 跳過探測確認無法遠端設定的模組，避免白跑一趟 CIP 寫入
    targets, skipped = [], []
    id_by_target = {}
    for cid in req.channel_ids:
        module, ch = backend.get_module_and_channel(cid)
        if backend.is_module_nominal_readonly(module):
            skipped.append(cid)
            continue
        targets.append((module, ch, amps_int))
        id_by_target[(module, ch)] = cid

    if not targets:
        raise HTTPException(status_code=422, detail="所選通道的模組皆不支援遠端設定額定電流")

    outcome = await asyncio.to_thread(backend.set_nominal_current_batch, targets)
    results = [
        {"channel": id_by_target.get((r["module"], r["channel"])),
         "ok": r["ok"], "actual": r["actual"], "error": r["error"]}
        for r in outcome["results"]
    ]
    return {"ok": outcome["ok"], "fail": outcome["fail"], "nominal_amps": amps_int,
            "skipped": skipped, "results": results}


# ==================== IP 設定 ====================
# 與 /api/device/network 的分工：
#   /api/device/network  → get_network_info()：MAC / hostname（含 0xF6 Ethernet Link）
#   /api/ipconfig/current → read_device_network_config()：0xF5 Attr1/3/5，**含 Static/DHCP 取得方式**
# 「IP 設定」頁需要判斷目前是靜態還是 DHCP，故走後者。兩者用途不同，勿混用。

class StaticIpRequest(BaseModel):
    """設定設備靜態 IP 的請求主體。"""
    ip:      str
    subnet:  str = "255.255.255.0"
    gateway: str = ""


@app.get("/api/ipconfig/current")
async def api_ipconfig_current():
    """讀取設備目前的網路設定（CIP 0xF5 Attr1/3/5，含 IP 取得方式）。"""
    if _DEMO_MODE:
        return {"success": True, "ip": "192.168.2.111", "subnet": "255.255.255.0",
                "gateway": "192.168.2.1", "config_control": 0,
                "config_control_str": "Static IP", "status": 0x35, "error": None}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="設備未連線")
    return await asyncio.to_thread(backend.read_device_network_config)


@app.get("/api/ipconfig/interfaces")
async def api_ipconfig_interfaces():
    """
    列出本機可用網卡，供前端選擇要從哪張網卡掃描（對應 CLI 的 _pick_iface()）。

    多網卡機器上這是必要的：不指定網卡時，OS 會依路由表決定導向廣播從哪個介面送出，
    很可能送錯網卡而掃不到設備。
    """
    if _DEMO_MODE:
        return {"interfaces": [
            {"name": "demo0", "description": "Demo Ethernet Adapter",
             "ip": "192.168.2.10", "mac": "00:11:22:33:44:55",
             "broadcast": "192.168.2.255"}]}
    return {"interfaces": await asyncio.to_thread(list_interfaces)}


@app.post("/api/ipconfig/discover")
async def api_ipconfig_discover(timeout: float = Query(default=2.0, ge=0.5, le=10.0),
                                iface_ip: str = Query(default=None)):
    """
    掃描網段尋找 CAPAROC 設備（EtherNet/IP List Identity 廣播，無回應時退回 ARP table）。

    刻意**不檢查連線狀態**——掃描的用途正是在還沒連上任何設備時找出設備 IP。

    Args:
        iface_ip: 指定從哪張網卡掃描（傳網卡自己的 IP）；未指定 = 全部網卡。
    """
    if _DEMO_MODE:
        return {"devices": [
                    {"ip": "192.168.2.111", "name": "CAPAROC-PM-EIP [DEMO]",
                     "serial": "DEMO0001", "revision": "1.0", "vendor_id": 1,
                     "mac": "00:a0:45:de:m0:01"},
                    {"ip": "192.168.2.112", "name": "CAPAROC-PM-EIP [DEMO2]",
                     "serial": "DEMO0002", "revision": "1.0", "vendor_id": 1,
                     "mac": "00:a0:45:de:m0:02"}],
                "via": "EIP", "broadcasts": ["192.168.2.255", "255.255.255.255"]}

    if iface_ip and not is_valid_ip(iface_ip):
        raise HTTPException(status_code=422, detail=f"「{iface_ip}」不是合法的網卡 IP")

    if not _discover_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="掃描進行中，請稍候")
    try:
        result = await asyncio.to_thread(discover, timeout, None, iface_ip)
    finally:
        _discover_lock.release()
    _WEB_LOGGER.log(_SYSTEM_LEVEL,
                    f"網段掃描完成：找到 {len(result['devices'])} 台設備"
                    f"（方式 {result['via'] or '無'}）",
                    extra={'log_module': 'WEB'})
    return result


@app.post("/api/ipconfig/static")
async def api_ipconfig_static(req: StaticIpRequest):
    """
    將設備設為靜態 IP，並在寫入後自動重連新 IP。

    寫入成功後舊連線必然中斷（設備 IP 立即改變），因此本路由承擔完整的
    「寫入 → 斷線 → 換 IP → 等待上線 → 重連」流程：放在伺服器端只有一份狀態機，
    且結果會透過既有的 1 Hz WebSocket 推送自然同步到所有開啟的分頁。
    """
    if _DEMO_MODE:
        return {"success": True, "new_ip": req.ip, "online": True, "reconnected": True}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="設備未連線")

    if not is_valid_ip(req.ip):
        raise HTTPException(status_code=422, detail=f"「{req.ip}」不是合法的 IP 格式")
    if not is_valid_ip(req.subnet):
        raise HTTPException(status_code=422, detail=f"「{req.subnet}」不是合法的子網路遮罩")
    if req.gateway and not is_valid_ip(req.gateway):
        raise HTTPException(status_code=422, detail=f"「{req.gateway}」不是合法的閘道位址")

    old_ip = backend.device_ip
    result = await asyncio.to_thread(
        backend.set_device_ip, None, req.ip, req.subnet, req.gateway)
    if not result['success']:
        _WEB_LOGGER.warning(f"設備 IP 寫入失敗 ({old_ip} → {req.ip}): {result['error']}",
                            extra={'log_module': 'WEB'})
        raise HTTPException(status_code=500, detail=f"寫入失敗: {result['error']}")

    _WEB_LOGGER.log(_SYSTEM_LEVEL, f"設備 IP 已寫入：{old_ip} → {req.ip}，等待設備重新上線",
                    extra={'log_module': 'WEB'})

    # 舊連線已隨 IP 變更失效，先清乾淨再指向新位址
    await asyncio.to_thread(backend.disconnect)
    backend.device_ip = req.ip

    # 純 TCP 44818 探測，不碰 _cip_lock，不會卡住 WebSocket 推送
    online = await asyncio.to_thread(wait_for_device, req.ip, 30.0)
    reconnected = False
    if online:
        reconnected = await asyncio.to_thread(backend.connect)

    _WEB_LOGGER.log(_SYSTEM_LEVEL,
                    f"IP 變更結果：new_ip={req.ip} online={online} reconnected={reconnected}",
                    extra={'log_module': 'WEB'})
    return {"success": True, "new_ip": req.ip,
            "online": online, "reconnected": reconnected}


@app.post("/api/ipconfig/dhcp")
async def api_ipconfig_dhcp():
    """
    將設備切換為 DHCP 模式。

    ⚠️ 切換後設備會向 DHCP server 重新取得 IP，新 IP 無法預知，
    因此這裡只斷線並提示使用者用「搜尋設備」找回。
    """
    if _DEMO_MODE:
        return {"success": True, "note": "[DEMO] 已切換為 DHCP"}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="設備未連線")

    old_ip = backend.device_ip
    result = await asyncio.to_thread(backend.set_device_dhcp, None)
    if not result['success']:
        raise HTTPException(status_code=500, detail=f"寫入失敗: {result['error']}")

    await asyncio.to_thread(backend.disconnect)
    _WEB_LOGGER.log(_SYSTEM_LEVEL, f"設備已切換為 DHCP 模式（原 IP {old_ip}），連線已中斷",
                    extra={'log_module': 'WEB'})
    return {"success": True,
            "note": "設備已切換為 DHCP，IP 由 DHCP server 重新指派；請用「搜尋設備」找回新 IP"}


class DhcpAssignRequest(BaseModel):
    """把 IP 指派給失聯設備的請求主體。"""
    iface_ip: str                        # 要在哪張網卡上開 DHCP server
    mac:      str                        # 目標設備 MAC
    ip:       str                        # 要指派並固化的 IP
    subnet:   str = "255.255.255.0"
    gateway:  str = ""
    timeout:  float = 120.0              # 等設備送出 DHCP Discover 的上限


@app.post("/api/ipconfig/detect-mac")
async def api_ipconfig_detect_mac(
    iface_ip: str = Query(...),
    timeout: float = Query(default=90.0, ge=5.0, le=180.0),
):
    """
    監聽 UDP/67 的 DHCP Discover，找出正在請求位址的設備 MAC。

    這是設備「切成 DHCP 但網段沒有 DHCP server」而失聯時**唯一**能發現它的方法：
    此時設備沒有 IP，EIP 廣播與 ARP 都查不到，但它會持續送出 DHCP Discover，
    封包裡帶著自己的 MAC。對應 CLI 的 _detect_mac_via_socket()。

    綁定 port 67 在 Windows 上不需要管理員權限，但該埠是獨佔的
    （BootP-DHCP Tool 等程式若開著會搶走）。

    ⚠️ 預設等 90 秒：DHCP client 的重試間隔會逐次拉長，實機實測設備約每 60 秒
    才送一次 Discover，等太短會誤以為偵測不到。
    """
    if _DEMO_MODE:
        return {"macs": [{"mac": "cc:cc:ea:9f:c9:72", "count": 3}],
                "iface_ip": iface_ip}
    if not is_valid_ip(iface_ip):
        raise HTTPException(status_code=422, detail=f"「{iface_ip}」不是合法的網卡 IP")
    if not _dhcp_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="另一項 DHCP 作業進行中，請稍候")
    try:
        _dhcp_cancel.clear()
        sock, err = await asyncio.to_thread(open_dhcp_socket, iface_ip)
        if sock is None:
            raise HTTPException(status_code=503, detail=err)
        try:
            own_mac = await asyncio.to_thread(iface_mac_for, iface_ip)
            seen = await asyncio.to_thread(
                detect_dhcp_macs, sock, own_mac, timeout, 2.0, None,
                _dhcp_cancel.is_set)
        finally:
            sock.close()
    finally:
        _dhcp_lock.release()

    cancelled = _dhcp_cancel.is_set()
    macs = [{"mac": m, "count": n} for m, n in sorted(seen.items())]
    _WEB_LOGGER.log(_SYSTEM_LEVEL,
                    f"DHCP MAC 偵測{'（已中斷）' if cancelled else '完成'}"
                    f"（{iface_ip}）：找到 {len(macs)} 個",
                    extra={'log_module': 'WEB'})
    return {"macs": macs, "iface_ip": iface_ip, "cancelled": cancelled}


@app.post("/api/ipconfig/dhcp-cancel")
async def api_ipconfig_dhcp_cancel():
    """
    中斷進行中的 DHCP 監聽／指派作業。

    設定共用的中斷旗標，讓佔著 UDP/67 的背景執行緒在下一輪（監聽約 0.25 秒、
    指派約 1 秒）自行結束並釋放鎖。若只在前端 abort fetch，伺服器端仍會跑到逾時。
    """
    if _DEMO_MODE:
        return {"success": True, "was_running": False}
    was_running = _dhcp_lock.locked()
    _dhcp_cancel.set()
    if was_running:
        _WEB_LOGGER.log(_SYSTEM_LEVEL, "收到 DHCP 作業中斷要求",
                        extra={'log_module': 'WEB'})
    return {"success": True, "was_running": was_running}


@app.post("/api/ipconfig/assign")
async def api_ipconfig_assign(req: DhcpAssignRequest):
    """
    救回失聯設備：開迷你 DHCP server 指派 IP 給指定 MAC，再把該 IP 固化為靜態。

    對應 CLI 的「[2] 新裝置初始設定」。流程：
      1. 綁 UDP/67，等目標 MAC 送出 Discover → 回 Offer → 收 Request → 回 ACK
      2. 等設備以新 IP 上線
      3. 連上去，把 IP 寫成靜態（Attr3 切 Static 再寫 Attr5），避免下次又靠 DHCP
    """
    if _DEMO_MODE:
        return {"success": True, "assigned": True, "online": True,
                "static_set": True, "ip": req.ip, "connected": True}

    for label, value in (("網卡 IP", req.iface_ip), ("指派 IP", req.ip),
                         ("子網路遮罩", req.subnet)):
        if not is_valid_ip(value):
            raise HTTPException(status_code=422, detail=f"{label}「{value}」格式不正確")
    if req.gateway and not is_valid_ip(req.gateway):
        raise HTTPException(status_code=422, detail=f"閘道「{req.gateway}」格式不正確")
    mac = normalize_mac(req.mac)
    if len(mac.split(':')) != 6:
        raise HTTPException(status_code=422, detail=f"MAC「{req.mac}」格式不正確")

    if not _dhcp_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="另一項 DHCP 作業進行中，請稍候")
    try:
        _dhcp_cancel.clear()
        # 設備可能還連著舊 session，先斷開以免占用
        if backend.is_connected:
            await asyncio.to_thread(backend.disconnect)

        sock, err = await asyncio.to_thread(open_dhcp_socket, req.iface_ip)
        if sock is None:
            raise HTTPException(status_code=503, detail=err)
        try:
            _WEB_LOGGER.log(_SYSTEM_LEVEL,
                            f"迷你 DHCP server 啟動（{req.iface_ip}）：指派 {req.ip} 給 {mac}",
                            extra={'log_module': 'WEB'})
            assigned = await asyncio.to_thread(
                serve_dhcp, sock, req.iface_ip, mac, req.ip, req.subnet,
                req.timeout, None, None, _dhcp_cancel.is_set)
        finally:
            sock.close()
    finally:
        _dhcp_lock.release()

    if not assigned:
        if _dhcp_cancel.is_set():
            raise HTTPException(status_code=499, detail="已手動中斷")
        raise HTTPException(
            status_code=504,
            detail=f"{int(req.timeout)} 秒內未收到 {mac} 的 DHCP 請求；"
                   f"請確認網路線已接上、網卡選對，必要時重插設備網路線強制重試")

    online = await asyncio.to_thread(wait_for_device, req.ip, 40.0)
    static_set, connected = False, False
    if online:
        backend.device_ip = req.ip
        connected = await asyncio.to_thread(backend.connect)
        if connected:
            result = await asyncio.to_thread(
                backend.set_device_ip, None, req.ip, req.subnet, req.gateway)
            static_set = bool(result.get('success'))
            # 固化靜態後連線通常會斷，重連一次
            await asyncio.to_thread(backend.disconnect)
            if await asyncio.to_thread(wait_for_device, req.ip, 30.0):
                connected = await asyncio.to_thread(backend.connect)

    _WEB_LOGGER.log(_SYSTEM_LEVEL,
                    f"設備救援結果：ip={req.ip} assigned={assigned} online={online} "
                    f"static_set={static_set} connected={connected}",
                    extra={'log_module': 'WEB'})
    return {"success": True, "assigned": assigned, "online": online,
            "static_set": static_set, "connected": connected, "ip": req.ip}


# ==================== Log API ====================
@app.get("/api/logs")
def get_logs(
    level:  str = Query(default="all"),           # all | warn | error
    limit:  int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """取得記憶體 log 緩衝（最新在前，支援分頁與等級篩選）。"""
    _WARN_LEVELS  = {"WARNING", "ERROR", "CRITICAL", "SYSTEM"}
    _ERROR_LEVELS = {"ERROR", "CRITICAL"}

    entries = list(_LOG_BUFFER)
    if level == "warn":
        entries = [e for e in entries if e["level"] in _WARN_LEVELS]
    elif level == "error":
        entries = [e for e in entries if e["level"] in _ERROR_LEVELS]

    entries.reverse()                    # 最新在前
    total = len(entries)
    page  = entries[offset: offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "entries": page}


@app.post("/api/logs/clear")
def clear_logs():
    """清空記憶體 log 緩衝。"""
    _LOG_BUFFER.clear()
    return {"success": True}


@app.get("/api/history")
def get_history(minutes: int = Query(default=10, ge=1, le=30)):
    """取得歷史感測資料（最近 N 分鐘，最多 30 分鐘）。"""
    count = min(minutes * 60, len(_history_buffer))
    entries = list(_history_buffer)[-count:] if count > 0 else []

    if not entries:
        return {"timestamps": [], "voltage": [], "total_current": [], "channels": {}}

    timestamps    = [e["ts"]            for e in entries]
    voltage       = [e["voltage"]       for e in entries]
    total_current = [e["total_current"] for e in entries]

    all_ch_ids: set = set()
    for e in entries:
        all_ch_ids.update(e["channels"].keys())

    channels = {
        ch_id: [e["channels"].get(ch_id, 0) for e in entries]
        for ch_id in sorted(all_ch_ids, key=lambda x: int(x))
    }
    return {"timestamps": timestamps, "voltage": voltage,
            "total_current": total_current, "channels": channels}


# ==================== Demo 資料生成 ====================
def _generate_demo_payload() -> dict:
    """生成模擬設備狀態（電流以正弦波小幅波動）。"""
    global _demo_tick
    _demo_tick += 1
    t = _demo_tick

    def wave(base: float, amp: float, period: float, offset: float = 0.0) -> float:
        return round(base + amp * math.sin(2 * math.pi * (t + offset) / period), 2)

    # 模組 2 模擬「額定電流無法遠端設定」的斷路器模組（實機上 M2 正是這種）。
    # 通道設定頁據此顯示 ⚙️ badge 並反灰輸入欄；沒有這個旗標的話 --demo 下
    # 整條 read-only 路徑都看不到，等於無法在沒有實機時檢視或除錯該 UI。
    _DEMO_READONLY_MODULES = {2}

    def _ro(module: int) -> bool:
        return module in _DEMO_READONLY_MODULES

    # 型號可調範圍：對應實機的 E4 12-24DC/1-4A 與 E2 12-24DC/2-10A。
    # 需與線上 payload 的 nominal_min/max 同步，否則 --demo 下的
    # 逐模組範圍驗證（輸入框 min/max、超範圍提示）無法檢視。
    _DEMO_RANGES = {1: (1, 4), 2: (2, 10)}

    # 模組 2 另外模擬固定額定型號（如 E1 12-24DC/16A）：--demo 下才看得到
    # 「不可調」與「旋鈕未轉 RC」兩種反灰文案的差異。
    _DEMO_FIXED: dict[int, int] = {}

    def _rng(module: int, idx: int):
        return _DEMO_RANGES.get(module, (None, None))[idx]

    channels = [
        # 模組 1 — 涵蓋所有常見狀態
        {"id": 1, "module": 1, "channel": 1, "on": True,  "current_amps": wave(1.5, 0.30, 20,  0), "nominal_amps": 4.0,
         "nominal_readonly": _ro(1),
         "nominal_min": _rng(1, 0), "nominal_max": _rng(1, 1), "nominal_fixed": _DEMO_FIXED.get(1),
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # warn_80: 電流超過額定 80%
        {"id": 2, "module": 1, "channel": 2, "on": True,  "current_amps": wave(3.4, 0.20, 25,  5), "nominal_amps": 4.0,
         "nominal_readonly": _ro(1),
         "nominal_min": _rng(1, 0), "nominal_max": _rng(1, 1), "nominal_fixed": _DEMO_FIXED.get(1),
         "warn_80": True,  "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # overload: 過載
        {"id": 3, "module": 1, "channel": 3, "on": True,  "current_amps": wave(4.6, 0.10, 18, 10), "nominal_amps": 4.0,
         "nominal_readonly": _ro(1),
         "nominal_min": _rng(1, 0), "nominal_max": _rng(1, 1), "nominal_fixed": _DEMO_FIXED.get(1),
         "warn_80": True,  "overload": True,  "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # short_circuit: 短路
        {"id": 4, "module": 1, "channel": 4, "on": True,  "current_amps": 25.5,                    "nominal_amps": 4.0,
         "nominal_readonly": _ro(1),
         "nominal_min": _rng(1, 0), "nominal_max": _rng(1, 1), "nominal_fixed": _DEMO_FIXED.get(1),
         "warn_80": True,  "overload": True,  "short_circuit": True,  "hardware_fault": False, "total_shutdown": False},
        # 模組 2 — 更多狀態範例（額定電流為 read-only）
        # hardware_fault: 硬體故障
        {"id": 5, "module": 2, "channel": 1, "on": False, "current_amps": 0.0,                     "nominal_amps": 4.0,
         "nominal_readonly": _ro(2),
         "nominal_min": _rng(2, 0), "nominal_max": _rng(2, 1), "nominal_fixed": _DEMO_FIXED.get(2),
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": True,  "total_shutdown": False},
        # total_shutdown: 總電流關斷
        {"id": 6, "module": 2, "channel": 2, "on": False, "current_amps": 0.0,                     "nominal_amps": 4.0,
         "nominal_readonly": _ro(2),
         "nominal_min": _rng(2, 0), "nominal_max": _rng(2, 1), "nominal_fixed": _DEMO_FIXED.get(2),
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": True},
        # 關閉 (正常)
        {"id": 7, "module": 2, "channel": 3, "on": False, "current_amps": 0.0,                     "nominal_amps": 2.0,
         "nominal_readonly": _ro(2),
         "nominal_min": _rng(2, 0), "nominal_max": _rng(2, 1), "nominal_fixed": _DEMO_FIXED.get(2),
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # 開啟 (正常運行)
        {"id": 8, "module": 2, "channel": 4, "on": True,  "current_amps": wave(1.2, 0.15, 22, 15), "nominal_amps": 4.0,
         "nominal_readonly": _ro(2),
         "nominal_min": _rng(2, 0), "nominal_max": _rng(2, 1), "nominal_fixed": _DEMO_FIXED.get(2),
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
    ]
    total_current = round(sum(ch["current_amps"] for ch in channels), 2)
    return {
        "connected":      True,
        "device_ip":      "192.168.2.111 [DEMO]",
        "module_count":   2,
        "voltage":        wave(24.1, 0.08, 40),
        "total_current":  total_current,
        "undervoltage":   False,
        "overvoltage":    False,
        "system_error":   False,
        "warn_80_global": False,
        "total_shutdown": False,
        "channels":       channels,
        # 必須與真實路徑同型別：_read_current_status() 給的是 time.time() 浮點數，
        # 這裡若給 ISO 字串，任何日後開始使用此欄位的前端邏輯都會在 demo 與實機
        # 之間表現不一致（tests/test_demo_payload.py 會擋下這種漂移）
        "timestamp":      time.time(),
    }


# ==================== WebSocket ====================
# 追蹤前端連線數；最後一個斷線後倒數自動關閉伺服器
_ws_client_count = 0
_ws_had_client   = False   # 曾有人連線過才啟動自動關閉計時
_ws_auto_task    = None    # asyncio.Task

# 秒：無前端連線多久後自動 shutdown（config.json 的 web.ws_idle_shutdown）
_WS_IDLE_TIMEOUT = float(_WEB_CFG.get("ws_idle_shutdown", 10.0))


async def _ws_idle_shutdown():
    """無前端連線超過 _WS_IDLE_TIMEOUT 秒後自動停止伺服器。"""
    await asyncio.sleep(_WS_IDLE_TIMEOUT)
    _WEB_LOGGER.log(_SYSTEM_LEVEL,
                    f"前端已離線 {_WS_IDLE_TIMEOUT:.0f} 秒，伺服器自動關閉",
                    extra={'log_module': 'WEB'})
    os.kill(os.getpid(), signal.SIGINT)


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    """每秒推送設備狀態至前端；前端斷線時自動清理。"""
    global _ws_client_count, _ws_had_client, _ws_auto_task

    await websocket.accept()
    _ws_client_count += 1
    _ws_had_client = True
    # 有新客戶端連入 → 取消待執行的自動關閉計時
    if _ws_auto_task and not _ws_auto_task.done():
        _ws_auto_task.cancel()
        _ws_auto_task = None

    try:
        while True:
            if _DEMO_MODE:
                payload = _generate_demo_payload()
            elif backend.is_connected:
                raw = await asyncio.to_thread(backend._read_current_status)
                if raw is None:
                    # 設備失聯：清理連線旗標，讓前端可以正常重連
                    await asyncio.to_thread(backend.disconnect)
                payload = _format_status(raw)
            else:
                payload = {"connected": False, "device_ip": backend.device_ip}
            await websocket.send_json(payload)
            # 推送至歷史緩衝（僅已連線且有通道資料時）
            if payload.get('connected') and payload.get('channels'):
                _history_buffer.append({
                    'ts':            _datetime.now().strftime("%H:%M:%S"),
                    'voltage':       payload['voltage'],
                    'total_current': payload['total_current'],
                    'channels':      {str(ch['id']): ch['current_amps']
                                      for ch in payload['channels']},
                })
            await asyncio.sleep(_WS_PUSH_INTERVAL)
    except WebSocketDisconnect:
        pass  # 前端正常關閉頁面/重整，不需記錄
    except Exception as e:
        _WEB_LOGGER.warning(f"WebSocket 迴圈異常中止: {type(e).__name__}: {e}",
                            extra={'log_module': 'WEB'})
    finally:
        _ws_client_count -= 1
        # 最後一個客戶端斷線 → 啟動倒數，逾時自動 shutdown
        if _ws_client_count <= 0:
            _ws_auto_task = asyncio.create_task(_ws_idle_shutdown())


# ==================== 直接執行入口 ====================
def _resolve_port() -> int:
    """
    決定監聽埠，優先序：
      1. 命令列 --port N
      2. 環境變數 CAPAROC_PORT
      3. config/config.json 的 web.port（預設 8001，避開 NVIDIA Overlay
         間歇佔用的 8000）
    選定埠若已被佔用，往上探 10 個埠取第一個可用的。
    """
    import socket

    chosen = int(_WEB_CFG.get("port", 8001))
    if "--port" in sys.argv:
        try:
            chosen = int(sys.argv[sys.argv.index("--port") + 1])
        except (IndexError, ValueError):
            print("[CAPAROC] --port 參數格式錯誤，改用預設")
    elif os.environ.get("CAPAROC_PORT"):
        try:
            chosen = int(os.environ["CAPAROC_PORT"])
        except ValueError:
            print("[CAPAROC] CAPAROC_PORT 格式錯誤，改用預設")

    for candidate in range(chosen, chosen + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", candidate))
            except OSError:
                print(f"[CAPAROC] 埠 {candidate} 已被佔用，改試 {candidate + 1}")
                continue
        if candidate != chosen:
            print(f"[CAPAROC] 改用埠 {candidate}")
        return candidate

    print(f"[CAPAROC] {chosen}~{chosen + 9} 全部無法綁定，仍嘗試 {chosen}")
    return chosen


if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn

    PORT = _resolve_port()
    URL = f"http://localhost:{PORT}"

    # 等伺服器就緒後再開瀏覽器（延遲 1.5 秒）
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()

    mode_label = " [DEMO]" if _DEMO_MODE else ""
    print(f"[CAPAROC{mode_label}] 伺服器啟動中... 開啟 {URL}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
