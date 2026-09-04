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
import locale
import re
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

# ── DHCP 常數 ────────────────────────────────────────────────
DHCP_SERVER_PORT   = 67
DHCP_CLIENT_PORT   = 68
DHCP_MAGIC         = b'\x63\x82\x53\x63'
DHCP_LEASE_SECONDS = 86400
# RFC 2131：client 尚無 IP 且 broadcast flag 有設時，server 應以受限廣播
# 255.255.255.255 回覆 Offer/ACK，而非依網卡遮罩算出的子網路導向廣播 ——
# 後者在網卡實際廣播網域與設備回報的遮罩不一致時（例如網卡是 /24 但設備
# 回報 /23）會送不到設備，導致卡在 Discover→Offer 循環收不到 Request。
DHCP_LIMITED_BROADCAST = '255.255.255.255'

# DHCP 訊息型別（Option 53）
DHCP_DISCOVER, DHCP_OFFER, DHCP_REQUEST, DHCP_ACK = 1, 2, 3, 5

# 等待／逾時（秒）
DEVICE_ONLINE_MAX_WAIT = 30.0   # 寫入 IP 後等設備重新上線的上限
DHCP_SERVE_TIMEOUT     = 300.0  # mini DHCP server 自動結束時間

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


def _iface_netmasks() -> dict[str, str]:
    """
    向作業系統查詢 {ip: netmask}，供廣播位址計算使用。

    psutil 是**選配**依賴：查不到就回空 dict，呼叫端退回 /24 推測。
    刻意不把它列為必要依賴——它只影響非 /24 網段的探索完整度，
    而受限廣播 255.255.255.255 本來就是所有情況的保底。
    """
    try:
        import psutil
    except ImportError:
        return {}
    masks: dict[str, str] = {}
    try:
        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET and a.address and a.netmask:
                    masks[a.address] = a.netmask
    except Exception:
        pass
    return masks


def _broadcast_from_mask(ip: str, mask: str | None) -> str:
    """
    由 IP + 遮罩算出廣播位址；遮罩不明或無法解析時退回 /24 推測。

    /24 只是**推測**不是事實——非 /24 網段（如 /16、/22）算出來的位址會落在
    錯誤的子網而收不到回應。有真實遮罩時一律優先採用。
    """
    if ip.startswith('169.254.'):
        return '169.254.255.255'
    if mask:
        try:
            net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
            # /31、/32（VPN／點對點介面常見）沒有可用的廣播位址——
            # IPv4Network 會回傳網段本身或該主機 IP，往那裡送廣播毫無意義。
            if net.prefixlen < 31:
                return str(net.broadcast_address)
            return ''
        except ValueError:
            pass
    return '.'.join(ip.split('.')[:3]) + '.255'


def get_broadcast_addresses() -> list[str]:
    """
    推導本機所有網卡的廣播位址（含受限廣播 255.255.255.255）。

    有 psutil 時使用作業系統回報的真實遮罩，正確涵蓋非 /24 網段；
    沒有時退回 /24 推測（原行為）。
    """
    broadcasts = {'255.255.255.255'}
    masks = _iface_netmasks()

    # psutil 的清單比 getaddrinfo(gethostname()) 完整——後者在多網卡機器上
    # 常只回傳「主要」那張，其餘網段的設備因此掃不到。
    candidate_ips = set(masks)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidate_ips.add(info[4][0])
    except Exception:
        pass

    for ip in candidate_ips:
        if ip.startswith('127.') or ip == '0.0.0.0':
            continue
        bcast = _broadcast_from_mask(ip, masks.get(ip))
        if bcast:
            broadcasts.add(bcast)
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
    return {ip for ip, ok in zip(ips, results, strict=True) if ok}


