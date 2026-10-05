# Architecture

This document describes the architecture of Universal AI Data Analytics & Visualization Studio
as currently implemented — not the full aspirational scope described in
[SPECIFICATION.md](../SPECIFICATION.md), which is a superset of what exists today. See
[CLAUDE.md](../CLAUDE.md) for the canonical, actively-maintained architecture reference; this
document expands on it for readers working outside a Claude Code session.

The repository is a **Qt-free Python core (`uadas_core/`) plus its tests**. It began as a PySide6
desktop application and is mid-transition to a web application
([plans/web-transition-glass-box-studio.md](../plans/web-transition-glass-box-studio.md)); the Qt
desktop shell was deleted in Phase 2.5 (last commit containing it: `8d3ec4d`). There is currently
no UI and no runnable application — application startup and UI composition return in Phase 4,
when the web UI is built. The verification floor until then is the test suite, `lint-imports`
and CI.

## Module layout and dependency direction

Web-transition Phase 1 carved the Qt-free core out of the old `src/` tree into a top-level
**`uadas_core/`** package (machine-checked by `.importlinter`: nothing in `uadas_core/` may
import PySide6 / PyQt / Django). Phase 2 then lifted the last Qt-free pieces of the shell into
it and deleted the rest; `src/` no longer exists.

```
uadas_core/          # the Qt-free core (import-clean of any GUI toolkit / web framework)
├── bootstrap.py     # bootstrap_process() + build_session() (process vs per-user services); legacy bootstrap() composes them
├── command_stack.py # real undo/redo built on the never-mutate-in-place cleaning contract (milestone 23)
├── models/          # Dataset / Visualization / Dashboard / DashboardTile / Project value types (extracted from services in Phase 2.2)
├── core/            # config, logging, DI container, exceptions, constants — the lowest layer
├── services/        # SettingsService, ProjectService, WorkspaceService, AnalysisOrchestratorService — depends on core
├── readers/         # CSV/JSON/Text/Excel/SQLite/PDF/Word/XML/Image/Archive readers — depends on core, services
├── cleaning/        # duplicate/missing-value/text/type-conversion operations — depends on core, services
├── analysis/        # column/dataset profiling, correlation, aggregation, crosstab, Explanation — depends on core, services, readers
├── forecasting/     # exponential smoothing, Prophet — depends on core
├── visualization/   # BaseChart + categorical/continuous/distribution charts, dashboard renderer — depends on core, services
├── ai/              # LLM provider abstraction, tool registry, assistant service — depends on core, services, cleaning, analysis, forecasting
├── database/        # BaseDatabaseConnection + Postgres/MySQL/SQL Server/Oracle/DuckDB connectors, DatabaseReader (milestone 14)
├── plugins/         # plugin manager + loader + built-in plugin categories (milestone 12)
├── reports/         # report exporters (HTML/PDF/…) + the report-generation wizard backend (milestone 13)
├── results/         # Qt-free result-renderer registry + section models (lifted from the old shell's results package in web-transition 1.5)
├── actions/         # action catalogue data (ActionSpec / action_registry) — no handlers, no QAction (lifted in Phase 2.1)
├── theme/           # semantic colour/space/type design tokens + contrast checker (lifted in Phase 2.1)
├── a11y/            # contrast_manifest — the foreground/background token pairings that must meet WCAG 2.2 AA (lifted in Phase 2.1)
├── help/            # in-app manual model: ManualIndex anchor resolver + ManualRenderer (lifted in Phase 2.1)
├── data_table/      # per-dtype dataframe cell formatters (lifted in Phase 2.1)
├── jobs/            # JobRunner protocol + ThreadPoolExecutorJobRunner + the process-wide default runner (web-transition 1.2)
├── persistence/     # PersistenceService — SQLite metadata + Parquet frames, per-project <stem>.workspace/ (web-transition 1.6)
└── provenance/      # analysis_logs_to_dag / analysis_logs_to_recipe — a read-only lineage view over the AnalysisLog set (web-transition 1.7)

tests/                # mirrors uadas_core/'s package layout, plus tests/assets/ (guards assets/ui-contract/)
assets/ui-contract/   # data mined from the deleted Qt shell (layout, copy, constants, a11y rules, behaviour rules)
resources/web/        # chart_host.html + chart_bridge.js + the vendored Plotly bundle — the chart host page that survived
```

