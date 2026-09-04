#!/usr/bin/env python3
"""
設備主機名稱（CIP 0xF5 Attr 6）測試。

不需實機、不需網路——CIP 往返以假的 driver 取代。

── 為什麼是 Attr 6 而不是 Attr 5 ──────────────────────────────────
實機診斷（192.168.50.111，2026-09-04，見 tests/manual/check_hostname.py）：

    Attr 5 raw: 6F 32 A8 C0 ... 00 00      ← Domain Name 長度前綴 = 0，空的
    Attr 6 raw: 08 00 63 61 70 61 72 6F 63 31   ← len=8 + "caparoc1"

Attr 5 是**整包結構**（IP/遮罩/閘道/DNS 都在裡面），與 set_device_ip() 同一個
attribute——寫錯會連 IP 一起改掉、設備失聯。Attr 6 是獨立的 CIP STRING，
寫壞了頂多名字不對。所以改名一律走 Attr 6，本測試守住這個選擇。
"""
import sys
import struct
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from caparoc_backend import CaparocBackend  # noqa: E402

# 實機讀到的真實位元組，作為編碼正確性的基準
_REAL_DEVICE_ATTR6 = bytes([0x08, 0x00]) + b"caparoc1"


class _FakeResp:
    def __init__(self, value=b"", error=None):
        self.value = value
        self.error = error


class _FakeDriver:
    """記錄所有 generic_message 呼叫，並依 (class, attr) 回傳預設好的內容。"""

    def __init__(self, reads=None, set_error=None):
        self.reads = reads or {}
        self.set_error = set_error
        self.calls = []

    def generic_message(self, service, class_code, instance, attribute,
                        request_data=None, **kw):
        self.calls.append({
            "service": service, "class_code": class_code,
            "instance": instance, "attribute": attribute, "data": request_data,
        })
        if service == 0x0E:                       # Get_Attribute_Single
            return _FakeResp(self.reads.get((class_code, attribute), b""))
        if service == 0x10:                       # Set_Attribute_Single
            if self.set_error:
                return _FakeResp(error=self.set_error)
            # 寫入成功後讓後續讀取看到新值（模擬「立即生效」的設備）
            self.reads[(class_code, attribute)] = request_data
            return _FakeResp()
        return _FakeResp(error="unexpected service")


def _backend(driver):
    b = CaparocBackend.__new__(CaparocBackend)      # 不跑 __init__，避免連線副作用
    import threading
    b._cip_lock = threading.RLock()
    b.driver = driver
    return b


# ── 編碼 ────────────────────────────────────────────────────────────────────
def test_encoding_matches_real_device_bytes():
    """編碼結果必須與實機讀到的位元組完全相同。"""
    assert CaparocBackend._encode_cip_string("caparoc1") == _REAL_DEVICE_ATTR6


def test_encoding_empty_string():
    """空字串＝長度前綴 0，等於清除名稱。"""
    assert CaparocBackend._encode_cip_string("") == struct.pack("<H", 0)


# ── 讀取 ────────────────────────────────────────────────────────────────────
def test_get_hostname_parses_real_bytes():
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    assert _backend(drv).get_device_hostname() == "caparoc1"


def test_get_hostname_reads_attr6_not_attr5():
    """
    只能讀 Attr 6。

    get_network_info() 是「Attr5 優先、Attr6 備援」，但寫入目標是 Attr 6——
    讀寫看不同欄位就永遠比對不起來，回讀驗證會失去意義。
    """
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    _backend(drv).get_device_hostname()
    attrs = {(c["class_code"], c["attribute"]) for c in drv.calls}
    assert attrs == {(0xF5, 6)}, f"不該碰 Attr 6 以外的東西，實際讀了 {attrs}"


def test_get_hostname_empty_and_malformed():
    assert _backend(_FakeDriver({(0xF5, 6): struct.pack("<H", 0)})).get_device_hostname() == ""
    # 長度前綴說有 99 字但資料不足 → None（不要回半截字串）
    bad = struct.pack("<H", 99) + b"abc"
    assert _backend(_FakeDriver({(0xF5, 6): bad})).get_device_hostname() is None


# ── 寫入 ────────────────────────────────────────────────────────────────────
def test_set_hostname_writes_attr6_with_correct_encoding():
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    res = _backend(drv).set_device_hostname("caparoc-A1")

    assert res["success"] is True
    writes = [c for c in drv.calls if c["service"] == 0x10]
    assert len(writes) == 1, "應該只寫一次"
    w = writes[0]
    assert (w["class_code"], w["attribute"]) == (0xF5, 6)
    assert w["data"] == CaparocBackend._encode_cip_string("caparoc-A1")


def test_set_hostname_never_touches_attr5():
    """
    絕對不能寫 Attr 5。

    那是整包 Interface Configuration（IP/遮罩/閘道/DNS），與 set_device_ip()
    同一個 attribute——誤寫會改掉 IP 讓設備失聯。這是本功能最重要的一條界線。
    """
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    _backend(drv).set_device_hostname("newname")
    for c in drv.calls:
        if c["service"] == 0x10:
            assert c["attribute"] != 5, "寫到 Attr 5 會連 IP 一起改掉，設備會失聯"


def test_set_hostname_readback_reports_applied():
    """回讀到新值 → applied=True。"""
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    res = _backend(drv).set_device_hostname("caparoc-A1")
    assert res["applied"] is True
    assert res["readback"] == "caparoc-A1"


def test_set_hostname_readback_reports_pending_reboot():
    """回讀仍是舊值 → applied=False（指令被接受，但要重啟才套用）。"""
    class _StickyDriver(_FakeDriver):
        def generic_message(self, service, class_code, instance, attribute,
                            request_data=None, **kw):
            if service == 0x10:                    # 接受寫入但不改變讀到的值
                self.calls.append({"service": service, "class_code": class_code,
                                   "instance": instance, "attribute": attribute,
                                   "data": request_data})
                return _FakeResp()
            return super().generic_message(service, class_code, instance,
                                           attribute, request_data, **kw)

    drv = _StickyDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    res = _backend(drv).set_device_hostname("caparoc-A1")
    assert res["success"] is True
    assert res["applied"] is False, "設備沒套用時要回 False，不能謊報成功生效"
    assert res["readback"] == "caparoc1"


def test_set_hostname_cip_error_is_reported():
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6}, set_error="Privilege violation")
    res = _backend(drv).set_device_hostname("nope")
    assert res["success"] is False
    assert "Privilege violation" in res["error"]


# ── 輸入驗證（寫入前就擋，不浪費一趟 CIP）──────────────────────────────────
@pytest.mark.parametrize("bad,reason", [
    ("x" * 65, "過長"),
    ("配電箱", "ASCII"),
])
def test_invalid_names_rejected_without_any_cip_write(bad, reason):
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    res = _backend(drv).set_device_hostname(bad)
    assert res["success"] is False
    assert reason in res["error"]
    assert not [c for c in drv.calls if c["service"] == 0x10], "不該送出寫入"


def test_name_is_trimmed():
    drv = _FakeDriver({(0xF5, 6): _REAL_DEVICE_ATTR6})
    _backend(drv).set_device_hostname("  caparoc2  ")
    w = [c for c in drv.calls if c["service"] == 0x10][0]
    assert w["data"] == CaparocBackend._encode_cip_string("caparoc2")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
