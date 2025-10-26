import logging
import sys
from src import config

def setup_logger() -> logging.Logger:
    """Sets up and returns a configured logger for the pipeline."""
    log_dir = config.PROJECT_ROOT / config.LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    log_filepath = log_dir / config.get_log_filename()

    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.INFO)

    # Remove existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()

    # Add a file handler
    fh = logging.FileHandler(log_filepath, encoding="utf-8")
    fh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(fh)

    # Also add a stream handler to see logs in the console
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(sh)

    return logger
