# File: src/ui/autosave_timer.py
"""Periodically saves the active project, per ``autosave.enabled``/``interval_minutes``.

Described in ``config.yaml`` since milestone 1a and never implemented before this milestone --
confirmed directly against the pre-milestone-29 source (no code anywhere constructed a
``QTimer`` tied to these two keys) before writing this module, not assumed.

**Runs the save synchronously on the UI thread, deliberately, not via
:class:`~src.ui.worker_runner.WorkerRunner`.** The manual "Save Project"/"Save Project As"
actions (:meth:`~src.ui.controllers.project_controller.ProjectController.save_project`) already
do exactly this -- a project file is metadata only (dataset names and *source paths*, never the
dataframes themselves; see :class:`~uadas_core.models.Project`'s own JSON shape), so
the write is small and fast, not the kind of "must not block the UI thread" operation this
project's own convention (report generation, dataset re-reads) reserves ``WorkerRunner`` for.
Mirroring the manual save path's own synchronous behavior here avoids introducing a new,
previously-nonexistent risk this milestone's own safety bar specifically calls out avoiding:
mutating a plain (not documented or verified thread-safe) :class:`~uadas_core.services.project_service.
Project` object from a worker thread while the UI thread might read it concurrently.

**Re-reads ``enabled``/``interval_minutes`` from :class:`~uadas_core.services.settings_service.
SettingsService` on every :meth:`AutosaveTimer.tick`, rather than requiring an explicit
"please reconfigure me" call from whoever owns the Settings dialog.** This is what lets a
change made through Settings take effect on the very next natural timer firing with zero
additional wiring anywhere else (no ``ThemeController``-style "apply on Settings Save" call
site needed) -- the trade-off, stated plainly rather than left implicit: a change made mid-way
through the *current* interval is not retroactive, so at most one interval's worth of the old
setting is honored before the new one takes effect. Chosen over the alternative (reconfigure
eagerly the moment Settings is saved) specifically because that alternative would need a second
controller wired through ``main_window.py``, which was already at its
``tests.ui.test_module_size`` budget as of this milestone.

**Testability**: :meth:`tick` is the unit of "one interval elapsed" and is what
``tests/ui/test_autosave_timer.py`` calls directly, any number of times, rather than waiting on
a real ``QTimer`` to actually fire -- this project's standing rule against wall-clock-sleep-based
tests for timing features (see this milestone's own safety bar). The real ``QTimer`` this class
owns is only ever exercised by the running application itself; calling :meth:`tick` in a test
is not a simplified stand-in for it, it is the exact same code path ``QTimer.timeout`` invokes.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer

from uadas_core.core.exceptions import ApplicationError
from uadas_core.core.logger import get_logger
from uadas_core.services.project_service import ProjectService
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService

_logger = get_logger(__name__)

_MS_PER_MINUTE = 60_000


class AutosaveTimer(QObject):
    """Drives periodic project saves off a ``QTimer``, self-configuring from live settings.

    Args:
        project_service: The active project (if any) is read and saved here.
        workspace_service: Supplies the current dataset list to
            :meth:`~uadas_core.services.project_service.ProjectService.record_datasets` before saving,
            so an autosave reflects datasets added/closed since the last save, the same as a
            manual save does.
        settings_service: Read fresh on every :meth:`tick` for ``autosave.enabled``/
            ``interval_minutes`` -- see this module's own docstring for why no separate
            "reconfigure" call is needed.
        parent: Qt parent -- keeps this object (and its internal ``QTimer``) alive for as long
            as ``parent`` is, the same ownership shape every other plain-UI-infrastructure
            collaborator in this codebase uses (see e.g. ``WorkerRunner``'s own docstring).
    """

    def __init__(
        self,
        project_service: ProjectService,
        workspace_service: WorkspaceService,
        settings_service: SettingsService,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._project_service = project_service
        self._workspace_service = workspace_service
        self._settings_service = settings_service
        self._enabled = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._apply_current_settings()

    def _apply_current_settings(self) -> None:
        """Read ``autosave.enabled``/``interval_minutes`` and start/stop/retime the timer."""
        self._enabled = self._settings_service.get("autosave", "enabled", default=True)
        interval_minutes = self._settings_service.get(
            "autosave", "interval_minutes", default=5
        )
        if self._enabled and interval_minutes > 0:
            self._timer.setInterval(interval_minutes * _MS_PER_MINUTE)
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def tick(self) -> None:
        """One interval elapsed: save the active project, if there is one worth saving.

        A no-op, not an error, in every one of these cases -- autosave should never interrupt
        the user with a dialog on a timer:

        * ``autosave.enabled`` is currently ``False`` (re-checked here, not only at
          construction -- see this module's own docstring).
        * No project is open.
        * The open project has never been saved before (``project.path`` is ``None``) --
          autosave never prompts for a filename the way a first manual save would; it only
          ever writes to a path that already exists.
        """
        self._apply_current_settings()
        if not self._enabled:
            return

        project = self._project_service.get_active_project()
        if project is None or project.path is None:
            return

        self._project_service.record_datasets(
            project, self._workspace_service.list_datasets()
        )
        try:
            self._project_service.save_project(project)
        except ApplicationError as exc:
            _logger.warning("Autosave failed for project '%s': %s", project.name, exc)
            return

        _logger.info("Autosaved project '%s' to %s.", project.name, project.path)
