# Phase 1.6 — Persistence Contract

**Status:** R0.4 design doc · produced 2026-09-07 (architect) · R0.4 sign-off 2026-09-08
(`code-reviewer` + `security-reviewer`, both APPROVE-WITH-CHANGES) · **R0.4 changes folded
2026-09-09** (rev 1) · **`ecc:architect` (opus, non-author) verification 2026-09-09 =
CONCERNS → B1–B4 + 9 must-fix resolved in rev 2 → re-check = implementation-ready YES, 3
wording fixes + 4 precision nits applied in rev 2.1** (no design rework).
The §0 disposition table maps every review item to where it lives. **Ready for the executable
plan + `implementer`.**

**Purpose.** Define the save/load round-trip contract for datasets (including *derived*
datasets), visualizations, and dashboards — and the characterization tests (Control C-3) that
prove it. Today `uadas_core/services/project_service.py::record_datasets` (`:246-302`) persists
only `{name, source_path}` per dataset and **explicitly skips derived datasets**
(`if dataset.source_path is None: … skipped`, `:288`). 1.6 closes that gap with a
serialization layer *alongside* `WorkspaceService` — additive, changing no existing behaviour
for existing callers except the changes enumerated in §9.

---

## §0. Review-item disposition

### From R0.4 `code-reviewer` (6)

