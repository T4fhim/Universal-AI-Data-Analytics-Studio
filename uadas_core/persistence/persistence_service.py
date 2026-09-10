# File: uadas_core/persistence/persistence_service.py
"""The workspace save/load round-trip: SQLite metadata + Parquet frames.

Why this lives in its own package rather than as methods on
:class:`~uadas_core.services.workspace_service.WorkspaceService`:

* ``WorkspaceService`` is a mutable ``bootstrap()`` singleton held by
  ``AssistantService`` and every controller; a save/load that ran *on* it would
  either block the UI thread or race those holders. ``PersistenceService``'s
  verbs instead take plain lists and return a plain
  :class:`WorkspaceSnapshot`, so the desktop shell runs them on a worker thread
  and only touches the singleton (via :meth:`WorkspaceService.load_snapshot`)
  back on the UI thread.
* It imports :mod:`uadas_core.visualization.chart_registry` directly to
  *re-derive* every :class:`~uadas_core.services.workspace_service.Visualization`
  figure on load. Figures are large and are a pure function of
  ``(dataframe, chart_parameters)``; storing them would only create
  stale-figure bugs when the underlying frame changes.

Structural corruption (an unreadable ``.db``, a ``parent_dataset_id`` cycle, a
non-uuid4 ``dataset_id``, a row-count/column-count checksum mismatch, a missing
frame) aborts the whole load with :class:`~uadas_core.core.exceptions.
ServiceError`. A *single* visualization that cannot be rebuilt (its column is
gone, its plugin chart is disabled) is isolated: it is dropped and its id is
returned in :attr:`WorkspaceSnapshot.rebuild_failures`, and the rest of the
project still loads — mirroring ``ProjectController._read_recorded_datasets``'s
per-dataset tolerance rather than an all-or-nothing open.

Every :class:`sqlite3.Error`, :class:`OSError`, and pyarrow
:class:`pyarrow.ArrowException` is caught and re-raised as ``ServiceError`` (the
repo-wide convention — see :mod:`uadas_core.core.exceptions`).
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pyarrow

from uadas_core.core.exceptions import ServiceError
from uadas_core.core.logger import get_logger
from uadas_core.services.workspace_service import (
    Dashboard,
    DashboardTile,
    Dataset,
    Visualization,
)
from uadas_core.visualization import chart_registry

_logger = get_logger(__name__)

# Static DDL. Every value written through these tables goes in as a ``?``
# placeholder (see the INSERT statements below); the only interpolation-looking
# thing here is ``"column"``, a static identifier quoted because ``column`` is a
# SQLite keyword. No FK is declared on ``datasets.parent_dataset_id`` or on
# ``dashboard_tiles.visualization_id`` on purpose: ``close_dataset`` /
# ``close_visualization`` are non-cascading, so a derived dataset whose parent
# was closed, or a tile pointing at a closed visualization, is *normal* state
# that must round-trip — a SQL FK would wrongly reject it on save. The
# ``visualizations.dataset_id`` FK *is* kept: save skips any visualization whose
# dataset is not also being saved (see :meth:`PersistenceService.save_workspace`),
# so that reference is always satisfiable, and it is a functional dependency
# (no frame -> no figure) rather than descriptive lineage.
_SCHEMA = """
CREATE TABLE datasets (
  dataset_id            TEXT PRIMARY KEY,
  name                  TEXT NOT NULL,
  source_path           TEXT,
  source_format         TEXT NOT NULL,
  row_count             INTEGER NOT NULL,
  column_count          INTEGER NOT NULL,
  read_warnings         TEXT NOT NULL,
  parent_dataset_id     TEXT,
  derivation_description TEXT
);
CREATE TABLE visualizations (
  visualization_id  TEXT PRIMARY KEY,
  dataset_id        TEXT NOT NULL,
  name              TEXT NOT NULL,
  chart_type        TEXT NOT NULL,
  chart_parameters  TEXT NOT NULL,
  FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
);
CREATE TABLE dashboards (
  dashboard_id TEXT PRIMARY KEY,
  name         TEXT NOT NULL
);
CREATE TABLE dashboard_tiles (
  tile_id          TEXT PRIMARY KEY,
  dashboard_id     TEXT NOT NULL,
  visualization_id TEXT NOT NULL,
  "row"            INTEGER NOT NULL,
  "column"         INTEGER NOT NULL,
  ordinal          INTEGER NOT NULL,
  FOREIGN KEY (dashboard_id) REFERENCES dashboards(dashboard_id)
);
"""

# A persisted ``dataset_id`` becomes ``{base}/{dataset_id}.parquet``. Anything
# that is not a lowercase uuid4 is rejected *before* that path is built, so a
# hand-edited ``.db`` cannot use the id to escape ``base`` (contract §6.2).
_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

# Errors from ``DataFrame.to_parquet`` / ``pd.read_parquet``. A missing file
# surfaces as ``FileNotFoundError`` (an ``OSError``); a truncated or non-Parquet
# file surfaces as ``pyarrow.ArrowInvalid`` (an ``ArrowException``). Those two
# hierarchies share no common base below ``Exception``, and ``BLE001`` forbids a
# bare ``except Exception`` — hence the explicit tuple rather than a catch-all.
_PARQUET_ERRORS: tuple[type[BaseException], ...] = (
    OSError,
    ValueError,
    pyarrow.ArrowException,
)


class _RebuildFailed(Exception):
    """A single visualization could not be rebuilt.

    Not an :class:`~uadas_core.core.exceptions.ApplicationError`: it is caught
    inside :meth:`PersistenceService.load_workspace`'s per-row loop and turned
    into a :attr:`WorkspaceSnapshot.rebuild_failures` entry. It must never leave
    this module.
    """


@dataclass
class SaveReport:
    """Outcome of :meth:`PersistenceService.save_workspace`.

    Attributes:
        skipped_visualization_ids: Visualizations that were *not* written
            because their ``dataset_id`` is not among the datasets being saved
            (``close_dataset`` is non-cascading, so a live visualization can
            outlive its frame). Sorted. The desktop shell surfaces this the way
            it surfaces skipped datasets — under a full-replace save such a
            visualization is destroyed on the *next* save.
    """

    skipped_visualization_ids: list[str]


@dataclass
class WorkspaceSnapshot:
    """Plain result of :meth:`PersistenceService.load_workspace`.

    Attributes:
        datasets: Topologically ordered, parents before children — so
            :meth:`WorkspaceService.load_snapshot` can install them in order.
        visualizations: Figures already re-derived; excludes any that failed to
            rebuild.
        dashboards: Each with its :class:`DashboardTile`s in ``ordinal`` order;
            a tile's ``visualization_id`` may dangle.
        rebuild_failures: ``visualization_id``s that could not be rebuilt
            (missing column, disabled plugin chart, malformed params). Sorted.
    """

    datasets: list[Dataset]
    visualizations: list[Visualization]
    dashboards: list[Dashboard]
    rebuild_failures: list[str]


class PersistenceService:
    """Stateless workspace serializer. Registered as a ``bootstrap()`` singleton.

    The storage location is a per-call ``base`` directory (the desktop shell
    derives ``<project-stem>.workspace/`` beside the ``.uads.json``), never a
    value this service holds or persists.
    """

    def save_workspace(
        self,
        datasets: list[Dataset],
        visualizations: list[Visualization],
        dashboards: list[Dashboard],
        base: Path,
    ) -> SaveReport:
        """Write ``datasets`` (frames + metadata), ``visualizations``, and
        ``dashboards`` into ``base`` as ``workspace.db`` + ``{id}.parquet`` files.

        Full-replace: the DB is rebuilt from scratch and any ``.parquet`` in
        ``base`` whose stem is not one of the datasets written is deleted
        (garbage from datasets closed since the last save). The DB is built at
        ``workspace.db.tmp`` and ``os.replace``d into place so a crash mid-write
        cannot leave a half-written ``workspace.db``.

        Raises:
            ServiceError: On any filesystem / SQLite / Parquet failure, or if a
                visualization's ``chart_type`` is neither a registered chart
                name nor a known chart class, or if two registered charts share
                a class name (reverse-map would be ambiguous).
        """
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ServiceError(
                f"Could not create workspace directory {base}: {exc}"
            ) from exc

        class_to_name = _class_name_to_registry_name()

        for dataset in datasets:
            if not _UUID4_RE.match(dataset.dataset_id):
                # Symmetry with load's §6.2 check: dataset_id is joined into a
                # filesystem path (``base / f"{id}.parquet"``) below and feeds
                # ``_gc_orphan_parquet``'s saved-id set. Today it is always a
                # uuid4 (contract §8), but a Dataset built with a crafted id
                # would otherwise write outside ``base``.
                raise ServiceError(
                    f"Refusing to save: dataset_id {dataset.dataset_id!r} is not "
                    f"a uuid4 and would be joined into a filesystem path."
                )

        saved_ids = {dataset.dataset_id for dataset in datasets}
        kept_visualizations: list[Visualization] = []
        skipped_visualization_ids: list[str] = []
        for visualization in visualizations:
            if visualization.dataset_id in saved_ids:
                kept_visualizations.append(visualization)
            else:
                skipped_visualization_ids.append(visualization.visualization_id)

        temp_db = base / "workspace.db.tmp"
        # A stale ``.tmp`` from a previously crashed save would make
        # ``executescript(_SCHEMA)`` fail with "table already exists"; drop it
        # first rather than reusing whatever is there.
        try:
            temp_db.unlink(missing_ok=True)
        except OSError as exc:
            raise ServiceError(f"Could not clear stale {temp_db.name}: {exc}") from exc

        try:
            connection = sqlite3.connect(temp_db)
        except sqlite3.Error as exc:
            raise ServiceError(f"Could not open {temp_db} for writing: {exc}") from exc
        try:
            # SQLite ignores FOREIGN KEY clauses unless this is set per-connection.
            # Must precede executescript() (which issues an implicit COMMIT). Save
            # already filters orphan visualizations (kept_visualizations above) and
            # only writes tiles for dashboards being written, so this only bites if
            # that filter logic regresses -- turning a silently inconsistent
            # workspace.db into a loud IntegrityError (caught -> ServiceError below).
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(_SCHEMA)

            dataset_rows = [
                (
                    dataset.dataset_id,
                    dataset.name,
                    (
                        str(dataset.source_path)
                        if dataset.source_path is not None
                        else None
                    ),
                    dataset.source_format,
                    int(dataset.row_count),
                    int(dataset.column_count),
                    json.dumps(list(dataset.read_warnings)),
                    dataset.parent_dataset_id,
                    dataset.derivation_description,
                )
                for dataset in datasets
            ]
            for dataset in datasets:
                _write_parquet_frame(
                    dataset.dataframe, base / f"{dataset.dataset_id}.parquet"
                )
            connection.executemany(
                'INSERT INTO datasets ("dataset_id", "name", "source_path", '
                '"source_format", "row_count", "column_count", "read_warnings", '
                '"parent_dataset_id", "derivation_description") '
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                dataset_rows,
            )

            visualization_rows = [
                (
                    visualization.visualization_id,
                    visualization.dataset_id,
                    visualization.name,
                    _registry_name_for(visualization, class_to_name),
                    json.dumps(visualization.chart_parameters),
                )
                for visualization in kept_visualizations
            ]
            connection.executemany(
                'INSERT INTO visualizations ("visualization_id", "dataset_id", '
                '"name", "chart_type", "chart_parameters") '
                "VALUES (?, ?, ?, ?, ?)",
                visualization_rows,
            )

            dashboard_rows = [
                (dashboard.dashboard_id, dashboard.name) for dashboard in dashboards
            ]
            tile_rows = [
                (
                    tile.tile_id,
                    dashboard.dashboard_id,
                    tile.visualization_id,
                    int(tile.row),
                    int(tile.column),
                    ordinal,
                )
                for dashboard in dashboards
                for ordinal, tile in enumerate(dashboard.tiles)
            ]
            connection.executemany(
                'INSERT INTO dashboards ("dashboard_id", "name") VALUES (?, ?)',
                dashboard_rows,
            )
            connection.executemany(
                'INSERT INTO dashboard_tiles ("tile_id", "dashboard_id", '
                '"visualization_id", "row", "column", "ordinal") '
                "VALUES (?, ?, ?, ?, ?, ?)",
                tile_rows,
            )

            connection.commit()
        except sqlite3.Error as exc:
            raise ServiceError(f"Failed writing workspace database: {exc}") from exc
        finally:
            connection.close()

        _gc_orphan_parquet(base, saved_ids)

        try:
            os.replace(temp_db, base / "workspace.db")
        except OSError as exc:
            raise ServiceError(
                f"Could not commit {temp_db.name} into place: {exc}"
            ) from exc

        _logger.info(
            "Saved workspace to %s: %d dataset(s), %d visualization(s) "
            "(%d skipped), %d dashboard(s).",
            base,
            len(datasets),
            len(kept_visualizations),
            len(skipped_visualization_ids),
            len(dashboards),
        )
        return SaveReport(skipped_visualization_ids=sorted(skipped_visualization_ids))

    def load_workspace(self, base: Path) -> WorkspaceSnapshot:
        """Read ``base`` back into a plain :class:`WorkspaceSnapshot`.

        Pure — touches no :class:`WorkspaceService`. Datasets come back
        topologically ordered; every visualization figure is re-derived through
        :mod:`~uadas_core.visualization.chart_registry` (so this depends on
        ``bootstrap()`` / plugin load having run first — the shell satisfies
        that because open happens well after bootstrap).

        Raises:
            ServiceError: For *structural* corruption — no/unreadable
                ``workspace.db``; a non-uuid4 ``dataset_id``; a missing or
                unreadable ``.parquet``; a row-count/column-count checksum
                mismatch; a ``parent_dataset_id`` cycle. A visualization that
                cannot be rebuilt is *not* raised — it is collected in
                :attr:`WorkspaceSnapshot.rebuild_failures`.
        """
        db_path = base / "workspace.db"
        if not db_path.is_file():
            raise ServiceError(f"No workspace database found at {db_path}.")

        try:
            # Read-only URI connection -- a load must never mutate the file.
            # ``Path.as_uri()`` percent-encodes ``?`` / ``#`` / ``%`` / spaces, so a
            # workspace directory name containing those cannot inject SQLite URI
            # query parameters (``vfs=``, ``mode=rwc``, ...). ``base`` is caller-
            # supplied and never read from the persisted artifact, so this is
            # defense in depth; still cheaper than reasoning about it. (The older
            # uadas_core.readers.sqlite_reader still uses a raw f-string here.)
            connection = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True)
        except sqlite3.Error as exc:
            raise ServiceError(
                f"Could not open workspace database {db_path}: {exc}"
            ) from exc
        try:
            connection.row_factory = sqlite3.Row
            dataset_records = connection.execute(
                'SELECT "dataset_id", "name", "source_path", "source_format", '
                '"row_count", "column_count", "read_warnings", '
                '"parent_dataset_id", "derivation_description" FROM datasets'
            ).fetchall()
            visualization_records = connection.execute(
                'SELECT "visualization_id", "dataset_id", "name", "chart_type", '
                '"chart_parameters" FROM visualizations'
            ).fetchall()
            dashboard_records = connection.execute(
                'SELECT "dashboard_id", "name" FROM dashboards'
            ).fetchall()
            tile_records = connection.execute(
                'SELECT "tile_id", "dashboard_id", "visualization_id", "row", '
                '"column", "ordinal" FROM dashboard_tiles ORDER BY "ordinal"'
            ).fetchall()
        except sqlite3.Error as exc:
            raise ServiceError(
                f"Could not read workspace database {db_path}: {exc}"
            ) from exc
        finally:
            connection.close()

        datasets_by_id: dict[str, Dataset] = {}
        for record in dataset_records:
            dataset_id = record["dataset_id"]
            if not isinstance(dataset_id, str) or not _UUID4_RE.match(dataset_id):
                # Rejected before any ``base / f"{dataset_id}.parquet"`` is built.
                raise ServiceError(
                    f"Refusing to load: dataset_id {dataset_id!r} is not a "
                    f"uuid4 and would be joined into a filesystem path."
                )
            frame = _read_parquet_frame(base / f"{dataset_id}.parquet")
            stored_rows = record["row_count"]
            stored_columns = record["column_count"]
            if stored_rows != len(frame) or stored_columns != len(frame.columns):
                raise ServiceError(
                    f"Dataset {dataset_id}: stored dimensions "
                    f"{stored_rows}x{stored_columns} disagree with the Parquet "
                    f"frame ({len(frame)}x{len(frame.columns)}); the workspace "
                    f"is structurally inconsistent."
                )
            source_path = record["source_path"]
            try:
                stored_warnings = list(json.loads(record["read_warnings"]))
            except (TypeError, ValueError) as exc:
                # Structural corruption (hand-edited .db) -> whole-load abort with
                # the module-standard ServiceError, not a bare JSONDecodeError.
                raise ServiceError(
                    f"Dataset {dataset_id}: read_warnings is not a valid JSON list."
                ) from exc
            datasets_by_id[dataset_id] = Dataset(
                name=record["name"],
                dataframe=frame,
                source_format=record["source_format"],
                source_path=Path(source_path) if source_path is not None else None,
                read_warnings=stored_warnings,
                dataset_id=dataset_id,
                parent_dataset_id=record["parent_dataset_id"],
                derivation_description=record["derivation_description"],
            )

        _reject_parent_dataset_id_cycles(datasets_by_id)
        ordered_datasets = _topological_sort(datasets_by_id)

        rebuilt_visualizations: list[Visualization] = []
        rebuild_failures: list[str] = []
        for record in visualization_records:
            visualization_id = record["visualization_id"]
            try:
                rebuilt_visualizations.append(
                    _rebuild_visualization(record, datasets_by_id)
                )
            except _RebuildFailed as exc:
                _logger.warning(
                    "Visualization %s could not be rebuilt (%s); dropping it "
                    "from the loaded workspace.",
                    visualization_id,
                    exc,
                )
                rebuild_failures.append(visualization_id)

        tiles_by_dashboard: dict[str, list[DashboardTile]] = {}
        for record in tile_records:
            tiles_by_dashboard.setdefault(record["dashboard_id"], []).append(
                DashboardTile(
                    visualization_id=record["visualization_id"],
                    row=record["row"],
                    column=record["column"],
                    tile_id=record["tile_id"],
                )
            )
        rebuilt_dashboards = [
            Dashboard(
                name=record["name"],
                tiles=tiles_by_dashboard.get(record["dashboard_id"], []),
                dashboard_id=record["dashboard_id"],
            )
            for record in dashboard_records
        ]

        _logger.info(
            "Loaded workspace from %s: %d dataset(s), %d visualization(s) "
            "(%d rebuild failure(s)), %d dashboard(s).",
            base,
            len(ordered_datasets),
            len(rebuilt_visualizations),
            len(rebuild_failures),
            len(rebuilt_dashboards),
        )
        return WorkspaceSnapshot(
            datasets=ordered_datasets,
            visualizations=rebuilt_visualizations,
            dashboards=rebuilt_dashboards,
            rebuild_failures=sorted(rebuild_failures),
        )


def _class_name_to_registry_name() -> dict[str, str]:
    """Reverse map ``ChartClass.__name__ -> registry name`` for save-time
    normalisation of a legacy class-name ``chart_type``.

    Raises:
        ServiceError: If two registered charts share a class name — the reverse
            lookup would be ambiguous (contract §2.1 / architect Q3), so this is
            a hard failure on save rather than a silent last-wins.
    """
    mapping: dict[str, str] = {}
    for name, registration in chart_registry.list_charts().items():
        class_name = registration.chart_class.__name__
        if class_name in mapping:
            raise ServiceError(
                f"Cannot persist visualizations: chart classes {mapping[class_name]!r} "
                f"and {name!r} both use the class name {class_name!r}, so "
                f"chart_type normalisation is ambiguous."
            )
        mapping[class_name] = name
    return mapping


def _registry_name_for(
    visualization: Visualization, class_to_name: dict[str, str]
) -> str:
    """Normalise ``visualization.chart_type`` to a registry name (contract §2.1).

    Passthrough if it is already a registry name; else reverse-map it from a
    chart *class* name (the legacy form
    ``create_visualization_dialog.py`` still emits); else fail.
    """
    chart_type = visualization.chart_type
    if chart_type in chart_registry.list_charts():
        return chart_type
    if chart_type in class_to_name:
        return class_to_name[chart_type]
    raise ServiceError(
        f"Visualization {visualization.visualization_id}: chart_type "
        f"{chart_type!r} is neither a registered chart name nor a known chart "
        f"class."
    )


def _write_parquet_frame(dataframe: pd.DataFrame, path: Path) -> None:
    """Write ``dataframe`` to ``path``. ``index=False`` drops any non-default
    index — accepted, because the cleaning operations already
    ``reset_index(drop=True)``.
    """
    try:
        dataframe.to_parquet(path, index=False)
    except _PARQUET_ERRORS as exc:
        raise ServiceError(f"Could not write dataset frame {path.name}: {exc}") from exc


def _read_parquet_frame(path: Path) -> pd.DataFrame:
    """Read ``path`` back into a DataFrame.

    A missing frame is *structural* corruption (the ``.db`` references it but it
    is not there), so this raises rather than returning an empty frame.
    """
    if not path.is_file():
        raise ServiceError(
            f"Dataset frame {path.name} is referenced by the workspace "
            f"database but is missing from disk."
        )
    try:
        return pd.read_parquet(path)
    except _PARQUET_ERRORS as exc:
        raise ServiceError(f"Could not read dataset frame {path.name}: {exc}") from exc


def _reject_parent_dataset_id_cycles(datasets_by_id: dict[str, Dataset]) -> None:
    """Whole-load abort if ``parent_dataset_id`` links form a cycle (contract §1.3).

    Deliberately *not* importing
    :func:`uadas_core.services.workspace_service._reject_parent_cycles`: this
    package must not reach into another module's private API, and the two checks
    guard different boundaries (this one the on-disk ``.db``, that one the
    in-memory restore in :meth:`WorkspaceService.load_snapshot`). A dangling
    ``parent_dataset_id`` (parent absent from the rows) is a clean stop, not a
    cycle — mirrors :meth:`WorkspaceService.get_lineage`.
    """
    for start in datasets_by_id:
        seen = {start}
        path = [start]
        current = datasets_by_id[start].parent_dataset_id
        while current is not None:
            path.append(current)
            if current in seen:
                raise ServiceError(f"parent_dataset_id cycle: {' -> '.join(path)}")
            seen.add(current)
            parent_dataset = datasets_by_id.get(current)
            if parent_dataset is None:
                break  # dangling parent: allowed, stop this walk
            current = parent_dataset.parent_dataset_id


def _topological_sort(datasets_by_id: dict[str, Dataset]) -> list[Dataset]:
    """Return the datasets parents-first (Kahn's algorithm).

    A ``parent_dataset_id`` absent from the map is a dangling reference, not an
    edge, so its child sorts as a root. :func:`_reject_parent_dataset_id_cycles`
    has already run, so the final length check is only belt-and-braces.
    """
    indegree = {dataset_id: 0 for dataset_id in datasets_by_id}
    children: dict[str, list[str]] = {dataset_id: [] for dataset_id in datasets_by_id}
    for dataset_id, dataset in datasets_by_id.items():
        parent = dataset.parent_dataset_id
        if parent is not None and parent in datasets_by_id:
            indegree[dataset_id] += 1
            children[parent].append(dataset_id)

    queue = [dataset_id for dataset_id, degree in indegree.items() if degree == 0]
    ordered: list[str] = []
    while queue:
        current = queue.pop(0)
        ordered.append(current)
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(ordered) != len(datasets_by_id):
        raise ServiceError("parent_dataset_id cycle detected while ordering datasets.")
    return [datasets_by_id[dataset_id] for dataset_id in ordered]


def _rebuild_visualization(
    record: sqlite3.Row, datasets_by_id: dict[str, Dataset]
) -> Visualization:
    """Re-derive one visualization's figure from its stored params (contract §2.2).

    The allow-list is the *real* ``build()`` signature, not the registration's
    column-field tuples: real ``chart_parameters`` also carry ``title`` /
    ``method`` / a stray ``chart_type``, which the column tuples do not name and
    which ``build(**params)`` would choke on. Unknown keys are dropped
    (debug-logged); a missing *required* param, a non-list ``list_fields``
    value, an unknown chart type, non-dict params, or a ``build()`` failure
    (e.g. a column that no longer exists) are per-visualization failures raised
    as :class:`_RebuildFailed`.
    """
    chart_type = record["chart_type"]
    try:
        registration = chart_registry.get_chart(chart_type)
    except ServiceError as exc:
        raise _RebuildFailed(f"unknown chart type {chart_type!r}") from exc

    try:
        raw = json.loads(record["chart_parameters"])
    except (json.JSONDecodeError, TypeError) as exc:
        raise _RebuildFailed("chart_parameters is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise _RebuildFailed("chart_parameters is not a JSON object")

    # ``chart_type`` is never a build() argument; drop it unconditionally.
    raw.pop("chart_type", None)

    signature = inspect.signature(registration.chart_class.build)
    if any(
        parameter.kind is parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        # A plugin ``build(**kwargs)`` (no built-in has one): fall back to the
        # registration's declared fields plus the near-universal ``title``.
        accepted = (
            set(registration.required_fields)
            | set(registration.optional_fields)
            | {"title"}
        )
        required = set(registration.required_fields)
    else:
        accepted = set(signature.parameters) - {"cls", "dataframe"}
        required = {
            name
            for name in accepted
            if signature.parameters[name].default is inspect.Parameter.empty
        }

    filtered = {key: value for key, value in raw.items() if key in accepted}
    dropped = set(raw) - set(filtered)
    if dropped:
        _logger.debug(
            "Visualization %s: dropped unknown build param(s) %s.",
            record["visualization_id"],
            sorted(dropped),
        )

    missing = required - filtered.keys()
    if missing:
        raise _RebuildFailed(f"missing required build param(s): {sorted(missing)}")
    for list_field in registration.list_fields:
        if list_field in filtered and not isinstance(filtered[list_field], list):
            raise _RebuildFailed(f"{list_field!r} must be a list of column names")

    dataset = datasets_by_id.get(record["dataset_id"])
    if dataset is None:
        # The kept FK makes this unreachable for a well-formed .db; a
        # hand-edited dangling dataset_id is a per-viz failure, not a load abort.
        raise _RebuildFailed(f"dataset_id {record['dataset_id']!r} is not loaded")

    try:
        figure = registration.chart_class.build(dataset.dataframe, **filtered)
    except Exception as exc:
        # Contract §2.2: a build() failure for ONE visualization is collected into
        # WorkspaceSnapshot.rebuild_failures, never raised -- one stale chart must
        # not stop the whole project opening. build() is chart_class code (a
        # built-in or a *plugin* chart) and can raise anything: a KeyError on a
        # renamed/dropped column, a ValueError from pandas/plotly, an
        # AttributeError, or a plugin's own exception type. A narrow
        # `except ServiceError` here silently reclassified every other exception
        # as a whole-load abort (end-of-range review, HIGH). _RebuildFailed never
        # leaves this module.
        raise _RebuildFailed(f"build() failed: {exc!r}") from exc

    return Visualization(
        name=record["name"],
        dataset_id=record["dataset_id"],
        figure=figure,
        chart_type=chart_type,
        # `filtered`, not `raw`: unknown/noise keys (a stray `method`, a
        # `title` on a chart whose build() has no such parameter) are dropped
        # from the round-tripped object too, not just from the build() call --
        # otherwise they persist forever across save/load cycles (contract §2.3).
        chart_parameters=filtered,
        visualization_id=record["visualization_id"],
    )


def _gc_orphan_parquet(base: Path, saved_ids: set[str]) -> None:
    """Delete every ``*.parquet`` in ``base`` whose stem is not a saved
    ``dataset_id`` — frames for datasets closed since the last save (contract §5.3).
    """
    try:
        stale = [path for path in base.glob("*.parquet") if path.stem not in saved_ids]
        for path in stale:
            path.unlink()
    except OSError as exc:
        raise ServiceError(
            f"Could not garbage-collect orphaned Parquet frames in {base}: {exc}"
        ) from exc
