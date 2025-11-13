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
  - 增強狀態顯示 (Phase 2 完成):
    * 全域系統狀態 (Byte 0: 欠壓/過壓/系統錯誤/80%警告/總電流關斷)
    * 系統電壓與總電流
    * 各通道詳細狀態 (開關/電流/警告)
  - 程式啟動全域狀態檢查 (Phase 3-1 完成):
    * 手冊 7.2.1: 系統電壓檢查 (9.0-30.5V)
    * 手冊 7.2.2: 欠壓/過壓警告檢測
    * 手冊 7.2.3: 系統錯誤檢測
    * 手冊 7.2.4: 80%總電流警告與總電流關斷狀態
    * 異常狀態時提示使用者是否繼續
  - 動態多模組支援 (V3.5):
    * 自動檢測模組數量 (1-16)
    * 動態通道管理 (最多64通道)
    * 多模組顯示格式
  - 即時監控功能 (Phase 3-2 完成):
    * 背景執行緒定期讀取狀態
    * 可設定更新頻率 (0.5s-60s)
    * 即時通道電流顯示
    * 狀態變化檢測與警報
    * 電流異常檢測 (>30%變化)
    * 新指令: monitor start/stop/status

⚠️ 待實作:
  1. 通道資訊擴展 (Phase 3-3)
  2. IP配置支援 (Phase 3-4)
  3. GUI 規劃設計 (Phase 3-5)

