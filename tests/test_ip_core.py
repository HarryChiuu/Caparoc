#!/usr/bin/env python3
"""
`caparoc_ip_core` 純函式安全網（TODO 零散技術債「建議項」）。

只涵蓋不碰網路、不碰子行程的純函式。需要 socket/subprocess 的部分
（discover / arp_table / serve_dhcp …）留給 `tests/manual/` 的手動工具。

── 為什麼這幾支值得釘住 ────────────────────────────────────────
* `is_valid_ip()` 曾被改成 `return false`（小寫）而整個 IP 設定頁失效——
  見 TODO「⚠️ 踩過的坑」。這裡的測試就是那次事故的回歸防線。
* `dhcp_msg_type()` 的 docstring 明講不可用 `data[0]` 判斷（BOOTP op 欄位
  與 DHCP_DISCOVER 都等於 1）。本檔用 REQUEST 封包驗證這個區別，
  避免有人「簡化」成讀 data[0] 而讓 REQUEST/RELEASE 全被誤判成 Discover。
* `same_subnet()` 遮罩壞掉時刻意回 True（只警告不擋），是產品決策不是 bug。
"""
import sys
import socket
import struct
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import caparoc_ip_core as core  # noqa: E402


# ── is_valid_ip ────────────────────────────────────────────────

@pytest.mark.parametrize("ip", [
    "192.168.50.10", "0.0.0.0", "255.255.255.255", "10.0.0.1",
])
def test_is_valid_ip_accepts_valid(ip):
    assert core.is_valid_ip(ip) is True


@pytest.mark.parametrize("ip", [
    "192.168.50.256",     # 超出 255
    "192.168.50",         # 段數不足
    "192.168.50.10.1",    # 段數過多
    "192.168.50.a",       # 非數字
    "", "   ", "not-an-ip",
])
def test_is_valid_ip_rejects_invalid(ip):
    assert core.is_valid_ip(ip) is False


def test_is_valid_ip_returns_real_bool():
    """回傳值必須是真的 bool——擋住「return false」那類事故重演。"""
    assert core.is_valid_ip("192.168.50.10") is True
    assert core.is_valid_ip("bad") is False


# ── same_subnet ────────────────────────────────────────────────

def test_same_subnet_true_within_24():
    assert core.same_subnet("192.168.50.20", "192.168.50.10", "255.255.255.0")


def test_same_subnet_false_across_24():
    assert not core.same_subnet("192.168.51.20", "192.168.50.10", "255.255.255.0")


def test_same_subnet_respects_non_24_mask():
    """/16 之下 192.168.51.x 與 192.168.50.x 屬同網段。"""
    assert core.same_subnet("192.168.51.20", "192.168.50.10", "255.255.0.0")


def test_same_subnet_broken_mask_returns_true():
    """遮罩無法解析時刻意回 True：只警告、不擋使用者操作。"""
    assert core.same_subnet("192.168.50.20", "192.168.50.10", "not-a-mask")


# ── normalize_mac ──────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("AA-BB-CC-DD-EE-FF", "aa:bb:cc:dd:ee:ff"),
    ("aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff"),
    ("  AA-BB-CC-DD-EE-FF  ", "aa:bb:cc:dd:ee:ff"),
    ("AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff"),
])
def test_normalize_mac(raw, expected):
    assert core.normalize_mac(raw) == expected


# ── dhcp_msg_type ──────────────────────────────────────────────

def _dhcp_packet(msg_type, op=1, magic=None, extra_opts=b''):
    """組一個最小可解析的 DHCP 封包（240 bytes 標頭 + options）。"""
    pkt = bytearray(240)
    pkt[0] = op
    pkt[236:240] = magic if magic is not None else core.DHCP_MAGIC
    opts = bytearray(extra_opts)
    if msg_type is not None:
        opts += bytes([53, 1, msg_type])
    opts += b'\xff'
    return bytes(pkt) + bytes(opts)


@pytest.mark.parametrize("msg_type", [1, 2, 3, 5, 7, 8])
def test_dhcp_msg_type_reads_option_53(msg_type):
    assert core.dhcp_msg_type(_dhcp_packet(msg_type)) == msg_type


def test_dhcp_msg_type_request_not_confused_with_discover():
    """
    關鍵回歸測試：BOOTP op=1 (BOOTREQUEST) 且 Option 53=3 (REQUEST) 的封包，
    必須回 3。若有人改成讀 data[0] 就會回 1 (DISCOVER) 而本測試失敗。
    """
    assert core.dhcp_msg_type(_dhcp_packet(3, op=1)) == 3


def test_dhcp_msg_type_skips_preceding_options():
    """Option 53 不在第一個位置時仍要找得到（需正確依 length 前進）。"""
    pkt = _dhcp_packet(5, extra_opts=bytes([12, 4]) + b'host')
    assert core.dhcp_msg_type(pkt) == 5


def test_dhcp_msg_type_bad_magic_returns_none():
    assert core.dhcp_msg_type(_dhcp_packet(1, magic=b'\x00\x00\x00\x00')) is None


