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
FRAMEID_IDENTIFY_REQ = 0xFEFF  # DCP Identify All Request (also used for response, ServiceType=0x01)
FRAMEID_SET_REQ      = 0xFEFD  # DCP Set Request

SVC_IDENTIFY = 0x05
SVC_SET      = 0x04


def _check_requirements() -> bool:
    """確認 scapy 可用；Npcap WinPcap 相容模式下不需管理員"""
    try:
        import scapy.all  # noqa: F401
    except ImportError:
        print("❌ scapy 未安裝，請執行：conda run -n sv pip install scapy")
        return False
    return True


def _pick_iface() -> str | None:
    """列出非 Loopback 網卡（含 MAC），讓使用者選擇實體介面"""
    from scapy.all import get_if_list, get_if_addr, get_if_hwaddr
    ifaces = get_if_list()
    print("\n  可用網卡（含 MAC，選實體乙太網卡）：")
    print(f"  {'#':>2}  {'IP 位址':<18}  {'MAC 位址':<20}  介面名稱")
    print("  " + "-" * 70)
    valid = []
    for name in ifaces:
        if 'loopback' in name.lower():
            continue
        try:
            ip  = get_if_addr(name)
            mac = get_if_hwaddr(name)
        except Exception:
            ip, mac = "?", "?"
        if ip.startswith("127.") or mac in ("?", "00:00:00:00:00:00"):
            continue
        idx = len(valid) + 1
        ip_disp = ip if ip not in ("0.0.0.0", "", "?") else "(無 IP / DHCP 待分配)"
        print(f"  [{idx}]  {ip_disp:<18}  {mac:<20}  {name}")
        valid.append((name, ip, mac))

    if not valid:
        print("  ⚠️  找不到可用網卡")
        return None
    if len(valid) == 1:
        n, ip, mac = valid[0]
        print(f"\n  自動選擇：{mac}  {ip}  ({n})")
        return n

    choice = input("\n  選擇網卡編號（選連接設備的實體網卡）: ").strip()
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
    """解析 DCP Identify Response（FrameID=0xFEFF, ServiceType=0x01）"""
    if len(raw) < 26:
        return None
    dcp = raw[14:]
    frame_id   = struct.unpack('>H', dcp[0:2])[0]
    svc_type   = dcp[3] if len(dcp) > 3 else 0xFF
    # Response: FrameID=0xFEFF, ServiceType=0x01
    if frame_id != FRAMEID_IDENTIFY_REQ or svc_type != 0x01:
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

    # 先做 2 秒全封包測試，確認介面有收到東西
    print(f"  測試介面（抓 2s 所有封包）...")
    test_pkts = sniff(iface=iface, timeout=2, count=20)
    if test_pkts:
        macs = set()
        for p in test_pkts:
            if hasattr(p, 'src') and p.src not in ('ff:ff:ff:ff:ff:ff', '00:00:00:00:00:00'):
                macs.add(p.src)
        print(f"  ✅ 介面有流量，看到 {len(test_pkts)} 個封包，來源 MAC: {', '.join(list(macs)[:5])}")
    else:
        print("  ⚠️  介面無任何流量，可能選錯網卡。請重新選擇。")
        return []

    pkt = _build_identify_pkt(iface)
    print(f"  發送 DCP Identify All → {DCP_MULTICAST_MAC}  (iface={iface})")
    try:
        sendp(pkt, iface=iface, verbose=False)
    except PermissionError:
        print("  ❌ PermissionError：請以管理員身份執行，或確認 Npcap 以 WinPcap 相容模式安裝")
        return []
    except Exception as e:
        print(f"  ❌ 發送失敗: {e}")
        return []

    print(f"  等待回應 {timeout} 秒...")
    # 不下 pcap filter，在 Python 層過濾 EtherType 0x8892，避免 filter 語法問題
    responses = sniff(
        iface=iface,
        timeout=timeout,
        lfilter=lambda p: hasattr(p, 'type') and p.type == ETHERTYPE_PROFINET
    )

    # debug: 顯示所有收到的 PROFINET 封包 raw hex
    if responses:
        print(f"  收到 {len(responses)} 個 PROFINET 封包（raw debug）:")
        for i, pkt in enumerate(responses):
            raw = bytes(pkt)
            src = pkt.src if hasattr(pkt, 'src') else '?'
            fid = f"0x{struct.unpack('>H', raw[14:16])[0]:04X}" if len(raw) >= 16 else '?'
            svc = f"svcType=0x{raw[17]:02X}" if len(raw) >= 18 else ''
            print(f"    [{i+1}] src={src}  FrameID={fid}  {svc}  len={len(raw)}")

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
        lfilter=lambda p: hasattr(p, 'type') and p.type == ETHERTYPE_PROFINET,
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
def _listen_dhcp_discover(iface: str, timeout: float = 30.0) -> str | None:
    """
    監聽 DHCP Discover，從 CHADDR 欄位讀出設備 MAC。
    自動排除 PC 自身 MAC，回傳找到的設備 MAC 或 None。
    """
    import time
    from scapy.all import get_if_hwaddr

    # 取得本機 MAC，用來排除 PC 自己的 DHCP
    try:
        own_mac = get_if_hwaddr(iface).lower()
    except Exception:
        own_mac = ''

    # ── 方法 A: 標準 UDP socket (port 67) ──────────────────
    import socket as _sock
    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
        s.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
        s.setsockopt(_sock.SOL_SOCKET, _sock.SO_BROADCAST, 1)
        s.settimeout(2.0)
        s.bind(('', 67))
        print(f"  監聽 UDP port 67（最多 {int(timeout)} 秒）... Ctrl+C 中斷")
        seen = set()
        deadline = time.time() + timeout
        found_mac = None
        try:
            while time.time() < deadline:
                try:
                    data, _ = s.recvfrom(1024)
                except _sock.timeout:
                    continue
                if len(data) < 34 or data[0] != 1:
                    continue
                chaddr = data[28:34]
                mac = ':'.join(f'{b:02x}' for b in chaddr)
                if mac in seen or mac == '00:00:00:00:00:00' or mac == own_mac:
                    continue
                seen.add(mac)
                print(f"\n  ✅ 發現設備 MAC: {mac}")
                found_mac = mac
                break
        except KeyboardInterrupt:
            pass
        finally:
            s.close()
        return found_mac

    except (PermissionError, OSError):
        print("  ⚠️  port 67 無法綁定，改用 scapy 監聽...")

    # ── 方法 B: scapy sniff ──────────────────────────────
    from scapy.all import sniff, DHCP, IP
    found = []
    print(f"  等待 DHCP Discover（最多 {int(timeout)} 秒）... 請重插設備網路線")

    def handle(pkt):
        if not (pkt.haslayer(DHCP) and pkt.haslayer(IP)):
            return
        if pkt[IP].src != '0.0.0.0':
            return
        opts = dict(o for o in pkt[DHCP].options if isinstance(o, tuple))
        if opts.get('message-type') != 1:
            return
        src_mac = pkt.src.lower() if hasattr(pkt, 'src') else ''
        if src_mac in (own_mac, '') or src_mac in found:
            return
        found.append(src_mac)
        print(f"\n  ✅ 發現設備 MAC: {src_mac}")

    try:
        sniff(iface=iface, timeout=timeout, prn=handle,
              lfilter=lambda p: p.haslayer('DHCP') if hasattr(p, 'haslayer') else False)
    except KeyboardInterrupt:
        pass

    return found[0] if found else None


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
        print("  [2] DCP Set IP  — 透過 MAC 設定靜態 IP（需先探索）")
        print("  [3] DCP Set IP  — 直接輸入 MAC 設定 IP（不需探索）★")
        print("  [4] 監聽 DHCP Discover — 從設備 DHCP 封包讀出 MAC ★")
        print("  [0] 離開")
        choice = input("\n  請選擇: ").strip()

        if choice == '0':
            break

        elif choice == '1':
            print("\n── DCP Identify All ──────────────────────────────────")
            devices = dcp_identify(iface)
            if not devices:
                print("  ⚠️  無回應（可能是 scapy 無法接收入站封包）")
                print("     請改用 [4] 監聽 DHCP，或 [3] 直接輸入 MAC")
            else:
                print(f"\n  發現 {len(devices)} 台設備：")
                print(f"  {'#':>2}  {'IP 位址':<18}  {'MAC 位址':<20}  名稱")
                print("  " + "-" * 60)
                for i, d in enumerate(devices, 1):
                    name = d.get('name') or '（未知）'
                    print(f"  {i:>2}  {d['ip']:<18}  {d['mac']:<20}  {name}")

        elif choice in ('2', '3'):
            if choice == '2':
                if not devices:
                    print("  ⚠️  請先執行 [1] 探索設備，或改用 [3] 直接輸入 MAC")
                    continue
                if len(devices) == 1:
                    target_mac = devices[0]['mac']
                    print(f"\n  目標設備：{target_mac}  （目前 IP: {devices[0]['ip']}）")
                else:
                    idx = input(f"  選擇設備編號 [1-{len(devices)}]: ").strip()
                    if not idx.isdigit() or not (1 <= int(idx) <= len(devices)):
                        continue
                    target_mac = devices[int(idx) - 1]['mac']
            else:
                print("\n── DCP Set IP（直接指定 MAC）─────────────────────────")
                print("  設備 MAC 可從設備標籤、Wireshark 或 [4] 監聽 DHCP 取得")
                target_mac = input("  設備 MAC 位址（格式 cc:cc:ea:9f:c9:72）: ").strip().lower()
                if not target_mac:
                    continue

            new_ip = input("  新 IP 位址（cancel 取消）: ").strip()
            if new_ip.lower() == 'cancel':
                continue
            subnet_in = input("  子網路遮罩 [Enter=255.255.255.0]: ").strip()
            subnet = subnet_in if subnet_in else "255.255.255.0"
            gw_in = input("  預設閘道   [Enter=0.0.0.0 不設定]: ").strip()
            gateway = gw_in if gw_in else "0.0.0.0"
            confirm = input(f"\n  確認將 {target_mac} 的 IP 設為 {new_ip}？ [Y/N]: ").strip().upper()
            if confirm != 'Y':
                continue
            dcp_set_ip(iface, target_mac, new_ip, subnet, gateway)
            print(f"\n  完成！請等待 2-3 秒後，用以下指令驗證：")
            print(f"  python tests/test_ip_config.py {new_ip}")

        elif choice == '4':
            print("\n── 監聽 DHCP Discover（等待設備廣播）────────────────────")
            found_mac = _listen_dhcp_discover(iface)
            if found_mac:
                ans = input(f"\n  立即對 {found_mac} 設定靜態 IP？ [Y/N]: ").strip().upper()
                if ans == 'Y':
                    new_ip = input("  新 IP 位址: ").strip()
                    subnet_in = input("  子網路遮罩 [Enter=255.255.255.0]: ").strip()
                    subnet = subnet_in if subnet_in else "255.255.255.0"
                    gw_in = input("  預設閘道   [Enter=0.0.0.0]: ").strip()
                    gateway = gw_in if gw_in else "0.0.0.0"
                    dcp_set_ip(iface, found_mac, new_ip, subnet, gateway)
                    print(f"\n  完成！請等待 3 秒後驗證：")
                    print(f"  python tests/test_ip_config.py {new_ip}")
            else:
                print("  ⚠️  超時未收到 DHCP Discover，請重插設備網路線後再試")

        else:
            print("  ⚠️  請輸入 0~4")

        if choice == '0':
            break

        elif choice == '1':
            print("\n── DCP Identify All ──────────────────────────────────")
            devices = dcp_identify(iface)
            if not devices:
                print("  ⚠️  無回應（可能是 scapy 無法接收入站封包）")
                print("     請改用 [3] 直接輸入 MAC 設定 IP")
            else:
                print(f"\n  發現 {len(devices)} 台設備：")
                print(f"  {'#':>2}  {'IP 位址':<18}  {'MAC 位址':<20}  名稱")
                print("  " + "-" * 60)
                for i, d in enumerate(devices, 1):
                    name = d.get('name') or '（未知）'
                    print(f"  {i:>2}  {d['ip']:<18}  {d['mac']:<20}  {name}")

        elif choice in ('2', '3'):
            if choice == '2':
                if not devices:
                    print("  ⚠️  請先執行 [1] 探索設備，或改用 [3] 直接輸入 MAC")
                    continue
                if len(devices) == 1:
                    target_mac = devices[0]['mac']
                    print(f"\n  目標設備：{target_mac}  （目前 IP: {devices[0]['ip']}）")
                else:
                    idx = input(f"  選擇設備編號 [1-{len(devices)}]: ").strip()
                    if not idx.isdigit() or not (1 <= int(idx) <= len(devices)):
                        continue
                    target_mac = devices[int(idx) - 1]['mac']
            else:
                # [3] 直接輸入 MAC
                print("\n── DCP Set IP（直接指定 MAC）─────────────────────────")
                print("  設備 MAC 可從設備標籤、Wireshark 或先前紀錄取得")
                target_mac = input("  設備 MAC 位址（格式 cc:cc:ea:9f:c9:72）: ").strip().lower()
                if not target_mac:
                    continue

            new_ip = input("  新 IP 位址（cancel 取消）: ").strip()
            if new_ip.lower() == 'cancel':
                continue

            subnet_in = input("  子網路遮罩 [Enter=255.255.255.0]: ").strip()
            subnet = subnet_in if subnet_in else "255.255.255.0"

            gw_in = input("  預設閘道   [Enter=0.0.0.0 不設定]: ").strip()
            gateway = gw_in if gw_in else "0.0.0.0"

            confirm = input(f"\n  確認將 {target_mac} 的 IP 設為 {new_ip}？ [Y/N]: ").strip().upper()
            if confirm != 'Y':
                continue

            dcp_set_ip(iface, target_mac, new_ip, subnet, gateway)
            print(f"\n  完成！請等待 2-3 秒後，用以下指令驗證：")
            print(f"  python tests/test_ip_config.py {new_ip}")

        else:
            print("  ⚠️  請輸入 0~3")


if __name__ == "__main__":
    main()
