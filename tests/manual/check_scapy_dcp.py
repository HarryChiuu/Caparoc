#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROFINET DCP / scapy 前期診斷測試

測試目標：
  Step 1 - 確認 scapy 可匯入、確認管理員權限
  Step 2 - 取得設備 MAC address（ARP）
  Step 3 - 發送 DCP Identify 廣播，確認設備是否回應 PROFINET DCP
  Step 4 - 若有回應，解析回應封包中的 IP Suite block

⚠️  須以「管理員身份」執行（scapy 需要 raw socket 權限）：
    在管理員 PowerShell 中：
        conda activate sv
        python tests/manual/check_scapy_dcp.py

    或指定設備 IP（預設 192.168.2.111）：
        python tests/manual/check_scapy_dcp.py 192.168.2.200
"""

import sys
import subprocess
import re
import struct
import socket as _socket
import time

DEVICE_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.2.111"

SEP  = "=" * 60
SEP2 = "-" * 40

# ──────────────────────────────────────────────────
# Step 1: scapy 可用性 + 管理員權限
# ──────────────────────────────────────────────────
def step1_check_scapy():
    print(f"\n{SEP}")
    print("Step 1: scapy 可用性 + 管理員權限")
    print(SEP)

    # 1-a: 匯入
    try:
        from scapy.all import conf  # noqa: F401
        print("  ✅ scapy 匯入成功")
    except ImportError:
        print("  ❌ scapy 未安裝")
        print("     請執行: pip install scapy")
        return False

    # 1-b: 管理員權限（Windows）
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False  # 非 Windows 或無法判定

    if is_admin:
        print("  ✅ 管理員身份確認")
    else:
        print("  ⚠️  非管理員身份")
        print("     raw socket 可能失敗，建議以管理員 PowerShell 執行")
        print("     繼續執行，若 sendp 失敗會顯示 PermissionError")

    return True


# ──────────────────────────────────────────────────
# Step 2: 取得設備 MAC（ARP）
# ──────────────────────────────────────────────────
def step2_get_mac():
    print(f"\n{SEP}")
    print(f"Step 2: 取得設備 MAC address (目標 IP: {DEVICE_IP})")
    print(SEP)

    # ping 一次讓 ARP table 有紀錄
    print(f"  ping {DEVICE_IP} ...")
    result = subprocess.run(
        ["ping", "-n", "1", "-w", "1000", DEVICE_IP],
        capture_output=True, text=True
    )
    if "TTL=" in result.stdout or "ttl=" in result.stdout:
        print("  ✅ ping 成功")
    else:
        print("  ⚠️  ping 無回應，嘗試繼續查 ARP table")

    # 查 ARP table
    arp_out = subprocess.run(
        ["arp", "-a", DEVICE_IP],
        capture_output=True, text=True
    ).stdout

    mac_match = re.search(
        r'([0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2}[-:][0-9a-f]{2})',
        arp_out, re.IGNORECASE
    )

    if mac_match:
        raw_mac = mac_match.group(1)
        # 統一轉為 xx:xx:xx:xx:xx:xx 格式
        mac = raw_mac.replace('-', ':').lower()
        print(f"  ✅ 設備 MAC: {mac}")
        return mac
    else:
        print("  ❌ 無法從 ARP table 取得 MAC")
        print(f"     ARP 輸出:\n{arp_out}")
        return None


# ──────────────────────────────────────────────────
# Step 3: DCP Identify 廣播（唯讀，不修改設備）
# ──────────────────────────────────────────────────
def step3_dcp_identify():
    print(f"\n{SEP}")
    print("Step 3: PROFINET DCP Identify 廣播（唯讀探測）")
    print(SEP)

    try:
        from scapy.all import Ether, Raw, sendp, sniff, get_if_list, conf
    except ImportError:
        print("  ❌ scapy 不可用，跳過")
        return []

    # 組裝 DCP Identify All Request
    # Ref: IEC 61158-6-10, DCP FrameID 0xFEFF
    dcp_payload = (
        b'\xfe\xff'          # FrameID: Identify All Request
        b'\x05'              # ServiceID: Identify
        b'\x00'              # ServiceType: Request
        b'\x00\x00\x00\x01' # Xid = 1
        b'\x00\x01'          # ResponseDelay = 1
        b'\x00\x04'          # DCPDataLength = 4
        b'\xff\xff'          # Option=All(0xFF), SubOption=All(0xFF)
        b'\x00\x00'          # BlockLength = 0
    )

    frame = Ether(
        dst="01:0e:cf:00:00:00",  # PROFINET DCP multicast MAC
        type=0x8892               # EtherType: PROFINET RT
    ) / Raw(load=dcp_payload)

    print(f"  發送 DCP Identify 廣播至 01:0e:cf:00:00:00 (Ethertype 0x8892)")
    try:
        sendp(frame, iface=None, verbose=False)
        print("  ✅ 封包發送成功")
    except PermissionError:
        print("  ❌ PermissionError: 請以管理員身份執行")
        return []
    except Exception as e:
        print(f"  ❌ 發送失敗: {e}")
        return []

    # 等待回應 3 秒
    print("  等待設備回應（3 秒）...")
    try:
        responses = sniff(
            filter="ether proto 0x8892",
            timeout=3,
            count=10
        )
    except Exception as e:
        print(f"  ❌ 捕捉封包失敗: {e}")
        return []

    if responses:
        print(f"  ✅ 收到 {len(responses)} 個 PROFINET 封包")
    else:
        print("  ⚠️  無回應（設備可能不支援 DCP，或網卡 iface 需指定）")
        _hint_iface()

    return list(responses)


# ──────────────────────────────────────────────────
# Step 4: 解析回應封包中的 IP Suite block
# ──────────────────────────────────────────────────
def step4_parse_responses(responses):
    print(f"\n{SEP}")
    print("Step 4: 解析 DCP 回應封包")
    print(SEP)

    if not responses:
        print("  （無封包可解析）")
        return

    for i, pkt in enumerate(responses):
        raw = bytes(pkt)
        print(f"\n  [{i+1}] 封包摘要: {pkt.summary()}")
        print(f"       原始 hex: {raw.hex()}")

        # 嘗試解析 FrameID（位移 12 bytes Ethernet header = dst(6)+src(6)，不含 type(2)）
        # Ethernet: dst(6) + src(6) + type(2) = 14 bytes header
        # PROFINET RT: 從 byte 14 開始
        if len(raw) < 18:
            print("       封包太短，跳過解析")
            continue

        frame_id = struct.unpack('>H', raw[14:16])[0]
        print(f"       FrameID: 0x{frame_id:04X}", end="")

        if frame_id == 0xFEFF:
            print(" (DCP Identify Response)")
        elif frame_id == 0xFEFD:
            print(" (DCP Set Request)")
        elif frame_id == 0xFEFE:
            print(" (DCP Get Response)")
        else:
            print(f" (未知 FrameID)")

        # 嘗試找 IP Suite block (Option=0x01, SubOption=0x02)
        _parse_dcp_ip_block(raw[14:])


def _parse_dcp_ip_block(dcp_data):
    """在 DCP payload 中搜尋 IP Suite block (Option=0x01, SubOption=0x02)"""
    # DCP header: FrameID(2) + ServiceID(1) + ServiceType(1) + Xid(4) + ResponseDelay(2) + DataLen(2) = 12
    if len(dcp_data) < 12:
        return

    data_offset = 12  # DCP blocks 從這裡開始
    payload = dcp_data[data_offset:]

    i = 0
    while i + 4 <= len(payload):
        option     = payload[i]
        sub_option = payload[i+1]
        block_len  = struct.unpack('>H', payload[i+2:i+4])[0]

        if option == 0x01 and sub_option == 0x02:
            # IP Suite block
            # BlockQualifier(2) + IP(4) + Subnet(4) + Gateway(4) = 14 bytes
            block_data = payload[i+4 : i+4+block_len]
            if len(block_data) >= 14:
                qualifier = struct.unpack('>H', block_data[0:2])[0]
                ip_addr  = _socket.inet_ntoa(block_data[2:6])
                subnet   = _socket.inet_ntoa(block_data[6:10])
                gateway  = _socket.inet_ntoa(block_data[10:14])
                print(f"\n       ✅ IP Suite Block:")
                print(f"          IP:      {ip_addr}")
                print(f"          Subnet:  {subnet}")
                print(f"          Gateway: {gateway}")
                print(f"          Qualifier: 0x{qualifier:04X} ({'Permanent' if qualifier & 1 else 'Temporary'})")
            break

        # 每個 block 對齊到偶數位元組
        i += 4 + block_len + (block_len % 2)


def _hint_iface():
    """列出可用網卡供使用者指定"""
    try:
        from scapy.all import get_if_list
        ifaces = get_if_list()
        print("\n  💡 可用網卡清單（若無回應可嘗試手動指定 iface）：")
        for name in ifaces:
            print(f"     {name}")
        print("\n  手動指定方式（修改腳本 step3_dcp_identify 中的 iface 參數）：")
        print("     sendp(frame, iface='Ethernet', verbose=False)")
        print("     sniff(filter='ether proto 0x8892', iface='Ethernet', timeout=3)")
    except Exception:
        pass


# ──────────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{'#'*60}")
    print("  PROFINET DCP / scapy 前期診斷測試")
    print(f"  目標設備 IP: {DEVICE_IP}")
    print(f"{'#'*60}")

    ok = step1_check_scapy()
    if not ok:
        print("\n❌ scapy 不可用，請先安裝後重試")
        sys.exit(1)

    mac = step2_get_mac()

    responses = step3_dcp_identify()

    step4_parse_responses(responses)

    print(f"\n{SEP}")
    print("診斷完成")
    if mac and responses:
        print("✅ 設備有 MAC，且有 DCP 回應 → 可進行 scapy DCP Set 實作")
    elif mac and not responses:
        print("⚠️  設備有 MAC，但無 DCP 回應 → 可能需要指定 iface，或設備不支援 DCP")
    else:
        print("❌ 無法取得 MAC，請先確認基礎網路連線")
    print(SEP)
