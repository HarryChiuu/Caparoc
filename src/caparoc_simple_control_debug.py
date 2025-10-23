#!/usr/bin/env python3
"""
CAPAROC 簡化四通道控制器 - DEBUG 版本
用於追蹤和診斷多通道控制問題

DEBUG 功能:
- 詳細的 buffer 狀態追蹤
- set_nominal_current 執行前後的 buffer 變化
- I/O worker 的寫入過程追蹤
- 每個控制步驟的詳細日誌

使用方法:
    python caparoc_simple_control_debug.py
"""

from pycomm3 import CIPDriver
import struct
import time
import threading


class CaparocSimpleController:
    """CAPAROC 簡化控制器 - 專注於四通道 Implicit Messaging 控制"""
    
    def __init__(self, device_ip="192.168.2.111", input_instance=0x65, output_instance=0x64):
        """
        初始化控制器
        
        Args:
            device_ip: 設備 IP 位址
            input_instance: Input Assembly Instance (預設 0x65)
            output_instance: Output Assembly Instance (預設 0x64) ⚠️ 必須是 0x64!
        """
        self.device_ip = device_ip
        self.input_instance = input_instance
        self.output_instance = output_instance
        
        # Implicit Messaging 狀態
        self.implicit_mode_enabled = False
        self.cip_keep_alive = False
        
        # I/O 資料緩存
        self.current_output_data = bytearray(20)  # 輸出狀態緩存
        self.current_input_data = bytearray(244)  # 輸入狀態緩存
        
        # I/O 執行緒
        self.io_update_thread = None
        self.io_data_lock = threading.Lock()
        self.last_io_update = 0
        
        # 暫停 I/O Worker 的旗標 (用於執行 set_nominal_current 時)
        self.pause_io_worker = False
        
        # CIP Driver 物件 (在 establish_implicit_messaging 時保存)
        self.driver = None
        
        # 額定電流設定記錄 - 記錄哪些通道已經設定過額定電流
        # Key: (module, channel), Value: current_amps
        self.nominal_current_per_channel = {}
        
        # 通道首次開啟記錄 - 避免重複設定額定電流
        self.channel_first_opened = set()

    def establish_implicit_messaging(self, driver, verbose=True):
        """
        建立 Implicit Messaging 模式 - 持續 I/O 連接
        這是實現可靠控制的關鍵
        """
        # 保存 driver 物件供其他方法使用
        self.driver = driver
        
        try:
            if verbose:
                print("[Implicit] 建立 Implicit Messaging 模式...")
            
            # 方法1: 嘗試使用 pycomm3 的 forward_open
            if hasattr(driver, 'forward_open'):
                if verbose:
                    print("[Implicit] 嘗試 pycomm3 forward_open...")
                
                try:
                    result = driver.forward_open(
                        o_to_t_size=18,
                        t_to_o_size=244,
                        o_to_t_rpi=20000,  # 20ms
                        t_to_o_rpi=20000,  # 20ms
                        output_assembly=self.output_instance,
                        input_assembly=self.input_instance
                    )
                    
                    if result:
                        if verbose:
                            print("[Implicit] ✅ Forward Open 成功")
                        
                        # 啟動 I/O 工作執行緒
                        self.implicit_mode_enabled = True
                        self.cip_keep_alive = True
                        
                        self.io_update_thread = threading.Thread(
                            target=self._implicit_io_worker,
                            args=(driver, verbose),
                            daemon=True
                        )
                        self.io_update_thread.start()
                        
                        # 等待連接穩定
                        time.sleep(1)
                        
                        if verbose:
                            print("[Implicit] ✅ Implicit Messaging 連接成功")
                        
                        return True
                        
                except Exception as e:
                    if verbose:
                        print(f"[Implicit] Forward Open 失敗: {e}")
            
            # 方法2: 使用自建 Forward Open 請求 (測試程式使用的方法)
            if verbose:
                print("[Implicit] 嘗試自建 Forward Open 請求...")
            
            try:
                response = driver.generic_message(
                    service=0x52,  # Forward Open
                    class_code=0x06,  # Connection Manager
                    instance=0x01,
                    request_data=self._build_forward_open_request(),
                    connected=True,
                    unconnected_send=False
                )
                
                if response:
                    if verbose:
                        print("[Implicit] ✅ 自建 Forward Open 成功")
                    
                    # 啟動 I/O 工作執行緒
                    self.implicit_mode_enabled = True
                    self.cip_keep_alive = True
                    
                    self.io_update_thread = threading.Thread(
                        target=self._implicit_io_worker,
                        args=(driver, verbose),
                        daemon=True
                    )
                    self.io_update_thread.start()
                    
                    # 等待連接穩定
                    time.sleep(1)
                    
                    if verbose:
                        print("[Implicit] ✅ Implicit Messaging 連接成功")
                    
                    return True
                    
            except Exception as e:
                if verbose:
                    print(f"[Implicit] 自建 Forward Open 失敗: {e}")
            
            # 方法3: 使用連接模式的 generic_message (最後回退方案)
            if verbose:
                print("[Implicit] 嘗試連接模式的 generic_message...")
            
            try:
                # 測試連接模式讀取
                resp = driver.generic_message(
                    service=0x0E,
                    class_code=0x04,
                    instance=self.input_instance,
                    attribute=3,
                    connected=True  # 關鍵: 使用連接模式
                )
                
                if resp and resp.value:
                    if verbose:
                        print("[Implicit] ✅ 連接模式 generic_message 成功")
                    
                    # 啟動 I/O 工作執行緒
                    self.implicit_mode_enabled = True
                    self.cip_keep_alive = True
                    
                    self.io_update_thread = threading.Thread(
                        target=self._implicit_io_worker,
                        args=(driver, verbose),
                        daemon=True
                    )
                    self.io_update_thread.start()
                    
                    # 等待連接穩定
                    time.sleep(1)
                    
                    if verbose:
                        print("[Implicit] ✅ Implicit Messaging 連接成功")
                    
                    return True
                else:
                    if verbose:
                        print("[Implicit] 連接模式 generic_message 無回應")
                    
            except Exception as e:
                if verbose:
                    print(f"[Implicit] 連接模式 generic_message 失敗: {e}")
            
            if verbose:
                print("[Implicit] ❌ 所有連接方式都失敗")
            return False
            
        except Exception as e:
            if verbose:
                print(f"[Implicit] 建立 Implicit Messaging 失敗: {e}")
            return False
    
    def _build_forward_open_request(self):
        """建立 Forward Open 請求數據 (從測試程式複製)"""
        request = bytearray()
        
        # Connection Serial Number (4 bytes)
        request.extend(struct.pack('<I', 0x12345678))
        
        # Vendor ID (2 bytes)
        request.extend(struct.pack('<H', 0x009A))
        
        # Originator Serial Number (4 bytes)
        request.extend(struct.pack('<I', 0x87654321))
        
        # Connection Timeout Multiplier (1 byte)
        request.append(0x00)
        
        # Reserved (3 bytes)
        request.extend([0x00, 0x00, 0x00])
        
        # O->T Network Connection ID (4 bytes)
        request.extend(struct.pack('<I', 0x20000001))
        
        # T->O Network Connection ID (4 bytes)
        request.extend(struct.pack('<I', 0x20000002))
        
        # Connection Timeout (2 bytes)
        request.extend(struct.pack('<H', 0x07D0))  # 2000ms
        
        # O->T Connection Parameters (4 bytes)
        request.extend(struct.pack('<I', 0x43F4))  # 20ms RPI
        
        # T->O Connection Parameters (4 bytes)
        request.extend(struct.pack('<I', 0x43F4))  # 20ms RPI
        
        # Transport Type/Trigger (1 byte)
        request.append(0xA3)  # Class 3, Application trigger
        
        # Connection Path Size (1 byte)
        request.append(0x03)  # 3 words
        
        # Connection Path
        request.extend([0x01, self.output_instance])  # Output Assembly
        request.extend([0x01, self.input_instance])   # Input Assembly
        request.extend([0x01, 0x01])                  # Config Assembly
        
        return bytes(request)

    def _implicit_io_worker(self, driver, verbose=True):
        """Implicit I/O 工作執行緒 - 持續更新 I/O 資料 (DEBUG 版本)"""
        cycle = 0
        last_byte1_value = 0x80  # 追蹤 byte[1] 的變化
        
        while self.cip_keep_alive and self.implicit_mode_enabled:
            try:
                cycle += 1
                
                # 檢查是否需要暫停 (例如執行 set_nominal_current 時)
                if self.pause_io_worker:
                    if cycle % 50 == 0:
                        print(f"[I/O Worker] 週期 {cycle}: ⏸️ 暫停中 (等待 set_nominal_current 完成)")
                    time.sleep(0.05)
                    continue
                
                # 發送輸出數據
                with self.io_data_lock:
                    output_data = bytes(self.current_output_data)
                    current_byte1 = output_data[1] if len(output_data) > 1 else 0
                
                # DEBUG: 顯示 byte[1] 變化
                if current_byte1 != last_byte1_value:
                    print(f"[I/O Worker DEBUG] 週期 {cycle}: byte[1] 變化 0x{last_byte1_value:02X} -> 0x{current_byte1:02X}")
                    print(f"                    CH1={bool(current_byte1 & 0x01)}, CH2={bool(current_byte1 & 0x02)}, CH3={bool(current_byte1 & 0x04)}, CH4={bool(current_byte1 & 0x08)}")
                    last_byte1_value = current_byte1
                
                try:
                    # 使用 generic_message 寫入 Output Assembly
                    # (因為 driver.write 在 Implicit 模式下可能不可用)
                    driver.generic_message(
                        service=0x10,  # Set Attribute Single
                        class_code=0x04,  # Assembly Object
                        instance=self.output_instance,
                        attribute=3,  # Data attribute
                        request_data=output_data,
                        connected=False
                    )
                    
                    # DEBUG: 每50個週期顯示一次狀態
                    if cycle % 50 == 0:
                        print(f"[I/O Worker] 週期 {cycle}: 持續寫入 byte[1]=0x{current_byte1:02X}")
                    
                    # 使用 generic_message 讀取 Input Assembly
                    input_response = driver.generic_message(
                        service=0x0E,  # Get Attribute Single
                        class_code=0x04,  # Assembly Object
                        instance=self.input_instance,
                        attribute=3,  # Data attribute
                        connected=False
                    )
                    
                    if input_response and hasattr(input_response, 'value'):
                        with self.io_data_lock:
                            if input_response.value:
                                self.current_input_data = bytearray(input_response.value)
                        
                        self.last_io_update = time.time()
                        
                except Exception as io_e:
                    # I/O 錯誤不中斷執行緒，只記錄
                    if cycle % 500 == 0:  # 減少錯誤輸出頻率
                        print(f"[I/O Worker ERROR] 週期 {cycle}: {io_e}")
                
                # 20Hz 更新頻率 (50ms)
                time.sleep(0.05)
                
            except Exception as e:
                if verbose:
                    print(f"[Implicit] I/O 工作執行緒錯誤: {e}")
                time.sleep(0.1)
        
        if verbose:
            print("[Implicit] I/O 工作執行緒已停止")

    def cleanup_implicit_messaging(self):
        """清理 Implicit Messaging 資源"""
        print("[Implicit] 清理 Implicit Messaging 資源...")
        
        # 停止 I/O 更新
        self.cip_keep_alive = False
        self.implicit_mode_enabled = False
        
        # 等待執行緒結束
        if self.io_update_thread and self.io_update_thread.is_alive():
            self.io_update_thread.join(timeout=2)
        
        print("[Implicit] Implicit Messaging 清理完成")

    def set_channel(self, driver, module, channel, state, verbose=True):
        """
        控制指定通道的開關
        
        Args:
            driver: CIPDriver 實例
            module: 模組序號 (1)
            channel: 通道序號 (1-4)
            state: True=開啟, False=關閉
            verbose: 是否顯示詳細訊息
        
        Returns:
            bool: 控制是否成功
        """
        try:
            if not self.implicit_mode_enabled:
                if verbose:
                    print("[錯誤] Implicit Messaging 未啟用")
                return False
            
            if verbose:
                action = "開啟" if state else "關閉"
                print(f"[控制] {action}通道{channel}...")
            
            # 步驟1: 設定額定電流 (與測試程式相同，每次開啟都執行)
            # DEBUG: 觀察這個步驟如何影響其他通道
            if state:
                if verbose:
                    print(f"[控制] 設定額定電流: 4A")
                print(f"[DEBUG] ⚠️ 即將執行 set_nominal_current，注意觀察其他通道狀態變化")
                self.set_nominal_current(driver, module, channel, 4, verbose=False)
            
            # 步驟2: 修改輸出資料緩存
            with self.io_data_lock:
                byte_offset = 1  # 控制字節位置 (固定為 byte 1)
                bit_position = channel - 1  # 位元位置 (0-3)
                
                print(f"[DEBUG] 修改輸出緩存: byte[{byte_offset}] bit[{bit_position}]")
                
                current_value = self.current_output_data[byte_offset]
                print(f"[DEBUG] 修改前整個 byte[1]: 0x{current_value:02X} (binary: {current_value:08b})")
                print(f"[DEBUG] 要修改的 bit: {bit_position}, 動作: {'開啟' if state else '關閉'}")
                
                # 設定通道狀態 (與測試程式完全相同的邏輯)
                if state:
                    # 開啟：設定對應位元為1，並設定bit7為1
                    new_value = current_value | (1 << bit_position) | 0x80
                    print(f"[DEBUG] 開啟計算: {current_value:02X} | {(1 << bit_position):02X} | 80 = {new_value:02X}")
                else:
                    # 關閉：清除對應位元，保持bit7為1
                    new_value = (current_value & ~(1 << bit_position)) | 0x80
                    mask = ~(1 << bit_position) & 0xFF
                    print(f"[DEBUG] 關閉計算: ({current_value:02X} & {mask:02X}) | 80 = {new_value:02X}")
                
                self.current_output_data[byte_offset] = new_value
                print(f"[DEBUG] 修改後整個 byte[1]: 0x{new_value:02X} (binary: {new_value:08b})")
                print(f"[DEBUG] CH1={bool(new_value & 0x01)}, CH2={bool(new_value & 0x02)}, CH3={bool(new_value & 0x04)}, CH4={bool(new_value & 0x08)}")
            
            # 步驟3: 等待 I/O 執行緒更新到設備
            print("[DEBUG] 等待 I/O 執行緒更新...")
            time.sleep(0.5)  # 等待幾個 I/O 週期
            
            # 檢查 buffer 是否被改變
            with self.io_data_lock:
                final_value = self.current_output_data[byte_offset]
                print(f"[DEBUG] 等待後 byte[1]: 0x{final_value:02X} (是否相同: {final_value == new_value})")
            
            print(f"[控制] ✅ 通道 {channel} -> {'開啟' if state else '關閉'} 命令已發送")
            
            return True
            
        except Exception as e:
            if verbose:
                print(f"[錯誤] 控制失敗: {e}")
            return False

    def set_nominal_current(self, driver, module, channel, current_amps, verbose=True):
        """
        設定通道額定電流 (4通道斷路器) - DEBUG 版本
        
        模擬 LED 按鈕操作:
        1. 長按進入程式模式
        2. 重複按鈕設定電流值
        3. 長按儲存設定
        """
        try:
            # ⚠️ 關鍵修復：暫停 I/O Worker，避免與 set_nominal_current 競爭 Assembly.0x64
            print(f"\n[DEBUG] ⏸️ 暫停 I/O Worker (避免競爭 Assembly.0x64)")
            self.pause_io_worker = True
            time.sleep(0.2)  # 等待 I/O Worker 進入暫停狀態
            
            # DEBUG: 記錄執行前的 buffer 狀態
            with self.io_data_lock:
                before_value = self.current_output_data[1]
            print(f"\n{'='*60}")
            print(f"[DEBUG] set_nominal_current 開始")
            print(f"[DEBUG] 目標通道: {channel}, 額定電流: {current_amps}A")
            print(f"[DEBUG] 執行前 byte[1]: 0x{before_value:02X}")
            print(f"[DEBUG] CH1={bool(before_value & 0x01)}, CH2={bool(before_value & 0x02)}, CH3={bool(before_value & 0x04)}, CH4={bool(before_value & 0x08)}")
            print(f"{'='*60}")
            
            if verbose:
                print(f"[額定電流] 設定通道{channel}額定電流: {current_amps}A")
            
            # 嘗試不同的 Assembly Instance (與測試程式相同)
            instances = [0x67, 0x68, 0x69, 0x6A, 0x64]
            
            for instance in instances:
                try:
                    # 確定資料長度 (與測試程式相同)
                    data_length = 18 if instance == 0x64 else 20
                    
                    print(f"[DEBUG] 嘗試 Instance 0x{instance:02X}, data_length={data_length}")
                    if instance == 0x64:
                        print(f"[DEBUG] ⚠️ 注意：0x64 是 Output Assembly，可能會影響 I/O 控制！")
                    
                    # 通道選擇
                    module_index = module
                    channel_index = channel
                    channel_byte = module_index  # byte position for module
                    channel_bit = channel_index - 1  # bit position for channel
                    
                    # 步驟1: 進入程式模式
                    prog_data = bytearray(data_length)
                    prog_data[channel_byte] = (1 << 7) | (1 << 6)
                    
                    print(f"[DEBUG] 進入程式模式 -> Instance 0x{instance:02X}, byte[{channel_byte}]=0x{prog_data[channel_byte]:02X}")
                    if data_length > 1:
                        print(f"[DEBUG] prog_data[0]=0x{prog_data[0]:02X}, prog_data[1]=0x{prog_data[1]:02X}")
                    
                    resp = driver.generic_message(
                        service=0x10,
                        class_code=0x04,
                        instance=instance,
                        attribute=3,
                        request_data=bytes(prog_data),
                        connected=False
                    )
                    
                    if resp and not (hasattr(resp, 'error') and resp.error):
                        if verbose:
                            print(f"[額定電流] 進入程式模式成功 (Instance 0x{instance:02X})")
                        
                        time.sleep(2.5)
                        
                        # 步驟2: 模擬按鈕設定電流值
                        for press_count in range(current_amps):
                            # 按下
                            press_data = bytearray(data_length)
                            press_data[channel_byte] = (1 << channel_bit) | (1 << 7)
                            driver.generic_message(
                                service=0x10, class_code=0x04, instance=instance,
                                attribute=3, request_data=bytes(press_data), connected=False
                            )
                            time.sleep(0.5)
                            
                            # 釋放
                            release_data = bytearray(data_length)
                            release_data[channel_byte] = (1 << 7)
                            driver.generic_message(
                                service=0x10, class_code=0x04, instance=instance,
                                attribute=3, request_data=bytes(release_data), connected=False
                            )
                            time.sleep(0.3)
                        
                        # 步驟3: 儲存設定
                        save_data = bytearray(data_length)
                        save_data[channel_byte] = (1 << channel_bit) | (1 << 7) | (1 << 6)
                        driver.generic_message(
                            service=0x10, class_code=0x04, instance=instance,
                            attribute=3, request_data=bytes(save_data), connected=False
                        )
                        time.sleep(3.0)
                        
                        # 退出程式模式
                        exit_data = bytearray(data_length)
                        print(f"[DEBUG] 退出程式模式 -> Instance 0x{instance:02X}, 發送全 0 資料")
                        if data_length > 1:
                            print(f"[DEBUG] exit_data[0]=0x{exit_data[0]:02X}, exit_data[1]=0x{exit_data[1]:02X}")
                        driver.generic_message(
                            service=0x10, class_code=0x04, instance=instance,
                            attribute=3, request_data=bytes(exit_data), connected=False
                        )
                        
                        # 記錄設定
                        channel_key = f"{module}_{channel}"
                        self.nominal_current_per_channel[channel_key] = current_amps
                        
                        # DEBUG: 記錄執行後的 buffer 狀態
                        with self.io_data_lock:
                            after_value = self.current_output_data[1]
                        print(f"\n{'='*60}")
                        print(f"[DEBUG] set_nominal_current 完成")
                        print(f"[DEBUG] 執行後 byte[1]: 0x{after_value:02X}")
                        print(f"[DEBUG] CH1={bool(after_value & 0x01)}, CH2={bool(after_value & 0x02)}, CH3={bool(after_value & 0x04)}, CH4={bool(after_value & 0x08)}")
                        if after_value != before_value:
                            print(f"[DEBUG] ⚠️ WARNING: byte[1] 被改變了！ 0x{before_value:02X} -> 0x{after_value:02X}")
                        else:
                            print(f"[DEBUG] ✅ byte[1] 保持不變")
                        print(f"{'='*60}\n")
                        
                        if verbose:
                            print(f"[額定電流] ✅ 設定完成")
                        
                        # ⚠️ 關鍵修復：恢復 I/O Worker
                        print(f"[DEBUG] ▶️ 恢復 I/O Worker")
                        self.pause_io_worker = False
                        
                        return True
                        
                except Exception as e:
                    if verbose:
                        print(f"[額定電流] Instance 0x{instance:02X} 失敗: {e}")
                    continue
            
            if verbose:
                print("[額定電流] ❌ 所有嘗試都失敗")
            
            # 即使失敗也要恢復 I/O Worker
            print(f"[DEBUG] ▶️ 恢復 I/O Worker (失敗後)")
            self.pause_io_worker = False
            return False
            
        except Exception as e:
            if verbose:
                print(f"[額定電流] 錯誤: {e}")
            
            # 即使異常也要恢復 I/O Worker
            print(f"[DEBUG] ▶️ 恢復 I/O Worker (異常後)")
            self.pause_io_worker = False
            return False

    def read_voltage(self, driver=None):
        """讀取系統電壓 (使用 Assembly.101 + generic_message)"""
        if driver is None:
            driver = self.driver
        try:
            # 使用 generic_message 讀取 Assembly.101 的 offset 4
            response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,  # Assembly Object
                instance=0x101,  # Assembly 101
                attribute=3,  # Data attribute
                connected=False
            )
            if response and hasattr(response, 'value') and len(response.value) >= 6:
                voltage_raw = struct.unpack('<H', response.value[4:6])[0]
                return voltage_raw / 100.0
        except:
            pass
        return 0.0

    def read_total_current(self, driver=None):
        """讀取總電流 (使用 Assembly.101 + generic_message)"""
        if driver is None:
            driver = self.driver
        try:
            # 使用 generic_message 讀取 Assembly.101
            response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,  # Assembly Object
                instance=0x101,  # Assembly 101
                attribute=3,  # Data attribute
                connected=False
            )
            if response and hasattr(response, 'value') and len(response.value) >= 8:
                current_raw = struct.unpack('<H', response.value[6:8])[0]
                return current_raw / 100.0
        except:
            pass
        return 0.0

    def read_channel_current(self, driver=None, module=1, channel=1, debug=False):
        """讀取指定通道電流 (使用 Assembly.101 + generic_message)"""
        if driver is None:
            driver = self.driver
        try:
            # 使用 generic_message 讀取 Assembly.101
            response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,  # Assembly Object
                instance=0x101,  # Assembly 101
                attribute=3,  # Data attribute
                connected=False
            )
            if response and hasattr(response, 'value'):
                offset = 20 + (module - 1) * 16 + (channel - 1) * 2
                if len(response.value) >= offset + 2:
                    current_raw = struct.unpack('<H', response.value[offset:offset+2])[0]
                    current = current_raw / 100.0
                    if debug:
                        print(f"   [DEBUG] 通道{channel} offset={offset} raw={current_raw} current={current:.2f}A")
                    return current
        except Exception as e:
            if debug:
                print(f"   [DEBUG] 讀取失敗: {e}")
        return 0.0

    def show_status(self, driver=None):
        """顯示所有通道狀態"""
        if driver is None:
            driver = self.driver
        try:
            # 等待一個 I/O 週期確保讀到最新資料
            time.sleep(0.1)
            
            print("\n📊 通道狀態報告:")
            voltage = self.read_voltage(driver)
            total_current = self.read_total_current(driver)
            
            print(f"   系統電壓: {voltage:.2f} V")
            print(f"   總電流: {total_current:.2f} A")
            print("   " + "─" * 35)
            
            for ch in range(1, 5):
                current = self.read_channel_current(driver, 1, ch)
                status = "🟢 開啟" if current > 0.05 else "🔴 關閉"
                bar = "█" * int(current) if current < 10 else "█" * 10 + "..."
                print(f"   通道{ch}: {current:5.2f} A  {status:6s} {bar}")
            
            # 連接狀態
            if self.implicit_mode_enabled:
                time_since = time.time() - self.last_io_update if self.last_io_update > 0 else float('inf')
                print("   " + "─" * 35)
                print(f"   連接模式: Implicit Messaging ✅")
                print(f"   I/O更新: {time_since:.1f} 秒前")
            
        except Exception as e:
            print(f"❌ 狀態讀取失敗: {e}")

    def run(self):
        """執行互動式四通道控制"""
        print("=" * 60)
        print("🚀 CAPAROC 簡化四通道控制器")
        print("   使用 Implicit Messaging 實現可靠控制")
        print("=" * 60)
        
        with CIPDriver(self.device_ip) as caparoc:
            try:
                print(f"\n[連接] 連接設備: {self.device_ip}")
                
                # 建立 Implicit Messaging 連接
                print("\n[初始化] 建立 Implicit Messaging 連接...")
                success = self.establish_implicit_messaging(caparoc, verbose=True)
                
                if not success:
                    print("❌ Implicit Messaging 連接失敗")
                    return
                
                print("✅ Implicit Messaging 連接成功！")
                time.sleep(2)
                
                # 顯示初始狀態
                print("\n[狀態] 初始狀態:")
                self.show_status(caparoc)
                
                # 互動控制循環
                print("\n[控制] 進入互動控制模式")
                print("指令格式:")
                print("  開啟: on <通道號>   例如: on 1")
                print("  關閉: off <通道號>  例如: off 1")
                print("  全開: all on")
                print("  全關: all off")
                print("  狀態: status (或 s)")
                print("  除錯: debug (或 d) - 顯示原始讀取值")
                print("  退出: quit (或 q)")
                print("-" * 40)
                
                while True:
                    try:
                        cmd = input("\n[控制] 輸入指令: ").strip().lower()
                        
                        if cmd in ["quit", "q"]:
                            break
                        elif cmd in ["status", "s"]:
                            self.show_status(caparoc)
                        elif cmd in ["debug", "d"]:
                            print("\n🔍 DEBUG 模式 - 原始讀取值:")
                            time.sleep(0.1)
                            for ch in range(1, 5):
                                self.read_channel_current(caparoc, 1, ch, debug=True)
                        elif cmd == "all on":
                            print("\n[批量控制] 開啟所有通道...")
                            for ch in range(1, 5):
                                self.set_channel(caparoc, 1, ch, True, verbose=True)
                                time.sleep(0.5)
                            self.show_status(caparoc)
                        elif cmd == "all off":
                            print("\n[批量控制] 關閉所有通道...")
                            for ch in range(1, 5):
                                self.set_channel(caparoc, 1, ch, False, verbose=True)
                                time.sleep(0.5)
                            self.show_status(caparoc)
                        elif cmd.startswith("on "):
                            try:
                                ch = int(cmd.split()[1])
                                if 1 <= ch <= 4:
                                    self.set_channel(caparoc, 1, ch, True, verbose=True)
                                    time.sleep(0.5)  # 等待通道穩定
                                    self.show_status(caparoc)  # 自動顯示狀態
                                else:
                                    print("❌ 通道號必須在 1-4 範圍內")
                            except (ValueError, IndexError):
                                print("❌ 格式錯誤，請使用: on <通道號>")
                        elif cmd.startswith("off "):
                            try:
                                ch = int(cmd.split()[1])
                                if 1 <= ch <= 4:
                                    self.set_channel(caparoc, 1, ch, False, verbose=True)
                                    time.sleep(0.5)  # 等待通道穩定
                                    self.show_status(caparoc)  # 自動顯示狀態
                                else:
                                    print("❌ 通道號必須在 1-4 範圍內")
                            except (ValueError, IndexError):
                                print("❌ 格式錯誤，請使用: off <通道號>")
                        elif cmd in ["help", "h"]:
                            print("可用指令: on <1-4>, off <1-4>, all on, all off, status, debug, quit")
                        else:
                            print("❌ 未知指令，輸入 'help' 查看可用指令")
                    
                    except KeyboardInterrupt:
                        print("\n[中斷] 使用者中止操作")
                        break
                    except Exception as e:
                        print(f"❌ 指令執行錯誤: {e}")
                
            except Exception as e:
                print(f"❌ 控制模式執行失敗: {e}")
                import traceback
                traceback.print_exc()
            
            finally:
                # 詢問是否關閉所有通道
                try:
                    response = input("\n[安全] 是否關閉所有通道? (y/N): ").strip().lower()
                    if response in ['y', 'yes']:
                        print("[安全] 關閉所有通道...")
                        for ch in range(1, 5):
                            self.set_channel(caparoc, 1, ch, False, verbose=False)
                            time.sleep(0.3)
                    else:
                        print("[保持] 通道保持當前狀態")
                except:
                    print("[保持] 通道保持當前狀態")
                
                # 清理資源
                print("[清理] 清理連接資源...")
                self.cleanup_implicit_messaging()
                print("✅ 控制器已停止")


def main():
    """主程式入口"""
    # 可以從命令列參數或配置文件讀取 IP
    controller = CaparocSimpleController(device_ip="192.168.2.111")
    controller.run()


if __name__ == "__main__":
    main()
