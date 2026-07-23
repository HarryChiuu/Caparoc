#!/usr/bin/env python3
"""
CAPAROC 後端操作層

提供裝置連線與控制的純邏輯層，供 CLI (caparoc_controller.py) 和 GUI (caparoc_gui.py) 共用。
本模組不包含 CLI 互動邏輯（input / help 訊息 / IP 設定）。

主要功能：
  - CIP 通訊（heartbeat 保活、連線狀態激活）
  - 通道開關控制（set_channel）
  - 額定電流設定（set_nominal_current）
  - 系統狀態讀取（check_global_system_status、_read_current_status）
  - 即時監控（start_monitor / stop_monitor）
  - 連線驗證（check_device_connection）

使用方式：
  from caparoc_backend import CaparocBackend
  backend = CaparocBackend("192.168.2.111")
"""

from pycomm3 import CIPDriver
import struct
import time
import threading
import traceback

try:
    from logging_manager import setup as _log_setup, get_logger
    _log_setup()
except ImportError:
    import logging
    def get_logger(name='caparoc'):
        return logging.getLogger(name)


class CaparocBackend:
    """CAPAROC 裝置操作後端（無 CLI 互動邏輯）"""

    def __init__(self, device_ip="192.168.2.111"):
        self.device_ip = device_ip
        self.output_instance = 0x64  # Output Assembly (EDS Assem100)
        self.input_instance = 0x65   # Input Assembly (EDS Assem101)
        self.config_instance = 0x66  # Config Assembly (EDS Assem102) - 僅用於讀取
        # ⚠️ 寫入配置使用 Parameter Object (Class 0x0F), 不是 Config Assembly!

        # 模組與通道配置（動態檢測）
        self.module_count = 0  # 初始化時檢測,支援 1-16 個模組
        self.channels_per_module = 4  # 每個模組最大掃描通道數（含空槽）
        # 動態對應表：由 _read_current_status 每次更新
        # { global_ch_id: (module, channel) }，正確反映實際通道佈局
        self._ch_id_map: dict[int, tuple[int, int]] = {}

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

        # 心跳機制 (保持連線)
        self.heartbeat_thread = None
        self.heartbeat_running = False
        self.heartbeat_interval = 300.0  # 預設 300 秒發送一次心跳
        self.last_activity_time = time.time()  # 記錄最後活動時間
        self.logger = get_logger()

        # 長駐連線管理（3.6.1 — 供 Web 服務使用）
        self._cip_driver = None   # CIPDriver 實例（context manager 外部持有）
        self._connected = False   # 連線狀態旗標

        # 設備通訊狀態追蹤（防止 log spam）
        self._last_read_ok = True    # _read_current_status 上次是否成功
        self._hb_fail_logged = False # heartbeat 連續失敗是否已記錄過

        # CIP 通訊锁：防止多執行緒並發 generic_message 破壞 TCP 串流
        self._cip_lock = threading.Lock()
        self._last_known_status = None   # _read_current_status 最後一次成功的快取

    # ==================== 通道偏移計算 ====================

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
        global_bytes = 6
        bytes_per_module = 12
        bytes_per_channel = 3
        module_offset = global_bytes + (module - 1) * bytes_per_module
        channel_offset = module_offset + (channel - 1) * bytes_per_channel
        return channel_offset

    def get_total_channels(self):
        """取得系統總通道數"""
        return self.module_count * self.channels_per_module

    def get_module_and_channel(self, global_channel):
        """
        將全域通道編號轉換為模組和通道。

        優先使用 _ch_id_map（由 _read_current_status 每次讀取硬體後更新），
        正確反映 2/4 通道混合安裝的實際佈局。
        連線前尚無資料時 fallback 至等差公式。

        Args:
            global_channel: 全域通道編號 (1-based)

        Returns:
            tuple: (module, channel)
        """
        if global_channel in self._ch_id_map:
            return self._ch_id_map[global_channel]
        # Fallback：連線前或地圖尚未建立時使用等差公式
        module = ((global_channel - 1) // self.channels_per_module) + 1
        channel = ((global_channel - 1) % self.channels_per_module) + 1
        return (module, channel)

    # ==================== 連線管理 ====================

    def _activate_connection_state(self, driver):
        """
        啟動 CIP 連線狀態

        關鍵發現：CAPAROC 設備需要在初始化時執行一次帶有 connected=True
        參數的請求，才能使後續的控制命令生效。
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
                idle_time = time.time() - self.last_activity_time

                if idle_time >= self.heartbeat_interval:
                    try:
                        driver.generic_message(
                            service=0x0E,
                            class_code=0x04,
                            instance=self.input_instance,
                            attribute=3,
                            connected=True,
                            unconnected_send=False
                        )
                        self.last_activity_time = time.time()
                        if self._hb_fail_logged:
                            self.logger.info(
                                f"心跳恢復正常 ({self.device_ip})",
                                extra={'log_module': 'CONN', 'ip': self.device_ip}
                            )
                            self._hb_fail_logged = False
                    except Exception as e:
                        if not self._hb_fail_logged:
                            self.logger.warning(
                                f"心跳失敗 ({self.device_ip})，設備可能已失聯: {e}",
                                extra={'log_module': 'CONN', 'ip': self.device_ip}
                            )
                            self._hb_fail_logged = True

                time.sleep(5.0)

            except Exception:
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

    # ==================== 長駐連線管理（3.6.1 — Web UI 用）====================

    @property
    def is_connected(self) -> bool:
        """回傳目前連線狀態（True = driver 已開啟且連線旗標有效）"""
        return self._connected and self.driver is not None

    def connect(self) -> bool:
        """
        建立並初始化 CIPDriver 連線（供 Web 服務長駐使用）。

        流程：
          1. 開啟 TCP 連線（CIPDriver.__enter__）
          2. 驗證裝置可讀取（check_device_connection）
          3. 從設備同步實際通道狀態至 output_data buffer
          4. _activate_connection_state（connected=True）
          5. 啟動 heartbeat 保活

        Returns:
            True  — 連線成功
            False — 連線失敗（driver 已被清理）
        """
        if self.is_connected:
            self.logger.warning("connect() 呼叫時已有連線，略過",
                                extra={'log_module': 'CONN'})
            return True

        try:
            self.logger.info(f"正在連線至 {self.device_ip}...",
                             extra={'log_module': 'CONN', 'ip': self.device_ip})

            self._cip_driver = CIPDriver(self.device_ip)
            self._cip_driver.__enter__()
            self.driver = self._cip_driver

            # 驗證裝置回應
            conn_result = self.check_device_connection(self.driver)
            if not conn_result['connected']:
                error = conn_result.get('error', '未知錯誤')
                self.logger.error(f"連線驗證失敗: {error}",
                                  extra={'log_module': 'CONN', 'ip': self.device_ip})
                self._cleanup_driver()
                return False

            # 儲存模組數量
            if conn_result['device_info']:
                self.module_count = conn_result['device_info'].get('module_count', 0)

            # 同步設備實際狀態至 output buffer（避免誤關正在運作的通道）
            self._sync_output_from_device()

            # 激活 CIP 連線狀態（必須執行，否則 set_channel 無效）
            self._activate_connection_state(self.driver)

            # 啟動心跳保活
            self._start_heartbeat(self.driver)

            self.channels_initialized = True
            self._connected = True

            dev = conn_result['device_info']
            self.logger.info(
                f"連線成功: {self.device_ip}, {self.module_count} 模組, "
                f"{self.get_total_channels()} 通道, 電壓 {dev.get('voltage', '?')}",
                extra={'log_module': 'CONN', 'ip': self.device_ip,
                       'modules': self.module_count,
                       'voltage': dev.get('voltage', '')}
            )
            return True

        except Exception as e:
            self.logger.error(f"connect() 例外: {e}",
                              extra={'log_module': 'CONN', 'ip': self.device_ip})
            self._cleanup_driver()
            return False

    def disconnect(self):
        """
        安全關閉連線（供 Web 服務停止或重連使用）。

        流程：
          1. 停止監控（如果運行中）
          2. 停止心跳
          3. 關閉 CIPDriver
        """
        self.logger.info(f"正在中斷連線: {self.device_ip}",
                         extra={'log_module': 'CONN', 'ip': self.device_ip})

        if self.monitor_running:
            self.stop_monitor()

        self._stop_heartbeat()
        self._cleanup_driver()
        self.channels_initialized = False

    def _cleanup_driver(self):
        """清理 CIPDriver 資源（內部方法，disconnect / 連線失敗時呼叫）"""
        self._connected = False
        if self._cip_driver is not None:
            try:
                self._cip_driver.__exit__(None, None, None)
            except Exception:
                pass
            self._cip_driver = None
        self.driver = None

    def get_network_info(self) -> dict:
        """
        讀取設備網路資訊。需已連線（connected=True）。
        每次 CIP 訊息都持有 _cip_lock，防止與 WebSocket 狀態讀取並發。

        回傳 dict：ip / subnet_mask / gateway / dns1 / dns2 / hostname / mac
        讀取失敗的欄位填 None，不影響其他欄位。
        """
        result = {
            "ip": None, "subnet_mask": None, "gateway": None,
            "dns1": None, "dns2": None, "hostname": None, "mac": None,
        }
        if not self.is_connected or self.driver is None:
            return result

        def _raw_to_ip(buf: bytes, offset: int = 0) -> str:
            """CIP 以 LE UDINT 儲存 IP 位址。
            先用 struct.unpack '<I' 讀成整數（位元組反轉），
            再以 big-endian bit-shift 逐 octet 取出，還原成正確點分十進位。"""
            v = struct.unpack_from('<I', buf, offset)[0]
            return f"{(v>>24)&0xFF}.{(v>>16)&0xFF}.{(v>>8)&0xFF}.{v&0xFF}"

        def _rd(cls, inst, attr):
            """Get_Attribute_Single（connected=True），持鎖避免並發損毀。"""
            try:
                with self._cip_lock:
                    resp = self.driver.generic_message(
                        service=0x0E, class_code=cls, instance=inst, attribute=attr,
                        connected=True, unconnected_send=False,
                    )
                if resp and not (hasattr(resp, 'error') and resp.error):
                    return bytes(resp.value) if resp.value is not None else b''
            except Exception:
                pass
            return None

        # TCP/IP Interface attr5: Interface Configuration（IP + Subnet + GW + DNS1 + DNS2 + Domain Name）
        raw = _rd(0xF5, 1, 5)
        if raw is not None and len(raw) >= 20:
            result["ip"]          = _raw_to_ip(raw, 0)
            result["subnet_mask"] = _raw_to_ip(raw, 4)
            result["gateway"]     = _raw_to_ip(raw, 8)
            result["dns1"]        = _raw_to_ip(raw, 12)
            result["dns2"]        = _raw_to_ip(raw, 16)
            # Domain Name：CIP STRING 格式（2-byte LE UINT 長度 + chars）
            if len(raw) >= 22:
                hn_len = struct.unpack_from('<H', raw, 20)[0]
                if 0 < hn_len <= 64 and len(raw) >= 22 + hn_len:
                    result["hostname"] = raw[22:22 + hn_len].decode('ascii', errors='replace').strip('\x00')

        # TCP/IP Interface attr6: Host Name（若 Domain Name 為空時的備援讀取）
        if not result["hostname"]:
            raw6 = _rd(0xF5, 1, 6)
            if raw6 is not None and len(raw6) >= 2:
                hn_len = struct.unpack_from('<H', raw6, 0)[0]
                if 0 < hn_len <= 64 and len(raw6) >= 2 + hn_len:
                    result["hostname"] = raw6[2:2 + hn_len].decode('ascii', errors='replace').strip('\x00')

        # Ethernet Link attr3: Physical Address（MAC 6 bytes）
        raw = _rd(0xF6, 1, 3)
        if raw is not None and len(raw) >= 6:
            result["mac"] = ":".join(f"{b:02X}" for b in raw[:6])

        return result

    def _sync_output_from_device(self):
        """
        讀取設備實際通道狀態，重建 output_data buffer。
        防止首次連線時誤關已在運行的通道。
        """
        try:
            response = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
                attribute=3,
                connected=False
            )
            if response and hasattr(response, 'value') and len(response.value) >= 18:
                data = response.value
                self.current_output_data = bytearray(18)
                byte1_value = 0x80  # bit7=1 (release)
                for ch in range(1, 5):
                    offset = self.get_channel_offset(1, ch)
                    if len(data) > offset and (data[offset] & 0x01):
                        byte1_value |= (1 << (ch - 1))
                self.current_output_data[1] = byte1_value
        except Exception:
            pass  # 同步失敗不影響後續操作，使用預設空白狀態

    def get_device_info(self) -> dict:
        """
        讀取設備識別資訊與全域設定參數。需已連線（connected=True）。
        每次 CIP 訊息都持有 _cip_lock，防止與 WebSocket 狀態讀取並發。

        回傳 dict：
          identity:      vendor_id / device_type / product_code /
                         revision_major / revision_minor / serial_number / product_name
          system_config: param_lock / ui_lock / switch_on_delay_ms / operating_mode
        讀取失敗的欄位填 None，不影響其他欄位。

        注意：CAPAROC 所有屬性皆需 connected=True；
              不可 fallback 至 unconnected_send，否則會破壞 CIP driver 內部狀態。
        """
        result = {
            "identity": {
                "vendor_id": None, "device_type": None, "product_code": None,
                "revision_major": None, "revision_minor": None,
                "serial_number": None, "product_name": None,
            },
            "system_config": {
                "param_lock": None, "ui_lock": None,
                "switch_on_delay_ms": None, "operating_mode": None,
            },
        }
        if not self.is_connected or self.driver is None:
            return result

        def _rd(cls, inst, attr):
            """Get_Attribute_Single（connected=True），持鎖避免並發損毀。"""
            try:
                with self._cip_lock:
                    resp = self.driver.generic_message(
                        service=0x0E, class_code=cls, instance=inst, attribute=attr,
                        connected=True, unconnected_send=False,
                    )
                if resp and not (hasattr(resp, 'error') and resp.error):
                    return bytes(resp.value) if resp.value is not None else b''
            except Exception:
                pass
            return None

        # ---- Identity Object (0x01, inst 1) — connected=True only ----
        for attr, size, key in (
            (1, 2, 'vendor_id'),
            (2, 2, 'device_type'),
            (3, 2, 'product_code'),
        ):
            raw = _rd(0x01, 1, attr)
            if raw is not None and len(raw) >= size:
                result["identity"][key] = struct.unpack_from('<H', raw)[0]

        # Revision: USINT.USINT = major (byte0) + minor (byte1)
        raw = _rd(0x01, 1, 4)
        if raw is not None and len(raw) >= 2:
            result["identity"]["revision_major"] = raw[0]
            result["identity"]["revision_minor"] = raw[1]

        # Serial Number: UDINT (4 bytes LE)
        raw = _rd(0x01, 1, 6)
        if raw is not None and len(raw) >= 4:
            result["identity"]["serial_number"] = struct.unpack_from('<I', raw)[0]

        # Product Name: CIP SHORT_STRING (1-byte len prefix + ASCII chars)
        raw = _rd(0x01, 1, 7)
        if raw is not None and len(raw) >= 1:
            slen = raw[0]
            if len(raw) >= 1 + slen:
                result["identity"]["product_name"] = raw[1:1 + slen].decode('ascii', errors='replace')

        # ---- Class 0x0F 全域設定（connected=True only）----
        raw = _rd(0x0F, 1, 1)  # Global current param lock (USINT)
        if raw is not None and len(raw) >= 1:
            result["system_config"]["param_lock"] = raw[0]

        raw = _rd(0x0F, 2, 1)  # Global user interface lock (USINT)
        if raw is not None and len(raw) >= 1:
            result["system_config"]["ui_lock"] = raw[0]

        raw = _rd(0x0F, 3, 1)  # Global switch-on delay (UINT, 2 bytes, ms)
        if raw is not None and len(raw) >= 2:
            result["system_config"]["switch_on_delay_ms"] = struct.unpack_from('<H', raw)[0]

        raw = _rd(0x0F, 4, 1)  # Global operating mode (USINT)
        if raw is not None and len(raw) >= 1:
            result["system_config"]["operating_mode"] = raw[0]

        return result

    # ==================== Config Assembly ====================

    def get_config_channel_offset(self, module, channel):
        """
        計算通道在 Config Assembly 中的 Nominal Current 位置

        根據手冊 Table 7-11 Structure of the config assembly:
        - Header: 6 bytes (Byte 0-5)
        - Body: 每個通道 3 bytes (Nominal Current, Programming Lock, Status)

        Args:
            module: 模組編號 (1-16)
            channel: 通道編號 (1-4)

        Returns:
            int: Nominal Current 的 Byte Offset
        """
        header_bytes = 6
        bytes_per_module = 12
        bytes_per_channel = 3
        module_offset = header_bytes + (module - 1) * bytes_per_module
        channel_offset = module_offset + (channel - 1) * bytes_per_channel
        return channel_offset

    def update_config_parameter(self, driver, byte_offset, new_value, data_type='USINT', debug=False):
        """
        安全更新 Config Assembly 的通用方法
        遵循: Read -> Modify -> Write 流程

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
            class_id = 0x04
            instance_id = self.config_instance  # 0x66
            attribute_id = 0x03

            if debug:
                print(f"\n[Config] Read-Modify-Write 流程開始...")
                print(f"   Class: 0x{class_id:02X}, Instance: 0x{instance_id:02X}, Attribute: {attribute_id}")
                print(f"   Offset: {byte_offset}, 新值: {new_value}, 型態: {data_type}")

            # STEP 1: READ
            if debug:
                print(f"\n   [步驟1] 讀取完整 Config Assembly...")

            response = driver.generic_message(
                service=0x0E,
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

            # STEP 2: MODIFY
            if debug:
                print(f"\n   [步驟2] 修改 Byte {byte_offset}...")

            if byte_offset >= len(current_data):
                print(f"   ❌ 錯誤: Byte Offset {byte_offset} 超出範圍 (總長度 {len(current_data)})")
                return False

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

            # STEP 3: WRITE
            if debug:
                print(f"\n   [步驟3] 寫回完整 Config Assembly...")

            write_response = driver.generic_message(
                service=0x10,
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
            traceback.print_exc()
            return False

    # ==================== 額定電流設定 ====================

    def _get_nominal_param_instance(self, module: int, channel: int) -> int:
        """
        計算 Class 0x0F (Parameter Object) 中對應通道額定電流的 instance 編號。

        掃描結果確認公式：instance = 5 + ((module-1)*4 + (channel-1))*3 + 1
        每個通道佔 3 個 instance：[Lock, Nominal, Status]
        """
        return 5 + ((module - 1) * 4 + (channel - 1)) * 3 + 1

    def set_nominal_current(self, module, channel, current_amps, verify=True):
        """
        設定通道的額定電流（使用 Config Assembly）

        根據手冊 Table 7-11 & 7-18:
        - Byte 0: Nominal Current (USINT, 1-20A)
        - Byte 1: Programming Lock
        - Byte 2: Status (0=Off, 1=On, 2=No Change)

        ⚠️ 關鍵修正：使用 Status Byte = 2 (No Change) 保護所有通道不被意外關閉！

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
            base_offset = self.get_config_channel_offset(module, channel)
            offset_current = base_offset
            offset_lock = base_offset + 1
            offset_status = base_offset + 2

            global_ch = (module - 1) * self.channels_per_module + channel
            if self.module_count > 1:
                ch_label = f"M{module}.CH{channel} (#{global_ch})"
            else:
                ch_label = f"CH{global_ch}"

            print(f"\n[額定電流設定] {ch_label}")

            current_value = self._read_nominal_current_silent(self.driver, module, channel)
            if current_value is not None:
                print(f"⚠️  變更警告: {ch_label} 目前為 {current_value}A，修改設定為 {current_amps}A")

            # ── 主要方法：Class 0x0F Parameter Object（適用所有模組，含 2 通道）──
            nominal_inst = self._get_nominal_param_instance(module, channel)
            print(f"   [0x0F] instance={nominal_inst}，寫入 {current_amps}A")
            write_response = self.driver.generic_message(
                service=0x10,
                class_code=0x0F,
                instance=nominal_inst,
                attribute=1,
                request_data=bytes([current_amps]),
                connected=True,
                unconnected_send=False,
            )
            wr_err = getattr(write_response, 'error', None)
            print(f"   [0x0F] write_error={wr_err!r}")

            if wr_err:
                # 備用方法：Config Assembly（舊邏輯，對部分模組仍有效）
                print(f"   [0x0F] 失敗，回退至 Config Assembly...")
                cfg_resp = self.driver.generic_message(
                    service=0x0E, class_code=0x04,
                    instance=self.config_instance, attribute=3, connected=True
                )
                if not cfg_resp or (hasattr(cfg_resp, 'error') and cfg_resp.error):
                    print(f"   ❌ Config Assembly 讀取失敗")
                    return False
                config_data = bytearray(cfg_resp.value)
                if offset_status >= len(config_data):
                    print(f"   ❌ Offset 超出範圍")
                    return False
                config_data[offset_current] = current_amps
                config_data[offset_status]  = 2
                for m in range(1, 17):
                    for ch in range(1, 5):
                        co = self.get_config_channel_offset(m, ch)
                        if co + 2 < len(config_data) and config_data[co] > 0 and config_data[co + 2] == 0:
                            config_data[co + 2] = 2
                wr2 = self.driver.generic_message(
                    service=0x10, class_code=0x04,
                    instance=self.config_instance, attribute=3,
                    request_data=bytes(config_data), connected=True
                )
                if hasattr(wr2, 'error') and wr2.error:
                    print(f"   ❌ Config Assembly 寫入失敗: {wr2.error}")
                    return False

            if verify:
                print(f"\n[驗證] 等待設備應用配置...")
                max_attempts = 6
                for attempt in range(1, max_attempts + 1):
                    time.sleep(0.5)
                    actual = self._read_nominal_current_silent(self.driver, module, channel)
                    if actual is not None and actual == current_amps:
                        elapsed = attempt * 0.5
                        print(f"✅ 變更成功: {ch_label} 目前為 {actual}A (耗時: {elapsed:.1f}s)")
                        self.logger.info(
                            f"{ch_label} 額定電流設為 {actual}A (耗時:{elapsed:.1f}s)",
                            extra={'log_module': 'INIT', 'channel': global_ch,
                                   'amps': actual, 'verified': True, 'elapsed': elapsed}
                        )
                        return True
                    elif attempt < max_attempts:
                        continue
                    else:
                        if actual is not None:
                            print(f"⚠️  驗證警告: 設備顯示 {actual}A，設定值 {current_amps}A")
                            print(f"   建議: 請使用 'verify {global_ch}' 命令再次確認")
                            self.logger.warning(
                                f"{ch_label} 驗證警告: 設備顯示 {actual}A，設定值 {current_amps}A",
                                extra={'log_module': 'INIT', 'channel': global_ch}
                            )
                        else:
                            print(f"⚠️  無法驗證（讀取失敗），但設定已寫入")
                        return True

            return True

        except Exception as e:
            print(f"   ❌ 發生異常: {e}")
            traceback.print_exc()
            return False

    def _read_nominal_current_silent(self, driver, module, channel):
        """
        靜默讀取通道的額定電流設定（不顯示調試信息）

        Returns:
            int: 實際額定電流值 (0-20A), 或 None (讀取失敗)
        """
        try:
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
                    return int(data[offset + 1])

            return None

        except Exception:
            return None

    def _wait_for_config_processing(self, driver, max_wait=10.0):
        """
        監測 Input Assembly Byte 0 Bit 7，等待配置處理完成

        Returns:
            bool: True = 處理完成, False = 超時
        """
        start_time = time.time()
        processing_detected = False

        while time.time() - start_time < max_wait:
            elapsed = time.time() - start_time
            try:
                response = driver.generic_message(
                    service=0x0E,
                    class_code=0x04,
                    instance=self.input_instance,
                    attribute=3,
                    connected=True
                )

                if not response or not hasattr(response, 'value') or len(response.value) == 0:
                    time.sleep(0.05)
                    continue

                byte0 = response.value[0]
                bit7 = (byte0 >> 7) & 0x01

                if bit7 == 1:
                    if not processing_detected:
                        print(f"   ⏳ 設備處理中 (Bit 7 = 1)...")
                        processing_detected = True
                    time.sleep(0.1)
                elif bit7 == 0:
                    if processing_detected:
                        print(f"   ✅ 處理完成 (耗時: {elapsed:.2f}s)")
                        return True
                    else:
                        print(f"   ✅ 配置已應用 (即時)")
                        return True

            except Exception:
                time.sleep(0.05)
                continue

        print(f"   ⚠️  監測超時 ({max_wait}s)")
        return False

    def _verify_nominal_current(self, driver, module, channel):
        """
        驗證通道的額定電流設定（顯示詳細調試信息）

        Returns:
            int: 實際額定電流值 (0-20A), 或 None (讀取失敗)
        """
        try:
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
                    nominal_current = data[offset + 1]

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

    # ==================== 通道開關控制 ====================

    def set_channel(self, module, channel, state):
        """
        控制通道開關（基於手冊 7.1.2 節）

        Args:
            module: 1-16（模組編號，對應 Output byte 1..16）
            channel: 1-4（模組內通道編號）
            state: True=開啟, False=關閉
        """
        if not self.driver:
            print("[錯誤] Driver 未初始化")
            return False

        with self.io_data_lock:
            byte_offset = module   # Module 1 -> byte 1, Module 2 -> byte 2, ...
            bit_position = channel - 1
            current_value = self.current_output_data[byte_offset]

            if state:
                new_value = current_value | (1 << bit_position) | 0x80
            else:
                new_value = (current_value & ~(1 << bit_position)) | 0x80

            self.current_output_data[byte_offset] = new_value

            print(f"[控制] M{module}-CH{channel} -> {'開啟' if state else '關閉'}")
            print(f"       byte[{byte_offset}]: 0x{current_value:02X} -> 0x{new_value:02X}")
            self.logger.info(
                f"CH{channel} {'開啟' if state else '關閉'}",
                extra={'log_module': 'CTRL', 'channel': channel}
            )

            if self.implicit_mode_enabled:
                print(f"       [Implicit] 更新到 buffer，等待 I/O Worker 寫入...")
                time.sleep(0.2)
                print(f"       ✅ 控制命令已提交")
            else:
                try:
                    output_data = bytes(self.current_output_data)
                    response = self.driver.generic_message(
                        service=0x10,
                        class_code=0x04,
                        instance=self.output_instance,
                        attribute=3,
                        request_data=output_data,
                        connected=False
                    )

                    if response and not (hasattr(response, 'error') and response.error):
                        try:
                            verify_resp = self.driver.generic_message(
                                service=0x0E,
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
                    traceback.print_exc()
                    return False

        time.sleep(0.5)
        self._read_and_show_result(channel, state)
        return True

    def _read_and_show_result(self, channel, expected_state):
        """讀取並顯示控制結果"""
        try:
            response = self.driver.generic_message(
                service=0x0E,
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

    # ==================== 系統狀態讀取 ====================

    def check_global_system_status(self):
        """
        檢查全域系統狀態（基於手冊 7.2.1-7.2.4）

        Returns:
            dict: {
                'safe': bool,
                'warnings': list,
                'errors': list,
                'voltage': float,
                'total_current': float,
                'module_count': int,
                'global_status_byte': int
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
            response = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
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

            global_status_byte = data[0]
            undervoltage      = bool(global_status_byte & 0x01)  # bit 0
            overvoltage       = bool(global_status_byte & 0x02)  # bit 1
            system_error      = bool(global_status_byte & 0x04)  # bit 2
            warning_80        = bool(global_status_byte & 0x08)  # bit 3
            total_shutdown    = bool(global_status_byte & 0x10)  # bit 4
            config_processing = bool(global_status_byte & 0x80)  # bit 7

            module_count = data[1] if len(data) > 1 else 0

            current_raw = struct.unpack('<H', data[2:4])[0]
            total_current = current_raw / 10.0

            voltage_raw = struct.unpack('<H', data[4:6])[0]
            voltage = voltage_raw / 100.0

            if module_count < 1:
                warnings.append("⚠️  未偵測到斷路器模組")
            elif module_count > 4:
                warnings.append(f"⚠️  偵測到 {module_count} 個模組（標準為 4 個）")

            if undervoltage:
                errors.append(f"⚡ 系統欠壓 (電壓: {voltage:.2f}V < 9.0V)")
            if overvoltage:
                errors.append(f"⚡ 系統過壓 (電壓: {voltage:.2f}V > 30.5V)")
            if system_error:
                errors.append("🔥 系統錯誤 (硬體故障或通訊異常)")
            if warning_80:
                warnings.append(f"⚠️  總電流已達80%警告閾值 (當前: {total_current:.2f}A)")
            if total_shutdown:
                warnings.append("🔴 總電流關斷已觸發 (系統已停止供電)")
            if config_processing:
                warnings.append("🔧 設備正在處理配置變更")

            if voltage < 9.0:
                errors.append(f"⚡ 電壓過低: {voltage:.2f}V (最低: 9.0V)")
            elif voltage > 30.5:
                errors.append(f"⚡ 電壓過高: {voltage:.2f}V (最高: 30.5V)")
            elif voltage < 18.0:
                warnings.append(f"⚠️  電壓偏低: {voltage:.2f}V (建議: 24V)")
            elif voltage > 26.0:
                warnings.append(f"⚠️  電壓偏高: {voltage:.2f}V (建議: 24V)")

            return {
                'safe':               len(errors) == 0,
                'warnings':           warnings,
                'errors':             errors,
                'voltage':            voltage,
                'total_current':      total_current,
                'module_count':       module_count,
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

    # ==================== 即時監控 ====================

    def _monitor_worker(self):
        """即時監控背景執行緒"""
        mode_str = "靜默模式 (僅警報)" if self.monitor_mode == 'silent' else "顯示模式"
        print(f"🔄 監控執行緒啟動 (更新頻率: {self.monitor_interval}s, {mode_str})")

        while self.monitor_running:
            try:
                current_status = self._read_current_status()

                if current_status:
                    changes = self._detect_changes(current_status)

                    # 將偵測到的變化寫入 log（_detect_changes 已做狀態轉換偵測，不會重複觸發）
                    for msg in changes['system_alerts']:
                        self.logger.warning(msg, extra={'log_module': 'CONN'})
                    for msg in changes['current_anomalies']:
                        self.logger.warning(msg, extra={'log_module': 'CONN'})
                    for msg in changes['channel_state_changes']:
                        self.logger.info(msg, extra={'log_module': 'CONN'})

                    if self.monitor_mode == 'display':
                        self._show_monitor_status(current_status, changes)
                    elif self.monitor_mode == 'silent':
                        if any([changes['channel_state_changes'],
                                changes['current_anomalies'],
                                changes['system_alerts']]):
                            self._show_monitor_alerts(changes)

                    with self.monitor_lock:
                        self.last_status_snapshot = current_status

                time.sleep(self.monitor_interval)

            except Exception as e:
                self.logger.error(f"監控執行緒錯誤: {e}", extra={'log_module': 'CONN'})
                time.sleep(self.monitor_interval)

        print("🛑 監控執行緒已停止")

    def _read_current_status(self):
        """讀取當前設備狀態 (用於監控)"""
        if not self.driver:
            return None

        # 嘗試取得 CIP 鎖（最多等 2 秒）。
        # 若 get_device_info / get_network_info 正在執行，每次 _rd() 僅持鎖 ~50ms，
        # 通常 2 秒內可以取得鎖。若超時則返回上次快取，避免觸發斷線。
        if not self._cip_lock.acquire(timeout=2.0):
            return self._last_known_status

        try:
            response = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
                attribute=3,
                connected=False
            )
        except Exception as e:
            # 通訊例外（網路斷線、TCP 超時等）。
            # 必須在此 catch 並 return None，不可讓例外傳播到 WebSocket handler——
            # 否則 handler 的 while 迴圈會被中斷，_ws_client_count 歸零，
            # 觸發伺服器自動 shutdown，且 backend.disconnect() 永遠不會被呼叫，
            # 導致 is_connected 維持 True，使用者無法重新連線。
            if self._last_read_ok:
                self.logger.warning(
                    f"設備失聯 ({self.device_ip})，讀取狀態失敗: {type(e).__name__}: {e}",
                    extra={'log_module': 'CONN', 'ip': self.device_ip}
                )
                self._last_read_ok = False
            return None   # finally 仍會執行，確保鎖被釋放
        finally:
            self._cip_lock.release()

        try:
            if not response or not hasattr(response, 'value'):
                if self._last_read_ok:
                    self.logger.warning(
                        f"設備失聯 ({self.device_ip})，CIP 回應無效",
                        extra={'log_module': 'CONN', 'ip': self.device_ip}
                    )
                    self._last_read_ok = False
                return None

            data = response.value

            global_status_byte = data[0] if len(data) > 0 else 0
            module_count       = data[1] if len(data) > 1 else 0

            total_current_raw = struct.unpack('<H', data[2:4])[0] if len(data) >= 4 else 0
            total_current = total_current_raw / 10.0

            voltage_raw = struct.unpack('<H', data[4:6])[0] if len(data) >= 6 else 0
            voltage = voltage_raw / 100.0

            channels = {}
            global_ch = 0
            for module in range(1, module_count + 1):
                for ch in range(1, self.channels_per_module + 1):
                    offset = self.get_channel_offset(module, ch)

                    if len(data) <= offset + 2:
                        break  # 資料不足，此模組後續通道也不會有資料

                    nominal_byte = data[offset + 1]
                    if nominal_byte == 0:
                        continue  # nominal_amps=0 代表空槽（非實體通道），跳過

                    global_ch += 1
                    status_byte  = data[offset]
                    flowing_byte = data[offset + 2]
                    self._ch_id_map[global_ch] = (module, ch)  # 更新對應表

                    channels[global_ch] = {
                        'module':          module,
                        'channel':         ch,
                        'is_on':           bool(status_byte & 0x01),
                        'flowing_current': flowing_byte / 10.0,
                        'nominal_current': float(nominal_byte),
                        'warning_80':      bool(status_byte & 0x02),
                        'overload':        bool(status_byte & 0x04),
                        'short_circuit':   bool(status_byte & 0x08),
                        'hardware_fault':  bool(status_byte & 0x10),
                        'total_shutdown':  bool(status_byte & 0x20),
                    }

            result = {
                'timestamp':         time.time(),
                'global_status_byte': global_status_byte,
                'module_count':      module_count,
                'total_current':     total_current,
                'voltage':           voltage,
                'channels':          channels
            }
            if not self._last_read_ok:
                self.logger.info(
                    f"設備恢復回應 ({self.device_ip})",
                    extra={'log_module': 'CONN', 'ip': self.device_ip}
                )
                self._last_read_ok = True
            self._last_known_status = result   # 更新快取
            return result

        except Exception as e:
            if self._last_read_ok:
                self.logger.warning(
                    f"設備失聯 ({self.device_ip})，讀取狀態失敗: {type(e).__name__}: {e}",
                    extra={'log_module': 'CONN', 'ip': self.device_ip}
                )
                self._last_read_ok = False
            return None

    def _detect_changes(self, current_status):
        """檢測狀態變化"""
        changes = {
            'channel_state_changes': [],
            'current_anomalies':     [],
            'system_alerts':         []
        }

        with self.monitor_lock:
            last = self.last_status_snapshot
            if not last:
                return changes

            for ch_num, ch_data in current_status['channels'].items():
                if ch_num not in last['channels']:
                    continue
                last_ch = last['channels'][ch_num]

                if self.module_count > 1:
                    ch_label = f"M{ch_data['module']}.CH{ch_data['channel']} (#{ch_num})"
                else:
                    ch_label = f"CH{ch_num}"

                if ch_data['is_on'] != last_ch['is_on']:
                    state_str = "開啟" if ch_data['is_on'] else "關閉"
                    changes['channel_state_changes'].append(f"{ch_label} 狀態變更: {state_str}")

                if ch_data['is_on'] and last_ch['is_on'] and last_ch['flowing_current'] > 0:
                    diff = abs(ch_data['flowing_current'] - last_ch['flowing_current'])
                    pct = (diff / last_ch['flowing_current']) * 100
                    if pct > 30:
                        changes['current_anomalies'].append(
                            f"{ch_label} 電流變化 {pct:.1f}%: "
                            f"{last_ch['flowing_current']:.1f}A → {ch_data['flowing_current']:.1f}A"
                        )

                if ch_data['warning_80'] and not last_ch['warning_80']:
                    changes['system_alerts'].append(f"{ch_label} ⚠️ 80% 警告")
                if ch_data['overload'] and not last_ch['overload']:
                    changes['system_alerts'].append(f"{ch_label} 🔴 過載")
                if ch_data['short_circuit'] and not last_ch['short_circuit']:
                    changes['system_alerts'].append(f"{ch_label} 🔴 短路")

            voltage_diff = abs(current_status['voltage'] - last['voltage'])
            if voltage_diff > 1.0:
                changes['system_alerts'].append(
                    f"電壓變化: {last['voltage']:.1f}V → {current_status['voltage']:.1f}V"
                )

        return changes

    def _show_monitor_status(self, status, changes):
        """顯示監控狀態 (display 模式)"""
        timestamp_str = time.strftime("%H:%M:%S", time.localtime(status['timestamp']))
        print(f"\n{'='*70}")
        print(f"🔄 即時監控 [{timestamp_str}] - 更新頻率: {self.monitor_interval}s")
        print(f"{'='*70}")
        print(f"📊 系統: {status['voltage']:.1f}V | {status['total_current']:.1f}A | {status['module_count']} 模組")
        print(f"\n{'通道':<15} {'狀態':<6} {'電流':<12} {'警告/錯誤'}")
        print("-" * 70)

        for ch_num in sorted(status['channels'].keys()):
            ch = status['channels'][ch_num]
            if self.module_count > 1:
                ch_label = f"M{ch['module']}.CH{ch['channel']} (#{ch_num})"
            else:
                ch_label = f"CH{ch_num}"

            state_icon = "🟢 開" if ch['is_on'] else "⚫ 關"
            current_str = f"{ch['flowing_current']:.1f}A / {ch['nominal_current']:.1f}A"

            alerts = []
            if ch['warning_80']:    alerts.append("⚠️ 80%")
            if ch['overload']:      alerts.append("❌ 過載")
            if ch['short_circuit']: alerts.append("❌ 短路")
            if ch['hardware_fault']:alerts.append("🔥 硬體故障")
            if ch['total_shutdown']:alerts.append("🔴 總電流關斷")
            alert_str = " ".join(alerts) if alerts else "✅"

            print(f"{ch_label:<15} {state_icon:<6} {current_str:<12} {alert_str}")

        if any([changes['channel_state_changes'], changes['current_anomalies'], changes['system_alerts']]):
            print(f"\n🔔 檢測到變化:")
            for change in changes['channel_state_changes']:
                print(f"  ▸ {change}")
            for anomaly in changes['current_anomalies']:
                print(f"  ▸ {anomaly}")
            for alert in changes['system_alerts']:
                print(f"  ▸ {alert}")

        print(f"{'='*70}")

    def _show_monitor_alerts(self, changes):
        """顯示監控警報 (silent 模式)"""
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
        print("> ", end='', flush=True)

    def start_monitor(self, interval=None, mode=None):
        """
        啟動即時監控

        Args:
            interval: 更新頻率(秒), 預設2.0
            mode: 'silent' 或 'display', 預設 'silent'
        """
        if self.monitor_running:
            print("⚠️  監控已在運行中")
            return False

        if interval is not None:
            if interval < 0.5:
                print(f"⚠️  更新頻率不能低於 0.5 秒")
                return False
            self.monitor_interval = interval

        if mode is not None:
            if mode not in ['silent', 'display']:
                print(f"⚠️  模式必須是 'silent' 或 'display'")
                return False
            self.monitor_mode = mode

        with self.monitor_lock:
            self.last_status_snapshot = {}

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

    # ==================== 狀態顯示 ====================

    def show_status(self):
        """顯示所有通道狀態 + 全域系統狀態（從設備讀取）"""
        if not self.driver:
            print("❌ Driver 未初始化")
            return

        try:
            print("\n📊 讀取設備狀態...")
            response_input = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
                attribute=3,
                connected=False
            )

            if not response_input or not hasattr(response_input, 'value'):
                print("❌ 無法讀取狀態資料")
                return

            data = response_input.value

            print("\n🌐 全域系統狀態:")
            if len(data) > 0:
                global_status_byte = data[0]
                status_icons = []
                if global_status_byte & 0x01: status_icons.append("⚡ 欠壓")
                if global_status_byte & 0x02: status_icons.append("⚡ 過壓")
                if global_status_byte & 0x04: status_icons.append("🔥 系統錯誤")
                if global_status_byte & 0x08: status_icons.append("⚠️  80%警告")
                if global_status_byte & 0x10: status_icons.append("🔴 總電流關斷")
                if global_status_byte & 0x80: status_icons.append("🔧 Config處理中")
                print("   " + " | ".join(status_icons) if status_icons else "   ✅ 正常")

            module_count = data[1] if len(data) > 1 else 0
            voltage = 0.0
            global_total_current = 0.0

            if len(data) >= 4:
                current_raw = struct.unpack('<H', data[2:4])[0]
                global_total_current = current_raw / 10.0

            if len(data) >= 6:
                voltage_raw = struct.unpack('<H', data[4:6])[0]
                voltage = voltage_raw / 100.0

            print(f"\n📊 系統參數:")
            print(f"   電壓: {voltage:.2f} V")
            print(f"   全域總電流: {global_total_current:.2f} A  (設備報告)")
            print(f"   模組數量: {module_count} 個")

            print("\n📊 通道狀態:")
            for module in range(1, module_count + 1):
                if module_count > 1:
                    print(f"\n   📦 模組 {module}:")
                print("   " + "─" * 40)

                for ch in range(1, self.channels_per_module + 1):
                    base_offset = self.get_channel_offset(module, ch)
                    global_ch = (module - 1) * self.channels_per_module + ch

                    if len(data) > base_offset + 2:
                        status_byte = data[base_offset]
                        is_on     = bool(status_byte & 0x01)
                        w80       = bool(status_byte & 0x02)
                        overload  = bool(status_byte & 0x04)
                        short_cir = bool(status_byte & 0x08)
                        hw_fault  = bool(status_byte & 0x10)
                        tot_shut  = bool(status_byte & 0x20)

                        nominal_current = data[base_offset + 1]
                        current = data[base_offset + 2] / 10.0

                        state = "🟢 開" if is_on else "⚫ 關"
                        if module_count > 1:
                            msg = f"   M{module}.CH{ch} (#{global_ch}): {state}  {current:.2f}A / {nominal_current}A"
                        else:
                            msg = f"   CH{ch}: {state}  {current:.2f}A / {nominal_current}A"

                        warn_list = []
                        if is_on and current < 0.05: warn_list.append("無負載")
                        if w80:      warn_list.append("⚠️ 80%")
                        if overload: warn_list.append("❌ 過載")
                        if short_cir:warn_list.append("❌ 短路")
                        if hw_fault: warn_list.append("🔥 硬體故障")
                        if tot_shut: warn_list.append("🔴 總電流關斷")
                        if warn_list:
                            msg += f" ({', '.join(warn_list)})"
                        print(msg)
                    else:
                        if module_count > 1:
                            print(f"   M{module}.CH{ch} (#{global_ch}): ⚠️ 資料不足 (offset {base_offset})")
                        else:
                            print(f"   CH{ch}: ⚠️ 資料不足 (offset {base_offset})")

            print("   " + "─" * 40)

        except Exception as e:
            print(f"❌ 讀取狀態失敗: {e}")
            traceback.print_exc()

    # ==================== 連線驗證 ====================

    def check_device_connection(self, driver):
        """
        檢查裝置連線狀態

        ⚠️ CAPAROC 不支援標準 Identity Object (Class 0x01)，改用讀取 Input Assembly 驗證。

        Returns:
            dict: {'connected': bool, 'error': str, 'device_info': dict}
        """
        result = {
            'connected': False,
            'error': None,
            'device_info': {}
        }

        try:
            response = driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
                attribute=3,
                connected=False
            )

            if response and hasattr(response, 'value') and len(response.value) >= 6:
                result['connected'] = True
                data = response.value

                if len(data) > 1:
                    module_count = data[1]
                    result['device_info']['module_count'] = module_count
                    result['device_info']['total_channels'] = module_count * 4

                if len(data) >= 6:
                    voltage_raw = struct.unpack('<H', data[4:6])[0]
                    voltage = voltage_raw / 100.0
                    result['device_info']['voltage'] = f"{voltage:.1f}V"

                result['device_info']['device_type'] = 'CAPAROC PM EIP'
            else:
                result['error'] = "設備無回應或 Input Assembly 讀取失敗"

        except Exception as e:
            result['error'] = f"連線失敗: {str(e)}"

        return result

    # ==================== 網路設定（CIP Class 0xF5） ====================

    def read_device_network_config(self, driver):
        """
        讀取設備目前的網路設定（CIP TCP/IP Interface Object, Class 0xF5）。

        讀取：
          - Attr 1 (Status)             — 介面狀態旗標
          - Attr 3 (Configuration Control) — 0x00=Static, 0x01=BOOTP, 0x02=DHCP
          - Attr 5 (Interface Configuration) — IP / Subnet / Gateway

        Returns:
            dict: {
                'success': bool,
                'ip': str, 'subnet': str, 'gateway': str,
                'config_control': int,  # 0=Static, 1=BOOTP, 2=DHCP
                'config_control_str': str,
                'status': int,
                'error': str or None
            }
        """
        result = {
            'success': False,
            'ip': '', 'subnet': '', 'gateway': '',
            'config_control': -1, 'config_control_str': '未知',
            'status': -1, 'error': None
        }
        try:
            # 讀取 Attr 1: Status
            resp_status = driver.generic_message(
                service=0x0E, class_code=0xF5, instance=1,
                attribute=1, connected=False
            )
            if resp_status and hasattr(resp_status, 'value'):
                raw = resp_status.value
                if len(raw) >= 4:
                    result['status'] = struct.unpack('<I', raw[:4])[0]

            # 讀取 Attr 3: Configuration Control
            resp_ctrl = driver.generic_message(
                service=0x0E, class_code=0xF5, instance=1,
                attribute=3, connected=False
            )
            if resp_ctrl and hasattr(resp_ctrl, 'value'):
                raw = resp_ctrl.value
                if len(raw) >= 4:
                    ctrl = struct.unpack('<I', raw[:4])[0]
                    result['config_control'] = ctrl
                    result['config_control_str'] = {
                        0: 'Static IP', 1: 'BOOTP', 2: 'DHCP'
                    }.get(ctrl, f'未知 (0x{ctrl:02X})')

            # 讀取 Attr 5: Interface Configuration
            resp_cfg = driver.generic_message(
                service=0x0E, class_code=0xF5, instance=1,
                attribute=5, connected=False
            )
            if resp_cfg and hasattr(resp_cfg, 'value'):
                raw = resp_cfg.value
                if len(raw) >= 12:
                    import socket as _socket
                    result['ip']      = _socket.inet_ntoa(raw[0:4])
                    result['subnet']  = _socket.inet_ntoa(raw[4:8])
                    result['gateway'] = _socket.inet_ntoa(raw[8:12])
                    result['success'] = True
            else:
                result['error'] = "Attr 5 無回應"

        except Exception as e:
            result['error'] = str(e)

        return result

    def set_device_ip(self, driver, new_ip, subnet="255.255.255.0", gateway=""):
        """
        透過 CIP Class 0xF5 將設備 IP 硬寫入設備。

        步驟：
          1. 寫入 Attr 3 = 0x00（強制 Static IP 模式）
          2. 寫入 Attr 5（new_ip + subnet + gateway + NS1=0 + NS2=0 + DomainName=""）

        ⚠️ 寫入成功後設備 IP 立即改變，現有連線會中斷（正常現象）。

        Args:
            driver: CIPDriver 實例（connected=False 模式）
            new_ip (str):  新 IP 位址，e.g. "192.168.2.200"
            subnet (str):  子網路遮罩，預設 "255.255.255.0"
            gateway (str): 預設閘道，空字串 = "0.0.0.0"

        Returns:
            dict: {'success': bool, 'error': str or None}
        """
        import socket as _socket

        result = {'success': False, 'error': None}

        # 空 gateway 轉為全零
        gw_addr = gateway if gateway else "0.0.0.0"

        try:
            # Step 1: 寫入 Attr 3 = Static IP (DWORD = 0x00000000)
            static_data = struct.pack('<I', 0)
            resp_ctrl = driver.generic_message(
                service=0x10, class_code=0xF5, instance=1,
                attribute=3, request_data=static_data, connected=False
            )
            # generic_message 失敗時通常拋 Exception，不需額外檢查回傳值

            # Step 2: 組裝 Attr 5 資料
            # 格式: IP(4) + Subnet(4) + Gateway(4) + NS1(4) + NS2(4) + DomainName UDINT len(4) + data(0)
            config_data = (
                _socket.inet_aton(new_ip) +
                _socket.inet_aton(subnet) +
                _socket.inet_aton(gw_addr) +
                bytes(4) +               # NameServer1 = 0.0.0.0
                bytes(4) +               # NameServer2 = 0.0.0.0
                struct.pack('<H', 0)     # DomainName SSTRING: length=0
            )
            resp_cfg = driver.generic_message(
                service=0x10, class_code=0xF5, instance=1,
                attribute=5, request_data=config_data, connected=False
            )
            result['success'] = True

        except Exception as e:
            result['error'] = str(e)

        return result
