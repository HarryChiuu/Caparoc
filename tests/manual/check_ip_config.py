#!/usr/bin/env python3
"""
IP 設定功能測試工具

測試 CIP Class 0xF5 (TCP/IP Interface Object) 的讀取與寫入：
  [1] 讀取目前設備網路設定
  [2] 設定靜態 IP（Set Attribute Single: Attr3=Static + Attr5=IP config）
  [3] 切換為 DHCP 模式（Set Attribute Single: Attr3=DHCP）
  [0] 離開

用法：
  python tests/manual/check_ip_config.py [設備IP]
  python tests/manual/check_ip_config.py 192.168.50.221
"""
import sys
import struct
import socket
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from pycomm3 import CIPDriver
from caparoc_backend import CaparocBackend

# ── 預設目標 IP ──────────────────────────────────────────────
DEFAULT_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.221"

# ── CIP 0xF5 常數 ────────────────────────────────────────────
CLASS_TCPIP = 0xF5
INST        = 1
SVC_GET     = 0x0E  # Get Attribute Single
SVC_SET     = 0x10  # Set Attribute Single
ATTR_STATUS = 1
ATTR_CTRL   = 3     # Configuration Control: 0=Static, 1=BOOTP, 2=DHCP
ATTR_IFACE  = 5     # Interface Configuration (IP/Subnet/Gateway/DNS)

CTRL_NAMES = {0: "Static IP", 1: "BOOTP", 2: "DHCP"}

# CIP 以 Little-Endian UDINT 儲存 IP，需反轉後才能用 inet_ntoa
_le2ip = lambda b, off: socket.inet_ntoa(b[off:off+4][::-1])
_ip2le = lambda ip: socket.inet_aton(ip)[::-1]


# ── EtherNet/IP List Identity 設備探索 ──────────────────────────────

def _parse_list_identity(data: bytes, src_ip: str) -> dict | None:
    """Parse a List Identity response, return device info dict or None"""
    try:
        if len(data) < 30:
            return None
        if struct.unpack_from('<H', data, 0)[0] != 0x0063:
            return None
        # header=24, item_count=2, type_id=2, item_len=2, proto_ver=2 = offset 32
        # socket_addr: sin_family(2)+sin_port(2)+sin_addr(4)+zero(8) = 16 bytes
        off = 32
        if off + 16 > len(data):
            return None
        ip = socket.inet_ntoa(data[off+4:off+8])  # socket struct uses BE
        off += 16
        if off + 12 > len(data):
            return None
        vendor_id   = struct.unpack_from('<H', data, off)[0];  off += 2
        device_type = struct.unpack_from('<H', data, off)[0];  off += 2
        product_code= struct.unpack_from('<H', data, off)[0];  off += 2
        rev_major   = data[off]; rev_minor = data[off+1];      off += 2
        off += 2  # status
        serial      = struct.unpack_from('<I', data, off)[0];  off += 4
        name_len    = data[off];                               off += 1
        name = data[off:off+name_len].decode('ascii', errors='replace')
        return {
            'ip': ip, 'src_ip': src_ip,
            'vendor_id': vendor_id, 'name': name,
            'revision': f"{rev_major}.{rev_minor}",
            'serial': f"{serial:08X}",
        }
    except Exception:
        return None


def _get_broadcast_addresses() -> list[str]:
    """取得所有本機網路介面的廣播位址，包含 APIPA (169.254.x.x/16)"""
    broadcasts = {'255.255.255.255'}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith('127.'):
                continue
            parts = ip.split('.')
            # APIPA 是 /16；一般辦公室網路假設 /24
            if ip.startswith('169.254.'):
                broadcasts.add('169.254.255.255')
            else:
                broadcasts.add('.'.join(parts[:3]) + '.255')
    except Exception:
        pass
    return list(broadcasts)


def discover_devices(timeout: float = 2.0) -> list[dict]:
    """
    廣播 EtherNet/IP List Identity (UDP 44818)，回傳網路上所有回應的設備。
    不需知道設備 IP，不需管理員權限。
    """
    EIP_PORT = 44818
    # 24-byte ENIP encapsulation header，無資料段
    pkt = (
        struct.pack('<H', 0x0063) +  # Command: List Identity
        struct.pack('<H', 0x0000) +  # Length
        struct.pack('<I', 0) +       # Session Handle
        struct.pack('<I', 0) +       # Status
        b'\x00' * 8 +               # Sender Context
        struct.pack('<I', 0)         # Options
    )
    devices = []
    seen_ips = set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    broadcasts = _get_broadcast_addresses()
    try:
        for bcast in broadcasts:
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


def _eip_port_open(ip: str, timeout: float = 0.5) -> bool:
    """TCP 連線測試：確認 IP 上的 EtherNet/IP port 44818 是否有回應"""
    try:
        with socket.create_connection((ip, 44818), timeout=timeout):
            return True
    except OSError:
        return False


