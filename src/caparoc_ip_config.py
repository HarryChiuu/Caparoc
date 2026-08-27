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

# 探索與 IP 格式判斷等不含互動 I/O 的邏輯統一放在 caparoc_ip_core，
# 與 web/app.py 共用同一份實作——修改探索行為只需改那一個檔案。
from caparoc_ip_core import (
    CLASS_TCPIP, INST, SVC_GET, SVC_SET, ATTR_CTRL, ATTR_IFACE, CTRL_NAMES,
    EIP_PORT, DEVICE_ONLINE_MAX_WAIT, _le2ip,
    is_valid_ip, same_subnet, discover, wait_for_device,
)

# ── DHCP 常數（僅新裝置配置流程使用，故留在本檔）─────────────
DHCP_SERVER_PORT = 67
DHCP_CLIENT_PORT = 68
DHCP_MAGIC       = b'\x63\x82\x53\x63'
DHCP_LEASE_SECONDS = 86400
# RFC 2131：client 尚無 IP 且 broadcast flag 有設時，server 應以受限廣播
# 255.255.255.255 回覆 Offer/ACK，而非依網卡遮罩算出的子網路導向廣播 ——
# 後者在網卡實際廣播網域與設備回報的遮罩不一致時（例如網卡是 /24 但設備
# 回報 /23）會送不到設備，導致卡在 Discover→Offer 循環收不到 Request。
DHCP_LIMITED_BROADCAST = '255.255.255.255'

# DHCP 訊息型別（Option 53）
DHCP_DISCOVER, DHCP_OFFER, DHCP_REQUEST, DHCP_ACK = 1, 2, 3, 5

# 等待／逾時（秒）；DEVICE_ONLINE_MAX_WAIT 由 caparoc_ip_core 提供
MAC_DETECT_TIMEOUT     = 30.0   # 偵測設備 MAC 的總上限（三種方法共用）
DHCP_SERVE_TIMEOUT     = 300.0  # mini DHCP server 自動結束時間


def _prompt_ip(prompt: str, allow_cancel_values: tuple[str, ...] = ()) -> str | None:
    """持續要求輸入直到格式正確的 IP，或使用者輸入取消關鍵字（回傳 None）"""
    while True:
        value = input(prompt).strip()
        if value.lower() in allow_cancel_values:
            return None
        if not value:
            return value  # 允許空字串代表「使用預設值/略過」，由呼叫端判斷
        if is_valid_ip(value):
            return value
        print(f"  ⚠️  「{value}」不是合法的 IP 格式（需為 x.x.x.x，例如 192.168.50.10），請重新輸入")


def _wait_for_device(ip: str, max_wait: float = DEVICE_ONLINE_MAX_WAIT) -> bool:
    """
    core.wait_for_device() 的 CLI 包裝：補回原地進度更新與結果訊息。

    核心層不做任何輸出（web 也要用），所以畫面呈現留在這一層。
    """
    ok = wait_for_device(
        ip, max_wait=max_wait,
        on_progress=lambda remain: print(
            f"  ⏳ 等待設備上線...（剩餘 {remain}s）", end='\r', flush=True),
    )
    if ok:
        print(f"\n  ✅ 設備已上線：{ip}")
    else:
        print(f"\n  ⚠️  {int(max_wait)}s 內未偵測到設備上線")
    return ok


# ── 設備探索（畫面呈現；探索邏輯在 caparoc_ip_core）────────

def _print_discover_stage(stage: str, info: dict) -> None:
    """core.discover() 的階段回呼：在每個階段開始前印出提示"""
    if stage == 'eip':
        print(f"\n探索設備（廣播：{', '.join(info['broadcasts'])}）...")
    elif stage == 'arp':
        print("  List Identity 無回應，改用 ARP table...")


