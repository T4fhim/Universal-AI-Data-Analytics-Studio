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
├── database/      # empty — not yet built
├── models/        # empty — not yet built
├── plugins/       # empty — not yet built
├── workers/       # empty — not yet built
├── reports/       # empty — not yet built
└── resources/     # empty — not yet built
```

Dependency direction is one-way down this list: `core` depends on nothing else in `src/`;
`ui` is the only package that depends on nearly everything else. Nothing in `core`, `services`,
`readers`, `cleaning`, `analysis`, `forecasting`, or `visualization` imports from `ui`.

## Application startup sequence

`main.py` → `Application.create()` (`src/core/app.py`) → `bootstrap()` (`src/core/bootstrap.py`),
in a fixed order:

1. **`AppConfig.load()`** (`src/core/config.py`) — reads `config/config.yaml`; self-healing,
   writes a default file if missing or empty. Deliberately does not import the project logger,
   since logging configuration is itself sourced from config — it uses a bare
   `logging.getLogger` for its own bootstrap-time messages.
2. **`configure_logging()`** — must run only after config is loaded, since log level/rotation
   settings come from it.
3. **`DependencyContainer` constructed**, `AppConfig` and `ApplicationState` registered into it.
4. **`SettingsService`, `ProjectService`, `WorkspaceService` constructed and registered** into
   the same container — one instance per running process, so every consumer resolves the same
   instance rather than each constructing its own.

`bootstrap()` returns a `BootstrapContext` (config, container, state). `Application.run()` is
the only place a `QApplication` is constructed — before doing so it forces software OpenGL
(`AA_UseSoftwareOpenGL`, `AA_ShareOpenGLContexts`) to work around a confirmed
`QWebEngineView` blank-render bug on some Windows GPU/driver combinations — then applies the
configured theme via `ThemeManager`, builds `MainWindow`, and enters the Qt event loop.

## Dependency container

`src/core/dependency_container.py` is a minimal service locator: `register(key, factory,
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
| `BaseReader` | `src/readers/base_reader.py` | CSV, JSON, Text, Excel, SQLite, PDF, Word, XML, Image |
| `BaseOperation` | `src/cleaning/base_operation.py` | duplicates, missing values, text normalization, type conversion |
| `BaseChart` | `src/visualization/base_chart.py` | categorical (bar/pie), continuous, distribution charts |
| `BaseLLMProvider` | `src/ai/llm_provider.py` | Anthropic, Gemini, Groq |

`BaseLLMProvider` is the one exception to "stateless classmethod-only" — it holds a real SDK
client and conversation history, since a provider genuinely needs instance state. Each provider
translates its own SDK's message/tool-call wire format to/from a shared `LLMTurn`/
`PendingToolCall` representation, so `AssistantService`'s tool-dispatch loop never branches on
which provider is active.

**Cleaning operations never mutate a `Dataset` in place** — every operation returns a new
`Dataset` with `parent_dataset_id` set to the source's ID and `derivation_description`
explaining the change. This is what makes dataset lineage (and eventually undo) possible.

## Workspace model

`WorkspaceService` (`src/services/workspace_service.py`) is the session-scoped, in-memory
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

## Configuration

`_default_config_dict()` in `src/core/config.py` is the single source of truth for the config
shape; `validate_config_structure()` checks both a freshly loaded file and any write from
`SettingsService`. `AppConfig` is a frozen dataclass — read through its typed properties, not
by indexing a raw dict. **Adding a new config key requires updating three places together**:
`_default_config_dict`, `_TOP_LEVEL_SCHEMA`/`_NESTED_SCHEMA`, and `AppConfig.from_dict`.

## Exceptions

Every custom exception inherits from `ApplicationError` (`src/core/exceptions.py`). Current
categories: `ReaderError`, `ServiceError`, `ConfigError`, `DependencyResolutionError`,
`ApplicationStateError`, `BootstrapError`. A new subclass is added only when a caller genuinely
needs to catch that specific failure mode.

## Path resolution

All fixed paths (`config/`, `logs/`, `projects/`) are anchored to the project root via
`src/core/constants.py`'s `PROJECT_ROOT`, derived from that file's own location rather than
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
- **No test suite currently exists.** `tests/` is empty despite `pytest` being a declared
  dependency; `black`/`isort`/`mypy` have no committed configuration or CI gate. "Tests pass" is
  not currently a meaningful verification signal for this project.
- Several `src/` subpackages (`database/`, `models/`, `plugins/`, `workers/`, `reports/`,
  `resources/`) are still empty directories awaiting their milestone.
