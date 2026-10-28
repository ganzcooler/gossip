import logging
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


def setup_logging():
    """Configure logging to stdout and monthly log files."""
    log_dir = Path(LOGS_DIR)
    log_dir.mkdir(exist_ok=True)

    # Get log level
    level = getattr(logging, LOG_LEVEL.upper(), logging.DEBUG)

    logging.basicConfig(
        level=level,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            MonthlyFileHandler(log_dir)
        ]
    )

    # Liste der nervigen Bibliotheken auf WARNING oder ERROR setzen
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.INFO)

    return logging.getLogger(__name__)