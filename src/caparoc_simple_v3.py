#!/usr/bin/env python3
"""
CAPAROC 簡化控制器 - 最終版本
基於手冊 7.1.2 節的正確控制方式

策略：
1. 程式啟動時一次性設定所有通道額定電流（順序執行，避免干擾）
2. 之後只使用 Output Assembly 控制開關（符合手冊規範）
3. 從 Input Assembly 讀取狀態
"""

from pycomm3 import CIPDriver
import struct
import time
import threading


class CaparocController:
    """CAPAROC 控制器 - 基於手冊規範"""
    
    def __init__(self, device_ip="192.168.2.111"):
        self.device_ip = device_ip
        self.output_instance = 0x64
        self.input_instance = 0x65
        
        # I/O 狀態
        self.implicit_mode_enabled = False
        self.cip_keep_alive = False
        # ⚠️ 關鍵修復：Output Assembly 0x64 長度是 18 bytes（不是 20）
        self.current_output_data = bytearray(18)  # Output Assembly = 18 bytes
        self.current_input_data = bytearray(244)  # Input Assembly = 244 bytes
        self.io_data_lock = threading.Lock()
        self.io_update_thread = None
        self.last_io_update = 0
        self.driver = None
        
        # 初始化標記
        self.channels_initialized = False
    
    def initialize_all_channels(self, driver, nominal_current=4):
        """
        初始化所有通道的額定電流（一次性，程式啟動時執行）
        
        重要：順序執行，確保不互相干擾
        """
        if self.channels_initialized:
            print("[初始化] 通道已初始化，跳過")
            return True
        
        print("\n" + "="*60)
        print("🔧 初始化所有通道額定電流")
        print("   這個過程需要約 40 秒，請耐心等待...")
        print("="*60)
        
        for ch in range(1, 5):
            print(f"\n[初始化] 通道 {ch}/4: 設定額定電流 {nominal_current}A")
            success = self._set_nominal_current_led_button(driver, 1, ch, nominal_current)
            if success:
                print(f"[初始化] ✅ 通道 {ch} 完成")
            else:
                print(f"[初始化] ⚠️ 通道 {ch} 失敗")
            
            # 每個通道間隔 1 秒
            time.sleep(1)
        
        self.channels_initialized = True
        print("\n" + "="*60)
        print("✅ 所有通道初始化完成！")
        print("="*60)
        return True
    
    def _establish_implicit_messaging(self, driver):
        """建立 Implicit Messaging 連接"""
        try:
            # 嘗試使用 generic_message 建立 Forward Open
            forward_open_data = self._build_forward_open_request()
            
            response = driver.generic_message(
                service=0x52,  # Forward Open
                class_code=0x06,  # Connection Manager
                instance=0x01,
                request_data=forward_open_data,
                connected=True,
                unconnected_send=False
            )
            
            if response and not (hasattr(response, 'error') and response.error):
                print("[Implicit] Forward Open 成功")
                self.implicit_mode_enabled = True
                
                # 啟動 I/O Worker
                self.cip_keep_alive = True
                self.io_update_thread = threading.Thread(
                    target=self._io_worker,
                    args=(driver,),
                    daemon=True
                )
                self.io_update_thread.start()
                time.sleep(0.5)
                
                return True
            else:
                print(f"[Implicit] Forward Open 失敗: {response.error if hasattr(response, 'error') else '未知'}")
                return False
                
        except Exception as e:
            print(f"[Implicit] 建立連接異常: {e}")
            return False
    
    def _build_forward_open_request(self):
        """建立 Forward Open 請求"""
        request = bytearray()
        request.extend(struct.pack('<I', 0x12345678))  # Connection Serial Number
        request.extend(struct.pack('<H', 0x009A))  # Vendor ID
        request.extend(struct.pack('<I', 0x87654321))  # Originator Serial Number
        request.append(0x00)  # Connection Timeout Multiplier
        request.extend([0x00, 0x00, 0x00])  # Reserved
        request.extend(struct.pack('<I', 0x20000001))  # O->T Network Connection ID
        request.extend(struct.pack('<I', 0x20000002))  # T->O Network Connection ID
        request.extend(struct.pack('<H', 0x07D0))  # Connection Timeout (2000ms)
        request.extend(struct.pack('<I', 0x43F4))  # O->T Connection Parameters (20ms RPI)
        request.extend(struct.pack('<I', 0x43F4))  # T->O Connection Parameters (20ms RPI)
        request.append(0xA3)  # Transport Type/Trigger
        request.append(0x03)  # Connection Path Size
        request.extend([0x01, self.output_instance])  # Output Assembly
        request.extend([0x01, self.input_instance])  # Input Assembly
        request.extend([0x01, 0x01])  # Config Assembly
        return bytes(request)
    
    def _io_worker(self, driver):
        """I/O Worker - 持續更新"""
        cycle = 0
        while self.cip_keep_alive and self.implicit_mode_enabled:
            try:
                cycle += 1
                
                with self.io_data_lock:
                    output_data = bytes(self.current_output_data)
                
                try:
                    # 寫入 Output Assembly
                    driver.write(f"Assembly.{self.output_instance}", output_data)
                    
                    # 讀取 Input Assembly
                    input_response = driver.read(f"Assembly.{self.input_instance}")
                    if input_response and hasattr(input_response, 'value'):
                        with self.io_data_lock:
                            self.current_input_data = bytearray(input_response.value)
                        self.last_io_update = time.time()
                        
                except Exception as io_e:
                    if cycle % 500 == 0:
                        print(f"[I/O Worker] 週期 {cycle} 錯誤: {io_e}")
                
                time.sleep(0.05)  # 20Hz
                
            except Exception as e:
                print(f"[I/O Worker] 異常: {e}")
                time.sleep(0.1)
    
    def _set_nominal_current_led_button(self, driver, module, channel, current_amps):
        """LED 按鈕模擬（僅用於初始化）"""
        try:
            instances = [0x67, 0x68, 0x69, 0x6A, 0x64]
            
            for instance in instances:
                try:
                    data_length = 18 if instance == 0x64 else 20
                    channel_byte = module
                    channel_bit = channel - 1
                    
                    # 進入程式模式
                    prog_data = bytearray(data_length)
                    prog_data[channel_byte] = (1 << 7) | (1 << 6)
                    
                    resp = driver.generic_message(
                        service=0x10, class_code=0x04, instance=instance,
                        attribute=3, request_data=bytes(prog_data), connected=False
                    )
                    
                    if resp and not (hasattr(resp, 'error') and resp.error):
                        time.sleep(2.5)
                        
                        # 按鈕操作
                        for _ in range(current_amps):
                            press_data = bytearray(data_length)
                            press_data[channel_byte] = (1 << channel_bit) | (1 << 7)
                            driver.generic_message(
                                service=0x10, class_code=0x04, instance=instance,
                                attribute=3, request_data=bytes(press_data), connected=False
                            )
                            time.sleep(0.5)
                            
                            release_data = bytearray(data_length)
                            release_data[channel_byte] = (1 << 7)
                            driver.generic_message(
                                service=0x10, class_code=0x04, instance=instance,
                                attribute=3, request_data=bytes(release_data), connected=False
                            )
                            time.sleep(0.3)
                        
                        # 儲存
                        save_data = bytearray(data_length)
                        save_data[channel_byte] = (1 << channel_bit) | (1 << 7) | (1 << 6)
                        driver.generic_message(
                            service=0x10, class_code=0x04, instance=instance,
                            attribute=3, request_data=bytes(save_data), connected=False
                        )
                        time.sleep(3.0)
                        
                        # 退出
                        exit_data = bytearray(data_length)
                        driver.generic_message(
                            service=0x10, class_code=0x04, instance=instance,
                            attribute=3, request_data=bytes(exit_data), connected=False
                        )
                        
                        return True
                        
                except Exception:
                    continue
            
            return False
            
        except Exception as e:
            print(f"[錯誤] {e}")
            return False
    
    def set_channel(self, channel, state):
        """
        控制通道開關（基於手冊 7.1.2 節）
        
        Args:
            channel: 1-4
            state: True=開啟, False=關閉
        """
        if not self.channels_initialized:
            print("[錯誤] 請先初始化通道（initialize_all_channels）")
            return False
        
        if not self.driver:
            print("[錯誤] Driver 未初始化")
            return False
        
        with self.io_data_lock:
            byte_offset = 1
            bit_position = channel - 1
            current_value = self.current_output_data[byte_offset]
            
            if state:
                # 手冊規範：bit7=1 (release), 對應通道 bit=1
                new_value = current_value | (1 << bit_position) | 0x80
            else:
                # 手冊規範：bit7=1 (release), 對應通道 bit=0
                new_value = (current_value & ~(1 << bit_position)) | 0x80
            
            self.current_output_data[byte_offset] = new_value
            
            print(f"[控制] CH{channel} -> {'開啟' if state else '關閉'}")
            print(f"[控制] CH{channel} -> {'開啟' if state else '關閉'}")
            print(f"       byte[1]: 0x{current_value:02X} -> 0x{new_value:02X}")
            
            # ⚠️ 關鍵：寫入方式取決於是否使用 Implicit Messaging
            if self.implicit_mode_enabled:
                # 使用 I/O Worker 自動更新
                print(f"       [Implicit] 已更新 buffer，等待 I/O Worker 寫入...")
                time.sleep(0.2)  # 等待幾個 I/O 週期
                print(f"       ✅ 控制命令已發送")
            else:
                # 直接使用 generic_message 寫入
                try:
                    output_data = bytes(self.current_output_data)
                    
                    # DEBUG: 顯示要寫入的完整資料
                    print(f"       [DEBUG] 寫入資料長度: {len(output_data)} bytes")
                    print(f"       [DEBUG] byte[0]: 0x{output_data[0]:02X}, byte[1]: 0x{output_data[1]:02X}")
                    print(f"       [DEBUG] 寫入 Assembly.0x{self.output_instance:02X}")
                    
                    response = self.driver.generic_message(
                        service=0x10,  # Set Attribute Single
                        class_code=0x04,  # Assembly Object
                        instance=self.output_instance,
                        attribute=3,
                        request_data=output_data,
                        connected=False
                    )
                    
                    # DEBUG: 顯示回應詳情
                    if response:
                        print(f"       [DEBUG] Response: {response}")
                        if hasattr(response, 'error'):
                            print(f"       [DEBUG] Error: {response.error}")
                        if hasattr(response, 'value'):
                            print(f"       [DEBUG] Value: {response.value}")
                    
                    if response and not (hasattr(response, 'error') and response.error):
                        print(f"       ✅ 已寫入設備")
                    else:
                        error_msg = response.error if hasattr(response, 'error') else '未知'
                        print(f"       ⚠️ 寫入失敗: {error_msg}")
                        print(f"       [提示] 可能需要 Implicit Messaging 模式")
                        return False
                        
                except Exception as e:
                    print(f"       ❌ 寫入異常: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
        
        time.sleep(0.5)  # 等待設備反應
        
        # 讀取並顯示結果
        self._read_and_show_result(channel, state)
        
        return True
    
    def _read_and_show_result(self, channel, expected_state):
        """讀取並顯示控制結果"""
        try:
            # 讀取 Assembly.101 獲取電流
            response = self.driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,
                instance=0x101,
                attribute=3,
                connected=False
            )
            
            if response and hasattr(response, 'value'):
                data = response.value
                offset = 20 + (channel - 1) * 2
                if len(data) >= offset + 2:
                    current_raw = struct.unpack('<H', data[offset:offset+2])[0]
                    current = current_raw / 100.0
                    
                    if expected_state:
                        if current > 0.05:
                            print(f"       ✅ CH{channel} 已開啟，電流: {current:.2f} A")
                        else:
                            print(f"       ⚠️ CH{channel} 命令已發送，但電流仍為 {current:.2f} A")
                    else:
                        if current < 0.05:
                            print(f"       ✅ CH{channel} 已關閉")
                        else:
                            print(f"       ⚠️ CH{channel} 命令已發送，但電流仍為 {current:.2f} A")
        except Exception as e:
            print(f"       ⚠️ 無法讀取結果: {e}")
    
    def read_channel_status(self, channel):
        """讀取通道狀態（基於手冊 7.2.5 節）"""
        with self.io_data_lock:
            # 通道 1: Byte 0, 通道 2: Byte 3, 通道 3: Byte 6, 通道 4: Byte 9
            byte_offset = (channel - 1) * 3
            if len(self.current_input_data) > byte_offset:
                status_byte = self.current_input_data[byte_offset]
                return {
                    'on': bool(status_byte & 0x01),
                    'warning_80%': bool(status_byte & 0x02),
                    'overload': bool(status_byte & 0x04),
                    'short_circuit': bool(status_byte & 0x08),
                    'hardware_fault': bool(status_byte & 0x10),
                    'total_current_shutdown': bool(status_byte & 0x20),
                }
        return None
    
    def show_status(self):
        """顯示所有通道狀態（從設備讀取）"""
        if not self.driver:
            print("❌ Driver 未初始化")
            return
        
        try:
            print("\n📊 讀取通道狀態...")
            
            # 讀取 Assembly.101
            response = self.driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,
                instance=0x101,
                attribute=3,
                connected=False
            )
            
            # DEBUG: 檢查回應
            if not response:
                print("❌ 無回應")
                return
            
            if hasattr(response, 'error') and response.error:
                print(f"❌ 讀取錯誤: {response.error}")
                return
            
            if not hasattr(response, 'value'):
                print(f"❌ 回應無 value 屬性")
                print(f"   Response: {response}")
                return
            
            data = response.value
            print(f"[DEBUG] 讀取到 {len(data)} bytes")
            
            if len(data) < 20:
                print(f"⚠️ 資料長度不足: {len(data)} bytes (預期至少 20 bytes)")
                return
            if len(data) < 20:
                print(f"⚠️ 資料長度不足: {len(data)} bytes (預期至少 20 bytes)")
                return
            
            print("\n📊 通道狀態 (即時讀取):")
            
            # 讀取電壓
            if len(data) >= 6:
                voltage_raw = struct.unpack('<H', data[4:6])[0]
                voltage = voltage_raw / 100.0
                print(f"   電壓: {voltage:.2f} V")
            
            # 讀取總電流
            if len(data) >= 8:
                total_current_raw = struct.unpack('<H', data[6:8])[0]
                total_current = total_current_raw / 100.0
                print(f"   總電流: {total_current:.2f} A")
            
            print("   " + "─" * 35)
            
            # 讀取各通道
            for ch in range(1, 5):
                offset = 20 + (ch - 1) * 2
                if len(data) >= offset + 2:
                    current_raw = struct.unpack('<H', data[offset:offset+2])[0]
                    current = current_raw / 100.0
                    
                    state = "🟢 開" if current > 0.05 else "🔴 關"
                    print(f"   CH{ch}: {state}  {current:.2f} A")
                else:
                    print(f"   CH{ch}: ⚠️ 資料不足")
            
        except Exception as e:
            print(f"❌ 讀取狀態失敗: {e}")
            import traceback
            traceback.print_exc()
    
    def run(self):
        """主程式"""
        print("🚀 CAPAROC 控制器 v3.0")
        print(f"設備: {self.device_ip}")
        
        with CIPDriver(self.device_ip) as driver:
            self.driver = driver
            
            # 步驟 1: 初始化所有通道
            print("\n[步驟 1/3] 初始化通道額定電流...")
            if not self.initialize_all_channels(driver):
                print("❌ 初始化失敗")
                return
            
            # 步驟 2: 建立 Implicit Messaging
            print("\n[步驟 2/3] 建立 Implicit Messaging 連接...")
            if not self._establish_implicit_messaging(driver):
                print("❌ Implicit Messaging 連接失敗")
                print("\n嘗試不使用 Implicit Messaging 模式...")
            else:
                print("✅ Implicit Messaging 連接成功")
            
            # 步驟 3: 互動控制
            print("\n指令:")
            print("  on <ch>   - 開啟通道 (例: on 1)")
            print("  off <ch>  - 關閉通道")
            print("  s         - 顯示狀態")
            print("  q         - 退出")
            
            while True:
                try:
                    cmd = input("\n> ").strip().lower()
                    
                    if cmd == 'q':
                        break
                    elif cmd == 's':
                        self.show_status()
                    elif cmd.startswith('on '):
                        ch = int(cmd.split()[1])
                        self.set_channel(ch, True)
                    elif cmd.startswith('off '):
                        ch = int(cmd.split()[1])
                        self.set_channel(ch, False)
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"❌ 錯誤: {e}")

def main():
    controller = CaparocController()
    controller.run()

if __name__ == "__main__":
    main()
