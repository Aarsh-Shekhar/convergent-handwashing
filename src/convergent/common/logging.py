"""Logging configuration with rotation. Call ``configure_logging()`` once per process."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONFIGURED = False


def configure_logging(
    level: str = "INFO",
    log_dir: str | Path | None = None,
    name: str = "convergent",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    global _CONFIGURED
    root = logging.getLogger()
    if not _CONFIGURED:
        root.setLevel(level.upper())
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
        if log_dir is not None:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                Path(log_dir) / f"{name}.log", maxBytes=max_bytes, backupCount=backup_count
            )
            fh.setFormatter(fmt)
            root.addHandler(fh)
        # third-party noise
        for noisy in ("httpx", "httpcore", "websockets", "urllib3", "matplotlib", "alembic", "alembic.runtime.migration"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _CONFIGURED = True
    else:
        root.setLevel(level.upper())
    return logging.getLogger(name)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
