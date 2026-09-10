# Architecture

This document describes the architecture of Universal AI Data Analytics & Visualization Studio
**as currently implemented in `src/`** — not the full aspirational scope described in
[SPECIFICATION.md](../SPECIFICATION.md), which is a superset of what exists today. See
[CLAUDE.md](../CLAUDE.md) for the canonical, actively-maintained architecture reference; this
document expands on it for readers working outside a Claude Code session.

## Module layout and dependency direction

```
src/
├── core/          # config, logging, DI container, bootstrap, exceptions, constants — depends on nothing else in src/
├── services/      # SettingsService, ProjectService, WorkspaceService — depends on core
├── readers/       # CSV/JSON/Text/Excel/SQLite/PDF/Word/XML/Image readers — depends on core, services
├── cleaning/      # duplicate/missing-value/text/type-conversion operations — depends on core, services
├── analysis/      # column/dataset profiling, correlation, aggregation, crosstab — depends on core, services, readers
├── forecasting/   # exponential smoothing, Prophet — depends on core
├── visualization/ # BaseChart + categorical/continuous/distribution charts, dashboard renderer — depends on core, services
├── ai/            # LLM provider abstraction, tool registry, assistant service — depends on core, services, cleaning, analysis, forecasting
├── ui/            # PySide6 main window, dialogs, widgets, dock/menu/toolbar/theme managers — depends on everything above
├── database/      # BaseDatabaseConnection + PostgreSQL/MySQL/SQL Server/Oracle/DuckDB connectors, DatabaseReader (milestone 14)
├── plugins/       # plugin manager + loader + built-in plugin categories (milestone 12)
├── workers/       # BaseWorker (QRunnable) + WorkerRunner — async work off the UI thread (milestone 6)
└── reports/       # report exporters (HTML/PDF/…) + the report-generation wizard backend (milestone 13)
```

> `src/models/`, `src/resources/`, and `src/utils/` were empty scaffold directories that no
> milestone ever populated; they were removed in Phase 0.4 of the desktop→web transition
> (`plans/web-transition-glass-box-studio.md`). QSS theme files live in `resources/styles/` at the
> repo root — referenced directly by `ThemeManager`, never through a `src/` package. Dataclasses in
> this codebase are co-located with their consumers (`Dataset` in `workspace_service.py`,
> `AnalysisLog` in `analysis_orchestrator_service.py`), not gathered into a central `models/`
> package.

Dependency direction is one-way down this list: `core` depends on nothing else in `src/`;
`ui` is the only package that depends on nearly everything else. Nothing in `core`, `services`,
`readers`, `cleaning`, `analysis`, `forecasting`, or `visualization` imports from `ui`.

## Application startup sequence

`main.py` → `Application.create()` (`src/app.py`) → `bootstrap()` (`uadas_core/core/bootstrap.py`),
in a fixed order:

1. **`AppConfig.load()`** (`uadas_core/core/config.py`) — reads `config/config.yaml`; self-healing,
   writes a default file if missing or empty. Deliberately does not import the project logger,
   since logging configuration is itself sourced from config — it uses a bare
   `logging.getLogger` for its own bootstrap-time messages.
2. **`configure_logging()`** — must run only after config is loaded, since log level/rotation
   settings come from it.
3. **`DependencyContainer` constructed**, `AppConfig` and `ApplicationState` registered into it.
4. **Built-in registries populated** — `bootstrap()` calls `_register_builtins()` on
   `uadas_core/cleaning/operation_registry.py`, `uadas_core/visualization/chart_registry.py`, and
   `uadas_core/results/result_renderer_registry.py`. Before the desktop→web transition's step 1.3
   these ran as a side effect of *importing* each registry module; they now run here so that
   importing `uadas_core` has no global-state effect (Phase-3 backend / multi-instance
   readiness). Each `_register_builtins()` is idempotent (a module-level `_builtins_registered`
   flag, mirroring `logger._configured`). Must precede step 6 — `PluginManager.load_plugins()`
   registers plugin-provided operations and chart types into these same registries. The test
   suite seeds them from `tests/conftest.py` (module level) instead of calling `bootstrap()`.
5. **`SettingsService`, `ProjectService`, `WorkspaceService` constructed and registered** into
   the same container — one instance per running process, so every consumer resolves the same
   instance rather than each constructing its own. `AnalysisOrchestratorService`,
   `GuidanceService`, `ReportService`, `DatabaseConnectionService` follow, each in dependency
   order.
6. **`PluginManager` constructed and `load_plugins()` run**, then `JobRunner` registered, then
   `PersistenceService` registered (web-transition 1.6 — the Qt-free workspace save/load
   singleton; last, since it only serializes the plain-data output of the services above).

