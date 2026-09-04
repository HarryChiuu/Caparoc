#!/usr/bin/env python3
"""
通道自訂標籤（4.3.6）測試 — app_config 儲存層 + web 端點。

不需實機、不需網路。所有寫入都導向暫存的 config.json（見 _isolated_config），
**不會動到使用者真正的設定檔**。

── 重點測項 ──────────────────────────────────────────────────────
1. 儲存往返、長度上限、空字串＝刪除
2. 不同設備的標籤互不污染（key 隔離）——這是「綁定物理設備」的核心保證
3. S/N 讀不到時退回 `ip:`（沿用 _probe_cache_key() 的既有慣例）
4. **payload 不得混入 label 欄位**——`_format_status()` 在 WebSocket 迴圈中
   每秒執行，塞入靜態文字等於每天推 8.6 萬次，且為了填 label 得每秒多讀一次
   CIP 取序號去搶 _cip_lock。這項守的是一個刻意的架構決策，不是實作細節。
"""
import sys
import json
import importlib
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import app_config  # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """把 app_config 的讀寫導到 tmp_path，並清掉快取。"""
    path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(app_config, "CONFIG_PATH", path)
    monkeypatch.setattr(app_config, "_cache", None)
    yield path
    monkeypatch.setattr(app_config, "_cache", None)


K1 = "sn:1378815610"
K2 = "sn:999999999"


# ── 儲存層 ──────────────────────────────────────────────────────────────────
def test_unknown_device_returns_empty_shape(cfg):
    """查無資料時回同樣結構的空值，呼叫端不必判 None。"""
    assert app_config.device_labels(K1) == {"device_label": "", "channels": {}}


def test_round_trip(cfg):
    app_config.save_channel_label(K1, 1, "主機電源")
    app_config.save_device_label(K1, "一號配電箱")
    got = app_config.device_labels(K1)
    assert got["channels"]["1"] == "主機電源"
    assert got["device_label"] == "一號配電箱"


def test_whitespace_is_trimmed(cfg):
    app_config.save_channel_label(K1, 1, "  主機電源  ")
    assert app_config.device_labels(K1)["channels"]["1"] == "主機電源"


def test_length_is_capped(cfg):
    app_config.save_channel_label(K1, 1, "X" * 100)
    assert len(app_config.device_labels(K1)["channels"]["1"]) == app_config.LABEL_MAX_LEN


def test_empty_string_deletes_the_key(cfg):
    """空字串＝刪除。標籤是稀疏資料，留空鍵會讓設定檔充滿雜訊。"""
    app_config.save_channel_label(K1, 1, "主機電源")
    app_config.save_channel_label(K1, 1, "")
    assert app_config.device_labels(K1)["channels"] == {}


def test_labels_block_removed_when_fully_cleared(cfg):
    app_config.save_channel_label(K1, 1, "主機電源")
    app_config.save_channel_label(K1, 1, "")
    assert "labels" not in json.loads(cfg.read_text(encoding="utf-8"))


def test_devices_do_not_contaminate_each_other(cfg):
    """兩台設備的標籤必須完全隔離——這是「以序號綁定」的核心保證。"""
    app_config.save_channel_label(K1, 1, "甲廠通道一")
    app_config.save_channel_label(K2, 1, "乙廠通道一")
    assert app_config.device_labels(K1)["channels"]["1"] == "甲廠通道一"
    assert app_config.device_labels(K2)["channels"]["1"] == "乙廠通道一"


def test_other_config_sections_survive_label_writes(cfg):
    """寫標籤不得動到 device / logging 等既有區塊。"""
    app_config.save_device_ip("192.168.50.111")
    app_config.save_channel_label(K1, 1, "主機電源")
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["device"]["default_ip"] == "192.168.50.111"


def test_empty_key_is_rejected(cfg):
    assert app_config.save_channel_label("", 1, "x") is False


# ── web 端點 ────────────────────────────────────────────────────────────────
def _load_web_app():
    """web/ 不是 package，用 importlib 直接載入（與 test_demo_payload.py 同法）。"""
    sys.argv = ["app.py", "--demo"]
    spec = importlib.util.spec_from_file_location("caparoc_web_labels", _ROOT / "web" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_mode_uses_a_stable_key():
    """--demo 下三個端點都要能運作，否則沒有實機就無法檢視這個 UI（債 #10）。"""
    m = _load_web_app()
    assert m._device_label_key() == "ip:demo"


def test_key_falls_back_to_ip_without_serial():
    """S/N 讀不到時退回 ip:——沿用 _probe_cache_key() 的既有慣例。"""
    m = _load_web_app()
    m._DEMO_MODE = False
    m._label_key_cache.clear()
    m.backend.device_ip = "192.168.50.111"
    assert m._device_label_key() == "ip:192.168.50.111"


def test_key_prefers_serial_when_known():
    m = _load_web_app()
    m._DEMO_MODE = False
    m._label_key_cache.clear()
    m.backend.device_ip = "192.168.50.111"
    m._remember_label_key("192.168.50.111", "1378815610")
    assert m._device_label_key() == "sn:1378815610"


def test_key_is_per_ip_not_a_single_current_value():
    """
    快取以 IP 為索引，換 IP 自然換 key。

    刻意不用單一「當前 key」變數：斷線點散在七處（手動斷線、IP 變更、
    WebSocket 失聯、關機…），漏掛任何一處都會讓標籤張冠李戴。
    """
    m = _load_web_app()
    m._DEMO_MODE = False
    m._label_key_cache.clear()
    m._remember_label_key("192.168.50.111", "111")
    m.backend.device_ip = "192.168.50.222"          # 換一台，沒記過序號
    assert m._device_label_key() == "ip:192.168.50.222"


# ── 架構防護 ────────────────────────────────────────────────────────────────
def test_status_payload_must_not_carry_labels():
    """
    每秒推送的 payload 不得混入 label。

    TODO 原規劃要在 _format_status() 每個 channel 加 label 欄位，本實作**刻意不採用**
    （見 docs/CHANNEL_LABELS_PLAN.md 決策 2）。這支測試守的是那個決策：
    日後若有人「順手」加回去，每秒推送會被撐大，且後端得每秒多讀一次 CIP 取序號。
    """
    m = _load_web_app()
    payload = m._generate_demo_payload()
    for ch in payload["channels"]:
        assert "label" not in ch, "label 不該進入每秒推送的 payload"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
