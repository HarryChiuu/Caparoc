#!/usr/bin/env python3
"""
前端資源版號（cache-busting `?v=`）單一真相來源的回歸測試。

── 為什麼需要這支測試 ──────────────────────────────────────────────
`docs/TODO.md` 技術債 #11：`?v=` 版號原本手寫在 index.html 兩處，改版漏改一處
就會讓使用者的瀏覽器沿用舊的 style.css／app.js，症狀是「新功能沒出現」，
而且**沒有錯誤訊息、沒有 log**——TODO 自評為最難查的一類故障。

2026-09-04 改為由 `src/version.py` 提供、`web/app.py` 在回應時替換。
本測試把「兩處是否同步」從人工複查變成自動偵測：

  1. index.html 不得再出現寫死的 app 版號（必須是 `{{ app_version }}` 佔位符）
  2. 佔位符必須真的被替換掉（不能把 `{{ app_version }}` 原樣送到瀏覽器）
  3. 兩個 app 資源拿到的版號必須一致，且等於 version.ASSET_VERSION

不需要實機、不需要網路。
"""
import re
import sys
import asyncio
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import version as _version  # noqa: E402

_INDEX = _ROOT / "web" / "templates" / "index.html"

# style.css / app.js 是本專案自己的資源，版號必須跟著 ASSET_VERSION 走。
# vendor/ 底下的 chart.js、vue 等是第三方函式庫，`?v=` 是**函式庫自己的版本**，
# 與應用程式版號無關，刻意不納入檢查。
_APP_ASSET_RE = re.compile(r'/static/(?:css/style\.css|js/app\.js)\?v=([^"\']+)')


def _load_web_app():
    """web/ 不是 package，用 importlib 直接載入 app.py（與 test_demo_payload.py 同法）。"""
    sys.argv = ["app.py", "--demo"]          # 避免 import 時嘗試連線真實設備
    spec = importlib.util.spec_from_file_location("caparoc_web_app_ver", _ROOT / "web" / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_template_has_no_hardcoded_app_version():
    """index.html 原始檔裡的 app 資源必須用佔位符，不得寫死版號。"""
    raw = _INDEX.read_text(encoding="utf-8")
    hardcoded = [v for v in _APP_ASSET_RE.findall(raw) if v != "{{ app_version }}"]
    assert not hardcoded, (
        f"index.html 仍有寫死的 app 資源版號 {hardcoded}；"
        "請改用 {{ app_version }}，版號只在 src/version.py 維護（TODO 技術債 #11）"
    )


def test_rendered_page_substitutes_placeholder():
    """實際回應不得把佔位符原樣送出——否則瀏覽器會拿 `?v={{ app_version }}` 當快取鍵。"""
    body = asyncio.run(_load_web_app().index()).body.decode("utf-8")
    assert "{{ app_version }}" not in body, "佔位符未被替換，_render_index() 可能失效"


def test_both_app_assets_share_the_single_source_version():
    """兩個 app 資源的版號必須一致，且等於 version.ASSET_VERSION。"""
    body = asyncio.run(_load_web_app().index()).body.decode("utf-8")
    found = _APP_ASSET_RE.findall(body)

    assert len(found) == 2, f"預期 style.css 與 app.js 各一個版號，實際找到 {found}"
    assert found[0] == found[1], f"兩處版號不一致：{found}——正是技術債 #11 的故障樣態"
    assert found[0] == _version.ASSET_VERSION, (
        f"頁面版號 {found[0]} 與 src/version.py 的 {_version.ASSET_VERSION} 不符"
    )


if __name__ == "__main__":
    test_index_template_has_no_hardcoded_app_version()
    test_rendered_page_substitutes_placeholder()
    test_both_app_assets_share_the_single_source_version()
    print("PASS — 前端資源版號單一真相來源正常")
