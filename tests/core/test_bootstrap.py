# File: tests/core/test_bootstrap.py
"""Tests for src.core.bootstrap.bootstrap().

Verifies the fixed startup sequence documented in bootstrap.py's own
module docstring: config load, logging configuration, and registration
of AppConfig, ApplicationState, SettingsService, ProjectService,
WorkspaceService, and (milestone 9) AnalysisOrchestratorService into
the returned BootstrapContext's container.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.core.application_state import ApplicationState
from src.core.bootstrap import BootstrapContext, bootstrap
from src.core.config import AppConfig, load_config
from src.plugins.plugin_manager import PluginManager
from src.services.analysis_orchestrator_service import AnalysisOrchestratorService
from src.services.project_service import ProjectService
from src.services.report_service import ReportService
from src.services.settings_service import SettingsService
from src.services.workspace_service import WorkspaceService


def test_bootstrap_returns_populated_context(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)

    assert isinstance(context, BootstrapContext)
    assert isinstance(context.config, AppConfig)
    assert isinstance(context.state, ApplicationState)


def test_bootstrap_registers_all_milestone_services(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)

    assert context.container.is_registered(AppConfig)
    assert context.container.is_registered(ApplicationState)
    assert context.container.is_registered(SettingsService)
    assert context.container.is_registered(ProjectService)
    assert context.container.is_registered(WorkspaceService)
    assert context.container.is_registered(AnalysisOrchestratorService)

    # Each resolves to the expected concrete type and is a singleton
    # (same instance on repeated resolution).
    assert context.container.resolve(AppConfig) is context.config
    assert context.container.resolve(ApplicationState) is context.state
    assert isinstance(context.container.resolve(SettingsService), SettingsService)
    assert isinstance(context.container.resolve(ProjectService), ProjectService)
    assert isinstance(context.container.resolve(WorkspaceService), WorkspaceService)
    assert context.container.resolve(WorkspaceService) is context.container.resolve(
        WorkspaceService
    )
    assert isinstance(
        context.container.resolve(AnalysisOrchestratorService),
        AnalysisOrchestratorService,
    )
    assert context.container.resolve(
        AnalysisOrchestratorService
    ) is context.container.resolve(AnalysisOrchestratorService)

    assert context.container.is_registered(PluginManager)
    assert isinstance(context.container.resolve(PluginManager), PluginManager)
    assert context.container.resolve(PluginManager) is context.container.resolve(
        PluginManager
    )

    assert context.container.is_registered(ReportService)
    assert isinstance(context.container.resolve(ReportService), ReportService)
    assert context.container.resolve(ReportService) is context.container.resolve(
        ReportService
    )


def test_bootstrap_seeds_project_service_from_config_recent_projects(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    # Prime a config file with a known recent_projects list before
    # bootstrap ever constructs ProjectService, so the seeding behavior
    # documented in bootstrap.py ("a freshly booted session remembers
    # projects opened in a previous run") is actually exercised rather
    # than trivially true against an empty default list.
    load_config(config_path)  # create default file first
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["recent_projects"] = ["C:/fake/project-one.json"]
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    context = bootstrap(config_path=config_path, log_dir=log_dir)
    project_service = context.container.resolve(ProjectService)

    assert "C:/fake/project-one.json" in project_service.get_recent_projects()


def test_bootstrap_creates_log_dir(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    assert not log_dir.exists()

    bootstrap(config_path=config_path, log_dir=log_dir)

    assert log_dir.exists()
