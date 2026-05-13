#!/usr/bin/env python3
"""
CAPAROC 控制器 (Production Version)
基於手冊 7.1.2 節的正確控制方式

功能狀態:
✅ 已實作:
  - 多通道獨立控制 (on/off)
  - 即時狀態讀取 (電壓、電流)
  - 額定電流設定功能 (Phase 3-3 完成):
    * 使用 Config Assembly Read-Modify-Write 安全更新
    * 支援 1-20A 範圍設定
    * 自動驗證設定結果
    * 保護 Reserved 欄位不被破壞
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
  - 心跳保活機制:
    * 300秒閒置後自動發送心跳
    * 保持 CIP 連線不超時
  - IP 配置支援 (Phase 3-4 完成):
    * 啟動時可變更設備 IP

⚠️ 待實作:
  1. GUI 規劃設計 (Phase 3-5)

策略:
1. 程式啟動時先檢查全域系統狀態(Phase 3 新增)
2. 使用 Config Assembly Read-Modify-Write 安全設定額定電流
3. 使用 Output Assembly 控制開關(符合手冊規範)
4. 從 Input Assembly 讀取狀態
5. 即時監控背景執行緒定期更新(Phase 3-2 新增)
"""

from pycomm3 import CIPDriver
import struct
import time
import threading
from caparoc_backend import CaparocBackend

try:
    from logging_manager import setup as _log_setup, get_logger
    _log_setup()
except ImportError:
    import logging
    def get_logger(name='caparoc'):
        return logging.getLogger(name)


