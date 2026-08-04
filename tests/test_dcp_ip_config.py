#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROFINET DCP IP 設定工具

透過 PROFINET DCP（Layer 2）探索並設定 CAPAROC 設備 IP，
不需要事先知道設備 IP，DHCP 狀態下也可使用。

功能：
  [1] DCP Identify All  — 廣播探索所有 PROFINET 設備（顯示 IP/MAC/名稱）
  [2] DCP Set IP        — 透過 MAC 設定靜態 IP（不需知道目前 IP）
  [0] 離開

⚠️  須以「管理員身份」執行（scapy 需要 raw socket）：
    在管理員 PowerShell 中：
        conda activate sv
        python tests/test_dcp_ip_config.py
"""

import sys
import struct
import socket
from pathlib import Path

# ── DCP 常數 ─────────────────────────────────────────────────
DCP_MULTICAST_MAC = "01:0e:cf:00:00:00"
ETHERTYPE_PROFINET = 0x8892
FRAMEID_IDENTIFY_REQ = 0xFEFF  # DCP Identify All Request
FRAMEID_IDENTIFY_RSP = 0xFEFE  # DCP Identify Response
FRAMEID_SET_REQ      = 0xFEFD  # DCP Set Request

SVC_IDENTIFY = 0x05
SVC_SET      = 0x04


def _check_requirements() -> bool:
    """確認 scapy 可用且為管理員身份"""
    try:
        import scapy.all  # noqa: F401
    except ImportError:
        print("❌ scapy 未安裝，請執行：conda run -n sv pip install scapy")
        return False

    try:
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("❌ 請以「管理員身份」執行 PowerShell 後再試")
            return False
    except Exception:
        pass

    return True


def _pick_iface() -> str | None:
    """列出網卡，讓使用者選擇正確的介面"""
    from scapy.all import get_if_list, get_if_addr
    ifaces = get_if_list()
    print("\n  可用網卡：")
    valid = []
    for i, name in enumerate(ifaces, 1):
        try:
            ip = get_if_addr(name)
        except Exception:
            ip = "?"
        if ip not in ("0.0.0.0", "?", ""):
            print(f"  [{i}] {name}  ({ip})")
            valid.append((name, ip))

    if not valid:
        print("  ⚠️  找不到有 IP 的網卡")
        return None
    if len(valid) == 1:
        print(f"\n  自動選擇：{valid[0][0]} ({valid[0][1]})")
        return valid[0][0]

    choice = input("\n  選擇網卡編號: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(valid):
        return valid[int(choice) - 1][0]
    return None


def _build_identify_pkt(iface: str):
    """組裝 DCP Identify All Request 封包"""
    from scapy.all import Ether, Raw, get_if_hwaddr
    src_mac = get_if_hwaddr(iface)
    payload = (
        struct.pack('>H', FRAMEID_IDENTIFY_REQ) +  # FrameID
        bytes([SVC_IDENTIFY, 0x00]) +               # ServiceID, ServiceType=Request
        struct.pack('>I', 1) +                      # Xid
        struct.pack('>H', 1) +                      # ResponseDelay
        struct.pack('>H', 4) +                      # DCPDataLength
        bytes([0xFF, 0xFF]) +                       # Option=All, SubOption=All
        struct.pack('>H', 0)                        # BlockLength=0
    )
    return Ether(src=src_mac, dst=DCP_MULTICAST_MAC, type=ETHERTYPE_PROFINET) / \
           __import__('scapy.all', fromlist=['Raw']).Raw(load=payload)


def _parse_identify_response(raw: bytes, src_mac: str) -> dict | None:
    """解析 DCP Identify Response，回傳設備資訊 dict"""
    # Ethernet header = 14 bytes；PROFINET 從 byte 14 開始
    if len(raw) < 26:
        return None
    dcp = raw[14:]
    frame_id = struct.unpack('>H', dcp[0:2])[0]
    if frame_id != FRAMEID_IDENTIFY_RSP:
        return None

    # DCP header: FrameID(2)+SvcID(1)+SvcType(1)+Xid(4)+Delay(2)+DataLen(2) = 12
    data_len = struct.unpack('>H', dcp[10:12])[0]
    blocks = dcp[12:12 + data_len]

    info = {'mac': src_mac, 'ip': None, 'subnet': None, 'gateway': None, 'name': None}
    i = 0
    while i + 4 <= len(blocks):
        opt     = blocks[i]
        sub_opt = blocks[i + 1]
        blen    = struct.unpack('>H', blocks[i + 2:i + 4])[0]
        bdata   = blocks[i + 4: i + 4 + blen]

        if opt == 0x01 and sub_opt == 0x02 and len(bdata) >= 14:
            # IP Suite: qualifier(2) + IP(4) + Subnet(4) + GW(4)
            info['ip']      = socket.inet_ntoa(bdata[2:6])
            info['subnet']  = socket.inet_ntoa(bdata[6:10])
            info['gateway'] = socket.inet_ntoa(bdata[10:14])

        elif opt == 0x02 and sub_opt == 0x02 and len(bdata) >= 2:
            # Station Name (NameOfStation)
            nlen = struct.unpack('>H', bdata[0:2])[0] if len(bdata) >= 2 else 0
            info['name'] = bdata[2:2 + nlen].decode('ascii', errors='replace') if nlen else None

        i += 4 + blen + (blen % 2)  # 對齊偶數

    return info if info['ip'] else None


def dcp_identify(iface: str, timeout: float = 3.0) -> list[dict]:
    """廣播 DCP Identify All，回傳找到的設備清單"""
    from scapy.all import sendp, sniff
    pkt = _build_identify_pkt(iface)
    print(f"  發送 DCP Identify All → {DCP_MULTICAST_MAC}  (iface={iface})")
    sendp(pkt, iface=iface, verbose=False)

    print(f"  等待回應 {timeout} 秒...")
    responses = sniff(
        iface=iface,
        filter=f"ether proto {ETHERTYPE_PROFINET}",
        timeout=timeout
    )

    devices = []
    seen = set()
    for pkt in responses:
        raw = bytes(pkt)
        src_mac = pkt.src if hasattr(pkt, 'src') else '?'
        if src_mac in seen or src_mac == DCP_MULTICAST_MAC:
            continue
        seen.add(src_mac)
        info = _parse_identify_response(raw, src_mac)
        if info:
            devices.append(info)

    return devices


def dcp_set_ip(iface: str, target_mac: str, new_ip: str,
               subnet: str = "255.255.255.0", gateway: str = "0.0.0.0") -> bool:
    """
    透過 DCP Set IP（Layer 2）設定指定 MAC 的設備 IP，不需知道目前 IP。
    回傳 True=成功送出（設備不一定立即回應）。
    """
    from scapy.all import Ether, Raw, get_if_hwaddr, sendp, sniff

    src_mac = get_if_hwaddr(iface)

    # IP Suite block: qualifier(2) + IP(4) + Subnet(4) + GW(4)
    ip_block = (
        struct.pack('>H', 0x0001) +          # qualifier: permanent
        socket.inet_aton(new_ip) +
        socket.inet_aton(subnet) +
        socket.inet_aton(gateway)
    )
    block = (
        bytes([0x01, 0x02]) +                # Option=IP, SubOption=IP Suite
        struct.pack('>H', len(ip_block)) +
        ip_block
    )
    payload = (
        struct.pack('>H', FRAMEID_SET_REQ) +
        bytes([SVC_SET, 0x00]) +
        struct.pack('>I', 2) +               # Xid
        struct.pack('>H', 0) +               # ResponseDelay
        struct.pack('>H', len(block)) +
        block
    )

    # padding 到偶數
    if len(payload) % 2:
        payload += b'\x00'

    pkt = Ether(src=src_mac, dst=target_mac, type=ETHERTYPE_PROFINET) / \
          Raw(load=payload)

    print(f"\n  DCP Set IP → {target_mac}")
    print(f"  IP={new_ip}  Subnet={subnet}  GW={gateway if gateway != '0.0.0.0' else '（未設定）'}")
    sendp(pkt, iface=iface, verbose=False)

    # 等待確認回應（有些設備會回 Set Response）
    resp = sniff(
        iface=iface,
        filter=f"ether proto {ETHERTYPE_PROFINET}",
        timeout=2.0, count=5
    )
    for r in resp:
        raw = bytes(r)
        if len(raw) >= 16:
            frame_id = struct.unpack('>H', raw[14:16])[0]
            svc_type = raw[17] if len(raw) > 17 else 0xFF
            if svc_type == 0x01:  # Response
                print("  ✅ 收到設備回應（Set Response）")
                return True

    print("  ⚠️  未收到確認回應（設備可能仍在套用，這是正常的）")
    return True


# ── 互動主程式 ──────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  PROFINET DCP IP 設定工具")
    print("  Layer 2 直接通訊，不需知道設備 IP")
    print("=" * 55)

    if not _check_requirements():
        return

    iface = _pick_iface()
    if not iface:
        print("❌ 無法選擇網卡")
        return

    devices = []

    while True:
        print("\n  [1] DCP Identify — 探索所有 PROFINET 設備")
        print("  [2] DCP Set IP  — 透過 MAC 設定靜態 IP")
        print("  [0] 離開")
        choice = input("\n  請選擇: ").strip()

        if choice == '0':
            break

        elif choice == '1':
            print("\n── DCP Identify All ──────────────────────────────────")
            devices = dcp_identify(iface)
            if not devices:
                print("  ⚠️  無回應，請確認：")
                print("     1. 選擇的網卡是否連接到設備所在網路")
                print("     2. 設備是否已開機")
            else:
                print(f"\n  發現 {len(devices)} 台設備：")
                print(f"  {'#':>2}  {'IP 位址':<18}  {'MAC 位址':<20}  名稱")
                print("  " + "-" * 60)
                for i, d in enumerate(devices, 1):
                    name = d.get('name') or '（未知）'
                    print(f"  {i:>2}  {d['ip']:<18}  {d['mac']:<20}  {name}")

        elif choice == '2':
            if not devices:
                print("  ⚠️  請先執行 [1] 探索設備")
                continue

            # 選擇目標設備
            if len(devices) == 1:
                target = devices[0]
                print(f"\n  目標設備：{target['mac']}  （目前 IP: {target['ip']}）")
            else:
                idx = input(f"  選擇設備編號 [1-{len(devices)}]: ").strip()
                if not idx.isdigit() or not (1 <= int(idx) <= len(devices)):
                    continue
                target = devices[int(idx) - 1]

            new_ip = input("  新 IP 位址（cancel 取消）: ").strip()
            if new_ip.lower() == 'cancel':
                continue

            subnet_in = input("  子網路遮罩 [Enter=255.255.255.0]: ").strip()
            subnet = subnet_in if subnet_in else "255.255.255.0"

            gw_in = input("  預設閘道   [Enter=0.0.0.0 不設定]: ").strip()
            gateway = gw_in if gw_in else "0.0.0.0"

            confirm = input(f"\n  確認將 {target['mac']} 的 IP 設為 {new_ip}？ [Y/N]: ").strip().upper()
            if confirm != 'Y':
                continue

            dcp_set_ip(iface, target['mac'], new_ip, subnet, gateway)
            print(f"\n  設定完成，請用以下指令驗證：")
            print(f"  python tests/test_ip_config.py {new_ip}")

        else:
            print("  ⚠️  請輸入 0~2")


if __name__ == "__main__":
    main()
