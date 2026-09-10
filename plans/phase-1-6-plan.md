# Phase 1.6 — Persistence Layer: Implementation Plan

> **For agentic workers:** implement this task-by-task. Steps use `- [ ]` checkboxes.
> **Spec:** `plans/phase-1-6-persistence-contract.md` (rev 2.1, frozen at `7a4812c`,
> `ecc:architect`-verified implementation-ready). The plan argues from the contract — read
> both. Every `§N` reference below is to that contract.

**Goal:** A greenfield `uadas_core/persistence/` layer that round-trips a `WorkspaceService`
(datasets incl. derived, visualizations, dashboards) to a per-project SQLite file + Parquet
frames, closing the gap where `record_datasets` persists only `{name, source_path}` and drops
derived datasets.

**Architecture:** `PersistenceService` (stateless, `bootstrap()` singleton) with two pure
verbs — `save_workspace(datasets, visualizations, dashboards, base) -> SaveReport` and
`load_workspace(base) -> WorkspaceSnapshot`. Both take/return plain data so
`ProjectController` runs them on a worker thread; state is installed into the live
`WorkspaceService` singleton on the UI thread via a new `WorkspaceService.load_snapshot(...)`
restore entry point. Figures are re-derived on load via `chart_registry`, never stored.

**Tech stack:** stdlib `sqlite3` + `json` + `uuid` + `inspect`; `pandas` `to_parquet` /
`read_parquet` (pyarrow/fastparquet, already deps); `plotly` via `uadas_core.visualization.chart_registry`.

**Spec:** `plans/phase-1-6-persistence-contract.md`.

## Global Constraints (from the contract + repo doctrine)

- **Parameterized SQL only** (§6.1). `?` placeholders for every value; `executemany` for bulk;
  DDL is static string literals; `"column"` is quoted (SQLite keyword). Nothing is
  f-string/`%`/`.format`/`+`-ed into SQL. CI `bandit` `--skip`s B608 — the `security-reviewer`
  ×2 gate at the end is the only SQL-injection check.
- **`dataset_id` uuid4-validated before any path-join** (§6.2), regex
  `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`. `base` is a call
  arg, never a persisted value.
- **`uadas_core` stays Qt/framework-free** — `lint-imports` (`.importlinter`) enforced in CI.
  `PersistenceService` imports `chart_registry` directly; no PySide6/Django.
- **Every `sqlite3.Error` / `OSError` / pyarrow exception → `ServiceError`** (repo convention,
  `uadas_core/core/exceptions.py`).
- **A10 / behaviour freeze:** the only changes to existing `uadas_core` behaviour are the two
  additive `workspace_service.py` items (`DashboardTile.tile_id`, `WorkspaceService.load_snapshot`)
  and the `bootstrap()` registration line. No existing method signature or logic changes.
- **A9 / test count:** the golden baseline is a rolling number (currently **1420 / 92 / 0** at
  `a0442e0`). Expected post-1.6: **+8 authored** C-3 tests + **+N** from `workspace_service`
  unit tests + **+2 structural** (`test_import_layering` parametrising over the 2 new
  `uadas_core/persistence/*.py` modules). Any *other* delta = a regression.
- **Every module** starts with `# File: <path>` then a docstring explaining *why*; `from
  __future__ import annotations`; type hints throughout; comments explain why a simpler
  alternative was rejected.
- The `PostToolUse` `quality-check.ps1` hook runs `ruff format` + `ruff check --fix` on every
  `.py` Edit/Write — **add an import and its first use in ONE edit** (obs 0021/0023), do not
  re-run ruff by hand. `black` / `isort` / `mypy` / `bandit` are NOT in that hook — run them
  explicitly.

## File Structure