`bootstrap()` returns a `BootstrapContext` (config, container, state). `Application.run()` is
the only place a `QApplication` is constructed — before doing so it forces software OpenGL
(`AA_UseSoftwareOpenGL`, `AA_ShareOpenGLContexts`) to work around a confirmed
`QWebEngineView` blank-render bug on some Windows GPU/driver combinations — then applies the
configured theme via `ThemeManager`, builds `MainWindow`, and enters the Qt event loop.

## Dependency container

`uadas_core/core/dependency_container.py` is a minimal service locator: `register(key, factory,
singleton=True)` / `resolve(key)`. Keys are conventionally the service's type. Registration is
lazy — a factory only runs on first `resolve()` call, and (for singletons) only once. New
session-wide services are registered in `bootstrap.py` alongside the existing ones, not
constructed ad hoc inside UI code.

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
  `load_workspace(base) -> WorkspaceSnapshot` — that take/return plain data, so the desktop
  shell runs them on a worker thread. State is installed back into the live `WorkspaceService`
  singleton on the UI thread via the new **`WorkspaceService.load_snapshot(...)`** restore
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
- Save is atomic (`workspace.db.tmp` → `os.replace`) and full-replace (orphaned `.parquet`
  frames are garbage-collected); Save-As is just a full `save_workspace` to the new base.
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

## PySide6/Qt layer specifics

- **Exactly one `QApplication` per process**, constructed only in `Application.run()`.
- **Chart rendering** (`src/ui/widgets/chart_view.py`): a Plotly figure is rendered to HTML and
  loaded into a `QWebEngineView` via a temporary file + `setUrl()`, not `setHtml()` — a fully
  inlined Plotly bundle can be large enough that `setHtml()` silently fails to load.
- **Theming** (`src/ui/theme_manager.py`): `.qss` files in `resources/styles/` are applied at
  the `QApplication` level via `setStyleSheet()`, cascading to every widget; switching themes at
  runtime just re-applies a different file.
- **Dock widgets** (`src/ui/dock_manager.py`): Project Explorer and Dataset Explorer are
  tabbed together; Console and Log are tabbed together; the Chart dock is left un-tabbed since
  chart content is significant enough to want default visibility. The Logging dock attaches a
  live `logging.Handler` to the root logger and must be detached before window close.

## Important architectural constraints to preserve

- **Milestone-by-milestone development**: each milestone must be complete and integrated with
  everything before it, not a stub — see the Roadmap document for the milestone sequence this
  codebase has actually followed.
- **Multi-file touchpoints that do not auto-sync**: adding a reader requires updating both
  `reader_registry.py`'s `_REGISTERED_READERS` tuple *and* the hardcoded `_DATASET_FILE_FILTER`
  string in `src/ui/main_window.py` — the second does not derive from the first automatically.
- **A real test suite and enforced tooling exist and are CI-gated.** `tests/` mirrors `src/`'s
  package layout; `black`, `isort`, `mypy` (scoped to a curated clean-module list — see
  [docs/MYPY_DEBT.md](MYPY_DEBT.md)), `ruff`, and `bandit` all have committed configuration in
  `pyproject.toml` with pinned versions in `requirements.txt`. `.github/workflows/ci.yml` gates on
  `black`, `isort`, scoped `mypy`, and `pytest` on `windows-latest`, and — added in Phase 0.6 of the
  web-transition plan — `ruff check` + `bandit` on a `ubuntu-latest` lint job. `ruff` and `bandit`
  are *also* enforced pre-CI by `.claude/hooks/` (on every Edit/Write and `git commit`) and by
  `.pre-commit-config.yaml`. "Tests pass" (and "lint/type/security checks pass") is a meaningful
  verification signal — see [CLAUDE.md](../CLAUDE.md#commands) for the exact commands, including why
  the full suite must be run via `scripts/run_tests_and_exit_cleanly.py` in two invocations rather
  than a bare `pytest tests/`. Keep this note current going forward: it went stale once already
  (written when milestone 16 first observed the opposite state, then claimed ruff/bandit were
  CI-gated when they were not) and nothing caught the drift until a later audit — treat a milestone
  that changes test/tooling state as also owning an update here.
- **No `src/` subpackage is an empty placeholder any more.** `database/`, `plugins/`, `workers/`,
  and `reports/` are built out (milestones 14, 12, 6, 13). The three that never had a purpose —
  `models/`, `resources/`, `utils/` — were deleted in Phase 0.4 of the web-transition plan. QSS
  theme files live in `resources/styles/` at the repo root, referenced directly by `ThemeManager`,
  not through a `src/` package. See
  [docs/ROADMAP.md](ROADMAP.md#what-is-explicitly-not-built-yet) for what genuinely does not exist
  yet (all of it now web-transition scope, not desktop).
