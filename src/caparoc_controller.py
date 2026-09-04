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

# 必須早於任何 print：stdout 被導向時 cp950 裝不下 emoji，會炸成
# UnicodeEncodeError 並被誤判為操作失敗（詳見 src/console_io.py）
from console_io import force_safe_stdio

force_safe_stdio()

from pycomm3 import CIPDriver  # noqa: E402
import time  # noqa: E402
import threading  # noqa: E402
from caparoc_backend import CaparocBackend  # noqa: E402

# 設定統一由 app_config 提供（config/config.json）；下面兩支保留為薄包裝，
# 讓既有呼叫點（_ask_save_default_ip / _handle_setting_connip 等）不需改動。
import app_config  # noqa: E402

_CONFIG_PATH = app_config.CONFIG_PATH


def _load_default_ip():
    """從 config/config.json 的 device.default_ip 讀取預設 IP"""
    return app_config.get('device', 'default_ip')


def _save_default_ip(ip):
    """將指定 IP 寫入 config/config.json 的 device.default_ip（保留其他區塊）"""
    return app_config.save_device_ip(ip)

try:
    from logging_manager import setup as _log_setup, get_logger
    _log_setup()
except ImportError:
    import logging
    def get_logger(name='caparoc'):
        return logging.getLogger(name)


