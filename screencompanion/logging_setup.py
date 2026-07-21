"""File-based logging so problems are diagnosable in the packaged (windowed) app.

The bundled build runs with no console (console=False), so stray prints go
nowhere. Everything is written to a rotating log file under
%LOCALAPPDATA%\\ScreenCompanion\\logs (or ~/ScreenCompanion/logs as a
fallback), which the user can open and share when something misbehaves.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False
_ROOT = "screencompanion"


def log_dir() -> Path:
    """Directory where log files live. Created on demand."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "ScreenCompanion" / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path.home()
    return d


def setup_logging() -> Path:
    """Attach a rotating file handler to the app's logger. Idempotent."""
    global _CONFIGURED
    logger = logging.getLogger(_ROOT)
    if _CONFIGURED:
        return log_dir()

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    path = log_dir() / "screencompanion.log"
    try:
        handler = RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
            )
        )
        logger.addHandler(handler)
    except OSError:
        pass  # Never let logging setup crash the app.

    _CONFIGURED = True
    logger.info("── logging started → %s ──", path)
    return log_dir()


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the app's namespace."""
    return logging.getLogger(f"{_ROOT}.{name}")
