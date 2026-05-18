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
    # 啟動時連線失敗不阻斷服務，可透過 POST /api/connect 手動連線
    try:
        await asyncio.to_thread(backend.connect)
    except Exception:
        pass
    yield
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
        return {"success": True, "ip": backend.device_ip}
    raise HTTPException(status_code=503, detail=f"無法連線至 {backend.device_ip}")


@app.post("/api/disconnect")
async def api_disconnect():
    """斷開連線。"""
    await asyncio.to_thread(backend.disconnect)
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
    """設定通道額定電流（1-based 全域通道編號，0.5-25.5 A）。"""
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    module, ch = backend.get_module_and_channel(channel_id)
    backend.set_nominal_current(module, ch, current_amps)
    return {"success": True, "channel": channel_id, "nominal_amps": current_amps}


# ==================== WebSocket ====================
@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket):
    """每秒推送設備狀態至前端；前端斷線時自動清理。"""
    await websocket.accept()
    try:
        while True:
            if backend.is_connected:
                raw = await asyncio.to_thread(backend._read_current_status)
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
