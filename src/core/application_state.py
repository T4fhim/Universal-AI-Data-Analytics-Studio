# File: src/core/application_state.py
"""In-memory session state for the currently running application instance.

:class:`ApplicationState` tracks what the user is currently working
on — the active project, dataset, and visualization — for the
lifetime of a single running process. It is not a persistence
mechanism; saving and loading project state to disk is the
responsibility of a project service (introduced in a later milestone),
which will read from and write into an ``ApplicationState`` instance
rather than duplicating what it tracks.

This module was written before milestone 1b-i built the concrete
``Project``, ``Dataset``, and ``Visualization`` classes it references.
Those classes now exist in ``src.services.project_service`` and
``src.services.workspace_service`` respectively. The accessors below
remain typed against them as forward references (quoted strings via
``from __future__ import annotations``, resolved only under
``TYPE_CHECKING``) rather than real imports, because ``src.core`` sits
above ``src.services`` in this project's layered architecture
(Application -> Service -> Business Logic -> Data -> Presentation ->
Plugin) — core must not carry a runtime dependency on the service
layer, since services already depend on core (every service built so
far imports ``ServiceError`` and ``get_logger`` from this package) and
a runtime import in the other direction would create exactly the
circular dependency the architecture is meant to prevent.
``TYPE_CHECKING``-only imports never execute, so they carry no such
risk regardless of which direction they point.

An instance of this class is intended to be registered into the
:class:`~src.core.dependency_container.DependencyContainer` as a
singleton (see :mod:`src.core.bootstrap`), rather than held as a
module-level global — this keeps session state explicit and
resolvable through the same mechanism as every other service, and
avoids a global mutable object that any module could import and
mutate without going through the container.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.exceptions import ApplicationStateError
from src.core.logger import get_logger

if TYPE_CHECKING:
    # Real imports guarded by TYPE_CHECKING: these classes exist as of
    # milestone 1b-i, but core.application_state must not import
    # src.services at runtime (see module docstring above for why).
    from src.services.project_service import Project
    from src.services.workspace_service import Dataset, Visualization

_logger = get_logger(__name__)


class ApplicationState:
    """Tracks the active project, dataset, and visualization for this session.

    All three accessors follow the same pattern: a private optional
    attribute, a getter that raises :class:`ApplicationStateError` if
    nothing has been set, a setter, and a ``has_*`` boolean check for
    callers that want to branch on presence without triggering the
    exception. This keeps "nothing is active yet" as an explicit,
    named condition rather than a silent ``None`` that a caller might
    forget to check before using.
    """

    def __init__(self) -> None:
        self._active_project: Project | None = None
        self._active_dataset: Dataset | None = None
        self._active_visualization: Visualization | None = None

    # -- Active project ----------------------------------------------------

    @property
    def active_project(self) -> Project:
        """Return the currently active project.

        Raises:
            ApplicationStateError: If no project is currently active.
        """
        if self._active_project is None:
            raise ApplicationStateError(
                "No active project is set. Check has_active_project() "
                "before accessing active_project, or set one first."
            )
        return self._active_project

    def set_active_project(self, project: Project | None) -> None:
        """Set (or clear, by passing ``None``) the active project."""
        self._active_project = project
        _logger.debug("Active project set to: %r", project)

    def has_active_project(self) -> bool:
        """Return whether a project is currently active."""
        return self._active_project is not None

    # -- Active dataset -----------------------------------------------------

    @property
    def active_dataset(self) -> Dataset:
        """Return the currently active dataset.

        Raises:
            ApplicationStateError: If no dataset is currently active.
        """
        if self._active_dataset is None:
            raise ApplicationStateError(
                "No active dataset is set. Check has_active_dataset() "
                "before accessing active_dataset, or set one first."
            )
        return self._active_dataset

    def set_active_dataset(self, dataset: Dataset | None) -> None:
        """Set (or clear, by passing ``None``) the active dataset."""
        self._active_dataset = dataset
        _logger.debug("Active dataset set to: %r", dataset)

    def has_active_dataset(self) -> bool:
        """Return whether a dataset is currently active."""
        return self._active_dataset is not None

    # -- Active visualization ------------------------------------------------

    @property
    def active_visualization(self) -> Visualization:
        """Return the currently active visualization.

        Raises:
            ApplicationStateError: If no visualization is currently
                active.
        """
        if self._active_visualization is None:
            raise ApplicationStateError(
                "No active visualization is set. Check "
                "has_active_visualization() before accessing "
                "active_visualization, or set one first."
            )
        return self._active_visualization

    def set_active_visualization(self, visualization: Visualization | None) -> None:
        """Set (or clear, by passing ``None``) the active visualization."""
        self._active_visualization = visualization
        _logger.debug("Active visualization set to: %r", visualization)

    def has_active_visualization(self) -> bool:
        """Return whether a visualization is currently active."""
        return self._active_visualization is not None
