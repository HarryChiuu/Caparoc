"""
CAPAROC Log 管理模組

架構：一個 Logger，多個出口
  - FileHandler   → logs/caparoc_YYYY-MM-DD.log  (人類可讀)
  - JsonlHandler  → logs/caparoc_YYYY-MM-DD.jsonl (結構化，未來 API 串接用)
  - QueueHandler  → GUI LogPanel 訂閱 (caparoc_gui.py 用)
  - RemoteHandler → 佔位符，未來實作 HTTP/MQTT/Syslog 推送到 Linux 主機

使用方式：
  # 程式啟動時初始化一次
  import logging_manager
  logging_manager.setup()

  # 任何地方取用
  logger = logging_manager.get_logger()
  logger.info('CH1 開啟', extra={'log_module': 'CTRL', 'channel': 1})
"""

import json
import logging
import logging.handlers
import queue
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ─── Module-level singleton ──────────────────────────────────────────────────
_instance: Optional['LogManager'] = None


def setup(config_path: str = None, enable_gui_queue: bool = False) -> 'LogManager':
    """
    初始化 LogManager（程式啟動時呼叫一次）。

    Args:
        config_path:      logging_config.json 路徑。None = 自動尋找 config/logging_config.json
        enable_gui_queue: True = 建立 GUI 用的 Queue（caparoc_gui.py 傳入 True）

    Returns:
        LogManager 單例
    """
    global _instance
    if _instance is None:
        _instance = LogManager(config_path, enable_gui_queue)
    return _instance


def get_logger(name: str = 'caparoc') -> logging.Logger:
    """取得已設定的 logger。若尚未 setup()，回傳基本 logger（不寫檔）。"""
    return logging.getLogger(name)


def get_instance() -> Optional['LogManager']:
    """取得 LogManager 單例（可能為 None）。"""
    return _instance


# ─── Custom JSONL Handler ────────────────────────────────────────────────────
class _JsonlHandler(logging.FileHandler):
    """每行寫入一條 JSON，供未來 API 串接或 Filebeat 採集。"""

    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                'ts': datetime.fromtimestamp(record.created).strftime('%Y-%m-%dT%H:%M:%S'),
                'level': record.levelname,
                'module': getattr(record, 'log_module', 'SYS'),
                'msg': record.getMessage(),
            }
            # 附加結構化欄位（由 extra= 傳入）
            for key in ('ip', 'channel', 'current', 'amps', 'voltage',
                        'modules', 'verified', 'elapsed', 'error'):
                val = getattr(record, key, None)
                if val is not None:
                    entry[key] = val

            self.stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
            self.flush()
        except Exception:
            self.handleError(record)


# ─── RemoteHandler 佔位符 ────────────────────────────────────────────────────
class RemoteHandler(logging.Handler):
    """
    未來擴充用：推送 log 到遠端 Linux 主機。

    實作選項（擇一）：
      - HTTP POST (REST API)
      - MQTT publish
      - UDP Syslog (RFC 5424)
      - Redis LPUSH
      - Fluentd forward protocol

    啟用方式（logging_config.json）：
        "remote": {
            "enabled": true,
            "type": "http",
            "url": "http://192.168.1.100:8080/api/logs",
            "token": "your-secret-token"
        }

    實作時只需繼承此類並 override emit()，不需改動其他程式。
    """

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._enabled = config.get('enabled', False)

    def emit(self, record: logging.LogRecord):
        if not self._enabled:
            return
        # ─── TODO: 在此實作遠端推送邏輯 ───────────────────────────
        # 範例（HTTP POST）：
        #
        # import requests, json
        # entry = {
        #     'ts': datetime.fromtimestamp(record.created).isoformat(),
        #     'level': record.levelname,
        #     'module': getattr(record, 'log_module', 'SYS'),
        #     'msg': record.getMessage(),
        # }
        # headers = {'Authorization': f"Bearer {self.config.get('token', '')}"}
        # requests.post(self.config['url'], json=entry, headers=headers, timeout=3)
        pass


