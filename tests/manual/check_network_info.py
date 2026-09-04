#!/usr/bin/env python3
"""
臨時測試：嘗試讀取 CAPAROC 設備的網路資訊
  0xF5 TCP/IP Interface  attr3=Interface Config, attr5=Hostname
  0xF6 Ethernet Link     attr3=MAC Address

用法：
  python tests/manual/check_network_info.py [IP]
  python tests/manual/check_network_info.py 192.168.50.111
"""
import sys
import struct
from pycomm3 import CIPDriver

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.111"

READS = [
    ("TCP/IP  attr3 Interface Config", 0xF5, 1, 3),
    ("TCP/IP  attr5 Hostname",         0xF5, 1, 5),
    ("EthLink attr3 MAC Address",      0xF6, 1, 3),
    ("EthLink attr1 Interface Speed",  0xF6, 1, 1),  # 額外：速率/雙工，常見支援
]

def parse_tcpip_config(data: bytes):
    """Interface Configuration struct: IP(4) + Subnet(4) + Gateway(4) + DNS1(4) + DNS2(4)"""
    if len(data) < 20:
        return f"  ⚠ 資料長度不足 ({len(data)} bytes)"
    ip      = ".".join(str(b) for b in data[0:4])
    subnet  = ".".join(str(b) for b in data[4:8])
    gateway = ".".join(str(b) for b in data[8:12])
    dns1    = ".".join(str(b) for b in data[12:16])
    dns2    = ".".join(str(b) for b in data[16:20])
    return (f"  IP      : {ip}\n"
            f"  Subnet  : {subnet}\n"
            f"  Gateway : {gateway}\n"
            f"  DNS1    : {dns1}\n"
            f"  DNS2    : {dns2}")

def parse_mac(data: bytes):
    if len(data) < 6:
        return f"  ⚠ 資料長度不足 ({len(data)} bytes)"
    return "  MAC: " + ":".join(f"{b:02X}" for b in data[:6])

def parse_string(data: bytes):
    """CIP Short String: len(2LE) + chars"""
    if len(data) < 2:
        return f"  ⚠ 資料長度不足"
    length = struct.unpack_from("<H", data, 0)[0]
    text = data[2:2+length].decode("ascii", errors="replace")
    return f"  Hostname: '{text}'"

print(f"\n{'='*55}")
print(f"  CAPAROC 網路資訊讀取測試  →  {IP}")
print(f"{'='*55}\n")

with CIPDriver(IP) as driver:
    for label, cls, inst, attr in READS:
        print(f"[{label}]  class=0x{cls:02X} inst={inst} attr={attr}")

        # 先試 unconnected（標準 EtherNet/IP 網路物件常用此模式）
        for connected in (False, True):
            mode = "connected" if connected else "unconnected"
            try:
                resp = driver.generic_message(
                    service=0x0E,
                    class_code=cls,
                    instance=inst,
                    attribute=attr,
                    connected=connected,
                    unconnected_send=not connected,
                )
                if resp and not (hasattr(resp, 'error') and resp.error):
                    raw = bytes(resp.value) if resp.value is not None else b''
                    print(f"  ✅ [{mode}] 成功  raw={raw.hex()  if raw else '(empty)'}")
                    # 解析
                    if cls == 0xF5 and attr == 3:
                        print(parse_tcpip_config(raw))
                    elif cls == 0xF5 and attr == 5:
                        print(parse_string(raw))
                    elif cls == 0xF6 and attr == 3:
                        print(parse_mac(raw))
                    else:
                        print(f"  raw bytes: {list(raw)}")
                    break  # 成功就不再試另一種模式
                else:
                    err = getattr(resp, 'error', resp) if resp else 'None'
                    print(f"  ❌ [{mode}] 失敗: {err}")
            except Exception as e:
                print(f"  ❌ [{mode}] 例外: {e}")
        print()

print("測試完成。")
