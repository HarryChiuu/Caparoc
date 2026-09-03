#!/usr/bin/env python3
"""
Log 保留策略測試（不需設備、不需網路、不碰真實 logs/）

用法：
  python tests/test_log_retention.py     # 直接跑，印 PASS / 總結
  pytest tests/test_log_retention.py     # 純 assert 函式，pytest 也能收

── 為什麼需要這支測試 ──────────────────────────────────────────────
2026-09-03 設定鍵稽核發現 `logging.retention_days` 是**死設定**：
`cleanup_old_logs()` 功能寫好了，但**全 repo 沒有任何呼叫者**——不在啟動
流程、沒有排程器、CLI 與 web 都沒接。使用者把它改成 10，logs/ 裡 25 個檔
（最舊超過三個月）一個都沒刪。

附帶還有一個潛伏缺陷：`cleanup_old_logs()` 直接用 `Path(config['log_dir'])`
建路徑，**沒做相對轉絕對**，而 `_setup_logger()` 有做。兩者不一致的後果是
從不同工作目錄啟動時「寫入 A 目錄、清除 B 目錄」——接線的當下才會爆。

本測試把三件事釘住：
  1. 清除門檻正確（只刪超過 N 天的，邊界日不刪）
  2. 相對 log_dir 一律以專案根目錄為基準，不受 CWD 影響
  3. web/app.py 的 lifespan 真的有呼叫（回歸「功能寫好但沒接上」）
"""

import logging
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import logging_manager  # noqa: E402


def _make_manager(log_dir, retention_days):
    """不經 __init__（會真的架 handler 寫檔），直接組出可測的實例。"""
    mgr = logging_manager.LogManager.__new__(logging_manager.LogManager)
    mgr.config = dict(logging_manager.LogManager.DEFAULT_CONFIG)
    mgr.config["log_dir"] = str(log_dir)
    mgr.config["retention_days"] = retention_days
    mgr._logger = logging.getLogger("caparoc.test_retention")
    return mgr


def test_removes_only_files_older_than_retention():
    """retention=10 → 只有 11 天前與 30 天前該被刪；邊界的第 10 天要留著。"""
    tmp = Path(tempfile.mkdtemp(prefix="caparoc_logtest_"))
    try:
        today = date.today()
        ages = (0, 5, 9, 10, 11, 30)
        for d in ages:
            (tmp / f"caparoc_{today - timedelta(days=d)}.log").write_text("x", encoding="utf-8")

        removed = _make_manager(tmp, 10).cleanup_old_logs()

        expect_gone = {f"caparoc_{today - timedelta(days=d)}.log" for d in (11, 30)}
        expect_kept = {f"caparoc_{today - timedelta(days=d)}.log" for d in (0, 5, 9, 10)}
        assert set(removed) == expect_gone, f"刪除清單不符: {sorted(removed)}"
        assert {p.name for p in tmp.iterdir()} == expect_kept, "留下的檔案不符"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_retention_zero_removes_nothing():
    """0 = 永不自動清除（config.example.json 的預設值），必須是 no-op。"""
    tmp = Path(tempfile.mkdtemp(prefix="caparoc_logtest_"))
    try:
        old = tmp / f"caparoc_{date.today() - timedelta(days=999)}.log"
        old.write_text("x", encoding="utf-8")

        assert _make_manager(tmp, 0).cleanup_old_logs() == []
        assert old.exists(), "retention_days=0 竟然刪了檔案"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_relative_log_dir_is_cwd_independent():
    """
    相對路徑必須解析到專案根目錄，不是 CWD。

    這正是原本的缺陷：_setup_logger() 有轉絕對、cleanup_old_logs() 沒有，
    從別的目錄啟動就會寫 A 清 B。
    """
    mgr = _make_manager("logs", 10)
    saved = os.getcwd()
    try:
        os.chdir(tempfile.gettempdir())
        assert mgr._resolve_log_dir() == ROOT / "logs", "相對 log_dir 被 CWD 影響"
    finally:
        os.chdir(saved)


def test_setup_and_cleanup_share_one_resolution():
    """兩條路徑必須走同一個 _resolve_log_dir()，不得各自 Path() 一次。"""
    src = (ROOT / "src" / "logging_manager.py").read_text(encoding="utf-8")
    body = src[src.index("def _setup_logger"):]
    assert "Path(self.config['log_dir'])" not in body, \
        "_setup_logger/cleanup_old_logs 又各自建路徑了，請共用 _resolve_log_dir()"


def test_cleanup_is_actually_wired_to_web_startup():
    """
    回歸「功能寫好但沒接上觸發點」——web/app.py 的 lifespan 必須呼叫它。

    2026-09-03 之前這裡是空的，retention_days 設什麼都沒用。
    """
    src = (ROOT / "web" / "app.py").read_text(encoding="utf-8")
    assert "cleanup_old_logs" in src, "web/app.py 未接上 cleanup_old_logs()"
    lifespan = src[src.index("async def lifespan"):]
    lifespan = lifespan[:lifespan.index("\nyield") if "\nyield" in lifespan else len(lifespan)]
    assert "_cleanup_old_logs" in lifespan, "cleanup 不在 lifespan 內"
    # 必須早於 _DEMO_MODE early return，否則 demo 模式下不會執行
    assert lifespan.index("_cleanup_old_logs") < lifespan.index("if _DEMO_MODE"), \
        "cleanup 晚於 _DEMO_MODE early return，demo 模式會跳過"


def test_module_level_helper_safe_before_setup():
    """尚未 setup() 時呼叫模組層入口不得拋例外。"""
    saved = logging_manager._instance
    try:
        logging_manager._instance = None
        assert logging_manager.cleanup_old_logs() == []
    finally:
        logging_manager._instance = saved


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