def test_dhcp_msg_type_too_short_returns_none():
    assert core.dhcp_msg_type(b'\x01' * 100) is None


def test_dhcp_msg_type_absent_option_returns_none():
    assert core.dhcp_msg_type(_dhcp_packet(None)) is None


# ── parse_list_identity ────────────────────────────────────────

def _identity_packet(ip="192.168.50.10", vendor=1234, serial=0xDEADBEEF,
                     name=b"CAPAROC", command=0x0063):
    """組一個 List Identity 回應封包（欄位位移與 parse_list_identity 對齊）。"""
    pkt = bytearray(32)
    struct.pack_into('<H', pkt, 0, command)
    body = bytearray(16)
    body[4:8] = socket.inet_aton(ip)
    pkt += body
    pkt += struct.pack('<H', vendor)        # vendor_id
    pkt += b'\x00' * 4                      # device_type + product_code
    pkt += bytes([2, 5])                    # revision major/minor
    pkt += b'\x00\x00'                      # status
    pkt += struct.pack('<I', serial)
    pkt += bytes([len(name)]) + name
    return bytes(pkt)


def test_parse_list_identity_extracts_fields():
    result = core.parse_list_identity(_identity_packet(), "192.168.50.10")
    assert result is not None
    assert result['ip'] == "192.168.50.10"
    assert result['vendor_id'] == 1234
    assert result['revision'] == "2.5"
    assert result['serial'] == "DEADBEEF"
    assert result['name'] == "CAPAROC"


def test_parse_list_identity_wrong_command_returns_none():
    assert core.parse_list_identity(_identity_packet(command=0x0004), "1.2.3.4") is None


def test_parse_list_identity_truncated_returns_none():
    assert core.parse_list_identity(_identity_packet()[:20], "1.2.3.4") is None


def test_parse_list_identity_garbage_returns_none():
    """不可拋例外——這支會餵到來自網路的任意 UDP 封包。"""
    assert core.parse_list_identity(b'\x00' * 5, "1.2.3.4") is None
    assert core.parse_list_identity(b'', "1.2.3.4") is None


# ── build_dhcp_reply ───────────────────────────────────────────

def test_build_dhcp_reply_structure():
    pkt = core.build_dhcp_reply(
        xid=b'\x11\x22\x33\x44', chaddr=b'\xaa' * 6,
        offered_ip="192.168.50.99", server_ip="192.168.50.1",
        subnet="255.255.255.0", msg_type=2,
    )
    assert pkt[0] == 2                                   # op = BOOTREPLY
    assert pkt[4:8] == b'\x11\x22\x33\x44'               # xid 原樣帶回
    assert pkt[16:20] == socket.inet_aton("192.168.50.99")  # yiaddr
    assert pkt[236:240] == core.DHCP_MAGIC
    assert core.dhcp_msg_type(pkt) == 2                  # 自家兩支函式互相對得上
    assert len(pkt) >= 300                               # 最小封包長度填充


def test_build_dhcp_reply_ack_roundtrip():
    pkt = core.build_dhcp_reply(
        xid=b'\x00' * 4, chaddr=b'\xbb' * 6,
        offered_ip="10.0.0.5", server_ip="10.0.0.1",
        subnet="255.0.0.0", msg_type=5,
    )
    assert core.dhcp_msg_type(pkt) == 5


# ── _broadcast_from_mask（非 /24 網段修正）─────────────────────

@pytest.mark.parametrize("ip,mask,expected", [
    ("192.168.50.10",  "255.255.255.0", "192.168.50.255"),   # /24
    ("192.168.50.200", "255.255.254.0", "192.168.51.255"),   # /23：舊 /24 推測會算錯
    ("10.80.209.1",    "255.255.254.0", "10.80.209.255"),    # /23
    ("172.20.5.7",     "255.255.0.0",   "172.20.255.255"),   # /16
    ("10.1.2.3",       "255.0.0.0",     "10.255.255.255"),   # /8
    ("192.168.4.130",  "255.255.255.192", "192.168.4.191"),  # /26
])
def test_broadcast_from_mask_uses_real_prefix(ip, mask, expected):
    assert core._broadcast_from_mask(ip, mask) == expected


@pytest.mark.parametrize("mask", [None, "", "not-a-mask"])
def test_broadcast_from_mask_falls_back_to_24(mask):
    """遮罩不明時維持舊行為（/24 推測），不可拋例外。"""
    assert core._broadcast_from_mask("192.168.50.10", mask) == "192.168.50.255"


@pytest.mark.parametrize("mask", ["255.255.255.255", "255.255.255.254"])
def test_broadcast_from_mask_p2p_has_no_broadcast(mask):
    """/31、/32（VPN／點對點）沒有可用廣播位址，回空字串讓呼叫端略過。"""
    assert core._broadcast_from_mask("172.16.0.5", mask) == ""


