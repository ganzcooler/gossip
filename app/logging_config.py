import logging
import sys
from datetime import datetime
from pathlib import Path

from app.core.config import LOGS_DIR, LOG_LEVEL


class MonthlyFileHandler(logging.Handler):
    """A logging handler that creates a new file each month, named YYYY-MM.log."""

    def __init__(self, log_dir: str, encoding: str = 'utf-8'):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.encoding = encoding
        self._current_month = None
        self._handler = None

    def setFormatter(self, fmt):
        super().setFormatter(fmt)
        if self._handler is not None:
            self._handler.setFormatter(fmt)

    def _ensure_handler(self):
        now = datetime.now()
        month_key = now.strftime('%Y-%m')
        if month_key != self._current_month:
            if self._handler is not None:
                self._handler.close()
            log_file = self.log_dir / f"{month_key}.log"
            self._handler = logging.FileHandler(log_file, encoding=self.encoding)
            if self.formatter:
                self._handler.setFormatter(self.formatter)
            self._current_month = month_key
        return self._handler

    def emit(self, record):
        handler = self._ensure_handler()
        handler.emit(record)

    def flush(self):
        if self._handler is not None:
            self._handler.flush()

    def close(self):
        if self._handler is not None:
            self._handler.close()
        super().close()


LOG_FORMAT = '%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S'


def setup_logging():
    """Configure identical logging to stdout and the monthly log file.

    Both handlers have no level of their own, so they always receive the same
    records. ``LOG_LEVEL=INFO`` therefore writes every warning and error plus
    the result of every Jev decision call to the console and to the file.
    """
    log_dir = Path(LOGS_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Get log level
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.NOTSET)

    file_handler = MonthlyFileHandler(log_dir)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.NOTSET)

    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

    # Route warnings.warn() through logging as well, so it also reaches the file.
    logging.captureWarnings(True)

    # Uvicorn installs non-propagating handlers before importing the app.
    # Route its warning/error logger through the root handlers so startup and
    # server errors are also written to the monthly file.
    for logger_name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
        uvicorn_logger.setLevel(logging.NOTSET)

    # Liste der nervigen Bibliotheken auf WARNING oder ERROR setzen
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.INFO)

    return logging.getLogger(__name__)
