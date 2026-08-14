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
before it — not a stub — but later milestones' functionality genuinely does not exist yet. See
[docs/ROADMAP.md](docs/ROADMAP.md#what-is-explicitly-not-built-yet) for the current list of empty/unbuilt
`src/` subpackages. Check whether a module actually exists before assuming it does.

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

Full narrative detail — startup sequence, dependency container mechanics, the workspace model,
configuration schema, and the exception hierarchy — lives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). What follows here is only the actionable rules: the
constraints that must be preserved whenever this code is touched, not the explanation of how it works.

### Startup sequence

`config.py` deliberately does not import the project logger (it's a dependency of the logger, not a
consumer of it) — it uses a bare `logging.getLogger` for its own bootstrap-time messages instead. Don't
"fix" this into a `get_logger` call. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#application-startup-sequence) for the full startup sequence
and why its order can't be changed.

### Dependency container

Register new session-wide services in `bootstrap.py` alongside the existing ones rather than constructing
them ad hoc inside UI code, so every consumer resolves the same instance. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#dependency-container) for how the container itself works.

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

### Workspace model

**Cleaning operations never mutate a `Dataset` in place** (see the `Base*` pattern above — this is the
same rule, restated because it's the constraint most likely to be violated by accident when extending
`WorkspaceService` itself). Closing a dataset or visualization does **not** cascade to things derived from
it — orphaned references (a stale `parent_dataset_id`, a dashboard tile pointing at a closed
visualization) are normal, expected state that dependent lookups handle gracefully, not corruption to
guard against. Preserve this non-cascading behavior when extending `WorkspaceService`'s methods. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#workspace-model) for the full `Dataset`/`Visualization`/
`Dashboard` model.

### Configuration

Adding a new config key means updating `_default_config_dict`, `_TOP_LEVEL_SCHEMA`/`_NESTED_SCHEMA`, and
`AppConfig.from_dict` together — all three, every time, or the two can drift apart. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#configuration) for the full schema mechanics.

### Exceptions

Add a new `ApplicationError` subclass only when some caller genuinely needs to catch that specific failure
mode — not as speculative coverage. `ReaderError`, `ServiceError`, `ConfigError`,
`DependencyResolutionError`, `ApplicationStateError`, `BootstrapError` are the existing categories; reuse
them where they fit before adding a new one. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#exceptions) for the full hierarchy.

### Path resolution

Fixed paths (`config/`, `logs/`, `projects/`) are anchored to the project root, not `Path.cwd()` — don't
introduce a new path constant that depends on the working directory the app happens to be launched from.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#path-resolution) for how the anchoring works.

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
