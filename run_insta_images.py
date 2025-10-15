from src.insta_images import create_insta_images
import logging
from src import config
import sys

if __name__ == "__main__":
    log_dir = config.PROJECT_ROOT / config.LOG_DIR_NAME
    log_dir.mkdir(parents=True, exist_ok=True)
    log_filepath = log_dir / "insta_images.log"

    # Set up a logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Add a file handler
    fh = logging.FileHandler(log_filepath, encoding="utf-8")
    fh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(fh)

    # Also add a stream handler to see logs in the console
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(config.LOG_FORMAT))
    logger.addHandler(sh)

    create_insta_images()