| # | Item | Resolution |
|---|---|---|
| 1 | Re-verify `file:line` citations against `uadas_core/` | Done; verified 2026-09-09 at HEAD `f5dd2d4`. Key: `Dataset` `workspace_service.py:39-120` (fields `:102-111`, `dataset_id` uuid4 factory `:109`, `row_count`/`column_count` `init=False` recomputed in `__post_init__:113-120`); `Visualization` `:123-165` (`figure` non-optional no-default `:162`); `DashboardTile` `:168-181`; `Dashboard` `:183-206`; `add_dataset` `:229-262` (parent-exists check `:249-257`, **no duplicate-id guard** — `:259`); `add_visualization` dataset check `:385-390`; `add_dashboard` tile check `:462-472`; `close_dataset` non-cascade `:264-295` (docstring `:273-280`); `get_lineage` orphan-tolerant `:308-334`; `get_dashboard_tiles` lenient `:507-534`. `record_datasets` `:246-302`. `chart_registry.get_chart` `:129`, `list_charts` `:158`, `ChartRegistration` `:41-81` (`chart_class` `:77`). `BarChart.build(cls, dataframe, category_column, value_column=None, title=None)` `categorical_charts.py:50-56` (concrete builds take **named params, no `**kwargs`**). |
| 2 | **BLOCKING** — `DashboardTile` has no `tile_id` | §3 + §9. `tile_id: str = field(default_factory=lambda: str(uuid.uuid4()))` as a **trailing** field. Every call site (`visualization_controller.py:183`, `tests/ui/controllers/test_visualization_controller.py:78`) uses kwargs → backward-compatible. |
| 3 | Figure re-derivation API — state exactly | §2.2. `chart_registry.get_chart(<registry_name>).chart_class.build(dataframe, **filtered_params)`. 1.3 kept `chart_registry` module-level (startup-graph §7d), so `PersistenceService` imports it directly (Qt-free `uadas_core` peer; `lint-imports` clean; already imported by the `linux_import` CI job, `ci.yml:401`). No injection. |
| 4 | Acyclic `parent_dataset_id` — verify precondition, decide | §1.3. **Corrected precondition:** an in-session cycle *is* constructible — `add_dataset` has no duplicate-id guard (`:259`), so `add(A)`→`add(B, parent=A)`→`add(A', dataset_id=A.id, parent=B.id)` closes one. Decision: **loader-side check only** (walk each dataset's ancestry with a visited-set; a repeat = cycle → `ServiceError`). **No `add_dataset` change** — an interactive re-add-with-duplicate-id is exotic, not a user flow, and the real threat (a hand-edited `.db`) is fully covered by the loader + `load_snapshot` check. |
| 5 | Strengthen C-3 figure assertion | §4 test 1: `v2.figure.to_json() == fig.to_json()`. Safe — `ChartView` themes via JS on the loaded page, not by mutating the `Figure`. |
| 6 | FK on `parent_dataset_id` vs non-cascading model | §1.2. **Option A** — drop the `parent_dataset_id` FK. It is *descriptive lineage* (`Dataset` docstring `:92-99`), an orphaned parent is normal (`close_dataset:273-280`), and the derived row is still fully persistable. The `visualizations.dataset_id` FK is **kept** (§2.4) — that is a *functional* dependency (no frame → no `figure`). |

### From R0.4 `security-reviewer` (7)

| # | Item | Resolution |
|---|---|---|
| 7 | **CRITICAL** — parameterized SQL | §6.1. `?` placeholders only, `executemany` for bulk; DDL is static literals. B608 is CI-`--skip`ped (`ci.yml:353`) so the `security-reviewer` ×2 gate is the only SQL check — called out in the plan. |
| 8 | **HIGH** — validate `dataset_id` is uuid4 before path-join | §6.2 + §4 test 5. Regex `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` on every `dataset_id` before it touches a path. `base` is a call argument, never a persisted value. |
| 9 | Validate `chart_parameters` on load | §2.3. Allow-list is `inspect.signature(chart_class.build)` (the real accepted kwargs). Unknown keys (producer noise — `chart_type`, `title` on a chart that lacks it, `method`) are **dropped with a debug log**, not raised. A missing no-default param, or a `list_fields` value that is not a `list`, is a **per-visualization rebuild failure** (§2.2), not a whole-load abort. |
| 10 | pyarrow/fastparquet min versions | §6.3. Both in `requirements.txt` (`:48-49`), unpinned; delegated there with a "Parquet deser is a CVE class, keep current" note. 1.6 adds no pin (repo-wide call, out of scope). |
| 11 | Load behaviour when a chart's columns no longer exist | §2.2. **Per-visualization** rebuild failure — the viz is dropped from the snapshot and its id is returned in `WorkspaceSnapshot.rebuild_failures`; the rest of the project loads. Whole-load abort is reserved for *structural* corruption (cycle, non-uuid4 id, unreadable `.db`, missing dataset frame). |
| 12 | Single-threaded SQLite + local-storage assumption | §6.4. |
| 13 | C-3 with a cycle-creation case | §4 test 2 + tests 3–7 (see §4). |

### From `ecc:architect` opus verification (rev 2)

| ID | Defect | Resolution |
|---|---|---|
| B1 | Loader can't re-enter the orphan states the contract guarantees — `add_dataset:249-257` rejects a dangling `parent_dataset_id`, `add_dashboard:462-472` rejects a tile with an unknown `visualization_id` | §2.5 + §9. New **`WorkspaceService.load_snapshot(datasets, visualizations, dashboards)`** restore entry point: clears current state, installs the three lists **directly** (tolerating dangling `parent_dataset_id` and dangling tile `visualization_id` — that is the point), re-runs the acyclic check. Datasets are inserted parents-first; the loader returns them topologically ordered. |
| B2 | `load_workspace() -> WorkspaceService` returning a *new* instance — but `WorkspaceService` is a `bootstrap()` singleton (`bootstrap.py:178`) that `AssistantService` / controllers / etc. hold | §5. `load_workspace(base) -> WorkspaceSnapshot` is **pure** — returns plain objects, touches no `WorkspaceService`. `ProjectController` runs it on a **worker thread** (mirroring `_read_recorded_datasets`, `project_controller.py:236-249`) then calls `workspace_service.load_snapshot(...)` on the **UI thread** (mirroring `_on_datasets_reloaded`, `:251-267`). `save_workspace` takes **plain lists** too (§5) so the worker never reads a live `WorkspaceService`. |
| B3 | §2.3's allow-list (`required_fields ∪ optional_fields`, column names only) rejects every real viz — real `chart_parameters` carry `title` (`visualize_page.py:417`, `create_visualization_dialog.py:219`), and AI/orchestrator store `dict(tool_input)` verbatim incl. `chart_type`/`title`/`method` (`assistant_service.py:484`, `analysis_orchestrator_service.py:428`); `build(**params)` would `TypeError` on `chart_type` | §2.3 rewritten to the `inspect.signature` allow-list with silent drop of unknowns (item 9). §2.2 states the filter runs *before* `build(**filtered)`. |
| B4 | `{base}` derivation, Save-As relocation, orphan-Parquet GC, save atomicity all unspecified | §5.1 (`{base}` = `<project-stem>.workspace/` beside the `.uads.json`), §5.2 (Save-As = full `save_workspace` to the new base; old dir left behind, like the old `.uads.json`), §5.3 (GC: `save_workspace` deletes `.parquet` whose stem is not a saved `dataset_id`), §5.4 (atomicity: `workspace.db` written to `.tmp` then `os.replace`; a partial frame is a per-dataset structural failure on load — accepted risk, noted). |
| Q3 | class-name→registry-name reverse map is silently last-wins on class collision | §2.1 — build the map with collision detection; two registrations sharing a `chart_class.__name__` → `ServiceError` on save. |
| Q5 | whole-load abort on one rebuild failure contradicts the `_read_recorded_datasets` precedent | §5 — `load_workspace` returns `(… , rebuild_failures: list[str])`; per-viz, not whole-load. |
| Q7 | routing persistence through `ProjectService` violates its "no `WorkspaceService` dependency" contract (`project_service.py:9-19`) | §5 + §9. `PersistenceService` is registered in `bootstrap()` and called by **`ProjectController`** (already holds both services, already does this shape at `:303-305`). `ProjectService` is **untouched**. `analysis_logs` stays in `.uads.json` (1.7). |
| — | `add_dataset` insertion must be topological; load phase-ordered (datasets → visualizations → dashboards) | §2.5 states both. |
| — | `column` is a SQLite keyword | §3 DDL quotes it as `"column"` (static identifier in static DDL — no §6.1 conflict). |
| — | `save_workspace`'s skipped list / `load_workspace`'s failures must be surfaced by the shell, like `_warn_about_skipped_datasets` (`project_controller.py:354-372`) | §9 desktop-shell touchpoint. |
| — | after 1.6, `open_project_at_path` would run *both* `_reload_project_datasets` and `load_workspace` → duplicate root datasets, different ids | §9 — if the `.workspace/` dir exists, `load_workspace` **replaces** the legacy reader-reload; the legacy path runs only for pre-1.6 projects (no `.workspace/`). |
| — | autosave (`autosave_timer.py:122-126`) would mean a periodic multi-second UI-thread freeze writing N Parquet files | §9 — **autosave does not call `save_workspace` in 1.6** (keeps the cheap `.uads.json` metadata autosave only). Documented 1.6 limitation; async workspace autosave is a later enhancement. |

### Chart_type storage inconsistency (found while folding, not in any review list)

`Visualization.chart_type` is stored as a chart *class* name (`"BarChart"`) by
`src/ui/dialogs/create_visualization_dialog.py:238` (`builder_class.__name__`) but as a
*registry* name (`"bar"`) by `visualize_page.py:439`, `assistant_service.py:483`,
`analysis_orchestrator_service.py:427`, `chart_recommender.py`. `get_chart()` only accepts
registry names. **§2.1:** the persistence layer normalises `chart_type` to the registry name
on save (passthrough → reverse-map by class name → `ServiceError`). The producer bug is
**not** fixed in 1.6 (it is `src/ui/`, Phase-2-doomed; out of a persistence step's scope) —
the reverse-map is a labelled compat read path. Round-trip is therefore *not* identity for a
legacy class-name value (`"BarChart"` in → `"bar"` out); §4's equality semantics say so.

---

## 1. `Dataset` → on-disk form

Field source: `uadas_core/services/workspace_service.py:102-111`.

### 1.1 DataFrame → Parquet

- **Key:** `{base}/{dataset_id}.parquet`; `dataset_id` is the uuid4 from `Dataset.dataset_id`
  (`:109`). Derived from `dataset_id`, **never** from `name` (user-editable; traversal /
  object-key-injection surface — matters now for the FS, more in Phase 3 with object storage).
- **Write:** `dataframe.to_parquet(path, index=False)` (pyarrow/fastparquet — both deps).
  `index=False` drops any non-default index; accepted (cleaning ops already
  `reset_index(drop=True)` — `missing_values.py:78`, `duplicates.py:67`).
- **Read:** `pd.read_parquet(path)` (mirrors `uadas_core/readers/parquet_reader.py`).
- **dtype fidelity (§8):** standard dtypes round-trip; `category` / tz-aware `datetime` /
  all-null `object` columns are known Parquet round-trip hazards — `DataFrame.equals()` is
  dtype-strict, so C-3 uses simple int/str/float frames.

### 1.2 Metadata row — SQLite table `datasets`

```sql
CREATE TABLE datasets (
  dataset_id            TEXT PRIMARY KEY,   -- uuid4; == the .parquet filename stem
  name                  TEXT NOT NULL,      -- Dataset.name
  source_path           TEXT,               -- Dataset.source_path; NULL for derived datasets
  source_format         TEXT NOT NULL,      -- Dataset.source_format ("csv"|"json"|"parquet"|…)
  row_count             INTEGER NOT NULL,   -- checksum only (see below)
  column_count          INTEGER NOT NULL,   -- checksum only
  read_warnings         TEXT NOT NULL,      -- JSON array of strings; "[]" when empty
  parent_dataset_id     TEXT,               -- Dataset.parent_dataset_id; NULL if root
  derivation_description TEXT               -- Dataset.derivation_description
  -- NO FOREIGN KEY on parent_dataset_id (R0.4 item 6): close_dataset() is non-cascading,
  -- so a derived dataset whose parent was closed is normal state and must round-trip; a
  -- SQL FK would wrongly reject it on save.
  -- derivation_description is NULL for a root dataset by convention (nothing on the
  -- Dataset dataclass enforces the "NULL iff parent NULL" pairing).
);
```

- `row_count` / `column_count` are `field(init=False)` on `Dataset`, recomputed in
  `__post_init__` from the loaded frame. The persisted columns are a **verification
  checksum**: on load, after `read_parquet`, assert `stored_row_count == len(df)` and
  `stored_column_count == len(df.columns)` — a mismatch is *structural* corruption
  (`ServiceError`, whole-load abort), the frame and metadata disagree.
- Rows with `parent_dataset_id IS NOT NULL` are persisted **in full** (frame + metadata) —
  the core gap 1.6 closes.

### 1.3 Acyclic `parent_dataset_id` (loader-side only)

After reading all `datasets` rows, for each dataset walk `parent_dataset_id` with a
visited-set; revisiting an id is a cycle → `ServiceError` naming the ids. Whole-load abort
(not a partial workspace). A dangling `parent_dataset_id` (parent not among the rows) is
**not** an error — it is stopped at, exactly like `get_lineage` (`workspace_service.py:328-334`).
No `add_dataset` change (R0.4 item 4 corrected).

---

## 2. `Visualization` → record (figure NOT stored; re-derived on load)

Field source: `uadas_core/services/workspace_service.py:160-165`.

```sql
CREATE TABLE visualizations (
  visualization_id  TEXT PRIMARY KEY,   -- Visualization.visualization_id (uuid4)
  dataset_id        TEXT NOT NULL,      -- saved-datasets set only (see 2.4)
  name              TEXT NOT NULL,      -- Visualization.name
  chart_type        TEXT NOT NULL,      -- registry name AFTER normalisation (2.1), e.g. "bar"
  chart_parameters  TEXT NOT NULL,      -- Visualization.chart_parameters, JSON object, verbatim
  FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id)
  -- FK kept: save skips any viz whose dataset_id is not in the saved set (2.4), so this
  -- reference is always satisfiable on load.
);
```

### 2.1 `chart_type` normalisation on save

For each `Visualization`:

1. `chart_type in list_charts()` → store as-is;
2. else build `class_to_name = {}` from `list_charts()`; for each `(name, reg)` add
   `reg.chart_class.__name__ → name`, **raising `ServiceError` if that class name is already
   a key** (two registrations, same class name — ambiguous). Look `chart_type` up → store the
   resolved registry name;
3. else `ServiceError(f"Visualization {vid}: chart_type {chart_type!r} is neither a "
   f"registered chart name nor a known chart class")`.

Stored `chart_type` is always a registry name.

### 2.2 Figure re-derivation on load (per-visualization failure isolation)

For each `visualizations` row, in a `try` that collects failures:

```python
registration = chart_registry.get_chart(chart_type)          # unknown -> failure
raw = json.loads(chart_parameters)                            # non-dict -> failure
raw.pop("chart_type", None)                                   # never a build() param; drop unconditionally
sig = inspect.signature(registration.chart_class.build)
if any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values()):   # a plugin build(**kwargs)
    accepted = set(registration.required_fields) | set(registration.optional_fields) | {"title"}
    required = set(registration.required_fields)
else:
    accepted = set(sig.parameters) - {"cls", "dataframe"}
    required = {p for p in accepted if sig.parameters[p].default is inspect.Parameter.empty}
filtered = {k: v for k, v in raw.items() if k in accepted}    # drops title/method noise (debug-log the drops)
# every name in `required` must be in `filtered` -> else per-viz failure
# every key in registration.list_fields present in `filtered` must be a list -> else per-viz failure
figure = registration.chart_class.build(dataset.dataframe, **filtered)   # ServiceError (missing column) -> failure
```

- `dataset` is the already-loaded `Dataset` for `dataset_id`.
- Any failure above → the viz is **omitted** from `WorkspaceSnapshot.visualizations` and its
  `visualization_id` is appended to `WorkspaceSnapshot.rebuild_failures`. The rest of the
  project loads. (R0.4 item 11 + architect Q5.)
- Not stored because figures are large and are a pure function of (data + params); storing
  them creates stale-figure bugs.

### 2.3 `chart_parameters` validation — see 2.2

The allow-list is the real `build()` signature (§2.2), not the registration's column-field
tuples (those are column names only; real params also carry `title` / `method` / a stray
`chart_type`). `chart_type` is dropped unconditionally; other unknown keys are dropped
(debug-logged), not rejected — they are known producer noise. A plugin `build(**kwargs)`
(no built-in has one) falls back to `required_fields ∪ optional_fields ∪ {"title"}`.
Genuinely broken params (a missing *required* param, a `list_fields` value that is not a
list) are per-viz failures.

### 2.4 Orphaned visualizations skipped on save

`close_dataset` does not cascade to visualizations, so a live `Visualization` may reference a
`dataset_id` no longer in the workspace — it has no frame to rebuild from. On save such a viz
is **skipped**; `save_workspace` returns `SaveReport.skipped_visualization_ids`. This keeps the
`visualizations.dataset_id` FK sound and `Visualization.figure` non-optional on load.
**Consequence (state in the shell):** under full-replace save a skipped viz is destroyed on
the *next* save — the shell must surface `skipped_visualization_ids` the way
`_warn_about_skipped_datasets` (`project_controller.py:354-372`) surfaces skipped datasets.

### 2.5 Restore path — `WorkspaceService.load_snapshot` (architect B1)

New method (additive; §9):

```python
def load_snapshot(self, datasets: list[Dataset],
                  visualizations: list[Visualization],
                  dashboards: list[Dashboard]) -> None:
    """Replace all workspace state with a restored snapshot.

    Unlike add_dataset / add_visualization / add_dashboard (interactive callers, which
    reject dangling references), this restore path INSTALLS the three lists directly and
    TOLERATES a dangling parent_dataset_id or a dangling tile visualization_id — those are
    normal persisted states (close_dataset / close_visualization are non-cascading). It
    still rejects a parent_dataset_id CYCLE (ServiceError). Active dataset / visualization
    are cleared. `datasets` must be topologically ordered (parents before children); the
    loader guarantees this.
    """
```

`ProjectController` calls it on the UI thread with the three lists off `WorkspaceSnapshot`.

---

## 3. `Dashboard` / `DashboardTile` → relational

Field source: `uadas_core/services/workspace_service.py:168-206`.

```sql
CREATE TABLE dashboards (
  dashboard_id TEXT PRIMARY KEY,        -- Dashboard.dashboard_id (uuid4)
  name         TEXT NOT NULL
);
CREATE TABLE dashboard_tiles (
  tile_id          TEXT PRIMARY KEY,    -- DashboardTile.tile_id  (NEW in 1.6 — §9)
  dashboard_id     TEXT NOT NULL,
  visualization_id TEXT NOT NULL,       -- may dangle (see below)
  row              INTEGER NOT NULL,
  "column"         INTEGER NOT NULL,    -- quoted: `column` is a SQLite keyword
  ordinal          INTEGER NOT NULL,    -- position within Dashboard.tiles (list order)
  FOREIGN KEY (dashboard_id) REFERENCES dashboards(dashboard_id)
  -- NO FK on visualization_id: a tile pointing at a since-closed or save-skipped (2.4)
  -- visualization is normal state (CLAUDE.md non-cascading rule; get_dashboard_tiles
  -- :507-534 resolves leniently). load_snapshot (2.5) re-installs such tiles unchanged.
);
```

- **`tile_id`** — stable row identity; the dataclass default (`str(uuid.uuid4())`) fills it
  when a `DashboardTile` is built without one, so existing call sites are unaffected.
- **`ordinal`** — the loader sorts tiles by `ordinal` when rebuilding `Dashboard.tiles`.
- A dangling-`visualization_id` tile **round-trips unchanged**.

---

## 4. C-3 tests (written first, red→green) — `tests/persistence/test_persistence_service.py`

Eight tests, one behaviour each. The `PersistenceService` API used throughout:
`save_workspace(datasets, visualizations, dashboards, base) -> SaveReport` and
`load_workspace(base) -> WorkspaceSnapshot` (§5).

1. **`test_workspace_round_trips_including_a_derived_dataset`** — happy path. root + derived
   (`parent_dataset_id` set, `source_path=None`) + a `"bar"` viz on the derived + a dashboard
   with one tile. Assert: root/derived frames `DataFrame.equals`; `derived.parent_dataset_id`
   and `derivation_description` preserved; `derived.source_path is None`; `viz.chart_type`,
   `viz.chart_parameters` preserved; `v2.figure.to_json() == fig.to_json()`;
   `tile.tile_id` / `row` / `column` / order preserved; `SaveReport.skipped_visualization_ids == []`;
   `WorkspaceSnapshot.rebuild_failures == []`.
2. **`test_load_rejects_a_parent_dataset_id_cycle`** — save a valid A/B (B.parent=A), then
   `UPDATE datasets SET parent_dataset_id = :b WHERE dataset_id = :a` directly; `load_workspace`
   → `ServiceError` matching `"cycle"`.
3. **`test_chart_type_class_name_is_normalised_to_registry_name_on_save`** — viz created with
   `chart_type="BarChart"` (legacy form); after round-trip `v2.chart_type == "bar"`.
4. **`test_visualization_on_a_closed_dataset_is_skipped_on_save`** — add dataset D + viz V on
   D, `close_dataset(D)`, save; `SaveReport.skipped_visualization_ids == [V.visualization_id]`;
   `load_workspace` has no V.
5. **`test_load_rejects_a_non_uuid4_dataset_id_before_any_path_join`** (security item 8) —
   `UPDATE datasets SET dataset_id = '../../etc/passwd' …`; `load_workspace` → `ServiceError`,
   and no file outside `base` is opened (assert via a `monkeypatch` on `pd.read_parquet` /
   path check).
6. **`test_a_visualization_whose_column_no_longer_exists_is_a_rebuild_failure_not_a_load_abort`** —
   persist a viz whose `chart_parameters` names a column, then rewrite the parquet so that
   column is gone **while keeping the frame's row/column counts unchanged** (rename it — a
   *shape* change is a §1.2 checksum failure and would abort the whole load, which test 8
   covers and this test must not trip). `load_workspace` succeeds, the dataset loads,
   `viz.visualization_id in WorkspaceSnapshot.rebuild_failures`, `snapshot.visualizations == []`.
7. **`test_dangling_tile_visualization_id_round_trips`** — dashboard tile pointing at a
   `visualization_id` that is never added / is closed; after `load_workspace` +
   `WorkspaceService.load_snapshot(...)`, `get_dashboard_tiles` returns the tile paired with
   `None` (not an exception, not dropped).
8. **`test_row_count_checksum_mismatch_is_a_structural_load_error`** — save a workspace, then
   overwrite one dataset's `.parquet` with a frame of a different row count; `load_workspace`
   → `ServiceError` (metadata/frame disagree), whole-load abort — not a per-viz failure.

**Equality semantics:** scalars `==`; DataFrames `DataFrame.equals()` (NaN-safe); figures
`fig.to_json()` string equality on a rebuild; collections `==`; nullable fields
both-`None`-or-both-equal. **`chart_type` is *not* identity** for a legacy class-name input
(`"BarChart"` → `"bar"`), by design (§2.1).

---

## 5. `PersistenceService` — API, storage, base derivation

```python
@dataclass
class SaveReport:
    skipped_visualization_ids: list[str]

@dataclass
class WorkspaceSnapshot:
    datasets: list[Dataset]            # topologically ordered, parents before children
    visualizations: list[Visualization]  # figure already rebuilt; excludes rebuild failures
    dashboards: list[Dashboard]
    rebuild_failures: list[str]        # visualization_ids that could not be rebuilt

class PersistenceService:
    """Stateless. Registered as a bootstrap() singleton; base location is a per-call arg."""
    def save_workspace(self, datasets: list[Dataset], visualizations: list[Visualization],
                       dashboards: list[Dashboard], base: Path) -> SaveReport: ...
    def load_workspace(self, base: Path) -> WorkspaceSnapshot: ...   # pure; touches no WorkspaceService
```

`save_workspace` / `load_workspace` take **plain lists / return plain data** so
`ProjectController` can run them on a worker thread without touching the non-thread-safe
`WorkspaceService` (architect B2). Both raise `ServiceError` for **structural** problems
(unreadable/corrupt `.db`; a `parent_dataset_id` cycle; a non-uuid4 `dataset_id`; a
`row_count`/`column_count` checksum mismatch; a `datasets` row whose `.parquet` is missing).
Per-visualization rebuild problems are collected in `rebuild_failures`, never raised.
Every `sqlite3.Error` / `OSError` / pyarrow exception is caught and re-raised as `ServiceError`
(repo convention).

### 5.1 `{base}` derivation

`base = project.path.parent / (project_stem + ".workspace")`, where `project_stem` is
`project.path.name` with a trailing `".uads.json"` removed **if present**, else the full file
name (`save_project_as` passes the chosen `Path(file_path_str)` through unmodified —
`project_controller.py:325-341` — so `foo.json` deterministically yields
`foo.json.workspace/`). Contains `workspace.db` and `{dataset_id}.parquet` files. Two
different project files in one folder get two different `.workspace/` dirs — no collision.

### 5.2 Save-As

`save_workspace` is full-replace from live state, so Save-As is just
`PersistenceService().save_workspace(<lists>, <new base>)`. The old `.workspace/` dir is left
in place (as the old `.uads.json` is). No frame-copy logic needed.

### 5.3 Orphan-Parquet GC

At the end of `save_workspace`, delete every `*.parquet` in `base` whose stem is not one of
the `dataset_id`s just written. Covers frames for datasets closed since the last save.

### 5.4 Atomicity

`workspace.db` is built at `base/workspace.db.tmp` then `os.replace`d onto `workspace.db`
(atomic on one filesystem). Parquet frames are written directly; a crash mid-frame-write
leaves a partial `.parquet`. On the next `load_workspace` an unreadable or
checksum-mismatched frame is a **structural** failure — `ServiceError`, whole-load abort
(the §5 list; silently losing a whole dataset is worse than losing a chart). Accepted risk
for 1.6 desktop-local use; Phase 3's object store + Postgres transaction removes it.

### 5.5 Ordering coupling

`load_workspace` calls `chart_registry.get_chart(...)`, so it depends on the built-in charts
having been registered — i.e. on `bootstrap()` (and plugin load) having run first. This is a
real post-1.3 ordering coupling; the desktop shell already satisfies it (open happens well
after `bootstrap()`).

---

## 6. Security & operational constraints

### 6.1 Parameterized SQL (R0.4 item 7 — CRITICAL)

`?` placeholders for every value; `executemany` for bulk insert; DDL is static string
literals. Nothing — not `name`, not `dataset_id`, not `chart_parameters` — is ever
formatted/`%`/`.format`/`+`-ed into SQL text. (B608 is CI-`--skip`ped, `ci.yml:353`, so this
+ the `security-reviewer` ×2 gate are the only SQL checks — the plan calls this out.)

### 6.2 `dataset_id` validation before path-join (R0.4 item 8 — HIGH)

On load, before `{base}/{dataset_id}.parquet` is built for any row, `dataset_id` must match
`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`. A failing row →
`ServiceError`, load aborts, no path is joined. `base` is the call argument, never a
persisted value. Tested (§4 test 5).

### 6.3 Parquet dependency versions (R0.4 item 10)

`pyarrow` + `fastparquet` in `requirements.txt` (`:48-49`), unpinned. Parquet deserialisation
is a known CVE class — keep current. 1.6 adds no pin (repo-wide policy call, out of scope);
noted so the decision is explicit.

### 6.4 Concurrency / locality (R0.4 item 12)

Single writer, single process, local non-networked filesystem. No cross-process locking, no
WAL tuning, no retry on `database is locked`. Network shares / AV interference out of scope;
Phase 3's Postgres removes it.

### 6.5 Retention

A closed dataset's `.parquet` is removed on the next `save_workspace` (§5.3), not on
`close_dataset` (persistence does not observe the live workspace). Between close and next save
the frame remains on local disk. Acceptable for 1.6 local-desktop; Phase 3 revisits with the
object store's lifecycle rules.

### 6.6 Out of scope for §6

File permissions / umask on the created `.db` and `.parquet` (local-desktop; inherits the
process default). Encryption at rest.

---

## 7. Scope fence — NOT in 1.6

Remote object storage · incremental/delta save · version history / restore-points ·
compression or encryption beyond Parquet's own · chunked/streaming DataFrames · multi-writer
concurrency / ACID beyond SQLite · `chart_type` rename/removal migration · **fixing the
`create_visualization_dialog.py:238` class-name producer bug** (Phase-2 UI) · pinning Parquet
deps · `AnalysisLog` / `Recipe` persistence — that is 1.7; `record_analysis_log` /
`project.contents["analysis_logs"]` stay in `.uads.json` untouched · persisting the active
dataset/visualization selection · async / worker-thread autosave of the workspace DB ·
Save-As frame-copy (full re-save covers it) · category/tz-datetime/all-null-object dtype
fidelity through Parquet. Anything here is rejected in review.

---

## 8. Assumptions / unverified

- `dataset_id` is always uuid4 today (`workspace_service.py:109`); §6.2 enforces it
  defensively on load regardless.
- `chart_parameters` is JSON-native (str/num/bool/list/dict/null). No current producer emits
  a non-JSON value. Nested dicts round-trip as-is.
- Figure re-derivation assumes stable column names/dtypes between save and load; §2.2 turns a
  mismatch into a per-viz failure, not a crash.
- **Plugin charts:** a project saved with a plugin chart enabled stores that chart's registry
  name; if the plugin is disabled at load, `get_chart` fails → that viz is a per-viz
  `rebuild_failure` (not a whole-load abort). Datasets and other viz still load.
- Standard pandas dtypes round-trip through `to_parquet`/`read_parquet`;
  `category`/tz-aware-`datetime`/all-null-`object` do not reliably — C-3 avoids them; a real
  project hitting one surfaces as a per-dataset structural failure (checksum) or a per-viz
  failure, never silent corruption.
- `to_parquet(index=False)` discards a non-default index; accepted (cleaning ops reset it).
- SQLite file-locking edge cases on network shares — out of scope (§6.4).

---

## 9. Multi-file touchpoints

- **`uadas_core/services/workspace_service.py`** —
  (1) `DashboardTile` gains a trailing `tile_id: str = field(default_factory=lambda: str(uuid.uuid4()))` (R0.4 item 2). Docstring updated.
  (2) **new** `WorkspaceService.load_snapshot(datasets, visualizations, dashboards)` — the
  restore entry point (§2.5). Additive; existing methods unchanged.
  *(No `add_dataset` cycle-guard — R0.4 item 4 corrected to loader-only.)*
- **new** `uadas_core/persistence/__init__.py`, `uadas_core/persistence/persistence_service.py`
  (`PersistenceService`, `SaveReport`, `WorkspaceSnapshot`).
- **`uadas_core/core/bootstrap.py`** — register `PersistenceService` as a singleton
  (`container.register(PersistenceService, lambda: PersistenceService(), singleton=True)`),
  after the other services. Its startup-sequence step is documented in `docs/ARCHITECTURE.md`.
- **`src/ui/controllers/project_controller.py`** — inject `PersistenceService` (new
  `__init__` arg, wired in `main_window.py::_build_controllers`).
  **Save** (`save_project` / `save_project_as`): keep the existing
  `_project_service.save_project(...)` for the `.uads.json`; then snapshot
  `workspace_service.{list_datasets,list_visualizations,list_dashboards}()` on the UI thread
  and run `save_workspace(...)` on a worker; in the result handler surface
  `SaveReport.skipped_visualization_ids` via a new `_warn_about_skipped_visualizations`
  (same shape as `_warn_about_skipped_datasets`, `:354-372`). **Suppress the existing
  `_warn_about_skipped_datasets` call for `record_datasets`'s skipped *derived* datasets on
  this path** — 1.6's `save_workspace` now persists those, so "could not be included" is
  false. (Whether `record_datasets` keeps running for the `.uads.json` reload-list is decided
  in the plan; its skipped-derived warning goes regardless.)
  **Open** (`open_project_at_path`): **if the `.workspace/` dir exists**, run
  `load_workspace(base)` on a worker; in the UI-thread result handler call
  `workspace_service.load_snapshot(snap.datasets, snap.visualizations, snap.dashboards)`,
  then `dock_manager.refresh_dataset_list(workspace_service.list_datasets())` +
  `_state_bus.request_refresh()` (mirroring `_on_datasets_reloaded:263-267`), then surface
  `rebuild_failures`; **skip** `_reload_project_datasets`. **Else** (no `.workspace/` —
  pre-1.6 project) fall back to `_reload_project_datasets` unchanged.
- **`src/ui/main_window.py`** — `_build_controllers` resolves `PersistenceService` from the
  container and passes it to `ProjectController` (typed since 1.4).
- **`src/ui/autosave_timer.py`** — **unchanged**; autosave keeps saving only `.uads.json`
  metadata in 1.6 (documented limitation; §7).
- **`.github/workflows/ci.yml`** — add `uadas_core/persistence` to the `mypy (clean packages)`
  list (new genuinely-clean package, per that step's growth convention).
- **`docs/ARCHITECTURE.md`** — persistence layer + its bootstrap registration + the
  open/save wiring in the startup / workspace sections.
- **new** `tests/persistence/__init__.py`, `tests/persistence/test_persistence_service.py`
  (the seven C-3 tests).
- **`plans/phase-1-baseline.md`** — post-1.6 suite count: +7 authored tests, +2 structural
  from `test_import_layering` parametrising over the 2 new `uadas_core/persistence/*.py`
  modules (same mechanism as 1.1/1.2). No `test_module_size` delta (that guard is
  `src/ui/`-only).
