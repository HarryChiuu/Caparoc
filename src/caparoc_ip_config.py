#!/usr/bin/env python3
"""
CAPAROC IP 設定工具

主選單（無參數執行時）：
  [1] 連線設備（自動探索 / 讀取 / 設定靜態 IP / 切換 DHCP）
  [2] 新裝置初始設定（DHCP 取得 IP → 設定為靜態 IP，需 scapy 選擇網卡）
  [0] 離開

連線設備選單：
  [1] 讀取目前設備網路設定
  [2] 設定靜態 IP
  [3] 切換為 DHCP 模式
  [0] 離開

用法：
  python src/caparoc_ip_config.py               # 顯示主選單
  python src/caparoc_ip_config.py 192.168.50.221  # 直連指定 IP，略過主選單
"""

import sys
import struct
import socket
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pycomm3 import CIPDriver
from caparoc_backend import CaparocBackend

# ── CIP 0xF5 常數 ────────────────────────────────────────────
CLASS_TCPIP = 0xF5
INST        = 1
SVC_GET     = 0x0E
SVC_SET     = 0x10
ATTR_CTRL   = 3   # Configuration Control: 0=Static, 2=DHCP
ATTR_IFACE  = 5   # Interface Configuration (IP/Subnet/Gateway/DNS)

CTRL_NAMES = {0: "Static IP", 1: "BOOTP", 2: "DHCP"}

_le2ip = lambda b, off: socket.inet_ntoa(b[off:off+4][::-1])
_ip2le = lambda ip: socket.inet_aton(ip)[::-1]

# ── 設備探索（EtherNet/IP List Identity + ARP fallback）──────

def _parse_list_identity(data: bytes, src_ip: str) -> dict | None:
    try:
        if len(data) < 30 or struct.unpack_from('<H', data, 0)[0] != 0x0063:
            return None
        off = 32
        if off + 16 > len(data):
            return None
        ip = socket.inet_ntoa(data[off+4:off+8])
        off += 16
        if off + 12 > len(data):
            return None
        vendor_id = struct.unpack_from('<H', data, off)[0]; off += 2
        off += 4  # device_type, product_code
        rev_major = data[off]; rev_minor = data[off+1]; off += 2
        off += 2  # status
        serial = struct.unpack_from('<I', data, off)[0]; off += 4
        name_len = data[off]; off += 1
        name = data[off:off+name_len].decode('ascii', errors='replace')
        return {'ip': ip, 'vendor_id': vendor_id, 'name': name,
                'revision': f"{rev_major}.{rev_minor}", 'serial': f"{serial:08X}"}
    except Exception:
        return None


def _get_broadcast_addresses() -> list[str]:
    broadcasts = {'255.255.255.255'}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith('127.'):
                continue
            parts = ip.split('.')
            if ip.startswith('169.254.'):
                broadcasts.add('169.254.255.255')
            else:
                broadcasts.add('.'.join(parts[:3]) + '.255')
    except Exception:
        pass
    return list(broadcasts)