| File | Responsibility | New/Mod |
|---|---|---|
| `uadas_core/persistence/__init__.py` | package marker + `# File:` docstring | new |
| `uadas_core/persistence/persistence_service.py` | `PersistenceService`, `SaveReport`, `WorkspaceSnapshot`; all SQLite + Parquet + figure-rebuild logic | new |
| `uadas_core/services/workspace_service.py` | `DashboardTile.tile_id` field; `WorkspaceService.load_snapshot()` | mod (additive) |
| `uadas_core/core/bootstrap.py` | register `PersistenceService` singleton | mod (1 line + docstring bullet) |
| `tests/persistence/__init__.py` | package marker | new |
| `tests/persistence/test_persistence_service.py` | the 8 C-3 tests (§4) | new |
| `tests/services/test_workspace_service.py` | `tile_id` + `load_snapshot` unit tests | mod (append) |
| `.github/workflows/ci.yml` | add `uadas_core/persistence` to the `mypy (clean packages)` list | mod (1 path) |
| `docs/ARCHITECTURE.md` | persistence layer + its bootstrap step + open/save wiring | mod |
| `src/ui/controllers/project_controller.py` | inject `PersistenceService`; worker-threaded save/open wiring (§9) | mod |
| `src/ui/main_window.py` | `_build_controllers` resolves + passes `PersistenceService` | mod (~2 lines) |
| `tests/ui/controllers/test_project_controller.py` | controller-level save→open round-trip | mod (append) |
| `plans/phase-1-baseline.md` | post-1.6 suite numbers | mod |

---

## PART A — Qt-free core (`implementer` in a worktree)

Everything here is `uadas_core` + tests, no Qt. Build in a worktree (`superpowers:using-git-worktrees`);
the shared branch stays clean if the run is interrupted (A7 — no tidying rebase on the shared
branch). One commit per task. Per-commit `code-reviewer` (haiku) is the only subagent inside
the cycle.

### Task A1: `DashboardTile.tile_id`

**Files:** Modify `uadas_core/services/workspace_service.py:168-181`; Test
`tests/services/test_workspace_service.py`.

**Interfaces — Produces:** `DashboardTile` gains `tile_id: str` (uuid4 default, trailing field).

- [ ] **Step 1 — failing test.** Append to `tests/services/test_workspace_service.py`:

```python
def test_dashboard_tile_gets_a_uuid4_tile_id_by_default() -> None:
    a = DashboardTile(visualization_id="v", row=0, column=0)
    b = DashboardTile(visualization_id="v", row=0, column=1)
    assert len(a.tile_id) == 36 and a.tile_id != b.tile_id
    assert DashboardTile(visualization_id="v", row=0, column=0, tile_id="fixed").tile_id == "fixed"
```

- [ ] **Step 2 — run, expect fail.** `pytest tests/services/test_workspace_service.py::test_dashboard_tile_gets_a_uuid4_tile_id_by_default -q` → `TypeError: __init__() got an unexpected keyword argument 'tile_id'`.
- [ ] **Step 3 — implement.** In `DashboardTile`, after `column: int`, add
  `tile_id: str = field(default_factory=lambda: str(uuid.uuid4()))`. Add to the docstring:
  `tile_id: Stable identity for this tile row, used by the persistence layer (Phase 1.6) as
  the ``dashboard_tiles`` primary key. Auto-generated; callers never set it.`
- [ ] **Step 4 — run.** The new test + `pytest tests/services/ tests/ui/controllers/test_visualization_controller.py -q` → all green (every `DashboardTile(...)` call site uses kwargs, §0 item 2).
- [ ] **Step 5 — commit.** `refactor(phase-1.6): add DashboardTile.tile_id for the dashboard_tiles PK`

### Task A2: `WorkspaceService.load_snapshot`

**Files:** Modify `uadas_core/services/workspace_service.py` (new method on `WorkspaceService`);
Test `tests/services/test_workspace_service.py`.

**Interfaces — Produces:** `WorkspaceService.load_snapshot(datasets: list[Dataset],
visualizations: list[Visualization], dashboards: list[Dashboard]) -> None`.

