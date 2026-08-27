#!/usr/bin/env python3
"""
CAPAROC IP 設定核心層（不含任何互動 I/O）

本模組只放**不呼叫 input()、不 print()** 的純邏輯，讓 CLI 與 web 共用同一份實作：

  - `src/caparoc_ip_config.py` — 互動式 CLI，負責選單、提示與畫面輸出
  - `web/app.py`               — FastAPI 路由，負責 HTTP 介面

⚠️ 維護守則：
  1. 本檔**不得** import `caparoc_backend`（那會連帶觸發 logging_manager.setup()）。
  2. 本檔**不得**出現 `input()` / `print()`。需要回報進度時一律用 callback 參數。
  只要守住這兩條，探索邏輯就能維持單一事實來源，不會 CLI 與 web 各長一份。
"""

import socket
import struct
import subprocess
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor

# ── CIP 0xF5（TCP/IP Interface Object）常數 ──────────────────
CLASS_TCPIP = 0xF5
INST        = 1
SVC_GET     = 0x0E
SVC_SET     = 0x10
ATTR_CTRL   = 3   # Configuration Control: 0=Static, 1=BOOTP, 2=DHCP
ATTR_IFACE  = 5   # Interface Configuration (IP/Subnet/Gateway/DNS)

CTRL_NAMES = {0: "Static IP", 1: "BOOTP", 2: "DHCP"}

# ── 網路常數 ─────────────────────────────────────────────────
EIP_PORT = 44818   # EtherNet/IP 明文 TCP/UDP 埠

# 等待／逾時（秒）
DEVICE_ONLINE_MAX_WAIT = 30.0   # 寫入 IP 後等設備重新上線的上限

# CIP 以 Little-Endian UDINT 儲存 IP，取出時需反轉 bytes
_le2ip = lambda b, off: socket.inet_ntoa(b[off:off + 4][::-1])


# ── IP 格式與網段判斷 ────────────────────────────────────────

def is_valid_ip(ip: str) -> bool:
    """檢查是否為合法的 IPv4 位址（四段 0~255，格式如 192.168.50.10）"""
    try:
        ipaddress.IPv4Address(ip)
        return True
    except ValueError:
        return False


def same_subnet(ip: str, ref_ip: str, mask: str) -> bool:
    """ip 是否與 ref_ip 位於同一網段。遮罩無法解析時回傳 True（只警告不擋）"""
    try:
        net = ipaddress.IPv4Network(f"{ref_ip}/{mask}", strict=False)
        return ipaddress.IPv4Address(ip) in net
    except ValueError:
        return True


# ── 設備探索（EtherNet/IP List Identity + ARP fallback）──────

def parse_list_identity(data: bytes, src_ip: str) -> dict | None:
    """解析 List Identity 回應封包，回傳設備資訊 dict；格式不符時回傳 None"""
    try:
        if len(data) < 30 or struct.unpack_from('<H', data, 0)[0] != 0x0063:
            return None
        off = 32
        if off + 16 > len(data):
            return None
        ip = socket.inet_ntoa(data[off + 4:off + 8])
        off += 16
        if off + 12 > len(data):
            return None
        vendor_id = struct.unpack_from('<H', data, off)[0]; off += 2
        off += 4  # device_type, product_code
        rev_major = data[off]; rev_minor = data[off + 1]; off += 2
        off += 2  # status
        serial = struct.unpack_from('<I', data, off)[0]; off += 4
        name_len = data[off]; off += 1
        name = data[off:off + name_len].decode('ascii', errors='replace')
        return {'ip': ip, 'vendor_id': vendor_id, 'name': name,
                'revision': f"{rev_major}.{rev_minor}", 'serial': f"{serial:08X}"}
    except Exception:
        return None


def get_broadcast_addresses() -> list[str]:
    """推導本機所有網卡的廣播位址（含受限廣播 255.255.255.255）"""
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


