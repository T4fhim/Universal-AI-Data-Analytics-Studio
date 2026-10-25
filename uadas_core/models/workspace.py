# File: uadas_core/models/workspace.py
"""The Qt-free, service-free value types a workspace session is built from.

Extracted from :mod:`uadas_core.services.workspace_service` in the
desktop->web transition's Phase 2.2 (D1) -- these four dataclasses carry no
service-layer behaviour and no Qt dependency, so nothing about them requires
living next to
:class:`~uadas_core.services.workspace_service.WorkspaceService`, and keeping
them here is what lets
:class:`~uadas_core.services.workspace_service.WorkspaceService` sit at a
*higher* layer than :mod:`uadas_core.core` in the dependency stack (see the
``layers`` import-linter contract, Phase 2.3) -- a service class can depend
on its own value types without those value types depending back on the
service.

:class:`Dataset`, :class:`Visualization`, :class:`DashboardTile`, and
:class:`Dashboard` are one concept split into four classes (a dashboard is a
grid of tiles referencing visualizations referencing datasets), so they stay
in one file rather than three -- see :mod:`uadas_core.models` (this
package's ``__init__``) for why every call site imports from there, not from
here directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd
    import plotly.graph_objects as go


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
            :class:`~uadas_core.readers.base_reader.BaseReader`.
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
            dataset's history (see :meth:`~uadas_core.services.workspace_service.WorkspaceService.get_lineage`
            below) — it is not a machine-replayable operation record.
            Milestone 3a deliberately stops short of building operation
            replay: doing so now would mean designing a serializable
            transformation-operation format before the Data Cleaning
            milestone exists to define what operations actually look
            like, which is building ahead of a dependency that does
            not exist yet.
    """

    name: str
    dataframe: pd.DataFrame
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
            :meth:`~uadas_core.services.workspace_service.WorkspaceService.close_dataset`) does not require
            walking every visualization to null out a direct
            reference — callers that need the actual dataset resolve
            it through :meth:`~uadas_core.services.workspace_service.WorkspaceService.get_dataset` using this
            ID.
        figure: The actual chart, as a ``plotly.graph_objects.Figure``
            — populated by milestone 5's chart-building functions (see
            ``uadas_core.visualization``). Typed as ``"go.Figure"`` under
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
    figure: go.Figure
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
        tile_id: Stable identity for this tile row, used by the
            persistence layer (Phase 1.6) as the ``dashboard_tiles``
            primary key. Auto-generated; callers never set it. Added as
            a trailing field with a default so every existing
            ``DashboardTile(...)`` call site (all keyword-based) keeps
            working unchanged.
    """

    visualization_id: str
    row: int
    column: int
    tile_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Dashboard:
    """An arrangement of existing visualizations into a grid.

    A dashboard does not own or copy its visualizations — it stores
    references (via :class:`DashboardTile`) to
    :class:`Visualization` objects that must already be tracked by
    :class:`~uadas_core.services.workspace_service.WorkspaceService`. This mirrors :class:`Visualization`'s
    own ``dataset_id``-by-reference pattern rather than
    ``dataset``-by-value, for the identical reason: a tile referencing
    a since-closed visualization is a normal, checkable state (see
    :meth:`~uadas_core.services.workspace_service.WorkspaceService.get_dashboard_tiles`), not a corruption to
    guard against by copying data around.

    Attributes:
        name: Display name.
        tiles: The grid arrangement.
        dashboard_id: Unique identifier within the session.
    """

    name: str
    tiles: list[DashboardTile] = field(default_factory=list)
    dashboard_id: str = field(default_factory=lambda: str(uuid.uuid4()))
