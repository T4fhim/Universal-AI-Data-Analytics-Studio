# File: src/services/workspace_service.py
"""Session-scoped tracking of loaded datasets and the active visualization.

:class:`WorkspaceService` answers "what data is currently loaded, and
what is the user currently looking at" for a running session. It does
not read files or parse formats itself — that is
:mod:`src.readers`'s job (see milestone 2a onward) — but as of
milestone 2a, :class:`Dataset` now holds the actual loaded data a
reader produced, not just a name and source path. This service's own
job is unchanged: bookkeeping over datasets someone else produced, not
producing them itself.

The :class:`Visualization` class remains deliberately minimal, for the
same reason :class:`Dataset` was minimal until this milestone: nothing
in the codebase yet produces a visualization, so there is nothing real
to extend it with. :class:`Dataset` is no longer in that position —
milestone 2a's readers are its producer, so it is extended here rather
than staying a placeholder past the point where a placeholder is
honest.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

if TYPE_CHECKING:
    import pandas as pd
    import plotly.graph_objects as go

_logger = get_logger(__name__)


@dataclass
class Dataset:
    """A single loaded dataset: its data, and metadata about how it was read.

    Attributes:
        dataset_id: Unique identifier for this dataset within the
            current session. Generated automatically if not supplied.
        name: Display name, typically derived from the source file
            name but editable independently of it.
        source_path: Where this dataset was loaded from, if it came
            from a file. ``None`` for datasets constructed without a
            file source (a database query result in a later
            milestone, for instance).
        dataframe: The actual loaded data, as a ``pandas.DataFrame``.
            This is what milestone 2a's readers exist to produce.
            Typed as ``pd.DataFrame`` under ``TYPE_CHECKING`` only
            (see the module-level import) even though pandas is a
            real runtime dependency of this project — done for
            consistency with how this file already handles
            forward-referenced types, and because it costs nothing to
            keep the pattern uniform.
        row_count: Number of rows in ``dataframe``, cached at load
            time. Duplicates ``len(dataframe)``, which is cheap for a
            DataFrame — this field exists so callers (status bar text,
            the dataset explorer dock) can display it without needing
            a DataFrame reference in scope, and so it survives even if
            a future milestone adds lazy-loaded or chunked datasets
            where ``dataframe`` might not always be immediately
            available.
        column_count: Number of columns in ``dataframe``, cached for
            the same reason as ``row_count``.
        source_format: The format this dataset was read from, e.g.
            ``"csv"``, ``"json"``. Set by the reader that produced
            this dataset — see
            :class:`~src.readers.base_reader.BaseReader`.
        read_warnings: Non-fatal issues the reader encountered while
            reading — malformed rows that were skipped, columns whose
            type had to be inferred ambiguously, and so on. An empty
            list means the reader completed with no warnings, not that
            no reader has run yet (a dataset with no ``dataframe`` set
            is not constructible — see below).
        parent_dataset_id: The :attr:`dataset_id` of the dataset this
            one was derived from, if any. ``None`` for a dataset
            produced directly by a reader (every ``Dataset`` in this
            project until milestone 3a) — a derived dataset (the
            output of a future cleaning or transformation operation)
            sets this to trace its lineage back to its source.
        derivation_description: A short, human-readable description of
            how this dataset was produced from its parent, e.g.
            ``"Removed rows with null values in 'email'"``. ``None``
            when ``parent_dataset_id`` is ``None`` — a dataset with no
            parent has nothing to describe how it was derived from.
            This is descriptive metadata only, for the UI to display a
            dataset's history (see :meth:`WorkspaceService.get_lineage`
            below) — it is not a machine-replayable operation record.
            Milestone 3a deliberately stops short of building operation
            replay: doing so now would mean designing a serializable
            transformation-operation format before the Data Cleaning
            milestone exists to define what operations actually look
            like, which is building ahead of a dependency that does
            not exist yet.
    """

    name: str
    dataframe: "pd.DataFrame"
    source_format: str
    source_path: Path | None = None
    row_count: int = field(init=False)
    column_count: int = field(init=False)
    read_warnings: list[str] = field(default_factory=list)
    dataset_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_dataset_id: str | None = None
    derivation_description: str | None = None

    def __post_init__(self) -> None:
        # row_count and column_count are derived, not independently
        # settable — computing them here rather than accepting them as
        # constructor arguments makes it impossible to construct a
        # Dataset whose reported dimensions disagree with its actual
        # dataframe.
        self.row_count = len(self.dataframe)
        self.column_count = len(self.dataframe.columns)


@dataclass
class Visualization:
    """A single visualization, tracked by identity within a session.

    Attributes:
        visualization_id: Unique identifier for this visualization
            within the current session.
        name: Display name for this visualization.
        dataset_id: The :attr:`Dataset.dataset_id` this visualization
            is based on. Stored as a plain string reference rather
            than holding a direct ``Dataset`` object, so that removing
            a dataset from the workspace (see
            :meth:`WorkspaceService.close_dataset`) does not require
            walking every visualization to null out a direct
            reference — callers that need the actual dataset resolve
            it through :meth:`WorkspaceService.get_dataset` using this
            ID.
        figure: The actual chart, as a ``plotly.graph_objects.Figure``
            — populated by milestone 5's chart-building functions (see
            ``src.visualization``). Typed as ``"go.Figure"`` under
            ``TYPE_CHECKING`` only, matching this file's existing
            pattern for ``pd.DataFrame`` on ``Dataset``, since this
            module has no other reason to import
            ``plotly.graph_objects`` at runtime.
        chart_type: Name of the chart class that produced ``figure``
            (e.g. ``"BarChart"``), and
        chart_parameters: the keyword arguments it was built with
            (column names, title, and so on). Recorded so a
            visualization can be rebuilt from its parameters — against
            a since-updated dataset, for instance — rather than only
            existing as a frozen, unreproducible image. Milestone 5b
            does not yet build this "rebuild" feature; these fields
            exist now because they cost nothing to record at creation
            time and are far cheaper to capture here than to
            reconstruct retroactively later.
    """

    name: str
    dataset_id: str
    figure: "go.Figure"
    chart_type: str
    chart_parameters: dict = field(default_factory=dict)
    visualization_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class DashboardTile:
    """One visualization's position within a Dashboard's grid.

    Attributes:
        visualization_id: Which visualization occupies this tile.
        row: 0-indexed grid row.
        column: 0-indexed grid column.
    """

    visualization_id: str
    row: int
    column: int


@dataclass
class Dashboard:
    """An arrangement of existing visualizations into a grid.

    A dashboard does not own or copy its visualizations — it stores
    references (via :class:`DashboardTile`) to
    :class:`Visualization` objects that must already be tracked by
    :class:`WorkspaceService`. This mirrors :class:`Visualization`'s
    own ``dataset_id``-by-reference pattern rather than
    ``dataset``-by-value, for the identical reason: a tile referencing
    a since-closed visualization is a normal, checkable state (see
    :meth:`WorkspaceService.get_dashboard_tiles`), not a corruption to
    guard against by copying data around.

    Attributes:
        name: Display name.
        tiles: The grid arrangement.
        dashboard_id: Unique identifier within the session.
    """

    name: str
    tiles: list[DashboardTile] = field(default_factory=list)
    dashboard_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class WorkspaceService:
    """Tracks loaded datasets and the active dataset/visualization for a session.

    All state here is in-memory and session-scoped — closing the
    application discards it. Persisting "which datasets were open"
    across sessions, if a later milestone wants that, belongs to
    :class:`~src.services.project_service.ProjectService`, which would
    read dataset references back out of a saved project file and
    re-register them here on open, rather than this service gaining
    its own persistence logic.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}
        self._visualizations: dict[str, Visualization] = {}
        self._dashboards: dict[str, Dashboard] = {}
        self._active_dataset_id: str | None = None
        self._active_visualization_id: str | None = None

    # -- Datasets ------------------------------------------------------------

    def add_dataset(self, dataset: Dataset) -> None:
        """Register ``dataset`` as loaded in this workspace.

        Does not change which dataset is active — call
        :meth:`set_active_dataset` explicitly if the newly added
        dataset should become the active one. Kept separate so that
        callers loading several datasets at once (for example,
        restoring a saved project) are not forced to accept whichever
        one happens to load last as implicitly active.

        Raises:
            ServiceError: If ``dataset.parent_dataset_id`` is set but
                does not refer to a currently loaded dataset — matching
                the same referential-integrity check
                :meth:`add_visualization` already performs for its own
                ``dataset_id`` reference, for the same reason: a
                dataset claiming lineage from a parent that is not
                actually in the workspace would be an inconsistent
                state this service refuses to create.
        """
        if (
            dataset.parent_dataset_id is not None
            and dataset.parent_dataset_id not in self._datasets
        ):
            raise ServiceError(
                f"Cannot add dataset '{dataset.name}': its "
                f"parent_dataset_id ({dataset.parent_dataset_id}) is "
                f"not a currently loaded dataset."
            )

        self._datasets[dataset.dataset_id] = dataset
        _logger.info("Added dataset to workspace: %s (%s)", dataset.name, dataset.dataset_id)

    def close_dataset(self, dataset_id: str) -> None:
        """Remove a dataset from the workspace.

        If the closed dataset was active, the active dataset is
        cleared (not reassigned to another loaded dataset — there is
        no well-defined "next" dataset to fall back to, so this
        service makes that an explicit caller decision rather than
        guessing).

        Does NOT cascade to datasets derived from this one. A closed
        parent leaves any children with a ``parent_dataset_id`` that
        no longer resolves — an orphaned reference, not an error
        state. Cascading deletion was considered and rejected: closing
        one dataset silently destroying a user's derived work because
        it happened to be built on top of it is a worse failure mode
        than a dangling lineage reference, which
        :meth:`get_lineage` handles gracefully (see that method).

        Args:
            dataset_id: The :attr:`Dataset.dataset_id` to remove.

        Raises:
            ServiceError: If no dataset with this ID is currently
                loaded.
        """
        if dataset_id not in self._datasets:
            raise ServiceError(f"No dataset loaded with id: {dataset_id}")

        removed = self._datasets.pop(dataset_id)
        if self._active_dataset_id == dataset_id:
            self._active_dataset_id = None
        _logger.info("Closed dataset: %s (%s)", removed.name, dataset_id)

    def get_dataset(self, dataset_id: str) -> Dataset:
        """Return the loaded dataset with ``dataset_id``.

        Raises:
            ServiceError: If no dataset with this ID is currently
                loaded.
        """
        if dataset_id not in self._datasets:
            raise ServiceError(f"No dataset loaded with id: {dataset_id}")
        return self._datasets[dataset_id]

    def get_lineage(self, dataset_id: str) -> list[Dataset]:
        """Return the chain of ancestor datasets for ``dataset_id``, root first.

        Walks ``parent_dataset_id`` links until reaching a dataset
        with no parent. Stops (without raising) if a
        ``parent_dataset_id`` is orphaned — points at a dataset that
        is no longer loaded, per :meth:`close_dataset`'s documented
        non-cascading behavior — since an orphaned ancestor is a
        normal, expected state, not a corruption to fail loudly over.

        Args:
            dataset_id: The dataset to trace lineage for.

        Raises:
            ServiceError: If ``dataset_id`` itself is not currently
                loaded.
        """
        dataset = self.get_dataset(dataset_id)
        chain: list[Dataset] = []
        current = dataset
        while current.parent_dataset_id is not None:
            if current.parent_dataset_id not in self._datasets:
                break  # orphaned ancestor; stop here rather than raise
            current = self._datasets[current.parent_dataset_id]
            chain.append(current)
        chain.reverse()
        return chain

    def get_children(self, dataset_id: str) -> list[Dataset]:
        """Return datasets directly derived from ``dataset_id``.

        Does not raise if ``dataset_id`` is not currently loaded —
        unlike most other methods on this service, checking "what
        points at this ID" is well-defined even if the ID itself is
        stale (for example, checking what would be orphaned before
        closing a dataset).
        """
        return [
            d for d in self._datasets.values() if d.parent_dataset_id == dataset_id
        ]

    def list_datasets(self) -> list[Dataset]:
        """Return all currently loaded datasets."""
        return list(self._datasets.values())

    def set_active_dataset(self, dataset_id: str | None) -> None:
        """Set (or clear, by passing ``None``) the active dataset.

        Raises:
            ServiceError: If ``dataset_id`` is not ``None`` and no
                dataset with that ID is currently loaded — this
                prevents the workspace from ever pointing at a dataset
                that isn't actually tracked.
        """
        if dataset_id is not None and dataset_id not in self._datasets:
            raise ServiceError(
                f"Cannot set active dataset to {dataset_id}: no "
                f"dataset with that id is loaded."
            )
        self._active_dataset_id = dataset_id
        _logger.debug("Active dataset set to: %s", dataset_id)

    def get_active_dataset(self) -> Dataset | None:
        """Return the active dataset, or ``None`` if none is set."""
        if self._active_dataset_id is None:
            return None
        return self._datasets[self._active_dataset_id]

    # -- Visualizations --------------------------------------------------------

    def add_visualization(self, visualization: Visualization) -> None:
        """Register ``visualization`` as part of this workspace.

        Raises:
            ServiceError: If ``visualization.dataset_id`` does not
                refer to a currently loaded dataset — a visualization
                referencing data that isn't in the workspace is an
                inconsistent state this service refuses to create.
        """
        if visualization.dataset_id not in self._datasets:
            raise ServiceError(
                f"Cannot add visualization '{visualization.name}': "
                f"its dataset_id ({visualization.dataset_id}) is not "
                f"a currently loaded dataset."
            )
        self._visualizations[visualization.visualization_id] = visualization
        _logger.info(
            "Added visualization to workspace: %s (%s)",
            visualization.name,
            visualization.visualization_id,
        )

    def close_visualization(self, visualization_id: str) -> None:
        """Remove a visualization from the workspace.

        Raises:
            ServiceError: If no visualization with this ID exists.
        """
        if visualization_id not in self._visualizations:
            raise ServiceError(f"No visualization with id: {visualization_id}")

        removed = self._visualizations.pop(visualization_id)
        if self._active_visualization_id == visualization_id:
            self._active_visualization_id = None
        _logger.info("Closed visualization: %s (%s)", removed.name, visualization_id)

    def get_visualization(self, visualization_id: str) -> Visualization:
        """Return the visualization with ``visualization_id``.

        Raises:
            ServiceError: If no visualization with this ID exists.
        """
        if visualization_id not in self._visualizations:
            raise ServiceError(f"No visualization with id: {visualization_id}")
        return self._visualizations[visualization_id]

    def list_visualizations(self) -> list[Visualization]:
        """Return all currently tracked visualizations."""
        return list(self._visualizations.values())

    def set_active_visualization(self, visualization_id: str | None) -> None:
        """Set (or clear, by passing ``None``) the active visualization.

        Raises:
            ServiceError: If ``visualization_id`` is not ``None`` and
                no visualization with that ID is currently tracked.
        """
        if visualization_id is not None and visualization_id not in self._visualizations:
            raise ServiceError(
                f"Cannot set active visualization to "
                f"{visualization_id}: no visualization with that id "
                f"is tracked."
            )
        self._active_visualization_id = visualization_id
        _logger.debug("Active visualization set to: %s", visualization_id)

    def get_active_visualization(self) -> Visualization | None:
        """Return the active visualization, or ``None`` if none is set."""
        if self._active_visualization_id is None:
            return None
        return self._visualizations[self._active_visualization_id]

    # -- Dashboards ------------------------------------------------------------

    def add_dashboard(self, dashboard: Dashboard) -> None:
        """Register ``dashboard`` in this workspace.

        Raises:
            ServiceError: If any tile's ``visualization_id`` does not
                refer to a currently tracked visualization — matching
                :meth:`add_visualization`'s own referential-integrity
                check against ``dataset_id``, for the identical reason.
        """
        unknown_ids = [
            t.visualization_id
            for t in dashboard.tiles
            if t.visualization_id not in self._visualizations
        ]
        if unknown_ids:
            raise ServiceError(
                f"Cannot add dashboard '{dashboard.name}': tile(s) "
                f"reference visualization_id(s) not currently "
                f"tracked: {', '.join(unknown_ids)}."
            )

        self._dashboards[dashboard.dashboard_id] = dashboard
        _logger.info(
            "Added dashboard to workspace: %s (%s), %d tile(s).",
            dashboard.name,
            dashboard.dashboard_id,
            len(dashboard.tiles),
        )

    def get_dashboard(self, dashboard_id: str) -> Dashboard:
        """Return the dashboard with ``dashboard_id``.

        Raises:
            ServiceError: If no dashboard with this ID is tracked.
        """
        if dashboard_id not in self._dashboards:
            raise ServiceError(f"No dashboard with id: {dashboard_id}")
        return self._dashboards[dashboard_id]

    def list_dashboards(self) -> list[Dashboard]:
        """Return all currently tracked dashboards."""
        return list(self._dashboards.values())

    def close_dashboard(self, dashboard_id: str) -> None:
        """Remove a dashboard from the workspace.

        Raises:
            ServiceError: If no dashboard with this ID is tracked.
        """
        if dashboard_id not in self._dashboards:
            raise ServiceError(f"No dashboard with id: {dashboard_id}")
        removed = self._dashboards.pop(dashboard_id)
        _logger.info("Closed dashboard: %s (%s)", removed.name, dashboard_id)

    def get_dashboard_tiles(self, dashboard_id: str) -> list[tuple[DashboardTile, Visualization | None]]:
        """Return each tile paired with its resolved Visualization, or None if closed.

        Args:
            dashboard_id: Which dashboard to resolve tiles for.

        A tile's visualization can be ``None`` if the referenced
        visualization was closed after the dashboard was created —
        :meth:`add_dashboard` validates references at creation time,
        but nothing in this service prevents a visualization from
        being closed afterward (there is no ``close_visualization``
        cascading guard, matching :meth:`close_dataset`'s own
        documented non-cascading stance). Callers (the dashboard
        rendering code) are expected to handle a ``None`` visualization
        by skipping that tile rather than crashing, the same way
        :meth:`get_lineage` handles an orphaned ``parent_dataset_id``
        by stopping gracefully rather than raising.

        Raises:
            ServiceError: If ``dashboard_id`` itself is not tracked.
        """
        dashboard = self.get_dashboard(dashboard_id)
        return [
            (tile, self._visualizations.get(tile.visualization_id))
            for tile in dashboard.tiles
        ]