- [ ] **Step 1 — failing tests.** Append 5 tests:
  `test_load_snapshot_replaces_all_state`,
  `test_load_snapshot_tolerates_a_dangling_parent_dataset_id` (derived dataset whose parent is
  not in the list → installed, `get_lineage` stops gracefully),
  `test_load_snapshot_tolerates_a_dangling_tile_visualization_id` (`get_dashboard_tiles` →
  `(tile, None)`),
  `test_load_snapshot_rejects_a_parent_dataset_id_cycle` (`ServiceError`, match `"cycle"`),
  `test_load_snapshot_clears_active_selection`.
- [ ] **Step 2 — run, expect fail** (`AttributeError: 'WorkspaceService' object has no attribute 'load_snapshot'`).
- [ ] **Step 3 — implement** per §2.5:

```python
def load_snapshot(
    self,
    datasets: list[Dataset],
    visualizations: list[Visualization],
    dashboards: list[Dashboard],
) -> None:
    """Replace all workspace state with a restored snapshot.

    The restore peer of :meth:`add_dataset` / :meth:`add_visualization` /
    :meth:`add_dashboard`. Those reject dangling references because an interactive
    caller creating one is a bug; a *persisted* dangling ``parent_dataset_id`` or tile
    ``visualization_id`` is normal (``close_dataset`` / ``close_visualization`` are
    non-cascading — see their docstrings), so this path installs the three lists as-is.
    It still rejects a ``parent_dataset_id`` cycle. ``datasets`` must already be
    topologically ordered (parents before children); :class:`PersistenceService` guarantees
    that. Active dataset / visualization are cleared.
    """
    _reject_parent_cycles(datasets)
    self._datasets = {d.dataset_id: d for d in datasets}
    self._visualizations = {v.visualization_id: v for v in visualizations}
    self._dashboards = {d.dashboard_id: d for d in dashboards}
    self._active_dataset_id = None
    self._active_visualization_id = None
    _logger.info(
        "Restored workspace snapshot: %d dataset(s), %d visualization(s), %d dashboard(s).",
        len(self._datasets), len(self._visualizations), len(self._dashboards),
    )
```

  `_reject_parent_cycles(datasets)` (module-level helper): build
  `{d.dataset_id: d.parent_dataset_id for d in datasets}`; for each id walk `parent` links
  through a per-walk visited-set; revisiting an id → `raise ServiceError(f"parent_dataset_id
  cycle: {' -> '.join(path)}")`. A parent id not in the map = a clean stop (dangling, allowed).

- [ ] **Step 4 — run.** New tests + full `pytest tests/services/ -q` green.
- [ ] **Step 5 — commit.** `feat(phase-1.6): WorkspaceService.load_snapshot restore entry point`

### Task A3: the 8 C-3 tests (red)

**Files:** `tests/persistence/__init__.py` (empty), `tests/persistence/test_persistence_service.py`.

- [ ] **Step 1 — write all 8 tests** exactly per §4 (names as listed). Imports:
  `from uadas_core.persistence.persistence_service import PersistenceService, SaveReport, WorkspaceSnapshot`,
  `from uadas_core.services.workspace_service import Dataset, Visualization, Dashboard, DashboardTile, WorkspaceService`,
  `from uadas_core.visualization import chart_registry`, `from uadas_core.core.exceptions import ServiceError`.
  Each test builds inputs with a `WorkspaceService()`, passes
  `ws.list_datasets()/list_visualizations()/list_dashboards()` to `save_workspace(...)`, then
  `load_workspace(base)`, asserts per §4. Tests 2/5/8 mutate the `.db` directly with `sqlite3`
  + `?` params; test 6 rewrites a `.parquet` with a column dropped.
  **Seeding:** `tests/conftest.py` already seeds the chart registry at module level (1.3), so
  `chart_registry.get_chart("bar")` works without `bootstrap()`.