def discover_devices(timeout: float = 2.0, broadcasts: list[str] | None = None,
                     bind_ip: str | None = None) -> list[dict]:
    """
    以 EtherNet/IP List Identity UDP 廣播探索設備。無需管理員權限。

    Args:
        broadcasts: 要送出廣播的位址清單；None = 本機全部網卡（get_broadcast_addresses()）。
        bind_ip:    把 socket 綁定到這張網卡的 IP。多網卡機器上**這是必要的**——
                    不綁定時 OS 會依路由表挑介面，導向廣播（例如 192.168.50.255）
                    很可能從錯的網卡送出去，設備收不到也就掃不到。
                    同一個教訓已記在 _open_dhcp_socket() 的註解裡。
    """
    pkt = (struct.pack('<H', 0x0063) + struct.pack('<H', 0) +
           struct.pack('<I', 0) + struct.pack('<I', 0) +
           b'\x00' * 8 + struct.pack('<I', 0))
    devices, seen_ips = [], set()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.3)
    if bind_ip:
        try:
            sock.bind((bind_ip, 0))
        except OSError:
            pass   # 綁不上就退回讓 OS 自行選擇，至少不要整個掃描失敗
    try:
        for bcast in (broadcasts if broadcasts else get_broadcast_addresses()):
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


_ARP_MAC_RE = re.compile(r'^(?:[0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}$')


def _is_static_arp_mac(mac: str) -> bool:
    """
    判斷是否為 `arp -a` 的「靜態」項目：廣播與多播位址。

    這些項目本來就不是實體設備，先前靠「動態/dynamic」文字排除，
    改以位址本身的結構判斷後就與系統語系無關了。
      * ff:ff:ff:ff:ff:ff        —— 廣播
      * 01:00:5e:xx:xx:xx        —— IPv4 多播
      * 33:33:xx:xx:xx:xx        —— IPv6 多播
    """
    m = normalize_mac(mac)
    return (m == 'ff:ff:ff:ff:ff:ff'
            or m.startswith('01:00:5e:')
            or m.startswith('33:33:'))


def arp_table() -> list[tuple[str, str]]:
    """
    讀取系統 ARP table 的實體項目，回傳 [(mac, ip), ...]，保留 `arp -a` 原始順序。

    僅適用 Windows（依賴 arp.exe）。

    ⚠️ 刻意**不比對「動態」/「dynamic」欄位**：該欄位是本地化文字，
    先前在非 zh-TW／英文語系下會一個項目都找不到（TODO 問題 #6）。
    改為以「這一行長得像 IP + MAC」判斷，並用 MAC 結構濾掉廣播/多播，
    行為與原本等價但不再依賴語系。

    另外用 errors='replace' 解碼：主控台代碼頁與 Python 預設編碼不一致時
    （zh-TW cp950 很常見），text=True 的預設解碼會直接拋 UnicodeDecodeError，
    讓整個 ARP 後援探索靜默失效。
    """
    try:
        result = subprocess.run(['arp', '-a'], capture_output=True)
    except (FileNotFoundError, OSError):
        return []   # 系統無 arp 指令（非 Windows）
    text = result.stdout.decode(locale.getpreferredencoding(False), errors='replace')
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split()
        # 標題列與「介面:」列的欄位排列不同，靠格式判斷自然被排除
        if len(parts) < 2:
            continue
        ip, mac = parts[0], parts[1]
        if not is_valid_ip(ip) or not _ARP_MAC_RE.match(mac):
            continue
        if _is_static_arp_mac(mac):
            continue
        pairs.append((mac, ip))
    return pairs


def arp_mac_map() -> dict[str, str]:
    """ARP table 的 {ip: mac} 對照表，供補齊 List Identity 查不到的 MAC。"""
    return {ip: mac for mac, ip in arp_table()}


def discover_by_arp() -> list[dict]:
    """後援探索：取 ARP table 動態項目，再逐一探測 EtherNet/IP 埠。"""
    ordered_pairs = arp_table()
    reachable = probe_eip_hosts([ip for _, ip in ordered_pairs])
    return [{'ip': ip, 'mac': mac, 'name': f'MAC {mac}', 'via': 'ARP'}
            for mac, ip in ordered_pairs if ip in reachable]