def _eip_port_open(ip: str, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((ip, 44818), timeout=timeout):
            return True
    except OSError:
        return False


def _discover_devices(timeout: float = 2.0) -> list[dict]:
    EIP_PORT = 44818
    pkt = (struct.pack('<H', 0x0063) + struct.pack('<H', 0) +
           struct.pack('<I', 0) + struct.pack('<I', 0) +
           b'\x00' * 8 + struct.pack('<I', 0))
    devices, seen_ips = [], set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    try:
        for bcast in _get_broadcast_addresses():
            sock.sendto(pkt, (bcast, EIP_PORT))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(1024)
                if addr[0] not in seen_ips:
                    seen_ips.add(addr[0])
                    dev = _parse_list_identity(data, addr[0])
                    if dev:
                        devices.append(dev)
            except socket.timeout:
                pass
    finally:
        sock.close()
    return devices


def _discover_by_arp() -> list[dict]:
    result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
    mac_to_ips: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in ('動態', 'dynamic'):
            mac_to_ips.setdefault(parts[1], []).append(parts[0])
    devices = []
    for mac, ips in mac_to_ips.items():
        for ip in ips:
            if _eip_port_open(ip):
                devices.append({'ip': ip, 'mac': mac, 'name': f'MAC {mac}', 'via': 'ARP'})
    return devices


def run_discovery() -> str | None:
    broadcasts = _get_broadcast_addresses()
    print(f"\n探索設備（廣播：{', '.join(broadcasts)}）...")
    devices = _discover_devices(timeout=2.0)
    if not devices:
        print("  List Identity 無回應，改用 ARP table...")
        devices = _discover_by_arp()
    if not devices:
        print("  ❕ 未發現設備。可手動指定：python src/caparoc_ip_config.py <IP>")
        return None
    print(f"\n  {'#':>2}  {'IP 位址':<18}  產品名稱")
    print("  " + "-"*50)
    for i, d in enumerate(devices, 1):
        via = f" [{d.get('via','EIP')}]" if d.get('via') else ''
        sn = f"  S/N: {d['serial']}" if d.get('serial') else ''
        print(f"  {i:>2}  {d['ip']:<18}  {d['name']}{sn}{via}")
    print()
    if len(devices) == 1:
        ans = input("  選擇設備 [Enter=第1台 / 0=離開]: ").strip()
        return None if ans == '0' else devices[0]['ip']
    ans = input(f"  選擇編號 [1-{len(devices)} / 0=離開]: ").strip()
    if ans == '0' or not ans.isdigit():
        return None
    idx = int(ans) - 1
    return devices[idx]['ip'] if 0 <= idx < len(devices) else None

# ── CIP 0xF5 讀寫 ─────────────────────────────────────────

def _read_attr(driver, attr):
    for connected in (False, True):
        resp = driver.generic_message(
            service=SVC_GET, class_code=CLASS_TCPIP, instance=INST,
            attribute=attr, connected=connected, unconnected_send=not connected)
        if resp and not (hasattr(resp, 'error') and resp.error):
            return resp
    return None


def read_config(driver):
    print("\n── 讀取設備網路設定 ─────────────────────────────────")
    resp = _read_attr(driver, ATTR_CTRL)
    if resp and resp.value is not None:
        raw = bytes(resp.value)
        if len(raw) >= 4:
            ctrl = struct.unpack('<I', raw[:4])[0]
            print(f"  IP 取得方式 (Attr3): {CTRL_NAMES.get(ctrl, f'未知 0x{ctrl:02X}')}  [{ctrl}]")
    else:
        print("  Attr3 讀取失敗")
    resp = _read_attr(driver, ATTR_IFACE)
    if resp and resp.value is not None:
        raw = bytes(resp.value)
        if len(raw) >= 12:
            print(f"  IP 位址          : {_le2ip(raw, 0)}")
            print(f"  子網路遮罩       : {_le2ip(raw, 4)}")
            gw = _le2ip(raw, 8)
            print(f"  預設閘道         : {gw if gw != '0.0.0.0' else '（未設定）'}")
    else:
        print("  Attr5 讀取失敗")
    print("─" * 52)


def set_static_ip(driver, backend: CaparocBackend):
    print("\n── 設定靜態 IP ──────────────────────────────────────")
    resp = _read_attr(driver, ATTR_IFACE)
    cur_subnet = "255.255.255.0"
    if resp and resp.value is not None:
        raw = bytes(resp.value)
        if len(raw) >= 8:
            cur_subnet = _le2ip(raw, 4)

    new_ip = input("  新 IP 位址（cancel 取消）: ").strip()
    if new_ip.lower() == "cancel":
        return
    subnet = input(f"  子網路遮罩 [Enter={cur_subnet}]: ").strip() or cur_subnet
    gateway = input("  預設閘道   [Enter=0.0.0.0]: ").strip()

    print(f"\n  IP={new_ip}  Subnet={subnet}  GW={gateway or '0.0.0.0'}")
    if input("  確認送出？ [Y/N]: ").strip().upper() != 'Y':
        print("  已取消")
        return

    result = backend.set_device_ip(driver, new_ip, subnet, gateway)
    if result['success']:
        print("  ✅ 指令送出完成！")
        print(f"  ⏳ 等待設備套用...")
        for i in range(10, 0, -1):
            print(f"  {i}s...", end='\r')
            time.sleep(1)
        print()
        try:
            with socket.create_connection((new_ip, 44818), timeout=3):
                print(f"  ✅ 驗證成功：設備已在 {new_ip}")
        except OSError:
            print(f"  ⚠️  請稍後重試：python src/caparoc_ip_config.py {new_ip}")
    else:
        print(f"  ❌ 寫入失敗: {result['error']}")


def set_dhcp(driver, backend: CaparocBackend):
    print("\n── 切換為 DHCP 模式 ─────────────────────────────────")
    print("  ⚠️  切換後設備 IP 將由 DHCP server 重新分配，連線會中斷。")
    if input("  確認切換為 DHCP？ [Y/N]: ").strip().upper() != 'Y':
        print("  已取消")
        return
    result = backend.set_device_dhcp(driver)
    if result['success']:
        print("  ✅ 完成！請執行 arp -a 確認設備新 IP")
    else:
        print(f"  ❌ 寫入失敗: {result['error']}")

# ── 新裝置初始設定（DHCP 取得 IP → 設定為靜態 IP）───────────

def _check_scapy() -> bool:
    """確認 scapy 可用（網卡選擇 / 自動 MAC 偵測需要）"""
    try:
        import scapy.all  # noqa: F401
        return True
    except ImportError:
        return False


def _pick_iface() -> str | None:
    """列出非 Loopback 網卡（含 MAC/IP），讓使用者選擇連接設備的實體介面"""
    from scapy.all import get_if_list, get_if_addr, get_if_hwaddr
    ifaces = get_if_list()
    print("\n  可用網卡（選連接設備的實體乙太網卡）：")
    print(f"  {'#':>2}  {'IP 位址':<18}  {'MAC 位址':<20}  介面名稱")
    print("  " + "-" * 70)
    valid = []
    for name in ifaces:
        if 'loopback' in name.lower():
            continue
        try:
            ip = get_if_addr(name)
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


def _listen_dhcp_discover(iface: str, timeout: float = 30.0) -> str | None:
    """
    監聽 DHCP Discover，從 CHADDR 欄位讀出設備 MAC。
    自動排除 PC 自身 MAC，回傳找到的設備 MAC 或 None。
    """
    from scapy.all import get_if_hwaddr

    # 統一格式（colons）排除 PC 自身的 DHCP Discover
    try:
        own_mac = get_if_hwaddr(iface).lower().replace('-', ':')
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
        print(f"  （PC 自身 MAC {own_mac} 已自動排除）")
        print(f"  （請重新插拔網路線，以快速搜尋設備MAC位址）")
        seen: dict[str, int] = {}  # mac → count
        deadline = time.time() + timeout
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
                if mac == '00:00:00:00:00:00' or mac == own_mac:
                    continue
                seen[mac] = seen.get(mac, 0) + 1
                if seen[mac] == 1:
                    print(f"  📡 發現 DHCP Discover from: {mac}")
        except KeyboardInterrupt:
            pass
        finally:
            s.close()

        if not seen:
            print("  ⚠️  UDP port 67 超時未找到外部設備，改用 Raw Socket 混雜模式...")
            # 不 return，繼續往下走 Method B

        else:
            macs = list(seen.keys())
            if len(macs) == 1:
                print(f"\n  ✅ 設備 MAC: {macs[0]}")
                return macs[0]
            print(f"\n  發現 {len(macs)} 個設備：")
            for i, m in enumerate(macs, 1):
                print(f"    [{i}] {m}  （Discover × {seen[m]}）")
            choice = input("  選擇設備編號: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(macs):
                return macs[int(choice) - 1]
            return None

    except (PermissionError, OSError):
        print("  ⚠️  port 67 無法綁定，改用 Raw Socket 混雜模式監聽...")

    # ── 方法 B: Windows Raw Socket + SIO_RCVALL（混雜模式，同 Wireshark 原理）──
    import socket as _sock
    DHCP_MAGIC = b'\x63\x82\x53\x63'
    found_raw = []
    try:
        rs = _sock.socket(_sock.AF_INET, _sock.SOCK_RAW, _sock.IPPROTO_IP)
        rs.setsockopt(_sock.IPPROTO_IP, _sock.IP_HDRINCL, 1)
        rs.settimeout(1.0)
        # 取得網卡 IP
        from scapy.all import get_if_addr
        bind_ip = get_if_addr(iface) or '0.0.0.0'
        rs.bind((bind_ip, 0))
        # 開啟混雜模式 - 接收所有進入此 NIC 的封包
        rs.ioctl(_sock.SIO_RCVALL, _sock.RCVALL_ON)
        print(f"  Raw Socket 混雜模式（{bind_ip}），等待 DHCP Discover...")
        deadline = time.time() + timeout
        try:
            while time.time() < deadline:
                try:
                    raw_pkt, _ = rs.recvfrom(65535)
                except _sock.timeout:
                    continue
                # IP header: 首 byte 低4位 = IHL（以 4 bytes 計）
                if len(raw_pkt) < 28:
                    continue
                ihl = (raw_pkt[0] & 0x0F) * 4
                proto = raw_pkt[9]
                if proto != 17:  # UDP only
                    continue
                udp_start = ihl
                if len(raw_pkt) < udp_start + 8:
                    continue
                dst_port = int.from_bytes(raw_pkt[udp_start + 2:udp_start + 4], 'big')
                if dst_port != 67:
                    continue
                payload = raw_pkt[udp_start + 8:]
                if len(payload) < 240 or payload[0] != 1:
                    continue
                if payload[236:240] != DHCP_MAGIC:
                    continue
                chaddr = payload[28:34]
                mac = ':'.join(f'{b:02x}' for b in chaddr)
                if mac in (own_mac, '00:00:00:00:00:00') or mac in found_raw:
                    continue
                found_raw.append(mac)
                print(f"\n  ✅ 發現設備 MAC（Raw Socket）: {mac}")
        except KeyboardInterrupt:
            pass
        finally:
            try:
                rs.ioctl(_sock.SIO_RCVALL, _sock.RCVALL_OFF)
            except Exception:
                pass
            rs.close()
        if found_raw:
            return found_raw[0]
    except Exception as e:
        print(f"  ⚠️  Raw Socket 失敗: {e}，改用 scapy...")

    # ── 方法 C: scapy sniff with BPF filter ──
    from scapy.all import sniff
    found = []
    print(f"  等待 DHCP Discover（scapy，{int(timeout)} 秒）...")

    def handle(pkt):
        src_mac = pkt.src.lower() if hasattr(pkt, 'src') else ''
        if not src_mac or src_mac in (own_mac, 'ff:ff:ff:ff:ff:ff') or src_mac in found:
            return
        raw = bytes(pkt)
        idx = raw.find(DHCP_MAGIC)
        if idx < 0:
            return
        opts = raw[idx + 4:]
        i = 0
        while i < len(opts) - 2:
            if opts[i] == 255:
                break
            if opts[i] == 0:
                i += 1
                continue
            olen = opts[i + 1]
            if opts[i] == 53 and olen >= 1:
                if opts[i + 2] == 1:
                    found.append(src_mac)
                    print(f"\n  ✅ 發現設備 MAC: {src_mac}")
                return
            i += 2 + olen

    try:
        sniff(iface=iface, timeout=timeout, prn=handle,
              filter="udp dst port 67")
    except KeyboardInterrupt:
        pass

    return found[0] if found else None


def _check_port_67() -> bool:
    test = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        test.bind(('', 67))
        return True
    except OSError:
        try:
            r = subprocess.run(
                ['powershell', '-c',
                 'Get-NetUDPEndpoint -LocalPort 67 | ForEach-Object {'
                 ' $p = Get-Process -Id $_.OwningProcess -EA SilentlyContinue;'
                 ' "$($p.Name) (PID $($_.OwningProcess))" }'],
                capture_output=True, text=True, timeout=5)
            if r.stdout.strip():
                print(f"  ❌ port 67 被占用：{r.stdout.strip()}")
                print("     請先關閉該程式（例如 BootP-DHCP Tool）")
        except Exception:
            print("  ❌ port 67 被占用")
        return False
    finally:
        test.close()


def _build_dhcp_reply(xid: bytes, chaddr: bytes, offered_ip: str,
                       server_ip: str, subnet: str, msg_type: int,
                       client_flags: bytes = b'\x80\x00') -> bytes:
    pkt = bytes([2, 1, 6, 0]) + xid + b'\x00\x00' + client_flags
    pkt += b'\x00' * 4                    # ciaddr
    pkt += socket.inet_aton(offered_ip)   # yiaddr
    pkt += b'\x00' * 4                    # siaddr（用 Option 54 識別）
    pkt += b'\x00' * 4                    # giaddr
    pkt += chaddr + b'\x00' * 10          # chaddr 16 bytes
    pkt += b'\x00' * 64 + b'\x00' * 128  # sname + file
    pkt += b'\x63\x82\x53\x63'           # DHCP magic cookie
    pkt += bytes([53, 1, msg_type])
    pkt += bytes([54, 4]) + socket.inet_aton(server_ip)
    pkt += bytes([51, 4, 0, 1, 81, 128])  # lease 86400s
    pkt += bytes([1, 4]) + socket.inet_aton(subnet)
    pkt += bytes([3, 4]) + socket.inet_aton(server_ip)  # router（必要）
    pkt += b'\xff'
    if len(pkt) < 300:
        pkt += b'\x00' * (300 - len(pkt))
    return pkt


def _mini_dhcp_server(server_ip: str, target_mac: str,
                       assign_ip: str, subnet: str = "255.255.255.0") -> bool:
    """持續監聽 port 67，分配 assign_ip 給指定 MAC，Ctrl+C 可中斷"""
    target_bytes = bytes(int(x, 16) for x in target_mac.replace('-', ':').split(':'))
    subnet_broadcast = '.'.join(server_ip.split('.')[:3]) + '.255'
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1.0)
    sock.bind((server_ip, 67))
    offered = False
    last_status = time.time()
    try:
        while True:
            if time.time() - last_status >= 10:
                last_status = time.time()
                print(f"  ⏳ 等待 DHCP Discover...", end='\r')
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
            client_flags = data[10:12]
            msg_type, i = None, 240
            while i < len(data) - 1:
                opt = data[i]
                if opt == 255: break
                if opt == 0: i += 1; continue
                length = data[i + 1]
                if opt == 53 and length >= 1:
                    msg_type = data[i + 2]
                i += 2 + length
            if msg_type == 1:
                reply = _build_dhcp_reply(xid, chaddr, assign_ip, server_ip, subnet, 2, client_flags)
                sock.sendto(reply, (subnet_broadcast, 68))
                print(f"\n  📤 DHCP Offer → {assign_ip}")
                offered = True
            elif msg_type == 3:
                reply = _build_dhcp_reply(xid, chaddr, assign_ip, server_ip, subnet, 5, client_flags)
                sock.sendto(reply, (subnet_broadcast, 68))
                print(f"  ✅ DHCP ACK → 設備已取得 {assign_ip}")
                return True
    finally:
        sock.close()
    return False


def _provision_new_device():
    """新裝置初始設定：mini DHCP server 分配 IP → CIP 設定為靜態 IP"""
    print("\n── 新裝置初始設定（DHCP 取得 IP → 設定為靜態 IP）───────")
    print("  前提：其他 DHCP/BOOTP 工具（如 BootP-DHCP Tool）已關閉\n")

    if not _check_port_67():
        return

    if not _check_scapy():
        print("  ❌ 缺少 scapy，無法選擇網卡 / 自動偵測設備 MAC")
        print("     請執行：pip install scapy")
        return

    iface = _pick_iface()
    if not iface:
        print("  ❌ 無法選擇網卡")
        return

    from scapy.all import get_if_addr
    server_ip = get_if_addr(iface)
    if not server_ip or server_ip in ('0.0.0.0', ''):
        print("  ❌ 此網卡無 IP，請確認 PC 在正確網段（例如 192.168.50.x）")
        return
    print(f"  DHCP server IP（此網卡）: {server_ip}")

    sub = input("\n  設備 MAC：[1] 監聽 DHCP Discover 自動偵測（30秒） [2] 手動輸入: ").strip()
    if sub == '2':
        target_mac = input("    MAC（格式 cc:cc:ea:9f:c9:72）: ").strip().lower()
    else:
        print("    等待設備 DHCP Discover（30秒），請確認設備已接上網路...")
        target_mac = _listen_dhcp_discover(iface, timeout=30.0)
        if not target_mac:
            target_mac = input("    未偵測到，手動輸入 MAC（留空取消）: ").strip().lower()
    if not target_mac:
        return

    assign_ip = input("\n  目標靜態 IP（e.g. 192.168.50.XXX）: ").strip()
    if not assign_ip:
        return
    subnet = input("  子網路遮罩 [Enter=255.255.255.0]: ").strip() or "255.255.255.0"
    gateway = input("  預設閘道   [Enter=0.0.0.0 不設定]: ").strip()

    print(f"\n  MAC    : {target_mac}")
    print(f"  目標 IP: {assign_ip}")
    if input("  確認啟動 mini DHCP server？ [Y/N]: ").strip().upper() != 'Y':
        return

    print(f"\n  mini DHCP server 已啟動（按 Ctrl+C 中斷）")
    print(f"  ⚡ 請重插設備網路線！")
    print(f"     或在另一個視窗執行: python src/caparoc_ip_config.py <目前IP> → [3] 切 DHCP")

    try:
        got = _mini_dhcp_server(server_ip, target_mac, assign_ip, subnet)
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

    # CIP 設定靜態 IP：寫入 Attr5（assign_ip/subnet/gateway）+ Attr3（Static）
    # 若只寫 Attr3 而不寫 Attr5，設備設定後可能沿用舊的/預設的 Attr5 值，
    # 而不是 mini DHCP server 剛才分配的目標 IP。
    backend = CaparocBackend(assign_ip)
    print(f"  連接 {assign_ip}，設定靜態 IP...")
    try:
        with CIPDriver(assign_ip) as driver:
            result = backend.set_device_ip(driver, assign_ip, subnet, gateway)
            if result['success']:
                print(f"  ✅ 設備靜態 IP 設定完成：{assign_ip}")
            else:
                print(f"  ❌ 設定失敗: {result['error']}")
    except Exception as e:
        print(f"  ⚠️  CIP 連線失敗: {e}（設備可能仍需幾秒才上線，請稍後重試）")
        print(f"     python src/caparoc_ip_config.py {assign_ip}")

# ── 主程式 ─────────────────────────────────────────────────

def _run_connected_menu(device_ip: str):
    """連線到已知 IP 的設備，提供讀取／設定靜態 IP／切換 DHCP 選單"""
    print(f"\n{'='*55}")
    print(f"  CAPAROC IP 設定工具  →  {device_ip}")
    print(f"{'='*55}")

    backend = CaparocBackend(device_ip)

    try:
        with CIPDriver(device_ip) as driver:
            while True:
                print(f"\n  連線 IP: {device_ip}")
                print("  [1] 讀取目前網路設定")
                print("  [2] 設定靜態 IP")
                print("  [3] 切換為 DHCP 模式")
                print("  [0] 離開")
                choice = input("\n  請選擇: ").strip()

                if choice == '0':
                    break
                elif choice == '1':
                    read_config(driver)
                elif choice == '2':
                    set_static_ip(driver, backend)
                    break
                elif choice == '3':
                    set_dhcp(driver, backend)
                    break
                else:
                    print("  ⚠️  請輸入 0~3")

    except Exception as e:
        print(f"\n❌ 連線失敗: {e}")
        print(f"   請確認設備 IP ({device_ip}) 是否正確")


def main():
    # 已知 IP：略過主選單，直接進入連線設定選單（維持既有用法）
    if len(sys.argv) > 1:
        _run_connected_menu(sys.argv[1])
        return

    print(f"\n{'='*55}")
    print(f"  CAPAROC IP 設定工具")
    print(f"{'='*55}")
    print("\n  [1] 連線設備（自動探索 / 讀取 / 設定靜態 IP / 切換 DHCP）")
    print("  [2] 新裝置初始設定（DHCP 取得 IP → 設定為靜態 IP）")
    print("  [0] 離開")
    choice = input("\n  請選擇: ").strip()

    if choice == '0':
        return
    if choice == '2':
        _provision_new_device()
        return

    device_ip = run_discovery()
    if device_ip is None:
        return
    _run_connected_menu(device_ip)


if __name__ == "__main__":
    main()