- [ ] **Step 2 — run, expect 8 failures.** `pytest tests/persistence/ -q` →
  `ModuleNotFoundError: No module named 'uadas_core.persistence'` (a collection error here is
  the intended red state).
- [ ] **Step 3 — commit.** `test(phase-1.6): C-3 persistence round-trip tests (red)`

### Task A4: `PersistenceService` — save + load (all 8 C-3 tests green)

**Files:** `uadas_core/persistence/__init__.py`, `uadas_core/persistence/persistence_service.py`.

**Interfaces — Produces:**
- `SaveReport(skipped_visualization_ids: list[str])` — `@dataclass`.
- `WorkspaceSnapshot(datasets: list[Dataset], visualizations: list[Visualization], dashboards: list[Dashboard], rebuild_failures: list[str])` — `@dataclass`.
- `PersistenceService.save_workspace(datasets, visualizations, dashboards, base: Path) -> SaveReport`
- `PersistenceService.load_workspace(base: Path) -> WorkspaceSnapshot`

- [ ] **Step 1 — module skeleton + dataclasses + schema constant.** `# File:` + docstring
  (why: closes the derived-dataset persistence gap; alongside `WorkspaceService`, not inside
  it; imports `chart_registry` directly per §0 item 3). `_SCHEMA` = the four `CREATE TABLE`
  statements from §1.2/§2/§3 as one static triple-quoted string, `"column"` quoted, **no**
  `parent_dataset_id` FK, `visualizations.dataset_id` FK kept, `dashboard_tiles.dashboard_id`
  FK kept, **no** `dashboard_tiles.visualization_id` FK. `_UUID4_RE` = the §6.2 regex compiled.
- [ ] **Step 2 — `save_workspace`** per §1–§3 + §5.1–§5.4:
  1. `base.mkdir(parents=True, exist_ok=True)`.
  2. Build `class_to_name` from `chart_registry.list_charts()` with **collision detection**
     (§2.1 step 2 — a repeated `chart_class.__name__` → `ServiceError`).
  3. `saved_ids = {d.dataset_id for d in datasets}`. Partition visualizations into
     `keep` / `skipped` by `viz.dataset_id in saved_ids` (§2.4).
  4. `sqlite3.connect(base / "workspace.db.tmp")`; `conn.executescript(_SCHEMA)`.
  5. Each dataset: `df.to_parquet(base / f"{dataset_id}.parquet", index=False)`; `INSERT` the
     row with `?` params (`read_warnings` = `json.dumps(list(...))`).
  6. Each kept viz: normalise `chart_type` (§2.1 — passthrough / reverse-map / `ServiceError`);
     `INSERT` with `chart_parameters` = `json.dumps(viz.chart_parameters)`.
  7. Each dashboard: `INSERT` into `dashboards`; `executemany` its tiles into `dashboard_tiles`
     with `ordinal` = list index, `tile_id` from the tile.
  8. `conn.commit()`, `conn.close()`.
  9. GC (§5.3): every `*.parquet` in `base` whose stem ∉ `saved_ids` → `unlink()`.
  10. `os.replace(base / "workspace.db.tmp", base / "workspace.db")` (§5.4).
  11. `return SaveReport(skipped_visualization_ids=sorted(skipped))`.
  Wrap sqlite/parquet/OS calls so `sqlite3.Error` / `OSError` / pyarrow errors surface as
  `ServiceError` (Global Constraints).
