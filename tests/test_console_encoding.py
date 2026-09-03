#!/usr/bin/env python3
"""
主控台編碼防護測試（不需設備、不需網路）

用法：
  python tests/test_console_encoding.py     # 直接跑，印 PASS / 總結
  pytest tests/test_console_encoding.py     # 純 assert 函式，pytest 也能收

── 為什麼需要這支測試 ──────────────────────────────────────────────
本專案有 400+ 處帶 emoji 的 `print()`。Windows 真實主控台走 Unicode API
（PEP 528）印得出來，但 **stdout 被導向檔案／pipe** 時會退回地區編碼
（繁中 = cp950），任何一個 emoji 都會拋 `UnicodeEncodeError`。

致命之處在於這些 print 多半在 `try` 內，例外會被 `except Exception` 當成
「操作失敗」吞掉。2026-09-03 實測：設備 ping 通、CIP 直連成功，但
`python web/app.py > run.log` 啟動時 `connect()` 回報失敗，log 只有

    [ERROR] [CONN] connect() 例外: 'cp950' codec can't encode character '\u274c'

使用者看到「連不上設備」，設備其實好好的。

本測試把它釘住：**進入點必須先呼叫 `force_safe_stdio()`**，之後
往 cp950 串流印 emoji 只會退化成 `?`，不得拋例外。
"""

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from console_io import force_safe_stdio  # noqa: E402

# 專案實際用到、且 cp950 一律裝不下的字元
EMOJI = "✅❌⚠️🔍📊💡🌐⏳🔧"


def _cp950_stream() -> io.TextIOWrapper:
    """模擬「stdout 被導向檔案」時 Python 在繁中 Windows 給的串流。"""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp950")


def test_cp950_stream_raises_without_protection():
    """前提驗證：沒有防護時，往 cp950 串流印 emoji 確實會炸。

    這支若失敗，代表環境不再重現該情境，其餘測試就失去意義（而非程式修好了）。
    """
    stream = _cp950_stream()
    try:
        stream.write(EMOJI)
        stream.flush()
    except UnicodeEncodeError:
        return
    raise AssertionError("cp950 串流竟然吃得下 emoji，測試前提已不成立")


def test_reconfigure_replaces_instead_of_raising():
    """`errors='replace'` 後同樣的寫入只會退化成 '?'，不得拋例外。"""
    stream = _cp950_stream()
    stream.reconfigure(errors="replace")
    stream.write(EMOJI)
    stream.flush()
    out = stream.buffer.getvalue().decode("cp950")
    assert "?" in out, f"未看到退化字元: {out!r}"


def test_cjk_still_readable_after_protection():
    """⚠️ 只改 errors、不改 encoding：中文必須維持正確，不能為了 emoji 弄壞它。"""
    stream = _cp950_stream()
    stream.reconfigure(errors="replace")
    stream.write("連線成功：3 模組 12 通道 ✅")
    stream.flush()
    out = stream.buffer.getvalue().decode("cp950")
    assert "連線成功：3 模組 12 通道" in out, f"中文被破壞: {out!r}"


def test_force_safe_stdio_is_idempotent_and_never_raises():
    """重複呼叫無害；stdout 為 None（pythonw）時也不得炸。"""
    force_safe_stdio()
    force_safe_stdio()

    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        sys.stdout = sys.stderr = None
        force_safe_stdio()          # 不得拋例外
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err


def test_entry_points_call_force_safe_stdio():
    """三個進入點都必須在任何輸出之前掛上防護（靜態檢查，不需依賴套件）。"""
    for rel in ("web/app.py", "src/caparoc_controller.py", "src/caparoc_ip_config.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "force_safe_stdio()" in src, f"{rel} 未呼叫 force_safe_stdio()"
        # 必須早於 caparoc_backend——connect() 正是踩雷的那支
        call = src.index("force_safe_stdio()")
        backend = src.find("from caparoc_backend import")
        assert backend == -1 or call < backend, f"{rel} 的防護晚於 caparoc_backend 匯入"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通過")
    sys.exit(1 if failed else 0)
