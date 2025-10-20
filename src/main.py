"""
Caparoc Breaker Control - Main Application
進行遠端控制Caparoc_breaker，可檢測每一channel的電壓電流值以及啟閉動作
"""

from utils import BreakerController


def main():
    """主程式進入點"""
    print("=" * 50)
    print("Caparoc Breaker Control System")
    print("=" * 50)
    
    # 初始化控制器
    controller = BreakerController()
    
    # 顯示系統狀態
    print("\n系統已初始化")
    print("準備進行遠端控制...")
    
    # TODO: 實作主要控制邏輯
    # - 連接到 Caparoc breaker
    # - 讀取 channel 狀態
    # - 控制 channel 啟閉
    
    print("\n程式執行完成")


if __name__ == "__main__":
    main()
