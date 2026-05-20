#!/usr/bin/env python3
"""
CAPAROC Web UI 服務 (Phase 4.0)

直接執行（自動開啟瀏覽器）：
    python web/app.py

或用 uvicorn（從專案根目錄）：
    uvicorn web.app:app --reload --port 8000
"""

import sys
import asyncio
import json
import logging
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.requests import Request
from fastapi.middleware.cors import CORSMiddleware

# ==================== 路徑設定 ====================
_WEB_DIR = Path(__file__).parent
_ROOT_DIR = _WEB_DIR.parent
sys.path.insert(0, str(_ROOT_DIR / "src"))

from caparoc_backend import CaparocBackend  # noqa: E402

# ==================== Log 攔截器 ====================
import re as _re
from datetime import date as _date

# 自訂 SYSTEM 等級（25，介於 INFO=20 與 WARNING=30 之間）
_SYSTEM_LEVEL = 25
logging.addLevelName(_SYSTEM_LEVEL, "SYSTEM")

# 記憶體 log 緩衝（最多 500 筆，FIFO）
_LOG_BUFFER: deque = deque(maxlen=500)
_log_serial = 0

# 解析 .log 檔行格式：2026-05-18 14:30:00 [INFO] [SYS] 訊息
_LOG_LINE_RE = _re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) \[(\w+)\] \[([^\]]+)\] (.+)$"
)


def _preload_log_file(max_lines: int = 400) -> None:
    """啟動時預載今日 .log 檔（最新 max_lines 筆），讓網頁可看到歷史記錄。"""
    global _log_serial
    today = _date.today().strftime("%Y-%m-%d")
    log_path = _ROOT_DIR / "logs" / f"caparoc_{today}.log"
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
                "time":   self.formatTime(record, self._TIME_FMT),
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
_CONFIG_PATH = _ROOT_DIR / "config" / "device_config.json"
_default_ip = "192.168.2.111"
if _CONFIG_PATH.exists():
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as _f:
            _default_ip = json.load(_f).get("default_ip", _default_ip)
    except Exception:
        pass

backend = CaparocBackend(_default_ip)


# ==================== Lifespan ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """服務啟動時嘗試連線；停止時安全斷線。"""
    _WEB_LOGGER.log(_SYSTEM_LEVEL, f"Web 服務啟動，嘗試連線至 {backend.device_ip}...",
                     extra={'log_module': 'WEB'})
    # 啟動時連線失敗不阻斷服務，可透過 POST /api/connect 手動連線
    try:
        ok = await asyncio.to_thread(backend.connect)
        if ok:
            _WEB_LOGGER.log(_SYSTEM_LEVEL, f"設備連線成功 ({backend.device_ip})",
                             extra={'log_module': 'WEB'})
        else:
            _WEB_LOGGER.warning(f"設備連線失敗 ({backend.device_ip})，可透過連線設定頁手動重試",
                                extra={'log_module': 'WEB'})
    except Exception as e:
        _WEB_LOGGER.error(f"啟動連線例外: {e}", extra={'log_module': 'WEB'})
    yield
    _WEB_LOGGER.log(_SYSTEM_LEVEL, "Web 服務關閉中...", extra={'log_module': 'WEB'})
    try:
        await asyncio.to_thread(backend.disconnect)
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

app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")


# ==================== 狀態格式化輔助 ====================
def _format_status(raw: dict | None) -> dict:
    """將 _read_current_status() 輸出轉換為前端友善格式。"""
    if raw is None:
        return {"connected": False, "error": "讀取失敗"}

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
@app.get("/", response_class=HTMLResponse)
async def index():
    resp = FileResponse(_WEB_DIR / "templates" / "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ==================== REST API ====================
@app.get("/api/status")
def get_status():
    """取得設備完整狀態快照。"""
    if not backend.is_connected:
        return {"connected": False, "device_ip": backend.device_ip}
    raw = backend._read_current_status()
    return _format_status(raw)


@app.post("/api/connect")
async def api_connect(ip: str = Query(default=None)):
    """建立連線。可選傳入新 IP（?ip=192.168.x.x）。"""
    if ip:
        backend.device_ip = ip
    success = await asyncio.to_thread(backend.connect)
    if success:
        _WEB_LOGGER.log(_SYSTEM_LEVEL, f"手動連線成功 ({backend.device_ip})",
                         extra={'log_module': 'WEB'})
        return {"success": True, "ip": backend.device_ip}
    _WEB_LOGGER.warning(f"手動連線失敗 ({backend.device_ip})", extra={'log_module': 'WEB'})
    raise HTTPException(status_code=503, detail=f"無法連線至 {backend.device_ip}")


@app.post("/api/disconnect")
async def api_disconnect():
    """斷開連線。"""
    await asyncio.to_thread(backend.disconnect)
    _WEB_LOGGER.log(_SYSTEM_LEVEL, f"手動斷線 ({backend.device_ip})", extra={'log_module': 'WEB'})
    return {"success": True}


@app.post("/api/channel/{channel_id}/on")
def channel_on(channel_id: int):
    """開啟通道（1-based 全域通道編號）。"""
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    module, ch = backend.get_module_and_channel(channel_id)
    backend.set_channel(ch, True)
    return {"success": True, "channel": channel_id, "state": "on"}


@app.post("/api/channel/{channel_id}/off")
def channel_off(channel_id: int):
    """關閉通道（1-based 全域通道編號）。"""
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    module, ch = backend.get_module_and_channel(channel_id)
    backend.set_channel(ch, False)
    return {"success": True, "channel": channel_id, "state": "off"}


@app.post("/api/channel/{channel_id}/nominal")
def set_nominal(channel_id: int, current_amps: float = Query(...)):
    """設定通道額定電流（1-based 全域通道編號，1-20 A 整數）。"""
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    amps_int = int(round(current_amps))
    if amps_int < 1 or amps_int > 20:
        raise HTTPException(status_code=422, detail="額定電流範圍 1–20 A")
    module, ch = backend.get_module_and_channel(channel_id)
    ok = backend.set_nominal_current(module, ch, amps_int)
    if not ok:
        raise HTTPException(status_code=500, detail="設定失敗，請確認設備連線")
    return {"success": True, "channel": channel_id, "nominal_amps": amps_int}


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


# ==================== WebSocket ====================
@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    """每秒推送設備狀態至前端；前端斷線時自動清理。"""
    await websocket.accept()
    try:
        while True:
            if backend.is_connected:
                raw = await asyncio.to_thread(backend._read_current_status)
                if raw is None:
                    # 設備失聯：清理連線旗標，讓前端可以正常重連
                    await asyncio.to_thread(backend.disconnect)
                payload = _format_status(raw)
            else:
                payload = {"connected": False, "device_ip": backend.device_ip}
            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ==================== 直接執行入口 ====================
if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn

    PORT = 8000
    URL = f"http://localhost:{PORT}"

    # 等伺服器就緒後再開瀏覽器（延遲 1.5 秒）
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()

    print(f"[CAPAROC] 伺服器啟動中... 開啟 {URL}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
