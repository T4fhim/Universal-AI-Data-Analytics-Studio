# File: src/core/logger.py
"""Application-wide logging setup.

Provides a single :func:`configure_logging` call that sets up both a
rotating file handler and a console handler, and a single
:func:`get_logger` entry point that every other module should use to
obtain a logger — rather than each module calling
``logging.getLogger`` and configuring handlers independently, which
would produce duplicate log lines and inconsistent formatting as the
codebase grows.

Rotation strategy: size-based rather than time-based
(``RotatingFileHandler`` rather than ``TimedRotatingFileHandler``).
This application is a desktop tool that may run for a few minutes or
be left open for days; a size-based rotation gives a predictable disk
footprint (``max_bytes * (backup_count + 1)`` at most) regardless of
how long a session runs, whereas a time-based policy would let a
single long session's log file grow without bound between rotation
boundaries. The size and backup count are both configurable via
config.yaml's ``logging`` section.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.core.constants import (
    DEFAULT_LOG_FILE_BACKUP_COUNT,
    DEFAULT_LOG_FILE_MAX_BYTES,
    DEFAULT_LOG_FILENAME,
    DEFAULT_LOG_LEVEL,
    LOG_DIR,
)

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Tracks whether configure_logging has already run, so that calling it
# more than once (which bootstrap.py should not do, but a test harness
# or a future re-init path might) does not attach duplicate handlers to
# the root logger.
_configured: bool = False


def configure_logging(
    *,
    level: str = DEFAULT_LOG_LEVEL,
    log_dir: Path = LOG_DIR,
    max_bytes: int = DEFAULT_LOG_FILE_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_FILE_BACKUP_COUNT,
) -> None:
    """Configure the root logger with a rotating file handler and console handler.

    This should be called exactly once, early in application startup
    (see :mod:`src.core.bootstrap`), before any other module calls
    :func:`get_logger` and emits its first message. Calling it again
    after the first call is a no-op — it will not attach duplicate
    handlers — but it also will not apply new settings; restart the
    process to pick up a changed log level or rotation size.

    Args:
        level: Minimum severity to log, e.g. ``"DEBUG"``, ``"INFO"``,
            ``"WARNING"``. Applies to both handlers equally in this
            milestone; per-handler levels can be split later if a
            concrete need arises (for example, verbose file logging
            with a quieter console).
        log_dir: Directory the rotating log file is written into.
            Created automatically if it does not exist.
        max_bytes: Maximum size in bytes of a single log file before
            it is rotated.
        backup_count: Number of rotated backup files to retain.
    """
    global _configured
    if _configured:
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file_path = log_dir / DEFAULT_LOG_FILENAME

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        filename=str(log_file_path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    _configured = True

    bootstrap_logger = get_logger(__name__)
    bootstrap_logger.info(
        "Logging configured: level=%s, file=%s, max_bytes=%d, backup_count=%d",
        level.upper(),
        log_file_path,
        max_bytes,
        backup_count,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for ``name``, typically ``__name__`` of the caller.

    This is the single entry point every module in the application
    should use to obtain a logger. It does not itself configure
    handlers — that is :func:`configure_logging`'s job, called once
    during bootstrap — it simply returns a named child of the root
    logger, which will inherit whatever handlers and level
    :func:`configure_logging` has already attached.

    If called before :func:`configure_logging`, the returned logger
    will still work (Python's logging module defaults to a
    last-resort handler that writes WARNING and above to stderr), but
    will not benefit from file rotation or the application's log
    format until configuration runs.

    Args:
        name: Logger name, conventionally the calling module's
            ``__name__``.
    """
    return logging.getLogger(name)
