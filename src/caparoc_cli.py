#!/usr/bin/env python3
"""
CAPAROC Breaker CLI - 命令列遠端控制工具

用法範例:
    # 監控所有通道狀態
    python caparoc_cli.py --ip 192.168.2.111 status
    
    # 開啟通道 1
    python caparoc_cli.py --ip 192.168.2.111 on 1
    
    # 關閉通道 2
    python caparoc_cli.py --ip 192.168.2.111 off 2
    
    # 即時監控（每秒更新）
    python caparoc_cli.py --ip 192.168.2.111 monitor
    
    # 監控特定通道
    python caparoc_cli.py --ip 192.168.2.111 monitor --channel 1
"""

import sys
import os
import argparse
import time
from pathlib import Path

# 添加 src 目錄到路徑
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from breaker_controller import BreakerController
import logging


def setup_logging(verbose: bool = False):
    """設定日誌級別"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )


def print_status(status: dict, title: str = "系統狀態"):
    """格式化顯示狀態"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)
    print(f"  系統電壓: {status['voltage']:.2f} V")
    print(f"  總電流:   {status['total_current']:.2f} A")
    print("-" * 60)
    print("  通道狀態:")
    for ch, data in status['channels'].items():
        state_icon = "🟢" if data['state'] == 'ON' else "⚫"
        print(f"    通道 {ch}: {state_icon} {data['state']:3s} | 電流: {data['current']:6.2f} A")
    print("=" * 60)


def cmd_status(args):
    """顯示系統狀態"""
    with BreakerController(args.ip) as controller:
        if not controller.connected:
            print("❌ 連接失敗")
            return 1
        
        status = controller.get_all_status()
        print_status(status)
        return 0


def cmd_on(args):
    """開啟通道"""
    with BreakerController(args.ip) as controller:
        if not controller.connected:
            print("❌ 連接失敗")
            return 1
        
        print(f"\n🔓 正在開啟通道 {args.channel}...")
        success = controller.turn_on_channel(args.channel, args.current)
        
        if success:
            time.sleep(0.5)
            status = controller.get_all_status()
            print_status(status, f"通道 {args.channel} 開啟後狀態")
            return 0
        else:
            print(f"❌ 開啟通道 {args.channel} 失敗")
            return 1


def cmd_off(args):
    """關閉通道"""
    with BreakerController(args.ip) as controller:
        if not controller.connected:
            print("❌ 連接失敗")
            return 1
        
        print(f"\n🔒 正在關閉通道 {args.channel}...")
        success = controller.turn_off_channel(args.channel)
        
        if success:
            time.sleep(0.5)
            status = controller.get_all_status()
            print_status(status, f"通道 {args.channel} 關閉後狀態")
            return 0
        else:
            print(f"❌ 關閉通道 {args.channel} 失敗")
            return 1


