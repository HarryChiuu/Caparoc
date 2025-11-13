"""
CAPAROC 診斷工具集
=================

此程式包含所有診斷和測試工具，用於深入分析 CAPAROC 設備的通訊問題。

診斷工具包括：
1. scan_assemblies() - 掃描所有 Assembly Instance
2. show_channel_limits() - 顯示通道配置限制
3. compare_assemblies() - 對比 Input/Output/Config Assembly
4. test_config_write_methods() - 測試各種 Config 寫入方法
5. diagnose_config_assembly_write() - 診斷 Config Assembly 寫入問題
6. test_led_button_method() - 測試 LED 按鈕模擬方法

使用方式:
    python tests/diagnostic_tools.py

作者: Harry
日期: 2025-11-13
"""

import sys
import os
import time
import struct

# 添加 src 目錄到 Python 路徑
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pycomm3 import CIPDriver


class CaparocDiagnostics:
    """CAPAROC 診斷工具類"""
    
    def __init__(self, device_ip="192.168.2.111"):
        self.device_ip = device_ip
        self.driver = None
        
        # Assembly 設定 (根據 EDS)
        self.output_instance = 0x64  # Output Assembly (20 bytes)
        self.input_instance = 0x65   # Input Assembly (208 bytes)
        self.config_instance = 0x66  # Config Assembly (244 bytes)
        
        # 多模組支援
        self.module_count = 1
        self.channels_per_module = 4
    
    def connect(self):
        """連接到 CAPAROC 設備"""
        print(f"\n正在連接到 {self.device_ip}...")
        try:
            self.driver = CIPDriver(self.device_ip)
            print(f"✅ 連接成功！\n")
            return True
        except Exception as e:
            print(f"❌ 連接失敗: {e}\n")
            return False
    
    def disconnect(self):
        """斷開連接"""
        if self.driver:
            self.driver.close()
            print("\n已斷開連接")
    
    def get_channel_offset(self, module, channel):
        """計算通道在 Input Assembly 中的起始位置"""
        base_offset = 6
        module_offset = (module - 1) * 4 * 13
        channel_offset = (channel - 1) * 13
        return base_offset + module_offset + channel_offset
    
    def _read_config_assembly(self):
        """讀取 Config Assembly 完整內容"""
        try:
            response = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.config_instance,
                attribute=3,
                connected=False
            )
            
            if response and hasattr(response, 'value'):
                return response.value
            return None
            
        except Exception as e:
            print(f"   ❌ 讀取異常: {e}")
            return None
    
    # ========== 診斷工具 1: 掃描 Assembly ==========
    def scan_assemblies(self):
        """掃描所有可能的 Assembly Instance"""
        print("\n" + "="*60)
        print("🔍 Assembly Instance 掃描")
        print("="*60)
        
        print("\n已知 Assembly:")
        print(f"  Output Assembly: 0x{self.output_instance:02X} (0x64)")
        print(f"  Input Assembly:  0x{self.input_instance:02X} (0x65)")
        print(f"  Config Assembly: 0x{self.config_instance:02X} (0x66)")
        
        print("\n掃描 Assembly Instance 0x60 - 0x70...")
        
        for instance in range(0x60, 0x71):
            try:
                response = self.driver.generic_message(
                    service=0x0E,
                    class_code=0x04,
                    instance=instance,
                    attribute=3,
                    connected=False
                )
                
                if response and hasattr(response, 'value') and response.value:
                    data = response.value
                    is_all_zero = all(b == 0 for b in data)
                    has_nominal = any(b in [3, 4] for b in data)
                    
                    status = "可用"
                    if instance == self.output_instance:
                        status = "✅ Output"
                    elif instance == self.input_instance:
                        status = "✅ Input"
                    elif instance == self.config_instance:
                        status = "⚙️  Config?"
                    elif is_all_zero:
                        status = "空白資料"
                    elif has_nominal:
                        status = "⚠️  疑似配置資料!"
                    
                    print(f"  0x{instance:02X}: 長度 {len(data):3d} bytes - {status}")
                    
                    if has_nominal and instance != self.input_instance:
                        print(f"       前 20 bytes: {data[:20].hex()}")
                
            except Exception:
                pass
        
        print("="*60)
    
    # ========== 診斷工具 2: 顯示通道限制 ==========
    def show_channel_limits(self):
        """顯示所有通道的配置限制"""
        print("\n" + "="*60)
        print("📊 通道配置診斷 (Config Assembly)")
        print("="*60)
        
        config_data = self._read_config_assembly()
        
        if config_data:
            print(f"\n✅ 成功讀取 Config Assembly ({len(config_data)} bytes)")
            print(f"\n前 32 bytes (Hex):")
            print(f"  {config_data[:32].hex()}")
            
            print(f"\n全域參數 (Param 1-5):")
            print(f"  Param1 (Global nominal current lock): {config_data[0]}")
            print(f"  Param2 (Global user interface lock):  {config_data[1]}")
            param3 = struct.unpack('<H', config_data[2:4])[0]
            print(f"  Param3 (Global switch-on delay):      {param3}")
            print(f"  Param4 (Global operating mode):       {config_data[4]}")
            print(f"  Param5 (Reserved):                    {config_data[5]}")
            
            print(f"\n通道參數 (Param 6+):")
            for module in range(1, self.module_count + 1):
                if self.module_count > 1:
                    print(f"\n  模組 {module}:")
                
                for ch in range(1, self.channels_per_module + 1):
                    param_base = 6 + (module - 1) * 12 + (ch - 1) * 3
                    nominal = config_data[param_base]
                    lock = config_data[param_base + 1]
                    status = config_data[param_base + 2]
                    
                    if self.module_count > 1:
                        print(f"    M{module}.CH{ch}: nominal={nominal}A, lock={lock}, status={status}")
                    else:
                        print(f"    CH{ch}: nominal={nominal}A, lock={lock}, status={status}")
        else:
            print("\n❌ 無法讀取 Config Assembly")
            print("   可能原因:")
            print("   1. Instance 0x66 不正確")
            print("   2. Config Assembly 不存在")
            print("   3. 通訊問題")
        
        print("="*60)
    
    # ========== 診斷工具 3: 對比 Assembly ==========
    def compare_assemblies(self):
        """對照比較 Input, Output, Config Assembly"""
        print("\n" + "="*70)
        print("🔬 Assembly 結構對照診斷")
        print("="*70)
        
        results = {
            'input': None,
            'output': None,
            'config': None,
            'output_writable': False,
            'config_writable': False
        }
        
        # 讀取 Input Assembly
        print("\n📥 [1/5] 讀取 Input Assembly (0x65)...")
        try:
            input_resp = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=0x65,
                attribute=3,
                connected=False
            )
            if input_resp and hasattr(input_resp, 'value'):
                results['input'] = input_resp.value
                print(f"  ✅ 成功讀取: {len(results['input'])} bytes")
            else:
                print(f"  ❌ 讀取失敗")
        except Exception as e:
            print(f"  ❌ 異常: {e}")
        
        # 讀取 Output Assembly
        print("\n📤 [2/5] 讀取 Output Assembly (0x64)...")
        try:
            output_resp = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=0x64,
                attribute=3,
                connected=False
            )
            if output_resp and hasattr(output_resp, 'value'):
                results['output'] = output_resp.value
                print(f"  ✅ 成功讀取: {len(results['output'])} bytes")
            else:
                print(f"  ❌ 讀取失敗")
        except Exception as e:
            print(f"  ❌ 異常: {e}")
        
        # 讀取 Config Assembly
        print("\n⚙️  [3/5] 讀取 Config Assembly (0x66)...")
        try:
            config_resp = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=0x66,
                attribute=3,
                connected=False
            )
            if config_resp and hasattr(config_resp, 'value'):
                results['config'] = config_resp.value
                print(f"  ✅ 成功讀取: {len(results['config'])} bytes")
            else:
                print(f"  ❌ 讀取失敗")
        except Exception as e:
            print(f"  ❌ 異常: {e}")
        
        # 測試 Output Assembly 寫入
        print("\n🧪 [4/5] 測試 Output Assembly (0x64) 寫入...")
        if results['output']:
            try:
                test_data = bytearray(results['output'])
                write_resp = self.driver.generic_message(
                    service=0x10,
                    class_code=0x04,
                    instance=0x64,
                    attribute=3,
                    request_data=bytes(test_data),
                    connected=False
                )
                
                if write_resp and not (hasattr(write_resp, 'error') and write_resp.error):
                    results['output_writable'] = True
                    print(f"  ✅ 寫入成功")
                else:
                    error_msg = write_resp.error if hasattr(write_resp, 'error') else "Unknown"
                    print(f"  ❌ 寫入失敗: {error_msg}")
            except Exception as e:
                print(f"  ❌ 異常: {e}")
        else:
            print(f"  ⏭️  跳過 (Output Assembly 讀取失敗)")
        
        # 測試 Config Assembly 寫入
        print("\n🧪 [5/5] 測試 Config Assembly (0x66) 寫入...")
        if results['config']:
            try:
                test_data = bytearray(results['config'])
                write_resp = self.driver.generic_message(
                    service=0x10,
                    class_code=0x04,
                    instance=0x66,
                    attribute=3,
                    request_data=bytes(test_data),
                    connected=False
                )
                
                if write_resp and not (hasattr(write_resp, 'error') and write_resp.error):
                    results['config_writable'] = True
                    print(f"  ✅ 寫入成功")
                else:
                    error_msg = write_resp.error if hasattr(write_resp, 'error') else "Unknown"
                    print(f"  ❌ 寫入失敗: {error_msg}")
            except Exception as e:
                print(f"  ❌ 異常: {e}")
        else:
            print(f"  ⏭️  跳過 (Config Assembly 讀取失敗)")
        
        # 分析結果
        print("\n" + "="*70)
        print("📊 分析結果")
        print("="*70)
        
        print("\n🔍 Assembly 大小比較:")
        print(f"  Input Assembly (0x65):  {len(results['input']) if results['input'] else 'N/A':>3} bytes {'✅' if results['input'] else '❌'}")
        print(f"  Output Assembly (0x64): {len(results['output']) if results['output'] else 'N/A':>3} bytes {'✅' if results['output'] else '❌'}")
        print(f"  Config Assembly (0x66): {len(results['config']) if results['config'] else 'N/A':>3} bytes {'✅' if results['config'] else '❌'}")
        
        print("\n🔍 寫入功能測試:")
        print(f"  Output Assembly (0x64): {'✅ 可寫入' if results['output_writable'] else '❌ 無法寫入'}")
        print(f"  Config Assembly (0x66): {'✅ 可寫入' if results['config_writable'] else '❌ 無法寫入'}")
        
        print("\n💡 診斷結論:")
        if not results['config_writable']:
            print("  ❌ Config Assembly (0x66) 無法寫入")
            print("  ✅ 建議使用 Parameter Object (Class 0x0F) 方法")
        else:
            print("  ✅ Config Assembly 可寫入")
        
        print("="*70)
        
        return results
    
    # ========== 診斷工具 4: 測試 Config 寫入方法 ==========
    def test_config_write_methods(self):
        """測試 Config Assembly 的各種寫入方法"""
        print("\n" + "="*70)
        print("🧪 Config Assembly 寫入方法測試")
        print("="*70)
        
        results = {}
        
        # 先讀取當前 Config Assembly
        print("\n📖 讀取當前 Config Assembly...")
        config_data = self._read_config_assembly()
        
        if not config_data:
            print("  ❌ 無法讀取 Config Assembly，終止測試")
            return results
        
        print(f"  ✅ 讀取成功: {len(config_data)} bytes")
        
        # 測試 1: 標準方法 (完整 244 bytes)
        print("\n🧪 [測試 1] Service 0x10, Attribute 3, 完整 244 bytes")
        try:
            resp = self.driver.generic_message(
                service=0x10,
                class_code=0x04,
                instance=0x66,
                attribute=3,
                request_data=bytes(config_data),
                connected=False
            )
            if resp and not (hasattr(resp, 'error') and resp.error):
                results['full_244'] = 'Success'
                print(f"  ✅ 成功")
            else:
                error = resp.error if hasattr(resp, 'error') else "Unknown"
                results['full_244'] = error
                print(f"  ❌ 失敗: {error}")
        except Exception as e:
            results['full_244'] = str(e)
            print(f"  ❌ 異常: {e}")
        
        # 測試 2: 部分資料
        print("\n🧪 [測試 2] Service 0x10, Attribute 3, 前 32 bytes")
        try:
            resp = self.driver.generic_message(
                service=0x10,
                class_code=0x04,
                instance=0x66,
                attribute=3,
                request_data=bytes(config_data[:32]),
                connected=False
            )
            if resp and not (hasattr(resp, 'error') and resp.error):
                results['partial_32'] = 'Success'
                print(f"  ✅ 成功")
            else:
                error = resp.error if hasattr(resp, 'error') else "Unknown"
                results['partial_32'] = error
                print(f"  ❌ 失敗: {error}")
        except Exception as e:
            results['partial_32'] = str(e)
            print(f"  ❌ 異常: {e}")
        
        # 結果摘要
        print("\n" + "="*70)
        print("📊 測試結果摘要")
        print("="*70)
        
        for test, result in results.items():
            status = "✅" if result == 'Success' else "❌"
            print(f"  {test}: {status} {result}")
        
        if all(r != 'Success' for r in results.values()):
            print("\n💡 所有測試都失敗 - Config Assembly 可能在運行時唯讀")
            print("   建議使用 Parameter Object (Class 0x0F) 方法")
        
        print("="*70)
        
        return results
    
    # ========== 診斷工具 5: 診斷 Param3 值 ==========
    def diagnose_config_assembly_write(self, test_values=None):
        """診斷 Config Assembly 寫入問題"""
        if test_values is None:
            test_values = [0, 10000, 65535]
        
        print("\n" + "="*70)
        print("🔬 Config Assembly 寫入診斷測試")
        print("="*70)
        print(f"測試目標: 找出 Param3 的正確「No Change」值")
        print(f"測試值: {test_values}")
        print("="*70)
        
        results = {}
        
        for delay_value in test_values:
            print(f"\n🧪 測試 Param3 = {delay_value} (0x{delay_value:04X})")
            print("-" * 70)
            
            # 建立測試緩衝區
            config_buffer = bytearray(244)
            config_buffer[0] = 0  # Param1: Unlocked
            config_buffer[1] = 0  # Param2: Unlocked
            config_buffer[2:4] = struct.pack('<H', delay_value)  # Param3
            config_buffer[4] = 2  # Param4
            config_buffer[5] = 2  # Param5
            
            # 填充通道參數
            offset = 6
            for _ in range(64):
                config_buffer[offset] = 0      # nominal
                config_buffer[offset + 1] = 2  # lock
                config_buffer[offset + 2] = 2  # status
                offset += 3
            
            # 填充剩餘
            for i in range(offset, 244):
                config_buffer[i] = 2
            
            print(f"  前 16 bytes: {config_buffer[:16].hex()}")
            
            # 嘗試寫入
            try:
                write_response = self.driver.generic_message(
                    service=0x10,
                    class_code=0x04,
                    instance=0x66,
                    attribute=3,
                    request_data=bytes(config_buffer),
                    connected=False
                )
                
                if write_response and not (hasattr(write_response, 'error') and write_response.error):
                    results[delay_value] = {'success': True, 'error': None}
                    print(f"  ✅ 寫入成功")
                else:
                    error = write_response.error if hasattr(write_response, 'error') else "Unknown"
                    results[delay_value] = {'success': False, 'error': error}
                    print(f"  ❌ 寫入失敗: {error}")
            except Exception as e:
                results[delay_value] = {'success': False, 'error': str(e)}
                print(f"  ❌ 異常: {e}")
        
        # 結果摘要
        print("\n" + "="*70)
        print("📊 測試結果摘要")
        print("="*70)
        
        for value, result in results.items():
            status = "✅ 成功" if result['success'] else "❌ 失敗"
            print(f"  Param3 = {value:5d} (0x{value:04X}): {status}")
            if not result['success']:
                print(f"    錯誤: {result['error']}")
        
        print("="*70)
        
        return results
    
    # ========== 主選單 ==========
    def run(self):
        """執行診斷工具主選單"""
        if not self.connect():
            return
        
        while True:
            print("\n" + "="*60)
            print("CAPAROC 診斷工具選單")
            print("="*60)
            print("\n1. 掃描 Assembly Instance")
            print("2. 顯示通道配置限制")
            print("3. 對比 Assembly 結構")
            print("4. 測試 Config 寫入方法")
            print("5. 診斷 Config Assembly 寫入")
            print("\nq. 退出")
            print("="*60)
            
            try:
                choice = input("\n請選擇: ").strip().lower()
                
                if choice == 'q':
                    break
                elif choice == '1':
                    self.scan_assemblies()
                elif choice == '2':
                    self.show_channel_limits()
                elif choice == '3':
                    self.compare_assemblies()
                elif choice == '4':
                    self.test_config_write_methods()
                elif choice == '5':
                    self.diagnose_config_assembly_write()
                else:
                    print("⚠️  無效選擇")
                    
            except KeyboardInterrupt:
                print("\n\n中斷執行")
                break
            except Exception as e:
                print(f"\n❌ 錯誤: {e}")
        
        self.disconnect()


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║          CAPAROC 診斷工具集 v1.0                         ║
    ║                                                          ║
    ║  此工具用於診斷 CAPAROC 設備的通訊和配置問題             ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    # 檢查命令列參數
    device_ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.2.111"
    
    diagnostics = CaparocDiagnostics(device_ip=device_ip)
    diagnostics.run()
