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
import signal
import asyncio
import threading
import json
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import date as _date, datetime as _datetime
from pathlib import Path

# ==================== Demo 模式旗標 ====================
_DEMO_MODE: bool = "--demo" in sys.argv
_demo_tick: int = 0  # 每秒遞增，用於電流波形模擬

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
        return {"success": True, "ip": backend.device_ip}
    _WEB_LOGGER.warning(f"手動連線失敗 ({backend.device_ip})", extra={'log_module': 'WEB'})
    raise HTTPException(status_code=503, detail=f"無法連線至 {backend.device_ip}")


@app.post("/api/disconnect")
async def api_disconnect():
    """斷開連線。"""
    await asyncio.to_thread(backend.disconnect)
    _WEB_LOGGER.log(_SYSTEM_LEVEL, f"手動斷線 ({backend.device_ip})", extra={'log_module': 'WEB'})
    return {"success": True}


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
    backend.set_channel(module, ch, True)
    return {"success": True, "channel": channel_id, "state": "on"}


@app.post("/api/channel/{channel_id}/off")
def channel_off(channel_id: int):
    """關閉通道（1-based 全域通道編號）。"""
    if _DEMO_MODE:
        return {"success": True, "channel": channel_id, "state": "off"}
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    module, ch = backend.get_module_and_channel(channel_id)
    backend.set_channel(module, ch, False)
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


