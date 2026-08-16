# File: tests/conftest.py
"""Shared pytest fixtures for isolating tests from the real application state.

Every fixture here exists to satisfy one specific rule: tests must never
read or write the project's real ``config/config.yaml`` or ``logs/``
directory. ``Application.create()``'s own docstring (see
:mod:`src.core.app`) states this separation is exactly why
``bootstrap()`` accepts overridable ``config_path``/``log_dir``
arguments — this module is what exercises that path.

``tmp_path``/``tmp_path_factory`` (pytest's built-in fixtures) are used
throughout rather than manual ``tempfile`` handling, per Work Item 1a's
plan: pytest manages their creation and cleanup in a way that avoids
the Windows-specific file-locking failures a hand-rolled temp directory
can hit when a ``RotatingFileHandler`` still holds a log file open at
teardown time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.core.logger as logger_module


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    """A config.yaml path inside an isolated temp directory, not yet created."""
    return tmp_path / "config" / "config.yaml"


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    """A log directory path inside an isolated temp directory, not yet created."""
    return tmp_path / "logs"


@pytest.fixture()
def reset_logging_state():
    """Reset src.core.logger's one-time configuration guard around a test.

    src.core.logger.configure_logging() is deliberately a no-op on any
    call after the first (see that module's docstring: "Calling it
    again after the first call is a no-op — it will not attach
    duplicate handlers — but it also will not apply new settings").
    That guard is correct production behavior (bootstrap() must only
    ever configure logging once per process), but it means tests that
    call bootstrap()/configure_logging() more than once across a
    pytest session would only see the *first* call's log_dir/level
    actually take effect, silently making every later test's
    assertions about its own isolated log_dir meaningless.

    This fixture resets the module-level ``_configured`` flag (and
    detaches any handlers configure_logging attached to the root
    logger) both before and after the test, so each test that needs
    configure_logging to actually run against its own temp log_dir
    gets a clean slate — without weakening the guard in production
    code, which is not touched here.
    """

    def _reset() -> None:
        logger_module._configured = False
        root_logger = logger_module.logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()

    _reset()
    yield
    _reset()
