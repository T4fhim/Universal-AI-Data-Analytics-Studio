# File: tests/ui/test_autosave_timer.py
"""Covers milestone 29's autosave wiring: real behavior, driven by a fake clock.

Per this milestone's own safety bar, ``AutosaveTimer.tick`` -- the exact method a real
``QTimer.timeout`` connects to -- is called directly, any number of times, standing in for
"N intervals elapsed" without any real wall-clock waiting. Every collaborator is a small,
duck-typed fake (matching ``tests/ui/controllers/test_project_controller.py``'s own stated
convention) so a test can assert precisely how many times ``save_project`` was actually called,
not merely that no exception was raised.
"""

from __future__ import annotations

from pathlib import Path

from src.ui.autosave_timer import AutosaveTimer
from uadas_core.services.project_service import Project


class _FakeProjectService:
    def __init__(self, active_project: Project | None) -> None:
        self._active_project = active_project
        self.save_calls: list[Project] = []
        self.record_calls: list[list] = []

    def get_active_project(self) -> Project | None:
        return self._active_project

    def record_datasets(self, project, datasets) -> list[str]:
        self.record_calls.append(list(datasets))
        return []

    def save_project(self, project, path=None) -> None:
        self.save_calls.append(project)


class _FakeWorkspaceService:
    def list_datasets(self):
        return []


class _FakeSettingsService:
    """A mutable ``{("autosave", "enabled"): ..., ("autosave", "interval_minutes"): ...}``
    stand-in -- tests mutate :attr:`values` between :meth:`~src.ui.autosave_timer.
    AutosaveTimer.tick` calls to simulate a Settings change taking effect on the next tick,
    exactly the behavior :mod:`src.ui.autosave_timer`'s own docstring documents.
    """

    def __init__(self, enabled: bool = True, interval_minutes: int = 5) -> None:
        self.values = {
            ("autosave", "enabled"): enabled,
            ("autosave", "interval_minutes"): interval_minutes,
        }

    def get(self, *key_path: str, default=None):
        return self.values.get(key_path, default)


def test_tick_saves_the_active_project_when_it_has_a_path(qapp, tmp_path: Path) -> None:
    project = Project(name="Demo", path=tmp_path / "demo.uads.json")
    project_service = _FakeProjectService(project)
    timer = AutosaveTimer(
        project_service, _FakeWorkspaceService(), _FakeSettingsService()
    )

    timer.tick()

    assert project_service.save_calls == [project]
    assert project_service.record_calls == [[]]


def test_tick_saves_exactly_once_per_call_no_more_no_less(qapp, tmp_path: Path) -> None:
    project = Project(name="Demo", path=tmp_path / "demo.uads.json")
    project_service = _FakeProjectService(project)
    timer = AutosaveTimer(
        project_service, _FakeWorkspaceService(), _FakeSettingsService()
    )

    for _ in range(5):
        timer.tick()

    assert len(project_service.save_calls) == 5


def test_disabling_autosave_stops_saving(qapp, tmp_path: Path) -> None:
    project = Project(name="Demo", path=tmp_path / "demo.uads.json")
    project_service = _FakeProjectService(project)
    settings = _FakeSettingsService(enabled=True)
    timer = AutosaveTimer(project_service, _FakeWorkspaceService(), settings)

    timer.tick()
    assert len(project_service.save_calls) == 1

    settings.values[("autosave", "enabled")] = False
    timer.tick()
    timer.tick()
    assert len(project_service.save_calls) == 1  # unchanged -- no further saves


def test_re_enabling_autosave_resumes_saving(qapp, tmp_path: Path) -> None:
    project = Project(name="Demo", path=tmp_path / "demo.uads.json")
    project_service = _FakeProjectService(project)
    settings = _FakeSettingsService(enabled=False)
    timer = AutosaveTimer(project_service, _FakeWorkspaceService(), settings)

    timer.tick()
    assert project_service.save_calls == []

    settings.values[("autosave", "enabled")] = True
    timer.tick()
    assert len(project_service.save_calls) == 1


def test_no_active_project_is_a_silent_no_op(qapp) -> None:
    project_service = _FakeProjectService(None)
    timer = AutosaveTimer(
        project_service, _FakeWorkspaceService(), _FakeSettingsService()
    )

    timer.tick()

    assert project_service.save_calls == []


def test_a_project_never_saved_before_is_a_silent_no_op(qapp) -> None:
    """A project with no path yet must never be autosaved -- that would require prompting for
    a filename, which a background timer must never do (see the module's own docstring).
    """
    project = Project(name="Untitled")  # path=None: never saved manually yet
    project_service = _FakeProjectService(project)
    timer = AutosaveTimer(
        project_service, _FakeWorkspaceService(), _FakeSettingsService()
    )

    timer.tick()

    assert project_service.save_calls == []


def test_interval_is_applied_in_milliseconds_at_construction(qapp) -> None:
    settings = _FakeSettingsService(enabled=True, interval_minutes=7)
    timer = AutosaveTimer(_FakeProjectService(None), _FakeWorkspaceService(), settings)

    assert timer._timer.interval() == 7 * 60_000
    assert timer._timer.isActive()


def test_disabled_at_construction_never_starts_the_real_timer(qapp) -> None:
    settings = _FakeSettingsService(enabled=False)
    timer = AutosaveTimer(_FakeProjectService(None), _FakeWorkspaceService(), settings)

    assert not timer._timer.isActive()


def test_changing_interval_takes_effect_on_the_next_tick(qapp) -> None:
    settings = _FakeSettingsService(enabled=True, interval_minutes=5)
    timer = AutosaveTimer(_FakeProjectService(None), _FakeWorkspaceService(), settings)
    assert timer._timer.interval() == 5 * 60_000

    settings.values[("autosave", "interval_minutes")] = 10
    timer.tick()

    assert timer._timer.interval() == 10 * 60_000
