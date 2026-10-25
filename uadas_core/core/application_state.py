# File: uadas_core/core/application_state.py
"""In-memory session state for the currently running application instance.

:class:`ApplicationState` tracks what the user is currently working
on — the active project, dataset, and visualization — for the
lifetime of a single running process. It is not a persistence
mechanism; saving and loading project state to disk is the
responsibility of a project service (introduced in a later milestone),
which will read from and write into an ``ApplicationState`` instance
rather than duplicating what it tracks.

This module was written before milestone 1b-i built the concrete
``Project``, ``Dataset``, and ``Visualization`` classes it holds (now in
``uadas_core.models``). The accessors below are typed against small
structural Protocols (:class:`ProjectLike`, :class:`DatasetLike`,
:class:`VisualizationLike`) rather than those classes, because
``uadas_core.core`` sits at the bottom of this project's layered
architecture: models already depend on core (``models.project`` raises
``ServiceError``), so any import in the other direction -- even a
``TYPE_CHECKING``-only one, which import-linter still counts -- is a cycle.
The old ``TYPE_CHECKING`` import needed an ``ignore_imports`` exemption in
``.importlinter``; the Protocols remove the edge, and the exemption, entirely.

An instance of this class is intended to be registered into the
:class:`~uadas_core.core.dependency_container.DependencyContainer` as a
singleton (see :mod:`uadas_core.bootstrap`), rather than held as a
module-level global — this keeps session state explicit and
resolvable through the same mechanism as every other service, and
avoids a global mutable object that any module could import and
mutate without going through the container.
"""

from __future__ import annotations

from typing import Protocol

from uadas_core.core.exceptions import ApplicationStateError
from uadas_core.core.logger import get_logger

_logger = get_logger(__name__)


# Structural stand-ins for :class:`uadas_core.models.Project` / ``Dataset`` /
# ``Visualization``. ApplicationState only *holds* and logs these objects, so all it
# needs from them is a name. Protocols (rather than the old ``TYPE_CHECKING`` import of
# ``uadas_core.models``) remove the last core -> models edge from the import graph --
# import-linter counts TYPE_CHECKING imports, which is why that edge needed an
# ``ignore_imports`` entry. The models satisfy these protocols structurally; read-only
# properties are used so the models' mutable dataclass fields conform.
class ProjectLike(Protocol):
    """Anything with a ``name`` -- in practice :class:`uadas_core.models.Project`."""

    @property
    def name(self) -> str: ...


class DatasetLike(Protocol):
    """A ``name`` and ``dataset_id`` -- in practice :class:`uadas_core.models.Dataset`."""

    @property
    def name(self) -> str: ...

    @property
    def dataset_id(self) -> str: ...


class VisualizationLike(Protocol):
    """A ``name`` and ``visualization_id`` -- in practice
    :class:`uadas_core.models.Visualization`."""

    @property
    def name(self) -> str: ...

    @property
    def visualization_id(self) -> str: ...


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
        self._active_project: ProjectLike | None = None
        self._active_dataset: DatasetLike | None = None
        self._active_visualization: VisualizationLike | None = None

    # -- Active project ----------------------------------------------------

    @property
    def active_project(self) -> ProjectLike:
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

    def set_active_project(self, project: ProjectLike | None) -> None:
        """Set (or clear, by passing ``None``) the active project."""
        self._active_project = project
        # Name only, never ``%r``: a Project's open-ended ``contents`` is tenant data and
        # this line lands in the log shared by every session of a server process.
        if project is None:
            _logger.debug("Active project cleared.")
        else:
            _logger.debug("Active project set to: %s", project.name)

    def has_active_project(self) -> bool:
        """Return whether a project is currently active."""
        return self._active_project is not None

    # -- Active dataset -----------------------------------------------------

    @property
    def active_dataset(self) -> DatasetLike:
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

    def set_active_dataset(self, dataset: DatasetLike | None) -> None:
        """Set (or clear, by passing ``None``) the active dataset."""
        self._active_dataset = dataset
        # Name and id only: a Dataset's repr includes its DataFrame's head and tail.
        if dataset is None:
            _logger.debug("Active dataset cleared.")
        else:
            _logger.debug(
                "Active dataset set to: %s (%s)", dataset.name, dataset.dataset_id
            )

    def has_active_dataset(self) -> bool:
        """Return whether a dataset is currently active."""
        return self._active_dataset is not None

    # -- Active visualization ------------------------------------------------

    @property
    def active_visualization(self) -> VisualizationLike:
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

    def set_active_visualization(self, visualization: VisualizationLike | None) -> None:
        """Set (or clear, by passing ``None``) the active visualization."""
        self._active_visualization = visualization
        # Name and id only: a Visualization's repr includes its figure and parameters.
        if visualization is None:
            _logger.debug("Active visualization cleared.")
        else:
            _logger.debug(
                "Active visualization set to: %s (%s)",
                visualization.name,
                visualization.visualization_id,
            )

    def has_active_visualization(self) -> bool:
        """Return whether a visualization is currently active."""
        return self._active_visualization is not None
