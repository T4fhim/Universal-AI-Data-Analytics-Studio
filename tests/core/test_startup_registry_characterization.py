# File: tests/core/test_startup_registry_characterization.py
"""Characterization guard for web-transition Phase 1.3 (Control B-3).

Phase 1.3 moves ``_register_builtins()`` for the cleaning-operation, chart, and
result-renderer registries off *module import* and into
:func:`uadas_core.core.bootstrap.bootstrap`. This module pins, as an executable
snapshot, two things every 1.3 commit must keep true:

1. After ``bootstrap()``, each of the three built-in registries holds exactly the
   set of built-ins it holds today (before the move) -- so a commit that forgets
   to seed one, seeds it twice, or drops an entry fails here rather than somewhere
   subtle downstream.
2. ``bootstrap()`` still resolves every service it registers, as singletons.

It deliberately does not assert the registries are *empty* without ``bootstrap()``
-- ``tests/conftest.py``'s session-autouse ``_seed_builtin_registries`` fixture
(added in the same phase) seeds them for the many tests that read a registry
without booting, so emptiness is not observable inside the suite. The snapshot of
*contents* is the regression signal, not the trigger mechanism.
"""

from __future__ import annotations

from pathlib import Path

from uadas_core.cleaning.operation_registry import list_operations
from uadas_core.core.application_state import ApplicationState
from uadas_core.core.bootstrap import bootstrap
from uadas_core.core.config import AppConfig
from uadas_core.jobs.job_runner import JobRunner
from uadas_core.plugins.plugin_manager import PluginManager
from uadas_core.results.result_renderer_registry import list_renderers
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
)
from uadas_core.services.database_connection_service import DatabaseConnectionService
from uadas_core.services.guidance_service import GuidanceService
from uadas_core.services.project_service import ProjectService
from uadas_core.services.report_service import ReportService
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService
from uadas_core.visualization.chart_registry import list_charts

_BUILTIN_OPERATION_NAMES = {
    "drop_missing_values",
    "fill_missing_values",
    "drop_duplicates",
    "normalize_text",
    "convert_type",
}

_BUILTIN_CHART_NAMES = {
    "bar",
    "pie",
    "line",
    "scatter",
    "histogram",
    "box_plot",
    "heatmap",
    "bubble",
    "treemap",
    "radar",
    "waterfall",
    "funnel",
}

# Every service type bootstrap() registers into the container, in construction order.
_REGISTERED_SERVICES: tuple[type, ...] = (
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
)


def test_bootstrap_populates_the_three_builtin_registries(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    bootstrap(config_path=config_path, log_dir=log_dir)

    assert set(list_operations()) == _BUILTIN_OPERATION_NAMES
    assert set(list_charts()) >= _BUILTIN_CHART_NAMES
    # 11 built-in renderers as of milestone 25 (see result_renderer_registry
    # ._register_builtins); aggregate/cross_tabulate fall through to the generic.
    assert len(list_renderers()) == 11


def test_bootstrap_resolves_every_registered_service_as_a_singleton(
    config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)

    for service_type in _REGISTERED_SERVICES:
        assert context.container.is_registered(service_type), service_type.__name__
        first = context.container.resolve(service_type)
        assert first is not None, service_type.__name__
        assert context.container.resolve(service_type) is first, service_type.__name__
