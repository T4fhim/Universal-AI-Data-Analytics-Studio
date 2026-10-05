# File: tests/core/test_bootstrap_characterization.py
"""Characterization of the legacy :func:`uadas_core.bootstrap.bootstrap` result.

The core session seam (Phase 3, between 3.3 and 3.4) splits ``bootstrap()`` into a
process half and a session half. The desktop-shaped entry point must keep returning
exactly what it returns today -- same :class:`BootstrapContext` shape, same
registrations, same side effects -- so this module pins that observable result
*before* the refactor (it was written and run green against the unsplit function)
and stays as the regression guard afterwards.

Only public container API is used (``is_registered`` / ``resolve``): a child
container resolves its parent's registrations, so the *set of resolvable keys* is the
contract, not which dictionary happens to hold them.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest
import yaml

from uadas_core.bootstrap import BootstrapContext, bootstrap
from uadas_core.core.application_state import ApplicationState
from uadas_core.core.config import AppConfig, load_config
from uadas_core.core.dependency_container import DependencyContainer
from uadas_core.jobs import get_default_job_runner
from uadas_core.jobs.job_runner import JobRunner
from uadas_core.persistence.persistence_service import PersistenceService
from uadas_core.plugins.plugin_manager import PluginManager
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
)
from uadas_core.services.database_connection_service import DatabaseConnectionService
from uadas_core.services.guidance_service import GuidanceService
from uadas_core.services.project_service import ProjectService
from uadas_core.services.report_service import ReportService
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService

# Every key the legacy bootstrap() makes resolvable. JobRunner is a Protocol, so it
# is typed ``object`` here (see DependencyContainer's "honesty caveats").
_LEGACY_KEYS: tuple[object, ...] = (
    AppConfig,
    ApplicationState,
    SettingsService,
    ProjectService,
    WorkspaceService,
    AnalysisOrchestratorService,
    GuidanceService,
    ReportService,
    DatabaseConnectionService,
    PluginManager,
    JobRunner,
    PersistenceService,
)


def test_context_shape_is_config_container_state_and_immutable(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)

    assert [f.name for f in dataclasses.fields(BootstrapContext)] == [
        "config",
        "container",
        "state",
    ]
    assert isinstance(context.container, DependencyContainer)
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.state = ApplicationState()  # type: ignore[misc]


def test_every_legacy_key_is_registered_and_resolves_to_a_singleton(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    container = bootstrap(config_path=config_path, log_dir=log_dir).container

    for key in _LEGACY_KEYS:
        assert container.is_registered(key), key
        first = container.resolve(key)
        assert first is not None, key
        assert container.resolve(key) is first, key


_PROCESS_KEYS: tuple[object, ...] = (
    AppConfig,
    PluginManager,
    JobRunner,
    PersistenceService,
)
_SESSION_KEYS: tuple[object, ...] = (
    ApplicationState,
    SettingsService,
    ProjectService,
    WorkspaceService,
    AnalysisOrchestratorService,
    GuidanceService,
    ReportService,
    DatabaseConnectionService,
)


def test_which_container_holds_what_process_versus_session(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    """Pins the ownership split: the returned container is the *session*, its parent the process."""
    context = bootstrap(config_path=config_path, log_dir=log_dir)
    session = context.container
    process = session.parent

    assert process is not None and process.parent is None
    for key in _PROCESS_KEYS:  # tenant-free: registered on the process container
        assert process.is_registered(key), key
        assert session.resolve(key) is process.resolve(key), key
    for key in _SESSION_KEYS:  # stateful per user: registered on the session only
        assert session.is_registered(key), key
        assert not process.is_registered(key), key


def test_plugins_are_loaded_before_the_session_services_are_built(
    config_path: Path,
    log_dir: Path,
    reset_logging_state,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the one deliberate ordering change of the process/session split.

    HEAD built the session services and *then* loaded plugins; the split necessarily
    builds the process half (plugins included) first. It is safe because no session
    service's constructor reads the plugin-fed registries (readers / operations /
    charts): each ``__init__`` only stores its collaborators or initialises empty
    dicts (verified by reading all eight), and registries are consulted at call time.
    If a service ever starts reading a registry in its constructor, this test is the
    reminder that the order matters.
    """
    order: list[str] = []
    real_load = PluginManager.load_plugins
    real_init = WorkspaceService.__init__

    def load_spy(self: PluginManager) -> list:
        order.append("plugins")
        return real_load(self)

    def init_spy(self: WorkspaceService) -> None:
        order.append("workspace")
        real_init(self)

    monkeypatch.setattr(PluginManager, "load_plugins", load_spy)
    monkeypatch.setattr(WorkspaceService, "__init__", init_spy)

    bootstrap(config_path=config_path, log_dir=log_dir)

    assert order == ["plugins", "workspace"]


def test_unrelated_keys_stay_unregistered(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    """Positive twin of the test above: the legacy key set is exact, not "anything"."""
    container = bootstrap(config_path=config_path, log_dir=log_dir).container

    assert not container.is_registered(DependencyContainer)
    assert not container.is_registered("nonsense-key")


def test_context_fields_resolve_to_the_container_registrations(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)

    assert context.container.resolve(AppConfig) is context.config
    assert context.container.resolve(ApplicationState) is context.state


def test_plugin_loading_runs_exactly_once_and_path_is_untouched_without_plugins(
    config_path: Path,
    log_dir: Path,
    reset_logging_state,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[PluginManager] = []
    real = PluginManager.load_plugins

    def spy(self: PluginManager) -> list:
        calls.append(self)
        return real(self)

    monkeypatch.setattr(PluginManager, "load_plugins", spy)
    path_before = list(sys.path)

    context = bootstrap(config_path=config_path, log_dir=log_dir)

    assert calls == [context.container.resolve(PluginManager)]
    assert sys.path == path_before


def test_services_are_distinct_objects_built_fresh_per_call(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    first = bootstrap(config_path=config_path, log_dir=log_dir)
    second = bootstrap(config_path=config_path, log_dir=log_dir)

    assert first.state is not second.state
    assert first.container is not second.container
    assert first.container.resolve(WorkspaceService) is not second.container.resolve(
        WorkspaceService
    )
    # ...and each service is wired to the *same context's* collaborators.
    orchestrator = first.container.resolve(AnalysisOrchestratorService)
    assert orchestrator is first.container.resolve(AnalysisOrchestratorService)
    assert orchestrator is not second.container.resolve(AnalysisOrchestratorService)


def test_side_effects_config_file_log_dir_and_default_runner_bridge(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    assert not config_path.exists()
    assert not log_dir.exists()

    context = bootstrap(config_path=config_path, log_dir=log_dir)

    assert config_path.exists()  # default config written on first run
    assert (log_dir / "application.log").exists()  # rotating file logging configured
    # The Phase-1.2 bridge hands out the identical object the container does.
    assert get_default_job_runner() is context.container.resolve(JobRunner)


def test_settings_service_still_persists_to_the_yaml_it_was_booted_from(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    settings = bootstrap(config_path=config_path, log_dir=log_dir).container.resolve(
        SettingsService
    )

    settings.set("autosave", "interval_minutes", value=17)
    settings.save()

    on_disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert on_disk["autosave"]["interval_minutes"] == 17


def test_project_service_is_seeded_from_config_recent_projects(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    data = load_config(config_path)  # writes the default file first
    data["recent_projects"] = ["C:/fake/one.json"]
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    context = bootstrap(config_path=config_path, log_dir=log_dir)

    assert context.container.resolve(ProjectService).get_recent_projects() == [
        "C:/fake/one.json"
    ]
