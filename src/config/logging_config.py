"""Logging: console + rotating file in logs/."""
import logging
from logging.handlers import RotatingFileHandler

from src.config.settings import LOG_DIR

_configured = False


def setup_logging(level=logging.INFO):
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file = RotatingFileHandler(LOG_DIR / "agent.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    file.setFormatter(fmt)
    root.addHandler(console)
    root.addHandler(file)
    for noisy in ("urllib3", "asyncio", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name):
    setup_logging()
    return logging.getLogger(name)