> The dataclasses that used to live beside their consumers (`Dataset`, `Visualization`,
> `Dashboard`, `DashboardTile`, `Project`) were extracted into `uadas_core/models/` in Phase 2.2
> so that `core` can sit at the bottom of the layered-import stack without importing upward
> into `services`. `AnalysisLog` still lives in `analysis_orchestrator_service.py`.

Dependency direction is one-way down the package list: `core` sits at the bottom and depends on
nothing above it; `services`, `readers`, `cleaning`, `analysis`, `forecasting`, and
`visualization` build on it; `ai` depends on most of them. `.importlinter` enforces this with
five contracts: (1) `uadas_core` must not import PySide6 / PyQt / Django, (2) only `provenance`
itself may import `uadas_core.provenance` (it is a leaf), (3) a `layers` contract that
makes the subpackages a strict dependency stack (with **no** `ignore_imports`: the two old
exemptions were removed by typing `AssistantService`'s workspace and `ApplicationState`'s
values as Protocols), (4) `uadas_core` must not import `uadas_api`, and (5) `uadas_api` must not
import `uadas_core.plugins` / `.jobs` (four ignored edges, all from `uadas_core.bootstrap`, the
composition root). Run `PYTHONPATH=apps/api lint-imports` to check them.

## Application startup sequence

Startup (`uadas_core/bootstrap.py`) has two halves, split in the Phase 3 **core session seam**
(design and limits: [plans/phase-3-session-seam.md](../plans/phase-3-session-seam.md)):

* **`bootstrap_process(*, server_mode=False, config=None)`** → `ProcessContext` — the
  process-wide, tenant-free world, built once: config, logging, the built-in registries, the
  `JobRunner`, `PersistenceService` (and, outside server mode, `PluginManager`). Its container is
  the *parent* of every session.
* **`build_session(process)`** → a *child* `DependencyContainer` holding the stateful per-user
  services (`ApplicationState`, `SettingsService`, `ProjectService`, `WorkspaceService`,
  `AnalysisOrchestratorService`, `GuidanceService`, `ReportService`, `DatabaseConnectionService`).
  Two sessions from one process share no mutable service state.
* **`bootstrap()`** — the legacy single-user entry point, unchanged in result: one process plus
  one session, returning the same `BootstrapContext` (config, container, state) and still the only
  caller of `set_default_job_runner`. (The old entry path `main.py` → `Application.create()` →
  `bootstrap()` went away with the Qt shell; a new application entry point returns in Phase 4.)

