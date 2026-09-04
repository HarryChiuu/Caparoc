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


# ── 前端綁定回歸防護 ────────────────────────────────────────────────────────
# 2026-09-04 回報：標籤輸入框「一 key 進去就自己刪掉」。
# 根因是輸入框直接綁 `:value="channelLabels[id]"`——那是**單向綁定**，而
# WebSocket 每秒推一次狀態會讓 state.channels 重新賦值、v-for 重算，
# :value 隨即把使用者打到一半的字覆寫回尚未存檔的舊值。
# 修法是加一層 labelDrafts 草稿，編輯期間由前端自己作主。
# 以下兩支是靜態檢查，確保不會有人把單向綁定改回去。
_INDEX = _ROOT / "web" / "templates" / "index.html"
_APPJS = _ROOT / "web" / "static" / "js" / "app.js"
_CSS = _ROOT / "web" / "static" / "css" / "style.css"


def _fn_body(js: str, signature: str) -> str:
    """
    粗略取出一個 JS 函式的內容：從簽名之後到第一個「縮排 8 空白的收尾大括號」為止。

    這些函式都在 setup() 內（縮排 8 格），所以 `\\n        }` 就是它的結束。
    只用於靜態檢查，不需要真正的 parser。
    """
    assert signature in js, f"找不到 {signature}"
    return js.split(signature, 1)[1].split("\n        }", 1)[0]


def test_label_inputs_must_not_bind_stored_value_directly():
    """
    輸入框不得直接綁 channelLabels / deviceLabel。

    每秒重繪會把使用者輸入清掉——這正是 2026-09-04 回報的症狀。
    """
    html = _INDEX.read_text(encoding="utf-8")
    for bad in (':value="channelLabels[ch.id]', ':value="deviceLabel"'):
        assert bad not in html, (
            f"標籤輸入框綁了 {bad}（單向綁定）。WebSocket 每秒重繪會覆寫使用者輸入，"
            "請改綁 labelValue()/labelDrafts。"
        )


def test_label_inputs_use_draft_layer():
    """輸入框必須走草稿層：labelValue 顯示、@focus 載入、@input 寫草稿。"""
    html = _INDEX.read_text(encoding="utf-8")
    for needed in ('labelValue(ch.id)', 'onLabelFocus(ch.id)', 'labelDrafts[ch.id]',
                   "labelValue('_device')", "labelDrafts['_device']"):
        assert needed in html, f"index.html 缺少草稿層綁定：{needed}"


def test_save_functions_clear_the_draft():
    """
    存檔後必須清掉草稿（無論值有沒有變）。

    草稿留著的話，之後 fetchLabels() 從後端拿到的新值會被草稿擋住蓋不上去
    （labelValue 是草稿優先）。
    """
    js = _APPJS.read_text(encoding="utf-8")
    assert "delete labelDrafts[chId];" in js
    assert "delete labelDrafts['_device'];" in js


# ── 版面與回饋狀態回歸防護（2026-09-04 第二輪回報）────────────────────────
# 回報 1：存檔後「✓ 已儲存」蓋到隔壁「目前額定電流」的「10 A」上，且該列文字沒對齊。
#   成因：.label-input 是 width:100%，已吃滿 190px 的 col-label，回饋 span 當成
#   inline 兄弟節點就無處可去；.td-label 又有 white-space:nowrap，在
#   table-layout:fixed 底下直接溢出。且 .td-label 沒有 .td-action 的 min-height:30px。
# 回報 2：同一列有「名稱」（blur 自動存、無按鈕）與「額定電流」（要按「設定」）
#   兩種設定，使用者設定完名稱去按「設定」，收到紅字「請輸入 N–M A」。


def test_label_cell_uses_flex_wrapper():
    """名稱欄必須有 .td-label-wrap 容器，否則回饋會溢出到隔壁欄。"""
    html = _INDEX.read_text(encoding="utf-8")
    assert 'class="td-label-wrap"' in html, "名稱欄缺少 flex 容器，回饋訊息會溢出蓋到隔壁欄"


