# File: uadas_core/core/logger.py
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
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from uadas_core.core.constants import (
    DEFAULT_LOG_FILE_BACKUP_COUNT,
    DEFAULT_LOG_FILE_MAX_BYTES,
    DEFAULT_LOG_FILENAME,
    DEFAULT_LOG_LEVEL,
    LOG_DIR,
)
from uadas_core.core.exceptions import BootstrapError

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Tracks whether configure_logging has already run, so that calling it
# more than once (which bootstrap.py should not do, but a test harness
# or a future re-init path might) does not attach duplicate handlers to
# the root logger.
_configured: bool = False
# Which mode that one configuration was made in. Logging is mode-aware because the two
# modes attach handlers to different loggers: switching mode in one process would
# silently keep the first mode's handlers (a desktop RotatingFileHandler under "server
# mode"), so a mismatching second call raises instead (see configure_logging).
_configured_server_mode: bool = False
_configure_lock = threading.Lock()

# The logger the core's own modules hang under (``uadas_core.*``). Server mode attaches
# its handler here, never to the root logger, which belongs to the host application.
_CORE_LOGGER_NAME = "uadas_core"


def configure_logging(
    *,
    level: str = DEFAULT_LOG_LEVEL,
    log_dir: Path = LOG_DIR,
    max_bytes: int = DEFAULT_LOG_FILE_MAX_BYTES,
    backup_count: int = DEFAULT_LOG_FILE_BACKUP_COUNT,
    stream: TextIO | None = None,
    server_mode: bool = False,
) -> None:
    """Configure logging: rotating file + console on the root logger, or (server) stderr only.

    **Desktop mode** (the default) is byte-for-byte what it always was: the root logger
    gets the level, a rotating file handler and a console handler.

    **Server mode** (``server_mode=True``) is for a process that is *hosted* -- Django owns
    the root logger, so rewriting its level or adding a root handler would change the
    host's logging (and duplicate every line through the host's own handler). Instead a
    single console handler (``sys.stderr`` unless ``stream`` is given) and the level are
    attached to the ``uadas_core`` logger only, with ``propagate=False``; the root
    logger is never touched, and no log file or directory is ever created
    (``log_dir``, ``max_bytes`` and ``backup_count`` are ignored).

    This should be called exactly once, early in application startup
    (see :mod:`uadas_core.bootstrap`), before any other module calls
    :func:`get_logger` and emits its first message. Calling it again
    in the *same* mode after the first call is a no-op — it will not attach
    duplicate handlers — but it also will not apply new settings; restart the
    process to pick up a changed log level or rotation size.

    Args:
        level: Minimum severity to log, e.g. ``"DEBUG"``, ``"INFO"``,
            ``"WARNING"``. Applies to both handlers equally in this
            milestone; per-handler levels can be split later if a
            concrete need arises (for example, verbose file logging
            with a quieter console).
        log_dir: Directory the rotating log file is written into.
            Created automatically if it does not exist. Ignored in server mode.
        max_bytes: Maximum size in bytes of a single log file before
            it is rotated. Ignored in server mode.
        backup_count: Number of rotated backup files to retain. Ignored in
            server mode.
        stream: Stream the console handler writes to. ``None`` (the default)
            means ``sys.stdout`` in desktop mode (the original behaviour) and
            ``sys.stderr`` in server mode; resolved at call time so a test that
            swaps the stream is honoured.
        server_mode: Select the hosted, root-logger-preserving configuration above.

    Raises:
        BootstrapError: If logging was already configured in the *other* mode. A
            process is desktop or server, never both; the first configuration is kept
            and nothing is attached or created by the refused call.
    """
    global _configured, _configured_server_mode
    # The check-then-configure below is a race if two threads start a process at
    # once (a server's first two requests); the lock makes "exactly once" true.
    with _configure_lock:
        if _configured:
            if _configured_server_mode != server_mode:
                first, second = (
                    ("server", "desktop")
                    if _configured_server_mode
                    else ("desktop", "server")
                )
                raise BootstrapError(
                    f"Logging is already configured in {first} mode; it cannot be "
                    f"reconfigured in {second} mode in the same process."
                )
            return

        numeric_level = getattr(logging, level.upper(), logging.INFO)
        formatter = logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT)
        log_file_path: Path | None = None

        if server_mode:
            core_logger = logging.getLogger(_CORE_LOGGER_NAME)
            core_logger.setLevel(numeric_level)
            core_logger.propagate = False
            console_handler = logging.StreamHandler(
                stream=sys.stderr if stream is None else stream
            )
            console_handler.setLevel(numeric_level)
            console_handler.setFormatter(formatter)
            core_logger.addHandler(console_handler)
        else:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / DEFAULT_LOG_FILENAME

            root_logger = logging.getLogger()
            root_logger.setLevel(numeric_level)

            file_handler = RotatingFileHandler(
                filename=str(log_file_path),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)

            console_handler = logging.StreamHandler(
                stream=sys.stdout if stream is None else stream
            )
            console_handler.setLevel(numeric_level)
            console_handler.setFormatter(formatter)

            root_logger.addHandler(file_handler)
            root_logger.addHandler(console_handler)

        _configured = True
        _configured_server_mode = server_mode

    bootstrap_logger = get_logger(__name__)
    bootstrap_logger.info(
        "Logging configured: level=%s, file=%s, max_bytes=%d, backup_count=%d",
        level.upper(),
        log_file_path if log_file_path is not None else "(console only)",
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