def list_interfaces() -> list[dict]:
    """
    列出本機可用網卡（供 UI 選擇要掃描哪個網段），對應 CLI 的 _pick_iface()。

    過濾掉 loopback、無 IP、以及 MAC 全為零的虛擬介面——與 _pick_iface() same 準則。

    Returns:
        list[dict]: [{'name','description','ip','mac','broadcast'}, ...]
                    取不到 scapy 時回退為只有 broadcast 的簡化清單。
    """
    ifaces: list[dict] = []
    try:
        from scapy.all import conf as _scapy_conf
        for name, itf in _scapy_conf.ifaces.items():
            ip = getattr(itf, 'ip', None)
            mac = getattr(itf, 'mac', None) or ''
            if not ip or ip == '0.0.0.0' or ip.startswith('127.'):
                continue
            if mac in ('', '00:00:00:00:00:00'):
                continue
            ifaces.append({
                'name': str(name),
                'description': str(getattr(itf, 'description', '') or name),
                'ip': ip,
                'mac': mac,
                'broadcast': _broadcast_for(ip),
            })
    except Exception:
        pass

    if not ifaces:
        # 沒有 scapy 時的退路：只能從廣播位址反推，給不出 MAC/描述
        for b in get_broadcast_addresses():
            if b == '255.255.255.255':
                continue
            ifaces.append({'name': b, 'description': f'網段 {b}',
                           'ip': '', 'mac': '', 'broadcast': b})
    ifaces.sort(key=lambda d: d['ip'])
    return ifaces


def _broadcast_for(ip: str) -> str:
    """
    由 IP 推導廣播位址。有作業系統遮罩時採用真實網段，否則退回 /24 推測。
    與 get_broadcast_addresses() 共用同一套計算，兩處不會再各算各的。
    """
    # discover() 會把回傳值直接當成廣播目標，因此 /31、/32 沒有廣播位址時
    # 退回受限廣播，而不是回空字串。
    return _broadcast_from_mask(ip, _iface_netmasks().get(ip)) or '255.255.255.255'


def discover(timeout: float = 2.0, on_stage=None, iface_ip: str | None = None) -> dict:
    """
    完整探索流程：先 List Identity 廣播，無回應時退回 ARP table。

    CLI 與 web 共用此函式，確保兩邊的 fallback 行為永遠一致。

    Args:
        iface_ip: 指定要從哪張網卡掃描（傳網卡自己的 IP）；None = 全部網卡。
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
    if iface_ip:
        # 指定網卡：同時送導向廣播與受限廣播。部分設備只回應 255.255.255.255
        # （原因同 DHCP_LIMITED_BROADCAST 的註解：網卡與設備的遮罩認知可能不一致）
        broadcasts = [_broadcast_for(iface_ip), '255.255.255.255']
    else:
        broadcasts = get_broadcast_addresses()
    if on_stage:
        on_stage('eip', {'broadcasts': broadcasts})
    devices = discover_devices(timeout=timeout, broadcasts=broadcasts, bind_ip=iface_ip)
    if devices:
        _fill_macs(devices)
        return {'devices': devices, 'via': 'EIP', 'broadcasts': broadcasts}

    if on_stage:
        on_stage('arp', {})
    devices = discover_by_arp()
    if devices:
        return {'devices': devices, 'via': 'ARP', 'broadcasts': broadcasts}

    return {'devices': [], 'via': None, 'broadcasts': broadcasts}


def _fill_macs(devices: list[dict]) -> None:
    """
    就地補上 List Identity 查不到的 MAC。

    List Identity 回應本身**不含 MAC**（只有 IP/廠商/序號/產品名），
    但設備既然剛回應過廣播，本機 ARP table 幾乎必然已有它的項目，
    因此查一次 ARP 就能補齊，讓 EIP 與 ARP 兩條探索路徑的欄位一致。
    """
    try:
        macs = arp_mac_map()
    except Exception:
        return
    for d in devices:
        if not d.get('mac'):
            d['mac'] = macs.get(d['ip'], '')


# ── DHCP 偵測與指派（設備失聯時的救援路徑）──────────────────
#
# 設備切成 DHCP 但網段上沒有 DHCP server 時，它拿不到位址，
# EIP 廣播與 ARP 都找不到它——但它仍會**持續送出 DHCP Discover 廣播**，
# 封包裡帶著自己的 MAC。監聽 UDP/67 是這種狀態下唯一能發現設備的方法，
# 也是把它救回來的第一步。綁定 port 67 在 Windows 上不需要管理員權限。


def dhcp_msg_type(data: bytes) -> int | None:
    """
    從 DHCP 封包解析 Option 53（訊息型別）。

    ⚠️ 不可用 `data[0]` 判斷——那是 BOOTP 的 `op` 欄位（1=BOOTREQUEST），
    不是訊息型別。因為 DHCP_DISCOVER 剛好也等於 1，用 data[0] 會把
    REQUEST/RELEASE/INFORM 全都誤判成 Discover。
    """
    if len(data) < 240 or data[236:240] != DHCP_MAGIC:
        return None
    i = 240
    while i < len(data) - 1:
        opt = data[i]
        if opt == 255:
            break
        if opt == 0:
            i += 1
            continue
        length = data[i + 1]
        if opt == 53 and length >= 1:
            return data[i + 2]
        i += 2 + length
    return None


def iface_mac_for(ip: str) -> str | None:
    """查出指定 IP 所屬網卡的 MAC（用來把本機自己的 DHCP 流量過濾掉）。"""
    try:
        from scapy.all import conf as _scapy_conf
        for _, itf in _scapy_conf.ifaces.items():
            if getattr(itf, 'ip', None) == ip:
                return getattr(itf, 'mac', None)
    except Exception:
        pass
    return None


def open_dhcp_socket(bind_ip: str) -> tuple:
    """
    綁定 UDP port 67，回傳 (socket, error_msg)。

    刻意綁定到 bind_ip（選定網卡的位址）而非 INADDR_ANY：多網卡主機上綁
    INADDR_ANY 時，送出 Offer/ACK 廣播可能選到錯誤網卡，設備永遠收不到而
    卡在 Discover 重試迴圈（實機驗證過的行為）。

    Returns:
        (socket, None)  綁定成功
        (None, str)     失敗，字串說明原因（含占用該埠的行程名稱，若查得到）
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind((bind_ip, DHCP_SERVER_PORT))
        return sock, None
    except OSError as e:
        sock.close()
        holder = ''
        try:
            r = subprocess.run(
                ['powershell', '-c',
                 'Get-NetUDPEndpoint -LocalPort 67 | ForEach-Object {'
                 ' $p = Get-Process -Id $_.OwningProcess -EA SilentlyContinue;'
                 ' "$($p.Name) (PID $($_.OwningProcess))" }'],
                capture_output=True, text=True, timeout=5)
            holder = r.stdout.strip()
        except Exception:
            pass
        if holder:
            return None, f"UDP port 67 被占用：{holder}（請先關閉，例如 BootP-DHCP Tool）"
        return None, f"無法綁定 UDP port 67 於 {bind_ip}: {e}"