def test_label_wrap_css_contains_and_aligns():
    """容器要能關住內容（min-width:0 可縮、訊息截斷）並與操作欄對齊（min-height）。"""
    css = _CSS.read_text(encoding="utf-8")
    assert ".td-label-wrap {" in css
    block = css.split(".td-label-wrap {", 1)[1].split("}", 1)[0]
    assert "min-height" in block, ".td-label-wrap 缺 min-height，名稱欄會與操作欄文字不齊"
    assert ".td-label-wrap .label-input" in css, "缺少輸入框覆寫，flex 子項不會縮"
    assert "min-width: 0" in css.split(".td-label-wrap .label-input", 1)[1].split("}", 1)[0], (
        "缺 min-width:0，flex 子項不肯縮到內在寬度以下，溢出會回來"
    )


def test_label_input_base_class_keeps_device_max_width():
    """
    覆寫必須限定在 .td-label-wrap 之下。

    .label-input 與系統狀態頁的設備名稱欄共用，若直接把 max-width 改在基底類別，
    那裡會失去 .label-input-device 的 260px 意圖。
    """
    css = _CSS.read_text(encoding="utf-8")
    base = css.split(".label-input {", 1)[1].split("}", 1)[0]
    assert "max-width: 180px" in base, ".label-input 基底的 max-width 被改動，會影響設備名稱欄"
    assert ".label-input-device" in css


def test_validate_nominal_is_untouched():
    """
    validateNominal 有三個呼叫端，其契約不得改動。

    空白輸入改由各呼叫端的 isBlankNominal 前置檢查處理，正是為了讓這支
    保持原樣——動它就有三處迴歸風險。
    """
    js = _APPJS.read_text(encoding="utf-8")
    assert "function validateNominal(raw, mod)" in js
    body = _fn_body(js, "function validateNominal(raw, mod) {")
    assert "isBlank" not in body, "空白判斷不該混進 validateNominal，會影響三個呼叫端"
    assert "請輸入 ${min}–${max} A" in body, "超出範圍的錯誤訊息不應改動"


def test_all_three_callers_guard_blank_input():
    """單通道、全域批次、模組批次三處都要先擋空白，否則按鈕仍會跳紅字。"""
    js = _APPJS.read_text(encoding="utf-8")
    assert "function isBlankNominal(" in js
    for caller in ("async function setNominal(", "async function setAllNominal(",
                   "async function setModuleNominal("):
        assert caller in js, f"找不到 {caller}"
        body = js.split(caller, 1)[1][:900]
        assert "isBlankNominal" in body, f"{caller} 缺少空白前置檢查，空欄位仍會跳紅字"


def test_blank_hint_is_not_rendered_as_error():
    """空白提示必須走 hint（中性色），不得用 err 紅字。"""
    js = _APPJS.read_text(encoding="utf-8")
    assert "hint: true" in js or "hint = true" in js, "找不到 hint 狀態"
    css = _CSS.read_text(encoding="utf-8")
    assert ".feedback-msg.hint" in css, "缺少 .feedback-msg.hint 樣式"
    html = _INDEX.read_text(encoding="utf-8")
    assert html.count("? 'hint' :") >= 3, "三個回饋點都要能渲染 hint 狀態"


def test_batch_status_writes_go_through_setter():
    """
    batchStatus 是持續存在的 reactive 物件（不可整個取代，否則斷反應性）。

    正因為不取代，未指定的欄位會沿用上次的值——某個錯誤路徑忘了清 hint，
    紅字就會被染成灰色。統一走 setBatchStatus() 讓這件事不可能發生。
    """
    js = _APPJS.read_text(encoding="utf-8")
    assert "function setBatchStatus(" in js
    setter = _fn_body(js, "function setBatchStatus(")
    direct = [ln.strip() for ln in js.splitlines()
              if ("batchStatus.ok =" in ln or "batchStatus.msg =" in ln or "batchStatus.hint =" in ln)
              and ln.strip() not in setter]
    assert not direct, (
        "以下 batchStatus 欄位是直接指派而非走 setBatchStatus()，"
        "會有殘留 hint 把紅字染灰的風險： " + " / ".join(direct)
    )


