#!/usr/bin/env python3
"""
CAPAROC 原廠 Web 介面 HTTP JSON API 客戶端（非互動核心層）

設備除了 EtherNet/IP CIP，還有一個未公開的原廠 Web 介面，提供兩個無認證的 GET 端點：

    GET http://<ip>/webif/systeminfo   -- 硬體清單 / 序號 / 韌體版本 / LED / 故障事件記憶
    GET http://<ip>/webif/processdata  -- 即時量測 + 每通道 errorid / errorcounter / led

本模組把兩者抓下來、正規化、合併成單一 dict，供 web 層加值顯示。
與 CIP 完全獨立（不同傳輸、不同埠），CIP 仍是所有關鍵即時值的來源。

設計原則：
  - 純函式，無 class，參數只吃 device_ip 字串
  - 任何失敗（逾時、連線拒絕、非 200、JSON 壞掉）一律回 None 或部分資料，永不 raise
  - 每個 parser 都可獨立單元測試（fixtures 見 tests/test_caparoc_http.py）

換算（已對實機 192.168.50.111 與 CIP /api/status 同刻交叉驗證）：
  voltage /100、totalcurrent /10、per-channel current /10、nominalcurrent = 整數安培（不除）
"""

import logging
import re

try:
    import requests
except ImportError:  # bare deploy 未裝 requests；呼叫端會拿到 None
    requests = None

logger = logging.getLogger("caparoc")

# 單次請求（連線 + 讀取）逾時秒數。原廠 API 回應很快，2.5 秒已相當寬裕。
_TIMEOUT = 2.5
_URL = "http://{ip}/webif/{path}"

# errorid 代碼 → 文字（index = 代碼）。
# ⚠️ 設備韌體內建的 DE / EN 對照表在 index 3 / 5 互相矛盾（原廠翻譯 bug），
#    這裡採用原廠 SPA bundle 的英文版為準。
ERRORID_TEXT = [
    "-",                        # 0
    "Short circuit",            # 1
    "Overload",                 # 2
    "Module current exceeded",  # 3
    "Hardware defect",          # 4
    "System current exceeded",  # 5
]

# errorevents 代碼 1..16 → 文字（0 = 空槽）。每模組保留最近 10 筆，最新在前。
_EE_KINDS = ["Short circuit", "Overload", "Module current exceeded", "Hardware defect"]
ERROREVENT_TEXT = [""] + [f"{k} channel {c}" for k in _EE_KINDS for c in (1, 2, 3, 4)]

# 有效的 LED 狀態值（供參考 / 驗證用）
LED_VALUES = {
    "off", "red", "green", "yellow",
    "blinking-red", "blinking-green", "blinking-yellow",
}

# 從模組型號字串解析額定電流範圍，例如 "CAPAROC E4 12-24DC/1-4A" -> (1, 4)
_NAME_RANGE_RE = re.compile(r"/\s*(\d+)\s*-\s*(\d+)\s*A", re.I)

# 固定額定電流型號：斜線後只有單一安培數，例如 "CAPAROC E1 12-24DC/16A"。
# 手冊 6.1.1：「It is only possible to program adjustable circuit breakers
# (designation in the name, e.g., 1-10A)」——名稱沒有範圍就是不可調，
# 與「可調但目前鎖住」（旋鈕未轉 RC）是不同狀況，UI 需分開說明。
_NAME_FIXED_RE = re.compile(r"/\s*(\d+)\s*A\s*$", re.I)


# ── 低階抓取 ──────────────────────────────────────────────

def _get_json(device_ip, path, timeout=_TIMEOUT):
    """GET 一支 /webif 端點。requests 會自動解 gzip。任何失敗 -> None。"""
    if requests is None:
        return None
    try:
        r = requests.get(_URL.format(ip=device_ip, path=path), timeout=timeout)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def fetch_systeminfo(device_ip, timeout=_TIMEOUT):
    """回傳 systeminfo 的 data 區塊（dict）或 None。"""
    j = _get_json(device_ip, "systeminfo", timeout)
    return j.get("data") if isinstance(j, dict) else None


def fetch_processdata(device_ip, timeout=_TIMEOUT):
    """回傳 processdata 的 data 區塊（dict）或 None。"""
    j = _get_json(device_ip, "processdata", timeout)
    return j.get("data") if isinstance(j, dict) else None


# ── Parser（純函式，匯出供測試） ──────────────────────────

def _clean(s):
    """原廠 JSON 的 name / orderid / serialnumber 帶尾隨空白。"""
    return s.strip() if isinstance(s, str) else s


def errorid_text(code):
    """errorid 代碼 -> 文字。越界回 'Unknown (n)'。"""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return f"Unknown ({code})"
    if 0 <= code < len(ERRORID_TEXT):
        return ERRORID_TEXT[code]
    return f"Unknown ({code})"


def errorevent_text(code):
    """errorevents 代碼 -> 文字。0 -> ''，越界回 'Unknown (n)'。"""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return f"Unknown ({code})"
    if 0 <= code < len(ERROREVENT_TEXT):
        return ERROREVENT_TEXT[code]
    return f"Unknown ({code})"


def decode_errorevents(events):
    """errorevents 陣列 -> 文字清單。過濾 0（空槽），保留順序（最新在前）。"""
    out = []
    for c in (events or []):
        try:
            if int(c):
                out.append(errorevent_text(c))
        except (TypeError, ValueError):
            continue
    return out


