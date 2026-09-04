#!/usr/bin/env python3
"""
主機名稱（Host Name）來源診斷 — 唯讀，不寫入任何東西。

── 為什麼需要這支 ──────────────────────────────────────────────────
Web UI 的「主機名稱」欄目前是唯讀顯示。原廠 EDS（docs/vendor/CAPAROC_PM_EIP.eds）
的 [TCP/IP Interface Class] 宣告：

    Instance_Attributes = ... 0x5, 0x6, ...      ← attr 6 = Host Name 有支援
    Instance_Services   = 0x01, 0xE, 0x10;       ← 0x10 = Set_Attribute_Single

也就是說**協定層面可以寫**。但要動手改之前必須先確認三件事，這支就是來回答的：

  1. 畫面上那個名稱到底來自哪一個 attribute？
     backend 的 get_network_info() 是「優先讀 attr 5 的 Domain Name，
     空的才退回 attr 6 的 Host Name」——兩者是不同欄位，寫錯地方不會有效果。
  2. 兩個欄位各自的實際位元組長什麼樣？（CIP STRING = 2-byte LE 長度 + ASCII）
  3. 設備到底回不回應 attr 6？EDS 說支援，不代表韌體真的實作了。

⚠️ 本工具**只做 Get_Attribute_Single（0x0E）**，不送任何寫入服務。
   對設備沒有副作用，可以安心在產線上跑。

用法：
    python tests/manual/check_hostname.py [IP]
    python tests/manual/check_hostname.py 192.168.50.111
"""
import sys
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from pycomm3 import CIPDriver          # noqa: E402
from console_io import force_safe_stdio  # noqa: E402

force_safe_stdio()

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.50.111"

SEP = "=" * 64


def hexdump(data: bytes, limit: int = 64) -> str:
    """前 limit 個位元組的 hex，方便比對格式。"""
    shown = data[:limit]
    out = " ".join(f"{b:02X}" for b in shown)
    return out + (f" …（共 {len(data)} bytes）" if len(data) > limit else f"（{len(data)} bytes）")


def parse_cip_string(data: bytes, offset: int = 0) -> tuple[str | None, str]:
    """
    CIP STRING：2-byte LE UINT 長度 + ASCII chars。

    回傳 (解析出的字串 or None, 說明)。
    """
    if len(data) < offset + 2:
        return None, f"長度不足，無法讀出 2-byte 長度前綴（只有 {len(data)} bytes）"
    n = struct.unpack_from("<H", data, offset)[0]
    if n == 0:
        return "", "長度前綴 = 0 → 這個欄位是空的"
    if len(data) < offset + 2 + n:
        return None, f"長度前綴說有 {n} 字，但實際只剩 {len(data) - offset - 2} bytes"
    text = data[offset + 2:offset + 2 + n].decode("ascii", errors="replace").strip("\x00")
    return text, f"長度前綴 = {n}"


def read(drv, cls, inst, attr, connected=True):
    """Get_Attribute_Single。回傳 bytes 或 None。"""
    try:
        resp = drv.generic_message(
            service=0x0E, class_code=cls, instance=inst,
            attribute=attr, connected=connected, unconnected_send=False,
        )
        if not resp or getattr(resp, "error", None):
            return None, getattr(resp, "error", "無回應")
        return bytes(resp.value or b""), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def main():
    print(f"\n{SEP}")
    print(f"  主機名稱來源診斷（唯讀）  →  {IP}")
    print(f"{SEP}\n")

    try:
        with CIPDriver(IP) as drv:
            # ── attr 5：Interface Configuration（IP/遮罩/閘道/DNS + Domain Name）──
            print("【attr 5】TCP/IP Interface Configuration")
            print("  結構：IP(4) Subnet(4) Gateway(4) DNS1(4) DNS2(4) + Domain Name(CIP STRING)")
            raw5, err5 = read(drv, 0xF5, 1, 5)
            if raw5 is None:
                print(f"  ❌ 讀取失敗：{err5}\n")
                domain = None
            else:
                print(f"  raw: {hexdump(raw5)}")
                if len(raw5) >= 20:
                    for i, label in enumerate(("IP", "Subnet", "Gateway", "DNS1", "DNS2")):
                        v = struct.unpack_from("<I", raw5, i * 4)[0]
                        print(f"    {label:8}: {(v>>24)&0xFF}.{(v>>16)&0xFF}.{(v>>8)&0xFF}.{v&0xFF}")
                domain, note = parse_cip_string(raw5, 20) if len(raw5) >= 22 else (None, "沒有 Domain Name 欄位")
                print(f"    Domain Name: {domain!r}  （{note}）\n")

            # ── attr 6：Host Name ──────────────────────────────────────────
            print("【attr 6】TCP/IP Host Name")
            raw6, err6 = read(drv, 0xF5, 1, 6)
            if raw6 is None:
                print(f"  ❌ 讀取失敗：{err6}")
                print("     → EDS 宣告有支援，但韌體可能未實作。若要改名只能走 attr 5。\n")
                host = None
            else:
                print(f"  raw: {hexdump(raw6)}")
                host, note = parse_cip_string(raw6, 0)
                print(f"    Host Name: {host!r}  （{note}）\n")

            # ── 結論 ────────────────────────────────────────────────────────
            print(SEP)
            print("  結論")
            print(SEP)
            print("  backend 的 get_network_info() 邏輯是：")
            print("    先讀 attr 5 的 Domain Name；若為空才退回 attr 6 的 Host Name。\n")

            if domain:
                shown, src, target = domain, "attr 5 的 Domain Name", "attr 5（整個 Interface Configuration 結構）"
            elif host:
                shown, src, target = host, "attr 6 的 Host Name", "attr 6（單一 CIP STRING）"
            else:
                shown = src = target = None

            if shown is None:
                print("  ⚠ 兩個欄位都讀不到內容，Web UI 應該顯示「—」。")
                print("    若畫面上有值，請把畫面截圖與本輸出一起回報。")
            else:
                print(f"  ✅ Web UI 顯示的「{shown}」來自 {src}")
                print(f"     → 要改名的話，寫入目標是 {target}")
                if domain and host and domain != host:
                    print(f"\n  ℹ️ 注意：attr 6 另有不同的值 {host!r}，兩者並存。")
                    print("     改名時要想清楚該動哪一個，或兩個都要同步。")

            if target and target.startswith("attr 5"):
                print("\n  ⚠️ attr 5 是**整包結構**（IP/遮罩/閘道/DNS 都在裡面）。")
                print("     要改 Domain Name 必須 read-modify-write 整包回寫——")
                print("     這與 set_device_ip() 是同一個 attribute，風險等級相同：")
                print("     寫錯會連 IP 一起改掉，設備可能失聯。")

            print()

    except Exception as e:
        print(f"\n❌ 無法連線至 {IP}：{type(e).__name__}: {e}")
        print("   請確認設備已上電、網路可達（先 ping 看看）。\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
