#!/usr/bin/env python3
"""
4.4.1 CLI 通道詳細狀態顯示 — 測試。

不需實機、不需網路：`show_channel_detail()` 唯一的外部依賴是
`_read_current_status()`，測試直接把它換成回傳固定 dict 的 stub。
這也順帶釘住一件事——該方法**不可以**繞過 `_read_current_status()`
自己去讀 Input Assembly（否則本檔的 stub 會失效而測試變綠燈但實際重複解析）。

── 重點測項 ──────────────────────────────────────────────────────
1. calc_utilization 的邊界：額定 0 → None（不是 0%），見該函式 docstring
2. 空槽／不存在通道要走「可用通道」提示，不可拋例外
3. bit 0-5 六個旗標都要出現在輸出，且狀態位元字串的位序是 bit5..bit0
4. 使用率門檻圖示與設備自身的 80% 警告位元對齊
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from caparoc_backend import CaparocBackend  # noqa: E402


def _channel(**over):
    """一個「正常開啟、2.5A / 4A」的通道，測項只覆寫關心的欄位。"""
    base = {
        'module': 1, 'channel': 1,
        'is_on': True,
        'flowing_current': 2.5,
        'nominal_current': 4.0,
        'warning_80': False, 'overload': False, 'short_circuit': False,
        'hardware_fault': False, 'total_shutdown': False,
    }
    base.update(over)
    return base


@pytest.fixture
def backend(monkeypatch):
    """未連線的 backend；driver 給個哨兵值讓前置檢查通過。"""
    b = CaparocBackend.__new__(CaparocBackend)
    b.driver = object()
    return b


def _run(backend, monkeypatch, capsys, channels, module_count=1, ch=1):
    monkeypatch.setattr(
        backend, '_read_current_status',
        lambda: {'module_count': module_count, 'channels': channels},
        raising=False,
    )
    backend.show_channel_detail(ch)
    return capsys.readouterr().out


# ── calc_utilization：純函式邊界 ──────────────────────────────────

@pytest.mark.parametrize("flowing,nominal,expected", [
    (2.5, 4.0, 62.5),
    (0.0, 4.0, 0.0),
    (4.0, 4.0, 100.0),
    (5.0, 4.0, 125.0),      # 過載可以 >100%，不夾在 100
])
def test_calc_utilization_values(flowing, nominal, expected):
    assert CaparocBackend.calc_utilization(flowing, nominal) == pytest.approx(expected)


@pytest.mark.parametrize("nominal", [0, 0.0, -1, None, "abc"])
def test_calc_utilization_returns_none_not_zero(nominal):
    """額定不明時必須是 None——回 0 會讓空槽看起來像健康的閒置通道。"""
    assert CaparocBackend.calc_utilization(2.5, nominal) is None


# ── show_channel_detail ─────────────────────────────────────────

def test_shows_utilization(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys, {1: _channel()})
    assert "62.5%" in out
    assert "2.50 A" in out and "4.00 A" in out


def test_missing_channel_lists_available(backend, monkeypatch, capsys):
    """空槽/不存在的通道要提示實際可用通道，而不是拋例外或印 0A。"""
    out = _run(backend, monkeypatch, capsys, {1: _channel(), 3: _channel()}, ch=2)
    assert "不存在或為空槽" in out
    assert "CH1" in out and "CH3" in out


def test_no_channels_at_all_does_not_crash(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys, {}, ch=1)
    assert "不存在或為空槽" in out


def test_all_six_bits_are_rendered(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys, {1: _channel()})
    for bit, _flag, text in CaparocBackend.CHANNEL_STATUS_BITS:
        assert f"bit {bit}" in out
        assert text in out


def test_status_bit_string_is_bit5_to_bit0(backend, monkeypatch, capsys):
    """只有 bit0(is_on) 與 bit3(short_circuit) 為真 → 0b001001。"""
    out = _run(backend, monkeypatch, capsys,
               {1: _channel(is_on=True, short_circuit=True)})
    assert "0b001001" in out


def test_faults_listed_in_warning_section(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys,
               {1: _channel(overload=True, hardware_fault=True)})
    assert "過載" in out and "硬體故障" in out
    assert "✅ 無" not in out


def test_clean_channel_reports_no_warning(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys, {1: _channel()})
    assert "✅ 無" in out


def test_on_but_no_current_flags_no_load(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys,
               {1: _channel(is_on=True, flowing_current=0.0)})
    assert "無負載" in out


def test_off_channel_without_current_is_not_no_load(backend, monkeypatch, capsys):
    """關閉的通道沒電流是正常的，不該報無負載。"""
    out = _run(backend, monkeypatch, capsys,
               {1: _channel(is_on=False, flowing_current=0.0)})
    assert "無負載" not in out


def test_multi_module_title_uses_module_prefix(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys,
               {5: _channel(module=2, channel=1)}, module_count=2, ch=5)
    assert "M2.CH1 (#5)" in out


def test_single_module_title_is_plain(backend, monkeypatch, capsys):
    out = _run(backend, monkeypatch, capsys, {1: _channel()}, module_count=1)
    assert "CH1 詳細狀態" in out


def test_read_failure_is_reported(backend, monkeypatch, capsys):
    monkeypatch.setattr(backend, '_read_current_status', lambda: None, raising=False)
    backend.show_channel_detail(1)
    assert "無法讀取狀態資料" in capsys.readouterr().out


def test_no_driver_is_reported(backend, capsys):
    backend.driver = None
    backend.show_channel_detail(1)
    assert "Driver 未初始化" in capsys.readouterr().out
