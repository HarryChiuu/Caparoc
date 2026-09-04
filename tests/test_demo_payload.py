#!/usr/bin/env python3
"""
demo 模式 payload 與真實 payload 的結構一致性測試（不需設備、不需網路）

用法：
  python tests/test_demo_payload.py       # 直接跑，印 PASS / 總結
  pytest tests/test_demo_payload.py       # 純 assert 函式，pytest 也能收

⚠️ 需在**裝有 fastapi 的環境**執行（本測試會 import `web/app.py`）——即 conda env `sv`。
（2026-09-04 更正：該環境已裝 pytest 9.1.1，`python -m pytest` 是現在的主要執行方式；
檔案底部的 `__main__` 區塊仍保留，直接執行也可以。）

── 為什麼需要這支測試 ──────────────────────────────────────────────
`web/app.py` 有兩條產生前端 payload 的路徑，必須保持結構一致：

  真實：_read_current_status()  →  _format_status()  →  前端
  demo：_generate_demo_payload()                     →  前端

新增欄位時只改真實路徑、忘了改 demo，`--demo` 會**靜默壞掉**：前端讀到
`undefined`，畫面上該功能就是不出現，沒有錯誤訊息、沒有 log。

`docs/TODO.md` 的技術債表第 10 項早就預言過這件事，而它在 2026-09-01 真的
發生了——`nominal_readonly` 只加在 `_format_status()`，demo 的 8 個通道都
沒有這個欄位，導致 2 通道模組的 badge 與反灰在 `--demo` 下永遠不出現，
沒有實機就無法檢視或除錯那個 UI。從實作到發現隔了約一週。

本測試把「漏寫 demo 分支」從人工複查變成自動偵測。
"""
import sys
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _load_web_app():
    """web/ 不是 package，用 importlib 直接載入 app.py。

    import 時不會連線設備（連線在 lifespan 內才發生），因此本測試無需實機。
    """
    spec = importlib.util.spec_from_file_location("caparoc_web_app", _ROOT / "web" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


app_mod = _load_web_app()

# nominal_min/max 來自 backend（型號經 HTTP 解析），不在 _read_current_status 的
# 輸出裡，因此 _fake_raw() 蓋不到。測試不連線設備時該字典是空的，真實 payload
# 會拿到 None、demo 拿到數字，型別比對就會誤報。這裡填入與 demo 相同的範圍，
# 讓兩邊可比對——正式執行時仍由 _load_module_ranges() 從設備讀取。
app_mod.backend._module_nominal_range = {1: (1, 4), 2: (2, 10)}


# ── 模擬 _read_current_status() 的輸出 ────────────────────────────────
# 欄位與型別對齊 src/caparoc_backend.py 的 result / channels 建構區塊。
# 兩個模組共 8 通道，與 demo 的規模一致，方便逐通道比對。
def _fake_raw() -> dict:
    channels = {}
    for global_ch in range(1, 9):
        module = 1 if global_ch <= 4 else 2
        channel = global_ch - (module - 1) * 4
        channels[global_ch] = {
            'module':          module,
            'channel':         channel,
            'is_on':           bool(global_ch % 2),
            'flowing_current': global_ch / 10.0,
            'nominal_current': float(4),
            'warning_80':      False,
            'overload':        False,
            'short_circuit':   False,
            'hardware_fault':  False,
            'total_shutdown':  False,
        }
    return {
        'timestamp':          1_756_700_000.0,   # time.time()
        'global_status_byte': 0,
        'module_count':       2,
        'total_current':      3.6,
        'voltage':            24.04,
        'channels':           channels,
    }


# ── 型別比對 ─────────────────────────────────────────────────────────
def _kind(val) -> str:
    """
    值的「型別家族」。

    int 與 float 視為同族——真實路徑的 `round()` 與 demo 的字面值可能一邊
    給 int 一邊給 float，那不是缺陷。但 str vs 數字、None vs 值就是真漂移，
    前端拿到會出錯或顯示成 NaN。

    ⚠️ bool 必須排在 int 之前判斷：Python 的 bool 是 int 的子類別，
    順序寫反的話 True/False 會被歸成 number，讓「布林欄位變成數字」漏檢。
    """
    if isinstance(val, bool):
        return "bool"
    if isinstance(val, (int, float)):
        return "number"
    if val is None:
        return "none"
    return type(val).__name__


def _fmt_diff(label: str, only_real: set, only_demo: set) -> str:
    parts = []
    if only_real:
        parts.append(f"只在真實 payload 有（demo 漏寫）：{sorted(only_real)}")
    if only_demo:
        parts.append(f"只在 demo 有（真實路徑漏寫或已移除）：{sorted(only_demo)}")
    return f"{label} 欄位不一致 — " + "；".join(parts)


# ── 測試 ─────────────────────────────────────────────────────────────
def test_top_level_keys_match():
    """頂層欄位集合必須完全相同。"""
    real = app_mod._format_status(_fake_raw())
    demo = app_mod._generate_demo_payload()
    r, d = set(real), set(demo)
    assert r == d, _fmt_diff("頂層", r - d, d - r)


def test_channel_keys_match():
    """每個 demo 通道的欄位集合都必須與真實通道相同。

    逐通道檢查而非只看第一個——漏寫可能只發生在某幾列（例如手寫的 demo
    通道清單中改了模組 1 卻忘了模組 2）。
    """
    real = app_mod._format_status(_fake_raw())
    demo = app_mod._generate_demo_payload()
    assert real["channels"], "測試資料有誤：真實 payload 沒有通道"
    assert demo["channels"], "demo payload 沒有通道"

    expected = set(real["channels"][0])
    for ch in demo["channels"]:
        got = set(ch)
        assert got == expected, _fmt_diff(
            f"demo 通道 id={ch.get('id')}（模組 {ch.get('module')}）",
            expected - got, got - expected,
        )


def test_top_level_types_match():
    """頂層欄位的型別家族必須相同（str vs 數字這類漂移前端會出錯）。"""
    real = app_mod._format_status(_fake_raw())
    demo = app_mod._generate_demo_payload()
    mismatched = {
        k: (_kind(real[k]), _kind(demo[k]))
        for k in set(real) & set(demo)
        if k != "channels" and _kind(real[k]) != _kind(demo[k])
    }
    assert not mismatched, (
        "頂層欄位型別不一致（真實, demo）：" +
        "；".join(f"{k}: {v[0]} vs {v[1]}" for k, v in sorted(mismatched.items()))
    )


def test_channel_types_match():
    """通道欄位的型別家族必須相同。"""
    real = app_mod._format_status(_fake_raw())
    demo = app_mod._generate_demo_payload()
    ref = real["channels"][0]
    for ch in demo["channels"]:
        mismatched = {
            k: (_kind(ref[k]), _kind(ch[k]))
            for k in set(ref) & set(ch)
            if _kind(ref[k]) != _kind(ch[k])
        }
        assert not mismatched, (
            f"demo 通道 id={ch.get('id')} 欄位型別不一致（真實, demo）：" +
            "；".join(f"{k}: {v[0]} vs {v[1]}" for k, v in sorted(mismatched.items()))
        )


def test_demo_covers_nominal_readonly_both_ways():
    """
    demo 必須同時涵蓋 nominal_readonly 的 True 與 False。

    只有欄位存在還不夠——若全部都是 False，通道設定頁的 badge、輸入欄反灰、
    說明 modal 這條路徑在 `--demo` 下依然看不到，等於沒有實機就無法檢視。
    這正是 2026-09-01 修掉的那個缺陷的完整形式。
    """
    demo = app_mod._generate_demo_payload()
    # 用 .get() 而非 []：欄位整個消失時應回報清楚的訊息，
    # 而不是 KeyError（那會蓋掉真正的診斷資訊）
    missing = [ch.get("id") for ch in demo["channels"] if "nominal_readonly" not in ch]
    assert not missing, f"demo 通道 {missing} 沒有 nominal_readonly 欄位"

    values = {ch["nominal_readonly"] for ch in demo["channels"]}
    assert values == {True, False}, (
        f"demo 的 nominal_readonly 只出現 {values}；"
        "需同時有可寫與 read-only 的模組，否則 --demo 下看不到 read-only UI"
    )


def test_demo_module_count_matches_channels():
    """demo 宣告的 module_count 必須與通道實際涵蓋的模組數一致。"""
    demo = app_mod._generate_demo_payload()
    modules = {ch["module"] for ch in demo["channels"]}
    assert demo["module_count"] == len(modules), (
        f"module_count={demo['module_count']} 但通道只涵蓋 {sorted(modules)}"
    )


# ── 直接執行 ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}\n        {e}")
        except Exception as e:
            # 一支測試因結構缺漏而拋例外（如 KeyError）時，其餘測試仍要跑完——
            # 漏寫欄位通常會同時打到好幾支，一次看到全部比逐次修快
            failed += 1
            print(f"  ERROR {fn.__name__}\n        {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通過")
    sys.exit(1 if failed else 0)
