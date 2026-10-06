import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
DEFAULT_LEVEL = logging.INFO


def setup_logging(log_dir="logs", level=DEFAULT_LEVEL, filename="trading_bot.log"):
    """Send all log records to stdout (visible in `docker compose logs`) and to a rotating file."""
    os.makedirs(log_dir, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = RotatingFileHandler(os.path.join(log_dir, filename), maxBytes=5_000_000, backupCount=3)
    for handler in (logging.StreamHandler(sys.stdout), file_handler):
        handler.setFormatter(formatter)
        root.addHandler(handler)

    for noisy in ("urllib3", "ccxt"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
