"""
主控台輸出編碼防護
==================

**問題**：本專案有 400+ 處 `print()` 帶 emoji（✅ ❌ ⚠️ 🔍 …）。Windows 的
**真實主控台**在 Python 3.6+ 走 Unicode API（PEP 528），emoji 印得出來；
但 stdout 一旦被**導向檔案或 pipe**（打包成 exe 由排程／服務啟動、
`python web/app.py > run.log`、被其他程式包起來執行），就會退回地區編碼
——繁體中文 Windows 是 **cp950**，裝不下任何 emoji。

**為什麼這比「畫面難看」嚴重**：這些 `print` 多半在 `try` 區塊內，
`UnicodeEncodeError` 會被外層的 `except Exception` 當成「操作失敗」吞掉。
實測 `CaparocBackend.connect()` 就這樣在設備完全正常（ping 通、CIP 可連）
的情況下回報連線失敗，log 只留下一行看不出所以然的：

    [ERROR] [CONN] connect() 例外: 'cp950' codec can't encode character '\u274c'

使用者看到的是「連不上設備」，實際上設備好好的。

**修法**：在進入點把 stdout/stderr 的 `errors` 改成 `replace`，裝不下的字元
退化成 `?`，不再拋例外。

⚠️ **刻意不改 `encoding`**：改成 UTF-8 會讓 cp950 主控台的**中文**變亂碼——
為了救裝飾用的 emoji 去弄壞真正重要的訊息，是賠本生意。

用法（每個進入點在 **任何輸出之前** 呼叫一次，重複呼叫無害）::

    from console_io import force_safe_stdio
    force_safe_stdio()
"""

import sys


def force_safe_stdio() -> None:
    """讓 print 不會因為主控台編碼裝不下某個字元而拋 UnicodeEncodeError。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            # pythonw / 無主控台時 stream 可能是 None 或不支援 reconfigure；
            # 這裡失敗只代表「沒得保護」，不該讓程式起不來，故一律吞掉。
            stream.reconfigure(errors="replace")
        except Exception:
            pass