def eip_port_open(ip: str, timeout: float = 0.5) -> bool:
    """探測指定 IP 的 EtherNet/IP TCP 埠是否可連線"""
    try:
        with socket.create_connection((ip, EIP_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_device(ip: str, max_wait: float = DEVICE_ONLINE_MAX_WAIT,
                    poll: float = 1.0, on_progress=None) -> bool:
    """
    輪詢 EtherNet/IP 埠直到設備上線或逾時。

    Args:
        on_progress: 可選 callback，簽名 `(remain_seconds: int) -> None`，
                     每輪呼叫一次供呼叫端顯示剩餘秒數（CLI 印進度、web 可忽略）。

    Returns:
        True  — 設備已上線
        False — 逾時仍未偵測到
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        remain = max(0, int(deadline - time.time()))
        if on_progress:
            on_progress(remain)
        if eip_port_open(ip, timeout=poll):
            return True
    return False


def probe_eip_hosts(ips: list[str], timeout: float = 0.5, workers: int = 32) -> set[str]:
    """並行探測多個 IP 的 EtherNet/IP TCP 埠，回傳有回應的 IP 集合"""
    if not ips:
        return set()
    with ThreadPoolExecutor(max_workers=min(workers, len(ips))) as ex:
        results = ex.map(lambda ip: eip_port_open(ip, timeout), ips)
    return {ip for ip, ok in zip(ips, results) if ok}


def discover_devices(timeout: float = 2.0) -> list[dict]:
    """以 EtherNet/IP List Identity UDP 廣播探索設備。無需管理員權限。"""
    pkt = (struct.pack('<H', 0x0063) + struct.pack('<H', 0) +
           struct.pack('<I', 0) + struct.pack('<I', 0) +
           b'\x00' * 8 + struct.pack('<I', 0))
    devices, seen_ips = [], set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    try:
        for bcast in get_broadcast_addresses():
            sock.sendto(pkt, (bcast, EIP_PORT))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(1024)
                if addr[0] not in seen_ips:
                    seen_ips.add(addr[0])
                    dev = parse_list_identity(data, addr[0])
                    if dev:
                        devices.append(dev)
            except socket.timeout:
                pass
    finally:
        sock.close()
    return devices


def discover_by_arp() -> list[dict]:
    """
    後援探索：讀取系統 ARP table 中的動態項目，再逐一探測 EtherNet/IP 埠。

    僅適用 Windows（依賴 arp.exe），且 `arp -a` 輸出的「動態/dynamic」欄位隨系統
    語系而異——非 zh-TW/英文語系下會找不到任何項目，屬已知限制。
    """
    try:
        result = subprocess.run(['arp', '-a'], capture_output=True, text=True)
    except (FileNotFoundError, OSError):
        return []   # 系統無 arp 指令（非 Windows）
    ordered_pairs: list[tuple[str, str]] = []  # (mac, ip)，保留 arp -a 原始順序
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] in ('動態', 'dynamic'):
            ordered_pairs.append((parts[1], parts[0]))
    reachable = probe_eip_hosts([ip for _, ip in ordered_pairs])
    return [{'ip': ip, 'mac': mac, 'name': f'MAC {mac}', 'via': 'ARP'}
            for mac, ip in ordered_pairs if ip in reachable]


def discover(timeout: float = 2.0, on_stage=None) -> dict:
    """
    完整探索流程：先 List Identity 廣播，無回應時退回 ARP table。

    CLI 與 web 共用此函式，確保兩邊的 fallback 行為永遠一致。

    Args:
        on_stage: 可選 callback，簽名 `(stage: str, info: dict) -> None`，
                  在每個階段**開始前**呼叫，供 CLI 即時印出進度
                  （ARP 掃描可能耗時數秒，不能等結束才提示）。
                  stage 取值：
                    'eip' — 即將送出 List Identity 廣播，info={'broadcasts': [...]}
                    'arp' — List Identity 無回應，即將改掃 ARP table，info={}

    Returns:
        dict: {
            'devices': list[dict],           # 設備清單（可能為空）
            'via': 'EIP' | 'ARP' | None,     # 實際命中的探索方式
            'broadcasts': list[str],         # 這次送出廣播的位址（供 UI 顯示）
        }
    """
    broadcasts = get_broadcast_addresses()
    if on_stage:
        on_stage('eip', {'broadcasts': broadcasts})
    devices = discover_devices(timeout=timeout)
    if devices:
        return {'devices': devices, 'via': 'EIP', 'broadcasts': broadcasts}

    if on_stage:
        on_stage('arp', {})
    devices = discover_by_arp()
    if devices:
        return {'devices': devices, 'via': 'ARP', 'broadcasts': broadcasts}

    return {'devices': [], 'via': None, 'broadcasts': broadcasts}