`server_mode=True` (plan 3.8's server half) makes the desktop-shaped behaviours impossible:
plugins are never loaded (the plugin package is not imported, no `PluginManager` exists,
`sys.path` is untouched); no YAML is read or written (config comes from the passed `AppConfig`
or `AppConfig.defaults()`, and sessions get in-memory `SettingsService`s); logging goes to stderr
through a handler on the `uadas_core` logger only (`propagate=False`) — no rotating files and the
host's root logger is never touched; the process-global default-runner bridge is not installed.
The mode is a **one-way latch** (`uadas_core/core/process_mode.py`): a process that bootstrapped in
one mode raises `BootstrapError` on any call for the other, and `configure_logging` refuses to
switch mode too. Services log names/ids and settings key paths, never object reprs or values. The
API reaches all of this through `apps/api/uadas_api/core_bridge.py`.

The fixed order inside `bootstrap_process` (unchanged from the old `bootstrap()`):

1. **`AppConfig.load()`** (`uadas_core/core/config.py`) — reads `config/config.yaml`; self-healing,
   writes a default file if missing or empty. Deliberately does not import the project logger,
   since logging configuration is itself sourced from config — it uses a bare
   `logging.getLogger` for its own bootstrap-time messages. (Server mode skips the file entirely.)
2. **`configure_logging()`** — must run only after config is loaded, since log level/rotation
   settings come from it. (`log_dir=None` selects console-only logging, used by server mode.)
3. **`DependencyContainer` constructed**, `AppConfig` registered into it.
4. **Built-in registries populated** — `bootstrap_process()` calls `_register_builtins()` on
   `uadas_core/cleaning/operation_registry.py`, `uadas_core/visualization/chart_registry.py`, and
   `uadas_core/results/result_renderer_registry.py`. Before the desktop→web transition's step 1.3
   these ran as a side effect of *importing* each registry module; they now run here so that
   importing `uadas_core` has no global-state effect (Phase-3 backend / multi-instance
   readiness). Each `_register_builtins()` is idempotent (a module-level `_builtins_registered`
   flag, mirroring `logger._configured`). Must precede step 6 — `PluginManager.load_plugins()`
   registers plugin-provided operations and chart types into these same registries. The test
   suite seeds them from `tests/conftest.py` (module level) instead of calling `bootstrap()`.
5. **`PluginManager` constructed and `load_plugins()` run** (desktop mode only; the import is
   deferred into that branch), then `JobRunner` registered, then `PersistenceService` registered
   (web-transition 1.6 — the Qt-free workspace save/load singleton; stateless, so process-wide).
   The `set_default_job_runner()` bridge is *not* installed here — only the legacy `bootstrap()`
   does that.

`build_session()` then constructs, in dependency order, `ApplicationState`, `SettingsService`
(persisting to the YAML path in desktop mode, in memory when `process.config_path is None`),
`ProjectService`, `WorkspaceService`, `AnalysisOrchestratorService`, `GuidanceService`,
`ReportService` and `DatabaseConnectionService`, each registered into the *session* container.
That is the end of startup: there is no event loop, window, or theme-application step. In the
Qt era `Application.run()` consumed the context to construct the single `QApplication`; the
Phase 4 web UI's composition root is `uadas_api.core_bridge` on top of the same two functions.

## Dependency container

`uadas_core/core/dependency_container.py` is a minimal service locator: `register(key, factory,
singleton=True)` / `resolve(key)`. Keys are conventionally the service's type. Registration is
lazy — a factory only runs on first `resolve()` call, and (for singletons) only once (guarded by
a re-entrant lock, so concurrent first resolutions build it once).

`DependencyContainer(parent=None)` adds **scoping**: a child resolves its own registrations
first and falls back to its parent; `is_registered` consults the chain; a registration in a child
never leaks to the parent or a sibling. A singleton in the parent is shared by every child, one
in a child is per-child — which is exactly how process-wide services and per-session services
coexist (`ProcessContext.container` is the parent, each `build_session()` result a child).
`parent=None` keeps the original behaviour and errors. New process-wide services are registered
in `bootstrap_process()` and new per-user ones in `build_session()` — not constructed ad hoc
inside other services or any future UI/backend code. If a service holds mutable per-user state it
belongs in `build_session()`; putting it in the process container would share it across tenants.

## The `Base*` extension-point pattern

Four packages define an abstract base class that concrete implementations plug into. All but
one share the same shape: **stateless, classmethod-only** (never instantiated), inputs
validated before real work happens.

| Base class | Package | Concrete implementations (current) |
|---|---|---|
| `BaseReader` | `uadas_core/readers/base_reader.py` | CSV, JSON, Text, Excel, SQLite, PDF, Word, XML, Image |
| `BaseOperation` | `uadas_core/cleaning/base_operation.py` | duplicates, missing values, text normalization, type conversion |
| `BaseChart` | `uadas_core/visualization/base_chart.py` | categorical (bar/pie), continuous, distribution charts |
| `BaseLLMProvider` | `uadas_core/ai/llm_provider.py` | Anthropic, Gemini, Groq |

`BaseLLMProvider` is the one exception to "stateless classmethod-only" — it holds a real SDK
client and conversation history, since a provider genuinely needs instance state. Each provider
translates its own SDK's message/tool-call wire format to/from a shared `LLMTurn`/
`PendingToolCall` representation, so `AssistantService`'s tool-dispatch loop never branches on
which provider is active.

**Cleaning operations never mutate a `Dataset` in place** — every operation returns a new
`Dataset` with `parent_dataset_id` set to the source's ID and `derivation_description`
explaining the change. This is what makes dataset lineage (and eventually undo) possible.

## Workspace model

`WorkspaceService` (`uadas_core/services/workspace_service.py`) is the session-scoped, in-memory
registry of everything loaded or created during a run. It does not read files or build charts
itself — it only tracks what other layers produced.

- **`Dataset`** — wraps a `pandas.DataFrame` plus lineage (`parent_dataset_id`,
  `derivation_description`). `row_count`/`column_count` are derived in `__post_init__`, never
  passed in.
- **`Visualization`** — references its `Dataset` by ID, not by holding the object, so closing a
  dataset doesn't require walking every visualization to null out a reference.
- **`Dashboard`/`DashboardTile`** — a grid arrangement referencing `Visualization`s by ID, same
  pattern.

**Referential integrity is checked at *add* time** (`add_visualization` rejects an unknown
`dataset_id`), but **closing a dataset/visualization does not cascade** to things derived from
it — orphaned references are treated as normal, expected state that dependent lookups
(`get_lineage`, `get_dashboard_tiles`) handle gracefully rather than as corruption to guard
against.

## Persistence

`uadas_core/persistence/persistence_service.py` (`PersistenceService`, web-transition 1.6)
round-trips a workspace to a per-project `<project-stem>.workspace/` directory beside the
`.uads.json`: a `workspace.db` (SQLite metadata — `datasets`, `visualizations`, `dashboards`,
`dashboard_tiles`) plus one `{dataset_id}.parquet` per dataset frame. It supersedes
`ProjectService.record_datasets`, which persisted only `{name, source_path}` and dropped
derived datasets (no `source_path` to re-read from).

- **Stateless bootstrap singleton.** Two pure verbs —
  `save_workspace(datasets, visualizations, dashboards, base) -> SaveReport` and
  `load_workspace(base) -> WorkspaceSnapshot` — that take/return plain data, so a caller can run
  them on a worker thread or job (the old desktop shell did). State is installed back into the
  live `WorkspaceService` singleton via the **`WorkspaceService.load_snapshot(...)`** restore
  entry point (the non-interactive peer of `add_dataset`/`add_visualization`/`add_dashboard`:
  it installs the lists as-is, tolerating dangling `parent_dataset_id` / tile
  `visualization_id`, and only rejects a `parent_dataset_id` cycle).
- **Figures are never stored** — each `Visualization` figure is re-derived on load through
  `chart_registry` (a figure is a pure function of frame + params; storing it only creates
  stale-figure bugs). A figure that cannot be rebuilt (column gone, plugin chart disabled) is
  isolated: dropped, its id returned in `WorkspaceSnapshot.rebuild_failures`, the rest of the
  project still loads. Structural corruption (unreadable `.db`, non-uuid4 `dataset_id`,
  `parent_dataset_id` cycle, row/column-count checksum mismatch, missing frame) aborts the
  whole load with `ServiceError`.
- **Non-cascading orphans round-trip** unchanged — a derived dataset whose parent was closed,
  a dashboard tile pointing at a closed visualization. No FK is declared on
  `datasets.parent_dataset_id` or `dashboard_tiles.visualization_id` for exactly that reason.
- Save is full-replace and its **ordering is load-bearing** (Phase 2.7, diagnosis D4 — see
  `save_workspace`'s docstring): frames are staged as `<id>.parquet.tmp` and the DB is built at
  `workspace.db.tmp`; only once both are complete are the frames promoted into place
  (`os.replace`, atomic per file) and *then* `workspace.db` swapped in; orphaned `.parquet`
  frames are garbage-collected only **after** the swap, because until then the previous DB may
  still reference them. A failure before the swap discards the staging files and rolls back newly
  promoted frames, so the previous workspace stays loadable; a hard process kill leaves at worst
  harmless extra frames or `.tmp` files that the next save clears.
  `tests/persistence/test_persistence_atomicity.py` injects each failure. Save-As is just a full
  `save_workspace` to the new base.
- `dataset_id` is uuid4-validated before it is ever joined into a filesystem path; all SQL is
  `?`-parameterized against a static DDL string.

## Provenance DAG & Recipe

`uadas_core/provenance/` (web-transition 1.7) is a Qt-free, read-only *view* over
`AnalysisOrchestratorService`'s per-dataset `AnalysisLog` set — it changes nothing for existing
callers and the services layer never imports it back. `analysis_logs_to_dag(logs, datasets)`
reshapes the flat, one-log-per-dataset history into the cross-dataset lineage graph that Phase
5's transparency features (F1 provenance graph, F2 replayable recipes, F3 time-travel/fork, F10
local-first privacy) build on. The single predicate for "this log entry produced a derived
dataset" is `"new_dataset_id" in entry.outputs` — never the `stage`.

- **Three DAG elements.** A `DatasetNode` per dataset id mentioned anywhere in the log set
  (missing `DatasetMeta` is synthesized `partial=True`, never raised); a `TransformEdge` per
  dataset-producing entry (`from` = the enclosing log's id, `to` = the new id, `outputs` kept
  verbatim); an `ArtifactNode` per non-producing entry (profile, chart, test, forecast,
  explanation), identity `(dataset_id, entry_index)`.
- **Recipe = DAG minus `outputs` minus data.** `analysis_logs_to_recipe` flattens the
  root→derived chain into positional-id (`s1`, `s2`, …) steps carrying only stage / tool /
  inputs / `produces_dataset` / explanation / origin-timestamp; `recipe_to_analysis_logs`
  replays it onto a fresh root id, re-minting the dataset ids `outputs` used to carry.
  `reproduce()` regenerates the real result payloads on actual re-execution. Linear chains
  only (a forest raises); `source_dataset.schema` stays `{}` (needs a live frame).
- **Recipe disk persistence is Phase 3.** 1.7 ships the in-memory converters plus
  `Recipe.to_dict()` / `from_dict()` and a JSON round-trip; nothing touches `project_service`
  or `PersistenceService` yet.

## Configuration

`_default_config_dict()` in `uadas_core/core/config.py` is the single source of truth for the config
shape; `validate_config_structure()` checks both a freshly loaded file and any write from
`SettingsService`. `AppConfig` is a frozen dataclass — read through its typed properties, not
by indexing a raw dict. **Adding a new config key requires updating three places together**:
`_default_config_dict`, `_TOP_LEVEL_SCHEMA`/`_NESTED_SCHEMA`, and `AppConfig.from_dict`.

## Exceptions

Every custom exception inherits from `ApplicationError` (`uadas_core/core/exceptions.py`). Current
categories: `ReaderError`, `ServiceError`, `ConfigError`, `DependencyResolutionError`,
`ApplicationStateError`, `BootstrapError`. A new subclass is added only when a caller genuinely
needs to catch that specific failure mode.

## Path resolution

All fixed paths (`config/`, `logs/`, `projects/`) are anchored to the project root via
`uadas_core/core/constants.py`'s `PROJECT_ROOT`, derived from that file's own location rather than
`Path.cwd()` — so behavior doesn't depend on the working directory the app is launched from.
`PROJECT_ROOT` is only the repository root in a source/editable checkout (in a non-editable
install `parents[2]` points into `site-packages`), so the override-aware accessors
`data_root()` / `config_file_path()` / `log_dir()` / `projects_dir()` honour the
`UADAS_DATA_ROOT` environment variable (must be absolute — a relative value raises `ConfigError`;
it is normalised) and otherwise return exactly the `PROJECT_ROOT`-anchored constants. `bootstrap()` uses them for its defaults; server mode needs none of them (it reads and
writes no config or logs).

## The removed Qt shell

There is no Qt layer any more: the PySide6 shell (`src/ui`, `src/workers`, `src/app.py`,
`main.py`) was deleted in Phase 2.5, and `uadas_core/` must stay Qt-free (`.importlinter`
contract 1, plus a CI step that asserts no Qt binding is importable). The facts worth keeping
from it — default dock layout, menus and command palette, UI constants and stylesheet metrics,
file-picker filters, mapping tables, user-facing strings, accessibility rules, and the product
rules with their rejected alternatives — were mined into data under
[`assets/ui-contract/`](../assets/ui-contract/) (start with `ui-behaviour-rules.md`) and are
guarded by `tests/assets/`. See [CLAUDE.md](../CLAUDE.md#the-removed-qt-shell-and-where-its-facts-live)
for the canonical summary. The chart host page (`resources/web/chart_host.html`,
`chart_bridge.js`) survives. Docstrings that still name `src.ui.*`, `MainWindow` or controllers
describe the deleted shell and are kept as design history.

## Important architectural constraints to preserve

- **Milestone-by-milestone development**: each milestone must be complete and integrated with
  everything before it, not a stub — see the Roadmap document for the milestone sequence this
  codebase has actually followed.
- **Multi-file touchpoints that do not auto-sync**: adding a reader requires updating both
  `reader_registry.py`'s `_BUILTIN_READERS` tuple *and* the file-picker filter groups in
  `assets/ui-contract/file-picker-filters.json` (which replaced the old hardcoded
  `_DATASET_FILE_FILTER` string in the deleted `src/ui/main_window.py`) — the second does not
  derive from the first automatically, but `tests/assets/` fails if their extension sets differ.
- **A real test suite and enforced tooling exist and are CI-gated.** `tests/` mirrors
  `uadas_core/`'s package layout (plus `tests/assets/`, which guards `assets/ui-contract/`);
  there are no pytest markers and no Qt, so the suite is plain pytest and runs the same on any OS.
  `black`, `isort`, `mypy` (scoped to a curated clean-package list — see
  [docs/MYPY_DEBT.md](MYPY_DEBT.md)), `ruff`, and `bandit` all have committed configuration in
  `pyproject.toml` with pinned versions in `requirements.txt`. `.github/workflows/ci.yml` is a
  single Linux (`ubuntu-latest`) workflow with three jobs: `test` (assert no Qt binding is
  importable, import `uadas_core`, scoped `mypy`, a collected-test floor so a shrinking suite
  fails, then `python -m pytest tests/`), `lint` (`ruff check`, `lint-imports`, `bandit`,
  `black --check`, `isort --check-only`), and `dco` (Signed-off-by on every PR commit). Running
  on Linux — the Phase-3 web-backend target — means a Windows-only assumption in the core fails
  CI instead of surviving until deployment. `ruff` and `bandit` are *also* enforced pre-CI by
  `.claude/hooks/` (on every Edit/Write and `git commit`) and by `.pre-commit-config.yaml`.
  "Tests pass" (and "lint/type/security checks pass") is a meaningful verification signal — see
  [CLAUDE.md](../CLAUDE.md#commands) for the exact commands (the full suite is just
  `python -m pytest tests -q`). Keep this note current going forward: it went stale once already
  (written when milestone 16 first observed the opposite state, then claimed ruff/bandit were
  CI-gated when they were not) and nothing caught the drift until a later audit — treat a milestone
  that changes test/tooling state as also owning an update here.
- **No `uadas_core/` subpackage is an empty placeholder any more.** `database/`, `plugins/`,
  `jobs/` and `reports/` are built out (milestones 14, 12, web-transition 1.2, 13). The three
  empty scaffold packages that never had a purpose — `models/`, `resources/`, `utils/` under
  the old `src/` — were deleted in Phase 0.4 of the web-transition plan (`uadas_core/models/` is
  an unrelated, later package holding the extracted value types). See
  [docs/ROADMAP.md](ROADMAP.md#what-is-explicitly-not-built-yet) for what genuinely does not exist
  yet (all of it web-transition scope, not desktop).
