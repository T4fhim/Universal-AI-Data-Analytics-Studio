# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Universal AI Data Analytics & Visualization Studio — a PySide6 desktop app for importing, cleaning,
analyzing, visualizing, forecasting, and reporting on data, with an AI assistant layer. The full intended
scope (every planned file format, chart type, statistical method, forecasting model, and plugin category)
is recorded in [SPECIFICATION.md](SPECIFICATION.md) — the actual codebase implements this incrementally;
do not assume something described there already exists without checking `src/`.

The project is being built **milestone by milestone** (see git history and module docstrings, e.g.
"milestone 2b", "milestone 3a"). Each milestone is expected to be complete and integrated with everything
before it — not a stub — but later milestones' functionality genuinely does not exist yet. Several `src/`
subpackages are still empty directories awaiting their milestone: `database/`, `models/`, `plugins/`,
`workers/`, `reports/`, `resources/`. Check whether a module actually exists before assuming it does.

## Commands

There is no build step (pure Python). Environment: Python 3.13, dependencies in
[requirements.txt](requirements.txt), a `.venv` already present at the repo root.

```powershell
# activate the existing venv (PowerShell)
.venv\Scripts\Activate.ps1

# install/sync dependencies
pip install -r requirements.txt

# run the application
python main.py

# run tests (pytest is a declared dependency; tests/ exists but is currently empty —
# there is no pytest.ini/pyproject.toml yet, so run directly against the package)
pytest tests/
pytest tests/test_some_module.py::test_case_name   # single test

# formatting / linting / types (all declared dependencies; no config files committed yet,
# so these run with their tool defaults)
black src/ tests/
isort src/ tests/
mypy src/
```

## Architecture

### Startup sequence

`main.py` → `Application.create()` ([src/core/app.py](src/core/app.py)) → `bootstrap()`
([src/core/bootstrap.py](src/core/bootstrap.py)), which runs in a fixed order that must not be reordered:

1. `AppConfig.load()` — reads `config/config.yaml` (self-healing: writes a default file if missing/empty).
2. `configure_logging()` — must happen only after config is loaded, since logging settings come from it.
3. Construct one `DependencyContainer` and register `AppConfig` and `ApplicationState` into it.
4. Construct and register `SettingsService`, `ProjectService`, `WorkspaceService`.

`config.py` deliberately does not import the project logger (it's a dependency of the logger, not a
consumer of it) — it uses a bare `logging.getLogger` for its own bootstrap-time messages instead. Don't
"fix" this into a `get_logger` call.

`bootstrap()` returns a `BootstrapContext` (config, container, state). `Application.run()` is the only
place a `QApplication` is constructed; it applies the theme via `ThemeManager`, builds `MainWindow`, and
enters the Qt event loop.

### Dependency container

[src/core/dependency_container.py](src/core/dependency_container.py) is a minimal service locator:
`register(key, factory, singleton=True)` / `resolve(key)`. Keys are conventionally the service's type.
Register new session-wide services in `bootstrap.py` alongside the existing ones rather than constructing
them ad hoc inside UI code, so every consumer resolves the same instance.

### The `Base*` extension-point pattern

Several packages define an abstract base class that concrete implementations plug into, all following the
same shape: **stateless, classmethod-only** (never instantiated — mirrors how they're actually consumed,
as classes held in a registry, not objects), with inputs validated before real work happens:

- `src/readers/base_reader.py` → `BaseReader.can_read()` / `list_tables()` / `read()`. New format readers
  register in `src/readers/reader_registry.py`'s `_REGISTERED_READERS` tuple — that's the one place to
  touch when adding a reader.
- `src/cleaning/base_operation.py` → `BaseOperation.apply(dataset, **kwargs) -> Dataset`. **Cleaning
  operations never mutate a `Dataset` in place** — always return a new `Dataset` with `parent_dataset_id`
  set to the source's `dataset_id` and `derivation_description` explaining the change. This is what makes
  undo and dataset lineage possible; don't special-case an in-place variant.
