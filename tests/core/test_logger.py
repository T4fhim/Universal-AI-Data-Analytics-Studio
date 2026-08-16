# File: tests/core/test_logger.py
"""Tests for src.core.logger: configure_logging, get_logger.

configure_logging() is guarded by a module-level "configure once per
process" flag (see logger.py's own docstring), so every test that
needs it to actually run against its own isolated log_dir uses the
reset_logging_state fixture (tests/conftest.py) to reset that guard
before and after, rather than relying on handler-removal alone.
"""

from __future__ import annotations

import logging
from pathlib import Path

import src.core.logger as logger_module
from src.core.logger import configure_logging, get_logger


def test_configure_logging_creates_log_dir_and_file(
    log_dir: Path, reset_logging_state
) -> None:
    assert not log_dir.exists()

    configure_logging(level="INFO", log_dir=log_dir, max_bytes=1024, backup_count=1)

    assert log_dir.exists()
    assert (log_dir / "application.log").exists()


def test_configure_logging_sets_root_logger_level(
    log_dir: Path, reset_logging_state
) -> None:
    configure_logging(level="DEBUG", log_dir=log_dir, max_bytes=1024, backup_count=1)

    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_is_a_noop_on_second_call(
    log_dir: Path, reset_logging_state
) -> None:
    configure_logging(level="INFO", log_dir=log_dir, max_bytes=1024, backup_count=1)
    handler_count_after_first = len(logging.getLogger().handlers)

    other_log_dir = log_dir.parent / "other-logs"
    configure_logging(
        level="DEBUG", log_dir=other_log_dir, max_bytes=1024, backup_count=1
    )

    # Documented behavior: a second call attaches no additional
    # handlers and does not apply the new settings (level stays INFO,
    # the second log_dir is never created).
    assert len(logging.getLogger().handlers) == handler_count_after_first
    assert logging.getLogger().level == logging.INFO
    assert not other_log_dir.exists()


def test_get_logger_returns_named_child_of_root(
    log_dir: Path, reset_logging_state
) -> None:
    configure_logging(level="INFO", log_dir=log_dir, max_bytes=1024, backup_count=1)

    logger = get_logger("tests.core.test_logger.example")

    assert logger.name == "tests.core.test_logger.example"
    assert logger_module._configured is True
