# File: tests/ui/controllers/test_project_controller.py
"""Tests for ProjectController, focused on the milestone-19 behavior change:

``ProjectService.record_datasets``'s skipped-dataset names (datasets with no
``source_path``, previously discarded at both call sites -- see
``ProjectController._warn_about_skipped_datasets``'s own docstring) are now
surfaced to the user via a warning dialog after a save.

Uses duck-typed fakes for the services/collaborators rather than the real
classes, matching ``tests/ui/actions/test_action_context.py``'s own stated
convention -- ``ProjectController`` only calls a handful of specific methods
on each.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow

from src.services.project_service import Project
from src.ui.controllers.project_controller import ProjectController


class _FakeProjectService:
    def __init__(self, active_project: Project | None, skipped_names=()) -> None:
        self._active_project = active_project
        self._skipped_names = list(skipped_names)
        self.saved_projects: list[Project] = []

    def get_active_project(self) -> Project | None:
        return self._active_project

    def record_datasets(self, project, datasets) -> list[str]:
        return self._skipped_names

    def save_project(self, project, path=None) -> None:
        if path is not None:
            project.path = path
        self.saved_projects.append(project)

    def get_recent_projects(self):
        return []


class _FakeWorkspaceService:
    def list_datasets(self):
        return []


class _FakeDockManager:
    def append_console_message(self, text: str) -> None:
        pass


class _FakeStatusBar:
    def show_message(self, text: str) -> None:
        pass

    def set_active_project_label(self, name) -> None:
        pass


class _FakeStateBus:
    def request_refresh(self) -> None:
        pass


class _FakeMenuBar:
    def update_recent_projects_menu(self, recent_paths, on_open) -> None:
        pass


def _make_controller(parent, project_service, worker_runner=None) -> ProjectController:
    return ProjectController(
        parent,
        project_service,
        _FakeWorkspaceService(),
        _FakeDockManager(),
        _FakeStatusBar(),
        _FakeStateBus(),
        worker_runner,
        _FakeMenuBar(),
    )


def test_save_project_with_no_skipped_datasets_shows_no_warning(
    qapp: QApplication, block_modals
) -> None:
    parent = QMainWindow()
    project = Project(name="Test", path=Path("test.uads.json"))
    service = _FakeProjectService(project, skipped_names=[])
    controller = _make_controller(parent, service)

    controller.save_project()

    assert service.saved_projects == [project]
    assert block_modals == []


def test_save_project_with_skipped_datasets_warns_the_user_by_name(
    qapp: QApplication, block_modals
) -> None:
    """The milestone-19 fix: before this, record_datasets' return value was
    discarded entirely -- a save that silently dropped a derived dataset
    gave the user no indication anything was left out.
    """
    parent = QMainWindow()
    project = Project(name="Test", path=Path("test.uads.json"))
    service = _FakeProjectService(project, skipped_names=["Cleaned Sales Data"])
    controller = _make_controller(parent, service)

    controller.save_project()

    assert service.saved_projects == [project]
    assert len(block_modals) == 1
    assert block_modals[0].kind == "warning"
    assert "Cleaned Sales Data" in block_modals[0].text


def test_save_project_as_with_skipped_datasets_also_warns(
    qapp: QApplication, block_modals, monkeypatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: ("saved.uads.json", "")),
    )

    parent = QMainWindow()
    project = Project(name="Test", path=None)
    service = _FakeProjectService(project, skipped_names=["Derived Dataset"])
    controller = _make_controller(parent, service)

    controller.save_project_as()

    assert service.saved_projects == [project]
    assert any(call.kind == "warning" for call in block_modals)