- `src/visualization/base_chart.py` → `BaseChart.build(dataframe, **kwargs) -> go.Figure`. Charts return
  Plotly `Figure` objects directly (no custom wrapper).
- `src/ai/llm_provider.py` → `BaseLLMProvider` is the exception to "stateless classmethod-only" (it holds
  a real SDK client and conversation history). Each provider (`AnthropicProvider`, `GeminiProvider`,
  `GroqProvider`) translates its SDK's own message/tool-call wire format to/from the shared
  `LLMTurn`/`PendingToolCall` shape, so `AssistantService`'s tool-dispatch loop never branches on which
  provider is active. Add a new provider by implementing `send()` / `append_user_message()` /
  `append_assistant_turn()` / `append_tool_results()` and wiring it into `create_provider()`.

When adding a new concrete implementation of any of these, follow the existing pattern in that package
rather than inventing a new shape.

### Workspace model (`src/services/workspace_service.py`)

`WorkspaceService` is the session-scoped, in-memory registry of everything loaded or created during a run
— it does not read files or build charts itself, only tracks what other layers produced:

- `Dataset` — wraps a `pandas.DataFrame` plus lineage (`parent_dataset_id`, `derivation_description`).
  `row_count`/`column_count` are derived in `__post_init__`, never passed in, so they can't disagree with
  the actual dataframe.
- `Visualization` — references its `Dataset` by ID (not by holding the object), so closing a dataset
  doesn't require walking every visualization to null out a reference.
- `Dashboard` / `DashboardTile` — a grid arrangement referencing `Visualization`s by ID, same pattern.

Referential integrity is checked at *add* time (e.g. `add_visualization` rejects an unknown
`dataset_id`), but closing a dataset/visualization does **not** cascade to things derived from it —
orphaned references are treated as normal, expected state that dependent lookups (`get_lineage`,
`get_dashboard_tiles`) handle gracefully rather than as corruption to guard against. Preserve this
non-cascading behavior when extending these methods.

### Configuration (`src/core/config.py` + `config/config.yaml`)

`_default_config_dict()` is the single source of truth for the config shape; `validate_config_structure()`
checks both a freshly loaded file and any write from `SettingsService`, so the two can never drift apart.
`AppConfig` is a frozen dataclass — read config through its typed properties, not by indexing a raw dict.
Adding a new config key means updating `_default_config_dict`, `_TOP_LEVEL_SCHEMA`/`_NESTED_SCHEMA`, and
`AppConfig.from_dict` together.

### Exceptions

Every custom exception inherits from `ApplicationError` ([src/core/exceptions.py](src/core/exceptions.py)).
Add a new subclass only when some caller genuinely needs to catch that specific failure mode — not as
speculative coverage. `ReaderError`, `ServiceError`, `ConfigError`, `DependencyResolutionError`,
`ApplicationStateError`, `BootstrapError` are the existing categories; reuse them where they fit before
adding a new one.

### Path resolution

All fixed paths (`config/`, `logs/`, `projects/`) are anchored to the project root via
`src/core/constants.py`'s `PROJECT_ROOT` (derived from that file's own location, not `Path.cwd()`), so
behavior doesn't depend on the working directory the app is launched from.

## Conventions to follow

- Every module has a `# File: <path>` comment as its first line, followed by a module docstring explaining
  *why* the module exists and how it relates to neighboring modules — not just what it does. Follow this
  for new files.
- Docstrings on classes/functions document rationale and cross-reference related classes with Sphinx-style
  `:class:`/:meth:` roles, even though no Sphinx build is currently wired up.
- Type hints throughout, `from __future__ import annotations` at the top of every module.
- Comments frequently explain *why a simpler-looking alternative was rejected* (e.g. why a deep copy is
  required, why an error is swallowed instead of raised). When editing existing code, preserve or update
  that reasoning rather than deleting it — it's load-bearing context for the next change, not filler.