- [ ] **Step 3 — `load_workspace`** per §1.2–§1.3, §2.2–§2.3, §3, §5:
  1. `db = base / "workspace.db"`; missing → `ServiceError`. `sqlite3.connect(f"file:{db}?mode=ro",
     uri=True)` (mirrors `sqlite_reader.py:84`).
  2. Read all `datasets` rows. Per row: validate `dataset_id` against `_UUID4_RE` **before**
     building any path (§6.2) → else `ServiceError`. `read_parquet(base / f"{id}.parquet")`
     (missing/unreadable → `ServiceError`, structural). Build `Dataset(name=, dataframe=df,
     source_format=, source_path=Path(sp) if sp else None, read_warnings=json.loads(rw),
     parent_dataset_id=pid, derivation_description=dd)`. **Checksum (§1.2):** stored
     `row_count == len(df)` and `column_count == len(df.columns)` → else `ServiceError`.
  3. Acyclic check over `parent_dataset_id` (§1.3, visited-set) → `ServiceError` match
     `"cycle"`. Topologically sort datasets parents-first for the snapshot (Kahn).
  4. Read `visualizations` rows. Per row, in a `try` collecting `rebuild_failures` (§2.2):
     `get_chart(chart_type)`; `raw = json.loads(chart_parameters)` (non-dict → failure);
     `raw.pop("chart_type", None)`; `sig = inspect.signature(reg.chart_class.build)`;
     VAR_KEYWORD → `accepted = required_fields|optional_fields|{"title"}`,
     `required = set(required_fields)`; else `accepted = set(sig.parameters) - {"cls","dataframe"}`,
     `required = {p for p in accepted if sig.parameters[p].default is inspect.Parameter.empty}`;
     `filtered = {k:v for k,v in raw.items() if k in accepted}`; require `required <= filtered.keys()`
     and every `reg.list_fields` key in `filtered` is a `list` (else failure); look up the
     row's loaded `Dataset` (FK guarantees present);
     `figure = reg.chart_class.build(dataset.dataframe, **filtered)` (`ServiceError`/missing
     column → failure). On success append `Visualization(name=, dataset_id=, figure=figure,
     chart_type=chart_type, chart_parameters=raw)` (the on-disk dict, minus the popped
     `chart_type`). On any failure append `visualization_id` to `rebuild_failures`, skip.
  5. Read `dashboards` + `dashboard_tiles` ordered by `ordinal`; rebuild each `Dashboard` with
     its `DashboardTile`s (incl. `tile_id`) in `ordinal` order. Dangling `visualization_id`
     kept as-is (§3).
  6. `return WorkspaceSnapshot(datasets=<topo>, visualizations=<rebuilt>, dashboards=<rebuilt>,
     rebuild_failures=sorted(rebuild_failures))`.
- [ ] **Step 4 — run the C-3 suite to green.** `pytest tests/persistence/ -q` → **8 passed**.
  Iterate on the implementation only. **If a test looks wrong, STOP and flag it — do not edit
  a test to pass.**
- [ ] **Step 5 — types + format.** `python -m mypy uadas_core/persistence --ignore-missing-imports
  --follow-imports=silent` → clean; `python -m black --check` + `python -m isort --check-only`
  on `uadas_core/persistence tests/persistence` → clean.
- [ ] **Step 6 — commit.** `feat(phase-1.6): PersistenceService save/load workspace round-trip`

### Task A5: bootstrap registration + CI mypy scope + architecture doc

**Files:** `uadas_core/core/bootstrap.py`, `.github/workflows/ci.yml`, `docs/ARCHITECTURE.md`.

- [ ] **Step 1 — bootstrap.** After the `JobRunner` registration (`bootstrap.py:260`), add the
  `from uadas_core.persistence.persistence_service import PersistenceService` import (top of
  file, in the `uadas_core.*` block) and
  `container.register(PersistenceService, lambda: PersistenceService(), singleton=True)` +
  `logger.debug("Registered PersistenceService into the dependency container.")`. Add a bullet
  to `bootstrap()`'s docstring service list.
- [ ] **Step 2 — CI mypy.** In `.github/workflows/ci.yml`'s `mypy (clean packages)` `run:`
  list, add `uadas_core/persistence` next to `uadas_core/results`, + a one-line comment
  ("Web-transition 1.6: new Qt-free persistence package, genuinely clean").