def detect_dhcp_macs(sock, own_mac: str | None, timeout: float = 30.0,
                     grace: float = 2.0, on_found=None, should_stop=None) -> dict:
    """
    監聽 DHCP Discover，回傳 {mac: 出現次數}。

    找到第一台後再多等 grace 秒，看是否還有其他設備一起在送 Discover。
    socket 由呼叫端持有與關閉，這裡只借用——MAC 偵測與後續的 serve_dhcp()
    必須共用同一個 socket，中途關閉重開會漏接設備的 Discover。

    Args:
        own_mac:     本機網卡 MAC，用來排除自己送出的 DHCP 流量；None = 不過濾
        on_found:    可選 callback `(mac: str) -> None`，第一次看到某個 MAC 時呼叫
        should_stop: 可選 callable `() -> bool`，每輪（約 0.25 秒）檢查一次；
                     回傳 True 就提早結束。給 web 做「手動中斷」用——不能只讓
                     前端放棄請求，那樣伺服器執行緒仍會佔著 UDP/67 直到逾時，
                     使用者根本無法重試。
    """
    sock.settimeout(0.25)
    seen: dict[str, int] = {}
    deadline = time.time() + timeout
    grace_deadline = None
    own = (own_mac or '').lower()
    try:
        while time.time() < deadline:
            if should_stop and should_stop():
                break
            if grace_deadline is not None and time.time() >= grace_deadline:
                break
            try:
                data, _ = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if dhcp_msg_type(data) != DHCP_DISCOVER:
                continue
            mac = ':'.join(f'{b:02x}' for b in data[28:34])
            if mac == '00:00:00:00:00:00' or mac == own:
                continue
            if mac not in seen:
                if on_found:
                    on_found(mac)
                if grace_deadline is None:
                    grace_deadline = time.time() + grace
            seen[mac] = seen.get(mac, 0) + 1
    except KeyboardInterrupt:
        pass   # CLI 按 Ctrl+C 時回傳已收集到的部分結果，不往上拋
    return seen


