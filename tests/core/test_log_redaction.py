# File: tests/core/test_log_redaction.py
"""Tenant data and secrets never reach the (shared) log, even at DEBUG.

In server mode every tenant's session logs into one stderr stream. ``%r`` of a
``Dataset`` includes its DataFrame head/tail, ``%r`` of a ``Project`` includes its
open-ended ``contents``, and ``%r`` of a setting value is whatever the caller stored --
including an API key. The services therefore log ids, names and key *paths* only. Each
test pairs the absence of the sentinel with the presence of the identifier that *is*
allowed in the log, so a logger that had simply gone silent could not pass.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Iterator

import pandas as pd
import plotly.graph_objects as go
import pytest

from uadas_core.bootstrap import ProcessContext, bootstrap_process, build_session
from uadas_core.core.application_state import ApplicationState
from uadas_core.core.config import AppConfig
from uadas_core.core.dependency_container import DependencyContainer
from uadas_core.models import Dataset, Project, Visualization
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService

_CELL = "SENTINEL-CELL-4f1d"
_CONTENTS = "SENTINEL-PROJECT-CONTENTS-77ab"
_CHART = "SENTINEL-CHART-PARAM-c0de"
_SECRET = "sk-SENTINEL-SECRET-1234567890"


@pytest.fixture()
def log(monkeypatch: pytest.MonkeyPatch, reset_logging_state) -> io.StringIO:
    """The captured stderr a server-mode process (at DEBUG) logs into."""
    sink = io.StringIO()
    monkeypatch.setattr(sys, "stderr", sink)
    return sink


@pytest.fixture()
def session(log: io.StringIO) -> Iterator[DependencyContainer]:
    data = AppConfig.defaults().to_dict()
    data["logging"]["level"] = "DEBUG"
    process: ProcessContext = bootstrap_process(
        server_mode=True, config=AppConfig.from_dict(data)
    )
    yield build_session(process)
    process.close()


def test_application_state_logs_names_and_ids_never_object_contents(
    log: io.StringIO, session: DependencyContainer
) -> None:
    state = session.resolve(ApplicationState)
    dataset = Dataset(
        name="sales-q3",
        dataframe=pd.DataFrame({"a": [_CELL, _CELL + "-2"]}),
        source_format="csv",
    )
    project = Project(name="board-pack", contents={"note": _CONTENTS})
    viz = Visualization(
        name="rev-chart",
        dataset_id=dataset.dataset_id,
        figure=go.Figure(),
        chart_type="bar",
        chart_parameters={"title": _CHART},
    )

    state.set_active_dataset(dataset)
    state.set_active_project(project)
    state.set_active_visualization(viz)

    text = log.getvalue()
    # allowed: names and ids (positive twin -- the DEBUG lines really were emitted)
    assert "sales-q3" in text and dataset.dataset_id in text
    assert "board-pack" in text
    assert "rev-chart" in text and viz.visualization_id in text
    # forbidden: any content
    for sentinel in (_CELL, _CONTENTS, _CHART):
        assert sentinel not in text


def test_clearing_the_active_object_logs_a_plain_message(
    log: io.StringIO, session: DependencyContainer
) -> None:
    state = session.resolve(ApplicationState)

    state.set_active_dataset(None)
    state.set_active_project(None)
    state.set_active_visualization(None)

    assert "Active dataset cleared" in log.getvalue()


def test_settings_service_logs_the_key_path_never_the_value(
    log: io.StringIO, session: DependencyContainer
) -> None:
    settings = session.resolve(SettingsService)

    settings.set("ai", "secret", value=_SECRET)

    text = log.getvalue()
    assert "ai.secret" in text  # the key path is logged (positive twin)
    assert _SECRET not in text
    assert settings.get("ai", "secret") == _SECRET  # and the value really was stored


def test_workspace_logging_does_not_leak_cells_either(
    log: io.StringIO, session: DependencyContainer
) -> None:
    workspace = session.resolve(WorkspaceService)
    dataset = Dataset(
        name="ws-data", dataframe=pd.DataFrame({"a": [_CELL]}), source_format="csv"
    )

    workspace.add_dataset(dataset)

    text = log.getvalue()
    assert dataset.dataset_id in text
    assert _CELL not in text