class CaparocController(CaparocBackend):
    """CLI 包裝層：繼承 CaparocBackend，加上命令列介面"""
    
    def __init__(self, device_ip=None):
        if device_ip is None:
            device_ip = _load_default_ip()
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

    # ==================== CLI 介面層 ====================

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
        print("  s <ch>                       - 單一通道詳細狀態 (例: s 1)")
        print("                                 （使用率/狀態位元 bit 0-5 逐項解析）")
        print("  device info                  - 設備識別資訊與全域設定")
        print("                                 （產品名稱/韌體版本/序號/運作模式/鎖定狀態）")
        print("  network info                 - 設備網路資訊")
        print("                                 （IP/遮罩/閘道/DNS/主機名稱/MAC）")
        print("\n【即時監控】")
        print("  monitor start [interval] [mode]  - 啟動監控")
        print("                                     interval: 更新頻率(秒), 預設2")
        print("                                     mode: silent/display, 預設silent")
        print("                                     範例: monitor start 5 silent")
        print("  monitor stop                 - 停止監控")
        print("  monitor status               - 顯示監控狀態")
        print("\n【連線設定】")
        print(f"  目前連線 IP: {self.device_ip}")
        print("  setting                      - 連線設定選單")
        print("                                 [1] 變更並連線（輸入新 IP，立即重連）")
        print("                                 [2] 恢復預設值（使用 config.json IP 重連）")
        print("                                 [3] 存為預設值（存下目前連線 IP）")
        print("                                 [4] 硬體 IP 修改（CIP 寫入設備，自動存檔）")
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
                    self._ask_save_default_ip(new_ip)
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

    def _ask_save_default_ip(self, new_ip):
        """詢問是否將 new_ip 存為預設 IP，並執行寫入。"""
        save = input(f"  是否將 {new_ip} 存為預設 IP？ [Y/N]: ").strip().upper()
        if save == 'Y':
            if _save_default_ip(new_ip):
                print(f"  ✅ 已儲存 {new_ip} 為預設 IP")
            # 失敗訊息由 _save_default_ip 內部顯示

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
            old_ip = self.device_ip
            self.device_ip = new_ip
            # 自動存檔：硬體改完 IP，程式的預設紀錄同步更新
            if _save_default_ip(new_ip):
                print(f"   ✅ 已自動存入 config.json 作為預設 IP")
            self.logger.info(f"硬體 IP 寫入成功: {old_ip} → {new_ip}（CIP 0xF5，已存檔）", extra={'log_module': 'SETTING', 'ip': new_ip})
            print("   連線已中斷（正常），正在以新 IP 重新連線...")
            return 'reconnect'
        else:
            print(f"❌ 寫入失敗: {write_result['error']}")
            print("   設備可能不支援此操作，或拒絕寫入")
            print("   提示：可使用 Phoenix Contact PRONETA 或 IP Address Wizard 設定 IP")
            return None

    def _handle_setting_connip(self, driver=None):
        """
        連線設定選單（setting 指令）。

        [1] 變更並連線    — 輸入新 IP → 立即重連
        [2] 恢復預設值    — 讀取 config.json 的 IP → 立即重連
        [3] 存為預設值    — 將目前連線中的 IP 寫入 config.json（不重連）
        [4] 硬體 IP 修改  — CIP 寫入設備 → 自動存檔 → 重連
        [0] 返回主選單

        Returns:
            'reconnect' — 需要重新連線
            None        — 返回主選單
        """
        default_ip = _load_default_ip()
        while True:
            print("\n" + "="*60)
            print("⚙️  連線設定")
            print("="*60)
            print(f"  目前連線 IP: {self.device_ip}")
            print(f"  預設 IP:     {default_ip}  (config/config.json)")
            print("-"*60)
            print("  [1] 變更並連線       - 輸入新 IP，立即重連")
            print("  [2] 恢復預設值       - 使用 config.json 的 IP 重連")
            print("  [3] 存為預設值       - 將目前連線中的 IP 存入 config.json")
            print("  [4] 硬體 IP 修改     - 透過 CIP 修改設備 IP（成功後自動存檔並重連）")
            print("  [0] 返回主選單")
            print("="*60)

            choice = input("\n請選擇 [0/1/2/3/4]: ").strip()

            if choice == '0':
                return None

            elif choice == '1':
                new_ip = input("\n新 IP 位址 (或輸入 cancel 取消): ").strip()
                if new_ip.lower() == 'cancel':
                    continue
                if not self._validate_ip(new_ip):
                    print(f"  ⚠️  無效的 IP 格式: {new_ip}")
                    continue
                old_ip = self.device_ip
                self.device_ip = new_ip
                self.logger.info(f"連線 IP 變更: {old_ip} → {new_ip}（立即重連）", extra={'log_module': 'SETTING', 'ip': new_ip})
                print(f"  ✅ 連線 IP 已設為 {self.device_ip}")
                print(f"  🔄 使用新 IP 重新連線...")
                return 'reconnect'

            elif choice == '2':
                if self.device_ip == default_ip:
                    print(f"  ℹ️  連線 IP 已是預設值 {default_ip}，仍要重連？")
                    confirm = input("  [Y/N]: ").strip().upper()
                    if confirm != 'Y':
                        continue
                old_ip = self.device_ip
                self.device_ip = default_ip
                self.logger.info(f"恢復預設 IP: {old_ip} → {default_ip}（立即重連）", extra={'log_module': 'SETTING', 'ip': default_ip})
                print(f"  ✅ 已恢復為預設 IP {self.device_ip}")
                print(f"  🔄 重新連線...")
                return 'reconnect'

            elif choice == '3':
                if _save_default_ip(self.device_ip):
                    self.logger.info(f"存為預設 IP: {self.device_ip}", extra={'log_module': 'SETTING', 'ip': self.device_ip})
                    print(f"  ✅ 已將 {self.device_ip} 設為預設 IP")
                    default_ip = self.device_ip  # 更新本地快取
                # 失敗訊息由 _save_default_ip 內部顯示

            elif choice == '4':
                if driver is None:
                    print("  ⚠️  無法進入硬體 IP 設定（driver 未就緒）")
                    continue
                result = self._handle_settingdeviceip_command(driver)
                if result == 'reconnect':
                    return 'reconnect'

            else:
                print("  ⚠️  請輸入 0 到 4 中的數字")

    def _handle_settingdeviceip_command(self, driver):
        """
        設備硬體 IP 設定選單（settingdeviceip 指令）。
        透過 CIP Class 0xF5 讀取/寫入設備本身的 IP。

        Returns:
            'reconnect' — 需要重新連線（IP 已變更）
            None        — 正常返回主選單
        """
        while True:
            print("\n" + "="*60)
            print("⚙️  設備硬體 IP 設定（CIP Class 0xF5）")
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

    # ==================== 設備資訊顯示（4.4.2 / 4.4.3）====================
    # 兩支都只做顯示，資料來源是 CaparocBackend 既有的 get_device_info() /
    # get_network_info()（Web UI 系統狀態頁與連線設定頁用的是同兩支）。
    # 用語刻意與 Web UI 的面板一致，避免同一個欄位在兩個介面叫不同名字。

    # 未知代碼一律顯示原始數值，不要猜——設備韌體版本不同可能有新值
    _PARAM_LOCK_TEXT = {0: '未鎖定', 1: '已鎖定'}
    _OPERATING_MODE_TEXT = {0: 'Independent（獨立控制）', 1: 'Wait for fieldbus（等待匯流排）'}

    @staticmethod
    def _fmt_val(val, suffix=''):
        """None（讀取失敗的欄位）統一顯示為 —，其餘加上單位。"""
        return '—' if val is None else f"{val}{suffix}"

    @classmethod
    def _fmt_enum(cls, val, table):
        """列舉值轉文字；表中沒有的值顯示 `原始值 (未知)`，不隱瞞。"""
        if val is None:
            return '—'
        return table.get(val, f"{val} (未知)")

    def show_device_info(self):
        """顯示設備識別資訊與全域設定（CLI `device info`）。"""
        if not self.is_connected:
            print("\n⚠️  尚未連線，無法讀取設備資訊")
            return

        print("\n📇 讀取設備識別資訊中...")
        info = self.get_device_info()
        ident = info.get('identity', {})
        sysc = info.get('system_config', {})

        rev = '—'
        if ident.get('revision_major') is not None and ident.get('revision_minor') is not None:
            rev = f"{ident['revision_major']}.{ident['revision_minor']}"

        vendor = '—'
        if ident.get('vendor_id') is not None:
            vendor = f"{ident['vendor_id']} (Phoenix Contact)"

        print("\n" + "="*52)
        print("📇 設備識別")
        print("="*52)
        print(f"  產品名稱:     {self._fmt_val(ident.get('product_name'))}")
        print(f"  廠商 ID:      {vendor}")
        print(f"  裝置類型:     {self._fmt_val(ident.get('device_type'))}")
        print(f"  產品代碼:     {self._fmt_val(ident.get('product_code'))}")
        print(f"  韌體版本:     {rev}")
        print(f"  序號:         {self._fmt_val(ident.get('serial_number'))}")
        print("-"*52)
        print("⚙️  全域設定")
        print("-"*52)
        print(f"  運作模式:         {self._fmt_enum(sysc.get('operating_mode'), self._OPERATING_MODE_TEXT)}")
        print(f"  通道循序啟動延遲: {self._fmt_val(sysc.get('switch_on_delay_ms'), ' ms')}")
        print(f"  電流參數鎖定:     {self._fmt_enum(sysc.get('param_lock'), self._PARAM_LOCK_TEXT)}")
        print(f"  按鈕介面鎖定:     {self._fmt_enum(sysc.get('ui_lock'), self._PARAM_LOCK_TEXT)}")
        print("="*52)

        # 全部欄位都是 None 代表 CIP 讀取整批失敗，而非設備真的沒有這些資料。
        # ⚠️ 必須用 `is None` 而非 `any()`——param_lock / ui_lock / operating_mode /
        # switch_on_delay_ms 四者同時為 0 是完全正常的設備狀態（未鎖定 + 無延遲 +
        # Independent 模式），`any()` 會把這種合法狀態誤判成讀取失敗。
        if (all(v is None for v in ident.values())
                and all(v is None for v in sysc.values())):
            print("  ⚠️  所有欄位皆讀取失敗，設備可能不支援 Identity Object 或連線已中斷")

    def show_network_info(self):
        """顯示設備網路資訊（CLI `network info`）。"""
        if not self.is_connected:
            print("\n⚠️  尚未連線，無法讀取網路資訊")
            return

        print("\n🌐 讀取設備網路資訊中...")
        net = self.get_network_info()

        print("\n" + "="*52)
        print("🌐 設備網路資訊")
        print("="*52)
        print(f"  IP 位址:      {self._fmt_val(net.get('ip'))}")
        print(f"  子網路遮罩:   {self._fmt_val(net.get('subnet_mask'))}")
        print(f"  預設閘道:     {self._fmt_val(net.get('gateway'))}")
        print(f"  DNS 1:        {self._fmt_val(net.get('dns1'))}")
        print(f"  DNS 2:        {self._fmt_val(net.get('dns2'))}")
        print(f"  主機名稱:     {self._fmt_val(net.get('hostname'))}")
        print(f"  MAC 位址:     {self._fmt_val(net.get('mac'))}")
        print("="*52)

        # 這裡讀到的 IP 是設備自己回報的，與我們連線用的位址不一定相同
        # （例如設備剛改過 IP 但我們還連在舊 session 上），不一致時明講
        dev_ip = net.get('ip')
        if dev_ip and dev_ip != self.device_ip:
            print(f"  ⚠️  設備回報的 IP ({dev_ip}) 與連線位址 ({self.device_ip}) 不同")
        # 同 show_device_info()：用 `is None` 而非 `any()`，空字串主機名稱不算失敗
        if all(v is None for v in net.values()):
            print("  ⚠️  所有欄位皆讀取失敗，設備可能不支援 CIP Class 0xF5/0xF6 或連線已中斷")
        else:
            print("  💡 本頁為唯讀。要變更設備 IP 請用 `setting` → [4] 硬體 IP 修改")

