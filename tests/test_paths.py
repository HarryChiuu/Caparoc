#!/usr/bin/env python3
"""
`src/paths.py` 路徑解析測試（Phase 5.1）。

── 為什麼需要這支測試 ──────────────────────────────────────────────
paths.py 的重點是**兩種路徑方向相反**，而這個區分在開發模式下**完全看不出來**
——開發時 RESOURCE_DIR 與 DATA_DIR 都等於專案根目錄，寫錯也照樣能跑，
要等打包成 exe 才會壞。正是「開發模式全部正常，問題只在打包後浮現」的那類缺陷。

  內嵌資源 RESOURCE_DIR：web/templates、web/static → sys._MEIPASS（跟著 exe，唯讀）
  外部資料 DATA_DIR    ：config/、logs/           → exe 旁邊（使用者可讀寫）

因此本測試**模擬 frozen 環境**（設好 sys.frozen / sys._MEIPASS / sys.executable
後重新載入 paths），把打包後才會出現的行為提前到 CI 就能驗證。
不需要真的跑 PyInstaller——frozen 偵測只看那兩個屬性。

不需實機、不需網路。
"""
import sys
import importlib
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import paths as _paths  # noqa: E402

_FAKE_MEIPASS = r"C:\FAKE\_MEI12345" if sys.platform == "win32" else "/fake/_MEI12345"
_FAKE_EXEDIR = r"C:\Program Files\Caparoc" if sys.platform == "win32" else "/opt/caparoc"


class _frozen:
    """context manager：在區塊內把 paths 重新載入成模擬的 frozen 狀態。

    paths 的常數是 import 時求值的，所以必須 reload 才會反映新的 sys 狀態；
    離開區塊時再 reload 回開發模式，避免污染同一個 process 內的其他測試。

    ⚠️ 必須在區塊**內**讀取常數。回傳模組物件再於區塊外讀會拿到還原後的值
    （模組是同一個物件，reload 就地改寫它的屬性），斷言會失去意義。
    """

    def __enter__(self):
        self._saved_exec = sys.executable
        self._had_frozen = hasattr(sys, "frozen")
        self._had_meipass = hasattr(sys, "_MEIPASS")
        sys.frozen = True                      # type: ignore[attr-defined]
        sys._MEIPASS = _FAKE_MEIPASS           # type: ignore[attr-defined]
        sys.executable = str(Path(_FAKE_EXEDIR) / "caparoc.exe")
        return importlib.reload(_paths)

    def __exit__(self, *exc):
        sys.executable = self._saved_exec
        if not self._had_frozen:
            delattr(sys, "frozen")
        if not self._had_meipass:
            delattr(sys, "_MEIPASS")
        importlib.reload(_paths)               # 還原成開發模式
        return False


# ── 開發模式 ────────────────────────────────────────────────────────────────
def test_dev_mode_is_not_frozen():
    assert _paths.IS_FROZEN is False
    assert _paths.RESOURCE_DIR == _paths.DATA_DIR == _ROOT


def test_dev_mode_dirs_point_at_real_project_layout():
    """開發模式下這些目錄必須真的存在，否則是解析錯了。"""
    assert _paths.CONFIG_DIR.is_dir()
    assert (_paths.WEB_DIR / "templates").is_dir()
    assert (_paths.WEB_DIR / "static").is_dir()


# ── frozen 模式（打包後才會出現的行為）──────────────────────────────────────
def test_frozen_embedded_resources_live_in_meipass():
    """templates/static 跟著 exe 走，必須落在 _MEIPASS。"""
    with _frozen() as p:
        assert p.IS_FROZEN is True
        assert p.RESOURCE_DIR == Path(_FAKE_MEIPASS)
        assert p.WEB_DIR == Path(_FAKE_MEIPASS) / "web"


def test_frozen_external_data_lives_next_to_exe():
    """config/logs 必須落在 exe 旁邊，否則使用者改不到、log 一關就消失。"""
    with _frozen() as p:
        assert p.DATA_DIR == Path(_FAKE_EXEDIR)
        assert p.CONFIG_DIR == Path(_FAKE_EXEDIR) / "config"
        assert p.LOG_DIR == Path(_FAKE_EXEDIR) / "logs"


def test_frozen_two_bases_must_diverge():
    """兩種 base 在 frozen 下必須不同——相等就代表某一邊用錯了 base。

    這是本模組最核心的不變式：開發模式相等是正常的，frozen 下相等就是 bug。
    """
    with _frozen() as p:
        assert p.RESOURCE_DIR != p.DATA_DIR


# ── resolve_data_dir ────────────────────────────────────────────────────────
def test_resolve_data_dir_relative_uses_data_base():
    """相對路徑以 DATA_DIR 為基準，不受 CWD 影響。"""
    with _frozen() as p:
        assert p.resolve_data_dir("logs", p.LOG_DIR) == Path(_FAKE_EXEDIR) / "logs"


def test_resolve_data_dir_absolute_is_respected():
    """使用者明確指定絕對路徑就尊重，不要再接到 DATA_DIR 後面。"""
    abs_dir = r"D:\mylogs" if sys.platform == "win32" else "/var/log/caparoc"
    assert _paths.resolve_data_dir(abs_dir, _paths.LOG_DIR) == Path(abs_dir)


def test_resolve_data_dir_empty_falls_back_to_default():
    assert _paths.resolve_data_dir("", _paths.LOG_DIR) == _paths.LOG_DIR
    assert _paths.resolve_data_dir(None, _paths.LOG_DIR) == _paths.LOG_DIR


# ── 回歸防護 ────────────────────────────────────────────────────────────────
def test_no_module_resolves_files_via_dunder_file():
    """
    src/ 與 web/ 底下不得再用 `Path(__file__)` 定位**檔案**。

    例外是 sys.path bootstrap（把 src/ 加進路徑），那必須先於 import paths
    執行，無法改用本模組——因此只允許出現在 sys.path.insert 那一行附近。
    """
    offenders = []
    for f in list((_ROOT / "src").glob("*.py")) + list((_ROOT / "web").glob("*.py")):
        if f.name == "paths.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "Path(__file__)" not in line:
                continue
            # bootstrap 允許：sys.path 那行，或僅作為 _WEB_DIR/_ROOT_DIR 的來源
            if "sys.path" in line or "_WEB_DIR = " in line:
                continue
            offenders.append(f"{f.relative_to(_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "以下位置仍用 Path(__file__) 定位檔案，打包後會指向暫存解壓目錄：\n  "
        + "\n  ".join(offenders)
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("全部通過")
