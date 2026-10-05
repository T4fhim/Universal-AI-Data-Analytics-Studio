# File: tests/core/test_server_mode.py
"""Server-mode guarantees of ``bootstrap_process(server_mode=True)``.

The server half of plan 3.8: one process serves many tenants, so the desktop-shaped
startup (YAML config, rotating log files, plugin loading that mutates ``sys.path``,
a process-global job-runner bridge) must be impossible, not merely unused. Every
"never" below is paired with a positive twin that shows the same input *does* take
effect in desktop mode -- otherwise a bootstrap that ignored its inputs entirely
would satisfy the "never" for the wrong reason.
"""

from __future__ import annotations

import io
import json
import logging
import logging.handlers
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

import uadas_core.jobs as jobs_module
from uadas_core.bootstrap import ProcessContext, bootstrap_process, build_session
from uadas_core.core import constants
from uadas_core.core.application_state import ApplicationState
from uadas_core.core.config import AppConfig
from uadas_core.core.exceptions import BootstrapError, DependencyResolutionError
from uadas_core.jobs.job_runner import JobRunner
from uadas_core.plugins import plugin_loader
from uadas_core.plugins.plugin_manager import PluginManager
from uadas_core.readers import reader_registry
from uadas_core.services.project_service import ProjectService
from uadas_core.services.settings_service import SettingsService


def _config_with_plugin_dir(plugin_root: Path) -> AppConfig:
    data = AppConfig.defaults().to_dict()
    data["plugins"]["enabled"] = True
    data["plugins"]["search_paths"] = [str(plugin_root)]
    return AppConfig.from_dict(data)


@pytest.fixture()
def plugin_root(tmp_path: Path) -> Path:
    """A search path holding one valid (empty-``provides``) plugin."""
    root = tmp_path / "plugins"
    plugin_dir = root / "plugin_probe"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "plugin_probe",
                "version": "1.0.0",
                "description": "probe",
                "provides": {},
            }
        ),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    return root


@pytest.fixture()
def server_process(reset_logging_state) -> Iterator[ProcessContext]:
    process = bootstrap_process(server_mode=True)
    yield process
    process.close()


# --- (a) plugins are never loaded -------------------------------------------------


def test_server_mode_never_loads_plugins_and_leaves_sys_path_alone(
    plugin_root: Path, monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("plugin loading was attempted in server mode")

    monkeypatch.setattr(plugin_loader, "discover_plugins", forbidden)
    monkeypatch.setattr(PluginManager, "load_plugins", forbidden)
    path_before = list(sys.path)
    plugin_readers_before = list(reader_registry._PLUGIN_READERS)

    # The *caller* asks for plugins (enabled + a real search path); server mode
    # must refuse regardless of what the config says.
    process = bootstrap_process(
        server_mode=True, config=_config_with_plugin_dir(plugin_root)
    )
    try:
        session = build_session(process)

        assert sys.path == path_before
        assert str(plugin_root.resolve()) not in sys.path
        assert plugin_readers_before == reader_registry._PLUGIN_READERS
        assert not process.container.is_registered(PluginManager)
        with pytest.raises(DependencyResolutionError):
            session.resolve(PluginManager)
        assert process.config.plugins_enabled is False
        assert process.config.plugin_search_paths == []
    finally:
        process.close()


def test_desktop_mode_loads_the_same_plugin_twin(
    plugin_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_logging_state,
) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))  # restore after the test
    process = bootstrap_process(
        server_mode=False,
        config=_config_with_plugin_dir(plugin_root),
        config_path=tmp_path / "config.yaml",
        log_dir=tmp_path / "logs",
    )
    try:
        manager = process.container.resolve(PluginManager)

        assert [p.manifest.name for p in manager.list_plugins()] == ["plugin_probe"]
        assert str(plugin_root.resolve()) in sys.path
    finally:
        process.close()


_IMPORT_PROBE = """
import sys
from uadas_core.bootstrap import bootstrap_process, build_session
process = bootstrap_process(server_mode=True)
build_session(process)
loaded = sorted(m for m in sys.modules if m.startswith("uadas_core.plugins"))
print("PLUGIN_MODULES=" + ",".join(loaded))
"""


def _run_probe(
    script: str, tmp_path: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=tmp_path,
        env={
            **os.environ,
            constants.DATA_ROOT_ENV_VAR: str(tmp_path),
            # cwd is the tmp dir (so a stray write would be visible there), which
            # means the source checkout must come from PYTHONPATH instead.
            "PYTHONPATH": str(constants.PROJECT_ROOT),
        },
        check=False,
    )


