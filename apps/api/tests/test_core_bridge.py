# File: apps/api/tests/test_core_bridge.py
"""``uadas_api.core_bridge``: how the API reaches the framework-free core's sessions.

Why: the core serves many tenants from one process only if (a) the process half is
built exactly once, in *server mode* (plugins hard-off, no YAML, no log files), and
(b) every request gets its own session. The bridge is the one place the API does that,
so these tests pin both -- including a fresh-interpreter probe that the plugin package
is never imported -- with a positive twin beside each "off" assertion.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pandas as pd  # type: ignore[import-untyped]  # no pandas-stubs in the api env
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

import uadas_core.core.logger as core_logger
from uadas_api import core_bridge
from uadas_core.core.process_mode import (
    ProcessMode,
    current_process_mode,
    reset_process_mode_for_tests,
)
from uadas_core.models import Dataset
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService


@pytest.fixture(autouse=True)
def fresh_bridge() -> Iterator[None]:
    """Give each test a never-built bridge and undo the logging it configures.

    ``configure_logging`` is once-per-process by design; the bridge triggers it, so the
    handlers and the guard flag are snapshotted and restored (as the core's own
    ``reset_logging_state`` fixture does) to keep other tests' logging untouched.
    """
    root = logging.getLogger()
    core = logging.getLogger("uadas_core")
    saved_handlers = list(root.handlers)
    saved_core_handlers = list(core.handlers)
    saved_level = root.level
    saved_flag = core_logger._configured
    core_bridge.reset_process_context()
    core_logger._configured = False
    reset_process_mode_for_tests()
    yield
    core_bridge.reset_process_context()
    for logger, saved in ((root, saved_handlers), (core, saved_core_handlers)):
        for handler in list(logger.handlers):
            if handler not in saved:
                logger.removeHandler(handler)
                handler.close()
    root.setLevel(saved_level)
    core.propagate = True
    core.setLevel(logging.NOTSET)
    core_logger._configured = saved_flag
    reset_process_mode_for_tests()


def _dataset(name: str = "d") -> Dataset:
    return Dataset(
        name=name, dataframe=pd.DataFrame({"a": [1, 2]}), source_format="csv"
    )


def test_process_context_is_built_in_server_mode_and_cached() -> None:
    first = core_bridge.get_process_context()

    assert first.server_mode is True
    assert first.config_path is None  # no YAML, in-memory settings
    assert first.config.plugins_enabled is False
    assert core_bridge.get_process_context() is first


def test_process_context_is_built_once_under_concurrent_first_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    real = core_bridge.bootstrap_process

    def counting(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(core_bridge, "bootstrap_process", counting)
    workers = 10
    barrier = threading.Barrier(workers)
    results: list[Any] = []

    def work() -> None:
        barrier.wait(timeout=30)
        results.append(core_bridge.get_process_context())

    threads = [threading.Thread(target=work) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(calls) == 1
    assert calls[0]["server_mode"] is True
    assert len(results) == workers
    assert all(result is results[0] for result in results)


def test_core_config_is_built_from_django_settings() -> None:
    assert core_bridge.build_core_config().log_level == "INFO"  # the default

    with override_settings(UADAS_CORE_LOG_LEVEL="WARNING"):
        assert core_bridge.build_core_config().log_level == "WARNING"


def test_core_debug_logging_is_refused_unless_django_debug_is_on() -> None:
    """DEBUG is where tenant-adjacent detail is logged; it needs Django's DEBUG too."""
    with override_settings(DEBUG=False, UADAS_CORE_LOG_LEVEL="DEBUG"):
        with pytest.raises(ImproperlyConfigured, match="UADAS_CORE_LOG_LEVEL"):
            core_bridge.build_core_config()
        with pytest.raises(ImproperlyConfigured):
            core_bridge.get_process_context()  # refused before anything is built
        assert core_bridge._process is None

    with override_settings(DEBUG=True, UADAS_CORE_LOG_LEVEL="DEBUG"):  # positive twin
        assert core_bridge.build_core_config().log_level == "DEBUG"


def test_two_new_sessions_are_independent_children_of_one_process() -> None:
    process = core_bridge.get_process_context()
    first, second = core_bridge.new_session(), core_bridge.new_session()

    assert first is not second
    assert first.parent is second.parent is process.container

    first.resolve(WorkspaceService).add_dataset(_dataset())
    first.resolve(SettingsService).set("theme", value="light")

    assert len(first.resolve(WorkspaceService).list_datasets()) == 1  # positive twin
    assert second.resolve(WorkspaceService).list_datasets() == []
    assert first.resolve(SettingsService).get("theme") == "light"
    assert second.resolve(SettingsService).get("theme") == "dark"


def test_building_the_bridge_claims_server_mode_and_spares_the_host_logger() -> None:
    root = logging.getLogger()
    root.setLevel(logging.WARNING)  # the host application's (Django's) choice
    handlers_before = list(root.handlers)

    core_bridge.get_process_context()

    assert current_process_mode() is ProcessMode.SERVER
    assert root.level == logging.WARNING
    assert root.handlers == handlers_before
    assert logging.getLogger("uadas_core").propagate is False


def test_new_session_lazily_builds_the_process_context() -> None:
    assert core_bridge._process is None

    core_bridge.new_session()

    assert core_bridge._process is not None


def test_reset_closes_and_forgets_the_process_context() -> None:
    first = core_bridge.get_process_context()

    core_bridge.reset_process_context()

    assert core_bridge._process is None
    assert core_bridge.get_process_context() is not first


_PROBE = """
import os, sys
os.environ["DJANGO_SETTINGS_MODULE"] = "uadas_api.settings.test"
import django
django.setup()
path_before = list(sys.path)
from uadas_api.core_bridge import get_process_context, new_session
process = get_process_context()
new_session()
loaded = sorted(m for m in sys.modules if m.startswith("uadas_core.plugins"))
assert sys.path == path_before, "sys.path changed"
assert process.server_mode and process.config.plugins_enabled is False
print("PLUGIN_MODULES=" + ",".join(loaded))
"""


def test_server_mode_really_is_on_plugins_never_imported(
    subprocess_env: Callable[..., dict[str, str]],
) -> None:
    """A fresh interpreter: bridge + session built, and the plugin package never loaded."""
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=180,
        env=subprocess_env(),
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "PLUGIN_MODULES="


def test_the_probe_would_notice_a_loaded_plugin_package_twin(
    subprocess_env: Callable[..., dict[str, str]],
) -> None:
    """Positive twin: the same probe reports ``uadas_core.plugins`` when it *is* imported."""
    script = _PROBE.replace(
        "loaded = sorted",
        "import uadas_core.plugins.plugin_manager\nloaded = sorted",
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        env=subprocess_env(),
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "uadas_core.plugins.plugin_manager" in result.stdout