def discover_by_arp() -> list[dict]:
    """
    從 Windows ARP table 掃出同網段設備，逐一測試 port 44818，
    回傳可連線的設備清單。
    """
    import subprocess
    result = subprocess.run(['arp', '-a'], capture_output=True, text=True)

    # 依 MAC 分組，避免同一設備多個快取 IP 重複顯示
    mac_to_ips: dict[str, list[str]] = {}
    current_iface = None
    for line in result.stdout.splitlines():
        if '介面' in line or 'Interface' in line:
            current_iface = line
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[2] in ('動態', 'dynamic'):
            ip, mac = parts[0], parts[1]
            mac_to_ips.setdefault(mac, []).append(ip)

    devices = []
    for mac, ips in mac_to_ips.items():
        # 測試哪個 IP 目前 active
        active = [ip for ip in ips if _eip_port_open(ip)]
        for ip in active:
            devices.append({'ip': ip, 'mac': mac, 'name': f'MAC {mac}', 'via': 'ARP'})

    return devices


def run_discovery() -> str | None:
    """列印探索結果，讓使用者選擇設備。回傳選定的 IP，或 None 表示取消。"""
    broadcasts = _get_broadcast_addresses()
    print(f"\n正在探索 EtherNet/IP 設備（廣播目標：{', '.join(broadcasts)}，等待 2s）...")
    devices = discover_devices(timeout=2.0)

    if not devices:
        print("  List Identity 廣播無回應，改用 ARP table 掃描...")
        devices = discover_by_arp()

    if not devices:
        print("  ❕ 未發現任何設備，請確認：")
        print("     1. 設備已開機且連接同一網路")
        print("     2. 若設備為 DHCP 模式，請確認 DHCP server 已分配 IP")
        print("     3. 可手動指定 IP：python tests/manual/check_ip_config.py <IP>")
        return None

    print(f"\n  發現 {len(devices)} 台設備：")
    print(f"  {'#':>2}  {'IP 位址':<18}  {'MAC / 產品名稱'}")
    print("  " + "-"*55)
    for i, d in enumerate(devices, 1):
        via = f"  [{d.get('via','EIP')}]" if d.get('via') else ''
        extra = d.get('serial', '')
        extra_str = f"  S/N: {extra}" if extra else ''
        print(f"  {i:>2}  {d['ip']:<18}  {d['name']}{extra_str}{via}")
    print()

    if len(devices) == 1:
        ans = input(f"  選擇設備 [Enter=選第1台 / 0=离開]: ").strip()
        if ans == '0':
            return None
        return devices[0]['ip']

    ans = input(f"  選擇編號 [1-{len(devices)} / 0=离開]: ").strip()
    if ans == '0' or not ans.isdigit():
        return None
    idx = int(ans) - 1
    if 0 <= idx < len(devices):
        return devices[idx]['ip']
    return None


def _read_attr(driver, attr):
    """嘗試 unconnected 再 connected，回傳第一個成功的結果"""
    for connected in (False, True):
        resp = driver.generic_message(
            service=SVC_GET, class_code=CLASS_TCPIP, instance=INST,
            attribute=attr, connected=connected,
            unconnected_send=not connected,
        )
        if resp and not (hasattr(resp, 'error') and resp.error):
            return resp
        mode = "unconnected" if not connected else "connected"
        err = getattr(resp, 'error', '(no resp)') if resp else '(no resp)'
        print(f"  [debug] Attr{attr} {mode} failed: {err}")
    return None


def _write_attr(driver, attr, data: bytes):
    return driver.generic_message(
        service=SVC_SET, class_code=CLASS_TCPIP, instance=INST,
        attribute=attr, request_data=data, connected=False,
        unconnected_send=True,
    )


def read_config(driver):
    """讀取並列印目前設備網路設定"""
    print("\n── 讀取設備網路設定 ───────────────────────────────")

    # Attr 3: Configuration Control
    resp = _read_attr(driver, ATTR_CTRL)
    if resp and resp.value is not None:
        raw = bytes(resp.value)
        if len(raw) >= 4:
            ctrl = struct.unpack('<I', raw[:4])[0]
            print(f"  IP 取得方式 (Attr3): {CTRL_NAMES.get(ctrl, f'未知 0x{ctrl:02X}')}  [{ctrl}]")
            print(f"  raw bytes         : {raw[:4].hex()}")
        else:
            print(f"  Attr3 資料長度不足: {raw.hex()}")
    else:
        print("  Attr3 讀取失敗")

    # Attr 5: Interface Configuration
    resp = _read_attr(driver, ATTR_IFACE)
    if resp and resp.value is not None:
        raw = bytes(resp.value)
        if len(raw) >= 12:
            ip      = _le2ip(raw, 0)
            subnet  = _le2ip(raw, 4)
            gw      = _le2ip(raw, 8)
            dns1    = _le2ip(raw, 12) if len(raw) >= 16 else "—"
            dns2    = _le2ip(raw, 16) if len(raw) >= 20 else "—"
            print(f"  IP 位址   (Attr5) : {ip}")
            print(f"  子網路遮罩        : {subnet}")
            print(f"  預設閘道          : {gw if gw != '0.0.0.0' else '（未設定）'}")
            print(f"  DNS1              : {dns1}")
            print(f"  DNS2              : {dns2}")
            print(f"  raw bytes         : {raw[:20].hex()}")
        else:
            print(f"  Attr5 資料長度不足: {raw.hex()}")
    else:
        print("  Attr5 讀取失敗")

    print("─" * 52)