# ==================== 暫時診斷 API ====================
@app.get("/api/debug/config-assembly")
def debug_config_assembly():
    """診斷：讀取 Config Assembly (0x66) 原始 bytes，對比 Input Assembly。"""
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    try:
        cfg_resp = backend.driver.generic_message(
            service=0x0E, class_code=0x04,
            instance=backend.config_instance, attribute=3, connected=True
        )
        inp_resp = backend.driver.generic_message(
            service=0x0E, class_code=0x04,
            instance=backend.input_instance, attribute=3, connected=False
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    cfg = bytes(cfg_resp.value) if (cfg_resp and hasattr(cfg_resp, 'value')) else b''
    inp = bytes(inp_resp.value) if (inp_resp and hasattr(inp_resp, 'value')) else b''
    module_count = inp[1] if len(inp) > 1 else 0

    rows = []
    for mod in range(1, module_count + 1):
        for ch in range(1, backend.channels_per_module + 1):
            off = backend.get_channel_offset(mod, ch)
            cfg_off = backend.get_config_channel_offset(mod, ch)
            inp_nom  = inp[off + 1]  if len(inp)  > off + 2  else None
            cfg_nom  = cfg[cfg_off]  if len(cfg)  > cfg_off  else None
            cfg_lock = cfg[cfg_off+1] if len(cfg) > cfg_off+1 else None
            cfg_stat = cfg[cfg_off+2] if len(cfg) > cfg_off+2 else None
            rows.append({
                "module": mod, "channel": ch,
                "inp_offset": off,   "inp_nominal": inp_nom,
                "cfg_offset": cfg_off, "cfg_nominal": cfg_nom,
                "cfg_lock": cfg_lock, "cfg_status": cfg_stat,
                "slot_empty": inp_nom == 0,
            })
    return {"cfg_len": len(cfg), "inp_len": len(inp), "channels": rows}


@app.post("/api/debug/set-nominal-direct")
def debug_set_nominal_direct(
    module: int = Query(...),
    channel: int = Query(...),
    amps: int = Query(...),
):
    """
    診斷：最小化寫入測試。
    只修改目標通道的 3 bytes（nominal+status），其他全部保持從 Config Assembly 讀到的原始值。
    不執行任何保護迴圈。寫入後等 1.5s 讀回 Input Assembly 確認。
    """
    import time as _time
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")

    # 1. 讀取 Config Assembly
    cfg_resp = backend.driver.generic_message(
        service=0x0E, class_code=0x04,
        instance=backend.config_instance, attribute=3, connected=True
    )
    if not cfg_resp or not hasattr(cfg_resp, 'value'):
        raise HTTPException(status_code=500, detail="讀取 Config Assembly 失敗")
    cfg = bytearray(cfg_resp.value)
    cfg_off = backend.get_config_channel_offset(module, channel)

    before_bytes = list(cfg[cfg_off:cfg_off+3])

    # 2. 只修改目標通道的 3 bytes，其他完全不動
    cfg[cfg_off]     = amps   # Nominal
    cfg[cfg_off + 2] = 2      # Status = No Change

    # 3. 寫回
    wr = backend.driver.generic_message(
        service=0x10, class_code=0x04,
        instance=backend.config_instance, attribute=3,
        request_data=bytes(cfg), connected=True
    )
    wr_err = getattr(wr, 'error', None)

    # 4. 等 1.5 秒後讀 Input Assembly 確認
    _time.sleep(1.5)
    inp_resp = backend.driver.generic_message(
        service=0x0E, class_code=0x04,
        instance=backend.input_instance, attribute=3, connected=False
    )
    inp = bytes(inp_resp.value) if (inp_resp and hasattr(inp_resp, 'value')) else b''
    inp_off = backend.get_channel_offset(module, channel)
    inp_nominal_after = inp[inp_off + 1] if len(inp) > inp_off + 2 else None

    return {
        "module": module, "channel": channel, "requested_amps": amps,
        "cfg_offset": cfg_off, "cfg_len": len(cfg),
        "before_bytes": before_bytes,
        "write_error": wr_err,
        "inp_nominal_after": inp_nominal_after,
        "success": inp_nominal_after == amps,
    }


@app.get("/api/debug/scan-param-object")
def debug_scan_param_object():
    """診斷：掃描 Class 0x0F (Parameter Object) 所有可讀的 instance。"""
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    results = []
    for inst in range(1, 80):
        try:
            r = backend.driver.generic_message(
                service=0x0E, class_code=0x0F, instance=inst,
                attribute=1, connected=True, unconnected_send=False
            )
            if r and not getattr(r, 'error', None) and r.value:
                results.append({
                    "instance": inst,
                    "bytes": list(r.value[:8]),
                    "val_uint8": r.value[0] if len(r.value) >= 1 else None,
                })
        except Exception:
            pass
    return {"count": len(results), "instances": results}


@app.post("/api/debug/try-param-object-write")
def debug_try_param_object_write(
    module: int = Query(...),
    channel: int = Query(...),
    amps: int = Query(...),
):
    """診斷：透過 Class 0x0F Parameter Object 直接寫入 nominal current。"""
    import time as _time
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    nominal_inst = 5 + ((module - 1) * 4 + (channel - 1)) * 3 + 1
    wr = backend.driver.generic_message(
        service=0x10, class_code=0x0F, instance=nominal_inst,
        attribute=1, request_data=bytes([amps]),
        connected=True, unconnected_send=False
    )
    wr_err = getattr(wr, 'error', None)
    _time.sleep(1.5)
    inp = backend.driver.generic_message(
        service=0x0E, class_code=0x04,
        instance=backend.input_instance, attribute=3, connected=False
    )
    inp_off = backend.get_channel_offset(module, channel)
    nom_after = inp.value[inp_off + 1] if inp and inp.value and len(inp.value) > inp_off + 2 else None
    return {
        "module": module, "channel": channel, "requested_amps": amps,
        "nominal_instance": nominal_inst,
        "write_error": wr_err,
        "inp_nominal_after": nom_after,
        "success": nom_after == amps,
    }


@app.post("/api/debug/try-cfg-status1")
def debug_try_cfg_status1(
    module: int = Query(...),
    channel: int = Query(...),
    amps: int = Query(...),
):
    """診斷：Config Assembly 寫入，status=1（RC mode 測試）。"""
    import time as _time
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    cfg_resp = backend.driver.generic_message(
        service=0x0E, class_code=0x04,
        instance=backend.config_instance, attribute=3, connected=True
    )
    cfg = bytearray(cfg_resp.value)
    off = backend.get_config_channel_offset(module, channel)
    cfg[off]     = amps
    cfg[off + 2] = 1      # status=1: Turn On + apply nominal
    wr = backend.driver.generic_message(
        service=0x10, class_code=0x04,
        instance=backend.config_instance, attribute=3,
        request_data=bytes(cfg), connected=True
    )
    wr_err = getattr(wr, 'error', None)
    _time.sleep(1.5)
    inp = backend.driver.generic_message(
        service=0x0E, class_code=0x04,
        instance=backend.input_instance, attribute=3, connected=False
    )
    inp_off = backend.get_channel_offset(module, channel)
    nom_after = inp.value[inp_off + 1] if inp and inp.value and len(inp.value) > inp_off + 2 else None
    return {
        "method": "Config status=1",
        "write_error": wr_err, "inp_nominal_after": nom_after, "success": nom_after == amps
    }


@app.post("/api/debug/try-param-attr3")
def debug_try_param_attr3(
    module: int = Query(...),
    channel: int = Query(...),
    amps: int = Query(...),
):
    """診斷：Parameter Object attribute=3 寫入。"""
    import time as _time
    if not backend.is_connected:
        raise HTTPException(status_code=503, detail="未連線")
    nominal_inst = 5 + ((module - 1) * 4 + (channel - 1)) * 3 + 1
    wr = backend.driver.generic_message(
        service=0x10, class_code=0x0F, instance=nominal_inst,
        attribute=3, request_data=bytes([amps]),
        connected=True, unconnected_send=False
    )
    wr_err = getattr(wr, 'error', None)
    _time.sleep(1.5)
    inp = backend.driver.generic_message(
        service=0x0E, class_code=0x04,
        instance=backend.input_instance, attribute=3, connected=False
    )
    inp_off = backend.get_channel_offset(module, channel)
    nom_after = inp.value[inp_off + 1] if inp and inp.value and len(inp.value) > inp_off + 2 else None
    return {
        "method": "Parameter Object attr=3",
        "nominal_instance": nominal_inst,
        "write_error": wr_err, "inp_nominal_after": nom_after, "success": nom_after == amps
    }


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

    channels = [
        # 模組 1 — 涵蓋所有常見狀態
        {"id": 1, "module": 1, "channel": 1, "on": True,  "current_amps": wave(1.5, 0.30, 20,  0), "nominal_amps": 4.0,
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # warn_80: 電流超過額定 80%
        {"id": 2, "module": 1, "channel": 2, "on": True,  "current_amps": wave(3.4, 0.20, 25,  5), "nominal_amps": 4.0,
         "warn_80": True,  "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # overload: 過載
        {"id": 3, "module": 1, "channel": 3, "on": True,  "current_amps": wave(4.6, 0.10, 18, 10), "nominal_amps": 4.0,
         "warn_80": True,  "overload": True,  "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # short_circuit: 短路
        {"id": 4, "module": 1, "channel": 4, "on": True,  "current_amps": 25.5,                    "nominal_amps": 4.0,
         "warn_80": True,  "overload": True,  "short_circuit": True,  "hardware_fault": False, "total_shutdown": False},
        # 模組 2 — 更多狀態範例
        # hardware_fault: 硬體故障
        {"id": 5, "module": 2, "channel": 1, "on": False, "current_amps": 0.0,                     "nominal_amps": 4.0,
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": True,  "total_shutdown": False},
        # total_shutdown: 總電流關斷
        {"id": 6, "module": 2, "channel": 2, "on": False, "current_amps": 0.0,                     "nominal_amps": 4.0,
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": True},
        # 關閉 (正常)
        {"id": 7, "module": 2, "channel": 3, "on": False, "current_amps": 0.0,                     "nominal_amps": 2.0,
         "warn_80": False, "overload": False, "short_circuit": False, "hardware_fault": False, "total_shutdown": False},
        # 開啟 (正常運行)
        {"id": 8, "module": 2, "channel": 4, "on": True,  "current_amps": wave(1.2, 0.15, 22, 15), "nominal_amps": 4.0,
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
        "timestamp":      _datetime.now().isoformat(),
    }


# ==================== WebSocket ====================
# 追蹤前端連線數；最後一個斷線後倒數自動關閉伺服器
_ws_client_count = 0
_ws_had_client   = False   # 曾有人連線過才啟動自動關閉計時
_ws_auto_task    = None    # asyncio.Task

_WS_IDLE_TIMEOUT = 10.0    # 秒：無前端連線多久後自動 shutdown


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
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        _ws_client_count -= 1
        # 最後一個客戶端斷線 → 啟動倒數，逾時自動 shutdown
        if _ws_client_count <= 0:
            _ws_auto_task = asyncio.create_task(_ws_idle_shutdown())


# ==================== 直接執行入口 ====================
if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn

    PORT = 8000
    URL = f"http://localhost:{PORT}"

    # 等伺服器就緒後再開瀏覽器（延遲 1.5 秒）
    threading.Timer(1.5, lambda: webbrowser.open(URL)).start()

    mode_label = " [DEMO]" if _DEMO_MODE else ""
    print(f"[CAPAROC{mode_label}] 伺服器啟動中... 開啟 {URL}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