def cmd_monitor(args):
    """即時監控模式"""
    print("\n📊 即時監控模式 (按 Ctrl+C 停止)")
    print("=" * 60)
    
    with BreakerController(args.ip) as controller:
        if not controller.connected:
            print("❌ 連接失敗")
            return 1
        
        try:
            cycle = 0
            while True:
                cycle += 1
                
                # 清除畫面（可選）
                if args.clear:
                    os.system('cls' if os.name == 'nt' else 'clear')
                
                # 讀取狀態
                if args.channel:
                    # 監控單一通道
                    voltage = controller.get_voltage()
                    current = controller.get_channel_current(args.channel)
                    state = "ON" if current > 0.05 else "OFF"
                    state_icon = "🟢" if state == "ON" else "⚫"
                    
                    print(f"\r[{cycle:04d}] 通道 {args.channel}: {state_icon} {state} | "
                          f"電流: {current:6.2f} A | 電壓: {voltage:6.2f} V", end='', flush=True)
                else:
                    # 監控所有通道
                    status = controller.get_all_status()
                    
                    if not args.clear:
                        print(f"\n--- 更新 #{cycle} ({time.strftime('%H:%M:%S')}) ---")
                    
                    print(f"系統電壓: {status['voltage']:.2f} V | 總電流: {status['total_current']:.2f} A")
                    
                    for ch, data in status['channels'].items():
                        state_icon = "🟢" if data['state'] == 'ON' else "⚫"
                        print(f"  CH{ch}: {state_icon} {data['state']:3s} {data['current']:6.2f}A", end='  ')
                    
                    if not args.clear:
                        print()  # 換行
                
                # 更新間隔
                time.sleep(args.interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 監控已停止")
            return 0


def cmd_all_on(args):
    """開啟所有通道"""
    with BreakerController(args.ip) as controller:
        if not controller.connected:
            print("❌ 連接失敗")
            return 1
        
        print("\n🔓 正在開啟所有通道...")
        
        for ch in range(1, 5):
            print(f"  開啟通道 {ch}...", end=' ', flush=True)
            success = controller.turn_on_channel(ch, args.current)
            print("✅" if success else "❌")
            time.sleep(0.5)
        
        time.sleep(1)
        status = controller.get_all_status()
        print_status(status, "所有通道開啟後狀態")
        return 0


def cmd_all_off(args):
    """關閉所有通道"""
    with BreakerController(args.ip) as controller:
        if not controller.connected:
            print("❌ 連接失敗")
            return 1
        
        print("\n🔒 正在關閉所有通道...")
        
        for ch in range(1, 5):
            print(f"  關閉通道 {ch}...", end=' ', flush=True)
            success = controller.turn_off_channel(ch)
            print("✅" if success else "❌")
            time.sleep(0.3)
        
        time.sleep(1)
        status = controller.get_all_status()
        print_status(status, "所有通道關閉後狀態")
        return 0


def main():
    """主程式"""
    parser = argparse.ArgumentParser(
        description='CAPAROC Breaker CLI - 遠端控制工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  %(prog)s --ip 192.168.2.111 status          # 顯示系統狀態
  %(prog)s --ip 192.168.2.111 on 1            # 開啟通道 1
  %(prog)s --ip 192.168.2.111 off 2           # 關閉通道 2
  %(prog)s --ip 192.168.2.111 monitor         # 即時監控所有通道
  %(prog)s --ip 192.168.2.111 monitor -c 1    # 監控通道 1
  %(prog)s --ip 192.168.2.111 all-on          # 開啟所有通道
  %(prog)s --ip 192.168.2.111 all-off         # 關閉所有通道
        """
    )
    
    # 全域選項
    parser.add_argument('--ip', type=str, default='192.168.2.111',
                        help='CAPAROC 設備 IP 位址 (預設: 192.168.2.111)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='顯示詳細日誌')
    
    # 子命令
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # status 命令
    parser_status = subparsers.add_parser('status', help='顯示系統狀態')
    parser_status.set_defaults(func=cmd_status)
    
    # on 命令
    parser_on = subparsers.add_parser('on', help='開啟通道')
    parser_on.add_argument('channel', type=int, choices=range(1, 5),
                           help='通道編號 (1-4)')
    parser_on.add_argument('--current', type=int, default=4,
                           help='額定電流 (A, 預設: 4)')
    parser_on.set_defaults(func=cmd_on)
    
    # off 命令
    parser_off = subparsers.add_parser('off', help='關閉通道')
    parser_off.add_argument('channel', type=int, choices=range(1, 5),
                            help='通道編號 (1-4)')
    parser_off.set_defaults(func=cmd_off)
    
    # monitor 命令
    parser_monitor = subparsers.add_parser('monitor', help='即時監控模式')
    parser_monitor.add_argument('-c', '--channel', type=int, choices=range(1, 5),
                                help='監控特定通道 (不指定則監控所有)')
    parser_monitor.add_argument('-i', '--interval', type=float, default=1.0,
                                help='更新間隔 (秒, 預設: 1.0)')
    parser_monitor.add_argument('--clear', action='store_true',
                                help='每次更新清除畫面')
    parser_monitor.set_defaults(func=cmd_monitor)
    
    # all-on 命令
    parser_all_on = subparsers.add_parser('all-on', help='開啟所有通道')
    parser_all_on.add_argument('--current', type=int, default=4,
                               help='額定電流 (A, 預設: 4)')
    parser_all_on.set_defaults(func=cmd_all_on)
    
    # all-off 命令
    parser_all_off = subparsers.add_parser('all-off', help='關閉所有通道')
    parser_all_off.set_defaults(func=cmd_all_off)
    
    # 解析參數
    args = parser.parse_args()
    
    # 設定日誌
    setup_logging(args.verbose)
    
    # 檢查是否有子命令
    if not hasattr(args, 'func'):
        parser.print_help()
        return 1
    
    # 執行命令
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n\n👋 程式已中止")
        return 0
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
