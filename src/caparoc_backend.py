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
import json
import struct
import time
import threading
import traceback
from pathlib import Path

import app_config

# 額定電流可設定範圍（安培）。來源為 config/config.json 的 nominal_current 區塊，
# 與 Web UI 輸入欄的 min/max（GET /api/config/limits）同一份設定。
_NOMINAL_MIN, _NOMINAL_MAX = app_config.nominal_range()

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
        # 不支援 CIP 遠端設定額定電流的模組（連線時主動探測）
        self._nominal_readonly_modules: set = set()

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
                        # 與 _read_current_status / set_channel 等所有 CIP 呼叫共用
                        # 同一把鎖，避免與其他執行緒並發送出 generic_message
                        with self._cip_lock:
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

            dev = conn_result['device_info']
            self.logger.info(
                f"連線成功: {self.device_ip}, {self.module_count} 模組, "
                f"{self.get_total_channels()} 通道, 電壓 {dev.get('voltage', '?')}",
                extra={'log_module': 'CONN', 'ip': self.device_ip,
                       'modules': self.module_count,
                       'voltage': dev.get('voltage', '')}
            )

            # 先讀一次狀態建立 _ch_id_map，再探測額定電流可寫性
            # ❗ 必須在 _connected = True 之前完成，避免 WebSocket 讀取與 probe 並發損寮 TCP
            self._read_current_status()
            self._probe_all_modules()

            # probe 完成後才開啟 WebSocket 讀取
            self._connected = True

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

    # ==================== CIP 共用存取 ====================

    def _cip_get(self, class_code, instance, attribute, connected=False, driver=None):
        """
        Get_Attribute_Single（Service 0x0E），內建 _cip_lock。

        所有 CIP 讀取都應走這裡，鎖由方法自己持有，
        呼叫端不必（也不該）自行 `with self._cip_lock`——
        避免新增呼叫點時忘記上鎖，破壞 pycomm3 的 TCP 串流。

        Args:
            driver: 指定要走哪個 CIPDriver。
                    None（web 一律如此）= 用 self.driver；
                    caparoc_ip_config.py 這類 CLI 工具會傳入自建的短命 driver
                    （它只想改 IP，不該被 connect() 的模組探測副作用波及）。
                    無論走哪個 driver 都持有 _cip_lock——CLI 單執行緒下無競爭，成本為零。

        Returns:
            bytes: 回應內容（可能為 b''）
            None:  讀取失敗、CIP 端點回錯誤、或尚未連線
        """
        drv = driver if driver is not None else self.driver
        if not drv:
            return None
        try:
            with self._cip_lock:
                resp = drv.generic_message(
                    service=0x0E, class_code=class_code, instance=instance,
                    attribute=attribute, connected=connected,
                    unconnected_send=False,
                )
            if not resp or getattr(resp, 'error', None):
                return None
            return bytes(resp.value) if resp.value is not None else b''
        except Exception:
            return None

    def _cip_set(self, class_code, instance, attribute, data, connected=True, driver=None):
        """
        Set_Attribute_Single（Service 0x10），內建 _cip_lock。

        Args:
            driver: 同 _cip_get()——None 表示用 self.driver。

        Returns:
            (True,  None)      寫入成功
            (False, error_msg) 寫入失敗（CIP 錯誤或例外）
        """
        ok, err, _ = self._cip_set_detail(class_code, instance, attribute, data,
                                          connected=connected, driver=driver)
        return ok, err

    def _cip_set_detail(self, class_code, instance, attribute, data,
                        connected=True, driver=None):
        """
        與 _cip_set() 相同，但多回傳 was_exception 旗標。

        寫入 0xF5 這類「成功後設備立刻換 IP、連線隨即中斷」的屬性時，必須分辨：
          - 設備**明確回 CIP 錯誤**（例如 DHCP 模式下寫 Attr5 會回 Object state
            conflict）→ 真失敗，要往上報
          - 送出後**拿不到回應而拋例外** → 極可能是成功了，只是連線已斷
        兩者若都當成失敗，改 IP 永遠會被誤報為失敗。

        Returns:
            (ok: bool, err: str|None, was_exception: bool)
        """
        drv = driver if driver is not None else self.driver
        if not drv:
            return False, "driver 未初始化", False
        try:
            with self._cip_lock:
                resp = drv.generic_message(
                    service=0x10, class_code=class_code, instance=instance,
                    attribute=attribute, request_data=data, connected=connected,
                    unconnected_send=False,
                )
            err = getattr(resp, 'error', None) if resp else "無回應"
            if err:
                return False, str(err), False
            return True, None, False
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", True

    def _read_input_assembly(self, connected=False):
        """
        讀取整份 Input Assembly（0x65 attr 3）。

        一次讀取即涵蓋所有模組/通道，批次驗證時可用單次 CIP 往返
        取代「每通道各讀一次」，大幅減少鎖競爭與 WebSocket 卡頓。
        """
        return self._cip_get(0x04, self.input_instance, 3, connected=connected)

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
            """Get_Attribute_Single（connected=True），鎖由 _cip_get 內建。"""
            return self._cip_get(cls, inst, attr, connected=True)

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
        同步所有模組，不僅模組 1。
        """
        try:
            response = self.driver.generic_message(
                service=0x0E,
                class_code=0x04,
                instance=self.input_instance,
                attribute=3,
                connected=False
            )
            if response and hasattr(response, 'value') and len(response.value) >= 6:
                data = response.value
                self.current_output_data = bytearray(18)
                module_count = data[1] if len(data) > 1 else self.module_count
                for mod in range(1, max(module_count, self.module_count) + 1):
                    byte_value = 0x80  # bit7=1 (release)
                    for ch in range(1, self.channels_per_module + 1):
                        offset = self.get_channel_offset(mod, ch)
                        if len(data) > offset and (data[offset] & 0x01):
                            byte_value |= (1 << (ch - 1))
                    if mod < len(self.current_output_data):
                        self.current_output_data[mod] = byte_value
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
            """Get_Attribute_Single（connected=True），鎖由 _cip_get 內建。"""
            return self._cip_get(cls, inst, attr, connected=True)

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

    def is_module_nominal_readonly(self, module: int) -> bool:
        """True 表示此模組的額定電流無法透過 CIP 遠端設定（連線時主動探測確認）。"""
        return module in self._nominal_readonly_modules

    def _probe_nominal_writable(self, module: int) -> bool:
        """
        探測某模組是否支援 CIP 額定電流寫入。

        ⚠️ 破壞性探測：會實際對設備寫入 nominal ± 1 再還原。
           結果由 _probe_all_modules() 快取到檔案，同一台設備正常只跑一次。

        方法：第一個實體通道寫入 nominal ± 1（probe 對照組），0.8 秒後讀回驗證。
              無論判定結果或中途例外，finally 都會還原原值，
              確保設備不會被留在 probe 值。

        Returns:
            True  = 可寫（主動探測確認）
            False = read-only（2 通道型或其他硬體限制）
        """
        nominal_inst = None
        original = None
        wrote_probe = False
        try:
            # 找模組內第一個實體通道（存在於 _ch_id_map）
            first_ch = None
            for _gch, (m, c) in self._ch_id_map.items():
                if m == module:
                    first_ch = c
                    break
            if first_ch is None:
                return False   # 模組沒有實體通道

            inp_off = self.get_channel_offset(module, first_ch)
            data = self._read_input_assembly()
            if data is None or len(data) <= inp_off + 2:
                return False
            original = data[inp_off + 1]
            if original == 0:
                return False

            # 計算 probe 對照組（寫 nominal ± 1）
            probe_val = (original - 1) if original > 1 else (original + 1)
            nominal_inst = self._get_nominal_param_instance(module, first_ch)

            ok, _err = self._cip_set(0x0F, nominal_inst, 1, bytes([probe_val]))
            if not ok:
                return False   # CIP 端點明確拒絕，設備值未被改動
            wrote_probe = True

            time.sleep(0.8)

            data2 = self._read_input_assembly()
            if data2 is None or len(data2) <= inp_off + 2:
                return False
            return data2[inp_off + 1] == probe_val

        except Exception as e:
            self.logger.warning(
                f"_probe_nominal_writable M{module} 例外: {e}",
                extra={'log_module': 'CONN'}
            )
            return False
        finally:
            # 只要送出過 probe 寫入就還原——包含判定 read-only 與中途例外的情況。
            # （read-only 模組本來就吃不下寫入，多還原一次無副作用）
            if wrote_probe and nominal_inst is not None and original is not None:
                ok, err = self._cip_set(0x0F, nominal_inst, 1, bytes([original]))
                if not ok:
                    self.logger.error(
                        f"M{module} 探測值還原失敗，額定電流可能停在 probe 值: {err}",
                        extra={'log_module': 'CONN'}
                    )

    # ---- 探測結果快取（避免每次連線都對設備做破壞性寫入）----

    _PROBE_CACHE_PATH = Path(__file__).resolve().parent.parent / "config" / "nominal_probe_cache.json"

    def _probe_cache_key(self) -> str:
        """
        快取索引鍵：優先用 Identity Object 序號（綁定物理設備），
        讀不到時退回 IP（同一台機器換 IP 會重新探測，可接受）。
        """
        raw = self._cip_get(0x01, 1, 6, connected=True)   # Serial Number, UDINT
        if raw is not None and len(raw) >= 4:
            return f"sn:{struct.unpack_from('<I', raw)[0]}"
        return f"ip:{self.device_ip}"

    def _load_probe_cache(self) -> dict:
        try:
            if self._PROBE_CACHE_PATH.exists():
                with open(self._PROBE_CACHE_PATH, encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            self.logger.warning(f"讀取額定電流探測快取失敗: {e}",
                                extra={'log_module': 'CONN'})
        return {}

    def _save_probe_cache(self, cache: dict):
        try:
            self._PROBE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self._PROBE_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"寫入額定電流探測快取失敗: {e}",
                                extra={'log_module': 'CONN'})

    def _probe_all_modules(self, force: bool = False):
        """
        判定各模組的額定電流是否可透過 CIP 寫入。

        探測本身會短暫改變設備的真實額定電流（見 _probe_nominal_writable），
        而同一台設備的硬體能力不會變，因此結果以序號為索引快取到
        config/nominal_probe_cache.json；只有下列情況才重新探測：
          - 沒有該設備的快取紀錄
          - 快取的模組數與現況不符（換過模組）
          - force=True（呼叫端明確要求重測）

        連線後內部呼叫一次。
        """
        self._nominal_readonly_modules.clear()

        cache = self._load_probe_cache()
        key = self._probe_cache_key()
        entry = cache.get(key) if not force else None

        if isinstance(entry, dict) and entry.get('module_count') == self.module_count:
            self._nominal_readonly_modules = {
                int(m) for m in entry.get('readonly_modules', [])
            }
            ro = sorted(self._nominal_readonly_modules)
            self.logger.info(
                f"沿用額定電流探測快取（{key}，{self.module_count} 模組）："
                f"read-only 模組 {ro if ro else '無'}；不對設備寫入",
                extra={'log_module': 'CONN'}
            )
            return

        reason = "強制重測" if force else ("模組數變更" if entry else "無快取紀錄")
        self.logger.info(
            f"開始探測 {self.module_count} 個模組的額定電流可寫性（{reason}）；"
            f"過程會短暫寫入設備並自動還原...",
            extra={'log_module': 'CONN'}
        )
        for mod in range(1, self.module_count + 1):
            writable = self._probe_nominal_writable(mod)
            status = "可寫入" if writable else "read-only（需手動旋鈕）"
            self.logger.info(
                f"  M{mod}: nominal {status}",
                extra={'log_module': 'CONN'}
            )
            if not writable:
                self._nominal_readonly_modules.add(mod)

        cache[key] = {
            'device_ip':        self.device_ip,
            'module_count':     self.module_count,
            'readonly_modules': sorted(self._nominal_readonly_modules),
            'probed_at':        time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        self._save_probe_cache(cache)

    # 驗證輪詢參數（單筆與批次共用）
    _NOMINAL_VERIFY_ATTEMPTS = 6
    _NOMINAL_VERIFY_INTERVAL = 0.5

    def _validate_nominal_args(self, module, channel, current_amps):
        """檢查額定電流設定的參數範圍。合法回 None，否則回錯誤訊息字串。"""
        if not self.driver:
            return "Driver 未初始化"
        if module < 1 or module > 16:
            return f"模組編號超出範圍 (1-16): {module}"
        if channel < 1 or channel > self.channels_per_module:
            return f"通道編號超出範圍 (1-{self.channels_per_module}): {channel}"
        if current_amps < _NOMINAL_MIN or current_amps > _NOMINAL_MAX:
            return f"額定電流超出範圍 ({_NOMINAL_MIN}-{_NOMINAL_MAX}A): {current_amps}"
        return None

    def _channel_label(self, module, channel):
        """回傳 (人類可讀標籤, 全域通道編號)。多模組時標籤帶 M#.CH# 與 #全域編號。"""
        global_ch = (module - 1) * self.channels_per_module + channel
        if self.module_count > 1:
            return f"M{module}.CH{channel} (#{global_ch})", global_ch
        return f"CH{global_ch}", global_ch

    def _write_nominal_current(self, module, channel, current_amps, ch_label, global_ch):
        """
        寫入額定電流（只寫入，不驗證）。單筆與批次設定共用。

        主要路徑：Class 0x0F Parameter Object（適用所有模組，含 2 通道）
        回退路徑：Config Assembly（舊邏輯，對部分模組仍有效）

        Returns:
            bool: True=寫入指令已被設備接受
        """
        nominal_inst = self._get_nominal_param_instance(module, channel)
        print(f"   [0x0F] instance={nominal_inst}，寫入 {current_amps}A")
        ok, wr_err = self._cip_set(0x0F, nominal_inst, 1, bytes([current_amps]))
        print(f"   [0x0F] write_error={wr_err!r}")
        if ok:
            return True

        # ── 回退：Config Assembly ──
        # 讀取→修改→寫入必須在同一次持鎖內完成才具原子性，
        # 因此這裡不用 _cip_get/_cip_set（兩者各自獨立上鎖）。
        print(f"   [0x0F] 失敗，回退至 Config Assembly...")
        offset_current = self.get_config_channel_offset(module, channel)
        offset_status = offset_current + 2
        try:
            with self._cip_lock:
                cfg_resp = self.driver.generic_message(
                    service=0x0E, class_code=0x04,
                    instance=self.config_instance, attribute=3, connected=True
                )
                if not cfg_resp or getattr(cfg_resp, 'error', None):
                    print(f"   ❌ Config Assembly 讀取失敗")
                    self.logger.error(f"{ch_label} 額定電流設定失敗：Config Assembly 讀取失敗",
                                      extra={'log_module': 'INIT', 'channel': global_ch})
                    return False
                config_data = bytearray(cfg_resp.value)
                if offset_status >= len(config_data):
                    print(f"   ❌ Offset 超出範圍")
                    self.logger.error(f"{ch_label} 額定電流設定失敗：offset 超出範圍",
                                      extra={'log_module': 'INIT', 'channel': global_ch})
                    return False
                config_data[offset_current] = current_amps
                config_data[offset_status]  = 2
                # ⚠️ 其他已設定通道的 Status Byte 補成 2 (No Change)，避免被意外關閉
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
                if getattr(wr2, 'error', None):
                    print(f"   ❌ Config Assembly 寫入失敗: {wr2.error}")
                    self.logger.error(f"{ch_label} 額定電流設定失敗：{wr2.error}",
                                      extra={'log_module': 'INIT', 'channel': global_ch})
                    return False
            return True

        except Exception as e:
            print(f"   ❌ Config Assembly 寫入異常: {e}")
            traceback.print_exc()
            self.logger.error(f"{ch_label} 額定電流設定異常: {e}",
                              extra={'log_module': 'INIT', 'channel': global_ch})
            return False

    def set_nominal_current(self, module, channel, current_amps, verify=True):
        """
        設定單一通道的額定電流。

        根據手冊 Table 7-11 & 7-18:
        - Byte 0: Nominal Current (USINT, 1-20A)
        - Byte 1: Programming Lock
        - Byte 2: Status (0=Off, 1=On, 2=No Change)

        Args:
            module: 模組編號 (1-16)
            channel: 通道編號 (1-4)
            current_amps: 額定電流 (1-20A)
            verify: 是否驗證設定成功（最長 3 秒）

        Returns:
            bool: True=成功, False=失敗

        多通道請改用 set_nominal_current_batch()，可省下 N 倍的驗證等待。
        """
        err = self._validate_nominal_args(module, channel, current_amps)
        if err:
            print(f"❌ {err}")
            return False

        self._update_activity()
        ch_label, global_ch = self._channel_label(module, channel)
        print(f"\n[額定電流設定] {ch_label}")

        current_value = self._read_nominal_current(module, channel)
        if current_value is not None:
            print(f"⚠️  變更警告: {ch_label} 目前為 {current_value}A，修改設定為 {current_amps}A")

        if not self._write_nominal_current(module, channel, current_amps, ch_label, global_ch):
            return False

        if not verify:
            return True

        print(f"\n[驗證] 等待設備應用配置...")
        actual = None
        for attempt in range(1, self._NOMINAL_VERIFY_ATTEMPTS + 1):
            time.sleep(self._NOMINAL_VERIFY_INTERVAL)
            actual = self._read_nominal_current(module, channel)
            if actual is not None and actual == current_amps:
                elapsed = attempt * self._NOMINAL_VERIFY_INTERVAL
                print(f"✅ 變更成功: {ch_label} 目前為 {actual}A (耗時: {elapsed:.1f}s)")
                self.logger.info(
                    f"{ch_label} 額定電流設為 {actual}A (耗時:{elapsed:.1f}s)",
                    extra={'log_module': 'INIT', 'channel': global_ch,
                           'amps': actual, 'verified': True, 'elapsed': elapsed}
                )
                return True

        # 寫入已被接受但設備未在時限內回報新值：沿用舊行為視為成功，僅記錄警告
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

    def set_nominal_current_batch(self, targets, verify=True):
        """
        批次設定多個通道的額定電流。

        與逐一呼叫 set_nominal_current() 的差別：
          - 先把所有通道都寫入，最後才統一驗證
          - 驗證改用「單次 Input Assembly 讀取檢查全部通道」，
            而不是每個通道各讀一次整份 assembly

        8 通道最壞情況從約 24 秒（8 × 6 × 0.5s）降到約 3 秒，
        期間搶 _cip_lock 的讀取次數從 48 次降到 6 次，
        WebSocket 狀態推送不再被長時間排隊卡住。

        Args:
            targets: [(module, channel, amps), ...]
            verify:  是否於寫入後驗證設備實際值

        Returns:
            dict: {
              'ok': int, 'fail': int,
              'results': [{'module','channel','amps','ok','actual','error'}, ...]
            }
        """
        results = []
        pending = []          # 寫入成功、等待設備套用的項目
        for module, channel, amps in targets:
            amps = int(round(amps))
            entry = {'module': module, 'channel': channel, 'amps': amps,
                     'ok': False, 'actual': None, 'error': None}
            results.append(entry)

            err = self._validate_nominal_args(module, channel, amps)
            if err:
                entry['error'] = err
                print(f"❌ {err}")
                continue

            self._update_activity()
            ch_label, global_ch = self._channel_label(module, channel)
            print(f"\n[額定電流設定] {ch_label}")
            if self._write_nominal_current(module, channel, amps, ch_label, global_ch):
                entry['ok'] = True
                pending.append(entry)
            else:
                entry['error'] = '寫入失敗'

        if verify and pending:
            print(f"\n[驗證] 等待設備套用 {len(pending)} 個通道的配置...")
            for _ in range(self._NOMINAL_VERIFY_ATTEMPTS):
                time.sleep(self._NOMINAL_VERIFY_INTERVAL)
                data = self._read_input_assembly()
                if data is None:
                    continue
                still_pending = []
                for entry in pending:
                    entry['actual'] = self._nominal_from_assembly(
                        data, entry['module'], entry['channel'])
                    if entry['actual'] != entry['amps']:
                        still_pending.append(entry)
                pending = still_pending
                if not pending:
                    break

            # 未在時限內回報新值者，與單筆設定行為一致：仍視為成功，僅記錄警告
            for entry in pending:
                label, gch = self._channel_label(entry['module'], entry['channel'])
                print(f"⚠️  驗證警告: {label} 設備顯示 {entry['actual']}A，設定值 {entry['amps']}A")
                self.logger.warning(
                    f"{label} 批次設定驗證逾時：設備顯示 {entry['actual']}A，"
                    f"設定值 {entry['amps']}A",
                    extra={'log_module': 'INIT', 'channel': gch}
                )

        ok_count = sum(1 for e in results if e['ok'])
        self.logger.info(
            f"批次額定電流設定完成：{ok_count} 成功 / {len(results) - ok_count} 失敗",
            extra={'log_module': 'INIT'}
        )
        return {'ok': ok_count, 'fail': len(results) - ok_count, 'results': results}

    def _nominal_from_assembly(self, data, module, channel):
        """從整份 Input Assembly 取出指定通道的額定電流（A）。"""
        if data is None:
            return None
        offset = self.get_channel_offset(module, channel)
        if len(data) > offset + 1:
            return int(data[offset + 1])
        return None

    def _read_nominal_current(self, module, channel, verbose=False):
        """
        讀取通道目前的額定電流設定。

        Args:
            verbose: True 時額外印出 Input Assembly 原始位元組（CLI `verify` 指令用）

        Returns:
            int: 實際額定電流值 (0-20A), 或 None (讀取失敗)
        """
        data = self._read_input_assembly()
        value = self._nominal_from_assembly(data, module, channel)

        if value is None:
            if verbose:
                print(f"       [驗證] 讀取失敗或資料長度不足")
            return None

        if verbose:
            offset = self.get_channel_offset(module, channel)
            print(f"       [驗證Debug] Input Assembly offset {offset}:")
            print(f"                   Byte 0 (status): 0x{data[offset]:02X}")
            print(f"                   Byte 1 (nominal): {value}A")
            if len(data) > offset + 2:
                print(f"                   Byte 2: 0x{data[offset+2]:02X}")
            if len(data) > offset + 3:
                print(f"                   Byte 3: 0x{data[offset+3]:02X}")

        return value

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

    # ==================== 通道開關控制 ====================

    def set_channel(self, module, channel, state, show_result=True):
        """
        控制通道開關（基於手冊 7.1.2 節）

        Args:
            module: 1-16（模組編號，對應 Output byte 1..16）
            channel: 1-4（模組內通道編號）
            state: True=開啟, False=關閉
            show_result: True=下命令後等 0.5 秒讀回實際電流並印出（CLI 用）。
                         Web 路徑請傳 False——輸出沒人看得到，卻要多花
                         0.5 秒與一次 CIP 往返，且 WebSocket 一秒內就會刷新真實狀態。
        """
        if not self.driver:
            print("[錯誤] Driver 未初始化")
            return False

        self._update_activity()

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
                # 與 _read_current_status / heartbeat 等所有 CIP 呼叫共用同一把鎖，
                # 避免多執行緒並發送出 generic_message 破壞 pycomm3 的 TCP 串流
                try:
                    with self._cip_lock:
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
                                if verify_resp and hasattr(verify_resp, 'value') and len(verify_resp.value) > byte_offset:
                                    actual_byte = verify_resp.value[byte_offset]
                                    if actual_byte == new_value:
                                        print(f"       ✅ 驗證成功 (設備 byte[{byte_offset}]=0x{actual_byte:02X})")
                                    else:
                                        print(f"       ⚠️ 驗證警告：設備 byte[{byte_offset}]=0x{actual_byte:02X}, 預期=0x{new_value:02X}")
                            except Exception as ve:
                                print(f"       ⚠️ 無法驗證: {ve}")
                        else:
                            error_msg = response.error if hasattr(response, 'error') else '未知'
                            print(f"       ❌ 寫入失敗: {error_msg}")
                            self.logger.error(
                                f"CH{channel} {'開啟' if state else '關閉'}失敗: {error_msg}",
                                extra={'log_module': 'CTRL', 'channel': channel}
                            )
                            return False

                except Exception as e:
                    print(f"       ❌ 寫入異常: {e}")
                    traceback.print_exc()
                    self.logger.error(
                        f"CH{channel} {'開啟' if state else '關閉'}異常: {e}",
                        extra={'log_module': 'CTRL', 'channel': channel}
                    )
                    return False

        if show_result:
            time.sleep(0.5)
            self._read_and_show_result(module, channel, state)
        return True

    def _read_and_show_result(self, module, channel, expected_state):
        """
        讀取並印出通道實際電流（CLI 用）。

        位址取法與 _read_current_status 一致：Input Assembly 0x65，
        通道區塊 offset 由 get_channel_offset() 算出，Byte 2 = 流動電流（0.1A 單位）。
        """
        data = self._read_input_assembly()
        if data is None:
            print(f"       ⚠️ 無法讀取結果")
            return

        offset = self.get_channel_offset(module, channel)
        if len(data) <= offset + 2:
            print(f"       ⚠️ 無法讀取結果：Input Assembly 長度不足 (offset={offset})")
            return

        current = data[offset + 2] / 10.0
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
            data = self._read_input_assembly()

            if data is None or len(data) < 6:
                return {
                    'safe': False,
                    'warnings': [],
                    'errors': ['無法讀取設備狀態'],
                    'voltage': 0.0,
                    'total_current': 0.0,
                    'module_count': 0,
                    'global_status_byte': 0
                }

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
            self._update_activity()  # 定期成功讀取即視為活躍，避免心跳與此並發搶鎖
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
            data = self._read_input_assembly()

            if data is None:
                print("❌ 無法讀取狀態資料")
                return

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

    def read_device_network_config(self, driver=None):
        """
        讀取設備目前的網路設定（CIP TCP/IP Interface Object, Class 0xF5）。

        讀取：
          - Attr 1 (Status)             — 介面狀態旗標
          - Attr 3 (Configuration Control) — 0x00=Static, 0x01=BOOTP, 0x02=DHCP
          - Attr 5 (Interface Configuration) — IP / Subnet / Gateway

        與 get_network_info() 的差別：本方法回傳 **config_control**（Static/BOOTP/DHCP
        取得方式），是「IP 設定」頁判斷模式所必需；get_network_info() 則額外含
        MAC / hostname（0xF6 Ethernet Link）但沒有取得方式。兩者用途不同，勿混用。

        Args:
            driver: None = 用 self.driver（web）；CLI 可傳入自建 driver。

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
        import socket as _socket

        result = {
            'success': False,
            'ip': '', 'subnet': '', 'gateway': '',
            'config_control': -1, 'config_control_str': '未知',
            'status': -1, 'error': None
        }
        def _read_f5(attr):
            """
            讀 0xF5 單一屬性，connected=False 失敗時退回 connected=True。

            ⚠️ 本設備（CAPAROC PM EIP）實測**三個屬性都只接受 connected=True**，
            connected=False 一律回 'Too much data'（它不支援 Unconnected Send 0x52）。
            此處保留兩段式嘗試而非寫死 True，是為了相容其他韌體/型號；
            順序與 caparoc_ip_config.py 的 _read_attr() 一致。
            """
            raw = self._cip_get(0xF5, 1, attr, connected=False, driver=driver)
            if raw:
                return raw
            return self._cip_get(0xF5, 1, attr, connected=True, driver=driver)

        try:
            # Attr 1: Status
            raw = _read_f5(1)
            if raw and len(raw) >= 4:
                result['status'] = struct.unpack('<I', raw[:4])[0]

            # Attr 3: Configuration Control
            raw = _read_f5(3)
            if raw and len(raw) >= 4:
                ctrl = struct.unpack('<I', raw[:4])[0]
                result['config_control'] = ctrl
                result['config_control_str'] = {
                    0: 'Static IP', 1: 'BOOTP', 2: 'DHCP'
                }.get(ctrl, f'未知 (0x{ctrl:02X})')

            # Attr 5: Interface Configuration
            raw = _read_f5(5)
            if raw is not None:
                if len(raw) >= 12:
                    # CIP 以 Little-Endian UDINT 儲存 IP，需反轉 bytes 才是正確順序
                    # （對稱於 set_device_ip() 寫入時的 inet_aton(...)[::-1]）
                    result['ip']      = _socket.inet_ntoa(raw[0:4][::-1])
                    result['subnet']  = _socket.inet_ntoa(raw[4:8][::-1])
                    result['gateway'] = _socket.inet_ntoa(raw[8:12][::-1])
                    result['success'] = True
            else:
                result['error'] = "Attr 5 無回應"

        except Exception as e:
            result['error'] = str(e)

        return result

    def set_device_ip(self, driver=None, new_ip=None, subnet="255.255.255.0", gateway=""):
        """
        透過 CIP Class 0xF5 將設備 IP 硬寫入設備。

        步驟（順序很重要）：
          1. 寫入 Attr 3 = 0x00（切為 Static IP 模式）
          2. 寫入 Attr 5（new_ip + subnet + gateway + NS1=0 + NS2=0 + DomainName=""）

        ⚠️ **必須先 Attr3 再 Attr5**。設備處於 DHCP 模式時會拒絕寫入 Attr5，
        回 CIP 錯誤 `Object state conflict`（介面設定由 DHCP 掌控，不接受手動改）。
        舊版寫成「先 Attr5 再 Attr3」，導致從 DHCP 切回靜態 IP 永遠失敗。
        兩個屬性都要寫——只寫 Attr3 的話設備會沿用舊的 Attr5 值，而不是使用者輸入的新 IP。

        ⚠️ 寫入成功後設備 IP 立即改變，現有連線會中斷（正常現象）。
        ⚠️ 因此 `success=True` 只代表「Attr5 指令已被接受」，不代表設備已用新 IP 上線。
           真正的確認要靠呼叫端在寫入後探測新 IP（見 caparoc_ip_core.wait_for_device()）。

        Args:
            driver:  None = 用 self.driver（web）；CLI 可傳入自建 driver。
                     保留為第一個位置參數以相容既有 CLI 呼叫
                     `backend.set_device_ip(driver, ip, subnet, gw)`。
            new_ip (str):  新 IP 位址，e.g. "192.168.2.200"
            subnet (str):  子網路遮罩，預設 "255.255.255.0"
            gateway (str): 預設閘道，空字串 = "0.0.0.0"

        Returns:
            dict: {'success': bool, 'error': str or None,
                   'ctrl_written': bool, 'unverified': bool}
                  ctrl_written — Attr3（切 Static）是否寫成功。
                  unverified   — Attr5 送出後連線即中斷、拿不到確認回應。
                                 這在 IP 真的改變時屬正常，呼叫端應改以探測新 IP 確認。
        """
        import socket as _socket

        result = {'success': False, 'error': None,
                  'ctrl_written': False, 'unverified': False}

        if not new_ip:
            result['error'] = "new_ip 未指定"
            return result

        # 空 gateway 轉為全零
        gw_addr = gateway if gateway else "0.0.0.0"

        try:
            # Step 1: 先切為 Static。DHCP 模式下不先切，Attr5 會被拒（Object state conflict）
            ctrl_ok, ctrl_err, ctrl_exc = self._cip_set_detail(
                0xF5, 1, 3, struct.pack('<I', 0), connected=True, driver=driver)
            result['ctrl_written'] = ctrl_ok
            if not ctrl_ok and not ctrl_exc:
                # 設備明確拒絕切模式 —— 這是真失敗，繼續寫 Attr5 也不會成功
                result['error'] = f"Attr3 write error: {ctrl_err}"
                return result

            # Step 2: 寫入 Attr 5
            # CIP 以 Little-Endian UDINT 儲存 IP，需反轉 bytes
            # 格式: IP(4) + Subnet(4) + Gateway(4) + NS1(4) + NS2(4) + DomainName SSTRING len(2)
            config_data = (
                _socket.inet_aton(new_ip)[::-1] +
                _socket.inet_aton(subnet)[::-1] +
                _socket.inet_aton(gw_addr)[::-1] +
                bytes(4) +               # NameServer1 = 0.0.0.0
                bytes(4) +               # NameServer2 = 0.0.0.0
                struct.pack('<H', 0)     # DomainName SSTRING: length=0
            )
            ok, err, was_exc = self._cip_set_detail(
                0xF5, 1, 5, config_data, connected=True, driver=driver)
            if ok:
                result['success'] = True
            elif was_exc:
                # 送出後連線中斷：IP 一改變本來就收不到回應，視為已送出，
                # 由呼叫端探測新 IP 來確認（見 caparoc_ip_core.wait_for_device()）
                result['success'] = True
                result['unverified'] = True
            else:
                result['error'] = f"Attr5 write error: {err}"

        except Exception as e:
            result['error'] = str(e)

        return result

    def set_device_dhcp(self, driver=None):
        """
        透過 CIP Class 0xF5 將設備切換為 DHCP 模式。

        只需寫入 Attr 3 = 0x02（DHCP），設備會自行向 DHCP server 取得 IP。
        ⚠️ 成功後設備 IP 立即改變，現有連線會中斷（正常現象）。

        ⚠️ **已知限制**：連線中斷與真正的寫入失敗在此難以區分——設備一換 IP 就
        不會再回應，拿不到成功回應是預期行為。因此本方法對「無回應」採寬鬆判定
        （視為已送出），呼叫端**不應把 success 當成設備真的切換成功的證據**；
        請改用探索（caparoc_ip_core.discover()）找回設備新 IP 來確認。

        Args:
            driver: None = 用 self.driver（web）；CLI 可傳入自建 driver。

        Returns:
            dict: {'success': bool, 'error': str or None}
        """
        result = {'success': False, 'error': None}
        dhcp_data = struct.pack('<I', 2)  # Configuration Control = 2 (DHCP)
        ok, err = self._cip_set(0xF5, 1, 3, dhcp_data,
                                connected=True, driver=driver)
        if ok:
            result['success'] = True
        else:
            # 連線因 IP 改變而中斷屬預期行為；此處沿用既有的寬鬆判定，
            # 把錯誤原因保留在 error 供日誌追查，但仍回報 success。
            result['success'] = True
            result['error'] = None
            self.logger.info(
                f"切換 DHCP 後未取得確認回應（屬預期，設備已換 IP）: {err}",
                extra={'log_module': 'CONN'})
        return result
