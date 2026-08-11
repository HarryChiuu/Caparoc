#!/usr/bin/env python3
"""
CAPAROC IP 設定工具

功能：
  [1] 讀取目前設備網路設定
  [2] 設定靜態 IP
  [3] 切換為 DHCP 模式
  [4] 從 DHCP 模式配置靜態 IP（新裝置初始設定）
  [0] 離開

用法：
  python src/caparoc_ip_config.py               # 自動探索設備
  python src/caparoc_ip_config.py 192.168.50.221  # 直連指定 IP
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
        print(f"  ⏳ 等待設備套用（10 秒）...")
        time.sleep(10)
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

# ── [4] 從 DHCP 模式配置靜態 IP（新裝置初始設定）───────────

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
    """[4] 從 DHCP 模式配置靜態 IP（新裝置初始設定）"""
    print("\n── 從 DHCP 模式配置靜態 IP（新裝置初始設定）───────────")
    print("  前提：PC 在 192.168.50.x 網段，BootP-DHCP Tool 已關閉\n")

    if not _check_port_67():
        return

    # 取得 PC IP 作為 DHCP server IP
    try:
        server_ip = socket.gethostbyname(socket.gethostname())
        if server_ip.startswith('127.') or server_ip.startswith('169.'):
            raise ValueError
    except Exception:
        server_ip = input("  PC IP（作為 DHCP server IP，e.g. 192.168.50.200）: ").strip()

    print(f"  DHCP server IP: {server_ip}")

    target_mac = input("\n  設備 MAC（格式 cc:cc:ea:9f:c9:72）: ").strip().lower()
    if not target_mac:
        return

    assign_ip = input("  目標靜態 IP（e.g. 192.168.50.221）: ").strip()
    if not assign_ip:
        return
    subnet = input("  子網路遮罩 [Enter=255.255.255.0]: ").strip() or "255.255.255.0"

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

    # CIP 固化靜態 IP
    backend = CaparocBackend(assign_ip)
    try:
        with CIPDriver(assign_ip) as driver:
            static_data = struct.pack('<I', 0)
            try:
                driver.generic_message(
                    service=SVC_SET, class_code=CLASS_TCPIP, instance=INST,
                    attribute=ATTR_CTRL, request_data=static_data, connected=True)
            except Exception:
                pass  # 連線因 IP 已改變而中斷，屬預期行為
            print(f"  ✅ 設備靜態 IP 配置完成：{assign_ip}")
    except Exception as e:
        print(f"  ⚠️  CIP 固化失敗: {e}（設備可能仍需幾秒才上線，請稍後重試）")

# ── 主程式 ─────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1:
        device_ip = sys.argv[1]
    else:
        device_ip = run_discovery()
        if device_ip is None:
            # [4] 不需要已知 IP，直接進入
            ans = input("\n  沒有找到設備。是否進行新裝置初始設定 [4]？ [Y/N]: ").strip().upper()
            if ans == 'Y':
                _provision_new_device()
            return

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
                print("  [4] 從 DHCP 模式配置靜態 IP（新裝置初始設定）")
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
                elif choice == '4':
                    _provision_new_device()
                else:
                    print("  ⚠️  請輸入 0~4")

    except Exception as e:
        print(f"\n❌ 連線失敗: {e}")
        print(f"   請確認設備 IP ({device_ip}) 是否正確")


if __name__ == "__main__":
    main()
