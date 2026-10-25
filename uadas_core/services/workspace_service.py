# File: uadas_core/services/workspace_service.py
"""Session-scoped tracking of loaded datasets and the active visualization.

:class:`WorkspaceService` answers "what data is currently loaded, and
what is the user currently looking at" for a running session. It does
not read files or parse formats itself — that is
:mod:`uadas_core.readers`'s job (see milestone 2a onward) — but as of
milestone 2a, :class:`~uadas_core.models.Dataset` now holds the actual
loaded data a reader produced, not just a name and source path. This
service's own job is unchanged: bookkeeping over datasets someone else
produced, not producing them itself.

The :class:`~uadas_core.models.Visualization` class remains deliberately
minimal, for the same reason :class:`~uadas_core.models.Dataset` was
minimal until this milestone: nothing in the codebase yet produces a
visualization, so there is nothing real to extend it with.
:class:`~uadas_core.models.Dataset` is no longer in that position —
milestone 2a's readers are its producer, so it is extended here rather
than staying a placeholder past the point where a placeholder is
honest. (Phase 2.2 moved :class:`~uadas_core.models.Dataset` and
:class:`~uadas_core.models.Visualization` themselves to
:mod:`uadas_core.models` — this module still owns the service that
tracks them.)
"""

from __future__ import annotations

from uadas_core.core.exceptions import ServiceError
from uadas_core.core.logger import get_logger
from uadas_core.models import Dashboard, DashboardTile, Dataset, Visualization

_logger = get_logger(__name__)


def _reject_parent_cycles(datasets: list[Dataset]) -> None:
    """Raise :class:`ServiceError` if ``parent_dataset_id`` links form a cycle.

    Used by :meth:`WorkspaceService.load_snapshot` (the restore path) rather
    than by :meth:`WorkspaceService.add_dataset`: an interactive caller cannot
    realistically build a cycle one ``add_dataset`` at a time, but a
    hand-edited persisted workspace can, so the check belongs on the load
    boundary. A ``parent_dataset_id`` that is not among ``datasets`` is a
    *dangling* reference, not a cycle — it is a clean stop (mirrors
    :meth:`get_lineage`'s own non-cascading tolerance), so only a *revisited*
    id is an error.
    """
    parents: dict[str, str | None] = {
        d.dataset_id: d.parent_dataset_id for d in datasets
    }
    for start in parents:
        seen: set[str] = {start}
        path: list[str] = [start]
        current = parents[start]
        while current is not None:
            path.append(current)
            if current in seen:
                raise ServiceError(f"parent_dataset_id cycle: {' -> '.join(path)}")
            seen.add(current)
            if current not in parents:
                break  # dangling parent: allowed, stop this walk
            current = parents[current]


class WorkspaceService:
    """Tracks loaded datasets and the active dataset/visualization for a session.

    All state here is in-memory and session-scoped — closing the
    application discards it. Persisting "which datasets were open"
    across sessions, if a later milestone wants that, belongs to
    :class:`~uadas_core.services.project_service.ProjectService`, which would
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

    # -- Restore -----------------------------------------------------------

    def load_snapshot(
        self,
        datasets: list[Dataset],
        visualizations: list[Visualization],
        dashboards: list[Dashboard],
    ) -> None:
        """Replace all workspace state with a restored snapshot.

        The restore peer of :meth:`add_dataset` / :meth:`add_visualization` /
        :meth:`add_dashboard`. Those reject dangling references because an
        interactive caller creating one is a bug; a *persisted* dangling
        ``parent_dataset_id`` or tile ``visualization_id`` is normal
        (:meth:`close_dataset` / :meth:`close_visualization` are
        non-cascading — see their docstrings), so this path installs the
        three lists as-is rather than re-running those referential-integrity
        checks. It still rejects a ``parent_dataset_id`` *cycle* (via
        :func:`_reject_parent_cycles`), which is only reachable through a
        hand-edited persisted workspace. ``datasets`` order is *not* a
        correctness precondition — the three lists become dicts keyed by id —
        but ``self._datasets`` keeps ``datasets``' insertion order, so a caller
        that wants parents-before-children in the Dataset Explorer should pass
        them that way (:class:`~uadas_core.persistence.persistence_service.PersistenceService`
        already topologically sorts on load). Active dataset / visualization are
        cleared — a restored snapshot does not persist the session's selection.
        """
        _reject_parent_cycles(datasets)
        self._datasets = {d.dataset_id: d for d in datasets}
        self._visualizations = {v.visualization_id: v for v in visualizations}
        self._dashboards = {d.dashboard_id: d for d in dashboards}
        self._active_dataset_id = None
        self._active_visualization_id = None
        _logger.info(
            "Restored workspace snapshot: %d dataset(s), %d visualization(s), "
            "%d dashboard(s).",
            len(self._datasets),
            len(self._visualizations),
            len(self._dashboards),
        )

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
        _logger.info(
            "Added dataset to workspace: %s (%s)", dataset.name, dataset.dataset_id
        )

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
            dataset_id: The :attr:`~uadas_core.models.Dataset.dataset_id` to remove.

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
        return [d for d in self._datasets.values() if d.parent_dataset_id == dataset_id]

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
        if (
            visualization_id is not None
            and visualization_id not in self._visualizations
        ):
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

    def get_dashboard_tiles(
        self, dashboard_id: str
    ) -> list[tuple[DashboardTile, Visualization | None]]:
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