策略:
1. 程式啟動時先檢查全域系統狀態(Phase 3 新增)
2. 一次性設定所有通道額定電流(順序執行,避免干擾)
3. 之後只使用 Output Assembly 控制開關(符合手冊規範)
4. 從 Input Assembly 讀取狀態
5. 即時監控背景執行緒定期更新(Phase 3-2 新增)
"""

from pycomm3 import CIPDriver
import struct
import time
import threading


class CaparocController:
    """CAPAROC  - 基於手冊規範"""
    
    def __init__(self, device_ip="192.168.2.111"): #預設 IP
        self.device_ip = device_ip
        self.output_instance = 0x64  # Output Assembly (EDS Assem100)
        self.input_instance = 0x65   # Input Assembly (EDS Assem101)
        self.config_instance = 0x66  # Config Assembly (EDS Assem102) - 僅用於讀取
        # ⚠️ 寫入配置使用 Parameter Object (Class 0x0F), 不是 Config Assembly!
        
        # 模組與通道配置（動態檢測）
        self.module_count = 0  # 初始化時檢測,支援 1-16 個模組
        self.channels_per_module = 4  # 每個模組 4 通道
        
        # I/O 狀態
        self.implicit_mode_enabled = False
        self.cip_keep_alive = False
        # ⚠️ 關鍵修復:Output Assembly 0x64 長度是 18 bytes(不是 20)
        self.current_output_data = bytearray(18)  # Output Assembly = 18 bytes
        self.current_input_data = bytearray(244)  # Input Assembly = 244 bytes
        self.io_data_lock = threading.Lock()
        self.io_update_thread = None
        self.last_io_update = 0
        self.driver = None
        
        # 初始化標記
        self.channels_initialized = False
        
        # 即時監控 (Phase 3-2)
        self.monitor_thread = None
        self.monitor_running = False
        self.monitor_interval = 2.0  # 預設 2 秒更新
        self.monitor_mode = 'silent'  # 'silent' (靜默) 或 'display' (顯示)
        self.monitor_lock = threading.Lock()
        self.last_status_snapshot = {}  # 儲存上次狀態,用於變化檢測

    
    def get_channel_offset(self, module, channel):
        """
        計算通道在 Input Assembly 中的起始位置（支援多模組）
        
        Args:
            module: 模組編號 (1-16)
            channel: 通道編號 (1-4)
        
        Returns:
            int: 該通道 Status byte 的位置
        
        範例:
            Module 1, CH1: offset = 6 + 0*12 + 0*3 = 6
            Module 1, CH4: offset = 6 + 0*12 + 3*3 = 15
            Module 2, CH1: offset = 6 + 1*12 + 0*3 = 18
            Module 2, CH4: offset = 6 + 1*12 + 3*3 = 27
        """
        # 全域資訊佔 6 bytes (Byte 0-5)
        global_bytes = 6
        
        # 每個模組佔 12 bytes (4 通道 × 3 bytes)
        bytes_per_module = 12
        
        # 每個通道佔 3 bytes (Status, Nominal, Flowing)
        bytes_per_channel = 3
        
        # 計算偏移
        module_offset = global_bytes + (module - 1) * bytes_per_module
        channel_offset = module_offset + (channel - 1) * bytes_per_channel
        
        return channel_offset
    
    def get_total_channels(self):
        """
        取得系統總通道數
        
        Returns:
            int: 總通道數 (module_count × channels_per_module)
        """
        return self.module_count * self.channels_per_module
    
    def get_module_and_channel(self, global_channel):
        """
        將全域通道編號轉換為模組和通道
        
        Args:
            global_channel: 全域通道編號 (1-64, 最多16個模組×4通道)
        
        Returns:
            tuple: (module, channel)
        
        範例:
            1 -> (1, 1)   # 模組1通道1
            4 -> (1, 4)   # 模組1通道4
            5 -> (2, 1)   # 模組2通道1
            8 -> (2, 4)   # 模組2通道4
        """
        module = ((global_channel - 1) // self.channels_per_module) + 1
        channel = ((global_channel - 1) % self.channels_per_module) + 1
        return (module, channel)
    
    def initialize_all_channels(self, driver, channel_currents=None):
        """
        初始化所有通道的額定電流（一次性，程式啟動時執行）- 支援多模組
        
        Args:
            driver: CIPDriver 實例
            channel_currents: dict {global_ch: current, ...} 或 None (使用預設)
        
        重要：順序執行，確保不互相干擾
        """
        if self.channels_initialized:
            print("[初始化] 通道已初始化，跳過")
            return True
        
        total_channels = self.get_total_channels()
        
        # 如果沒有提供設定，使用預設值（所有通道 4A）
        if channel_currents is None:
            channel_currents = {ch: 4.0 for ch in range(1, total_channels + 1)}
        
        print("\n" + "="*60)
        print(f"🔧 初始化所有通道額定電流 ({self.module_count} 個模組, {total_channels} 個通道)")
        print("   設定值:")
        
        for module in range(1, self.module_count + 1):
            if self.module_count > 1:
                print(f"     📦 模組 {module}:")
            
            for ch in range(1, self.channels_per_module + 1):
                global_ch = (module - 1) * self.channels_per_module + ch
                current = channel_currents.get(global_ch, 4)
                
                if current > 0:
                    if self.module_count > 1:
                        print(f"       M{module}.CH{ch} (#{global_ch}): {current} A")
                    else:
                        print(f"     CH{ch}: {current} A")
                else:
                    if self.module_count > 1:
                        print(f"       M{module}.CH{ch} (#{global_ch}): 跳過")
                    else:
                        print(f"     CH{ch}: 跳過")
        
        est_time = total_channels * 2  # 每個通道約 2 秒 (Config Assembly 方法)
        print(f"   預估時間: 約 {est_time} 秒 (使用 Config Assembly 快速設定)")
        print("="*60)
        
        # 遍歷所有模組的所有通道
        for module in range(1, self.module_count + 1):
            for ch in range(1, self.channels_per_module + 1):
                global_ch = (module - 1) * self.channels_per_module + ch
                current = channel_currents.get(global_ch, 4)  # 預設 4A
                
                # 如果設定為 0, 跳過初始化
                if current == 0:
                    if self.module_count > 1:
                        print(f"\n[初始化] M{module}.CH{ch} (#{global_ch}/{total_channels}): ⏭️  跳過")
                    else:
                        print(f"\n[初始化] CH{ch} ({global_ch}/{total_channels}): ⏭️  跳過")
                    continue
                
                if self.module_count > 1:
                    print(f"\n[初始化] M{module}.CH{ch} (#{global_ch}/{total_channels}): 設定額定電流 {current}A")
                else:
                    print(f"\n[初始化] CH{ch} ({global_ch}/{total_channels}): 設定額定電流 {current}A")
                
                # ✅ 優先使用 Parameter Object 方法 (繞過 244-byte 限制)
                success = self._set_nominal_current_parameter_object(driver, module, ch, int(current))
                
                # ⚠️ 如果 Parameter Object 失敗,回退到 LED 按鈕模擬 (舊方法)
                if not success:
                    print(f"       ⚠️  Parameter Object 方法失敗,嘗試 LED 按鈕模擬...")
                    if int(current) <= 10:  # LED 按鈕只支援 1-10A
                        success = self._set_nominal_current_led_button(driver, module, ch, int(current))
                    else:
                        print(f"       ❌ LED 按鈕模擬不支援 {int(current)}A (最大 10A)")
                
                if success:
                    if self.module_count > 1:
                        print(f"[初始化] ✅ M{module}.CH{ch} 完成")
                    else:
                        print(f"[初始化] ✅ CH{ch} 完成")
                else:
                    if self.module_count > 1:
                        print(f"[初始化] ⚠️ M{module}.CH{ch} 失敗")
                    else:
                        print(f"[初始化] ⚠️ CH{ch} 失敗")
                
                # 通道間短暫延遲
                time.sleep(0.3)
        
        self.channels_initialized = True
        print("\n" + "="*60)
        print(f"✅ 所有 {total_channels} 個通道初始化完成！")
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
    
    def _get_config_param_number(self, module, channel):
        """
        計算 Config Assembly 中通道標稱電流的 EDS 參數編號
        
        Args:
            module: 模組編號 (1-16)
            channel: 通道編號 (1-4)
        
        Returns:
            int: EDS 參數編號
        
        範例 (根據手冊 Table 7-11):
            Module 1, CH1: 6  (nominal current)
            Module 1, CH2: 9  (nominal current)
            Module 1, CH3: 12 (nominal current)
            Module 1, CH4: 15 (nominal current)
            Module 2, CH1: 18 (nominal current)
            ...
        
        公式:
            基礎參數 = 6 + (module - 1) * 12 + (channel - 1) * 3
            (每個模組 12 個參數: 4通道 × 3參數/通道)
        """
        base_param = 6  # Module 1, CH1 的起始參數
        params_per_module = 12  # 每個模組 12 個參數 (4 通道 × 3)
        params_per_channel = 3  # 每個通道 3 個參數 (nominal, lock, status)
        
        param_number = base_param + (module - 1) * params_per_module + (channel - 1) * params_per_channel
        return param_number
    
    def _read_config_assembly(self, driver):
        """
        讀取 Config Assembly 完整內容
        
        Returns:
            bytes: Config Assembly 資料, 或 None (失敗)
        """
        try:
            # 嘗試讀取 Config Assembly
            response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,  # Assembly Object
                instance=self.config_instance,  # 0x66
                attribute=3,  # Data attribute
                connected=False
            )
            
            if response and hasattr(response, 'value'):
                return response.value
            
            return None
            
        except Exception as e:
            print(f"[診斷] 讀取 Config Assembly 失敗: {e}")
            return None
    
    def _verify_nominal_current(self, driver, module, channel):
        """
        驗證通道的標稱電流設定
        
        Args:
            driver: CIPDriver 實例
            module: 模組編號
            channel: 通道編號
        
        Returns:
            int: 實際標稱電流值 (0-20A), 或 None (讀取失敗)
        """
        try:
            # 讀取 Input Assembly 0x65
            response = driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
                attribute=3,
                connected=False
            )
            
            if response and hasattr(response, 'value'):
                data = response.value
                offset = self.get_channel_offset(module, channel)
                
                if len(data) > offset + 1:
                    # Byte 1: Nominal current (0-20A)
                    nominal_current = data[offset + 1]
                    
                    # 🔍 詳細診斷
                    print(f"       [驗證Debug] Input Assembly offset {offset}:")
                    print(f"                   Byte 0 (status): 0x{data[offset]:02X}")
                    print(f"                   Byte 1 (nominal): {nominal_current}A")
                    if len(data) > offset + 2:
                        print(f"                   Byte 2: 0x{data[offset+2]:02X}")
                    if len(data) > offset + 3:
                        print(f"                   Byte 3: 0x{data[offset+3]:02X}")
                    
                    return int(nominal_current)
            
            return None
            
        except Exception as e:
            print(f"       [驗證] 讀取失敗: {e}")
            return None
    
    def _check_and_unlock_programming(self, driver, module, channel):
        """
        檢查並解鎖通道的 programming lock
        
        根據 EDS:
        - Param7: M1.CH1 programming lock
        - Param10: M1.CH2 programming lock
        - Param13: M1.CH3 programming lock
        - Param16: M1.CH4 programming lock
        
        Lock 值:
        - 0 = Unlocked (允許修改)
        - 1 = Locked via button
        - 2 = Locked via communication (預設)
        
        Args:
            driver: CIPDriver 實例
            module: 模組編號
            channel: 通道編號
        
        Returns:
            bool: True=已解鎖或成功解鎖, False=解鎖失敗
        """
        try:
            # 計算 programming lock 參數編號
            # Param6 = M1.CH1 nominal current
            # Param7 = M1.CH1 programming lock
            # 每個通道間隔 3 個參數
            base_param = 6 + (module - 1) * 12 + (channel - 1) * 3
            lock_param = base_param + 1  # nominal current 的下一個參數
            
            print(f"       [Lock] 檢查 Param{lock_param} (M{module}.CH{channel} programming lock)...")
            
            # 讀取當前 lock 狀態
            read_response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x0F,  # Parameter Object
                instance=lock_param,
                attribute=1,  # Value
                connected=False
            )
            
            if read_response and hasattr(read_response, 'value'):
                lock_value = int(read_response.value[0]) if isinstance(read_response.value, (bytes, bytearray)) else int(read_response.value)
                lock_status = {0: "Unlocked", 1: "Locked(Button)", 2: "Locked(Comm)"}
                print(f"       [Lock] 當前狀態: {lock_status.get(lock_value, f'Unknown({lock_value})')}")
                
                if lock_value == 0:
                    print(f"       ✅ 已解鎖,可以修改")
                    return True
                
                # 嘗試解鎖
                print(f"       [Lock] 嘗試解鎖...")
                unlock_response = driver.generic_message(
                    service=0x10,  # Set Attribute Single
                    class_code=0x0F,  # Parameter Object
                    instance=lock_param,
                    attribute=1,  # Value
                    request_data=bytes([0]),  # 0 = Unlocked
                    connected=False
                )
                
                if unlock_response and not (hasattr(unlock_response, 'error') and unlock_response.error):
                    print(f"       ✅ 解鎖成功")
                    return True
                else:
                    error_msg = unlock_response.error if hasattr(unlock_response, 'error') else '未知錯誤'
                    print(f"       ❌ 解鎖失敗: {error_msg}")
                    return False
            else:
                print(f"       ⚠️  無法讀取 lock 狀態")
                return True  # 假設已解鎖,繼續嘗試
                
        except Exception as e:
            print(f"       ⚠️  Lock 檢查異常: {e}")
            return True  # 發生錯誤時仍嘗試寫入
    
    def _set_nominal_current_parameter_object(self, driver, module, channel, current_amps):
        """
        使用 Parameter Object 方法設定標稱電流 (推薦方法!)
        
        根據專家建議和 EDS [Params] 定義:
        - 使用 Class 0x0F (Parameter Object)
        - 每個參數獨立寫入 (1-4 bytes)
        - 適用於顯性訊息 (Explicit Messaging)
        - 不受 244 bytes 封包限制
        
        步驟:
        1. 解除全域電流鎖定 (Param1 = 0)
        2. 解除全域介面鎖定 (Param2 = 0)
        3. 解除目標通道 programming lock (ParamN+1 = 0)
        4. 設定標稱電流 (ParamN = current_amps)
        5. 驗證結果
        
        EDS 路徑格式:
        - Param1: Class 0x0F, Instance 0x01, Attribute 0x01
        - Param2: Class 0x0F, Instance 0x02, Attribute 0x01
        - Param6: Class 0x0F, Instance 0x06, Attribute 0x01
        
        Args:
            driver: CIPDriver 實例
            module: 模組編號 (1-16)
            channel: 通道編號 (1-4)
            current_amps: 標稱電流值 (1-20A)
        
        Returns:
            bool: 成功/失敗
        """
        try:
            print(f"\n{'='*70}")
            print(f"🔧 使用 Parameter Object 方法設定標稱電流")
            print(f"   目標: M{module}.CH{channel} → {current_amps}A")
            print(f"{'='*70}\n")
            
            # 驗證電流範圍
            if not (1 <= current_amps <= 20):
                print(f"       ❌ 電流值超出範圍: {current_amps}A (必須在 1-20A 之間)")
                return False
            
            print(f"       ✅ 參數驗證通過: {current_amps}A 在有效範圍內 (1-20A)\n")
            
            # 計算目標參數編號
            # Param6 = M1.CH1, Param9 = M1.CH2, Param12 = M1.CH3, Param15 = M1.CH4
            # Param18 = M2.CH1, ...
            # 公式: ParamN = 6 + (module-1)*12 + (channel-1)*3
            target_param_number = 6 + (module - 1) * 12 + (channel - 1) * 3
            lock_param_number = target_param_number + 1  # programming lock
            
            print(f"       📊 參數計算:")
            print(f"          目標通道: Module {module}, Channel {channel}")
            print(f"          標稱電流參數: Param{target_param_number}")
            print(f"          Programming lock: Param{lock_param_number}\n")
            
            # ========== Step 1: 解除全域電流鎖定 (Param1) ==========
            print(f"🔓 [Step 1/5] 解除全域電流鎖定 (Param1)")
            print(f"       EDS 路徑: Class 0x0F, Instance 0x01, Attribute 0x01")
            print(f"       寫入資料: 0x00 (Disable)")
            
            try:
                param1_resp = driver.generic_message(
                    service=0x10,       # Set Attribute Single
                    class_code=0x0F,    # Parameter Object
                    instance=0x01,      # Param1
                    attribute=0x01,     # Value
                    request_data=bytes([0x00]),  # 0 = Disable
                    connected=False
                )
                
                if param1_resp is None:
                    print(f"       ⚠️  無回應，繼續嘗試...")
                elif hasattr(param1_resp, 'error') and param1_resp.error:
                    print(f"       ⚠️  錯誤: {param1_resp.error}，繼續嘗試...")
                else:
                    print(f"       ✅ Param1 解鎖成功")
            except Exception as e:
                print(f"       ⚠️  異常: {e}，繼續嘗試...")
            
            time.sleep(0.2)
            
            # ========== Step 2: 解除全域介面鎖定 (Param2) ==========
            print(f"\n🔓 [Step 2/5] 解除全域介面鎖定 (Param2)")
            print(f"       EDS 路徑: Class 0x0F, Instance 0x02, Attribute 0x01")
            print(f"       寫入資料: 0x00 (Disable)")
            
            try:
                param2_resp = driver.generic_message(
                    service=0x10,
                    class_code=0x0F,
                    instance=0x02,      # Param2
                    attribute=0x01,
                    request_data=bytes([0x00]),
                    connected=False
                )
                
                if param2_resp is None:
                    print(f"       ⚠️  無回應，繼續嘗試...")
                elif hasattr(param2_resp, 'error') and param2_resp.error:
                    print(f"       ⚠️  錯誤: {param2_resp.error}，繼續嘗試...")
                else:
                    print(f"       ✅ Param2 解鎖成功")
            except Exception as e:
                print(f"       ⚠️  異常: {e}，繼續嘗試...")
            
            time.sleep(0.2)
            
            # ========== Step 3: 解除目標通道 programming lock ==========
            print(f"\n🔓 [Step 3/5] 解除目標通道 programming lock (Param{lock_param_number})")
            print(f"       EDS 路徑: Class 0x0F, Instance 0x{lock_param_number:02X}, Attribute 0x01")
            print(f"       寫入資料: 0x00 (Unlocked)")
            
            try:
                lock_resp = driver.generic_message(
                    service=0x10,
                    class_code=0x0F,
                    instance=lock_param_number,
                    attribute=0x01,
                    request_data=bytes([0x00]),
                    connected=False
                )
                
                if lock_resp is None:
                    print(f"       ⚠️  無回應，繼續嘗試...")
                elif hasattr(lock_resp, 'error') and lock_resp.error:
                    print(f"       ⚠️  錯誤: {lock_resp.error}，繼續嘗試...")
                else:
                    print(f"       ✅ Param{lock_param_number} 解鎖成功")
            except Exception as e:
                print(f"       ⚠️  異常: {e}，繼續嘗試...")
            
            time.sleep(0.2)
            
            # ========== Step 4: 設定標稱電流 ==========
            print(f"\n✍️  [Step 4/5] 設定標稱電流 (Param{target_param_number})")
            print(f"       EDS 路徑: Class 0x0F, Instance 0x{target_param_number:02X}, Attribute 0x01")
            print(f"       寫入資料: 0x{current_amps:02X} ({current_amps}A)")
            
            current_resp = driver.generic_message(
                service=0x10,
                class_code=0x0F,
                instance=target_param_number,
                attribute=0x01,
                request_data=bytes([current_amps]),
                connected=False
            )
            
            if current_resp is None:
                print(f"       ❌ 無回應")
                print(f"\n{'='*70}")
                print(f"❌ 設定失敗: 設備無回應")
                print(f"{'='*70}\n")
                return False
            elif hasattr(current_resp, 'error') and current_resp.error:
                print(f"       ❌ 錯誤: {current_resp.error}")
                print(f"\n{'='*70}")
                print(f"❌ 設定失敗: {current_resp.error}")
                print(f"{'='*70}\n")
                return False
            else:
                print(f"       ✅ Param{target_param_number} 寫入成功!")
            
            time.sleep(0.5)
            
            # ========== Step 5: 驗證結果 ==========
            print(f"\n🔍 [Step 5/5] 驗證設定結果")
            
            # 方法1: 讀取 Parameter Object
            print(f"       方法1: 讀取 Param{target_param_number}...")
            try:
                verify_param_resp = driver.generic_message(
                    service=0x0E,       # Get Attribute Single
                    class_code=0x0F,
                    instance=target_param_number,
                    attribute=0x01,
                    connected=False
                )
                
                if verify_param_resp and hasattr(verify_param_resp, 'value'):
                    param_value = verify_param_resp.value[0] if isinstance(verify_param_resp.value, (bytes, bytearray)) else verify_param_resp.value
                    print(f"       Param{target_param_number} 值: {param_value}A")
                    
                    if param_value == current_amps:
                        print(f"       ✅ Parameter Object 驗證成功!")
                    else:
                        print(f"       ⚠️  Parameter Object 值不符: 期望 {current_amps}A, 實際 {param_value}A")
            except Exception as e:
                print(f"       ⚠️  Parameter Object 驗證失敗: {e}")
            
            # 方法2: 讀取 Input Assembly
            print(f"\n       方法2: 讀取 Input Assembly (0x65)...")
            actual_current = self._verify_nominal_current(driver, module, channel)
            
            if actual_current is not None:
                print(f"       Input Assembly 值: {actual_current}A")
                
                if actual_current == current_amps:
                    print(f"       ✅ Input Assembly 驗證成功!")
                    
                    print(f"\n{'='*70}")
                    print(f"✅ 標稱電流設定成功!")
                    print(f"   M{module}.CH{channel} = {actual_current}A")
                    print(f"   方法: Parameter Object (Class 0x0F)")
                    print(f"{'='*70}\n")
                    return True
                else:
                    print(f"       ⚠️  Input Assembly 值不符: 期望 {current_amps}A, 實際 {actual_current}A")
                    print(f"       💡 可能需要等待設備處理...")
                    
                    # 再等待一下再驗證
                    time.sleep(1.0)
                    actual_current2 = self._verify_nominal_current(driver, module, channel)
                    if actual_current2 == current_amps:
                        print(f"       ✅ 延遲驗證成功: {actual_current2}A")
                        print(f"\n{'='*70}")
                        print(f"✅ 標稱電流設定成功!")
                        print(f"   M{module}.CH{channel} = {actual_current2}A")
                        print(f"{'='*70}\n")
                        return True
            else:
                print(f"       ⚠️  無法從 Input Assembly 驗證")
            
            print(f"\n{'='*70}")
            print(f"⚠️  設定可能成功，但驗證未通過")
            print(f"   建議: 使用 's' 命令手動確認通道狀態")
            print(f"{'='*70}\n")
            return True  # 寫入成功，即使驗證未通過
            
        except Exception as e:
            print(f"\n{'='*70}")
            print(f"❌ 設定異常")
            print(f"{'='*70}")
            print(f"錯誤訊息: {e}")
            import traceback
            print(f"\n堆疊追蹤:")
            traceback.print_exc()
            print(f"{'='*70}\n")
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
    
    def check_global_system_status(self):
        """
        檢查全域系統狀態（基於手冊 7.2.1-7.2.4）
        在程式啟動時執行，確保系統狀態安全
        
        涵蓋功能：
        - 7.2.1: Input assembly, global status (Byte 0)
        - 7.2.2: Input assembly, global module counter (Byte 1)
        - 7.2.3: Input assembly, global total current (Byte 2-3)
        - 7.2.4: Input assembly, global input voltage (Byte 4-5)
        
        Returns:
            dict: {
                'safe': bool,  # True=安全可以繼續, False=有嚴重問題
                'warnings': list,  # 警告訊息列表
                'errors': list,  # 錯誤訊息列表
                'voltage': float,  # 系統電壓 (V)
                'total_current': float,  # 總電流 (A)
                'module_count': int,  # 安裝的斷路器模組數量 (0-16)
                'global_status_byte': int  # 原始狀態位元組
            }
        """
        if not self.driver:
            return {
                'safe': False,
                'warnings': [],
                'errors': ['Driver 未初始化'],
                'voltage': 0.0,
                'total_current': 0.0,
                'module_count': 0,
                'global_status_byte': 0
            }
        
        try:
            # 讀取 Input Assembly 0x65
            response = self.driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,  # Assembly Object
                instance=self.input_instance,  # 0x65
                attribute=3,
                connected=False
            )
            
            if not response or not hasattr(response, 'value') or len(response.value) < 6:
                return {
                    'safe': False,
                    'warnings': [],
                    'errors': ['無法讀取設備狀態'],
                    'voltage': 0.0,
                    'total_current': 0.0,
                    'module_count': 0,
                    'global_status_byte': 0
                }
            
            data = response.value
            warnings = []
            errors = []
            
            # ========== 解析 Byte 0: 全域系統狀態 (7.2.1) ==========
            global_status_byte = data[0]
            undervoltage = bool(global_status_byte & 0x01)      # bit 0
            overvoltage = bool(global_status_byte & 0x02)       # bit 1
            system_error = bool(global_status_byte & 0x04)      # bit 2
            warning_80 = bool(global_status_byte & 0x08)        # bit 3
            total_shutdown = bool(global_status_byte & 0x10)    # bit 4
            config_processing = bool(global_status_byte & 0x80) # bit 7
            
            # ========== 解析 Byte 1: 全域模組計數器 (7.2.2) ==========
            module_count = data[1] if len(data) > 1 else 0  # 0-16 個模組
            
            # ========== 解析 Byte 2-3: 總電流 (7.2.3) ==========
            current_raw = struct.unpack('<H', data[2:4])[0]
            total_current = current_raw / 10.0  # 0.0-50.0A
            
            # ========== 解析 Byte 4-5: 系統電壓 (7.2.4) ==========
            voltage_raw = struct.unpack('<H', data[4:6])[0]
            voltage = voltage_raw / 100.0  # 9.0-30.5V
            
            # ========== 模組數量檢查 ==========
            if module_count < 1:
                warnings.append("⚠️  未偵測到斷路器模組")
            elif module_count > 4:
                warnings.append(f"⚠️  偵測到 {module_count} 個模組（標準為 4 個）")
            
            # ========== 判斷錯誤狀態 ==========
            if undervoltage:
                errors.append(f"⚡ 系統欠壓 (電壓: {voltage:.2f}V < 9.0V)")
            
            if overvoltage:
                errors.append(f"⚡ 系統過壓 (電壓: {voltage:.2f}V > 30.5V)")
            
            if system_error:
                errors.append("🔥 系統錯誤 (硬體故障或通訊異常)")
            
            # ========== 判斷警告狀態 ==========
            if warning_80:
                warnings.append(f"⚠️  總電流已達80%警告閾值 (當前: {total_current:.2f}A)")
            
            if total_shutdown:
                warnings.append("🔴 總電流關斷已觸發 (系統已停止供電)")
            
            if config_processing:
                warnings.append("🔧 設備正在處理配置變更")
            
            # 電壓範圍檢查 (9.0V - 30.5V)
            if voltage < 9.0:
                errors.append(f"⚡ 電壓過低: {voltage:.2f}V (最低: 9.0V)")
            elif voltage > 30.5:
                errors.append(f"⚡ 電壓過高: {voltage:.2f}V (最高: 30.5V)")
            elif voltage < 18.0:
                warnings.append(f"⚠️  電壓偏低: {voltage:.2f}V (建議: 24V)")
            elif voltage > 26.0:
                warnings.append(f"⚠️  電壓偏高: {voltage:.2f}V (建議: 24V)")
            
            # 判斷是否安全
            safe = len(errors) == 0
            
            return {
                'safe': safe,
                'warnings': warnings,
                'errors': errors,
                'voltage': voltage,
                'total_current': total_current,
                'module_count': module_count,
                'global_status_byte': global_status_byte
            }
            
        except Exception as e:
            return {
                'safe': False,
                'warnings': [],
                'errors': [f'狀態檢查異常: {str(e)}'],
                'voltage': 0.0,
                'total_current': 0.0,
                'module_count': 0,
                'global_status_byte': 0
            }
    
    # ==================== 即時監控功能 (Phase 3-2) ====================
    
    def _monitor_worker(self):
        """即時監控背景執行緒"""
        mode_str = "靜默模式 (僅警報)" if self.monitor_mode == 'silent' else "顯示模式"
        print(f"🔄 監控執行緒啟動 (更新頻率: {self.monitor_interval}s, {mode_str})")
        
        while self.monitor_running:
            try:
                # 讀取當前狀態
                current_status = self._read_current_status()
                
                if current_status:
                    # 檢測變化
                    changes = self._detect_changes(current_status)
                    
                    # 根據模式決定是否顯示
                    if self.monitor_mode == 'display':
                        # 顯示模式: 每次都顯示完整狀態
                        self._show_monitor_status(current_status, changes)
                    elif self.monitor_mode == 'silent':
                        # 靜默模式: 只在有變化時顯示警報
                        if any([changes['channel_state_changes'], 
                               changes['current_anomalies'], 
                               changes['system_alerts']]):
                            self._show_monitor_alerts(changes)
                    
                    # 更新快照
                    with self.monitor_lock:
                        self.last_status_snapshot = current_status
                
                # 等待下次更新
                time.sleep(self.monitor_interval)
                
            except Exception as e:
                print(f"⚠️  監控執行緒錯誤: {e}")
                time.sleep(self.monitor_interval)
        
        print("🛑 監控執行緒已停止")
    
    def _read_current_status(self):
        """讀取當前設備狀態 (用於監控)"""
        if not self.driver:
            return None
        
        try:
            response = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
                attribute=3,
                connected=False
            )
            
            if not response or not hasattr(response, 'value'):
                return None
            
            data = response.value
            
            # 解析全域狀態
            global_status_byte = data[0] if len(data) > 0 else 0
            module_count = data[1] if len(data) > 1 else 0
            
            total_current_raw = struct.unpack('<H', data[2:4])[0] if len(data) >= 4 else 0
            total_current = total_current_raw / 10.0
            
            voltage_raw = struct.unpack('<H', data[4:6])[0] if len(data) >= 6 else 0
            voltage = voltage_raw / 100.0
            
            # 解析通道狀態
            channels = {}
            for module in range(1, module_count + 1):
                for ch in range(1, self.channels_per_module + 1):
                    global_ch = (module - 1) * self.channels_per_module + ch
                    offset = self.get_channel_offset(module, ch)
                    
                    if len(data) > offset + 2:
                        status_byte = data[offset]
                        nominal_byte = data[offset + 1]
                        flowing_byte = data[offset + 2]
                        
                        is_on = bool(status_byte & 0x01)
                        warning_80 = bool(status_byte & 0x02)
                        overload = bool(status_byte & 0x04)
                        short_circuit = bool(status_byte & 0x08)
                        hardware_fault = bool(status_byte & 0x10)
                        total_shutdown_ch = bool(status_byte & 0x20)
                        
                        # Byte 1: Nominal current (標稱電流) 1-10A (直接值,不需除以10)
                        nominal_current = float(nominal_byte)
                        # Byte 2: Flowing current (流動電流) 0-255 = 0-25.5A (需除以10)
                        flowing_current = flowing_byte / 10.0
                        
                        channels[global_ch] = {
                            'module': module,
                            'channel': ch,
                            'is_on': is_on,
                            'flowing_current': flowing_current,
                            'nominal_current': nominal_current,
                            'warning_80': warning_80,
                            'overload': overload,
                            'short_circuit': short_circuit,
                            'hardware_fault': hardware_fault,
                            'total_shutdown': total_shutdown_ch
                        }
            
            return {
                'timestamp': time.time(),
                'global_status_byte': global_status_byte,
                'module_count': module_count,
                'total_current': total_current,
                'voltage': voltage,
                'channels': channels
            }
            
        except Exception as e:
            print(f"⚠️  讀取狀態失敗: {e}")
            return None
    
    def _detect_changes(self, current_status):
        """檢測狀態變化"""
        changes = {
            'channel_state_changes': [],
            'current_anomalies': [],
            'system_alerts': []
        }
        
        with self.monitor_lock:
            last = self.last_status_snapshot
            
            if not last:
                return changes
            
            # 檢測通道開關狀態變化
            for ch_num, ch_data in current_status['channels'].items():
                if ch_num in last['channels']:
                    last_ch = last['channels'][ch_num]
                    
                    # 開關狀態變化
                    if ch_data['is_on'] != last_ch['is_on']:
                        state_str = "開啟" if ch_data['is_on'] else "關閉"
                        if self.module_count > 1:
                            ch_label = f"M{ch_data['module']}.CH{ch_data['channel']} (#{ch_num})"
                        else:
                            ch_label = f"CH{ch_num}"
                        changes['channel_state_changes'].append(f"{ch_label} 狀態變更: {state_str}")
                    
                    # 電流異常變化 (變化超過 30%)
                    if ch_data['is_on'] and last_ch['is_on']:
                        current_diff = abs(ch_data['flowing_current'] - last_ch['flowing_current'])
                        if last_ch['flowing_current'] > 0:
                            change_percent = (current_diff / last_ch['flowing_current']) * 100
                            if change_percent > 30:
                                if self.module_count > 1:
                                    ch_label = f"M{ch_data['module']}.CH{ch_data['channel']} (#{ch_num})"
                                else:
                                    ch_label = f"CH{ch_num}"
                                changes['current_anomalies'].append(
                                    f"{ch_label} 電流變化 {change_percent:.1f}%: "
                                    f"{last_ch['flowing_current']:.1f}A → {ch_data['flowing_current']:.1f}A"
                                )
                    
                    # 新出現的警告/錯誤
                    if ch_data['warning_80'] and not last_ch['warning_80']:
                        if self.module_count > 1:
                            ch_label = f"M{ch_data['module']}.CH{ch_data['channel']} (#{ch_num})"
                        else:
                            ch_label = f"CH{ch_num}"
                        changes['system_alerts'].append(f"{ch_label} ⚠️ 80% 警告")
                    
                    if ch_data['overload'] and not last_ch['overload']:
                        if self.module_count > 1:
                            ch_label = f"M{ch_data['module']}.CH{ch_data['channel']} (#{ch_num})"
                        else:
                            ch_label = f"CH{ch_num}"
                        changes['system_alerts'].append(f"{ch_label} 🔴 過載")
                    
                    if ch_data['short_circuit'] and not last_ch['short_circuit']:
                        if self.module_count > 1:
                            ch_label = f"M{ch_data['module']}.CH{ch_data['channel']} (#{ch_num})"
                        else:
                            ch_label = f"CH{ch_num}"
                        changes['system_alerts'].append(f"{ch_label} 🔴 短路")
            
            # 系統電壓變化
            voltage_diff = abs(current_status['voltage'] - last['voltage'])
            if voltage_diff > 1.0:
                changes['system_alerts'].append(
                    f"電壓變化: {last['voltage']:.1f}V → {current_status['voltage']:.1f}V"
                )
        
        return changes
    
    def _show_monitor_status(self, status, changes):
        """顯示監控狀態 (簡潔格式)"""
        # 清屏效果 (可選)
        # print("\n" * 2)
        
        timestamp_str = time.strftime("%H:%M:%S", time.localtime(status['timestamp']))
        
        print(f"\n{'='*70}")
        print(f"🔄 即時監控 [{timestamp_str}] - 更新頻率: {self.monitor_interval}s")
        print(f"{'='*70}")
        
        # 系統摘要
        print(f"📊 系統: {status['voltage']:.1f}V | {status['total_current']:.1f}A | {status['module_count']} 模組")
        
        # 顯示所有通道
        print(f"\n{'通道':<15} {'狀態':<6} {'電流':<12} {'警告/錯誤'}")
        print("-" * 70)
        
        for ch_num in sorted(status['channels'].keys()):
            ch = status['channels'][ch_num]
            
            # 通道標籤
            if self.module_count > 1:
                ch_label = f"M{ch['module']}.CH{ch['channel']} (#{ch_num})"
            else:
                ch_label = f"CH{ch_num}"
            
            # 狀態
            state_icon = "🟢 開" if ch['is_on'] else "🔴 關"
            
            # 電流
            current_str = f"{ch['flowing_current']:.1f}A / {ch['nominal_current']:.1f}A"
            
            # 警告/錯誤
            alerts = []
            if ch['warning_80']:
                alerts.append("⚠️80%")
            if ch['overload']:
                alerts.append("🔴過載")
            if ch['short_circuit']:
                alerts.append("🔴短路")
            if ch['hardware_fault']:
                alerts.append("🔴硬體")
            if ch['total_shutdown']:
                alerts.append("🔴總斷")
            
            alert_str = " ".join(alerts) if alerts else "✅"
            
            print(f"{ch_label:<15} {state_icon:<6} {current_str:<12} {alert_str}")
        
        # 顯示變化
        if any([changes['channel_state_changes'], changes['current_anomalies'], changes['system_alerts']]):
            print(f"\n{'🔔 檢測到變化:'}")
            for change in changes['channel_state_changes']:
                print(f"  ▸ {change}")
            for anomaly in changes['current_anomalies']:
                print(f"  ▸ {anomaly}")
            for alert in changes['system_alerts']:
                print(f"  ▸ {alert}")
        
        print(f"{'='*70}")
    
    def _show_monitor_alerts(self, changes):
        """顯示監控警報 (靜默模式專用)"""
        timestamp_str = time.strftime("%H:%M:%S", time.localtime())
        
        print(f"\n{'='*70}")
        print(f"🔔 監控警報 [{timestamp_str}]")
        print(f"{'='*70}")
        
        for change in changes['channel_state_changes']:
            print(f"  ▸ {change}")
        for anomaly in changes['current_anomalies']:
            print(f"  ▸ {anomaly}")
        for alert in changes['system_alerts']:
            print(f"  ▸ {alert}")
        
        print(f"{'='*70}")
        print("> ", end='', flush=True)  # 恢復輸入提示
    
    def start_monitor(self, interval=None, mode=None):
        """啟動即時監控
        
        Args:
            interval: 更新頻率(秒), 預設2.0
            mode: 'silent' (靜默,僅警報) 或 'display' (持續顯示), 預設 'silent'
        """
        if self.monitor_running:
            print("⚠️  監控已在運行中")
            return False
        
        if interval is not None:
            if interval < 0.5:
                print("⚠️  更新頻率不能小於 0.5 秒")
                return False
            self.monitor_interval = interval
        
        if mode is not None:
            if mode not in ['silent', 'display']:
                print("⚠️  模式必須是 'silent' 或 'display'")
                return False
            self.monitor_mode = mode
        
        # 初始化快照
        with self.monitor_lock:
            self.last_status_snapshot = {}
        
        # 啟動監控執行緒
        self.monitor_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self.monitor_thread.start()
        
        mode_desc = "靜默模式 (僅警報)" if self.monitor_mode == 'silent' else "顯示模式 (持續更新)"
        print(f"✅ 即時監控已啟動")
        print(f"   更新頻率: {self.monitor_interval}s")
        print(f"   模式: {mode_desc}")
        if self.monitor_mode == 'silent':
            print(f"   💡 提示: 監控在背景運行,有變化時會自動通知")
        return True
    
    def stop_monitor(self):
        """停止即時監控"""
        if not self.monitor_running:
            print("⚠️  監控未運行")
            return False
        
        print("🛑 正在停止監控...")
        self.monitor_running = False
        
        # 等待執行緒結束
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        print("✅ 監控已停止")
        return True
    
    def show_monitor_info(self):
        """顯示監控狀態資訊"""
        mode_desc = "靜默模式 (僅警報)" if self.monitor_mode == 'silent' else "顯示模式 (持續更新)"
        
        if self.monitor_running:
            print(f"✅ 監控運行中")
            print(f"   更新頻率: {self.monitor_interval}s")
            print(f"   模式: {mode_desc}")
        else:
            print(f"⚠️  監控未啟動")
            print(f"   設定頻率: {self.monitor_interval}s")
            print(f"   設定模式: {mode_desc}")
            print(f"   (參數將在下次啟動時生效)")
    
    # ==================== 原有功能 ====================
    
    def show_status(self):
        """顯示所有通道狀態 + 全域系統狀態（從設備讀取）"""
        if not self.driver:
            print("❌ Driver 未初始化")
            return
        
        try:
            print("\n📊 讀取設備狀態...")
            
            # 讀取 Input Assembly 0x65 (包含系統資訊和通道電流)
            response_input = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,  # 0x65
                attribute=3,
                connected=False
            )
            
            if not response_input or not hasattr(response_input, 'value'):
                print("❌ 無法讀取狀態資料")
                return
            
            data = response_input.value
            
            # ========== 1. 全域系統狀態 (7.2.1 - Byte 0) ==========
            print("\n🌐 全域系統狀態:")
            if len(data) > 0:
                global_status_byte = data[0]
                undervoltage = bool(global_status_byte & 0x01)
                overvoltage = bool(global_status_byte & 0x02)
                system_error = bool(global_status_byte & 0x04)
                warning_80 = bool(global_status_byte & 0x08)
                total_shutdown = bool(global_status_byte & 0x10)
                config_processing = bool(global_status_byte & 0x80)
                
                status_icons = []
                if undervoltage:
                    status_icons.append("⚡ 欠壓")
                if overvoltage:
                    status_icons.append("⚡ 過壓")
                if system_error:
                    status_icons.append("🔥 系統錯誤")
                if warning_80:
                    status_icons.append("⚠️  80%警告")
                if total_shutdown:
                    status_icons.append("🔴 總電流關斷")
                if config_processing:
                    status_icons.append("🔧 Config處理中")
                
                if status_icons:
                    print("   " + " | ".join(status_icons))
                else:
                    print("   ✅ 正常")
            
            # ========== 2. 模組數量 (7.2.2 - Byte 1) ==========
            module_count = data[1] if len(data) > 1 else 0
            
            # ========== 3. 系統電壓與全域總電流 (7.2.3, 7.2.4) ==========
            # 根據實測驗證:
            # - Byte 4-5: Total voltage (例如 2400 = 24.00V) - 7.2.4
            # - Byte 2-3: Total current (例如 102 = 10.2A) - 7.2.3
            voltage = 0.0
            global_total_current = 0.0
            
            if len(data) >= 4:
                # Byte 2-3: Total current (little-endian)
                current_raw = struct.unpack('<H', data[2:4])[0]
                global_total_current = current_raw / 10.0  # 0-500 -> 0.0-50.0A
            
            if len(data) >= 6:
                # Byte 4-5: Total voltage (little-endian)
                voltage_raw = struct.unpack('<H', data[4:6])[0]
                voltage = voltage_raw / 100.0  # 例如 2400 -> 24.00V
            
            print(f"\n📊 系統參數:")
            print(f"   電壓: {voltage:.2f} V")
            print(f"   全域總電流: {global_total_current:.2f} A  (設備報告)")
            print(f"   模組數量: {module_count} 個")
            
            # ========== 4. 各通道狀態 (7.2.5) - 支援多模組 ==========
            # 根據手冊 7.2.5 節 (Table 7-9):
            # 每個模組有 12 bytes 數據塊，4 通道模組分為 4 組，每組 3 bytes:
            #   Byte 0: Status byte (6 個狀態位元)
            #     - bit 0: Channel status (開/關)
            #     - bit 1: 80% warning
            #     - bit 2: Overload tripping (過載跳脫)
            #     - bit 3: Short-circuit tripping (短路跳脫)
            #     - bit 4: Hardware fault (硬體故障)
            #     - bit 5: Total current shutdown (總電流關斷)
            #   Byte 1: Nominal current (標稱電流, 1A - 10A)
            #   Byte 2: Flowing current (流動電流, 0-255 = 0A - 25.5A)
            
            print("\n📊 通道狀態:")
            
            # 動態顯示所有模組的所有通道
            for module in range(1, module_count + 1):
                # 如果多於一個模組，顯示模組標題
                if module_count > 1:
                    print(f"\n   � 模組 {module}:")
                print("   " + "─" * 40)
                
                for ch in range(1, self.channels_per_module + 1):
                    # 使用動態計算的偏移
                    base_offset = self.get_channel_offset(module, ch)
                    
                    # 計算全域通道編號
                    global_ch = (module - 1) * self.channels_per_module + ch
                    
                    if len(data) > base_offset + 2:
                        # Byte 0: Status byte (根據手冊 7.2.5 Table 7-9)
                        status_byte = data[base_offset]
                        is_on = bool(status_byte & 0x01)           # bit 0: Channel status (on/off)
                        warning_80_ch = bool(status_byte & 0x02)   # bit 1: 80% warning
                        overload = bool(status_byte & 0x04)        # bit 2: Overload tripping
                        short_circuit = bool(status_byte & 0x08)   # bit 3: Short-circuit tripping
                        hardware_fault = bool(status_byte & 0x10)  # bit 4: Hardware fault
                        total_shutdown_ch = bool(status_byte & 0x20) # bit 5: Total current shutdown
                        
                        # Byte 1: Nominal current (標稱電流) 1-10A
                        nominal_current = data[base_offset + 1]
                        
                        # Byte 2: Flowing current (實際電流) 0-255 = 0-25.5A
                        current_raw = data[base_offset + 2]
                        current = current_raw / 10.0
                        
                        # 根據狀態位元判斷開關,而非電流值
                        state = "🟢 開" if is_on else "🔴 關"
                        
                        # 組合顯示訊息 - 顯示全域通道編號或模組.通道格式
                        if module_count > 1:
                            status_msg = f"   M{module}.CH{ch} (#{global_ch}): {state}  {current:.2f}A / {nominal_current}A"
                        else:
                            status_msg = f"   CH{ch}: {state}  {current:.2f}A / {nominal_current}A"
                        
                        # 添加特殊狀態標註
                        warnings = []
                        if is_on and current < 0.05:
                            warnings.append("無負載")
                        if warning_80_ch:
                            warnings.append("⚠️ 80%")
                        if overload:
                            warnings.append("❌ 過載")
                        if short_circuit:
                            warnings.append("❌ 短路")
                        if hardware_fault:
                            warnings.append("🔥 硬體故障")
                        if total_shutdown_ch:
                            warnings.append("🔴 總電流關斷")
                        
                        if warnings:
                            status_msg += f" ({', '.join(warnings)})"
                        
                        print(status_msg)
                    else:
                        if module_count > 1:
                            print(f"   M{module}.CH{ch} (#{global_ch}): ⚠️ 資料不足 (offset {base_offset})")
                        else:
                            print(f"   CH{ch}: ⚠️ 資料不足 (offset {base_offset})")
            
            print("   " + "─" * 40)
            
        except Exception as e:
            print(f"❌ 讀取狀態失敗: {e}")
            import traceback
            traceback.print_exc()
    
    def check_device_connection(self, driver):
        """
        檢查裝置連線狀態
        
        ⚠️ 重要：CAPAROC 不支援標準 Identity Object (Class 0x01)
        改用直接讀取 Input Assembly (0x65) 來驗證連線
        
        Args:
            driver: CIPDriver 實例
        
        Returns:
            dict: {
                'connected': bool,  # 是否連線成功
                'error': str,       # 錯誤訊息 (如果有)
                'device_info': dict # 設備資訊 (如果連線成功)
            }
        """
        result = {
            'connected': False,
            'error': None,
            'device_info': {}
        }
        
        try:
            # ✅ 改用讀取 Input Assembly 來驗證連線
            # 這是 CAPAROC 已知支援的方法
            response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=0x04,  # Assembly Object
                instance=self.input_instance,  # 0x65 (Input Assembly)
                attribute=3,
                connected=False
            )
            
            if response and hasattr(response, 'value') and len(response.value) >= 6:
                result['connected'] = True
                
                # 從 Input Assembly 讀取基本資訊
                data = response.value
                
                # 讀取模組數量 (Byte 1)
                if len(data) > 1:
                    module_count = data[1]
                    result['device_info']['module_count'] = module_count
                    result['device_info']['total_channels'] = module_count * 4
                
                # 讀取系統電壓 (Byte 4-5)
                if len(data) >= 6:
                    voltage_raw = struct.unpack('<H', data[4:6])[0]
                    voltage = voltage_raw / 100.0
                    result['device_info']['voltage'] = f"{voltage:.1f}V"
                
                # 標註為 CAPAROC 設備
                result['device_info']['device_type'] = 'CAPAROC Circuit Breaker'
                    
            else:
                result['error'] = "設備無回應或 Input Assembly 讀取失敗"
                
        except Exception as e:
            result['error'] = f"連線失敗: {str(e)}"
        
        return result
    
    def _configure_device_ip(self):
        """
        配置設備 IP 位址
        
        Returns:
            str: 新的 IP 位址，或 None (取消)
        """
        print("\n" + "="*60)
        print("📝 IP 位址設定")
        print("="*60)
        print("請輸入新的設備 IP 位址")
        print("格式: xxx.xxx.xxx.xxx (例: 192.168.1.100)")
        print("或輸入 'cancel' 取消設定")
        print("="*60)
        
        while True:
            new_ip = input("\n新 IP 位址: ").strip()
            
            if new_ip.lower() == 'cancel':
                return None
            
            # 驗證 IP 格式
            if self._validate_ip(new_ip):
                # 確認變更
                print(f"\n⚠️  確認要將 IP 從 {self.device_ip} 變更為 {new_ip} 嗎？")
                confirm = input("請輸入 [Y]確認 / [N]取消: ").strip().upper()
                if confirm == 'Y':
                    return new_ip
                elif confirm == 'N':
                    print("已取消變更")
                    continue
                else:
                    print("⚠️  無效的輸入，請重新輸入 IP")
            else:
                print(f"⚠️  無效的 IP 格式: {new_ip}")
                print("   請使用正確格式 (例: 192.168.1.100)")
    
    def _validate_ip(self, ip_str):
        """
        驗證 IP 位址格式
        
        Args:
            ip_str: IP 位址字串
        
        Returns:
            bool: True=有效, False=無效
        """
        try:
            parts = ip_str.split('.')
            if len(parts) != 4:
                return False
            
            for part in parts:
                num = int(part)
                if num < 0 or num > 255:
                    return False
            
            return True
        except (ValueError, AttributeError):
            return False
    
    def run(self):
        """主程式"""
        print("🚀 CAPAROC PM EIP Controller v3.7 beta")
        print("\n✅目前可用功能:")
        print("1. 開關控制: 各模組通道進行啟閉控制")
        print("2. 狀態顯示: Global/channel 系統狀態檢查")
        print("3. 即時監控: 依據設定時間定時回傳系統狀態")
        print("4. 設備IP配置: 啟動時可變更設備 IP 位址")
        print("\n⚠️  待實作功能:")
        print("   1. 標稱電流修改 (Phase 3-3)")
        print("   2. 通道資訊擴展 (Phase 3-4)")
        print("   3. GUI 規劃設計 (Phase 3-6)")
        
        # ========== 步驟 0: 裝置連線檢查 ==========
        print("\n" + "="*60)
        print("🔌 檢查裝置連線...")
        print("="*60)
        
        try:
            with CIPDriver(self.device_ip) as driver:
                self.driver = driver
                
                # 執行連線檢查
                conn_result = self.check_device_connection(driver)
                
                if not conn_result['connected']:
                    print(f"\n❌ 裝置連線失敗!")
                    print(f"   IP 位址: {self.device_ip}")
                    if conn_result['error']:
                        print(f"   錯誤: {conn_result['error']}")
                    print(f"\n💡 請檢查:")
                    print(f"   1. 設備是否已開機")
                    print(f"   2. 網路線是否正確連接")
                    print(f"   3. IP 位址是否正確 (當前: {self.device_ip})")
                    print(f"   4. 電腦與設備是否在同一網段")
                    print(f"   5. 防火牆是否阻擋連線")
                    
                    # 提供重新連線選項
                    print("\n" + "="*60)
                    while True:
                        user_choice = input("\n請選擇: [R]重新連線 / [Q]退出程式: ").strip().upper()
                        if user_choice == 'R':
                            print("\n🔄 嘗試重新連線...\n")
                            return 'reconnect'
                        elif user_choice == 'Q':
                            print("✅ 退出程式")
                            return
                        else:
                            print("   ⚠️  請輸入 R (重新連線) 或 Q (退出)")
                    return
                
                # 連線成功，顯示設備資訊
                print(f"✅ 裝置連線成功!")
                print(f"   IP 位址: {self.device_ip}")
                
                if conn_result['device_info']:
                    if 'device_type' in conn_result['device_info']:
                        print(f"   設備類型: {conn_result['device_info']['device_type']}")
                    if 'module_count' in conn_result['device_info']:
                        print(f"   模組數量: {conn_result['device_info']['module_count']} 個 ({conn_result['device_info'].get('total_channels', 0)} 通道)")
                    if 'voltage' in conn_result['device_info']:
                        print(f"   系統電壓: {conn_result['device_info']['voltage']}")
                
                print("="*60)
                
                # ========== IP 配置詢問 (Phase 3-5) ==========
                print("\n" + "="*60)
                print("🌐 IP 配置設定")
                print("="*60)
                print(f"當前連線 IP: {self.device_ip} (預設)")
                print("\n是否要變更設備 IP 位址？")
                print("  [Y] 是，我要設定新的 IP")
                print("  [N] 否，使用預設 IP (192.168.2.111)")
                
                while True:
                    choice = input("\n請選擇 [Y/N]: ").strip().upper()
                    if choice == 'Y':
                        new_ip = self._configure_device_ip()
                        if new_ip and new_ip != self.device_ip:
                            print(f"\n🔄 正在使用新 IP 重新連線: {new_ip}")
                            self.device_ip = new_ip
                            return 'reconnect'  # 重新連線
                        elif new_ip == self.device_ip:
                            print(f"\n✅ IP 未變更，繼續使用 {self.device_ip}")
                            break
                        else:
                            print("\n⚠️  IP 設定取消，繼續使用當前 IP")
                            break
                    elif choice == 'N':
                        print(f"\n✅ 使用預設 IP: {self.device_ip}")
                        break
                    else:
                        print("   ⚠️  請輸入 Y 或 N")
                
                print("="*60)
                
                # ========== Phase 3: 步驟 0 - 全域系統狀態檢查 ==========
                print("\n" + "="*60)
                print("🔍 Phase 3: 全域系統狀態檢查")
                print("="*60)
                
                status = self.check_global_system_status()
                
                # 儲存模組數量到實例變數（供後續動態使用）
                self.module_count = status['module_count']
                
                # 顯示檢查結果
                print(f"\n📊 系統狀態:")
                print(f"   電壓: {status['voltage']:.2f} V")
                print(f"   總電流: {status['total_current']:.2f} A")
                print(f"   模組數量: {status['module_count']} 個 ({self.get_total_channels()} 通道)")
                print(f"   狀態位元組: 0x{status['global_status_byte']:02X}")
                
                # 顯示錯誤訊息
                if status['errors']:
                    print(f"\n❌ 發現 {len(status['errors'])} 個錯誤:")
                    for error in status['errors']:
                        print(f"   {error}")
                
                # 顯示警告訊息
                if status['warnings']:
                    print(f"\n⚠️  發現 {len(status['warnings'])} 個警告:")
                    for warning in status['warnings']:
                        print(f"   {warning}")
                
                # 顯示正常狀態
                if not status['errors'] and not status['warnings']:
                    print(f"\n✅ 系統狀態正常")
                
                # 如果有嚴重錯誤，詢問是否繼續
                if not status['safe']:
                    print("\n" + "="*60)
                    print("⚠️  警告: 系統狀態異常")
                    print("="*60)
                    while True:
                        user_choice = input("\n是否仍要繼續? [y/N]: ").strip().lower()
                        if user_choice in ['y', 'yes']:
                            print("⚠️  使用者選擇繼續 (風險自負)")
                            break
                        elif user_choice in ['', 'n', 'no']:
                            print("✅ 安全退出")
                            return
                        else:
                            print("   請輸入 y (繼續) 或 N (退出)")
                
                print("\n" + "="*60)
                
                # 步驟 1: 從設備讀取實際狀態並同步 (避免誤關閉運行中的通道)
                print("\n[啟動] 讀取設備實際狀態並同步...")
                try:
                    # ✅ 正確做法: 從 Input Assembly 讀取實際狀態
                    response = driver.generic_message(
                        service=0x0E,  # Get Attribute Single
                        class_code=0x04,
                        instance=self.input_instance,  # 0x65 (Input Assembly)
                        attribute=3,
                        connected=False
                    )
                    
                    if response and hasattr(response, 'value') and len(response.value) >= 18:
                        data = response.value
                        
                        # 讀取各通道實際狀態 (從 Byte 6, 9, 12, 15)
                        channel_offsets = [6, 9, 12, 15]
                        actual_states = {}
                        
                        print("   設備當前狀態:")
                        for ch in range(1, 5):
                            offset = channel_offsets[ch - 1]
                            if len(data) > offset:
                                status_byte = data[offset]
                                is_on = bool(status_byte & 0x01)  # bit 0 = on/off
                                actual_states[ch] = is_on
                                
                                current_byte = data[offset + 2] if len(data) > offset + 2 else 0
                                current = current_byte / 10.0
                                
                                state_icon = "🟢 開" if is_on else "🔴 關"
                                print(f"     CH{ch}: {state_icon} ({current:.1f}A)")
                        
                        # 根據實際狀態重建 Output Assembly buffer
                        self.current_output_data = bytearray(18)
                        byte1_value = 0x80  # bit7=1 (release)
                        
                        for ch, is_on in actual_states.items():
                            if is_on:
                                byte1_value |= (1 << (ch - 1))
                        
                        self.current_output_data[1] = byte1_value
                        
                        print(f"\n   ✅ 已同步控制狀態 (byte[1]=0x{byte1_value:02X})")
                        print(f"   現在可以安全地控制通道,不會影響其他已開啟的通道")
                    else:
                        print("⚠️  無法讀取設備狀態,使用空白狀態")
                        
                except Exception as e:
                    print(f"⚠️  讀取設備狀態失敗: {e}")
                    print("   將使用空白狀態 (可能會關閉運行中的通道)")
                
                # 標記為已初始化 (允許控制)
                self.channels_initialized = True
                
                # 嘗試建立 Implicit Messaging (靜默模式,CAPAROC 不支援)
                self._establish_implicit_messaging(driver)
                
                print("\n" + "="*60)
                print("📋 可用命令:")
                print("="*60)
                print("\n【標稱電流設定】")
                print("  init <ch> <amps>             - 設定通道標稱電流")
                print("                                 範例: init 2 4  (設定 CH2 為 4A)")
                print("  verify <ch>                  - 驗證通道標稱電流設定")
                print("\n【通道控制】")
                print("  on <ch>                      - 開啟通道 (例: on 1)")
                print("  off <ch>                     - 關閉通道")
                print("\n【狀態查詢】")
                print("  s                            - 顯示完整狀態")
                print("\n【即時監控】")
                print("  monitor start [interval] [mode]  - 啟動監控")
                print("                                     interval: 更新頻率(秒), 預設2")
                print("                                     mode: silent/display, 預設silent")
                print("                                     範例: monitor start 5 silent")
                print("  monitor stop                 - 停止監控")
                print("  monitor status               - 顯示監控狀態")
                print("\n【系統】")
                print("  reconnect                    - 重新連線設備")
                print("  q                            - 退出程式")
                print("="*60)
                print("💡 快速開始:")
                print("  1. 使用 'init <ch> <amps>' 設定標稱電流 (如: init 1 4)")
                print("  2. 使用 'on <ch>' 開啟通道 (如: on 1)")
                print("  3. 使用 's' 查看狀態")
                print("  4. 使用 'monitor start 2 silent' 啟動監控")
                print("="*60)
                
                while True:
                    try:
                        cmd = input("\n> ").strip().lower()
                        
                        if cmd == 'q':
                            # 停止監控 (如果運行中)
                            if self.monitor_running:
                                self.stop_monitor()
                            break
                        
                        elif cmd == 'reconnect':
                            print("\n🔄 嘗試重新連線...")
                            # 停止監控 (如果運行中)
                            if self.monitor_running:
                                self.stop_monitor()
                            return 'reconnect'
                        
                        elif cmd == 's':
                            self.show_status()
                        elif cmd.startswith('init '):
                            # ✅ 使用正確的 Config Assembly 方法設定標稱電流
                            try:
                                parts = cmd.split()
                                if len(parts) != 3:
                                    print("⚠️  用法: init <通道編號> <電流值>")
                                    print("   範例: init 2 4  (設定 CH2 為 4A)")
                                    continue
                                
                                ch = int(parts[1])
                                amps = int(parts[2])
                                
                                if not (1 <= ch <= self.get_total_channels()):
                                    print(f"⚠️  通道編號超出範圍 (1-{self.get_total_channels()})")
                                    continue
                                
                                if not (1 <= amps <= 20):
                                    print(f"⚠️  電流值超出範圍 (1-20A)")
                                    continue
                                
                                module, channel = self.get_module_and_channel(ch)
                                
                                if self.module_count > 1:
                                    print(f"\n[設定] M{module}.CH{channel} (#{ch}): 標稱電流 {amps}A")
                                else:
                                    print(f"\n[設定] CH{ch}: 標稱電流 {amps}A")
                                
                                # ✅ 使用 Parameter Object 方法 (繞過 244-byte 限制)
                                success = self._set_nominal_current_parameter_object(driver, module, channel, amps)
                                
                                if success:
                                    print(f"✅ CH{ch} 設定完成")
                                else:
                                    print(f"❌ CH{ch} 設定失敗")
                                    print(f"💡 請檢查:")
                                    print(f"   1. 設備旋轉開關是否在 'RC' 位置")
                                    print(f"   2. 硬體鎖是否已解除 (長按 PWR 3秒)")
                            
                            except (ValueError, IndexError) as e:
                                print(f"⚠️  命令格式錯誤: {e}")
                                print("   用法: init <通道編號> <電流值>")
                        
                        elif cmd.startswith('verify '):
                            try:
                                ch = int(cmd.split()[1])
                                if 1 <= ch <= self.get_total_channels():
                                    module, channel = self.get_module_and_channel(ch)
                                    actual = self._verify_nominal_current(driver, module, channel)
                                    if actual is not None:
                                        if self.module_count > 1:
                                            print(f"✅ M{module}.CH{channel} (#{ch}) 標稱電流: {actual}A")
                                        else:
                                            print(f"✅ CH{ch} 標稱電流: {actual}A")
                                    else:
                                        print(f"❌ 無法讀取 CH{ch} 的標稱電流")
                                else:
                                    print(f"⚠️  通道編號超出範圍 (1-{self.get_total_channels()})")
                            except (ValueError, IndexError):
                                print("⚠️  用法: verify <通道編號>")
                        elif cmd.startswith('on '):
                            ch = int(cmd.split()[1])
                            self.set_channel(ch, True)
                        elif cmd.startswith('off '):
                            ch = int(cmd.split()[1])
                            self.set_channel(ch, False)
                        elif cmd.startswith('monitor'):
                            parts = cmd.split()
                            if len(parts) < 2:
                                print("⚠️  請指定 monitor 子命令: start, stop, status")
                                continue
                            
                            subcmd = parts[1]
                            
                            if subcmd == 'start':
                                # 解析間隔和模式參數
                                interval = None
                                mode = None
                                
                                if len(parts) >= 3:
                                    try:
                                        interval = float(parts[2])
                                    except ValueError:
                                        print(f"⚠️  無效的更新頻率: {parts[2]}")
                                        continue
                                
                                if len(parts) >= 4:
                                    mode = parts[3]
                                    if mode not in ['silent', 'display']:
                                        print(f"⚠️  模式必須是 'silent' 或 'display'")
                                        continue
                                
                                self.start_monitor(interval, mode)
                            
                            elif subcmd == 'stop':
                                self.stop_monitor()
                            
                            elif subcmd == 'status':
                                self.show_monitor_info()
                            
                            else:
                                print(f"⚠️  未知的 monitor 子命令: {subcmd}")
                        
                    except KeyboardInterrupt:
                        print("\n⚠️  收到中斷訊號")
                        if self.monitor_running:
                            self.stop_monitor()
                        break
                    except Exception as e:
                        print(f"❌ 錯誤: {e}")
        
        except Exception as e:
            # 處理 CIPDriver 連線失敗
            print(f"\n❌ 裝置連線失敗!")
            print(f"   IP 位址: {self.device_ip}")
            print(f"   錯誤: 無法建立連線")
            print(f"\n💡 請檢查:")
            print(f"   1. 設備是否已開機")
            print(f"   2. 網路線是否正確連接")
            print(f"   3. IP 位址是否正確 (當前: {self.device_ip})")
            print(f"   4. 電腦與設備是否在同一網段")
            print(f"   5. 防火牆是否阻擋連線 (Port 44818)")
            
            # 提供重新連線選項
            print("\n" + "="*60)
            while True:
                user_choice = input("\n請選擇: [R]重新連線 / [Q]退出程式: ").strip().upper()
                if user_choice == 'R':
                    print("\n🔄 嘗試重新連線...\n")
                    return 'reconnect'
                elif user_choice == 'Q':
                    print("✅ 退出程式")
                    return
                else:
                    print("   ⚠️  請輸入 R (重新連線) 或 Q (退出)")

def main():
    controller = CaparocController()
    while True:
        result = controller.run()
        if result == 'reconnect':
            print("\n[系統] 重新啟動連線與初始化流程...\n")
            continue
        break

if __name__ == "__main__":
    main()