# ── 卡在「儲存中…」與版面推擠（2026-09-04 第三輪回報）──────────────────────
def test_label_input_must_not_bind_disabled():
    """
    名稱輸入框不得綁 :disabled。

    Vue 一停用**聚焦中**的輸入框，瀏覽器會補發一次 blur → 再次呼叫 saveLabel →
    撞上 _postLabel 的 busy 早退 → feedback 永遠停在「儲存中…」，
    輸入框也一直是灰的。這正是回報的卡住現象。
    """
    html = _INDEX.read_text(encoding="utf-8")
    assert 'disabled="labelBusy' not in html, (
        "名稱輸入框綁了 :disabled；停用聚焦中的輸入框會讓瀏覽器補發 blur，"
        "造成重複送出並卡在「儲存中…」"
    )


def test_label_state_is_an_icon_not_a_text_message():
    """
    存檔狀態要用輸入框內的小圖示，不用文字訊息。

    col-label 只有 190px，放不下「輸入框 + 文字」並排，擠成兩行會把整張表推長。
    """
    html = _INDEX.read_text(encoding="utf-8")
    assert "labelStateIcon(" in html, "缺少狀態圖示"
    assert "labelFeedback[ch.id].msg }}" not in html, (
        "名稱欄仍在渲染文字訊息，190px 放不下、會把列高推高"
    )
    css = _CSS.read_text(encoding="utf-8")
    block = css.split(".label-state {", 1)[1].split("}", 1)[0]
    assert "position: absolute" in block, (
        ".label-state 必須絕對定位才不會參與版面計算，否則列高會跳動"
    )


def test_post_label_does_not_early_return_on_busy():
    """
    _postLabel 不得因 busy 早退。

    早退會讓重複觸發的那次直接返回，feedback 停在前一次設下的「儲存中…」。
    移除輸入框的 :disabled 後已無重入來源，重複送出改由 saveLabel 的
    「值沒變就不打 API」擋掉。
    """
    js = _APPJS.read_text(encoding="utf-8")
    body = _fn_body(js, "async function _postLabel(slot, url, text) {")
    assert "if (labelBusy[slot]) return;" not in body, (
        "_postLabel 仍有 busy 早退，會造成卡在「儲存中…」"
    )


# ── 設定檔並行寫入（2026-09-04 實測發現）──────────────────────────────────
def test_all_config_writes_hold_the_lock():
    """
    每個 read-modify-write 都必須整段持有 _write_lock。

    2026-09-04 實測：8 個通道標籤同時 POST，HTTP 全部 200，實際只存下 2 筆。
    FastAPI 把同步的 def 端點丟到 threadpool，兩個請求各讀到同一份起始狀態，
    後寫的把先寫的整個蓋掉——兩邊都回成功，其中一筆靜默消失。
    觸發條件很日常：在通道設定頁用 Tab 一路輸入名稱。
    """
    src = (_ROOT / "src" / "app_config.py").read_text(encoding="utf-8")
    assert "_write_lock" in src, "app_config 缺少寫入鎖"
    for fn in ("def save_device_ip(", "def record_connection(",
               "def forget_device_ip(", "def _save_label("):
        assert fn in src, f"找不到 {fn}"
        body = src.split(fn, 1)[1].split("\ndef ", 1)[0]
        assert "_read_json(CONFIG_PATH)" in body, f"{fn} 不是 read-modify-write？"
        lock_at = body.find("with _write_lock:")
        read_at = body.find("_read_json(CONFIG_PATH)")
        assert lock_at != -1, f"{fn} 沒有持有 _write_lock，並行寫入會遺失資料"
        assert lock_at < read_at, (
            f"{fn} 的鎖必須在 _read_json() **之前**取得，"
            "否則仍會發生「兩邊各讀一份、後寫覆蓋先寫」"
        )


def test_concurrent_label_writes_do_not_lose_data(cfg):
    """16 個通道同時寫入，一筆都不能少。"""
    import concurrent.futures as cf

    def write(ch):
        return app_config.save_channel_label(K1, ch, f"通道{ch}")

    with cf.ThreadPoolExecutor(16) as ex:
        assert all(ex.map(write, range(1, 17)))

    got = app_config.device_labels(K1)["channels"]
    missing = sorted(set(str(i) for i in range(1, 17)) - set(got))
    assert not missing, f"並行寫入遺失了通道 {missing}（共 {len(got)}/16 筆）"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
