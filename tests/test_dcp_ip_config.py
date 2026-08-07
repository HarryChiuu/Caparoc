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
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


def _check_port_67() -> bool:
    """確認 port 67 可用；占用時顯示是哪個程式"""
    test = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        test.bind(('', 67))
        return True
    except OSError:
        print("  ❌ port 67 被占用，無法啟動 mini DHCP server")
        try:
            r = subprocess.run(
                ['powershell', '-c',
                 'Get-NetUDPEndpoint -LocalPort 67 | ForEach-Object {'
                 ' $p = Get-Process -Id $_.OwningProcess -EA SilentlyContinue;'
                 ' "$($p.Name) (PID $($_.OwningProcess))" }'],
                capture_output=True, text=True, timeout=5
            )
            if r.stdout.strip():
                print(f"     占用程式：{r.stdout.strip()}")
        except Exception:
            pass
        print("  ⚠️  請先關閉占用 port 67 的程式（例如 BootP-DHCP Tool）後再試")
        return False
    finally:
        test.close()


def _build_dhcp_reply(xid: bytes, chaddr: bytes, offered_ip: str,
                       server_ip: str, subnet: str, msg_type: int,
                       client_flags: bytes = b'\x80\x00') -> bytes:
    """組裝 DHCP Offer（msg_type=2）或 ACK（msg_type=5）封包"""
    pkt = bytes([2, 1, 6, 0])            # op=Reply, htype=Eth, hlen=6, hops=0
    pkt += xid                            # Transaction ID
    pkt += b'\x00\x00' + client_flags    # secs=0, flags（繼承 client 的 flags）
    pkt += b'\x00' * 4                   # ciaddr
    pkt += socket.inet_aton(offered_ip)  # yiaddr
    pkt += b'\x00' * 4                   # siaddr（DHCP 標準用 Option 54 識別 server）
    pkt += b'\x00' * 4                   # giaddr
    pkt += chaddr + b'\x00' * 10         # chaddr (6 + 10 padding = 16)
    pkt += b'\x00' * 64                  # sname
    pkt += b'\x00' * 128                 # file
    pkt += b'\x63\x82\x53\x63'          # DHCP magic cookie
    pkt += bytes([53, 1, msg_type])      # Option 53: message type
    pkt += bytes([54, 4]) + socket.inet_aton(server_ip)   # Option 54: server ID
    pkt += bytes([51, 4, 0, 1, 81, 128])  # Option 51: lease 86400s
    pkt += bytes([1, 4]) + socket.inet_aton(subnet)       # Option 1: subnet mask
    pkt += bytes([3, 4]) + socket.inet_aton(server_ip)    # Option 3: router（必要）
    pkt += b'\xff'                        # Option 255: end
    # DHCP 封包最小 300 bytes（向後相容 BOOTP）
    if len(pkt) < 300:
        pkt += b'\x00' * (300 - len(pkt))
    return pkt


def _mini_dhcp_server(server_ip: str, target_mac: str,
                       assign_ip: str, subnet: str = "255.255.255.0",
                       timeout: float = None) -> bool:
    """
    回應指定 MAC 的 DHCP Discover/Request，分配 assign_ip。
    timeout=None 表示持續監聽不限時，Ctrl+C 可中斷。
    回傳 True = 設備成功取得 IP。
    """
    target_bytes = bytes(int(x, 16) for x in target_mac.replace('-', ':').split(':'))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1.0)
    sock.bind(('', 67))

    deadline = time.time() + timeout if timeout else None
    offered = False
    try:
        while True:
            if deadline and time.time() > deadline:
                break
            try:
                data, _ = sock.recvfrom(1024)
            except socket.timeout:
                continue
            if len(data) < 240 or data[236:240] != b'\x63\x82\x53\x63':
                continue
            chaddr = data[28:34]
            if chaddr != target_bytes:
                continue
            xid = data[4:8]
            # 解析 message-type option
            msg_type, i = None, 240
            client_flags = data[10:12]  # 保存 client 的 flags 供 reply 使用
            while i < len(data) - 1:
                opt = data[i]
                if opt == 255: break
                if opt == 0: i += 1; continue
                length = data[i + 1]
                if opt == 53 and length >= 1:
                    msg_type = data[i + 2]
                i += 2 + length
            if msg_type == 1:  # Discover → Offer
                reply = _build_dhcp_reply(xid, chaddr, assign_ip, server_ip, subnet, 2, client_flags)
                sock.sendto(reply, ('255.255.255.255', 68))
                print(f"  📤 DHCP Offer → {assign_ip}")
                offered = True
            elif msg_type == 3:  # Request → ACK
                reply = _build_dhcp_reply(xid, chaddr, assign_ip, server_ip, subnet, 5, client_flags)
                sock.sendto(reply, ('255.255.255.255', 68))
                print(f"  ✅ DHCP ACK → 設備已取得 {assign_ip}")
                return True
            else:
                print(f"  [debug] 收到 DHCP msg_type={msg_type} from {':'.join(f'{b:02x}' for b in chaddr)}")
    finally:
        sock.close()
    return False


