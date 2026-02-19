import logging
from datetime import datetime
from pathlib import Path
from app.config import LOGS_DIR, LOG_LEVEL


def setup_logging():
    """Configure logging to stdout and monthly log files."""
    log_dir = Path(LOGS_DIR)
    log_dir.mkdir(exist_ok=True)

    # Monthly log file
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m')}.log"

    # Get log level
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )

    return logging.getLogger(__name__)