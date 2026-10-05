# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Working method:** read [docs/RESOURCE_ORCHESTRATION.md](docs/RESOURCE_ORCHESTRATION.md) each
session alongside this file — it is the standing doctrine for phase→resource routing (which
agent / skill / model tier / MCP for which kind of work), the delegation rules, the hooks that
already run automatically, and the living-truth discipline for this repo's lagging plan docs.

## What this is

Universal AI Data Analytics & Visualization Studio — a Qt-free Python core (`uadas_core/`) for importing,
cleaning, analyzing, visualizing, forecasting, and reporting on data, with an AI assistant layer. It is
mid-transition from a PySide6 desktop app to a web application
([plans/web-transition-glass-box-studio.md](plans/web-transition-glass-box-studio.md)). **The Qt desktop
shell was deleted in Phase 2.5** (the last commit that still contains it is `8d3ec4d`), so there is
currently **no UI and no runnable application** until the Phase 4 web UI exists; the verification floor
is the test suite, `lint-imports` and CI. The full intended scope (every planned file format, chart type,
statistical method, forecasting model, and plugin category) is recorded in
[SPECIFICATION.md](SPECIFICATION.md) — the actual codebase implements this incrementally; do not assume
something described there already exists without checking `uadas_core/`.

The project is being built **milestone by milestone** (see git history and module docstrings, e.g.
"milestone 2b", "milestone 3a"). Each milestone is expected to be complete and integrated with everything
before it — not a stub — but later milestones' functionality genuinely does not exist yet. See
[docs/ROADMAP.md](docs/ROADMAP.md#what-is-explicitly-not-built-yet) for the current list of empty/unbuilt
`uadas_core/` subpackages. Check whether a module actually exists before assuming it does.

Docstrings and comments that name `src.ui.*`, `MainWindow`, controllers, dialogs or `tests/ui` describe
that deleted desktop shell and are kept as design history; the facts worth keeping from it were mined
into [assets/ui-contract/](assets/ui-contract/) (start with `ui-behaviour-rules.md`).

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

```

There is nothing to run: the application entry point (`main.py`) was removed with the Qt shell.

### Tests

`tests/` mirrors `uadas_core/`'s package layout (plus `tests/assets/`, which guards the data mined from
the old UI). There are no pytest markers and no Qt: the suite is plain pytest and runs the same on any OS.

```powershell
# single test — plain pytest is fine for iterating
pytest tests/some_package/test_some_module.py::test_case_name

# full suite — exactly what CI and the commit gate run
python -m pytest tests -q
```

CI (`.github/workflows/ci.yml`) has one Linux `test` job (imports with no Qt binding installed, mypy,
a collected-test floor so a shrinking suite fails, then the suite), a `lint` job, and `dco` on pull
requests. Reproduce a CI failure on the exact dependency set with a clean virtualenv, not your existing
`.venv`: a stale local environment can hide a resolution problem (e.g. an unpinned upper bound).

### Formatting, linting, types, security

Versions are pinned in `requirements.txt` (`black==26.5.1`, `isort==8.0.1`, `mypy==2.1.0`,
`ruff==0.16.3`, `bandit==1.9.4`) and enforced in CI (`.github/workflows/ci.yml`), not left to
whatever the tool defaults to:

```powershell
black --check uadas_core/ tests/ scripts/
isort --check-only uadas_core/ tests/ scripts/
bandit -r uadas_core -q --skip B101,B107,B608   # same skips as CI (rationale in ci.yml's bandit step)
PYTHONPATH=apps/api lint-imports                  # the 5 .importlinter contracts (PYTHONPATH finds uadas_api)
```

`mypy` is **not** run repo-wide — it's scoped to an explicit, curated list of packages/modules that
are currently clean (see the `mypy` step in `.github/workflows/ci.yml` for the authoritative list,
and [docs/MYPY_DEBT.md](docs/MYPY_DEBT.md) for what's excluded and why). Running `mypy uadas_core/`
directly will surface pre-existing debt, not a meaningful pass/fail signal; when a milestone makes
an excluded module clean, add it to that CI list rather than treating a bare repo-wide run as the
target.

`ruff` is also configured (`[tool.ruff]`), with an explicitly curated `select` list (not "ruff's
current defaults") and `ignore = ["RUF001", "RUF005"]`. Ruff's own isort rule-group (`"I"`) is
deliberately **not** enabled — `isort` (profile `black`) stays the tool of record for import order.
This matters because a `PostToolUse` hook (`.claude/hooks/quality-check.ps1`) already runs `isort`,
then `black`, then `ruff check --fix` automatically on every Edit/Write to a `.py` file (black, not
`ruff format`, because black is the formatter CI checks) — re-running those by hand after an edit is
redundant, but `mypy`/`bandit`/`lint-imports` are not part of that hook and still need to be run
explicitly to match what CI gates on.

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
  `.claude/hooks/pre-commit-check.ps1`, which (when any `.py` file is staged) runs the full
  `python -m pytest tests -q` suite and `bandit` first and blocks the commit if either fails — a commit
  that takes minutes is the suite running; one that is rejected means one of those failed, so check the
  output rather than retrying blindly.
- `.claude/hooks/protect-files.ps1` blocks Edit/Write to `.env*`, `secrets.json`,
  `credentials.json`, and `*.pem`/`*.key` files.

### Visual verification

There is none until Phase 4: the Qt screenshot tooling was deleted with the shell. UI facts that used to
be verified visually (default layout, menus, copy, thresholds, accessibility rules) are recorded as data
in [assets/ui-contract/](assets/ui-contract/) and guarded by `tests/assets/`.

## Architecture

Full narrative detail — startup sequence, dependency container mechanics, the workspace model,
configuration schema, and the exception hierarchy — lives in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). What follows here is only the actionable rules: the
constraints that must be preserved whenever this code is touched, not the explanation of how it works.

### Startup sequence

`config.py` deliberately does not import the project logger (it's a dependency of the logger, not a
consumer of it) — it uses a bare `logging.getLogger` for its own bootstrap-time messages instead. Don't
"fix" this into a `get_logger` call. Startup is split in two (Phase 3 session seam):
`bootstrap_process(server_mode=..., config=...)` builds the process-wide, tenant-free world once and
`build_session(process)` builds the stateful per-user services into a child container; the legacy
`bootstrap()` composes them and returns the same `BootstrapContext`. **`server_mode=True` must stay
impossible to turn into desktop behaviour**: no plugin loading (the plugin package is not even
imported), no YAML read/write, no log files (and never the host's root logger), no
`set_default_job_runner` bridge — don't add a code path in `bootstrap_process` that does any of those.
The mode is a one-way latch (`core/process_mode.py`): desktop and server bootstraps in one process raise.
Never log `%r` of a dataset/project/setting value (tenant data and secrets share one server log). See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#application-startup-sequence) and
[plans/phase-3-session-seam.md](plans/phase-3-session-seam.md) for the sequence and why its order can't be changed.

### Dependency container

`DependencyContainer(parent=...)`: a child resolves its own registrations first, then falls back to its
parent, and nothing registered in a child leaks to the parent or siblings. Register a new **process-wide,
stateless** service in `bootstrap_process()` and a new **per-user, stateful** one in `build_session()`
(never on the process container — that would share it across tenants), rather than constructing them ad
hoc inside other services, so every consumer resolves the same instance. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#dependency-container) for how the container itself works.

### The `Base*` extension-point pattern

Several packages define an abstract base class that concrete implementations plug into, all following the
same shape: **stateless, classmethod-only** (never instantiated — mirrors how they're actually consumed,
as classes held in a registry, not objects), with inputs validated before real work happens:

- `uadas_core/readers/base_reader.py` → `BaseReader.can_read()` / `list_tables()` / `read()`. New format readers
  register in `uadas_core/readers/reader_registry.py`'s `_BUILTIN_READERS` tuple — that's the one place to
  touch when adding a reader.
- `uadas_core/cleaning/base_operation.py` → `BaseOperation.apply(dataset, **kwargs) -> Dataset`. **Cleaning
  operations never mutate a `Dataset` in place** — always return a new `Dataset` with `parent_dataset_id`
  set to the source's `dataset_id` and `derivation_description` explaining the change. This is what makes
  undo and dataset lineage possible; don't special-case an in-place variant.
- `uadas_core/visualization/base_chart.py` → `BaseChart.build(dataframe, **kwargs) -> go.Figure`. Charts return
  Plotly `Figure` objects directly (no custom wrapper).
- `uadas_core/ai/llm_provider.py` → `BaseLLMProvider` is the exception to "stateless classmethod-only" (it holds
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

One deliberate exception at the persistence boundary (web-transition 1.6): `PersistenceService.
save_workspace` does **not** persist a visualization whose dataset has been closed — it is reported
in `SaveReport.skipped_visualization_ids` and its Parquet frame is GC'd. So that particular
orphaned-reference state (visualization outliving its dataset) does not survive a save/load
round-trip, even though it is legal in a live session. This is a save-side scope choice, not a
break of the non-cascading rule.

`save_workspace`'s **ordering is load-bearing** (Phase 2.7): frames are staged as `<id>.parquet.tmp`, then
promoted, then `workspace.db` is swapped in, and orphan frames are garbage-collected only **after** the
swap. Garbage-collecting earlier means a failure in between leaves the *previous* `workspace.db`
pointing at frames that are already gone. Don't reorder it; `tests/persistence/test_persistence_atomicity.py`
injects each failure.

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

### The removed Qt shell, and where its facts live

The PySide6 shell (`src/ui`, `src/workers`, `src/app.py`, `main.py`) is gone; there is no Qt anywhere in
this repo, and `uadas_core/` must stay that way (`.importlinter` contract 1, plus a CI step that asserts no
Qt binding is importable). Before designing any UI, read [assets/ui-contract/](assets/ui-contract/): the
default dock layout, menus and command palette (`workspace-layout.json`), UI constants and stylesheet
metrics (`ui-constants.json`), file-picker filters, mapping tables, all 345 user-facing strings
(`ui-copy.json`), the accessibility rules and the three non-obvious interaction patterns (`a11y-*.json`),
and the product rules with their rejected alternatives (`ui-behaviour-rules.md`). The chart host page
(`resources/web/chart_host.html`, `chart_bridge.js`) survives and is loaded once, then updated through
`Plotly.newPlot`/`react`/`relayout`; never reload it per chart.

### Multi-file touchpoints that do not auto-sync

Adding a reader requires updating both `reader_registry.py`'s `_BUILTIN_READERS` tuple *and* the file-picker
filter groups in `assets/ui-contract/file-picker-filters.json` — the second does not derive from the first
automatically, but `tests/assets/` now fails if their extension sets differ. Watch for the same class of gap (a registry plus a separately-hardcoded consumer)
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