def run_discovery() -> str | None:
    devices = discover(timeout=2.0, on_stage=_print_discover_stage)['devices']
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

    new_ip = _prompt_ip("  新 IP 位址（cancel 取消）: ", allow_cancel_values=("cancel",))
    if new_ip is None:
        return
    subnet = _prompt_ip(f"  子網路遮罩 [Enter={cur_subnet}]: ") or cur_subnet
    gateway = _prompt_ip("  預設閘道   [Enter=0.0.0.0]: ") or "0.0.0.0"

    print(f"\n  IP={new_ip}  Subnet={subnet}  GW={gateway or '0.0.0.0'}")
    if input("  確認送出？ [Y/N]: ").strip().upper() != 'Y':
        print("  已取消")
        return

    result = backend.set_device_ip(driver, new_ip, subnet, gateway)
    if result['success']:
        print("  ✅ 指令送出完成！")
        if not _wait_for_device(new_ip):
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


def _open_dhcp_socket(bind_ip: str) -> socket.socket | None:
    """
    綁定 UDP port 67 並回傳該 socket；此 socket 會在整個新裝置設定流程中
    全程持有，MAC 偵測（方法 A）與 mini DHCP server 共用同一個 socket，
    中間不再關閉重開，避免使用者輸入參數期間漏接設備的 DHCP Discover。

    刻意綁定到 bind_ip（使用者選定網卡的位址）而非 INADDR_ANY：這台工具
    常在多網卡主機上執行，若綁 INADDR_ANY，稍後送出 Offer/ACK 廣播封包時
    作業系統可能選到錯誤的網卡送出，導致設備永遠收不到、卡在 Discover
    重試迴圈。綁定到特定網卡位址可確保送收都固定走同一張網卡（此為實機
    測試驗證過的行為）。

    綁定失敗時嘗試找出占用該埠的行程，回傳 None。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind((bind_ip, DHCP_SERVER_PORT))
        return sock
    except OSError:
        sock.close()
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
            else:
                print("  ❌ port 67 被占用")
        except Exception:
            print("  ❌ port 67 被占用")
        return None


def _detect_mac_via_socket(sock: socket.socket, own_mac: str, deadline: float,
                            grace: float = 2.0) -> dict[str, int]:
    """
    方法 A：在呼叫端已綁定 port 67 的 socket 上監聽 DHCP Discover。
    找到第一個設備後再多等 grace 秒，看是否有其他設備一併送出 Discover。
    socket 由呼叫端持有／關閉，這裡只借用。
    """
    sock.settimeout(0.25)
    seen: dict[str, int] = {}
    grace_deadline: float | None = None
    try:
        while time.time() < deadline:
            if grace_deadline is not None and time.time() >= grace_deadline:
                break
            try:
                data, _ = sock.recvfrom(1024)
            except socket.timeout:
                continue
            if len(data) < 34 or data[0] != DHCP_DISCOVER:
                continue
            chaddr = data[28:34]
            mac = ':'.join(f'{b:02x}' for b in chaddr)
            if mac == '00:00:00:00:00:00' or mac == own_mac:
                continue
            if mac not in seen:
                print(f"  📡 發現 DHCP Discover from: {mac}")
                if grace_deadline is None:
                    grace_deadline = time.time() + grace
            seen[mac] = seen.get(mac, 0) + 1
    except KeyboardInterrupt:
        pass
    return seen


def _detect_mac_via_rawsock(iface: str, own_mac: str, deadline: float) -> str | None:
    """方法 B：Windows Raw Socket + SIO_RCVALL（混雜模式，同 Wireshark 原理）"""
    found_raw: list[str] = []
    try:
        rs = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        rs.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        rs.settimeout(1.0)
        from scapy.all import get_if_addr
        bind_ip = get_if_addr(iface) or '0.0.0.0'
        rs.bind((bind_ip, 0))
        # 開啟混雜模式 - 接收所有進入此 NIC 的封包
        rs.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        print(f"  Raw Socket 混雜模式（{bind_ip}），等待 DHCP Discover...")
        try:
            while time.time() < deadline:
                try:
                    raw_pkt, _ = rs.recvfrom(65535)
                except socket.timeout:
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
                if dst_port != DHCP_SERVER_PORT:
                    continue
                payload = raw_pkt[udp_start + 8:]
                if len(payload) < 240 or payload[0] != DHCP_DISCOVER:
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
                rs.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except Exception:
                pass
            rs.close()
        if found_raw:
            return found_raw[0]
    except Exception as e:
        print(f"  ⚠️  Raw Socket 失敗: {e}，改用 scapy...")
    return None


def _detect_mac_via_scapy(iface: str, own_mac: str, deadline: float) -> str | None:
    """方法 C：scapy sniff with BPF filter"""
    from scapy.all import sniff
    found: list[str] = []
    remain = max(0.1, deadline - time.time())
    print(f"  等待 DHCP Discover（scapy，{int(remain)} 秒）...")

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
                if opts[i + 2] == DHCP_DISCOVER:
                    found.append(src_mac)
                    print(f"\n  ✅ 發現設備 MAC: {src_mac}")
                return
            i += 2 + olen

    try:
        sniff(iface=iface, timeout=remain, prn=handle,
              filter="udp dst port 67")
    except KeyboardInterrupt:
        pass

    return found[0] if found else None


def _detect_device_mac(iface: str, sock: socket.socket,
                        timeout: float = MAC_DETECT_TIMEOUT) -> str | None:
    """
    偵測設備 MAC：依序嘗試方法 A（呼叫端已綁定的 port 67 socket）→
    方法 B（Windows Raw Socket 混雜模式）→ 方法 C（scapy sniff）。
    三者共用同一個 deadline，總耗時上限為 timeout，而非三者相加。
    """
    from scapy.all import get_if_hwaddr

    try:
        own_mac = get_if_hwaddr(iface).lower().replace('-', ':')
    except Exception:
        own_mac = ''

    deadline = time.time() + timeout
    print(f"  監聽 UDP port 67（最多 {int(timeout)} 秒）... Ctrl+C 中斷")
    print(f"  （PC 自身 MAC {own_mac} 已自動排除）")
    print(f"  （若遲遲沒有反應，可重新插拔設備網路線觸發它送出 Discover）")

    seen = _detect_mac_via_socket(sock, own_mac, deadline)
    if seen:
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

    if deadline - time.time() < 3.0:
        print("  ⚠️  時間已用盡，略過 Raw Socket / scapy 偵測")
        return None

    print("  ⚠️  UDP port 67 超時未找到外部設備，改用 Raw Socket 混雜模式...")
    mac = _detect_mac_via_rawsock(iface, own_mac, deadline)
    if mac:
        return mac

    if deadline - time.time() < 1.0:
        return None
    return _detect_mac_via_scapy(iface, own_mac, deadline)


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


def _serve_dhcp(sock: socket.socket, server_ip: str, target_mac: str,
                 assign_ip: str, subnet: str = "255.255.255.0",
                 timeout: float = DHCP_SERVE_TIMEOUT) -> bool:
    """
    在呼叫端已開啟並持有的 port 67 socket 上持續監聽，分配 assign_ip 給
    指定 MAC。Ctrl+C 或逾時（預設 5 分鐘）皆會中止；socket 由呼叫端關閉。
    """
    target_bytes = bytes(int(x, 16) for x in target_mac.replace('-', ':').split(':'))
    sock.settimeout(1.0)
    deadline = time.time() + timeout
    last_status = time.time()
    while time.time() < deadline:
        if time.time() - last_status >= 10:
            last_status = time.time()
            remain = int(deadline - time.time())
            print(f"  ⏳ 等待 DHCP Discover...（剩餘 {remain}s）", end='\r', flush=True)
        try:
            data, _ = sock.recvfrom(1024)
        except socket.timeout:
            continue
        if len(data) < 240 or data[236:240] != DHCP_MAGIC:
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
        if msg_type == DHCP_DISCOVER:
            reply = _build_dhcp_reply(xid, chaddr, assign_ip, server_ip, subnet, DHCP_OFFER, client_flags)
            sock.sendto(reply, (DHCP_LIMITED_BROADCAST, DHCP_CLIENT_PORT))
            print(f"\n  📤 DHCP Offer → {assign_ip}")
        elif msg_type == DHCP_REQUEST:
            reply = _build_dhcp_reply(xid, chaddr, assign_ip, server_ip, subnet, DHCP_ACK, client_flags)
            sock.sendto(reply, (DHCP_LIMITED_BROADCAST, DHCP_CLIENT_PORT))
            print(f"  ✅ DHCP ACK → 設備已取得 {assign_ip}")
            return True
    print(f"\n  ⚠️  {int(timeout)}s 內未完成 DHCP 交握")
    return False


def _provision_new_device():
    """新裝置初始設定：mini DHCP server 分配 IP → CIP 設定為靜態 IP"""
    print("\n── 新裝置初始設定（DHCP 取得 IP → 設定為靜態 IP）───────")
    print("  前提：其他 DHCP/BOOTP 工具（如 BootP-DHCP Tool）已關閉\n")

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

    # ── 先找出設備 MAC，再問要給它的 IP ──────────────────────
    # socket 一開就不再關閉，MAC 偵測與稍後的 mini DHCP server 共用同一個
    # socket；即使使用者接下來要花時間輸入 IP/遮罩/閘道，設備重送的
    # DHCP Discover 也只會停在 kernel 的接收緩衝區等著，不會被漏接。
    sock = _open_dhcp_socket(server_ip)
    if sock is None:
        return

    try:
        sub = input("\n  設備 MAC：[1] 監聽 DHCP Discover 自動偵測（最多 30 秒） [2] 手動輸入: ").strip()
        if sub == '2':
            target_mac = input("    MAC（格式 cc:cc:ea:9f:c9:72）: ").strip().lower()
        else:
            print("    等待設備 DHCP Discover，請確認設備已接上網路...")
            target_mac = _detect_device_mac(iface, sock, timeout=MAC_DETECT_TIMEOUT)
            if not target_mac:
                target_mac = input("    未偵測到，手動輸入 MAC（留空取消）: ").strip().lower()
        if not target_mac:
            return

        assign_ip = _prompt_ip("\n  目標靜態 IP（e.g. 192.168.50.XXX，留空取消）: ")
        if not assign_ip:
            return
        subnet = _prompt_ip("  子網路遮罩 [Enter=255.255.255.0]: ") or "255.255.255.0"
        gateway = _prompt_ip("  預設閘道   [Enter=0.0.0.0 不設定]: ") or "0.0.0.0"

        if assign_ip == server_ip:
            print(f"  ❌ 目標 IP 與本機網卡 IP 相同（{server_ip}），請重新執行並輸入不同的 IP")
            return
        if not same_subnet(assign_ip, server_ip, subnet):
            print(f"  ⚠️  目標 IP {assign_ip} 與本機網卡 {server_ip}（遮罩 {subnet}）不同網段，")
            print(f"     DHCP 分配可能『看似成功』但設備上線後仍連不上。")
            if input("  仍要繼續？ [Y/N]: ").strip().upper() != 'Y':
                print("  已取消")
                return

        print(f"\n  MAC    : {target_mac}")
        print(f"  目標 IP: {assign_ip}  Subnet: {subnet}  GW: {gateway}")
        if input("  確認啟動 mini DHCP server？ [Y/N]: ").strip().upper() != 'Y':
            return

        print(f"\n  mini DHCP server 已啟動（按 Ctrl+C 中斷）")
        print(f"  ⏳ 等待設備自動送出 DHCP Discover（設備會自動重試，通常不需操作）")
        print(f"  ⚡ 若久候沒有反應，可重插設備網路線以強制立即重試")
        print(f"     或在另一個終端機執行: python src/caparoc_ip_config.py <目前IP> → [3] 切 DHCP")

        try:
            got = _serve_dhcp(sock, server_ip, target_mac, assign_ip, subnet)
        except KeyboardInterrupt:
            print("\n  中斷")
            return
    finally:
        sock.close()

    if not got:
        return

    if not _wait_for_device(assign_ip):
        print(f"  ⚠️  設備尚未偵測到上線，仍嘗試寫入靜態 IP...")

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
        ip_arg = sys.argv[1]
        if not is_valid_ip(ip_arg):
            print(f"❌ 「{ip_arg}」不是合法的 IP 格式")
            print(__doc__)
            return
        _run_connected_menu(ip_arg)
        return

    while True:
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
            continue

        device_ip = run_discovery()
        if device_ip is not None:
            _run_connected_menu(device_ip)


if __name__ == "__main__":
    main()