# ─── LogManager ──────────────────────────────────────────────────────────────
class LogManager:

    DEFAULT_CONFIG = {
        'log_level':      'INFO',
        'retention_days': 0,         # 0 = 永不自動清除
        'log_dir':        'logs',
        'write_jsonl':    True,
        'remote': {
            'enabled':             False,
            'type':                'http',
            'url':                 '',
            'batch_size':          50,
            'flush_interval_sec':  60,
            'token':               '',
        },
    }

    def __init__(self, config_path: str = None, enable_gui_queue: bool = False):
        self.config = self._load_config(config_path)
        self.gui_queue: Optional[queue.Queue] = None
        self._logger = logging.getLogger('caparoc')
        self._setup_logger(enable_gui_queue)

    # ── 設定檔 ────────────────────────────────────────────────────────────────
    def _load_config(self, config_path: str) -> dict:
        cfg = dict(self.DEFAULT_CONFIG)
        cfg['remote'] = dict(self.DEFAULT_CONFIG['remote'])

        if config_path is None:
            here = Path(__file__).parent
            config_path = here.parent / 'config' / 'logging_config.json'

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                user_cfg = json.load(f)
                cfg.update({k: v for k, v in user_cfg.items() if k != 'remote'})
                if 'remote' in user_cfg:
                    cfg['remote'].update(user_cfg['remote'])
        except FileNotFoundError:
            pass  # 使用預設值
        except Exception as e:
            print(f'[LogManager] 無法讀取設定檔: {e}，使用預設值')

        return cfg

    # ── 初始化 handlers ───────────────────────────────────────────────────────
    def _setup_logger(self, enable_gui_queue: bool):
        logger = self._logger
        logger.setLevel(getattr(logging, self.config['log_level'].upper(), logging.INFO))
        logger.handlers.clear()
        logger.propagate = False

        # 建立 logs/ 目錄
        log_dir = Path(self.config['log_dir'])
        log_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now().strftime('%Y-%m-%d')

        # 日誌格式：時間戳 [等級] [模組] 訊息
        fmt = logging.Formatter(
            '%(asctime)s [%(levelname)-7s] [%(log_module)-4s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

        # Handler 1 ── .log 人類可讀 ──────────────────────────────────────────
        log_file = log_dir / f'caparoc_{today}.log'
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(fmt)
        logger.addHandler(fh)

        # Handler 2 ── .jsonl 結構化 ──────────────────────────────────────────
        if self.config.get('write_jsonl', True):
            jsonl_file = log_dir / f'caparoc_{today}.jsonl'
            jh = _JsonlHandler(str(jsonl_file), encoding='utf-8')
            logger.addHandler(jh)

        # Handler 3 ── GUI Queue（caparoc_gui.py 啟用）────────────────────────
        if enable_gui_queue:
            self.gui_queue = queue.Queue()
            qh = logging.handlers.QueueHandler(self.gui_queue)
            logger.addHandler(qh)

        # Handler 4 ── Remote（設定 enabled=true 後生效）─────────────────────
        remote_cfg = self.config.get('remote', {})
        if remote_cfg.get('enabled', False):
            rh = RemoteHandler(remote_cfg)
            logger.addHandler(rh)

        # 啟動訊息
        logger.info(
            f'日誌系統啟動 → {log_file}',
            extra={'log_module': 'SYS'},
        )

    # ── 清除舊檔（手動呼叫或由排程觸發）─────────────────────────────────────
    def cleanup_old_logs(self, retention_days: int = None) -> list[str]:
        """
        清除超過保留天數的 log 檔案。

        Args:
            retention_days: 保留天數。
                            None  → 使用 logging_config.json 的 retention_days。
                            0     → 不清除，直接返回。
                            N > 0 → 刪除 N 天前的 .log 與 .jsonl 檔案。

        Returns:
            已刪除的檔名列表（空列表代表無刪除）。
        """
        days = retention_days if retention_days is not None else self.config.get('retention_days', 0)

        if days <= 0:
            return []

        log_dir = Path(self.config['log_dir'])
        cutoff = datetime.now() - timedelta(days=days)
        removed = []

        for pattern in ('*.log', '*.jsonl'):
            for f in log_dir.glob(pattern):
                try:
                    # 從檔名解析日期：caparoc_YYYY-MM-DD.log → YYYY-MM-DD
                    date_str = f.stem.split('_', 1)[1]
                    file_date = datetime.strptime(date_str, '%Y-%m-%d')
                    if file_date < cutoff:
                        f.unlink()
                        removed.append(f.name)
                except (ValueError, IndexError):
                    pass  # 跳過非標準檔名

        if removed:
            self._logger.info(
                f'清除 {len(removed)} 個舊 log 檔 (>{days} 天): {", ".join(sorted(removed))}',
                extra={'log_module': 'SYS'},
            )

        return removed

    @property
    def logger(self) -> logging.Logger:
        return self._logger
