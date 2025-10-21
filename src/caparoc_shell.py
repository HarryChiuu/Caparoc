#!/usr/bin/env python3
"""
CAPAROC Breaker 互動式控制 Shell

啟動後可持續運行，支援即時命令輸入和控制。

使用方法：
    python caparoc_shell.py --ip 192.168.2.111
    
互動命令：
    status / st          - 顯示當前狀態
    on <channel>         - 開啟通道 (1-4)
    off <channel>        - 關閉通道 (1-4)
    all-on               - 開啟所有通道
    all-off              - 關閉所有通道
    monitor [channel]    - 啟動監控模式
    stop                 - 停止監控
    voltage / v          - 顯示電壓
    current <ch>         - 顯示通道電流
    help / ?             - 顯示幫助
    quit / exit          - 退出程式
"""

import sys
import os
import argparse
import time
import threading
from pathlib import Path

# 添加 src 目錄到路徑
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from breaker_controller import BreakerController
import logging


class BreakerShell:
    """CAPAROC 斷路器互動式 Shell"""
    
    def __init__(self, device_ip: str, verbose: bool = False):
        self.device_ip = device_ip
        self.verbose = verbose
        self.controller = None
        self.running = False
        self.monitoring = False
        self.monitor_thread = None
        self.monitor_channel = None
        
        # 設定日誌
        level = logging.DEBUG if verbose else logging.WARNING
        logging.basicConfig(level=level, format='%(message)s')
    
    def connect(self) -> bool:
        """連接到設備"""
        print(f"\n🔌 正在連接到 {self.device_ip}...")
        self.controller = BreakerController(self.device_ip)
        
        if self.controller.connect():
            print("✅ 連接成功！")
            print("📡 Implicit Messaging 已啟動 (20Hz)")
            return True
        else:
            print("❌ 連接失敗")
            return False
    
    def disconnect(self):
        """斷開連接"""
        if self.monitoring:
            self.stop_monitor()
        
        if self.controller:
            self.controller.disconnect()
            print("\n👋 已斷開連接")
    
    def show_status(self):
        """顯示當前狀態"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        status = self.controller.get_all_status()
        
        print("\n" + "=" * 60)
        print("  📊 系統狀態")
        print("=" * 60)
        print(f"  電壓: {status['voltage']:.2f} V  |  總電流: {status['total_current']:.2f} A")
        print("-" * 60)
        
        for ch, data in status['channels'].items():
            icon = "🟢" if data['state'] == 'ON' else "⚫"
            print(f"  CH{ch}: {icon} {data['state']:3s}  |  {data['current']:6.2f} A")
        
        print("=" * 60)
    
    def turn_on(self, channel: int):
        """開啟通道"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        print(f"\n🔓 開啟通道 {channel}...", end=' ', flush=True)
        success = self.controller.turn_on_channel(channel)
        
        if success:
            time.sleep(0.3)
            current = self.controller.get_channel_current(channel)
            print(f"✅ 成功 (電流: {current:.2f}A)")
        else:
            print("❌ 失敗")
    
    def turn_off(self, channel: int):
        """關閉通道"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        print(f"\n🔒 關閉通道 {channel}...", end=' ', flush=True)
        success = self.controller.turn_off_channel(channel)
        
        if success:
            time.sleep(0.3)
            current = self.controller.get_channel_current(channel)
            print(f"✅ 成功 (電流: {current:.2f}A)")
        else:
            print("❌ 失敗")
    
    def all_on(self):
        """開啟所有通道"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        print("\n🔓 開啟所有通道...")
        for ch in range(1, 5):
            print(f"  CH{ch}...", end=' ', flush=True)
            self.controller.turn_on_channel(ch)
            print("✅")
            time.sleep(0.3)
        
        print("✅ 所有通道已開啟")
    
    def all_off(self):
        """關閉所有通道"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        print("\n🔒 關閉所有通道...")
        for ch in range(1, 5):
            print(f"  CH{ch}...", end=' ', flush=True)
            self.controller.turn_off_channel(ch)
            print("✅")
            time.sleep(0.2)
        
        print("✅ 所有通道已關閉")
    
    def start_monitor(self, channel=None):
        """啟動監控模式"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        if self.monitoring:
            print("⚠️  監控已在運行，請先停止 (輸入 'stop')")
            return
        
        self.monitoring = True
        self.monitor_channel = channel
        self.monitor_thread = threading.Thread(target=self._monitor_worker, daemon=True)
        self.monitor_thread.start()
        
        if channel:
            print(f"\n📊 開始監控通道 {channel} (輸入 'stop' 停止)")
        else:
            print("\n📊 開始監控所有通道 (輸入 'stop' 停止)")
    
    def stop_monitor(self):
        """停止監控"""
        if not self.monitoring:
            print("⚠️  監控未運行")
            return
        
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        
        print("\n⏹️  監控已停止")
    
    def _monitor_worker(self):
        """監控工作執行緒"""
        print("=" * 60)
        
        try:
            while self.monitoring:
                if self.monitor_channel:
                    # 監控單一通道
                    voltage = self.controller.get_voltage()
                    current = self.controller.get_channel_current(self.monitor_channel)
                    state = "ON " if current > 0.05 else "OFF"
                    icon = "🟢" if current > 0.05 else "⚫"
                    
                    timestamp = time.strftime('%H:%M:%S')
                    print(f"\r[{timestamp}] CH{self.monitor_channel}: {icon} {state} | "
                          f"{current:6.2f}A | {voltage:6.2f}V", end='', flush=True)
                else:
                    # 監控所有通道
                    status = self.controller.get_all_status()
                    timestamp = time.strftime('%H:%M:%S')
                    
                    output = f"\r[{timestamp}] V:{status['voltage']:6.2f}V I:{status['total_current']:5.2f}A | "
                    
                    for ch, data in status['channels'].items():
                        icon = "🟢" if data['state'] == 'ON' else "⚫"
                        output += f"CH{ch}:{icon}{data['current']:5.2f}A "
                    
                    print(output, end='', flush=True)
                
                time.sleep(1.0)
                
        except Exception as e:
            print(f"\n❌ 監控錯誤: {e}")
    
    def show_voltage(self):
        """顯示電壓"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        voltage = self.controller.get_voltage()
        total_current = self.controller.get_total_current()
        print(f"\n⚡ 電壓: {voltage:.2f} V  |  總電流: {total_current:.2f} A")
    
    def show_current(self, channel: int):
        """顯示通道電流"""
        if not self.controller or not self.controller.connected:
            print("❌ 設備未連接")
            return
        
        current = self.controller.get_channel_current(channel)
        state = "ON" if current > 0.05 else "OFF"
        icon = "🟢" if current > 0.05 else "⚫"
        print(f"\n📊 通道 {channel}: {icon} {state}  |  電流: {current:.2f} A")
    
    def show_help(self):
        """顯示幫助訊息"""
        print("\n" + "=" * 60)
        print("  📖 可用命令")
        print("=" * 60)
        print("  status, st               - 顯示系統狀態")
        print("  on <channel>             - 開啟通道 (1-4)")
        print("  off <channel>            - 關閉通道 (1-4)")
        print("  all-on                   - 開啟所有通道")
        print("  all-off                  - 關閉所有通道")
        print("  monitor [channel]        - 啟動監控 (不指定channel則監控全部)")
        print("  stop                     - 停止監控")
        print("  voltage, v               - 顯示電壓")
        print("  current <channel>, i <ch>- 顯示通道電流")
        print("  help, ?                  - 顯示此幫助")
        print("  clear, cls               - 清除畫面")
        print("  quit, exit, q            - 退出程式")
        print("=" * 60)
        print("\n範例:")
        print("  > on 1          # 開啟通道 1")
        print("  > monitor 2     # 監控通道 2")
        print("  > all-off       # 關閉所有通道")
    
    def clear_screen(self):
        """清除畫面"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def process_command(self, cmd_line: str) -> bool:
        """
        處理命令
        
        Returns:
            bool: True 繼續運行, False 退出
        """
        cmd_line = cmd_line.strip()
        
        if not cmd_line:
            return True
        
        parts = cmd_line.split()
        cmd = parts[0].lower()
        args = parts[1:]
        
        try:
            # 退出命令
            if cmd in ['quit', 'exit', 'q']:
                return False
            
            # 幫助
            elif cmd in ['help', '?']:
                self.show_help()
            
            # 清除畫面
            elif cmd in ['clear', 'cls']:
                self.clear_screen()
            
            # 狀態
            elif cmd in ['status', 'st']:
                self.show_status()
            
            # 開啟通道
            elif cmd == 'on':
                if not args:
                    print("❌ 請指定通道編號 (1-4)")
                else:
                    try:
                        channel = int(args[0])
                        if 1 <= channel <= 4:
                            self.turn_on(channel)
                        else:
                            print("❌ 通道編號必須在 1-4 之間")
                    except ValueError:
                        print("❌ 無效的通道編號")
            
            # 關閉通道
            elif cmd == 'off':
                if not args:
                    print("❌ 請指定通道編號 (1-4)")
                else:
                    try:
                        channel = int(args[0])
                        if 1 <= channel <= 4:
                            self.turn_off(channel)
                        else:
                            print("❌ 通道編號必須在 1-4 之間")
                    except ValueError:
                        print("❌ 無效的通道編號")
            
            # 開啟所有
            elif cmd == 'all-on':
                self.all_on()
            
            # 關閉所有
            elif cmd == 'all-off':
                self.all_off()
            
            # 監控
            elif cmd == 'monitor':
                if args:
                    try:
                        channel = int(args[0])
                        if 1 <= channel <= 4:
                            self.start_monitor(channel)
                        else:
                            print("❌ 通道編號必須在 1-4 之間")
                    except ValueError:
                        print("❌ 無效的通道編號")
                else:
                    self.start_monitor()
            
            # 停止監控
            elif cmd == 'stop':
                self.stop_monitor()
            
            # 電壓
            elif cmd in ['voltage', 'v']:
                self.show_voltage()
            
            # 電流
            elif cmd in ['current', 'i']:
                if not args:
                    print("❌ 請指定通道編號 (1-4)")
                else:
                    try:
                        channel = int(args[0])
                        if 1 <= channel <= 4:
                            self.show_current(channel)
                        else:
                            print("❌ 通道編號必須在 1-4 之間")
                    except ValueError:
                        print("❌ 無效的通道編號")
            
            else:
                print(f"❌ 未知命令: {cmd}  (輸入 'help' 查看可用命令)")
        
        except Exception as e:
            print(f"❌ 命令執行錯誤: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
        
        return True
    
    def run(self):
        """運行互動式 Shell"""
        print("=" * 60)
        print("  🚀 CAPAROC Breaker 互動式控制 Shell")
        print("=" * 60)
        
        # 連接設備
        if not self.connect():
            return 1
        
        # 顯示初始狀態
        self.show_status()
        
        # 顯示提示
        print("\n💡 輸入 'help' 查看可用命令, 'quit' 退出")
        
        self.running = True
        
        try:
            while self.running:
                try:
                    # 如果正在監控，顯示簡化提示
                    if self.monitoring:
                        cmd_line = input("\n> ")
                    else:
                        cmd_line = input("\n🎮 > ")
                    
                    if not self.process_command(cmd_line):
                        break
                
                except EOFError:
                    # Ctrl+D / Ctrl+Z
                    break
                
                except KeyboardInterrupt:
                    # Ctrl+C
                    if self.monitoring:
                        print("\n\n⚠️  使用 'stop' 命令停止監控")
                    else:
                        print("\n\n⚠️  使用 'quit' 命令退出程式")
        
        finally:
            self.disconnect()
        
        return 0


def main():
    """主程式"""
    parser = argparse.ArgumentParser(
        description='CAPAROC Breaker 互動式控制 Shell',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
啟動後可持續運行，支援以下命令：
  status          - 顯示狀態
  on <ch>         - 開啟通道
  off <ch>        - 關閉通道
  all-on/all-off  - 批次控制
  monitor [ch]    - 啟動監控
  stop            - 停止監控
  help            - 顯示幫助
  quit            - 退出
        """
    )
    
    parser.add_argument('--ip', type=str, default='192.168.2.111',
                        help='設備 IP 位址 (預設: 192.168.2.111)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='詳細輸出模式')
    
    args = parser.parse_args()
    
    # 創建並運行 Shell
    shell = BreakerShell(args.ip, args.verbose)
    
    try:
        return shell.run()
    except Exception as e:
        print(f"\n❌ 程式錯誤: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