def test_broadcast_from_mask_link_local_is_special_cased():
    assert core._broadcast_from_mask("169.254.10.20", "255.255.0.0") == "169.254.255.255"


def test_get_broadcast_addresses_skips_p2p_and_loopback(monkeypatch):
    monkeypatch.setattr(core, '_iface_netmasks', lambda: {
        "192.168.50.200": "255.255.254.0",   # /23
        "172.16.0.5":     "255.255.255.255", # /32 → 應被略過
        "127.0.0.1":      "255.0.0.0",       # loopback → 應被略過
    })
    monkeypatch.setattr(core.socket, 'getaddrinfo',
                        lambda *a, **k: (_ for _ in ()).throw(OSError()))
    result = core.get_broadcast_addresses()
    assert "192.168.51.255" in result          # /23 正確展開
    assert "172.16.0.5" not in result          # 主機 IP 不可當廣播目標
    assert not any(r.startswith("127.") for r in result)
    assert "255.255.255.255" in result         # 受限廣播永遠保底


def test_broadcast_for_never_returns_empty(monkeypatch):
    """discover() 直接把回傳值當廣播目標，不能是空字串。"""
    monkeypatch.setattr(core, '_iface_netmasks',
                        lambda: {"172.16.0.5": "255.255.255.255"})
    assert core._broadcast_for("172.16.0.5") == "255.255.255.255"


def test_iface_netmasks_without_psutil_returns_empty(monkeypatch):
    """psutil 是選配依賴：沒有它時要安靜退回空 dict，不是炸掉。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'psutil':
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    assert core._iface_netmasks() == {}


# ── arp_table 語系獨立性 ───────────────────────────────────────

@pytest.mark.parametrize("type_word", ['動態', 'dynamic', 'dynamisch', 'динамический', '???'])
def test_arp_table_parses_regardless_of_locale_word(monkeypatch, type_word):
    """
    問題 #6 的回歸測試：type 欄位是本地化文字，解析不可以依賴它。
    同一份表格換成任何語系的「動態」字樣都必須解析出相同結果。
    """
    out = (
        f"介面: 10.80.209.1 --- 0x5\n"
        f"  網際網路位址          實體位址              類型\n"
        f"  192.168.50.10         aa-bb-cc-dd-ee-ff     {type_word}\n"
        f"  192.168.50.11         11-22-33-44-55-66     {type_word}\n"
    ).encode('utf-8')

    class _R:
        stdout = out

    monkeypatch.setattr(core.subprocess, 'run', lambda *a, **k: _R())
    monkeypatch.setattr(core.locale, 'getpreferredencoding', lambda *a: 'utf-8')

    assert core.arp_table() == [
        ('aa-bb-cc-dd-ee-ff', '192.168.50.10'),
        ('11-22-33-44-55-66', '192.168.50.11'),
    ]


def test_arp_table_excludes_broadcast_and_multicast(monkeypatch):
    out = (
        "  192.168.50.10         aa-bb-cc-dd-ee-ff     dynamic\n"
        "  192.168.50.255        ff-ff-ff-ff-ff-ff     static\n"
        "  224.0.0.22            01-00-5e-00-00-16     static\n"
        "  239.255.255.250       01-00-5e-7f-ff-fa     static\n"
    ).encode('utf-8')

    class _R:
        stdout = out

    monkeypatch.setattr(core.subprocess, 'run', lambda *a, **k: _R())
    monkeypatch.setattr(core.locale, 'getpreferredencoding', lambda *a: 'utf-8')
    assert core.arp_table() == [('aa-bb-cc-dd-ee-ff', '192.168.50.10')]


def test_arp_table_survives_undecodable_bytes(monkeypatch):
    """
    主控台代碼頁與 Python 預設編碼不一致時（cp950 很常見），
    原本 text=True 會拋 UnicodeDecodeError 讓 ARP 後援靜默失效。
    """
    out = b"  \xb0\xea\xbb\xda    \xa9\xf1\n  192.168.50.10   aa-bb-cc-dd-ee-ff   \xb0\xca\xba\xa1\n"

    class _R:
        stdout = out

    monkeypatch.setattr(core.subprocess, 'run', lambda *a, **k: _R())
    monkeypatch.setattr(core.locale, 'getpreferredencoding', lambda *a: 'utf-8')
    assert core.arp_table() == [('aa-bb-cc-dd-ee-ff', '192.168.50.10')]


def test_arp_table_no_arp_command_returns_empty(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(core.subprocess, 'run', _boom)
    assert core.arp_table() == []


@pytest.mark.parametrize("mac,is_static", [
    ("ff-ff-ff-ff-ff-ff", True),
    ("FF:FF:FF:FF:FF:FF", True),
    ("01-00-5e-00-00-16", True),
    ("33-33-00-00-00-01", True),
    ("aa-bb-cc-dd-ee-ff", False),
    ("50-5a-65-f9-b1-5e", False),
])
def test_is_static_arp_mac(mac, is_static):
    assert core._is_static_arp_mac(mac) is is_static