def set_static_ip(driver, backend: CaparocBackend):
    """互動式設定靜態 IP"""
    print("\n── 設定靜態 IP ────────────────────────────────────")

    # 先讀目前設定作為預設值
    resp = _read_attr(driver, ATTR_IFACE)
    cur_subnet = "255.255.255.0"
    if resp and resp.value is not None:
        raw = bytes(resp.value)
        if len(raw) >= 8:
            cur_subnet = _le2ip(raw, 4)

    new_ip = input("  新 IP 位址（cancel 取消）: ").strip()
    if new_ip.lower() == "cancel":
        return

    subnet_in = input(f"  子網路遮罩 [Enter={cur_subnet}]: ").strip()
    subnet = subnet_in if subnet_in else cur_subnet

    gw_in = input("  預設閘道   [Enter=0.0.0.0 不設定]: ").strip()
    gateway = gw_in if gw_in else ""

    gw_display = gateway if gateway else "0.0.0.0（不設定）"
    print(f"\n  即將寫入：IP={new_ip}  Subnet={subnet}  GW={gw_display}")

    # 顯示將要送出的 raw bytes（方便對照 Wireshark）
    gw_addr = gateway if gateway else "0.0.0.0"
    attr3_bytes = struct.pack('<I', 0)
    attr5_bytes = (
        _ip2le(new_ip) +
        _ip2le(subnet) +
        _ip2le(gw_addr) +
        bytes(4) +            # DNS1
        bytes(4) +            # DNS2
        struct.pack('<H', 0)  # DomainName SSTRING len=0
    )
    print(f"\n  [Wireshark 對照]")
    print(f"  Attr3 write data : {attr3_bytes.hex()}  (Static=0x00000000)")
    print(f"  Attr5 write data : {attr5_bytes.hex()}")

    confirm = input("\n  確認送出？ [Y/N]: ").strip().upper()
    if confirm != 'Y':
        print("  已取消")
        return

    result = backend.set_device_ip(driver, new_ip, subnet, gateway)
    if result['success']:
        print(f"  ✅ 指令送出完成！")
        print(f"  ⏳ 等待設備套用設定（15 秒）...")
        import time as _t
        _t.sleep(10)
        try:
            with socket.create_connection((new_ip, 44818), timeout=3):
                print(f"  ✅ 驗證成功：設備已在 {new_ip}")
                print(f"     python tests/manual/check_ip_config.py {new_ip}")
        except OSError:
            print(f"  ⚠️  10 秒後仍無法連線，請稍後再試")
            print(f"     python tests/manual/check_ip_config.py {new_ip}")
    else:
        print(f"  ❌ 寫入失敗: {result['error']}")


def set_dhcp(driver, backend: CaparocBackend):
    """切換設備為 DHCP 模式"""
    print("\n── 切換為 DHCP 模式 ────────────────────────────────")

    attr3_bytes = struct.pack('<I', 2)
    print(f"  [Wireshark 對照]")
    print(f"  Attr3 write data : {attr3_bytes.hex()}  (DHCP=0x00000002)")
    print("  ⚠️  切換後設備 IP 將由 DHCP server 重新分配，連線會中斷。")

    confirm = input("\n  確認切換為 DHCP？ [Y/N]: ").strip().upper()
    if confirm != 'Y':
        print("  已取消")
        return

    result = backend.set_device_dhcp(driver)
    if result['success']:
        print("  ✅ 指令送出完成！")
        print("  ⏳ 等待設備切換 DHCP（10 秒）...")
        import time as _t
        _t.sleep(10)
        print("  ✅ 完成！請執行 arp -a 確認設備新 IP")
    else:
        print(f"  ❌ 寫入失敗: {result['error']}")


# ── 主程式 ──────────────────────────────────────────────────
def main():
    # 沒有給定 IP 時，自動廣播探索
    if len(sys.argv) > 1:
        device_ip = sys.argv[1]
    else:
        device_ip = run_discovery()
        if device_ip is None:
            return

    print(f"\n{'='*55}")
    print(f"  IP 設定功能測試  →  {device_ip}")
    print(f"  CIP Class 0xF5 (TCP/IP Interface Object)")
    print(f"{'='*55}")

    backend = CaparocBackend(device_ip)

    try:
        with CIPDriver(device_ip) as driver:
            while True:
                print("\n  [1] 讀取目前網路設定")
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
                    break  # 設定後 IP 變更，連線失效，直接結束
                elif choice == '3':
                    set_dhcp(driver, backend)
                    break  # 設定後 IP 變更，連線失效，直接結束
                else:
                    print("  ⚠️  請輸入 0~3")

    except Exception as e:
        print(f"\n❌ 連線失敗: {e}")
        print(f"   請確認設備 IP ({device_ip}) 是否正確，以及網路連線是否正常。")


if __name__ == "__main__":
    main()
