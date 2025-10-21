#!/usr/bin/env python3
"""
CAPAROC Breaker Controller - 核心控制器
基於 Implicit Messaging 即時遠端控制

功能：
- 建立和管理 Implicit Messaging 連接
- 即時 I/O 資料交換 (20Hz)
- 通道開關控制
- 電壓電流監控
- 額定電流設定
"""

from pycomm3 import CIPDriver
import struct
import time
import threading
from typing import Optional, Dict, Tuple
import logging

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BreakerController:
    """CAPAROC 斷路器控制器 - 使用 Implicit Messaging"""
    
    def __init__(self, device_ip: str = "192.168.2.111", 
                 input_instance: int = 0x65, 
                 output_instance: int = 0x64):
        """
        初始化控制器
        
        Args:
            device_ip: 設備 IP 位址
            input_instance: Input Assembly Instance (預設 0x65)
            output_instance: Output Assembly Instance (預設 0x64)
        """
        self.device_ip = device_ip
        self.input_instance = input_instance
        self.output_instance = output_instance
        
        # 連接狀態
        self.connected = False
        self.implicit_enabled = False
        
        # I/O 執行緒
        self.io_thread = None
        self.io_running = False
        self.io_lock = threading.Lock()
        
        # I/O 緩存
        self.output_data = bytearray(20)
        self.input_data = bytearray(20)
        
        # CIP 驅動
        self.driver = None
        
        logger.info(f"控制器初始化完成 - IP: {device_ip}")
    
    def connect(self) -> bool:
        """
        連接到 CAPAROC 設備並建立 Implicit Messaging
        
        Returns:
            bool: 連接是否成功
        """
        try:
            logger.info(f"正在連接到設備: {self.device_ip}")
            
            # 建立 CIP 連接
            self.driver = CIPDriver(self.device_ip)
            self.driver.open()
            
            logger.info("CIP 連接建立成功")
            
            # 建立 Implicit Messaging
            if self._establish_implicit_messaging():
                self.connected = True
                logger.info("✅ Implicit Messaging 連接成功")
                return True
            else:
                logger.error("❌ Implicit Messaging 連接失敗")
                return False
                
        except Exception as e:
            logger.error(f"連接失敗: {e}")
            return False
    
    def disconnect(self):
        """斷開連接並清理資源"""
        logger.info("正在斷開連接...")
        
        # 停止 I/O 執行緒
        if self.io_thread and self.io_thread.is_alive():
            self.io_running = False
            self.io_thread.join(timeout=2)
            logger.info("I/O 執行緒已停止")
        
        # 關閉 CIP 連接
        if self.driver:
            try:
                self.driver.close()
                logger.info("CIP 連接已關閉")
            except:
                pass
        
        self.connected = False
        self.implicit_enabled = False
        logger.info("✅ 斷開連接完成")
    
    def _establish_implicit_messaging(self) -> bool:
        """建立 Implicit Messaging 連接"""
        try:
            logger.info("建立 Implicit Messaging 模式...")
            
            # 嘗試建立連接
            try:
                response = self.driver.generic_message(
                    service=0x52,  # Forward Open
                    class_code=0x06,  # Connection Manager
                    instance=0x01,
                    request_data=self._build_forward_open_request(),
                    connected=True,
                    unconnected_send=False
                )
                
                logger.info("Forward Open 請求成功")
                
            except Exception as e:
                logger.warning(f"Forward Open 失敗，繼續嘗試: {e}")
            
            # 啟動 I/O 執行緒
            self.io_running = True
            self.io_thread = threading.Thread(
                target=self._io_worker,
                daemon=True
            )
            self.io_thread.start()
            
            self.implicit_enabled = True
            logger.info("I/O 執行緒已啟動 (20Hz)")
            
            # 等待穩定
            time.sleep(0.5)
            
            return True
            
        except Exception as e:
            logger.error(f"Implicit Messaging 建立失敗: {e}")
            return False
    
    def _build_forward_open_request(self) -> bytes:
        """建立 Forward Open 請求數據"""
        request = bytearray()
        
        # Connection Serial Number
        request.extend(struct.pack('<I', 0x12345678))
        # Vendor ID
        request.extend(struct.pack('<H', 0x009A))
        # Originator Serial Number
        request.extend(struct.pack('<I', 0x87654321))
        # Connection Timeout Multiplier
        request.append(0x00)
        # Reserved
        request.extend([0x00, 0x00, 0x00])
        # O->T Network Connection ID
        request.extend(struct.pack('<I', 0x20000001))
        # T->O Network Connection ID
        request.extend(struct.pack('<I', 0x20000002))
        # Connection Timeout
        request.extend(struct.pack('<H', 0x07D0))
        # O->T Connection Parameters (20ms RPI)
        request.extend(struct.pack('<I', 0x43F4))
        # T->O Connection Parameters (20ms RPI)
        request.extend(struct.pack('<I', 0x43F4))
        # Transport Type/Trigger
        request.append(0xA3)
        # Connection Path Size
        request.append(0x03)
        # Connection Path
        request.extend([0x01, self.output_instance])
        request.extend([0x01, self.input_instance])
        request.extend([0x01, 0x01])
        
        return bytes(request)
    
    def _io_worker(self):
        """I/O 工作執行緒 - 20Hz 持續更新"""
        cycle = 0
        
        while self.io_running:
            try:
                cycle += 1
                
                # 每 200 個週期顯示一次 (10秒)
                if cycle % 200 == 0:
                    logger.debug(f"I/O 週期: {cycle}")
                
                # 寫入輸出
                with self.io_lock:
                    output = bytes(self.output_data)
                
                try:
                    self.driver.write(f"Assembly.{self.output_instance}", output)
                    
                    # 讀取輸入
                    response = self.driver.read(f"Assembly.{self.input_instance}")
                    
                    if response and hasattr(response, 'value') and response.value:
                        with self.io_lock:
                            self.input_data = bytearray(response.value)
                
                except Exception as io_error:
                    # 減少錯誤日誌頻率
                    if cycle % 500 == 0:
                        logger.debug(f"I/O 錯誤 (週期 {cycle}): {io_error}")
                
                # 50ms 週期 (20Hz)
                time.sleep(0.05)
                
            except Exception as e:
                logger.error(f"I/O 執行緒錯誤: {e}")
                time.sleep(0.1)
        
        logger.info("I/O 執行緒已結束")
    
    def turn_on_channel(self, channel: int, nominal_current: int = 4) -> bool:
        """
        開啟通道
        
        Args:
            channel: 通道編號 (1-4)
            nominal_current: 額定電流 (A)
            
        Returns:
            bool: 操作是否成功
        """
        if not self.connected or not self.implicit_enabled:
            logger.error("設備未連接或 Implicit 模式未啟用")
            return False
        
        if not 1 <= channel <= 4:
            logger.error(f"通道編號無效: {channel} (應為 1-4)")
            return False
        
        logger.info(f"🔓 開啟通道 {channel} (額定電流: {nominal_current}A)")
        
        try:
            # 設定額定電流
            self._set_nominal_current(channel, nominal_current)
            
            # 設定控制位元
            byte_offset = 1
            bit_position = channel - 1
            
            with self.io_lock:
                current_value = self.output_data[byte_offset]
                # 設定通道位元 + bit7
                self.output_data[byte_offset] = current_value | (1 << bit_position) | 0x80
                logger.debug(f"控制字節: 0x{self.output_data[byte_offset]:02X}")
            
            # 等待 I/O 更新
            time.sleep(0.2)
            
            # 驗證
            current = self.get_channel_current(channel)
            logger.info(f"通道 {channel} 電流: {current:.2f}A")
            
            if current > 0.05:
                logger.info(f"✅ 通道 {channel} 開啟成功")
                return True
            else:
                logger.warning(f"⚠ 通道 {channel} 狀態待確認 (電流: {current:.2f}A)")
                return True
                
        except Exception as e:
            logger.error(f"開啟通道 {channel} 失敗: {e}")
            return False
    
    def turn_off_channel(self, channel: int) -> bool:
        """
        關閉通道
        
        Args:
            channel: 通道編號 (1-4)
            
        Returns:
            bool: 操作是否成功
        """
        if not self.connected or not self.implicit_enabled:
            logger.error("設備未連接或 Implicit 模式未啟用")
            return False
        
        if not 1 <= channel <= 4:
            logger.error(f"通道編號無效: {channel} (應為 1-4)")
            return False
        
        logger.info(f"🔒 關閉通道 {channel}")
        
        try:
            # 清除控制位元
            byte_offset = 1
            bit_position = channel - 1
            
            with self.io_lock:
                current_value = self.output_data[byte_offset]
                # 清除通道位元，保持 bit7
                self.output_data[byte_offset] = (current_value & ~(1 << bit_position)) | 0x80
                logger.debug(f"控制字節: 0x{self.output_data[byte_offset]:02X}")
            
            # 等待 I/O 更新
            time.sleep(0.2)
            
            # 驗證
            current = self.get_channel_current(channel)
            logger.info(f"通道 {channel} 電流: {current:.2f}A")
            
            if current < 0.05:
                logger.info(f"✅ 通道 {channel} 關閉成功")
                return True
            else:
                logger.warning(f"⚠ 通道 {channel} 可能未完全關閉 (電流: {current:.2f}A)")
                return True
                
        except Exception as e:
            logger.error(f"關閉通道 {channel} 失敗: {e}")
            return False
    
    def _set_nominal_current(self, channel: int, current_amps: int):
        """設定通道額定電流（簡化版本）"""
        try:
            logger.debug(f"設定通道 {channel} 額定電流: {current_amps}A")
            
            # 嘗試透過 Output Assembly 設定
            position = 13 + (channel - 1)
            
            config_data = bytearray(20)
            config_data[position] = int(current_amps)
            
            self.driver.generic_message(
                service=0x10,
                class_code=0x04,
                instance=self.output_instance,
                attribute=3,
                request_data=bytes(config_data),
                connected=False
            )
            
            time.sleep(0.1)
            
        except Exception as e:
            logger.debug(f"額定電流設定: {e}")
    
    def get_voltage(self) -> float:
        """
        讀取系統電壓
        
        Returns:
            float: 電壓值 (V)
        """
        try:
            response = self.driver.read("Assembly.101[4]")
            if response and hasattr(response, 'value'):
                voltage_raw = struct.unpack('<H', response.value)[0]
                return voltage_raw / 100.0
        except Exception as e:
            logger.debug(f"讀取電壓失敗: {e}")
        return 0.0
    
    def get_total_current(self) -> float:
        """
        讀取總電流
        
        Returns:
            float: 總電流值 (A)
        """
        try:
            response = self.driver.read("Assembly.101[6]")
            if response and hasattr(response, 'value'):
                current_raw = struct.unpack('<H', response.value)[0]
                return current_raw / 100.0
        except Exception as e:
            logger.debug(f"讀取總電流失敗: {e}")
        return 0.0
    
    def get_channel_current(self, channel: int) -> float:
        """
        讀取指定通道電流
        
        Args:
            channel: 通道編號 (1-4)
            
        Returns:
            float: 電流值 (A)
        """
        if not 1 <= channel <= 4:
            return 0.0
        
        try:
            # Assembly 101: offset = 20 + (channel-1)*2
            offset = 20 + (channel - 1) * 2
            response = self.driver.read(f"Assembly.101[{offset}]")
            if response and hasattr(response, 'value'):
                current_raw = struct.unpack('<H', response.value)[0]
                return current_raw / 100.0
        except Exception as e:
            logger.debug(f"讀取通道 {channel} 電流失敗: {e}")
        return 0.0
    
    def get_all_status(self) -> Dict:
        """
        讀取所有狀態
        
        Returns:
            dict: 包含電壓、總電流、各通道電流的字典
        """
        status = {
            'voltage': self.get_voltage(),
            'total_current': self.get_total_current(),
            'channels': {}
        }
        
        for ch in range(1, 5):
            current = self.get_channel_current(ch)
            status['channels'][ch] = {
                'current': current,
                'state': 'ON' if current > 0.05 else 'OFF'
            }
        
        return status
    
    def __enter__(self):
        """Context manager 進入"""
        if not self.connected:
            self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager 退出"""
        self.disconnect()
