"""
Caparoc Breaker Control - Unit Tests
單元測試
"""

import sys
sys.path.insert(0, '../src')

from utils import BreakerController


def test_breaker_controller_init():
    """測試控制器初始化"""
    controller = BreakerController()
    assert controller is not None
    assert controller.connected == False
    assert len(controller.channels) == 0


def test_connect():
    """測試連接功能"""
    controller = BreakerController()
    result = controller.connect("localhost", 8080)
    assert result == True
    assert controller.connected == True


def test_disconnect():
    """測試斷開連接功能"""
    controller = BreakerController()
    controller.connect("localhost", 8080)
    controller.disconnect()
    assert controller.connected == False


def test_turn_on():
    """測試啟動 channel"""
    controller = BreakerController()
    result = controller.turn_on(1)
    assert result == True


def test_turn_off():
    """測試關閉 channel"""
    controller = BreakerController()
    result = controller.turn_off(1)
    assert result == True


def test_get_channel_status():
    """測試取得 channel 狀態"""
    controller = BreakerController()
    status = controller.get_channel_status(1)
    assert 'voltage' in status
    assert 'current' in status
    assert 'is_on' in status
