# File: tests/core/test_session_isolation.py
"""Two sessions built from ONE process share no mutable service state.

This is the property the whole session seam exists for: a multi-tenant server holds
one :class:`~uadas_core.bootstrap.ProcessContext` and builds a fresh session
container per request/tenant. Anything stateful that leaked between sessions would be
a cross-tenant data leak, so each test mutates session A and asserts session B did
not move -- and keeps a positive twin in the same test (A *did* change) so a service
that silently ignored writes could not pass.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

import pandas as pd
import pytest

from uadas_core.bootstrap import ProcessContext, bootstrap_process, build_session
from uadas_core.cleaning import operation_registry
from uadas_core.core.application_state import ApplicationState
from uadas_core.core.config import AppConfig
from uadas_core.core.dependency_container import DependencyContainer
from uadas_core.core.exceptions import ServiceError
from uadas_core.jobs.job_runner import JobRunner
from uadas_core.models import Dataset
from uadas_core.persistence.persistence_service import PersistenceService
from uadas_core.readers import reader_registry
from uadas_core.results import result_renderer_registry
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisLog,
    AnalysisOrchestratorService,
    PipelineStage,
)
from uadas_core.services.database_connection_service import DatabaseConnectionService
from uadas_core.services.guidance_service import GuidanceService
from uadas_core.services.project_service import ProjectService
from uadas_core.services.report_service import ReportService
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService
from uadas_core.visualization import chart_registry

# The per-user services: each must be a distinct object in every session.
_PER_SESSION: tuple[type, ...] = (
    ApplicationState,
    SettingsService,
    ProjectService,
    WorkspaceService,
    AnalysisOrchestratorService,
    GuidanceService,
    ReportService,
    DatabaseConnectionService,
)
# The process-wide services: one shared, stateless-by-design instance.
_PER_PROCESS: tuple[object, ...] = (AppConfig, PersistenceService, JobRunner)


@pytest.fixture()
def process(reset_logging_state) -> Iterator[ProcessContext]:
    context = bootstrap_process(server_mode=True)
    yield context
    context.close()


def _dataset(name: str = "d") -> Dataset:
    return Dataset(
        name=name, dataframe=pd.DataFrame({"a": [1, 2, 3]}), source_format="csv"
    )


def test_per_user_services_are_distinct_and_process_services_are_shared(
    process: ProcessContext,
) -> None:
    a, b = build_session(process), build_session(process)

    for service_type in _PER_SESSION:
        assert a.resolve(service_type) is not b.resolve(service_type), service_type
        assert a.resolve(service_type) is a.resolve(service_type), service_type
    for key in _PER_PROCESS:
        assert a.resolve(key) is b.resolve(key) is process.container.resolve(key)


def test_sessions_are_children_of_the_process_container(
    process: ProcessContext,
) -> None:
    session = build_session(process)

    assert isinstance(session, DependencyContainer)
    assert session.parent is process.container
    # Per-user services are registered in the session, never on the process.
    for service_type in _PER_SESSION:
        assert session.is_registered(service_type)
        assert not process.container.is_registered(service_type), service_type


def test_datasets_opened_in_one_session_are_invisible_in_the_other(
    process: ProcessContext,
) -> None:
    a, b = build_session(process), build_session(process)
    ds = _dataset()

    a.resolve(WorkspaceService).add_dataset(ds)

    assert a.resolve(WorkspaceService).list_datasets() == [ds]  # positive twin
    assert b.resolve(WorkspaceService).list_datasets() == []


def test_closing_a_workspace_dataset_in_one_session_does_not_touch_the_other(
    process: ProcessContext,
) -> None:
    a, b = build_session(process), build_session(process)
    ds_a, ds_b = _dataset("a"), _dataset("b")
    a.resolve(WorkspaceService).add_dataset(ds_a)
    b.resolve(WorkspaceService).add_dataset(ds_b)

    a.resolve(WorkspaceService).close_dataset(ds_a.dataset_id)

    assert a.resolve(WorkspaceService).list_datasets() == []
    assert b.resolve(WorkspaceService).list_datasets() == [ds_b]


def test_settings_changes_in_one_session_do_not_appear_in_the_other(
    process: ProcessContext,
) -> None:
    a, b = build_session(process), build_session(process)

    a.resolve(SettingsService).set("theme", value="light")
    a.resolve(SettingsService).save()

    assert a.resolve(SettingsService).get("theme") == "light"  # positive twin
    assert b.resolve(SettingsService).get("theme") == "dark"
    assert build_session(process).resolve(SettingsService).get("theme") == "dark"
    assert process.config.theme == "dark"


def test_application_state_and_recent_projects_are_per_session(
    process: ProcessContext,
) -> None:
    a, b = build_session(process), build_session(process)
    ds = _dataset()

    a.resolve(ApplicationState).set_active_dataset(ds)

    assert a.resolve(ApplicationState).has_active_dataset()  # positive twin
    assert not b.resolve(ApplicationState).has_active_dataset()


def test_analysis_logs_are_per_session(process: ProcessContext) -> None:
    a, b = build_session(process), build_session(process)

    a.resolve(AnalysisOrchestratorService).load_log(AnalysisLog(dataset_id="ds-1"))

    assert [
        log.dataset_id for log in a.resolve(AnalysisOrchestratorService).get_all_logs()
    ] == [
        "ds-1"
    ]  # positive twin
    assert b.resolve(AnalysisOrchestratorService).get_all_logs() == []


def test_a_session_orchestrator_is_wired_to_its_own_workspace(
    process: ProcessContext,
) -> None:
    a, b = build_session(process), build_session(process)
    ds = _dataset()
    a.resolve(WorkspaceService).add_dataset(ds)

    # A's orchestrator can see A's dataset; B's cannot see it at all.
    entry = a.resolve(AnalysisOrchestratorService).run_stage(
        ds.dataset_id, PipelineStage.UNDERSTAND
    )
    assert (
        entry in a.resolve(AnalysisOrchestratorService).get_log(ds.dataset_id).entries
    )
    with pytest.raises(ServiceError):
        b.resolve(AnalysisOrchestratorService).run_stage(
            ds.dataset_id, PipelineStage.UNDERSTAND
        )


def test_process_registries_are_shared_by_design_and_not_grown_by_sessions(
    process: ProcessContext,
) -> None:
    def snapshot() -> tuple[object, ...]:
        return (
            list(reader_registry._PLUGIN_READERS),
            sorted(operation_registry.list_operations()),
            sorted(chart_registry.list_charts()),
            len(result_renderer_registry.list_renderers()),
            len(process.container._factories),  # type: ignore[attr-defined]
        )

    before = snapshot()

    for _ in range(25):
        session = build_session(process)
        session.resolve(WorkspaceService).add_dataset(_dataset())
        session.resolve(SettingsService).set("theme", value="light")

    assert snapshot() == before  # no module-global or process-container growth
    assert reader_registry._PLUGIN_READERS == []


def test_dropping_a_session_does_not_affect_the_process_or_other_sessions(
    process: ProcessContext,
) -> None:
    keeper = build_session(process)
    ds = _dataset()
    keeper.resolve(WorkspaceService).add_dataset(ds)

    for _ in range(5):
        build_session(process).resolve(WorkspaceService).add_dataset(_dataset())

    assert keeper.resolve(WorkspaceService).list_datasets() == [ds]


def test_concurrent_sessions_stay_isolated_under_threads(
    process: ProcessContext,
) -> None:
    workers = 12
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []
    seen: dict[int, list[str]] = {}

    def work(index: int) -> None:
        try:
            barrier.wait(timeout=30)
            session = build_session(process)
            workspace = session.resolve(WorkspaceService)
            settings = session.resolve(SettingsService)
            mine = [_dataset(f"w{index}-{n}") for n in range(5)]
            for dataset in mine:
                workspace.add_dataset(dataset)
            settings.set("autosave", "interval_minutes", value=100 + index)
            # A shared process runner must be reachable from every thread.
            assert session.resolve(JobRunner) is process.job_runner
            names = sorted(d.name for d in workspace.list_datasets())
            assert names == sorted(d.name for d in mine)
            assert settings.get("autosave", "interval_minutes") == 100 + index
            seen[index] = names
        except BaseException as exc:  # noqa: BLE001 - surfaced after join
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert errors == []
    assert len(seen) == workers
    assert process.config.autosave_interval_minutes == 5  # process config untouched


def test_the_process_context_is_reusable_for_many_sessions(
    process: ProcessContext,
) -> None:
    sessions = [build_session(process) for _ in range(50)]

    assert len({id(s.resolve(WorkspaceService)) for s in sessions}) == 50
    assert len({id(s.resolve(JobRunner)) for s in sessions}) == 1
