# File: tests/ui/actions/test_action_context.py
"""Tests for ActionContext.capture() and satisfies().

Uses minimal duck-typed stand-ins for ProjectService/WorkspaceService/
SettingsService rather than the real classes -- capture() only calls a
handful of specific methods on each, and constructing the real services
would require project/config file I/O this module has no interest in
exercising. No QApplication anywhere in this file.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ui.actions.action_context import ActionContext
from src.ui.actions.action_registry import Requirement


class _FakeProjectService:
    def __init__(self, active_project: object | None = None) -> None:
        self._active_project = active_project

    def get_active_project(self):
        return self._active_project


class _FakeDataset:
    def __init__(self, dataframe: pd.DataFrame) -> None:
        self.dataframe = dataframe


class _FakeWorkspaceService:
    def __init__(
        self, active_dataset: _FakeDataset | None = None, visualizations=()
    ) -> None:
        self._active_dataset = active_dataset
        self._visualizations = list(visualizations)

    def get_active_dataset(self):
        return self._active_dataset

    def list_visualizations(self):
        return self._visualizations


class _FakeSettingsService:
    def __init__(self, providers=()) -> None:
        self._providers = list(providers)

    def get(self, *key_path, default=None):
        if key_path == ("ai", "providers"):
            return self._providers
        return default


def test_capture_with_no_project_no_dataset() -> None:
    context = ActionContext.capture(
        project_service=_FakeProjectService(active_project=None),
        workspace_service=_FakeWorkspaceService(active_dataset=None),
        settings_service=_FakeSettingsService(providers=[]),
    )
    assert context.has_project is False
    assert context.has_active_dataset is False
    assert context.visualization_count == 0
    assert context.numeric_column_count == 0
    assert context.datetime_column_count == 0
    assert context.ai_configured is False


def test_capture_with_project_and_dataset() -> None:
    df = pd.DataFrame(
        {
            "a": [1, 2, 3],
            "b": [1.5, 2.5, 3.5],
            "c": ["x", "y", "z"],
            "d": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )
    context = ActionContext.capture(
        project_service=_FakeProjectService(active_project=object()),
        workspace_service=_FakeWorkspaceService(
            active_dataset=_FakeDataset(df), visualizations=[object(), object()]
        ),
        settings_service=_FakeSettingsService(providers=[{"name": "anthropic"}]),
    )
    assert context.has_project is True
    assert context.has_active_dataset is True
    assert context.visualization_count == 2
    # Column-count computation is O(columns): int + float both count as
    # numeric (dtype.kind "i"/"f"), the object column does not, and the
    # one datetime64 column counts separately.
    assert context.numeric_column_count == 2
    assert context.datetime_column_count == 1
    assert context.ai_configured is True


def test_capture_never_touches_dataframe_rows() -> None:
    """A dtypes-only computation must stay correct (and cheap) at any row
    count -- this is the "O(columns), never O(rows)" contract the module
    docstring makes explicit, exercised at a size a naive per-row
    implementation would visibly slow down on.
    """
    df = pd.DataFrame({"n": range(200_000)})
    context = ActionContext.capture(
        project_service=_FakeProjectService(),
        workspace_service=_FakeWorkspaceService(active_dataset=_FakeDataset(df)),
        settings_service=_FakeSettingsService(),
    )
    assert context.numeric_column_count == 1


def test_satisfies_project_open() -> None:
    context = ActionContext.capture(
        project_service=_FakeProjectService(active_project=object()),
        workspace_service=_FakeWorkspaceService(),
        settings_service=_FakeSettingsService(),
    )
    assert context.satisfies(Requirement.PROJECT_OPEN) is True
    assert context.satisfies(Requirement.ACTIVE_DATASET) is False


def test_can_undo_redo_default_false() -> None:
    context = ActionContext.capture(
        project_service=_FakeProjectService(),
        workspace_service=_FakeWorkspaceService(),
        settings_service=_FakeSettingsService(),
    )
    assert context.can_undo is False
    assert context.can_redo is False


def test_context_is_frozen() -> None:
    context = ActionContext.capture(
        project_service=_FakeProjectService(),
        workspace_service=_FakeWorkspaceService(),
        settings_service=_FakeSettingsService(),
    )
    with pytest.raises(AttributeError):
        context.has_project = True  # type: ignore[misc]
