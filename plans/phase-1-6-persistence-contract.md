# Phase 1.6 — Persistence Contract

**Status:** R0.4 design doc · produced 2026-09-07 (architect) · **needs reviewer + `security-reviewer` sign-off before any 1.6 code** (Gate verdict).

**Purpose.** Define the save/load round-trip contract for datasets (incl. *derived* datasets),
visualizations, and dashboards — and the test that proves it. The current code
(`src/services/project_service.py:278-292`) persists only `{name, source_path}` per dataset and
**explicitly skips derived datasets** (`if dataset.source_path is None: … not yet persistable`).
1.6 closes that gap. Additive: a serialization layer *alongside* `WorkspaceService`, changing
no existing behavior for existing callers.

---

## 1. `Dataset` → on-disk form

Field source: `src/services/workspace_service.py:102-111`.

### 1.1 DataFrame → Parquet

- **Key:** `{base}/{dataset_id}.parquet` where `dataset_id` is the UUID from
  `Dataset.dataset_id` (`field(default_factory=lambda: str(uuid.uuid4()))`, line 109).
  Derived from `dataset_id`, **never from `name`** — `name` is user-editable and a
  path-traversal / object-key-injection surface (matters now for the filesystem, more in
  Phase 3 with object storage). `security-reviewer` checks this (Control C-5).
- **Write:** `dataframe.to_parquet(path, index=False)` (pyarrow/fastparquet, both already deps).
- **Read:** `pd.read_parquet(path)` (mirrors the existing `ParquetReader`,
  `src/readers/parquet_reader.py`).

### 1.2 Metadata row — SQLite table `datasets`

```sql
CREATE TABLE datasets (
  dataset_id            TEXT PRIMARY KEY,   -- UUID; == the .parquet filename stem
  name                  TEXT NOT NULL,      -- Dataset.name
  source_path           TEXT,               -- Dataset.source_path; NULL for derived datasets
  source_format         TEXT NOT NULL,      -- Dataset.source_format ("csv"|"json"|"parquet"|…)
  row_count             INTEGER NOT NULL,   -- Dataset.row_count  (invariant: == len(df) on load)
  column_count          INTEGER NOT NULL,   -- Dataset.column_count (invariant: == len(df.columns))
  read_warnings         TEXT NOT NULL,      -- JSON array of strings; "[]" when empty
  parent_dataset_id     TEXT,               -- Dataset.parent_dataset_id; NULL if root
  derivation_description TEXT,              -- Dataset.derivation_description; NULL iff parent is NULL
  FOREIGN KEY (parent_dataset_id) REFERENCES datasets(dataset_id)
);
```

**The fix:** rows with `parent_dataset_id IS NOT NULL` are persisted *in full* — DataFrame as
Parquet **and** metadata — so lineage survives a round trip. `add_dataset`
(`workspace_service.py:249-257`) currently checks only that the parent exists; 1.6 adds an
**acyclic-chain check** on `parent_dataset_id` before persistence.

---

## 2. `Visualization` → record (figure NOT stored)

Field source: `src/services/workspace_service.py:160-165`.

```sql
CREATE TABLE visualizations (
  visualization_id  TEXT PRIMARY KEY,   -- Visualization.visualization_id (UUID)
  dataset_id        TEXT NOT NULL,      -- Visualization.dataset_id
  name              TEXT NOT NULL,      -- Visualization.name
  chart_type        TEXT NOT NULL,      -- Visualization.chart_type ("BarChart"|"LineChart"|…)
  chart_parameters  TEXT NOT NULL,      -- Visualization.chart_parameters, JSON dict
  FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
);
```

`Visualization.figure` (`go.Figure`, line 162) is **re-derived on load**:
`chart_registry.get(chart_type).build(dataset.dataframe, **chart_parameters)`. Rationale:
figures are large, are a pure function of (data + params), and storing them creates
stale-figure bugs.

---

## 3. `Dashboard` / `DashboardTile` → relational

Field source: `src/services/workspace_service.py:178-205`.

```sql
CREATE TABLE dashboards (
  dashboard_id TEXT PRIMARY KEY,        -- Dashboard.dashboard_id (UUID)
  name         TEXT NOT NULL            -- Dashboard.name
);
CREATE TABLE dashboard_tiles (
  tile_id          TEXT PRIMARY KEY,    -- new in 1.6 (row identity for the tile)
  dashboard_id     TEXT NOT NULL,       -- parent Dashboard
  visualization_id TEXT NOT NULL,       -- DashboardTile.visualization_id
  row              INTEGER NOT NULL,    -- DashboardTile.row  (0-indexed)
  column           INTEGER NOT NULL,    -- DashboardTile.column (0-indexed)
  ordinal          INTEGER NOT NULL,    -- position within Dashboard.tiles (list order)
  FOREIGN KEY (dashboard_id) REFERENCES dashboards(dashboard_id)
  -- NOTE: deliberately NO FK on visualization_id (see below)
);
```

**Non-cascading rule (CLAUDE.md / `workspace_service.py:274-280`):** closing a visualization
does not delete tiles that point at it. A tile with a dangling `visualization_id` is *normal
state*, must survive the round trip, and is resolved leniently at render time
(`get_dashboard_tiles` returns what it can). Hence no FK on `visualization_id`.

