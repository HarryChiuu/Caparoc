#!/usr/bin/env python3
"""
caparoc_http 解析層單元測試（不需設備、不需網路）

用法：
  python tests/test_caparoc_http.py       # 直接跑，印 PASS / 總結
  pytest tests/test_caparoc_http.py       # 若環境有 pytest 也能收

Fixtures 為 192.168.50.111 的實機 capture（systeminfo 一份 + processdata「有載」一份，
M2 CH1 抽載 0.4 A，用來驗證除數）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import caparoc_http as ch  # noqa: E402

# ── 實機 capture（data 區塊，已去掉外層 {"topic":...}） ──────────────

SYSTEMINFO = {
    "powermodule": {
        "generaldata": {
            "name": "CAPAROC PM EIP", "orderid": "1393553             ",
            "serialnumber": "1378815610", "hwversion": 0, "hwversion_comp": 0,
            "fwversion": "1.0.0",
        },
        "networkinfo": {
            "dnsname": "caparoc1", "ip": "192.168.50.111",
            "subnetmask": "255.255.254.0", "defaultgateway": "192.168.50.1",
            "mac": "cc:cc:ea:9f:c9:72",
        },
        "leds": [
            {"name": "PWR", "color": "green", "de": "Betriebsspannung vorhanden",
             "en": "Operating voltage present"},
            {"name": "NET", "color": "green", "de": "Verbunden", "en": "Connected"},
            {"name": "MOD", "color": "green", "de": "Gerat betriebsbereit",
             "en": "Device operational"},
            {"name": "RDY", "color": "green", "de": "Gerat ist betriebsbereit",
             "en": "Device is ready for operation"},
        ],
    },
    "cbmodules": [
        {"name": "CAPAROC E4 12-24DC/1-4A         ", "serialnumber": "1378554559      ",
         "hwversion": 1, "fwversion": "1.0.2", "channels": 4,
         "errorevents": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
        {"name": "CAPAROC E2 12-24DC/2-10A        ", "serialnumber": "1378794205      ",
         "hwversion": 3, "fwversion": "1.0.4", "channels": 2,
         "errorevents": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
        {"name": "CAPAROC E4 12-24DC/1-4A         ", "serialnumber": "1378555393      ",
         "hwversion": 1, "fwversion": "1.0.2", "channels": 4,
         "errorevents": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]},
    ],
    "text1": {"de": "", "en": ""}, "text2": {"de": "", "en": ""},
}

PROCESSDATA = {
    "powermodule": {
        "voltage": 2424, "totalcurrent": 4, "ratedcurrent": 26,
        "cumulativeerror": "off", "80percenterror": "off", "totalcurrenterror": "off",
    },
    "cbmodules": [
        [{"nominalcurrent": 2, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0},
         {"nominalcurrent": 2, "current": 0, "led": "green", "errorid": 0, "errorcounter": 0},
         {"nominalcurrent": 2, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0},
         {"nominalcurrent": 2, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0}],
        [{"nominalcurrent": 4, "current": 4, "led": "green", "errorid": 0, "errorcounter": 0},
         {"nominalcurrent": 6, "current": 0, "led": "green", "errorid": 0, "errorcounter": 0}],
        [{"nominalcurrent": 4, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0},
         {"nominalcurrent": 1, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0},
         {"nominalcurrent": 1, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0},
         {"nominalcurrent": 2, "current": 0, "led": "off", "errorid": 0, "errorcounter": 0}],
    ],
}


# ── 測試 ────────────────────────────────────────────────────

def test_merge_full():
    out = ch.merge_http_info(SYSTEMINFO, PROCESSDATA)
    assert out is not None
    pm = out["powermodule"]
    assert pm["name"] == "CAPAROC PM EIP"
    assert pm["fwversion"] == "1.0.0"
    assert pm["orderid"] == "1393553"           # 尾隨空白已去除
    assert pm["dnsname"] == "caparoc1"
    assert pm["voltage"] == 24.24               # 2424 / 100
    assert pm["totalcurrent"] == 0.4            # 4 / 10
    assert pm["percent80error"] == "off"        # 鍵已改名
    assert [l["name"] for l in pm["leds"]] == ["PWR", "NET", "MOD", "RDY"]
    assert pm["leds"][0]["label"] == "Operating voltage present"   # en 優先

    mods = out["modules"]
    assert len(mods) == 3
    assert mods[0]["name"] == "CAPAROC E4 12-24DC/1-4A"            # 無尾隨空白
    assert mods[0]["serialnumber"] == "1378554559"
    assert (mods[0]["nominal_min"], mods[0]["nominal_max"]) == (1, 4)
    assert (mods[1]["nominal_min"], mods[1]["nominal_max"]) == (2, 10)
    assert (mods[2]["nominal_min"], mods[2]["nominal_max"]) == (1, 4)
    assert mods[0]["nominal_range_label"] == "1–4 A"
    assert mods[1]["channels"] == 2
    assert len(mods[1]["channels_data"]) == 2

    cd = mods[1]["channels_data"][0]
    assert cd["channel"] == 1
    assert cd["current"] == 0.4                 # 4 / 10
    assert cd["nominalcurrent"] == 4            # 整數安培，不除
    assert cd["errorid_text"] == "-"
    assert cd["errorcounter"] == 0

    assert all(m["fault_events"] == [] for m in mods)
    assert out["source"] == {"systeminfo": True, "processdata": True}


def test_merge_systeminfo_only():
    out = ch.merge_http_info(SYSTEMINFO, None)
    assert out is not None
    assert len(out["modules"]) == 3
    assert all(m["channels_data"] == [] for m in out["modules"])
    assert out["powermodule"]["voltage"] is None
    assert out["powermodule"]["totalcurrent"] is None
    assert out["source"]["processdata"] is False
    # 靜態欄位仍在
    assert out["modules"][1]["nominal_max"] == 10


def test_merge_no_systeminfo():
    assert ch.merge_http_info(None, PROCESSDATA) is None
    assert ch.merge_http_info(None, None) is None


def test_errorid_text():
    assert ch.errorid_text(0) == "-"
    assert ch.errorid_text(2) == "Overload"
    assert ch.errorid_text(5) == "System current exceeded"
    assert ch.errorid_text(9) == "Unknown (9)"


def test_errorevent_text():
    assert ch.errorevent_text(0) == ""
    assert ch.errorevent_text(1) == "Short circuit channel 1"
    assert ch.errorevent_text(8) == "Overload channel 4"
    assert ch.errorevent_text(16) == "Hardware defect channel 4"
    assert ch.errorevent_text(17) == "Unknown (17)"


def test_decode_errorevents():
    assert ch.decode_errorevents([3, 0, 0, 0, 0, 0, 0, 0, 0, 0]) == ["Short circuit channel 3"]
    assert ch.decode_errorevents([0] * 10) == []
    assert ch.decode_errorevents([2, 6]) == ["Short circuit channel 2", "Overload channel 2"]
    assert ch.decode_errorevents(None) == []


def test_nominal_range_from_name():
    assert ch.nominal_range_from_name("CAPAROC E2 12-24DC/2-10A        ") == (2, 10)
    assert ch.nominal_range_from_name("CAPAROC E4 12-24DC/1-4A") == (1, 4)
    assert ch.nominal_range_from_name("weird module") is None
    assert ch.nominal_range_from_name("") is None
    assert ch.nominal_range_from_name(None) is None


def test_fetch_http_info_no_network(monkeypatch=None):
    """_get_json 全部回 None -> fetch_http_info 回 None，不 raise。"""
    orig = ch._get_json
    ch._get_json = lambda *a, **k: None
    try:
        assert ch.fetch_http_info("10.0.0.1") is None
    finally:
        ch._get_json = orig


# ── 執行器（無 pytest 也能跑） ──────────────────────────────

def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
