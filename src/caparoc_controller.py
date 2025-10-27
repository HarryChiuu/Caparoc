#!/usr/bin/env python3
"""
CAPAROC 控制器 (Production Version)
基於手冊 7.1.2 節的正確控制方式

功能狀態:
✅ 已實作:
  - 多通道獨立控制 (on/off)
  - 即時狀態讀取 (電壓、電流)
  - 通道額定電流初始化
  - 互動式電流值設定 (Phase 1 完成)
  - Implicit Messaging 自動檢測

⚠️ 待實作:
  1. 全域狀態監測 (持續背景監控異常狀態)
  2. GUI 規劃設計 (圖形化控制介面)

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
    """CAPAROC  - 基於手冊規範"""
    
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
    
    def prompt_channel_currents(self):
        """
        互動式詢問每個通道的額定電流設定
        
        Returns:
            dict: {1: current, 2: current, 3: current, 4: current}
            或 None (完全跳過初始化)
        """
        while True:  # 外層循環: 是否初始化
            print("\n" + "="*60)
            print("⚙️  通道額定電流設定")
            print("="*60)
            print("⚠️  注意: 初始化會覆蓋設備當前狀態")
            print()
            
            # 先詢問是否需要初始化
            skip_init = input("是否需要初始化通道? [y/N]: ").strip().lower()
            if skip_init not in ['y', 'yes']:
                print("✅ 跳過初始化,保持設備當前狀態")
                return None
            
            # 進入設定循環
            while True:  # 內層循環: 設定電流值
                print("\n請為每個通道設定額定電流 (0.5A - 25.5A)")
                print("直接按 Enter 使用預設值 4A")
                print()
                channel_currents = {}
                default_current = 4.0
                for ch in range(1, 5):
                    while True:
                        try:
                            user_input = input(f"  CH{ch} 額定電流 [預設: {default_current}A]: ").strip()
                            if user_input == "":
                                current = default_current
                                print(f"    → 使用預設值: {current}A")
                                channel_currents[ch] = current
                                break
                            current = float(user_input)
                            if 0.5 <= current <= 25.5:
                                print(f"    → 設定為: {current}A")
                                channel_currents[ch] = current
                                break
                            else:
                                print(f"    ⚠️  錯誤: 請輸入 0.5-25.5 之間的數值")
                        except ValueError:
                            print(f"    ⚠️  錯誤: 請輸入有效的數字")
                        except KeyboardInterrupt:
                            print("\n\n⚠️  設定已取消")
                            return None
                
                # 顯示設定摘要
                print("\n" + "="*60)
                print("📋 設定摘要:")
                for ch, current in channel_currents.items():
                    if current > 0:
                        print(f"  CH{ch}: {current}A")
                    else:
                        print(f"  CH{ch}: 跳過初始化")
                print("="*60)
                
                # 確認設定
                while True:
                    confirm = input("\n確認設定? [Y/n/b(返回)]: ").strip().lower()
                    
                    if confirm in ['b', 'back', '返回']:
                        print("⚠️  返回上一層 (重新選擇是否初始化)")
                        break  # 跳出確認循環
                        
                    elif confirm in ['n', 'no']:
                        print("⚠️  重新設定通道電流值\n")
                        break  # 跳出確認循環
                        
                    elif confirm in ['', 'y', 'yes']:
                        # 確認完成,返回設定
                        return channel_currents
                        
                    else:
                        print("    請輸入 Y(確認), n(重設), 或 b(返回)")
                
                # 根據選擇決定行為
                if confirm in ['b', 'back', '返回']:
                    break  # 跳出內層循環,回到外層 (重新詢問是否初始化)
                # 如果是 'n',繼續內層循環 (重新輸入電流值)

    
    def initialize_all_channels(self, driver, channel_currents=None):
        """
        初始化所有通道的額定電流（一次性，程式啟動時執行）
        
        Args:
            driver: CIPDriver 實例
            channel_currents: dict {1: 4.0, 2: 2.5, 3: 1.0, 4: 5.0} 或 None (使用預設)
        
        重要：順序執行，確保不互相干擾
        """
        if self.channels_initialized:
            print("[初始化] 通道已初始化，跳過")
            return True
        
        # 如果沒有提供設定，使用預設值
        if channel_currents is None:
            channel_currents = {1: 4, 2: 4, 3: 4, 4: 4}
        
        print("\n" + "="*60)
        print("🔧 初始化所有通道額定電流")
        print("   設定值:")
        for ch, current in channel_currents.items():
            if current > 0:
                print(f"     CH{ch}: {current} A")
            else:
                print(f"     CH{ch}: 跳過")
        print("   這個過程需要約 40 秒，請耐心等待...")
        print("="*60)
        
        for ch in range(1, 5):
            current = channel_currents.get(ch, 4)  # 預設 4A
            
            # 如果設定為 0, 跳過初始化
            if current == 0:
                print(f"\n[初始化] 通道 {ch}/4: ⏭️  跳過")
                continue
            
            print(f"\n[初始化] 通道 {ch}/4: 設定額定電流 {current}A")
            success = self._set_nominal_current_led_button(driver, 1, ch, int(current))
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
                print("[DEBUG] Forward Open 成功")
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
                # 設備不支援 Implicit Messaging,使用標準 Explicit 模式
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
                        print(f"       [DEBUG] Response 物件: {response}")
                        if hasattr(response, 'error'):
                            error_status = response.error if response.error else "None (成功)"
                            print(f"       [DEBUG] Error: {error_status}")
                        if hasattr(response, 'value'):
                            value_str = response.value if response.value else "b'' (空回應，正常)"
                            print(f"       [DEBUG] Value: {value_str}")
                            print(f"       [說明] Set 操作成功時通常回傳空值")
                    
                    if response and not (hasattr(response, 'error') and response.error):
                        print(f"       ✅ 已寫入設備")
                        
                        # 驗證: 讀取回來確認
                        try:
                            verify_resp = self.driver.generic_message(
                                service=0x0E,  # Get Attribute Single
                                class_code=0x04,
                                instance=self.output_instance,
                                attribute=3,
                                connected=False
                            )
                            if verify_resp and hasattr(verify_resp, 'value') and len(verify_resp.value) >= 2:
                                actual_byte1 = verify_resp.value[1]
                                print(f"       [驗證] 設備實際 byte[1] = 0x{actual_byte1:02X}")
                                if actual_byte1 == new_value:
                                    print(f"       ✅ 驗證成功：設備狀態與預期一致")
                                else:
                                    print(f"       ⚠️ 警告：設備 byte[1]=0x{actual_byte1:02X}, 預期=0x{new_value:02X}")
                        except Exception as ve:
                            print(f"       [驗證] 無法驗證: {ve}")
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
            
            # 讀取 Input Assembly 0x65 (包含系統資訊和通道電流)
            response_input = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,  # 0x65
                attribute=3,
                connected=False
            )
            
            voltage = 0.0
            total_current = 0.0
            
            if response_input and hasattr(response_input, 'value'):
                data = response_input.value
                if len(data) >= 6:
                    voltage = struct.unpack('<H', data[4:6])[0] / 100.0
                if len(data) >= 8:
                    total_current = struct.unpack('<H', data[6:8])[0] / 100.0
            
            # 根據手冊 7.2.5 節 (Table 7-4, 7-9):
            # Module 1: CH1=Byte[8], CH2=Byte[11], CH3=Byte[14], CH4=Byte[17]
            # 資料格式: 1 byte, 範圍 0-255 對應 0-25.5A
            
            print("\n📊 通道狀態 (即時讀取):")
            print(f"   電壓: {voltage:.2f} V")
            print(f"   總電流: {total_current:.2f} A")
            print("   " + "─" * 35)
            
            # 通道電流的 offset (Module 1)
            channel_offsets = [8, 11, 14, 17]  # CH1, CH2, CH3, CH4
            
            for ch in range(1, 5):
                offset = channel_offsets[ch - 1]
                
                if len(data) > offset:
                    # 讀取 1 byte, 範圍 0-255 = 0-25.5A
                    current_raw = data[offset]
                    current = current_raw / 10.0  # 0-255 -> 0-25.5A
                    
                    state = "🟢 開" if current > 0.05 else "🔴 關"
                    print(f"   CH{ch}: {state}  {current:.2f} A")
                else:
                    print(f"   CH{ch}: ⚠️ 資料不足 (offset {offset})")
            
        except Exception as e:
            print(f"❌ 讀取狀態失敗: {e}")
            import traceback
            traceback.print_exc()
    
    def run(self):
        """主程式"""
        print("🚀 CAPAROC 控制器 (Production)")
        print(f"設備: {self.device_ip}")
        print("\n✅ Phase 1 完成: 互動式電流值設定")
        print("⚠️  待實作功能:")
        print("   1. 全域狀態監測 (持續背景監控)")
        print("   2. GUI 規劃設計 (圖形化介面)")
        
        with CIPDriver(self.device_ip) as driver:
            self.driver = driver
            
            # 步驟 1: 互動式設定通道額定電流
            channel_currents = self.prompt_channel_currents()
            
            # 步驟 2: 初始化所有通道 (如果需要)
            if channel_currents is not None:
                print("\n[步驟 1/2] 初始化通道額定電流...")
                if not self.initialize_all_channels(driver, channel_currents):
                    print("❌ 初始化失敗")
                    return
                # 初始化後標記為已完成
                self.channels_initialized = True
            else:
                # 跳過初始化,先讀取設備當前狀態
                print("\n[步驟 1/2] 跳過初始化,讀取設備當前狀態...")
                try:
                    # 讀取當前 Output Assembly 狀態
                    response = driver.generic_message(
                        service=0x0E,  # Get Attribute Single
                        class_code=0x04,
                        instance=self.output_instance,
                        attribute=3,
                        connected=False
                    )
                    
                    if response and hasattr(response, 'value') and len(response.value) >= 18:
                        # 載入設備當前狀態到 buffer
                        # ⚠️ 重要: 只取前 18 bytes (Output Assembly 0x64 的正確長度)
                        device_data = response.value[:18]  # 截取前 18 bytes
                        self.current_output_data = bytearray(device_data)
                        
                        print(f"✅ 已載入設備狀態 (byte[1]=0x{self.current_output_data[1]:02X})")
                        print(f"   資料長度: {len(self.current_output_data)} bytes")
                        print(f"   這樣可以避免覆蓋設備當前運行的通道")
                    else:
                        print("⚠️  無法讀取設備狀態,使用空白狀態")
                        
                except Exception as e:
                    print(f"⚠️  讀取設備狀態失敗: {e}")
                    print("   將使用空白狀態 (可能會關閉運行中的通道)")
                
                # 標記為已完成 (允許控制)
                self.channels_initialized = True
            
            # 嘗試建立 Implicit Messaging (靜默模式,CAPAROC 不支援)
            self._establish_implicit_messaging(driver)
            
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
