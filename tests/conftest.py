# File: tests/conftest.py
"""Shared pytest fixtures for isolating tests from the real application state.

Every fixture here exists to satisfy one specific rule: tests must never
read or write the project's real ``config/config.yaml`` or ``logs/``
directory. ``Application.create()``'s own docstring (see
:mod:`src.app`) states this separation is exactly why
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

import uadas_core.core.logger as logger_module
from uadas_core.cleaning import operation_registry
from uadas_core.results import result_renderer_registry
from uadas_core.visualization import chart_registry

# web-transition 1.3: the cleaning-operation, chart, and result-renderer registries
# no longer populate their built-ins as a module-import side effect (see
# plans/phase-1-3-startup-graph.md §9) -- bootstrap() does. The test suite needs
# them seeded independently of bootstrap(): many tests read a registry without
# booting, and tests/ui/help/test_manual_anti_rot.py builds a
# @pytest.mark.parametrize id list from list_renderers() at *collection* time, so
# a fixture (which runs only once collection is done) is too late. Doing it here,
# at root-conftest import, runs before any test module is collected. Each
# _register_builtins() is idempotent, so a test that calls bootstrap() is
# unaffected. This is the test harness explicitly initialising state it needs --
# it replaces the old registry-module import side effect, relocated here.
operation_registry._register_builtins()
chart_registry._register_builtins()
result_renderer_registry._register_builtins()


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
    """Reset uadas_core.core.logger's one-time configuration guard around a test.

    uadas_core.core.logger.configure_logging() is deliberately a no-op on any
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