def _wait_for_dhcp_ip(target_mac: str, timeout: float = 30.0) -> str | None:
    """輪詢 ARP table 等 target_mac 的 DHCP IP 出現，測試 port 44818 確認可連"""
    mac_variants = {target_mac.lower(), target_mac.replace(':', '-').lower()}
    print(f"  等待設備取得 DHCP IP（最多 {int(timeout)} 秒）...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            ip, mac = parts[0], parts[1].lower()
            if mac not in mac_variants:
                continue
            try:
                with socket.create_connection((ip, 44818), timeout=0.8):
                    print(f"  ✅ 設備在 {ip}（port 44818 可連）")
                    return ip
            except OSError:
                pass
        time.sleep(2)
        print("  ...", end='\r')
    return None


def _cip_fix_as_static(device_ip: str, new_ip: str = None,
                        subnet: str = "255.255.255.0", gateway: str = "") -> bool:
    """
    透過 CIP 連線，固化靜態 IP。
    - new_ip 為 None：保留 DHCP 取得的 IP，僅寫 Attr3=0x00
    - new_ip 指定：寫 Attr5（新 IP）+ Attr3=0x00
    """
    from caparoc_backend import CaparocBackend
    from pycomm3 import CIPDriver

    backend = CaparocBackend(device_ip)
    target = new_ip if new_ip else device_ip
    print(f"\n  連接 {device_ip}，固化靜態 IP {target}...")
    try:
        with CIPDriver(device_ip) as driver:
            if new_ip and new_ip != device_ip:
                result = backend.set_device_ip(driver, new_ip, subnet, gateway)
            else:
                import struct as _s
                try:
                    driver.generic_message(
                        service=0x10, class_code=0xF5, instance=1,
                        attribute=3, request_data=_s.pack('<I', 0), connected=True
                    )
                    result = {'success': True, 'error': None}
                except Exception:
                    result = {'success': True, 'error': None}  # RST 視為成功

            if result['success']:
                target = new_ip if new_ip else device_ip
                print(f"  ✅ 指令送出完成")
                print(f"  ⏳ 等待設備套用設定（10 秒）...")
                time.sleep(10)
                try:
                    with socket.create_connection((target, 44818), timeout=3):
                        print(f"  ✅ 驗證成功：設備已在 {target}")
                        print(f"     python tests/test_ip_config.py {target}")
                except OSError:
                    print(f"  ⚠️  10 秒後仍無法連線，請稍後再試")
                    print(f"     python tests/test_ip_config.py {target}")
            else:
                print(f"  ❌ 失敗: {result['error']}")
            return result['success']
    except Exception as e:
        print(f"  ❌ CIP 連線失敗: {e}")
        return False


def main():
    print("=" * 55)
    print("  PROFINET DCP / DHCP IP 設定工具")
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
        print("\n  [1] DCP Identify      — 探索所有 PROFINET 設備 ⚠️ 此設備不支援")
        print("  [2] DCP Set IP        — 透過 MAC 設定 IP（需先 [1]）⚠️ 此設備不支援")
        print("  [3] DCP Set IP        — 直接輸入 MAC ⚠️ 此設備不支援")
        print("  [4] 監聽 DHCP Discover — 從 DHCP 封包讀出 MAC ✅")
        print("  [5] 新設備完整設定     — mini DHCP → CIP 固化靜態 ✅")
        print("  [0] 離開")
        choice = input("\n  請選擇: ").strip()

        if choice == '0':
            break

        elif choice == '1':
            print("\n── DCP Identify All ──────────────────────────────────")
            print("  ⚠️  此功能對 CAPAROC 設備無效（scapy 無法接收入站封包）")
            print("     請改用 [4] 監聽 DHCP 取得 MAC")

        elif choice in ('2', '3'):
            print("\n  ⚠️  DCP Set IP 對此設備無效（設備不接受 PN-DCP Set 指令）")
            print("     請改用 [5] 完整設定流程")

        elif choice == '4':
            print("\n── 監聽 DHCP Discover（等待設備廣播）────────────────────")
            found_mac = _listen_dhcp_discover(iface)
            if found_mac:
                ans = input(f"\n  發現 MAC: {found_mac}，立即進入 [5] 設定靜態 IP？ [Y/N]: ").strip().upper()
                if ans == 'Y':
                    choice = '5_with_mac'
                    # 帶著已知 MAC 直接進入 [5] 流程
                    _run_new_device_setup(iface, prefill_mac=found_mac)
            else:
                print("  ⚠️  超時，請重插設備網路線後再試")

        elif choice == '5':
            _run_new_device_setup(iface)

        else:
            print("  ⚠️  請輸入 0~5")


def _run_new_device_setup(iface: str, prefill_mac: str = None):
    """
    新設備完整設定：mini DHCP server 分配 IP → CIP 固化靜態。
    prefill_mac: 已從 [4] 取得的 MAC，跳過監聽步驟。
    """
    print("\n── 新設備完整設定（mini DHCP → CIP 固化靜態）──────────")
    print("  前提：PC 在 192.168.50.x 網段，BootP-DHCP Tool 已關閉\n")

    # 自檢 port 67
    if not _check_port_67():
        return

    from scapy.all import get_if_addr
    server_ip = get_if_addr(iface)
    if not server_ip or server_ip in ('0.0.0.0', ''):
        print("  ❌ 無法取得此網卡 IP")
        return
    print(f"  PC IP（DHCP server）: {server_ip}")

    # Step 1: 取得設備 MAC
    if prefill_mac:
        target_mac = prefill_mac
        print(f"\n  Step 1: 設備 MAC（已從 DHCP 監聽取得）: {target_mac}")
    else:
        print("\n  Step 1: 取得設備 MAC")
        sub = input("    [1] 輸入已知 MAC  [2] 監聽 DHCP Discover（30秒）: ").strip()
        if sub == '1':
            target_mac = input("    MAC（格式 cc:cc:ea:9f:c9:72）: ").strip().lower()
        else:
            print("    等待設備 DHCP Discover（30秒），請確認設備已接上網路...")
            target_mac = _listen_dhcp_discover(iface, timeout=30.0)
            if not target_mac:
                target_mac = input("    未偵測到，手動輸入 MAC（留空取消）: ").strip().lower()
        if not target_mac:
            return

    # Step 2: 目標靜態 IP
    assign_ip = input(f"\n  目標靜態 IP（e.g. 192.168.50.223）: ").strip()
    if not assign_ip:
        return
    subnet_in = input("  子網路遮罩 [Enter=255.255.255.0]: ").strip()
    subnet = subnet_in if subnet_in else "255.255.255.0"

    print(f"\n  設備 MAC : {target_mac}")
    print(f"  目標 IP  : {assign_ip}")
    if input("  確認啟動 mini DHCP server？ [Y/N]: ").strip().upper() != 'Y':
        return

    print(f"\n  mini DHCP server 已啟動，持續監聽（按 Ctrl+C 中斷）")
    print(f"  ⚡ 請現在重插設備網路線！")
    print(f"     或在另一個視窗: python tests/test_ip_config.py <目前IP> → [3] 切 DHCP")

    try:
        got = _mini_dhcp_server(server_ip, target_mac, assign_ip, subnet, timeout=None)
    except KeyboardInterrupt:
        print("\n  中斷")
        return

    if not got:
        return

    print(f"\n  等待設備上線（10 秒）...")
    for i in range(10, 0, -1):
        print(f"  {i}s...", end='\r')
        time.sleep(1)
    print()
    _cip_fix_as_static(assign_ip)


if __name__ == "__main__":
    main()

