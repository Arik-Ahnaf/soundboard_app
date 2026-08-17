"""Centralized logging utility."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_NAME = "Soundboard"
LOG_FILENAME = "soundboard.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 3

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get_log_dir() -> Path:
    """Resolve the logs/ directory in the project root."""
    return PROJECT_ROOT / "logs"


def _build_root_logger() -> logging.Logger:
    log_dir = _get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(APP_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_dir / LOG_FILENAME,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
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
    return _get_log_dir() / LOG_FILENAME