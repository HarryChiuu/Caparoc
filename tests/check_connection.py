#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAPAROC 連接診斷工具
快速檢查與設備的網路連接狀態
"""

import sys
import socket
import time
from pathlib import Path

# 添加 src 目錄到路徑
sys.path.insert(0, str(Path(__file__).parent / "src"))

def check_ping(host):
    """檢查網路連通性 (ping)"""
    import subprocess
    import platform
    
    print(f"\n[1/4] 檢查網路連通性...")
    print(f"      執行: ping {host}")
    
    try:
        # Windows 使用 -n, Linux/Mac 使用 -c
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '3', host]
        
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10
        )
        
        if result.returncode == 0:
            print(f"      ✅ 網路連通 (ping 成功)")
            return True
        else:
            print(f"      ❌ 網路不通 (ping 失敗)")
            return False
    except Exception as e:
        print(f"      ⚠️  無法執行 ping: {e}")
        return False

def check_port(host, port=44818):
    """檢查 EtherNet/IP 埠號是否開放"""
    print(f"\n[2/4] 檢查 EtherNet/IP 埠號...")
    print(f"      測試: {host}:{port}")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"      ✅ 埠號開放 (Port {port})")
            return True
        else:
            print(f"      ❌ 埠號未開放 (Port {port})")
            print(f"         可能原因: 設備未啟動 EtherNet/IP 服務")
            return False
    except socket.timeout:
        print(f"      ❌ 連接超時")
        return False
    except Exception as e:
        print(f"      ⚠️  檢查失敗: {e}")
        return False

def check_cip_driver():
    """檢查 pycomm3 安裝"""
    print(f"\n[3/4] 檢查 pycomm3 安裝...")
    
    try:
        from pycomm3 import CIPDriver
        print(f"      ✅ pycomm3 已安裝")
        
        # 顯示版本
        try:
            import pycomm3
            version = pycomm3.__version__
            print(f"      版本: {version}")
        except Exception:
            pass
        
        return True
    except ImportError:
        print(f"      ❌ pycomm3 未安裝")
        print(f"         請執行: pip install pycomm3")
        return False

def check_device_connection(host):
    """嘗試建立 CIP 連接"""
    print(f"\n[4/4] 測試 CIP 連接...")
    
    try:
        from pycomm3 import CIPDriver
        
        print(f"      建立連接...")
        driver = CIPDriver(host)
        
        print(f"      讀取 Identity Object...")
        response = driver.generic_message(
            service=0x01,  # Get Attributes All
            class_code=0x01,  # Identity Object
            instance=0x01,
            connected=False
        )
        
        if response and not (hasattr(response, 'error') and response.error):
            print(f"      ✅ CIP 連接成功!")
            
            # 嘗試解析 Identity 資訊
            if hasattr(response, 'value') and response.value:
                data = response.value
                if len(data) >= 4:
                    vendor_id = int.from_bytes(data[0:2], 'little')
                    device_type = int.from_bytes(data[2:4], 'little')
                    print(f"      Vendor ID: 0x{vendor_id:04X}")
                    print(f"      Device Type: 0x{device_type:04X}")
            
            driver.close()
            return True
        else:
            error = response.error if hasattr(response, 'error') else '未知錯誤'
            print(f"      ❌ CIP 連接失敗: {error}")
            driver.close()
            return False
            
    except Exception as e:
        print(f"      ❌ 連接異常: {e}")
        return False

def main():
    """主函數"""
    print("="*60)
    print("🔍 CAPAROC 連接診斷工具")
    print("="*60)
    
    # 設備 IP
    device_ip = "192.168.2.111"
    print(f"\n目標設備: {device_ip}")
    
    # 執行檢查
    results = {
        'ping': check_ping(device_ip),
        'port': check_port(device_ip),
        'driver': check_cip_driver(),
        'connection': False
    }
    
    # 只有前面都成功才測試 CIP 連接
    if results['ping'] and results['port'] and results['driver']:
        results['connection'] = check_device_connection(device_ip)
    else:
        print(f"\n[4/4] 測試 CIP 連接...")
        print(f"      ⏭️  跳過 (前置檢查未通過)")
    
    # 總結
    print("\n" + "="*60)
    print("📊 診斷結果")
    print("="*60)
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\n通過: {passed}/{total}")
    print(f"  網路連通性: {'✅' if results['ping'] else '❌'}")
    print(f"  埠號開放:   {'✅' if results['port'] else '❌'}")
    print(f"  驅動安裝:   {'✅' if results['driver'] else '❌'}")
    print(f"  CIP 連接:   {'✅' if results['connection'] else '❌'}")
    
    # 建議
    print("\n" + "="*60)
    if passed == total:
        print("✅ 所有檢查通過! 設備連接正常")
        print("\n你可以運行:")
        print("  python example_main_power_control.py")
    else:
        print("❌ 部分檢查失敗")
        print("\n💡 建議:")
        
        if not results['ping']:
            print("\n1. 網路連通性問題:")
            print("   - 檢查網路線是否插好")
            print("   - 檢查設備電源是否開啟")
            print("   - 確認 IP 位址正確: 192.168.2.111")
            print("   - 檢查電腦與設備是否在同一網段")
        
        if not results['port']:
            print("\n2. EtherNet/IP 埠號未開放:")
            print("   - 設備可能未啟動 EtherNet/IP 服務")
            print("   - 防火牆可能阻擋 Port 44818")
            print("   - 嘗試重啟設備")
        
        if not results['driver']:
            print("\n3. pycomm3 未安裝:")
            print("   執行: pip install pycomm3")
        
        if not results['connection'] and results['driver']:
            print("\n4. CIP 連接失敗:")
            print("   - 設備可能不支援 EtherNet/IP")
            print("   - EDS 檔案可能不匹配")
            print("   - 嘗試使用官方工具測試")
    
    print("="*60)

if __name__ == "__main__":
    main()