---

## 4. Save → load round-trip contract (the C-3 test, written first, red→green)

```python
def test_workspace_round_trips_including_a_derived_dataset(tmp_path):
    ws1 = WorkspaceService()

    root = Dataset(name="sales", dataframe=pd.DataFrame({"region": ["e", "w"], "rev": [100, 200]}),
                   source_format="csv", source_path=Path("data/sales.csv"))
    ws1.add_dataset(root)

    derived = Dataset(name="sales_clean", dataframe=root.dataframe.dropna(),
                      source_format="csv", source_path=None,
                      parent_dataset_id=root.dataset_id,
                      derivation_description="dropped null rows")
    ws1.add_dataset(derived)

    fig = BarChart.build(derived.dataframe, category_column="region", value_column="rev")
    viz = Visualization(name="by region", dataset_id=derived.dataset_id, figure=fig,
                        chart_type="BarChart",
                        chart_parameters={"category_column": "region", "value_column": "rev"})
    ws1.add_visualization(viz)

    dash = Dashboard(name="Q4", tiles=[DashboardTile(visualization_id=viz.visualization_id,
                                                     row=0, column=0)])
    ws1.add_dashboard(dash)

    PersistenceLayer(tmp_path).save_workspace(ws1)
    ws2 = PersistenceLayer(tmp_path).load_workspace()

    r2 = ws2.get_dataset(root.dataset_id)
    assert (r2.name, r2.dataset_id, r2.source_path) == (root.name, root.dataset_id, root.source_path)
    assert r2.row_count == root.row_count and r2.column_count == root.column_count
    assert r2.dataframe.equals(root.dataframe)
    assert r2.parent_dataset_id is None

    d2 = ws2.get_dataset(derived.dataset_id)                 # <-- currently dropped entirely
    assert d2.dataframe.equals(derived.dataframe)
    assert d2.source_path is None
    assert d2.parent_dataset_id == root.dataset_id           # <-- lineage preserved
    assert d2.derivation_description == "dropped null rows"

    v2 = ws2.get_visualization(viz.visualization_id)
    assert (v2.chart_type, v2.chart_parameters) == (viz.chart_type, viz.chart_parameters)
    assert v2.figure is not None and len(v2.figure.data) > 0   # re-derived

    t2, _ = ws2.get_dashboard_tiles(dash.dashboard_id)
    assert (t2[0].visualization_id, t2[0].row, t2[0].column) == (viz.visualization_id, 0, 0)
```

**Equality semantics:** scalars `==`; DataFrames `DataFrame.equals()` (NaN-safe, value-wise);
figures `fig.to_json() == fig.to_json()` on a rebuild (structure, not identity); collections
list/dict `==`; nullable fields both-None-or-both-equal.

---

## 5. Storage substrate

**1.6 (desktop):** SQLite file `projects/<project>.db` beside the existing `.uads.json`;
Parquet under `projects/<project>_data/<dataset_id>.parquet`. Local filesystem only.
**Phase 3 (web):** metadata → Postgres (per-tenant), frames → S3-compatible object store
(MinIO local, S3/R2 prod), key `datasets/<tenant_id>/<dataset_id>.parquet`.

**New module:** `uadas_core/persistence/persistence_service.py` (post-1.1 location).
`ProjectService` calls into it on open/save; the desktop shell wires open→`load_workspace()`,
save→`save_workspace()`. Full-replace write (no deltas).

---

## 6. Scope fence — NOT in 1.6

Remote object storage · incremental/delta save · version history / restore-points ·
compression or encryption beyond Parquet's own · chunked/streaming DataFrames · multi-writer
concurrency / ACID beyond SQLite's default · chart_type rename/removal migration ·
AnalysisLog / Recipe persistence (that's 1.7). Anything here is rejected in review.

---

## `## Unverified`

- `dataset_id` is *always* a `uuid4()` today (line 109) → keys are traversal-safe. If any
  future path lets a caller supply a custom `dataset_id`, the key derivation must sanitize.
- Figure re-derivation assumes the dataset's column names/dtypes are stable between save and
  load; 1.6 does not validate a chart's params still match its dataset.
- SQLite file-locking edge cases on Windows network shares / with AV interference — assumed
  out of scope for local-desktop use; Phase 3's Postgres removes the concern.
- `chart_parameters` may nest dicts (advanced Plotly config); JSON round-trip assumed lossless
  for JSON-native types only.
- Acyclic `parent_dataset_id`: `add_dataset` does not check today; 1.6 must add it. Whether any
  existing fixture builds a cycle is unverified.
- Column-order: Parquet preserves it; params look up by name, so a reorder is cosmetically
  visible but not breaking. Accepted.

---

## Multi-file touchpoints

`uadas_core/services/workspace_service.py` (acyclic check in `add_dataset`, no dataclass
change) · `uadas_core/services/project_service.py` (call into persistence; stop skipping
derived) · desktop shell open/save wiring · **new** `uadas_core/persistence/` ·
`tests/persistence/test_persistence_service.py` (the C-3 round-trip).
