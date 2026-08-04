#!/usr/bin/env python3
"""
IP 設定功能測試工具

測試 CIP Class 0xF5 (TCP/IP Interface Object) 的讀取與寫入：
  [1] 讀取目前設備網路設定
  [2] 設定靜態 IP（Set Attribute Single: Attr3=Static + Attr5=IP config）
  [3] 切換為 DHCP 模式（Set Attribute Single: Attr3=DHCP）
  [0] 離開

用法：
  python tests/test_ip_config.py [設備IP]
  python tests/test_ip_config.py 192.168.50.221
"""
import sys
import struct
import socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


def _read_attr(driver, attr):
    return driver.generic_message(
        service=SVC_GET, class_code=CLASS_TCPIP, instance=INST,
        attribute=attr, connected=False
    )


def _write_attr(driver, attr, data: bytes):
    return driver.generic_message(
        service=SVC_SET, class_code=CLASS_TCPIP, instance=INST,
        attribute=attr, request_data=data, connected=False
    )


def read_config(driver):
    """讀取並列印目前設備網路設定"""
    print("\n── 讀取設備網路設定 ───────────────────────────────")

    # Attr 3: Configuration Control
    resp = _read_attr(driver, ATTR_CTRL)
    if resp and resp.value and len(resp.value) >= 4:
        ctrl = struct.unpack('<I', resp.value[:4])[0]
        print(f"  IP 取得方式 (Attr3): {CTRL_NAMES.get(ctrl, f'未知 0x{ctrl:02X}')}  [{ctrl}]")
        print(f"  raw bytes         : {resp.value[:4].hex()}")
    else:
        print("  Attr3 讀取失敗")

    # Attr 5: Interface Configuration
    resp = _read_attr(driver, ATTR_IFACE)
    if resp and resp.value and len(resp.value) >= 12:
        raw = resp.value
        ip      = socket.inet_ntoa(raw[0:4])
        subnet  = socket.inet_ntoa(raw[4:8])
        gw      = socket.inet_ntoa(raw[8:12])
        dns1    = socket.inet_ntoa(raw[12:16]) if len(raw) >= 16 else "—"
        dns2    = socket.inet_ntoa(raw[16:20]) if len(raw) >= 20 else "—"
        print(f"  IP 位址   (Attr5) : {ip}")
        print(f"  子網路遮罩        : {subnet}")
        print(f"  預設閘道          : {gw if gw != '0.0.0.0' else '（未設定）'}")
        print(f"  DNS1              : {dns1}")
        print(f"  DNS2              : {dns2}")
        print(f"  raw bytes         : {raw[:20].hex()}")
    else:
        print("  Attr5 讀取失敗")

    print("─" * 52)


def set_static_ip(driver, backend: CaparocBackend):
    """互動式設定靜態 IP"""
    print("\n── 設定靜態 IP ────────────────────────────────────")

    # 先讀目前設定作為預設值
    resp = _read_attr(driver, ATTR_IFACE)
    cur_subnet = "255.255.255.0"
    if resp and resp.value and len(resp.value) >= 8:
        cur_subnet = socket.inet_ntoa(resp.value[4:8])

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
        socket.inet_aton(new_ip) +
        socket.inet_aton(subnet) +
        socket.inet_aton(gw_addr) +
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
        print(f"  ✅ 寫入成功！設備 IP 已變更為 {new_ip}")
        print("     連線中斷為正常現象，請以新 IP 重新連線。")
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
        print("  ✅ 寫入成功！設備正在向 DHCP server 取得 IP。")
        print("     請用 Wireshark 觀察 DHCP Discover 封包。")
    else:
        print(f"  ❌ 寫入失敗: {result['error']}")


# ── 主程式 ──────────────────────────────────────────────────
def main():
    device_ip = DEFAULT_IP
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