class CaparocController(CaparocBackend):
    """CLI 包裝層：繼承 CaparocBackend，加上命令列介面"""
    
    def __init__(self, device_ip="192.168.2.111"):
        super().__init__(device_ip)
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
        self.help_shown = False  # 標記是否已顯示幫助信息（避免重複）
        
        # 即時監控 (Phase 3-2)
        self.monitor_thread = None
        self.monitor_running = False
        self.monitor_interval = 2.0  # 預設 2 秒更新
        self.monitor_mode = 'silent'  # 'silent' (靜默) 或 'display' (顯示)
        self.monitor_lock = threading.Lock()
        self.last_status_snapshot = {}  # 儲存上次狀態,用於變化檢測
        
        # 心跳機制 (保持連線)
        self.heartbeat_thread = None
        self.heartbeat_running = False
        self.heartbeat_interval = 300.0  # 預設 300 秒發送一次心跳
        self.last_activity_time = time.time()  # 記錄最後活動時間
        self.logger = get_logger()

    
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
    
    def _activate_connection_state(self, driver):
        """
        啟動 CIP 連線狀態
        
        關鍵發現：CAPAROC 設備需要在初始化時執行一次帶有 connected=True 
        參數的請求，才能使後續的控制命令生效。
        
        技術原理：
        - pycomm3 的 connected=True 會在底層建立 CIP 連線上下文
        - 這個連線狀態是設備響應後續控制命令的必要條件
        - 不需要 Forward Open 或 Implicit Messaging
        - 任何 service 都可以，只要 connected=True
        
        實作：使用讀取 Input Assembly 的請求，既啟動連線又讀取狀態
        """
        try:
            print("\n[CIP 連線] 正在建立 CIP 連線狀態...")
            
            response = driver.generic_message(
                service=0x0E,                      # Get Attribute Single
                class_code=0x04,                   # Assembly Object
                instance=self.input_instance,      # 0x65 Input Assembly
                attribute=3,
                connected=True,                    # ⚠️ 關鍵：啟動連線狀態
                unconnected_send=False
            )
            
            if response and not (hasattr(response, 'error') and response.error):
                print("✅ CIP 連線已建立 (WEB UI 應顯示 'connected')")
                return True
            else:
                print("⚠️ CIP 連線建立失敗")
                return False
                
        except Exception as e:
            print(f"❌ CIP 連線異常: {e}")
            return False
    
    def _heartbeat_worker(self, driver):
        """
        心跳執行緒：定期發送請求保持連線活躍
        
        策略：
        - 只在閒置時發送（如果有其他操作則跳過）
        - 使用輕量級的讀取請求
        - 靜默執行，不干擾用戶操作
        """
        while self.heartbeat_running:
            try:
                # 計算閒置時間
                idle_time = time.time() - self.last_activity_time
                
                # 如果閒置超過心跳間隔，發送心跳
                if idle_time >= self.heartbeat_interval:
                    try:
                        # 發送輕量級讀取請求作為心跳
                        driver.generic_message(
                            service=0x0E,                  # Get Attribute Single
                            class_code=0x04,               # Assembly Object
                            instance=self.input_instance,  # Input Assembly
                            attribute=3,
                            connected=True,                # 保持 connected 狀態
                            unconnected_send=False
                        )
                        # 更新活動時間
                        self.last_activity_time = time.time()
                    except Exception as e:
                        # 心跳失敗不影響主程式
                        pass
                
                # 每 5 秒檢查一次
                time.sleep(5.0)
                
            except Exception as e:
                time.sleep(5.0)
    
    def _start_heartbeat(self, driver):
        """啟動心跳機制"""
        if not self.heartbeat_running:
            self.heartbeat_running = True
            self.last_activity_time = time.time()
            self.heartbeat_thread = threading.Thread(
                target=self._heartbeat_worker, 
                args=(driver,), 
                daemon=True
            )
            self.heartbeat_thread.start()
    
    def _stop_heartbeat(self):
        """停止心跳機制"""
        if self.heartbeat_running:
            self.heartbeat_running = False
            if self.heartbeat_thread:
                self.heartbeat_thread.join(timeout=1)
    
    def _update_activity(self):
        """更新最後活動時間（在每次用戶操作時調用）"""
        self.last_activity_time = time.time()
    
    def get_config_channel_offset(self, module, channel):
        """
        計算通道在 Config Assembly 中的 Nominal Current 位置
        
        根據手冊 Table 7-11 Structure of the config assembly:
        - Header: 6 bytes (Byte 0-5)
        - Body: 每個通道 3 bytes (Nominal Current, Programming Lock, Status)
        - 支援最多 16 個模組，每個模組 4 通道
        
        Args:
            module: 模組編號 (1-16)
            channel: 通道編號 (1-4)
        
        Returns:
            int: Nominal Current 的 Byte Offset
        
        範例:
            Module 1, CH1: offset = 6 + 0*12 + 0*3 = 6
            Module 1, CH4: offset = 6 + 0*12 + 3*3 = 15
            Module 2, CH1: offset = 6 + 1*12 + 0*3 = 18
        """
        # Header 佔 6 bytes
        header_bytes = 6
        
        # 每個模組 4 通道 × 3 bytes = 12 bytes
        bytes_per_module = 12
        
        # 每個通道 3 bytes (Nominal Current, Programming Lock, Status)
        bytes_per_channel = 3
        
        # 計算偏移
        module_offset = header_bytes + (module - 1) * bytes_per_module
        channel_offset = module_offset + (channel - 1) * bytes_per_channel
        
        # 返回 Nominal Current 的位置 (通道 3 bytes 中的第 0 byte)
        return channel_offset
    
    def update_config_parameter(self, driver, byte_offset, new_value, data_type='USINT', debug=False):
        """
        安全更新 Config Assembly 的通用方法
        遵循: Read -> Modify -> Write 流程
        
        根據手冊 Table 7-11，Config Assembly 結構：
        - Instance: 0x66 (EDS Assem102)
        - 使用 Read-Modify-Write 確保不會破壞 Reserved 欄位
        
        Args:
            driver: CIPDriver 實例
            byte_offset: 要修改的 Byte 位置
            new_value: 新值
            data_type: 資料型態 ('USINT', 'INT', 'DINT', 'UDINT')
            debug: 是否顯示詳細資訊
        
        Returns:
            bool: True=成功, False=失敗
        """
        try:
            # 定義 Config Assembly 的路徑
            class_id = 0x04
            instance_id = self.config_instance  # 0x66
            attribute_id = 0x03
            
            if debug:
                print(f"\n[Config] Read-Modify-Write 流程開始...")
                print(f"   Class: 0x{class_id:02X}, Instance: 0x{instance_id:02X}, Attribute: {attribute_id}")
                print(f"   Offset: {byte_offset}, 新值: {new_value}, 型態: {data_type}")
            
            # ==========================================
            # STEP 1: READ (讀取目前的完整設定)
            # ==========================================
            if debug:
                print(f"\n   [步驟1] 讀取完整 Config Assembly...")
            
            response = driver.generic_message(
                service=0x0E,  # Get Attribute Single
                class_code=class_id,
                instance=instance_id,
                attribute=attribute_id,
                connected=True
            )
            
            if not response or (hasattr(response, 'error') and response.error):
                error_msg = response.error if hasattr(response, 'error') else '未知錯誤'
                print(f"   ❌ 讀取失敗: {error_msg}")
                return False
            
            current_data = bytearray(response.value)
            if debug:
                print(f"   ✅ 讀取成功，Config 長度: {len(current_data)} bytes")
            
            # ==========================================
            # STEP 2: MODIFY (修改指定位置)
            # ==========================================
            if debug:
                print(f"\n   [步驟2] 修改 Byte {byte_offset}...")
            
            # 檢查是否越界
            if byte_offset >= len(current_data):
                print(f"   ❌ 錯誤: Byte Offset {byte_offset} 超出範圍 (總長度 {len(current_data)})")
                return False
            
            # 保存舊值用於對比
            if data_type == 'USINT':
                old_value = current_data[byte_offset]
                struct.pack_into('<B', current_data, byte_offset, new_value)
            elif data_type == 'INT':
                old_value = struct.unpack_from('<H', current_data, byte_offset)[0]
                struct.pack_into('<H', current_data, byte_offset, new_value)
            elif data_type in ['DINT', 'UDINT']:
                old_value = struct.unpack_from('<I', current_data, byte_offset)[0]
                struct.pack_into('<I', current_data, byte_offset, new_value)
            else:
                print(f"   ❌ 不支援的資料型態: {data_type}")
                return False
            
            if debug:
                print(f"   舊值: {old_value} -> 新值: {new_value}")
            
            # ==========================================
            # STEP 3: WRITE (整包寫回)
            # ==========================================
            if debug:
                print(f"\n   [步驟3] 寫回完整 Config Assembly...")
            
            write_response = driver.generic_message(
                service=0x10,  # Set Attribute Single
                class_code=class_id,
                instance=instance_id,
                attribute=attribute_id,
                request_data=bytes(current_data),
                connected=True
            )
            
            if hasattr(write_response, 'error') and write_response.error:
                print(f"   ❌ 寫入失敗: {write_response.error}")
                return False
            
            if debug:
                print(f"   ✅ 寫入成功！")
            
            return True
            
        except Exception as e:
            print(f"   ❌ 發生異常: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def set_nominal_current(self, module, channel, current_amps, verify=True):
        """
        設定通道的額定電流（使用 Config Assembly）
        
        根據手冊 Table 7-11 & 7-18:
        - 每個通道在 Config Assembly 中有 3 bytes
        - Byte 0: Nominal Current (USINT, 1-20A)
        - Byte 1: Programming Lock
        - Byte 2: Status (0=Off, 1=On, 2=No Change)
        
        ⚠️ 關鍵修正：
        使用 Status Byte = 2 (No Change) 保護所有通道不被意外關閉！
        這樣只會修改電流，不會影響通道開關狀態。
        
        Args:
            module: 模組編號 (1-16)
            channel: 通道編號 (1-4)
            current_amps: 額定電流 (1-20A)
            verify: 是否驗證設定成功
        
        Returns:
            bool: True=成功, False=失敗
        """
        if not self.driver:
            print("❌ Driver 未初始化")
            return False
        
        # 驗證參數範圍
        if module < 1 or module > 16:
            print(f"❌ 模組編號超出範圍 (1-16): {module}")
            return False
        
        if channel < 1 or channel > self.channels_per_module:
            print(f"❌ 通道編號超出範圍 (1-{self.channels_per_module}): {channel}")
            return False
        
        if current_amps < 1 or current_amps > 20:
            print(f"❌ 額定電流超出範圍 (1-20A): {current_amps}")
            return False
        
        try:
            # 計算 Config Assembly 中的偏移
            base_offset = self.get_config_channel_offset(module, channel)
            offset_current = base_offset      # Nominal Current Byte
            offset_lock = base_offset + 1     # Programming Lock Byte  
            offset_status = base_offset + 2   # Status Byte
            
            # 顯示資訊
            global_ch = (module - 1) * self.channels_per_module + channel
            if self.module_count > 1:
                ch_label = f"M{module}.CH{channel} (#{global_ch})"
            else:
                ch_label = f"CH{global_ch}"
            
            print(f"\n[額定電流設定] {ch_label}")
            
            # ==========================================
            # 讀取當前額定電流值
            # ==========================================
            current_value = self._read_nominal_current_silent(self.driver, module, channel)
            if current_value is not None:
                print(f"⚠️  變更警告: {ch_label} 目前為 {current_value}A，修改設定為 {current_amps}A")
            # else:
            #     print(f"   目標電流: {current_amps}A")
            # print(f"   Config Offset: Byte {offset_current} (Current), {offset_status} (Status)")
            
            # ==========================================
            # STEP 1: READ - 讀取完整設定
            # ==========================================
            # print(f"   [步驟1] 讀取 Config Assembly...")
            
            response = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.config_instance,
                attribute=3,
                connected=True
            )
            
            if not response or (hasattr(response, 'error') and response.error):
                error_msg = response.error if hasattr(response, 'error') else '未知錯誤'
                print(f"   ❌ 讀取失敗: {error_msg}")
                return False
            
            config_data = bytearray(response.value)
            # print(f"   ✅ 讀取成功 (長度: {len(config_data)} bytes)")
            
            # ==========================================
            # STEP 2: MODIFY - 修改電流值
            # ==========================================
            # print(f"   [步驟2] 修改設定...")
            
            # 檢查偏移是否越界
            if offset_status >= len(config_data):
                print(f"   ❌ Offset 超出範圍")
                return False
            
            # 讀取舊值
            old_current = config_data[offset_current]
            old_status = config_data[offset_status]
            
            # 修改 Nominal Current
            struct.pack_into('<B', config_data, offset_current, current_amps)
            
            # ⚠️ 關鍵修正：將 Status 設為 2 (No Change)
            # 這樣只會更新電流，不會影響通道開關狀態
            struct.pack_into('<B', config_data, offset_status, 2)
            
            # print(f"   Nominal Current: {old_current}A -> {current_amps}A")
            # print(f"   Status: {old_status} -> 2 (No Change - 保持現狀)")
            
            # 進階保護：確保所有通道的 Status 都是 2 (No Change)
            # 這樣可以防止任何意外的 0 值關閉其他通道
            # print(f"   [保護] 設定所有通道 Status = 2 (No Change)...")
            
            # 遍歷所有模組和通道
            for m in range(1, 17):  # 最多 16 個模組
                for ch in range(1, 5):  # 每個模組 4 通道
                    ch_offset = self.get_config_channel_offset(m, ch)
                    ch_status_offset = ch_offset + 2
                    
                    # 確保不越界
                    if ch_status_offset < len(config_data):
                        # 如果是 0，改成 2 (No Change)
                        if config_data[ch_status_offset] == 0:
                            struct.pack_into('<B', config_data, ch_status_offset, 2)
            
            # print(f"   ✅ 所有通道已保護")
            
            # ==========================================
            # STEP 3: WRITE - 寫回完整設定
            # ==========================================
            # print(f"   [步驟3] 寫回 Config Assembly...")
            
            write_response = self.driver.generic_message(
                service=0x10,
                class_code=0x04,
                instance=self.config_instance,
                attribute=3,
                request_data=bytes(config_data),
                connected=True
            )
            
            if hasattr(write_response, 'error') and write_response.error:
                print(f"   ❌ 寫入失敗: {write_response.error}")
                return False
            
            # print(f"   ✅ Config Assembly 已更新")
            
            # 說明
            # print(f"\n   💡 機制說明:")
            # print(f"   - 使用 Status Byte = 2 (No Change) 保護所有通道")
            # print(f"   - 只會修改 {ch_label} 的額定電流")
            # print(f"   - 其他通道的開關狀態不會被影響！")
            
            # 驗證設定
            if verify:
                print(f"\n[驗證] 等待設備應用配置...")
                
                # 漸進式重試驗證（最多 3 秒）
                max_attempts = 6  # 6 次嘗試
                for attempt in range(1, max_attempts + 1):
                    time.sleep(0.5)  # 每次等 500ms
                    
                    actual = self._read_nominal_current_silent(self.driver, module, channel)
                    if actual is not None and actual == current_amps:
                        # 驗證成功
                        elapsed = attempt * 0.5
                        print(f"✅ 變更成功: {ch_label} 目前為 {actual}A (耗時: {elapsed:.1f}s)")
                        self.logger.info(f"{ch_label} 額定電流設為 {actual}A (耗時:{elapsed:.1f}s)", extra={'log_module': 'INIT', 'channel': global_ch, 'amps': actual, 'verified': True, 'elapsed': elapsed})
                        return True
                    elif attempt < max_attempts:
                        # 還沒成功，繼續等待
                        continue
                    else:
                        # 最後一次仍失敗
                        if actual is not None:
                            print(f"⚠️  驗證警告: 設備顯示 {actual}A，設定值 {current_amps}A")
                            print(f"   建議: 請使用 'verify {global_ch}' 命令再次確認")
                            self.logger.warning(f"{ch_label} 驗證警告: 設備顯示 {actual}A，設定值 {current_amps}A", extra={'log_module': 'INIT', 'channel': global_ch})
                        else:
                            print(f"⚠️  無法驗證（讀取失敗），但設定已寫入")
                        return True
            
            return True
            
        except Exception as e:
            print(f"   ❌ 發生異常: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _read_nominal_current_silent(self, driver, module, channel):
        """
        靜默讀取通道的額定電流設定（不顯示調試信息）
        
        Args:
            driver: CIPDriver 實例
            module: 模組編號
            channel: 通道編號
        
        Returns:
            int: 實際額定電流值 (0-20A), 或 None (讀取失敗)
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
                    return int(nominal_current)
            
            return None
            
        except Exception as e:
            return None
    
    def _wait_for_config_processing(self, driver, max_wait=10.0):
        """
        監測 Input Assembly Byte 0 Bit 7，等待配置處理完成
        
        根據手冊：
        - Bit 7 = 1: 設備正在處理配置 (Processing)
        - Bit 7 = 0: 處理完成 (Complete)
        
        Args:
            driver: CIPDriver 實例
            max_wait: 最長等待時間（秒）
        
        Returns:
            bool: True = 處理完成, False = 超時
        """
        start_time = time.time()
        check_count = 0
        processing_detected = False
        
        while time.time() - start_time < max_wait:
            check_count += 1
            elapsed = time.time() - start_time
            
            try:
                # 讀取 Input Assembly（使用 connected=True 加速）
                response = driver.generic_message(
                    service=0x0E,
                    class_code=0x04,
                    instance=self.input_instance,
                    attribute=3,
                    connected=True  # ⚡ 使用現有連線，更快
                )
                
                if not response or not hasattr(response, 'value') or len(response.value) == 0:
                    time.sleep(0.05)
                    continue
                
                byte0 = response.value[0]
                bit7 = (byte0 >> 7) & 0x01
                
                if bit7 == 1:
                    # 處理中
                    if not processing_detected:
                        print(f"   ⏳ 設備處理中 (Bit 7 = 1)...")
                        processing_detected = True
                    time.sleep(0.1)  # 處理中時等待 100ms
                    
                elif bit7 == 0:
                    # Bit 7 = 0 (處理完成或從未開始)
                    if processing_detected:
                        # 從 1 變 0：處理完成
                        print(f"   ✅ 處理完成 (耗時: {elapsed:.2f}s)")
                        return True
                    else:
                        # 從來沒偵測到 processing
                        # 可能：1) 設備處理極快，2) 根本不需要處理
                        # 直接認為已完成，不浪費時間
                        print(f"   ✅ 配置已應用 (即時)")
                        return True
                
            except Exception as e:
                time.sleep(0.05)
                continue
        
        # 超時
        print(f"   ⚠️  監測超時 ({max_wait}s)")
        return False
    
    def _verify_nominal_current(self, driver, module, channel):
        """
        驗證通道的額定電流設定（顯示詳細調試信息）
        
        Args:
            driver: CIPDriver 實例
            module: 模組編號
            channel: 通道編號
        
        Returns:
            int: 實際額定電流值 (0-20A), 或 None (讀取失敗)
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
    
    def set_channel(self, channel, state):
        """
        控制通道開關（基於手冊 7.1.2 節）
        
        Args:
            channel: 1-4
            state: True=開啟, False=關閉
        """
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
            print(f"       byte[1]: 0x{current_value:02X} -> 0x{new_value:02X}")
            self.logger.info(f"CH{channel} {'開啟' if state else '關閉'}", extra={'log_module': 'CTRL', 'channel': channel})
            
            # 雙模式：優先嘗試快速的 Implicit Messaging
            if self.implicit_mode_enabled:
                # 使用 I/O Worker 背景寫入
                print(f"       [Implicit] 更新到 buffer，等待 I/O Worker 寫入...")
                time.sleep(0.2)  # 等待至少一次 I/O 週期
                print(f"       ✅ 控制命令已提交")
            else:
                # 直接使用 generic_message 寫入
                try:
                    output_data = bytes(self.current_output_data)
                    
                    # DEBUG: 除錯模式（需要時取消註解）
                    # print(f"       [DEBUG] 寫入資料長度: {len(output_data)} bytes")
                    # print(f"       [DEBUG] byte[0]: 0x{output_data[0]:02X}, byte[1]: 0x{output_data[1]:02X}")
                    # print(f"       [DEBUG] 寫入 Assembly.0x{self.output_instance:02X}")
                    
                    response = self.driver.generic_message(
                        service=0x10,  # Set Attribute Single
                        class_code=0x04,  # Assembly Object
                        instance=self.output_instance,
                        attribute=3,
                        request_data=output_data,
                        connected=False
                    )
                    
                    # DEBUG: 除錯模式（需要時取消註解）
                    # if response:
                    #     print(f"       [DEBUG] Response 物件: {response}")
                    #     if hasattr(response, 'error'):
                    #         error_status = response.error if response.error else "None (成功)"
                    #         print(f"       [DEBUG] Error: {error_status}")
                    #     if hasattr(response, 'value'):
                    #         value_str = response.value if response.value else "b'' (空回應，正常)"
                    #         print(f"       [DEBUG] Value: {value_str}")
                    #         print(f"       [說明] Set 操作成功時通常回傳空值")
                    
                    if response and not (hasattr(response, 'error') and response.error):
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
                                if actual_byte1 == new_value:
                                    print(f"       ✅ 驗證成功 (設備 byte[1]=0x{actual_byte1:02X})")
                                else:
                                    print(f"       ⚠️ 驗證警告：設備 byte[1]=0x{actual_byte1:02X}, 預期=0x{new_value:02X}")
                        except Exception as ve:
                            print(f"       ⚠️ 無法驗證: {ve}")
                    else:
                        error_msg = response.error if hasattr(response, 'error') else '未知'
                        print(f"       ❌ 寫入失敗: {error_msg}")
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
    
    def _show_help_message(self):
        """顯示幫助信息（統一方法）"""
        print("\n" + "="*60)
        print("📋 可用命令:")
        print("="*60)
        print("\n【額定電流設定】")
        print("  init <ch> <amps>             - 設定通道額定電流 (1-20A)")
        print("                                 範例: init 2 4  (設定 CH2 為 4A)")
        print("                                 使用 Read-Modify-Write 安全更新")
        print("  verify <ch>                  - 驗證通道額定電流設定")
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
        print("\n【設備設定】")
        print("  setting                      - 進入設備設定選單")
        print("                                 (讀取/寫入設備網路 IP 等設定)")
        print("\n【系統】")
        print("  h / help                     - 顯示此幫助信息")
        print("  reconnect                    - 重新連線設備")
        print("  q                            - 退出程式")
        print("="*60)
        print("💡 快速開始:")
        print("  1. 使用 'init <ch> <amps>' 設定額定電流 (如: init 1 4)")
        print("  2. 使用 'on <ch>' 開啟通道 (如: on 1)")
        print("  3. 使用 's' 查看狀態")
        print("  4. 使用 'monitor start 2 silent' 啟動監控")
        print("="*60)
    
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
                        
                        # Byte 1: Nominal current (額定電流) 1-10A (直接值,不需除以10)
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
            state_icon = "🟢 開" if ch['is_on'] else "⚫ 關"
            
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
            self.monitor_thread.join(timeout=1)
        
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
            #   Byte 1: Nominal current (額定電流, 1A - 10A)
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
                        
                        # Byte 1: Nominal current (額定電流) 1-10A
                        nominal_current = data[base_offset + 1]
                        
                        # Byte 2: Flowing current (實際電流) 0-255 = 0-25.5A
                        current_raw = data[base_offset + 2]
                        current = current_raw / 10.0
                        
                        # 根據狀態位元判斷開關,而非電流值
                        state = "🟢 開" if is_on else "⚫ 關"
                        
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
                result['device_info']['device_type'] = 'CAPAROC PM EIP'
                    
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

    # ==================== 設備設定選單（Phase 3.6.3） ====================

    def _handle_write_device_ip(self, driver):
        """
        寫入新 IP 至設備的完整互動流程（雙重確認）。

        Returns:
            'reconnect' — 寫入成功，需以新 IP 重連
            None        — 取消或失敗
        """
        print("\n" + "="*60)
        print("✏️  寫入設備 IP 位址")
        print("="*60)

        # 先讀取目前設定，讓使用者確認
        print("正在讀取設備目前網路設定...")
        cfg = self.read_device_network_config(driver)
        if cfg['success']:
            print(f"  目前 IP:       {cfg['ip']}")
            print(f"  子網路遮罩:    {cfg['subnet']}")
            print(f"  預設閘道:      {cfg['gateway'] if cfg['gateway'] != '0.0.0.0' else '（未設定）'}")
            print(f"  IP 取得方式:   {cfg['config_control_str']}")
        else:
            print(f"  ⚠️  無法讀取目前設定: {cfg['error']}")
            print(f"  程式連線 IP: {self.device_ip}")

        print("\n" + "-"*60)
        print("請輸入新的 IP 設定（輸入 'cancel' 取消）")

        # --- 輸入新 IP ---
        while True:
            new_ip = input("\n新 IP 位址: ").strip()
            if new_ip.lower() == 'cancel':
                print("已取消")
                return None
            if self._validate_ip(new_ip):
                break
            print(f"  ⚠️  無效的 IP 格式: {new_ip}，請重新輸入")

        # --- 輸入 Subnet（可直接 Enter 採用預設） ---
        default_subnet = cfg['subnet'] if cfg['success'] and cfg['subnet'] else "255.255.255.0"
        subnet_input = input(f"子網路遮罩 [Enter=使用 {default_subnet}]: ").strip()
        if subnet_input == '':
            subnet = default_subnet
        elif self._validate_ip(subnet_input):
            subnet = subnet_input
        else:
            print(f"  ⚠️  無效格式，使用預設 {default_subnet}")
            subnet = default_subnet

        # --- 輸入 Gateway（可直接 Enter 採用空值） ---
        gateway_input = input("預設閘道 [Enter=不設定（0.0.0.0）]: ").strip()
        if gateway_input == '':
            gateway = ""
        elif self._validate_ip(gateway_input):
            gateway = gateway_input
        else:
            print("  ⚠️  無效格式，使用空值")
            gateway = ""

        gw_display = gateway if gateway else "0.0.0.0（不設定）"

        # --- 第一次確認 ---
        print("\n" + "="*60)
        print("⚠️  即將寫入以下設定至設備：")
        print(f"  新 IP:      {new_ip}")
        print(f"  子網路:     {subnet}")
        print(f"  閘道:       {gw_display}")
        print("="*60)
        print("⚠️  寫入後設備 IP 將立即變更，目前連線會中斷！")
        confirm1 = input("\n確認要繼續嗎？ [Y/N]: ").strip().upper()
        if confirm1 != 'Y':
            print("已取消")
            return None

        # --- 第二次確認（防誤觸） ---
        confirm2 = input(f"再次確認：將設備 IP 改為 {new_ip}？ [YES/no]: ").strip()
        if confirm2.lower() not in ('yes', 'y'):
            print("已取消")
            return None

        # --- 執行寫入 ---
        print(f"\n正在寫入 IP {new_ip} 至設備...")
        write_result = self.set_device_ip(driver, new_ip, subnet, gateway)

        if write_result['success']:
            print(f"✅ 寫入成功！設備 IP 已變更為 {new_ip}")
            print("   連線已中斷（正常），正在以新 IP 重新連線...")
            self.device_ip = new_ip
            return 'reconnect'
        else:
            print(f"❌ 寫入失敗: {write_result['error']}")
            print("   設備可能不支援此操作，或拒絕寫入")
            print("   提示：可使用 Phoenix Contact PRONETA 或 IP Address Wizard 設定 IP")
            return None

    def _handle_setting_command(self, driver):
        """
        設備設定子選單，供 CLI 主迴圈呼叫。

        Returns:
            'reconnect' — 需要重新連線（IP 已變更）
            None        — 正常返回主選單
        """
        while True:
            print("\n" + "="*60)
            print("⚙️  設備設定選單")
            print("="*60)
            print("  [1] 讀取目前設備網路設定")
            print("  [2] 寫入新 IP 至設備（硬寫設備 IP）")
            print("  [0] 返回主選單")
            print("="*60)

            choice = input("\n請選擇 [0/1/2]: ").strip()

            if choice == '0':
                return None

            elif choice == '1':
                print("\n正在讀取設備網路設定...")
                cfg = self.read_device_network_config(driver)
                print("\n" + "-"*40)
                if cfg['success']:
                    print(f"  IP 位址:     {cfg['ip']}")
                    print(f"  子網路遮罩:  {cfg['subnet']}")
                    print(f"  預設閘道:    {cfg['gateway'] if cfg['gateway'] != '0.0.0.0' else '（未設定）'}")
                    print(f"  IP 取得方式: {cfg['config_control_str']}")
                    if cfg['status'] != -1:
                        print(f"  介面狀態:    0x{cfg['status']:08X}")
                else:
                    print(f"  ❌ 讀取失敗: {cfg['error']}")
                    print("     設備可能不支援 CIP Class 0xF5")
                print("-"*40)

            elif choice == '2':
                result = self._handle_write_device_ip(driver)
                if result == 'reconnect':
                    return 'reconnect'

            else:
                print("  ⚠️  請輸入 0、1 或 2")

# ========== 主程式入口 ==========
    def run(self):
        self.logger.info("CAPAROC PM EIP Controller v3.7 啟動", extra={'log_module': 'SYS'})
        print("🚀 CAPAROC PM EIP Controller v3.7 beta")
        print("\n✅  目前可用功能:")
        print("1. 開關控制: 各模組通道進行啟閉控制")
        print("2. 狀態顯示: Global/channel 系統狀態檢查")
        print("3. 即時監控: 依據設定時間定時回傳系統狀態")
        print("4. 設備IP配置: 啟動時可變更設備 IP 位址")
        print("\n⚠️  待實作功能:")
        print("   1. 額定電流修改 (Phase 3-3)")
        print("   2. 通道資訊擴展 (Phase 3-4)")
        print("   3. GUI 規劃設計 (Phase 3-5)")
        
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
                    self.logger.error(f"連線失敗: {self.device_ip} - {conn_result.get('error', '未知錯誤')}", extra={'log_module': 'CONN', 'ip': self.device_ip})
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
                        print(f"  目前連線 IP: {self.device_ip}")
                        user_choice = input("\n請選擇: [R]重新連線 / [C]變更 IP / [Q]退出程式: ").strip().upper()
                        if user_choice == 'R':
                            print("\n🔄 嘗試重新連線...\n")
                            return 'reconnect'
                        elif user_choice == 'C':
                            new_ip = self._configure_device_ip()
                            if new_ip:
                                self.device_ip = new_ip
                                print(f"\n🔄 使用新 IP {self.device_ip} 重新連線...\n")
                                return 'reconnect'
                            # 取消則繼續顯示選單
                        elif user_choice == 'Q':
                            print("✅ 退出程式")
                            return
                        else:
                            print("   ⚠️  請輸入 R (重新連線)、C (變更 IP) 或 Q (退出)")
                    return
                
                # 連線成功，顯示設備資訊
                self.logger.info(f"已連線至 {self.device_ip}", extra={'log_module': 'CONN', 'ip': self.device_ip, 'modules': conn_result['device_info'].get('module_count', 0) if conn_result['device_info'] else 0, 'voltage': conn_result['device_info'].get('voltage', '') if conn_result['device_info'] else ''})
                print(f"✅ Pycomm3 TCP 連線成功! (尚未建立 CIP 連線)")
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
                print("🔍 Phase 3: Check global system status")
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
                        self.logger.error(error, extra={'log_module': 'SYS'})
                
                # 顯示警告訊息
                if status['warnings']:
                    print(f"\n⚠️  發現 {len(status['warnings'])} 個警告:")
                    for warning in status['warnings']:
                        print(f"   {warning}")
                        self.logger.warning(warning, extra={'log_module': 'SYS'})
                
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
                                
                                state_icon = "🟢 開" if is_on else "⚫ 關"
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
                
                # 啟動 CIP 連線狀態（必須執行，否則控制命令無效）
                # 💡 此時才真正建立 CIP 連線，WEB UI 才會顯示 connected
                self._activate_connection_state(driver)
                
                # 啟動心跳機制（保持連線活躍）
                self._start_heartbeat(driver)
                
                # 只在第一次連線時顯示幫助信息
                if not self.help_shown:
                    self._show_help_message()
                    self.help_shown = True
                else:
                    print("\n✅ 重新連線成功，可繼續使用命令（輸入 'h' 查看幫助）")
                
                while True:
                    try:
                        cmd = input("\n> ").strip().lower()
                        
                        if cmd == 'q' or cmd == 'quit':
                            print("\n🛑 正在退出程式...")
                            # 停止監控 (如果運行中)
                            if self.monitor_running:
                                self.stop_monitor()
                            # 停止心跳
                            self._stop_heartbeat()
                            self.logger.info("程式正常退出", extra={'log_module': 'SYS'})
                            print("✅ 退出程式")
                            break
                        
                        elif cmd == 'h' or cmd == 'help':
                            # 顯示幫助信息
                            self._show_help_message()
                        
                        elif cmd == 'reconnect':
                            print("\n🔄 嘗試重新連線...")
                            # 停止監控 (如果運行中)
                            if self.monitor_running:
                                self.stop_monitor()
                            # 停止心跳
                            self._stop_heartbeat()
                            return 'reconnect'
                        
                        elif cmd == 's' or cmd == 'status':
                            self._update_activity()
                            self.show_status()
                        
                        elif cmd.startswith('init '):
                            # 額定電流設定功能 (使用 Config Assembly Read-Modify-Write)
                            try:
                                parts = cmd.split()
                                if len(parts) != 3:
                                    print("\n⚠️  用法: init <通道編號> <電流值>")
                                    print("   範例: init 2 4  (設定 CH2 為 4A)")
                                    print("   電流範圍: 1-20A")
                                    continue
                                
                                global_ch = int(parts[1])
                                current_amps = int(parts[2])
                                
                                # 檢查通道範圍
                                if global_ch < 1 or global_ch > self.get_total_channels():
                                    print(f"⚠️  通道編號超出範圍 (1-{self.get_total_channels()})")
                                    continue
                                
                                # 檢查電流範圍
                                if current_amps < 1 or current_amps > 20:
                                    print(f"⚠️  電流值超出範圍 (1-20A): {current_amps}A")
                                    continue
                                
                                # 轉換為模組和通道
                                module, channel = self.get_module_and_channel(global_ch)
                                
                                # 執行設定
                                self.set_nominal_current(module, channel, current_amps, verify=True)
                                
                            except ValueError:
                                print("\n⚠️  參數格式錯誤")
                                print("   用法: init <通道編號> <電流值>")
                                print("   範例: init 2 4  (設定 CH2 為 4A)")
                            except Exception as e:
                                print(f"❌ 設定失敗: {e}")
                        
                        elif cmd.startswith('verify '):
                            # 驗證通道額定電流
                            try:
                                ch = int(cmd.split()[1])
                                if 1 <= ch <= self.get_total_channels():
                                    module, channel = self.get_module_and_channel(ch)
                                    actual = self._verify_nominal_current(driver, module, channel)
                                    if actual is not None:
                                        if self.module_count > 1:
                                            print(f"✅ M{module}.CH{channel} (#{ch}) 額定電流: {actual}A")
                                        else:
                                            print(f"✅ CH{ch} 額定電流: {actual}A")
                                    else:
                                        print(f"❌ 無法讀取 CH{ch} 的額定電流")
                                else:
                                    print(f"⚠️  通道編號超出範圍 (1-{self.get_total_channels()})")
                            except (ValueError, IndexError):
                                print("⚠️  用法: verify <通道編號>")
                        
                        elif cmd.startswith('on '):
                            self._update_activity()
                            ch = int(cmd.split()[1])
                            self.set_channel(ch, True)
                        elif cmd.startswith('off '):
                            self._update_activity()
                            ch = int(cmd.split()[1])
                            self.set_channel(ch, False)
                        elif cmd == 'setting':
                            result = self._handle_setting_command(driver)
                            if result == 'reconnect':
                                if self.monitor_running:
                                    self.stop_monitor()
                                self._stop_heartbeat()
                                return 'reconnect'

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
                        self._stop_heartbeat()
                        break
                    except Exception as e:
                        print(f"❌ 錯誤: {e}")
        
        except Exception as e:
            # 處理 CIPDriver 連線失敗
            print(f"\n❌ 裝置連線失敗!")
            self.logger.error(f"連線失敗（例外）: {self.device_ip} - {str(e)}", extra={'log_module': 'CONN', 'ip': self.device_ip})
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
                print(f"  目前連線 IP: {self.device_ip}")
                user_choice = input("\n請選擇: [R]重新連線 / [C]變更 IP / [Q]退出程式: ").strip().upper()
                if user_choice == 'R':
                    print("\n🔄 嘗試重新連線...\n")
                    return 'reconnect'
                elif user_choice == 'C':
                    new_ip = self._configure_device_ip()
                    if new_ip:
                        self.device_ip = new_ip
                        print(f"\n🔄 使用新 IP {self.device_ip} 重新連線...\n")
                        return 'reconnect'
                    # 取消則繼續顯示選單
                elif user_choice == 'Q':
                    print("✅ 退出程式")
                    return
                else:
                    print("   ⚠️  請輸入 R (重新連線)、C (變更 IP) 或 Q (退出)")

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