- [ ] **Step 3 — architecture doc.** `docs/ARCHITECTURE.md`: add the `PersistenceService`
  registration step to the startup sequence; add a short "Persistence" subsection near the
  workspace-model section (per-project `<name>.workspace/workspace.db` + Parquet frames;
  `save_workspace`/`load_workspace`; figures re-derived; `load_snapshot` restore path;
  non-cascading orphans round-trip).
- [ ] **Step 4 — verify.** `python -m mypy <full CI list> uadas_core/persistence
  --ignore-missing-imports --follow-imports=silent` → `Success`. `lint-imports` → contract
  KEPT. `python -m bandit -r uadas_core -q --skip B101,B107,B608` → exit 0.
- [ ] **Step 5 — commit.** `feat(phase-1.6): register PersistenceService in bootstrap; CI mypy + docs`

### Part A exit criteria (before merge)

- `pytest tests/persistence/ tests/services/test_workspace_service.py -q` all green.
- Per-commit `code-reviewer` = APPROVE on A1, A2, A4, A5 (A3 = red tests, note only).
- `mypy` CI list + `uadas_core/persistence` clean; `lint-imports` green; `bandit` exit 0.
- No change to any existing `uadas_core` behaviour beyond the 3 additive items.

---

## PART B — Desktop-shell wiring + verification (inline, main session, after merge)

### Task B1: `ProjectController` + `main_window.py` wiring (§9)

- [ ] Inject `persistence_service: PersistenceService` into `ProjectController.__init__`
  (after `workspace_service`); resolve + pass it in `main_window.py::_build_controllers`
  (`container.resolve(PersistenceService)` — typed since 1.4).
- [ ] Helper `_workspace_base(project) -> Path` per §5.1 (strip `.uads.json` if present else
  full name; `parent / (stem + ".workspace")`).
- [ ] **Save** (`save_project`, `save_project_as`): keep the existing `save_project(...)`.
  Then snapshot `workspace_service.list_datasets()/list_visualizations()/list_dashboards()` on
  the UI thread and `self._worker_runner.run(self._persistence_service.save_workspace,
  datasets, visualizations, dashboards, base, on_result=self._on_workspace_saved,
  on_error=..., on_finished=self._status_bar.hide_busy)`. `_on_workspace_saved(report)` →
  `_warn_about_skipped_visualizations(report.skipped_visualization_ids)`. **Suppress**
  `_warn_about_skipped_datasets` for `record_datasets`'s derived-dataset skips on this path
  (§9 — now persisted).
- [ ] **Open** (`open_project_at_path`): after `_project_service.open_project`, compute `base`;
  if `base.is_dir()` → `self._worker_runner.run(self._persistence_service.load_workspace, base,
  on_result=self._on_workspace_loaded, ...)` and **return** (skip `_reload_project_datasets`).
  `_on_workspace_loaded(snapshot)` (UI thread) → `workspace_service.load_snapshot(snapshot.datasets,
  snapshot.visualizations, snapshot.dashboards)`; `dock_manager.refresh_dataset_list(
  workspace_service.list_datasets())`; `_state_bus.request_refresh()`; if
  `snapshot.rebuild_failures` → `QMessageBox.warning` listing them. Else → existing
  `_reload_project_datasets(project)`.
- [ ] `_warn_about_skipped_visualizations` — copy `_warn_about_skipped_datasets`'s shape
  (`:354-372`), wording adjusted ("could not be saved because their dataset is closed").
- [ ] `python -m mypy` on the CI list (includes `src/ui/controllers`) → clean.

### Task B2: controller round-trip test

- [ ] Append to `tests/ui/controllers/test_project_controller.py` (offscreen, existing
  fixtures): build a controller, add root + derived dataset + a viz + a dashboard,
  `save_project_as(tmp_path/"p.uads.json")`, then a fresh controller sharing a fresh
  `WorkspaceService`, `open_project_at_path(tmp_path/"p.uads.json")`, assert both datasets
  present (incl. derived, by id) and the viz rebuilt. Use the worker-runner's synchronous
  test mode if present, else `qtbot.waitUntil`.
