import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from runtime_paths import resolve_runtime_paths


def get_log_file() -> Path:
    return resolve_runtime_paths().logs_dir / "temodar_agent.log"


def build_rotating_file_handler() -> RotatingFileHandler | None:
    log_file = get_log_file()
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    except OSError:
        return None
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    return handler


def _build_console_handler() -> logging.StreamHandler:
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
    )
    return console_handler


def setup_logger(name: str = "temodar_agent") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.INFO)
    logger.addHandler(_build_console_handler())

    file_handler = build_rotating_file_handler()
    if file_handler is not None:
        logger.addHandler(file_handler)
    else:
        logger.warning("File logging disabled because the log directory is not writable.")

    return logger
