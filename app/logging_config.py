import logging
from datetime import datetime
from pathlib import Path
from app.core.config import LOGS_DIR, LOG_LEVEL


def setup_logging():
    """Configure logging to stdout and monthly log files."""
    log_dir = Path(LOGS_DIR)
    log_dir.mkdir(exist_ok=True)

    # Monthly log file
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m')}.log"

    # Get log level
    level = getattr(logging, LOG_LEVEL.upper(), logging.DEBUG)

    logging.basicConfig(
        level=level,
        format='%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding='utf-8')
        ]
    )

    # Liste der nervigen Bibliotheken auf WARNING oder ERROR setzen
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.INFO)

    return logging.getLogger(__name__)