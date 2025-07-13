import logging
import pathlib

log_dir = pathlib.Path("logs")
log_dir.mkdir(parents=True, exist_ok=True)
log_filepath = log_dir / "test.log"

logger = logging.getLogger("test_logger")
logger.setLevel(logging.INFO)

fh = logging.FileHandler(log_filepath, encoding="utf-8")
fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(fh)

logger.info("This is a test message.")

print(f"Log file should be at: {log_filepath.resolve()}")
print(f"Log file exists: {log_filepath.exists()}")
