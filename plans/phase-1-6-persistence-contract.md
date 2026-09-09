# Phase 1.6 — Persistence Contract

**Status:** R0.4 design doc · produced 2026-09-07 (architect) · R0.4 sign-off 2026-09-08
(`code-reviewer` = APPROVE-WITH-CHANGES · `security-reviewer` = APPROVE-WITH-CHANGES) ·
**R0.4 changes FOLDED IN 2026-09-09** (this revision). The §0 disposition table maps every
review item to where it now lives. Ready for the executable plan + implementation once an
`ecc:architect` (opus, non-author) pass confirms this revision is implementation-ready.

**Purpose.** Define the save/load round-trip contract for datasets (including *derived*
datasets), visualizations, and dashboards — and the characterization test (Control C-3) that
proves it. The current code (`uadas_core/services/project_service.py:285-302`,
`record_datasets`) persists only `{name, source_path}` per dataset and **explicitly skips
derived datasets** (`if dataset.source_path is None: … skipped`, line 288). 1.6 closes that
gap with a serialization layer *alongside* `WorkspaceService` — additive, changing no existing
behaviour for existing callers except the two documented dataclass/guard changes in §9.

---

## §0. R0.4 review-item disposition

| # | Source | Item | Where addressed in this revision |
|---|---|---|---|
| 1 | code-reviewer | Re-verify every `file:line` citation against the current `uadas_core/` tree | Done throughout; verified 2026-09-09 against HEAD `a0442e0`. Key ones: `Dataset` fields `workspace_service.py:102-111`; `Visualization` `:160-165`; `DashboardTile` `:168-181` (fields `:178-180`); `Dashboard` `:183-206`; `add_dataset` parent check `:249-257`; `close_dataset` non-cascade docstring `:273-280`; `record_datasets` skip `project_service.py:287-293` (the `source_path is None` test is line 288); `chart_registry.get_chart` `:129`; `ChartRegistration` `:41-81`. |
| 2 | code-reviewer | **BLOCKING** — `DashboardTile` has no `tile_id` | §3 + §9. Add `tile_id: str = field(default_factory=lambda: str(uuid.uuid4()))` as a **trailing** field on the dataclass (`workspace_service.py`). Verified every `DashboardTile(...)` call site (2: `visualization_controller.py:183`, `tests/ui/controllers/test_visualization_controller.py:78`) uses keyword args, so a trailing defaulted field is backward-compatible. |
| 3 | code-reviewer | Figure re-derivation API — state it exactly | §2.2. Real call: `chart_registry.get_chart(<registry_name>).chart_class.build(dataframe, **chart_parameters)` (`get_chart` is module-level, `chart_registry.py:129`; `chart_class` is `ChartRegistration.chart_class`, `:77`). **1.3 kept `chart_registry` as module-level functions (did NOT convert it to a container instance — startup-graph §7d), so the persistence layer imports it directly** (a Qt-free `uadas_core` peer; `lint-imports` clean; already imported by the `linux_import` CI job). No injection. |
| 4 | code-reviewer | Acyclic `parent_dataset_id` — verify precondition, decide fixture-fix vs graceful | §1.3. Verified precondition: no existing fixture/project builds a `parent_dataset_id` cycle (in-session cycles are already unconstructible via `add_dataset` alone — it requires the parent to be loaded first — so a cycle needs post-hoc `.parent_dataset_id` mutation or a corrupt `.db`). Decision: **two guards** — (a) a cheap forward check in `add_dataset` (walk ancestors of the proposed parent; if the new `dataset_id` appears, raise `ServiceError`), (b) the loader validates the full chain and raises a clear `ServiceError` on any cycle (defends a hand-edited/corrupt `.db`). Not a silent failure either way. |
| 5 | code-reviewer | Strengthen C-3 assertion to structural figure round-trip | §4. `v2.figure.to_json() == fig.to_json()` (rebuild vs original), not "figure is not None". |
| 6 | code-reviewer | FK on `parent_dataset_id` vs non-cascading model | §1.2. **Option A** — **drop** the `parent_dataset_id` FK; a derived dataset whose parent was closed is normal state (matches `close_dataset`'s documented non-cascade) and is still fully persistable (own frame + metadata). Comment in the DDL. |
| 7 | security-reviewer | **CRITICAL** — mandate parameterized SQL | §6.1. Absolute rule: `sqlite3` `?` placeholders only; never f-string / `%` / `.format` / `+` into SQL text. B608 is `--skip`ped in CI so this review + the security-reviewer×2 gate are the only SQL checks. |
| 8 | security-reviewer | **HIGH** — validate `dataset_id` is uuid4 before path-join on load | §6.2. Loader rejects any `dataset_id` that is not a canonical uuid4 string *before* it is joined into a Parquet path. Base dir is caller-supplied (constructor arg), never read from a row. |
| 9 | security-reviewer | Validate `chart_parameters` on load | §2.3. Keys must be a subset of the `ChartRegistration`'s `required_fields ∪ optional_fields`; every `list_fields` value must be a `list`; every `required_fields` key must be present; unknown `chart_type` raises (`get_chart` already does). |
| 10 | security-reviewer | pyarrow/fastparquet minimum versions | §6.3. Delegated to `requirements.txt` (both already listed, unpinned) with a note: Parquet deserialisation is a CVE class; keep current. 1.6 does not itself pin (a repo-wide pin decision, out of scope). |
| 11 | security-reviewer | Load behaviour when a persisted chart's columns no longer exist | §2.2. **Hard error** — `ServiceError` naming the `visualization_id`, `chart_type`, and the missing column parameter(s). No silent degrade. |
| 12 | security-reviewer | State the single-threaded SQLite + local-storage assumption | §6.4. |
| 13 | security-reviewer | Extend C-3 with a cycle-creation case that must be rejected | §4 (second test, `test_load_rejects_a_parent_dataset_id_cycle`). |

**Additional issue found while folding (2026-09-09), not in the review list:**

`Visualization.chart_type` is stored **inconsistently** across the current tree:
`src/ui/dialogs/create_visualization_dialog.py:238` writes `builder_class.__name__` (a *class*
name, e.g. `"BarChart"`), while `src/ui/workbench/pages/visualize_page.py:439`,
`uadas_core/ai/assistant_service.py:483`, `uadas_core/services/analysis_orchestrator_service.py:427`
and `uadas_core/visualization/chart_recommender.py` all write the *registry* name (e.g.
`"bar"`). `chart_registry.get_chart()` only accepts registry names. **Resolution (§2.1):** the
persistence layer **normalises `chart_type` to the registry name on save** — if the stored
value is not already a registry key, reverse-look-up by `chart_class.__name__` over
`list_charts()`; if it matches neither, raise `ServiceError` on save naming the value. On load
the value is always a registry name.

---

## 1. `Dataset` → on-disk form

Field source: `uadas_core/services/workspace_service.py:102-111`.

### 1.1 DataFrame → Parquet

- **Key:** `{base}/{dataset_id}.parquet`, where `dataset_id` is the uuid4 from
  `Dataset.dataset_id` (`field(default_factory=lambda: str(uuid.uuid4()))`, line 109).
  Derived from `dataset_id`, **never from `name`** — `name` is user-editable and a
  path-traversal / object-key-injection surface (matters now for the filesystem; more in
  Phase 3 with object storage).
- **Write:** `dataframe.to_parquet(path, index=False)` (pyarrow/fastparquet — both deps).
- **Read:** `pd.read_parquet(path)` (mirrors `uadas_core/readers/parquet_reader.py`).
- **`base` is caller-constrained:** the `PersistenceService` constructor takes the base
  directory; nothing derives it from a persisted row (§6.2).

### 1.2 Metadata row — SQLite table `datasets`

```sql
CREATE TABLE datasets (
  dataset_id            TEXT PRIMARY KEY,   -- uuid4; == the .parquet filename stem
  name                  TEXT NOT NULL,      -- Dataset.name
  source_path           TEXT,               -- Dataset.source_path; NULL for derived datasets
  source_format         TEXT NOT NULL,      -- Dataset.source_format ("csv"|"json"|"parquet"|…)
  row_count             INTEGER NOT NULL,   -- Dataset.row_count  (invariant: == len(df) on load)
  column_count          INTEGER NOT NULL,   -- Dataset.column_count (invariant: == len(df.columns))
  read_warnings         TEXT NOT NULL,      -- JSON array of strings; "[]" when empty
  parent_dataset_id     TEXT,               -- Dataset.parent_dataset_id; NULL if root
  derivation_description TEXT               -- Dataset.derivation_description; NULL iff parent is NULL
  -- NO FOREIGN KEY on parent_dataset_id (R0.4 item 6, Option A): close_dataset() does not
  -- cascade, so a derived dataset whose parent has been closed is normal, expected state.
  -- It is still persisted in full (frame + metadata); a SQL FK would wrongly reject it.
);
```

Rows with `parent_dataset_id IS NOT NULL` are persisted **in full** — DataFrame as Parquet
*and* metadata — so lineage survives a round trip (this is the core gap 1.6 closes;
`record_datasets` currently drops them).

### 1.3 Acyclic `parent_dataset_id`

- **Precondition (verified 2026-09-09):** no current fixture or checked-in project builds a
  `parent_dataset_id` cycle. `add_dataset` (`workspace_service.py:249-257`) today only checks
  the parent is loaded; a cycle cannot be built by `add_dataset` calls alone (the parent must
  exist first), so today's only cycle routes are post-hoc `.parent_dataset_id` mutation or a
  corrupt `.db`.
- **Guard (a) — `add_dataset`:** before inserting, walk the ancestor chain from
  `dataset.parent_dataset_id`; if `dataset.dataset_id` is reached, raise
  `ServiceError("… would create a parent_dataset_id cycle")`. O(depth), no dataclass change.
- **Guard (b) — loader:** after reading all `datasets` rows, validate the `parent_dataset_id`
  graph is acyclic; on a cycle raise `ServiceError` naming the ids in the cycle. The workspace
  is not partially populated (fail the whole `load_workspace`).

---

## 2. `Visualization` → record (figure NOT stored, re-derived on load)

Field source: `uadas_core/services/workspace_service.py:160-165`.

```sql
CREATE TABLE visualizations (
  visualization_id  TEXT PRIMARY KEY,   -- Visualization.visualization_id (uuid4)
  dataset_id        TEXT NOT NULL,      -- Visualization.dataset_id (saved set only; see 2.4)
  name              TEXT NOT NULL,      -- Visualization.name
  chart_type        TEXT NOT NULL,      -- registry name AFTER normalisation (see 2.1), e.g. "bar"
  chart_parameters  TEXT NOT NULL,      -- Visualization.chart_parameters, JSON object
  FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
  -- FK kept: save excludes any visualization whose dataset_id is not in the saved set
  -- (§2.4), so this reference is always satisfiable on load.
);
```

### 2.1 `chart_type` normalisation on save

`chart_type` in a live `Visualization` is either a registry name (`"bar"`, from VisualizePage
/ AI / orchestrator / recommender) or a chart *class* name (`"BarChart"`, from the legacy
`CreateVisualizationDialog`). On save:

1. if `chart_type in list_charts()` → store as-is;
2. else build `{reg.chart_class.__name__: name for name, reg in list_charts().items()}` and
   look `chart_type` up in it → store the resolved registry name;
3. else raise `ServiceError(f"Visualization {vid}: chart_type {chart_type!r} is neither a "
   f"registered chart name nor a known chart class")`.

The stored value is therefore always a registry name.

### 2.2 Figure re-derivation on load

```python
registration = chart_registry.get_chart(chart_type)          # ServiceError if unknown
figure = registration.chart_class.build(dataset.dataframe, **chart_parameters)
```

- `dataset` is the already-loaded `Dataset` for `visualizations.dataset_id`.
- **Missing columns (R0.4 item 11):** if `build()` raises because a `chart_parameters` column
  is not in `dataset.dataframe.columns`, the loader re-raises as
  `ServiceError(f"Visualization {vid} ({chart_type}) cannot be rebuilt: column(s) {missing} "
  f"no longer exist in dataset {dataset_id}")`. Hard error, not a silent skip.
- Rationale for not storing the figure: figures are large, are a pure function of
  (data + params), and persisting them creates stale-figure bugs.

### 2.3 `chart_parameters` validation on load (R0.4 item 9)

Before `build()`:

- `json.loads(chart_parameters)` must yield a `dict`;
- every key must be in `set(registration.required_fields) | set(registration.optional_fields)`
  — an unknown key raises `ServiceError`;
- every `registration.required_fields` name must be present;
- every value whose key is in `registration.list_fields` must be a `list` (raise otherwise);
- unknown `chart_type` already raises via `get_chart`.

### 2.4 Orphaned visualizations excluded on save

`close_dataset` does not cascade to visualizations, so a live `Visualization` may reference a
`dataset_id` that is no longer in the workspace. Such a visualization has no data to rebuild
from. **On save, a visualization whose `dataset_id` is not among the saved datasets is
skipped**; `save_workspace` returns the list of skipped `visualization_id`s (mirrors
`record_datasets`'s skipped-names return). This keeps the `visualizations.dataset_id` FK
sound and `Visualization.figure` non-optional on load.

---

## 3. `Dashboard` / `DashboardTile` → relational

Field source: `uadas_core/services/workspace_service.py:168-206`.

```sql
CREATE TABLE dashboards (
  dashboard_id TEXT PRIMARY KEY,        -- Dashboard.dashboard_id (uuid4)
  name         TEXT NOT NULL            -- Dashboard.name
);
CREATE TABLE dashboard_tiles (
  tile_id          TEXT PRIMARY KEY,    -- DashboardTile.tile_id  (NEW in 1.6 — see §9)
  dashboard_id     TEXT NOT NULL,       -- parent Dashboard
  visualization_id TEXT NOT NULL,       -- DashboardTile.visualization_id
  row              INTEGER NOT NULL,    -- DashboardTile.row  (0-indexed)
  column           INTEGER NOT NULL,    -- DashboardTile.column (0-indexed)
  ordinal          INTEGER NOT NULL,    -- position within Dashboard.tiles (list order)
  FOREIGN KEY (dashboard_id) REFERENCES dashboards(dashboard_id)
  -- NO FK on visualization_id: a tile pointing at a since-closed (or save-skipped, §2.4)
  -- visualization is normal state per CLAUDE.md's non-cascading rule and
  -- workspace_service.py:273-280 / get_dashboard_tiles (:507-534), which resolve leniently.
);
```

- **`tile_id`** is the stable row identity. It is generated by the dataclass default
  (`str(uuid.uuid4())`) when a `DashboardTile` is constructed without one, so existing call
  sites are unaffected (§9).
- **`ordinal`** preserves `Dashboard.tiles` list order across the round trip; the loader sorts
  tiles by `ordinal` when rebuilding the list.
- A tile with a dangling `visualization_id` **must survive the round trip** — persisted as-is,
  resolved leniently at render time.

---

## 4. Save → load round-trip contract — the C-3 tests (written first, red→green)

`tests/persistence/test_persistence_service.py`. Two tests.

```python
def test_workspace_round_trips_including_a_derived_dataset(tmp_path):
    ws1 = WorkspaceService()

    root = Dataset(name="sales", dataframe=pd.DataFrame({"region": ["e", "w"], "rev": [100, 200]}),
                   source_format="csv", source_path=Path("data/sales.csv"))
    ws1.add_dataset(root)

    derived = Dataset(name="sales_clean", dataframe=root.dataframe.iloc[:1].copy(),
                      source_format="csv", source_path=None,
                      parent_dataset_id=root.dataset_id,
                      derivation_description="first row only")
    ws1.add_dataset(derived)

    fig = chart_registry.get_chart("bar").chart_class.build(
        derived.dataframe, category_column="region", value_column="rev")
    viz = Visualization(name="by region", dataset_id=derived.dataset_id, figure=fig,
                        chart_type="bar",
                        chart_parameters={"category_column": "region", "value_column": "rev"})
    ws1.add_visualization(viz)

    dash = Dashboard(name="Q4", tiles=[DashboardTile(visualization_id=viz.visualization_id,
                                                     row=0, column=0)])
    ws1.add_dashboard(dash)

    skipped = PersistenceService(tmp_path).save_workspace(ws1)
    assert skipped == []
    ws2 = PersistenceService(tmp_path).load_workspace()

    r2 = ws2.get_dataset(root.dataset_id)
    assert (r2.name, r2.dataset_id, r2.source_path) == (root.name, root.dataset_id, root.source_path)
    assert r2.row_count == root.row_count and r2.column_count == root.column_count
    assert r2.dataframe.equals(root.dataframe)
    assert r2.parent_dataset_id is None

    d2 = ws2.get_dataset(derived.dataset_id)                 # currently dropped entirely
    assert d2.dataframe.equals(derived.dataframe)
    assert d2.source_path is None
    assert d2.parent_dataset_id == root.dataset_id           # lineage preserved
    assert d2.derivation_description == "first row only"

    v2 = ws2.get_visualization(viz.visualization_id)
    assert (v2.chart_type, v2.chart_parameters) == ("bar", viz.chart_parameters)
    assert v2.figure.to_json() == fig.to_json()              # structural figure round-trip

    tiles2 = ws2.get_dashboard_tiles(dash.dashboard_id)
    assert (tiles2[0][0].visualization_id, tiles2[0][0].row, tiles2[0][0].column) \
        == (viz.visualization_id, 0, 0)
    assert tiles2[0][0].tile_id == dash.tiles[0].tile_id     # tile identity preserved


def test_load_rejects_a_parent_dataset_id_cycle(tmp_path):
    """A hand-edited / corrupt .db whose datasets rows form a parent cycle is rejected
    on load with a clear ServiceError, not a hang or a silent partial workspace."""
    svc = PersistenceService(tmp_path)
    # ... build a valid saved workspace with datasets A and B (B.parent = A) ...
    # ... then UPDATE the datasets table directly: set A.parent_dataset_id = B.dataset_id ...
    with pytest.raises(ServiceError, match="cycle"):
        svc.load_workspace()
```

**Equality semantics:** scalars `==`; DataFrames `DataFrame.equals()` (NaN-safe, value-wise);
figures `fig.to_json()` string equality on a rebuild (structure, not identity); collections
list/dict `==`; nullable fields both-`None`-or-both-equal.

---

## 5. Storage substrate + module

**1.6 (desktop):** one SQLite file per project (`{base}/workspace.db`) and Parquet frames
under the same `{base}` as `{dataset_id}.parquet`. Local filesystem only. Full-replace write
(no deltas): `save_workspace` recreates the schema and rewrites everything.

**Phase 3 (web):** metadata → Postgres (per-tenant), frames → S3-compatible object store, key
`datasets/<tenant_id>/<dataset_id>.parquet`. Out of scope for 1.6, noted so the 1.6 API
(a `PersistenceService` with a caller-supplied base location and `save_workspace` /
`load_workspace` verbs) does not close that door.

**New module:** `uadas_core/persistence/persistence_service.py` (+ `uadas_core/persistence/__init__.py`).
`ProjectService` gains a call into it on open/save; the desktop shell wires
open → `load_workspace()`, save → `save_workspace()`. `PersistenceService` imports
`uadas_core.visualization.chart_registry` directly (§0 item 3) and `pandas` / `sqlite3` /
`json` / `uuid` from the stdlib + deps. No Qt, no framework — `lint-imports` stays green.

---

## 6. Security & operational constraints

### 6.1 Parameterized SQL (R0.4 item 7 — CRITICAL)

Every SQL statement uses `sqlite3` `?` placeholders. No value is ever formatted, `%`-ed,
`.format`-ed, or concatenated into SQL text — not table contents, not `dataset_id`, not
`name`. `executemany` for bulk inserts. Schema DDL is static string literals with no
interpolation. (CI `bandit` `--skip`s B608, so this is enforced only by review + the
`security-reviewer` ×2 gate — call it out in the plan.)

### 6.2 `dataset_id` validation before path-join (R0.4 item 8 — HIGH)

On load, before `{base}/{dataset_id}.parquet` is constructed for any row, `dataset_id` must
match a canonical uuid4 (`uuid.UUID(value, version=4)` round-trips to the same string, or an
explicit regex `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`).
A row failing this raises `ServiceError` and aborts the load — a corrupt/hand-edited row
carrying `dataset_id = "../../etc/passwd"` never reaches a path join. `base` is the
constructor argument, never a persisted value.

### 6.3 Parquet dependency versions (R0.4 item 10)

`pyarrow` and `fastparquet` are in `requirements.txt` (unpinned). Parquet deserialisation is
a known CVE class; the versions should be kept current. 1.6 does not add a pin (repo-wide
policy call, out of scope) — noted here so the decision is explicit, not forgotten.

### 6.4 Concurrency / locality (R0.4 item 12)

1.6 assumes a **single writer, single process, local non-networked filesystem**. No
cross-process locking, no WAL tuning, no retry/backoff on `sqlite3.OperationalError:
database is locked`. SQLite on a network share or with AV interference is out of scope for
local-desktop use; Phase 3's Postgres removes the concern.

---

## 7. Scope fence — NOT in 1.6

Remote object storage · incremental/delta save · version history / restore-points ·
compression or encryption beyond Parquet's own · chunked/streaming DataFrames · multi-writer
concurrency / ACID beyond SQLite's default · `chart_type` rename/removal migration · pinning
Parquet deps · `AnalysisLog` / `Recipe` persistence (that is 1.7) · persisting active
dataset/visualization selection · persisting `read_warnings` semantics beyond a JSON blob.
Anything here is rejected in review.

---

## 8. Assumptions / unverified

- `dataset_id` is *always* a `uuid4()` today (`workspace_service.py:109`). §6.2 enforces it
  defensively on load regardless.
- Figure re-derivation assumes the dataset's column names/dtypes are stable between save and
  load. §2.2 turns a mismatch into a clear hard error rather than a crash.
- `chart_parameters` may nest dicts (advanced Plotly config); JSON round-trip is assumed
  lossless for JSON-native types only. Non-JSON-native values in `chart_parameters` are out
  of scope (no current chart produces them).
- Column order: Parquet preserves it; params look up by name, so a reorder is cosmetically
  visible but not breaking. Accepted.
- `read_warnings` is a `list[str]`; stored as a JSON array, `"[]"` when empty.
- SQLite file-locking edge cases on Windows network shares — out of scope (§6.4).

---

## 9. Multi-file touchpoints

- **`uadas_core/services/workspace_service.py`** —
  (1) `DashboardTile` gains `tile_id: str = field(default_factory=lambda: str(uuid.uuid4()))`
  as a trailing field (R0.4 item 2, BLOCKING). Docstring updated.
  (2) `add_dataset` gains the forward acyclic-`parent_dataset_id` check (§1.3 guard a).
  Both are documented 1.6 changes; the existing suite must stay green (any new assertions are
  additive test files).
- **`uadas_core/services/project_service.py`** — a call into `PersistenceService` on
  open/save; `record_datasets` stops being the persistence path for datasets (it may remain
  for the `.uads.json` recent-list metadata — decided in the plan). Stop skipping derived
  datasets.
- **desktop shell** (`src/ui/` open/save wiring) — open → `load_workspace()`,
  save → `save_workspace()`. Exact wiring file(s) identified in the plan.
- **new** `uadas_core/persistence/__init__.py`, `uadas_core/persistence/persistence_service.py`.
- **new** `tests/persistence/__init__.py` (if the suite needs it),
  `tests/persistence/test_persistence_service.py` (the two C-3 tests).
- **`.github/workflows/ci.yml`** — add `uadas_core/persistence` to the `mypy (clean packages)`
  list (new genuinely-clean package, per that step's growth convention).
- **`plans/phase-1-baseline.md`** — record the post-1.6 suite count (additive: the new
  persistence tests; any structural `test_import_layering` delta from the 2 new
  `uadas_core/persistence/*.py` modules, same mechanism as 1.1/1.2).
