"""Centralized logging utility."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "Soundboard"
LOGS_FOLDER_PATH = Path(__file__).resolve().parent.parent / "logs"


def _build_root_logger() -> logging.Logger:

    LOGS_FOLDER_PATH.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(APP_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / LOG_FILENAME,
        maxBytes=2 * 1024 * 1024 ,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    return root


_root_logger = _build_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger that feeds the app's root logger."""
    return logging.getLogger(f"{APP_NAME}.{name}")


def get_log_path() -> Path:
    """Expose the active log file path (e.g., for a 'Show Log' menu action)."""
    return LOGS_FOLDER_PATH / "soundboard.log"