- [ ] `pytest tests/ui/controllers/test_project_controller.py -q` green.

### Task B3: full verification

- [ ] Two-invocation suite (CI mirror), `QT_QPA_PLATFORM=offscreen`:
  `python scripts/run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q --tb=no`
  then `python scripts/run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration"
  --ignore=tests/ui/test_worker_runner.py --tb=no`. Expect **1420 + 8 + (workspace unit tests)
  + 2 structural**, 92 skipped, 0 failed. Any other delta → investigate.
- [ ] `python scripts/screenshot_app_state.py --output <scratch>.png` → **byte-identical** to
  `plans/baseline-app.png` (16,294 bytes).
- [ ] `mypy` CI list + `uadas_core/persistence` → `Success`. `lint-imports` green.
  `bandit -r src uadas_core -q --skip B101,B107,B608` → exit 0. `black --check` /
  `isort --check-only` on `src/ uadas_core/ tests/` → clean.

### Task B4: end-of-range review (whole 1.6 commit range)

- [ ] `ecc:security-reviewer` **×2 non-author passes** — (1) SQL construction
  (parameterisation, the DDL, `executescript`/`executemany`), (2) filesystem path handling
  (`dataset_id` validation, `base` join, GC `unlink`, the `.tmp` swap, Save-As). B608 is
  CI-`--skip`ped — these are the only injection gate. Both to APPROVE / no unresolved HIGH+.
- [ ] `code-reviewer` (repo) over the whole 1.6 range.
- [ ] `architect` (repo) — boundary check: `uadas_core/persistence` Qt-free; the
  `ProjectController` seam matches §9; `load_snapshot` doesn't weaken `WorkspaceService`'s
  interactive-caller invariants.
- [ ] Apply worthwhile findings; record YAGNI/deferred in a new
  `plans/phase-1-6-persistence-contract.md` §10 "As-built + review" (mirroring 1.3's §11).

### Task B5: land it

- [ ] Update `plans/phase-1-baseline.md` — post-1.6 suite counts + the +8/+N/+2 breakdown.
- [ ] Update `.superpowers/sdd/phase-1/progress.md` — 1.6 `[x]` with commit range + verdicts;
  you-are-here → 1.7.
- [ ] Push; wait for CI (`gh` at `C:\Program Files\GitHub CLI\gh.exe`); confirm `test` /
  `lint` / `linux_import` / `uia_integration` green (`linux_import` is the proof
  `uadas_core.persistence` imports Qt-free).
- [ ] Report; **stop for the user's 1.7 go-ahead.**

---

## Self-review (2026-09-09)

- **Spec coverage:** contract §1/§2/§3 → A4; §2.5 → A2; §3 `tile_id` → A1; §4 → A3+A4; §5
  API/base/GC/atomicity → A4; §5 bootstrap → A5; §6 SQL/uuid4 → A4 + B4(security); §9 shell
  wiring → B1; §9 ci.yml/docs → A5. The 8 C-3 tests are enumerated verbatim from §4.
- **No placeholders:** every code step carries real code or a precise numbered procedure.
- **Type consistency:** `save_workspace(datasets, visualizations, dashboards, base)` /
  `load_workspace(base)` / `SaveReport.skipped_visualization_ids` /
  `WorkspaceSnapshot.{datasets,visualizations,dashboards,rebuild_failures}` /
  `WorkspaceService.load_snapshot(datasets, visualizations, dashboards)` — identical in the
  contract, this plan, and the test list.
- **Split rationale:** Part A is Qt-free, fully specified, abortable → worktree `implementer`.
  Part B is Qt + threading + screenshot → inline under direct review.