def test_server_mode_never_even_imports_the_plugin_package(tmp_path: Path) -> None:
    result = _run_probe(_IMPORT_PROBE, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PLUGIN_MODULES="  # probe ran, loaded nothing


_DESKTOP_IMPORT_PROBE = """
import sys
from pathlib import Path
from uadas_core.bootstrap import bootstrap_process
root = Path(sys.argv[1])
bootstrap_process(config_path=root / "c.yaml", log_dir=root / "logs")
loaded = sorted(m for m in sys.modules if m.startswith("uadas_core.plugins"))
print("PLUGIN_MODULES=" + ",".join(loaded))
"""


def test_desktop_mode_imports_the_plugin_package_twin(tmp_path: Path) -> None:
    result = _run_probe(_DESKTOP_IMPORT_PROBE, tmp_path, str(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "uadas_core.plugins.plugin_loader" in result.stdout


# --- (b) no YAML read or write ----------------------------------------------------


def test_server_mode_reads_and_writes_no_yaml_and_opens_no_file_for_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, str(tmp_path))
    yaml_calls: list[str] = []
    write_opens: list[str] = []

    def spy_yaml(name: str, real: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            yaml_calls.append(name)
            return real(*args, **kwargs)

        return wrapper

    for name in ("safe_load", "safe_dump", "load", "dump"):
        monkeypatch.setattr(yaml, name, spy_yaml(name, getattr(yaml, name)))

    import io as io_module

    real_open = io_module.open

    def spy_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wax+"):
            write_opens.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(io_module, "open", spy_open)

    process = bootstrap_process(server_mode=True)
    try:
        session = build_session(process)
        settings = session.resolve(SettingsService)
        settings.set("autosave", "interval_minutes", value=11)
        settings.save()
        settings.reload()
    finally:
        process.close()

    assert yaml_calls == []
    assert write_opens == []
    assert list(tmp_path.iterdir()) == []  # no config/, logs/, projects/ appeared


def test_desktop_mode_does_read_and_write_yaml_twin(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    process = bootstrap_process(config_path=config_path, log_dir=log_dir)
    try:
        settings = build_session(process).resolve(SettingsService)
        settings.set("autosave", "interval_minutes", value=11)
        settings.save()

        assert (
            yaml.safe_load(config_path.read_text(encoding="utf-8"))["autosave"][
                "interval_minutes"
            ]
            == 11
        )
    finally:
        process.close()


def test_server_session_settings_are_in_memory_only(
    server_process: ProcessContext,
) -> None:
    assert server_process.config_path is None
    settings = build_session(server_process).resolve(SettingsService)

    settings.set("theme", value="light")

    assert settings.get("theme") == "light"
    assert server_process.config.theme == "dark"


def test_server_config_is_sanitized_of_cross_tenant_desktop_state(
    reset_logging_state,
) -> None:
    data = AppConfig.defaults().to_dict()
    data["recent_projects"] = ["C:/someone/elses/project.json"]
    data["database"]["profiles"] = [{"name": "prod-db", "db_type": "postgres"}]
    process = bootstrap_process(server_mode=True, config=AppConfig.from_dict(data))
    try:
        session = build_session(process)

        assert process.config.recent_projects == []
        assert process.config.database_profiles == []
        assert session.resolve(ProjectService).get_recent_projects() == []
    finally:
        process.close()


def test_a_caller_supplied_config_is_not_mutated_by_server_sanitizing(
    reset_logging_state,
) -> None:
    data = AppConfig.defaults().to_dict()
    data["recent_projects"] = ["keep-me"]
    supplied = AppConfig.from_dict(data)

    process = bootstrap_process(server_mode=True, config=supplied)
    process.close()

    assert supplied.recent_projects == ["keep-me"]
    assert supplied.plugins_enabled is True


def test_server_mode_rejects_desktop_only_paths_but_desktop_accepts_them(
    tmp_path: Path, reset_logging_state
) -> None:
    with pytest.raises(BootstrapError):
        bootstrap_process(server_mode=True, config_path=tmp_path / "c.yaml")
    with pytest.raises(BootstrapError):
        bootstrap_process(server_mode=True, log_dir=tmp_path / "logs")

    process = bootstrap_process(
        config_path=tmp_path / "c.yaml", log_dir=tmp_path / "logs"
    )
    process.close()
    assert (tmp_path / "c.yaml").exists()


# --- (c) no rotating log files ----------------------------------------------------


def test_server_mode_logs_to_stderr_only_and_creates_no_log_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, str(tmp_path))
    sink = io.StringIO()
    monkeypatch.setattr(sys, "stderr", sink)

    root = logging.getLogger()
    root.setLevel(logging.WARNING)  # the host application's choice
    root_handlers_before = list(root.handlers)

    process = bootstrap_process(server_mode=True)
    try:
        core_handlers = logging.getLogger("uadas_core").handlers
        assert not any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in core_handlers
        )
        assert [
            h.stream for h in core_handlers if type(h) is logging.StreamHandler
        ] == [sink]
        assert not (tmp_path / "logs").exists()
        assert "Process bootstrap complete (server_mode=True)" in sink.getvalue()
        # The host's root logger is exactly as the host left it.
        assert root.level == logging.WARNING
        assert root.handlers == root_handlers_before
    finally:
        process.close()


# --- (d) secrets only from env / explicit arguments -------------------------------


def test_server_mode_persists_no_secret_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    """Secrets live in the environment; settings changes touch no disk at all.

    A provider profile stores only the *name* of the env var holding its key; the
    key itself, and a database password, are held in memory by the objects that
    use them. Combined with the no-write assertions above, nothing secret can reach
    a file in server mode.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, str(tmp_path))
    monkeypatch.setenv("UADAS_TEST_API_KEY", "sk-super-secret-value")
    data = AppConfig.defaults().to_dict()
    data["ai"]["providers"] = [
        {
            "name": "p",
            "provider_type": "groq",
            "api_key_env_var": "UADAS_TEST_API_KEY",
            "model": None,
        }
    ]
    process = bootstrap_process(server_mode=True, config=AppConfig.from_dict(data))
    try:
        settings = build_session(process).resolve(SettingsService)
        settings.save()

        assert list(tmp_path.iterdir()) == []
        assert "sk-super-secret-value" not in json.dumps(settings.get("ai"))
    finally:
        process.close()


# --- (e) PROJECT_ROOT is not required ---------------------------------------------


def test_server_mode_works_with_a_bogus_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    bogus = tmp_path / "site-packages" / "nowhere"
    monkeypatch.setattr(constants, "PROJECT_ROOT", bogus)
    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, str(tmp_path / "data"))

    process = bootstrap_process(server_mode=True)
    try:
        session = build_session(process)

        assert isinstance(session.resolve(ApplicationState), ApplicationState)
        assert not bogus.exists()
        assert not (tmp_path / "data").exists()  # server mode creates no data dirs
    finally:
        process.close()


def test_desktop_bootstrap_honours_the_data_root_override_twin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    from uadas_core.bootstrap import bootstrap

    monkeypatch.setenv(constants.DATA_ROOT_ENV_VAR, str(tmp_path))

    bootstrap()

    assert (tmp_path / "config" / "config.yaml").exists()
    assert (tmp_path / "logs" / "application.log").exists()


# --- (f) the job-runner bridge is not how server code gets a runner ---------------


def test_server_mode_does_not_install_the_default_runner_bridge(
    monkeypatch: pytest.MonkeyPatch, reset_logging_state
) -> None:
    monkeypatch.setattr(jobs_module, "_default_job_runner", None)

    process = bootstrap_process(server_mode=True)
    try:
        session = build_session(process)

        with pytest.raises(RuntimeError):
            jobs_module.get_default_job_runner()
        # Sessions get the process's runner through the container instead.
        assert session.resolve(JobRunner) is process.job_runner
    finally:
        process.close()


def test_only_the_legacy_bootstrap_installs_the_bridge_twin(
    config_path: Path,
    log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_logging_state,
) -> None:
    from uadas_core.bootstrap import bootstrap

    monkeypatch.setattr(jobs_module, "_default_job_runner", None)
    process = bootstrap_process(config_path=config_path, log_dir=log_dir)
    try:
        with pytest.raises(RuntimeError):  # bootstrap_process alone never does
            jobs_module.get_default_job_runner()
    finally:
        process.close()

    context = bootstrap(config_path=config_path, log_dir=log_dir)
    assert jobs_module.get_default_job_runner() is context.container.resolve(JobRunner)