def build_dhcp_reply(xid: bytes, chaddr: bytes, offered_ip: str,
                     server_ip: str, subnet: str, msg_type: int,
                     client_flags: bytes = b'\x80\x00') -> bytes:
    """組出 DHCP Offer/ACK 封包（BOOTP 標頭 + Option 53/54/51/1/3）。"""
    pkt = bytes([2, 1, 6, 0]) + xid + b'\x00\x00' + client_flags
    pkt += b'\x00' * 4                    # ciaddr
    pkt += socket.inet_aton(offered_ip)   # yiaddr
    pkt += b'\x00' * 4                    # siaddr（用 Option 54 識別）
    pkt += b'\x00' * 4                    # giaddr
    pkt += chaddr + b'\x00' * 10          # chaddr 16 bytes
    pkt += b'\x00' * 64 + b'\x00' * 128  # sname + file
    pkt += DHCP_MAGIC
    pkt += bytes([53, 1, msg_type])
    pkt += bytes([54, 4]) + socket.inet_aton(server_ip)
    pkt += bytes([51, 4]) + DHCP_LEASE_SECONDS.to_bytes(4, 'big')
    pkt += bytes([1, 4]) + socket.inet_aton(subnet)
    pkt += bytes([3, 4]) + socket.inet_aton(server_ip)  # router（必要）
    pkt += b'\xff'
    if len(pkt) < 300:
        pkt += b'\x00' * (300 - len(pkt))
    return pkt


def normalize_mac(mac: str) -> str:
    """把 `aa-bb-cc-...` / 大寫 等寫法統一成 `aa:bb:cc:...`。"""
    return mac.replace('-', ':').strip().lower()


def serve_dhcp(sock, server_ip: str, target_mac: str, assign_ip: str,
               subnet: str = "255.255.255.0",
               timeout: float = DHCP_SERVE_TIMEOUT,
               on_progress=None, on_event=None, should_stop=None) -> bool:
    """
    迷你 DHCP server：只回應 target_mac，指派 assign_ip 給它。

    Args:
        on_progress: 可選 callback `(remain_seconds: int) -> None`，每約 10 秒一次
        on_event:    可選 callback `(event: str, info: dict) -> None`
                     event 為 'offer' 或 'ack'
        should_stop: 可選 callable `() -> bool`，每輪（約 1 秒）檢查一次，
                     回傳 True 就中止。理由同 detect_dhcp_macs()。

    Returns:
        True  已送出 ACK（設備取得位址）
        False 逾時、或被 should_stop 中止
    """
    target_bytes = bytes(int(x, 16) for x in normalize_mac(target_mac).split(':'))
    sock.settimeout(1.0)
    deadline = time.time() + timeout
    last_status = time.time()
    while time.time() < deadline:
        if should_stop and should_stop():
            break
        if on_progress and time.time() - last_status >= 10:
            last_status = time.time()
            on_progress(int(deadline - time.time()))
        try:
            data, _ = sock.recvfrom(1024)
        except socket.timeout:
            continue
        except OSError:
            break
        if len(data) < 240 or data[236:240] != DHCP_MAGIC:
            continue
        if data[28:34] != target_bytes:
            continue
        xid = data[4:8]
        client_flags = data[10:12]
        msg_type = dhcp_msg_type(data)
        if msg_type == DHCP_DISCOVER:
            reply = build_dhcp_reply(xid, data[28:34], assign_ip, server_ip,
                                     subnet, DHCP_OFFER, client_flags)
            sock.sendto(reply, (DHCP_LIMITED_BROADCAST, DHCP_CLIENT_PORT))
            if on_event:
                on_event('offer', {'ip': assign_ip})
        elif msg_type == DHCP_REQUEST:
            reply = build_dhcp_reply(xid, data[28:34], assign_ip, server_ip,
                                     subnet, DHCP_ACK, client_flags)
            sock.sendto(reply, (DHCP_LIMITED_BROADCAST, DHCP_CLIENT_PORT))
            if on_event:
                on_event('ack', {'ip': assign_ip})
            return True
    return False
