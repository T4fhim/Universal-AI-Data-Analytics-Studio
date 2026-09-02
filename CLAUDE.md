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
[requirements.txt](requirements.txt) (runtime and pinned dev-tool versions in one file — there is no
separate `requirements-dev.txt`), a `.venv` already present at the repo root. Tool configuration
(`black`, `isort`, `mypy`, `ruff`, `bandit`, `pytest`) lives in `pyproject.toml`.

```powershell
# activate the existing venv (PowerShell)
.venv\Scripts\Activate.ps1

# install/sync dependencies
pip install -r requirements.txt

# run the application
python main.py
```

### Tests

`tests/` mirrors `src/`'s package layout and is not empty. Two markers are declared in
`pyproject.toml` and are opt-in, not part of a default run:

- `webengine` — constructs a real `QWebEngineView`; can hang/fail to initialize offscreen, so it's
  kept as a guarded smoke test rather than the default for chart-related assertions.
- `uia_integration` — launches a real, visible top-level window in its own process and drives it
  with pywinauto's UIA backend (Windows-only). This forces `QT_QPA_PLATFORM=windows` regardless of
  the surrounding job's env, so it cannot run inside the main offscreen session; CI runs it as its
  own non-blocking job.

`tests/ui/conftest.py` requires `QT_QPA_PLATFORM=offscreen` to be set **before any PySide6 import**
— export/set it before running anything under `tests/ui/`. `pytest-qt` is installed (`qt_api =
"pyside6"` pinned in `pyproject.toml`) — its `qtbot` fixture (simulated key/mouse events,
`waitSignal`/`waitSignals`, auto-fail on exceptions in Qt virtual methods/slots) is the standard way
to write new offscreen widget tests; the existing suite predates it and hasn't been migrated
wholesale, so don't assume every existing test already uses it.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"

# single test — plain pytest is fine for iterating
pytest tests/some_package/test_some_module.py::test_case_name

# full suite — mirror CI exactly, not a bare `pytest tests/`, for two reasons documented in
# .github/workflows/ci.yml: (1) tests/ui/test_worker_runner.py's real-QThreadPool tests proved
# flaky once event-loop backpressure builds up later in a long single-process run, so it must run
# FIRST; (2) a real Windows access violation during CPython/Qt interpreter shutdown can fail the
# process *after* pytest itself already reported a fully clean result, which is why
# scripts/run_tests_and_exit_cleanly.py (calls os._exit() once pytest's real result is known) is
# used instead of a bare `python -m pytest` — see that script's own docstring for the evidence.
python scripts/run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q
python scripts/run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py

# the UIA integration tests, separately (Windows only)
pytest tests/ui/a11y/test_uia_integration.py -q -m uia_integration
```

### Formatting, linting, types, security

Versions are pinned in `requirements.txt` (`black==26.5.1`, `isort==8.0.1`, `mypy==2.1.0`,
`ruff==0.16.3`, `bandit==1.9.4`) and enforced in CI (`.github/workflows/ci.yml`), not left to
whatever the tool defaults to:

```powershell
black --check src/ tests/
isort --check-only src/ tests/
bandit -r src -q                # excludes .venv and tests per pyproject.toml [tool.bandit]
```

`mypy` is **not** run repo-wide — it's scoped to an explicit, curated list of packages/modules that
are currently clean (see the `mypy` step in `.github/workflows/ci.yml` for the authoritative list,
and [docs/MYPY_DEBT.md](docs/MYPY_DEBT.md) for what's excluded and why). Running `mypy src/`
directly will surface pre-existing debt, not a meaningful pass/fail signal; when a milestone makes
an excluded module clean, add it to that CI list rather than treating a bare repo-wide run as the
target.

`ruff` is also configured (`[tool.ruff]`), with an explicitly curated `select` list (not "ruff's
current defaults") and `ignore = ["RUF001", "RUF005"]`. Ruff's own isort rule-group (`"I"`) is
deliberately **not** enabled — `isort` (profile `black`) stays the tool of record for import order.
This matters because a `PostToolUse` hook (`.claude/hooks/quality-check.ps1`) already runs
`ruff format` + `ruff check --fix` automatically on every Edit/Write to a `.py` file — re-running
`ruff` by hand after an edit is redundant, but `black`/`isort`/`mypy`/`bandit` are not part of that
hook and still need to be run explicitly to match what CI gates on.

### Standalone git pre-commit hooks (tool-agnostic)

`.pre-commit-config.yaml` (ruff check+format, isort, plus lightweight
trailing-whitespace/YAML/large-file checks) is the enforcement layer for commits made *outside*
Claude Code — a plain terminal, another editor, another AI tool. Run `pre-commit install` once per
clone to activate it. It does not replace `.claude/hooks/pre-commit-check.ps1`'s pytest+bandit gate
below; that stays Claude-Code-specific and comprehensive, while this stays fast and tool-agnostic
per 2026 pre-commit-framework convention (fast/auto-fixing checks locally, slow/comprehensive ones
in CI).

### Other repo-enforced hooks

- `git commit` (any Bash command matching it) is intercepted by
  `.claude/hooks/pre-commit-check.ps1`, which runs the full `pytest` suite and
  `bandit -r src -q` first and blocks the commit if either fails — a commit that appears to hang or
  get rejected usually means one of those failed; check their output rather than retrying blindly.
- `.claude/hooks/protect-files.ps1` blocks Edit/Write to `.env*`, `secrets.json`,
  `credentials.json`, and `*.pem`/`*.key` files.

### Visual verification

`scripts/screenshot_app_state.py` boots the real `Application`/`bootstrap()`/`MainWindow`
composition path offscreen and saves a PNG — run it after any milestone that changes what the app
looks like, the same way the test suite and formatters/linters run after every milestone:

```powershell
python scripts/screenshot_app_state.py --output out.png
python scripts/screenshot_app_state.py --output out.png --new-project
python scripts/screenshot_app_state.py --output out.png --open-dataset path/to/file.csv
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

### PySide6/Qt layer specifics

- **Exactly one `QApplication` per process**, constructed only in `Application.run()`.
- **Chart rendering** (`src/ui/widgets/chart_view.py`): a Plotly figure is rendered to HTML and loaded
  into a `QWebEngineView` via a temporary file + `setUrl()`, not `setHtml()` — a fully inlined Plotly
  bundle can be large enough that `setHtml()` silently fails to load.
- **Theming** (`src/ui/theme_manager.py`): `.qss` files in `resources/styles/` are applied at the
  `QApplication` level via `setStyleSheet()`, cascading to every widget; switching themes at runtime just
  re-applies a different file.
- **Dock widgets** (`src/ui/dock_manager.py`): Project Explorer and Dataset Explorer are tabbed together;
  Console and Log are tabbed together; the Chart dock is left un-tabbed. The Logging dock attaches a live
  `logging.Handler` to the root logger and must be detached before window close.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#pyside6qt-layer-specifics) for more.

### Multi-file touchpoints that do not auto-sync

Adding a reader requires updating both `reader_registry.py`'s `_REGISTERED_READERS` tuple *and* the
hardcoded `_DATASET_FILE_FILTER` string in `src/ui/main_window.py` — the second does not derive from the
first automatically. Watch for the same class of gap (a registry plus a separately-hardcoded consumer)
when extending charts, cleaning operations, or plugin categories.

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
