#!/usr/bin/env python3
"""
CAPAROC Byte 值測試程式
系統性測試不同的 byte[1] 值對設備的影響

目的：
1. 了解每個 bit 的作用
2. 找出正確的控制方式
3. 避免盲目猜測
"""

from pycomm3 import CIPDriver
import time
import struct

class ByteValueTester:
    """Byte 值測試器"""
    
    def __init__(self, device_ip="192.168.2.111"):
        self.device_ip = device_ip
        self.output_instance = 0x64
        self.input_instance = 0x65
    
    def write_byte1_value(self, driver, value, description=""):
        """
        向 Assembly.0x64 寫入指定的 byte[1] 值
        
        Args:
            driver: CIPDriver 實例
            value: byte[1] 的值 (0x00-0xFF)
            description: 這個值的描述
        """
        print(f"\n{'='*60}")
        print(f"測試: byte[1] = 0x{value:02X} (binary: {value:08b})")
        if description:
            print(f"說明: {description}")
        print(f"{'='*60}")
        
        # 創建 18 byte 的資料 (Assembly.0x64 的長度)
        data = bytearray(18)
        data[1] = value
        
        try:
            # 使用 generic_message 寫入
            response = driver.generic_message(
                service=0x10,  # Set Attribute Single
                class_code=0x04,  # Assembly Object
                instance=self.output_instance,
                attribute=3,
                request_data=bytes(data),
                connected=False
            )
            
            if response and not (hasattr(response, 'error') and response.error):
                print("✅ 寫入成功")
            else:
                print(f"⚠️ 寫入失敗: {response.error if hasattr(response, 'error') else '未知錯誤'}")
            
        except Exception as e:
            print(f"❌ 寫入異常: {e}")
    
    def read_channel_status(self, driver):
        """讀取所有通道的電流狀態"""
        try:
            # 讀取 Assembly.101
            response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,  # Assembly Object
                instance=0x101,
                attribute=3,
                connected=False
            )
            
            if response and hasattr(response, 'value'):
                data = response.value
                
                # 讀取電壓
                if len(data) >= 6:
                    voltage_raw = struct.unpack('<H', data[4:6])[0]
                    voltage = voltage_raw / 100.0
                    print(f"   電壓: {voltage:.2f} V")
                
                # 讀取各通道電流
                print(f"   通道電流:")
                for ch in range(1, 5):
                    offset = 20 + (ch - 1) * 2
                    if len(data) >= offset + 2:
                        current_raw = struct.unpack('<H', data[offset:offset+2])[0]
                        current = current_raw / 100.0
                        status = "🟢 開啟" if current > 0.05 else "🔴 關閉"
                        print(f"      CH{ch}: {current:.2f} A  {status}")
                
                return True
            else:
                print("⚠️ 無法讀取狀態")
                return False
                
        except Exception as e:
            print(f"❌ 讀取異常: {e}")
            return False
    
    def test_individual_bits(self, driver):
        """測試單獨的 bit 0-7"""
        print("\n" + "="*70)
        print("📊 測試 1: 單獨的 Bit 測試 (bit0-bit7)")
        print("="*70)
        
        test_cases = [
            (0x00, "全部為 0 (基準)"),
            (0x01, "bit0 = 1 (CH1?)"),
            (0x02, "bit1 = 1 (CH2?)"),
            (0x04, "bit2 = 1 (CH3?)"),
            (0x08, "bit3 = 1 (CH4?)"),
            (0x10, "bit4 = 1"),
            (0x20, "bit5 = 1"),
            (0x40, "bit6 = 1 (程式模式?)"),
            (0x80, "bit7 = 1 (啟用位元?)"),
        ]
        
        for value, desc in test_cases:
            self.write_byte1_value(driver, value, desc)
            time.sleep(1)  # 等待設備反應
            self.read_channel_status(driver)
            
            input("\n按 Enter 繼續下一個測試...")
    
    def test_bit7_combinations(self, driver):
        """測試 bit7 + 通道組合"""
        print("\n" + "="*70)
        print("📊 測試 2: bit7 + 通道 Bit 組合")
        print("="*70)
        
        test_cases = [
            (0x80, "bit7=1, 所有通道=0 (基準)"),
            (0x81, "bit7=1 + bit0=1 (CH1 開啟?)"),
            (0x82, "bit7=1 + bit1=1 (CH2 開啟?)"),
            (0x83, "bit7=1 + bit0=1 + bit1=1 (CH1+CH2 開啟?)"),
            (0x84, "bit7=1 + bit2=1 (CH3 開啟?)"),
            (0x88, "bit7=1 + bit3=1 (CH4 開啟?)"),
            (0x8F, "bit7=1 + 所有通道=1 (全部開啟?)"),
        ]
        
        for value, desc in test_cases:
            self.write_byte1_value(driver, value, desc)
            time.sleep(1)
            self.read_channel_status(driver)
            
            input("\n按 Enter 繼續下一個測試...")
    
    def test_program_mode(self, driver):
        """測試程式模式相關的值"""
        print("\n" + "="*70)
        print("📊 測試 3: 程式模式相關")
        print("="*70)
        
        test_cases = [
            (0xC0, "bit7=1 + bit6=1 (進入程式模式?)"),
            (0xC1, "程式模式 + CH1"),
            (0xC2, "程式模式 + CH2"),
            (0xC3, "程式模式 + CH1+CH2"),
        ]
        
        for value, desc in test_cases:
            self.write_byte1_value(driver, value, desc)
            time.sleep(2)  # 程式模式可能需要更長時間
            self.read_channel_status(driver)
            
            input("\n按 Enter 繼續下一個測試...")
    
    def test_sequence(self, driver):
        """測試開啟/關閉序列"""
        print("\n" + "="*70)
        print("📊 測試 4: 開啟/關閉序列")
        print("="*70)
        
        print("\n[序列] 測試 CH1 開啟 → 關閉")
        
        # 開啟 CH1
        self.write_byte1_value(driver, 0x81, "開啟 CH1")
        time.sleep(1)
        self.read_channel_status(driver)
        input("\n按 Enter 繼續...")
        
        # 關閉 CH1
        self.write_byte1_value(driver, 0x80, "關閉 CH1 (只保留 bit7)")
        time.sleep(1)
        self.read_channel_status(driver)
        input("\n按 Enter 繼續...")
        
        print("\n[序列] 測試 CH1+CH2 同時開啟")
        
        # 開啟 CH1+CH2
        self.write_byte1_value(driver, 0x83, "開啟 CH1+CH2")
        time.sleep(1)
        self.read_channel_status(driver)
        input("\n按 Enter 繼續...")
        
        # 只關閉 CH1
        self.write_byte1_value(driver, 0x82, "關閉 CH1，保留 CH2")
        time.sleep(1)
        self.read_channel_status(driver)
        input("\n按 Enter 繼續...")
        
        # 全部關閉
        self.write_byte1_value(driver, 0x80, "全部關閉")
        time.sleep(1)
        self.read_channel_status(driver)
    
    def run_all_tests(self):
        """執行所有測試"""
        print("🚀 CAPAROC Byte 值系統測試")
        print(f"設備: {self.device_ip}")
        print("="*70)
        
        with CIPDriver(self.device_ip) as driver:
            try:
                print("\n初始狀態:")
                self.read_channel_status(driver)
                
                print("\n\n選擇測試:")
                print("1. 單獨 Bit 測試 (bit0-bit7)")
                print("2. bit7 + 通道組合")
                print("3. 程式模式測試")
                print("4. 開啟/關閉序列")
                print("5. 執行所有測試")
                
                choice = input("\n請選擇 (1-5): ").strip()
                
                if choice == '1':
                    self.test_individual_bits(driver)
                elif choice == '2':
                    self.test_bit7_combinations(driver)
                elif choice == '3':
                    self.test_program_mode(driver)
                elif choice == '4':
                    self.test_sequence(driver)
                elif choice == '5':
                    self.test_individual_bits(driver)
                    self.test_bit7_combinations(driver)
                    self.test_program_mode(driver)
                    self.test_sequence(driver)
                else:
                    print("無效的選擇")
                
                print("\n" + "="*70)
                print("✅ 測試完成")
                print("="*70)
                
            except KeyboardInterrupt:
                print("\n\n⚠️ 測試中斷")
            except Exception as e:
                print(f"\n\n❌ 測試失敗: {e}")

def main():
    tester = ByteValueTester()
    tester.run_all_tests()

if __name__ == "__main__":
    main()
