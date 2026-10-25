# File: tests/core/test_logger_stream_only.py
"""``configure_logging(server_mode=True)``: stderr-only logging that never touches the host.

A server process (the Django API) already owns the root logger: its level, its handlers.
The core must therefore log through a handler attached to the ``uadas_core`` logger alone
(``propagate=False``, so nothing is duplicated into the host's handler either) and must
never write a rotating file. Desktop mode keeps configuring the root logger exactly as it
always did -- the positive twin of every assertion here. Switching mode in one process is
refused, in both orders.
"""

from __future__ import annotations

import io
import logging
import logging.handlers
import sys
from pathlib import Path

import pytest

import uadas_core.core.logger as logger_module
from uadas_core.core.exceptions import BootstrapError
from uadas_core.core.logger import configure_logging


def _core_logger() -> logging.Logger:
    return logging.getLogger("uadas_core")


def _exact_stream_handlers(logger: logging.Logger) -> list[logging.StreamHandler]:
    """Handlers that are exactly ``StreamHandler`` -- not pytest's capture subclasses."""
    return [h for h in logger.handlers if type(h) is logging.StreamHandler]


def test_server_mode_leaves_the_host_root_logger_completely_alone(
    reset_logging_state,
) -> None:
    root = logging.getLogger()
    root.setLevel(logging.WARNING)  # the host's choice
    handlers_before = list(root.handlers)

    configure_logging(level="DEBUG", server_mode=True)

    assert root.level == logging.WARNING
    assert root.handlers == handlers_before


def test_desktop_mode_still_configures_the_root_logger_twin(
    log_dir: Path, reset_logging_state
) -> None:
    root = logging.getLogger()
    root.setLevel(logging.WARNING)

    configure_logging(level="DEBUG", log_dir=log_dir, max_bytes=1024, backup_count=1)

    assert root.level == logging.DEBUG
    assert any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
    )
    assert _exact_stream_handlers(root)  # the console handler
    core = _core_logger()
    assert core.propagate is True and core.handlers == []  # untouched in desktop mode


def test_server_mode_attaches_one_stderr_handler_to_the_core_logger_only(
    reset_logging_state,
) -> None:
    configure_logging(level="INFO", server_mode=True)

    core = _core_logger()
    assert core.propagate is False  # nothing is duplicated into the host's handlers
    assert core.level == logging.INFO
    (handler,) = _exact_stream_handlers(core)
    assert handler.stream is sys.stderr
    assert not any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in core.handlers
    )


def test_server_mode_routes_core_records_to_the_stream_and_host_records_elsewhere(
    reset_logging_state,
) -> None:
    sink = io.StringIO()

    configure_logging(level="INFO", server_mode=True, stream=sink)

    logging.getLogger("uadas_core.some.module").info("core says hello")
    logging.getLogger("uadas_api.host").warning("host says hello")
    assert "core says hello" in sink.getvalue()  # positive twin
    assert "host says hello" not in sink.getvalue()


def test_server_mode_creates_no_directory_and_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    monkeypatch.chdir(tmp_path)

    configure_logging(level="INFO", server_mode=True)

    assert list(tmp_path.iterdir()) == []
    assert logger_module._configured is True


def test_file_logging_is_still_the_default_twin(
    log_dir: Path, reset_logging_state
) -> None:
    configure_logging(level="INFO", log_dir=log_dir, max_bytes=1024, backup_count=1)

    assert (log_dir / "application.log").exists()


def test_desktop_console_stream_is_unchanged_stdout(
    log_dir: Path, reset_logging_state
) -> None:
    configure_logging(level="INFO", log_dir=log_dir, max_bytes=1024, backup_count=1)

    (handler,) = _exact_stream_handlers(logging.getLogger())
    assert handler.stream is sys.stdout


def test_server_after_desktop_raises_and_attaches_nothing(
    log_dir: Path, reset_logging_state
) -> None:
    configure_logging(level="INFO", log_dir=log_dir, max_bytes=1024, backup_count=1)

    with pytest.raises(BootstrapError, match="desktop"):
        configure_logging(level="INFO", server_mode=True)

    assert _core_logger().handlers == []
    assert _core_logger().propagate is True


def test_desktop_after_server_raises_and_creates_no_log_dir(
    log_dir: Path, reset_logging_state
) -> None:
    configure_logging(level="INFO", server_mode=True)
    root_handlers = list(logging.getLogger().handlers)

    with pytest.raises(BootstrapError, match="server"):
        configure_logging(level="INFO", log_dir=log_dir)

    assert not log_dir.exists()
    assert logging.getLogger().handlers == root_handlers


def test_repeating_the_same_mode_stays_a_noop(reset_logging_state) -> None:
    configure_logging(level="INFO", server_mode=True)
    handlers_after_first = list(_core_logger().handlers)

    configure_logging(level="DEBUG", server_mode=True)

    assert _core_logger().handlers == handlers_after_first
    assert _core_logger().level == logging.INFO  # first configuration wins, as before