def nominal_range_from_name(name):
    """從型號字串解析額定電流範圍。解析不出或 lo > hi 回 None。"""
    m = _NAME_RANGE_RE.search(name or "")
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    return (lo, hi) if lo <= hi else None


def fixed_nominal_from_name(name):
    """
    型號標示的固定額定電流（安培）。可調型或解析不出回 None。

    例：'CAPAROC E1 12-24DC/16A' -> 16；'CAPAROC E4 12-24DC/1-4A' -> None。
    """
    if nominal_range_from_name(name):      # 有範圍就是可調型
        return None
    m = _NAME_FIXED_RE.search((name or "").strip())
    return int(m.group(1)) if m else None


def _range_label(rng):
    """(1, 4) -> '1–4 A'（en-dash）。None -> None。"""
    return f"{rng[0]}–{rng[1]} A" if rng else None


def _div(value, divisor, ndigits=2):
    """安全除法：非數值回 None。"""
    try:
        return round(value / divisor, ndigits)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


# ── 合併 / 正規化 ────────────────────────────────────────

def merge_http_info(systeminfo, processdata):
    """
    合併 systeminfo + processdata 成單一正規化 dict。

    systeminfo 缺 -> 回 None（沒有模組清單就沒意義）。
    processdata 缺 -> 即時欄位填 None、channels_data == []、source.processdata = False。

    模組以陣列 index 對齊：modules[i].index = i + 1，對應 CIP 的 ch.module；
    channel j + 1 對應 CIP 的 ch.channel。原廠陣列含所有實體通道（含 CIP 視為空槽者）。
    """
    if not isinstance(systeminfo, dict):
        return None

    si_pm = systeminfo.get("powermodule", {}) or {}
    gen = si_pm.get("generaldata", {}) or {}
    net = si_pm.get("networkinfo", {}) or {}
    si_mods = systeminfo.get("cbmodules", []) or []

    pd = processdata if isinstance(processdata, dict) else None
    pd_pm = (pd or {}).get("powermodule", {}) or {}
    pd_mods = (pd or {}).get("cbmodules", []) or []

    powermodule = {
        "name":          _clean(gen.get("name")),
        "orderid":       _clean(gen.get("orderid")),
        "serialnumber":  _clean(gen.get("serialnumber")),
        "hwversion":     gen.get("hwversion"),
        "fwversion":     gen.get("fwversion"),      # 原廠 Web 韌體版本 -- 非 CIP Identity revision
        "dnsname":       _clean(net.get("dnsname")),
        "ip":            net.get("ip"),
        "mac":           net.get("mac"),
        "leds": [
            {"name": l.get("name"), "color": l.get("color"),
             "label": l.get("en") or l.get("de") or ""}
            for l in (si_pm.get("leds", []) or [])
        ],
        "voltage":           _div(pd_pm.get("voltage"), 100) if "voltage" in pd_pm else None,
        "totalcurrent":      _div(pd_pm.get("totalcurrent"), 10) if "totalcurrent" in pd_pm else None,
        "cumulativeerror":   pd_pm.get("cumulativeerror"),
        "percent80error":    pd_pm.get("80percenterror"),   # 鍵改名：原鍵開頭數字，JS 端不安全
        "totalcurrenterror": pd_pm.get("totalcurrenterror"),
        # powermodule.ratedcurrent 刻意不帶：語意不明、非需求
    }

    modules = []
    for i, m in enumerate(si_mods):
        name = _clean(m.get("name"))
        rng = nominal_range_from_name(name)
        # 固定額定型號（如 /16A）本來就沒有範圍，不是解析失敗，不該告警
        if rng is None and fixed_nominal_from_name(name) is None:
            logger.warning("caparoc_http: 無法從模組型號解析額定範圍: %r", name)
        pdm = pd_mods[i] if i < len(pd_mods) else []
        modules.append({
            "index":        i + 1,
            "name":         name,
            "serialnumber": _clean(m.get("serialnumber")),
            "hwversion":    m.get("hwversion"),
            "fwversion":    m.get("fwversion"),
            "channels":     m.get("channels"),
            "nominal_min":  rng[0] if rng else None,
            "nominal_max":  rng[1] if rng else None,
            "nominal_range_label": _range_label(rng),
            # 固定額定型號的安培數（可調型為 None）。用於區分「不可調」與
            # 「可調但旋鈕未轉 RC」——兩者都反灰，但解法完全不同。
            "nominal_fixed": fixed_nominal_from_name(name),
            "fault_events": decode_errorevents(m.get("errorevents")),
            "channels_data": [
                {
                    "channel":       j + 1,
                    "nominalcurrent": c.get("nominalcurrent"),          # 整數安培，不除
                    "current":       _div(c.get("current", 0), 10),
                    "led":           c.get("led"),
                    "errorid":       c.get("errorid", 0),
                    "errorid_text":  errorid_text(c.get("errorid", 0)),
                    "errorcounter":  c.get("errorcounter", 0),          # 累計跳脫次數
                }
                for j, c in enumerate(pdm)
            ],
        })

    return {
        "powermodule": powermodule,
        "modules": modules,
        "source": {"systeminfo": True, "processdata": pd is not None},
    }


def fetch_http_info(device_ip, timeout=_TIMEOUT):
    """
    抓 systeminfo + processdata 並合併。

    systeminfo 抓不到 -> None。processdata 抓不到 -> 仍回 dict，只是即時欄位為 None。
    """
    si = fetch_systeminfo(device_ip, timeout)
    pd = fetch_processdata(device_ip, timeout)
    return merge_http_info(si, pd)