# ========== 主程式入口 ==========
    def run(self):
        self.logger.info("CAPAROC PM EIP Controller v3.8 啟動", extra={'log_module': 'CLI'})
        print("🚀 CAPAROC PM EIP Controller v3.8")
        print(f"   預設連線 IP: {self.device_ip}")
        
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
                            # （存檔詢問已在 _configure_device_ip 內完成）
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

                        elif cmd.startswith('s ') or cmd.startswith('status '):
                            # `s <ch>` 單一通道詳細狀態。範圍檢查交給
                            # show_channel_detail()——它讀到的 channels 才是
                            # 實際存在的通道（已濾掉空槽），比 get_total_channels()
                            # 的等差上限準確。
                            self._update_activity()
                            try:
                                target_ch = int(cmd.split()[1])
                            except (ValueError, IndexError):
                                print("⚠️  用法: s <通道編號>   範例: s 1")
                            else:
                                self.show_channel_detail(target_ch)
                        
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
                                    actual = self._read_nominal_current(module, channel, verbose=True)
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
                            global_ch = int(cmd.split()[1])
                            _mod, _ch = self.get_module_and_channel(global_ch)
                            self.set_channel(_mod, _ch, True)
                        elif cmd.startswith('off '):
                            self._update_activity()
                            global_ch = int(cmd.split()[1])
                            _mod, _ch = self.get_module_and_channel(global_ch)
                            self.set_channel(_mod, _ch, False)
                        elif cmd in ('device info', 'device', 'devinfo'):
                            self._update_activity()
                            self.show_device_info()

                        elif cmd in ('network info', 'network', 'netinfo'):
                            self._update_activity()
                            self.show_network_info()

                        elif cmd == 'setting':
                            result = self._handle_setting_connip(driver)
                            if result == 'reconnect':
                                if self.monitor_running:
                                    self.stop_monitor()
                                self._stop_heartbeat()
                                return 'reconnect'
                            print("  💡 輸入 'h' 可查看所有指令")

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
                    # （存檔詢問已在 _configure_device_ip 內完成）
                elif user_choice == 'Q':
                    print("✅ 退出程式")
                    return
                else:
                    print("   ⚠️  請輸入 R (重新連線)、C (變更 IP) 或 Q (退出)")

def main():
    controller = CaparocController()  # 自動從 config/config.json 讀取預設 IP
    while True:
        result = controller.run()
        if result == 'reconnect':
            print("\n[系統] 重新啟動連線與初始化流程...\n")
            continue
        break

if __name__ == "__main__":
    main()
