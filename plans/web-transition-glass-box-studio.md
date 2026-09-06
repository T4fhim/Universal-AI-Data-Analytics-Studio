# Universal AI Data Analytics Studio — Desktop → Web Transition Plan

**Status:** approved 2026-09-02 · execution deferred to a dedicated session · This is the third planning document; `plans/` holds two others, both executed.

**Decisions locked 2026-09-03:**
- **Licence** = **AGPL-3.0**, with a **CLA or DCO required from the first commit** (Phase 0.8).
- **`src/models/`** = **delete** (Phase 0.4), along with the other two empty `src/` packages.

---

## Context

The project is a PySide6 desktop app: **208 Python files in `src/`, 146 under `tests/`, 29 completed milestones across two fully-executed planning documents, and no third plan naming what comes next.** The roadmap is exhausted. Fifteen of the last sixteen commits are CI firefighting, not features. Nothing has ever merged to `main` (the feature branch is **50 commits ahead, 0 behind** — the status report's "48" is stale).

The decision is to move to the web. Five choices are locked and this plan is built on them:

| Decision | Choice |
|---|---|
| Desktop app | **Retire completely** after mining reusable assets |
| Audience | **Open-source + self-hostable, plus a hosted multi-tenant instance** |
| Frontend | **Vite + React + TypeScript SPA** |
| Sequencing | **Port to parity first, then differentiate** |
| Licence | **AGPL-3.0**, with a **CLA or DCO required from the first commit** (Phase 0.8) — closes the SaaS loophole (a competitor cannot run a modified hosted fork without publishing changes), stays OSI-approved and freely self-hostable, and the contributor agreement preserves the option to dual-licence commercially later |

### The finding that makes this feasible

An exhaustive grep of `src/` establishes that **exactly two files outside `src/ui/` import PySide6**:

- `src/core/app.py:21,112` — constructs `QApplication`, enters the event loop. Dies with the desktop app.
- `src/workers/base_worker.py:24` — `QObject`/`QRunnable`/`Signal`. Small, mechanical replacement.

**105 of the 107 non-`ui` modules are already Qt-free.** All 20 readers, 7 cleaning ops, 14 analysis modules, 8 forecasting modules, 10 visualization modules, 5 AI modules, 8 report exporters, 10 database modules, 4 plugin modules and 8 services import zero Qt. `src/visualization/__init__.py:2` says it outright: *"Backend only."* The dependency direction is strictly one-way and `tests/ui/test_import_layering.py` already enforces it.

This is not a rewrite. It is an **extraction** — the domain layer is already the thing a web backend needs, sitting behind a Qt shell.

### Assets already built that most projects would have to invent

1. **`AnalysisOrchestratorService`** (`src/services/analysis_orchestrator_service.py`) already implements a 10-stage `PipelineStage` StrEnum (`UPLOAD → UNDERSTAND → CLEAN → EXPLORE → ANALYZE → VISUALIZE → PREDICT → EXPLAIN → REPORT → REPRODUCE`), an `AnalysisLog` of `AnalysisLogEntry` records capturing *stage, tool name, exact inputs, outputs, explanation, timestamp*, `to_dict()`/`from_dict()` on both, and a working `reproduce(dataset_id)` method. **That is a provenance ledger and a replayable pipeline, already written.** It is the core of the product's differentiation and it exists today.
2. **The result-section model** (`src/ui/results/base_result_renderer.py`) — *"Qt lives nowhere in this module — not an import, not a type hint."* Six frozen dataclasses (`KeyValueSection`, `TableSection`, `FigureSection`, `ProseSection`, `MetricSection`, `AssumptionsSection`), 11 concrete renderers under `src/ui/results/renderers/`, all pure classmethods, all values already display-formatted strings. **A web API serializes `sections()` output almost verbatim** — the only non-JSON member is a Plotly figure, which already serializes via `figure.to_json()`.
3. **`resources/web/`** is already a browser bundle — `plotly.min.js` (Plotly 6.8.0, 4.8 MB), `chart_host.html`, `chart_bridge.js`. `QWebEngineView` was only ever a browser in a window. Every chart in `src/visualization/` returns a plain `plotly.graph_objects.Figure`, which renders in Plotly.js unchanged. **Zero chart code is rewritten.**
4. **`docs/manual/`** — 81 Markdown files, 348 KB, already source-format with a YAML-frontmatter anchor index, compiled at runtime by `markdown_it`. Its resolver (`src/ui/help/manual_index.py`) is itself Qt-free. Ships to the web as-is.
5. **Design tokens** (`src/ui/theme/tokens.py`) — 3 complete themes as frozen dataclasses; `ThemeTokens.as_qss_mapping()` is *already* a flat `dict[str,str]` with `px` units, one method away from emitting `:root { --surface-0: … }`. `src/ui/theme/plotly_theme.py`'s `plotly_layout()`/`plotly_config()` return plain dicts with **no Plotly import** — they feed straight into Plotly.js.

### Intended outcome

A web application that reaches desktop parity, then adds the layer nobody in this market has: **a glass box.** Every AI action, every clean, every statistical test and forecast is an inspectable, replayable, forkable node in a provenance graph — not a chat answer you have to trust.

---

## Positioning: why this becomes its own category

The 2026 AI-analytics market has split three ways, and each segment has a structural hole:

| Segment | Examples | The hole |
|---|---|---|
| Conversational analysts | Julius, Databricks Genie, Snowflake Cortex Analyst, ThoughtSpot Sage | **Black box.** You get a number and a chart. You cannot audit how, reproduce it next month, or fork a what-if. Governance vendors sell lineage as a *separate product* precisely because these tools have none. |
| Notebooks | Hex, Deepnote, Mode, Observable | Require code. Kernel state is destroyed on restart — no time travel, no forking an intermediate state. |
| Drag-and-drop BI | Tableau, Power BI, Looker | No statistics worth the name, no assumption checking, no reasoning layer. |
| Visual pipeline tools | KNIME, Orange | Have the DAG, but are desktop, dated, and have no AI or explanation layer. |

**The gap: nobody ships provenance-native, assumption-checked, expertise-adaptive analysis.** Lineage is sold as governance tooling bolted on afterwards, never as the analysis surface itself.

That is the category this becomes: **the Glass-Box Analyst.** The differentiating rule, enforced architecturally:

> The AI can never do anything the user cannot see, inspect, undo, replay, or fork.

Credible here specifically because of decisions already in this codebase: cleaning operations never mutate a `Dataset` in place (every intermediate state still exists → time travel is free), `Visualization`/`Dashboard` reference by ID not object (→ the graph is already serializable), `AnalysisLog` already records exact tool inputs (→ replay is already implemented), and `GuidanceService` already *re-ranks* by `ExpertiseLevel` without filtering (→ expertise-adaptive UI is a real, tested product rule, not a tagline).

---

## Verified facts this plan is built on

Every load-bearing claim below was checked against the working tree, not read from a document.

| Claim | Verdict | Evidence |
|---|---|---|
| Only 2 files outside `src/ui/` import PySide6 | ✅ | `grep -rl PySide6 src --include=*.py \| grep -v ^src/ui/` → `src/core/app.py`, `src/workers/base_worker.py` |
| `src/` file count | ⚠️ **208**, not the reported 207 | `find src -name '*.py' \| wc -l` |
| `tests/` file count | ✅ 146 — but only **120** are `test_*.py` | rest: 21 `__init__.py` + 3 `conftest.py` + 2 helpers |
| Qt share of the test suite | **90 of 146 files under `tests/ui/`** | 62% of the suite retires with the desktop UI |
| Empty `src/` packages | ⚠️ **three**, not two | `src/models`, `src/resources`, **`src/utils`** — `src/utils/` is missed by the status report *and* `docs/ARCHITECTURE.md` |
| Branch ahead of `main` | ⚠️ **50**, not 48 | `git rev-list --count main..HEAD` |
| No `TODO`/`FIXME`/`XXX`/`HACK` in `src/` | ✅ 0 | pattern widened to include `HACK`; still zero |
| CI runs neither `ruff check` nor `bandit` | ✅ confirmed | `.github/workflows/ci.yml` (268 lines, only workflow) contains neither — while `docs/ARCHITECTURE.md:150-155` claims CI "gates on all of them" |
| `pyproject.toml` has no `[project]` section | ✅ | Tool config only. **The project is not pip-installable** — flat script layout, `pythonpath = ["."]` |
| Stray git worktrees | ✅ and **worse** | `.claude/worktrees/agent-a8c94eedacbd2ebb9` registered and already merged into HEAD, **plus** an unregistered empty `agent-a69999b2fa3641991/`; neither gitignored |
| `config/config.yaml` tracked and drifted | ✅ | committed copy is a **pre-milestone-7 schema** missing `database`/`accessibility`/`ui` sections; loads only via five `_migrate_legacy_*` shims. Working tree copy carries machine-local state incl. a named `GROQ_API_KEY` provider profile **in a tracked file** |
| Declared-but-never-imported deps | ✅ | `polars`, `dask`, `numba`, `joblib`, `xgboost`, `lightgbm`, `catboost`, `networkx`, `ydata-profiling`, `watchdog`, `aiohttp` — no `import` of any in `src/` |
| `duckdb`/`pyarrow` usage | ⚠️ indirect only | `duckdb` only as a SQLAlchemy dialect string; `pyarrow` only as a pandas backend |
| AI tool-dispatch loop has no iteration cap | ✅ | `src/ai/assistant_service.py:271` — `while True:` unbounded. Real DoS/cost risk on the web |
| No streaming anywhere in the AI layer | ✅ | `OllamaProvider` sends `"stream": False` (`llm_provider.py:472`); all four providers use non-streaming calls |
| Plugin loader is unsandboxed | ✅ | `plugin_loader.py:115` `importlib.import_module()` on a manifest string, `:237` permanent `sys.path.insert` — arbitrary code execution |
| `execute_query` runs arbitrary user SQL | ✅ | `src/database/base_connection.py:267` — deliberate, bounded only by chunk size |
| `WorkspaceService` has no persistence | ✅ | its own docstring: *"All state here is in-memory and session-scoped."* `ProjectService` persists only `{name, source_path}` per dataset + analysis logs — **never the DataFrames, visualizations or dashboards**, and silently skips derived datasets |
| `CLAUDE.md` chart/dock sections are stale | ✅ | `chart_view.py` uses a once-per-process staged shell + `runJavaScript`, not "temp file + setUrl per chart"; the Project Explorer dock was deleted, not "tabbed with Dataset Explorer" |

**Unverified / assumptions carried forward** (do not treat as fact): live test-suite pass counts (`1371 passed` etc. — quoted from CI logs; the suite was **not executed**); `docs/MYPY_DEBT.md` states 72 errors but its per-file breakdown sums to 71; whether `src/forecasting/prophet_forecast.py` mutates the root logger to silence Prophet (the `import logging` is present, the call site was not read); all effort framing in this plan is estimate, not measurement.

---

## Anti-hallucination regime (in force from Phase 0)

Requested explicitly, and designed so it does **not** depend on a skill arriving later. The contingency is that enforcement is machine-run, not prompt-run.

**Rules:**

1. **A claim of "done" requires a command and its output.** A code read is never evidence. Standing principle already in the observation log (entries 0005 / 0008): a hook that reads correctly, an MCP that says "Connected", a scheduled task with a "last successful run", a local all-clean tool run — none of those are the thing they stand in for.
2. **Every phase ends with a named verification command**, listed in that phase, not a subjective judgement.
3. **Subagents' negative claims get spot-checked** — "pre-existing", "unrelated", "already handled" (observation 0006: a delegated agent's black-drift claim was checked against the true base commit and was false).
4. **Whoever writes does not verify.** `implementer` writes; `code-reviewer` / `security-reviewer` / `ecc:django-reviewer` / `ecc:react-reviewer` verify. Never self-review.
5. **Assumptions are written down as assumptions**, in an `## Unverified` section of every milestone doc.

**Machines that check the work so a human doesn't have to** — the real contingency:

| Guard | What it catches | Added in |
|---|---|---|
| `import-linter` contract | Any Qt import creeping back into the core; any core→web dependency | Phase 1 |
| OpenAPI schema committed + CI drift check | Backend and frontend silently disagreeing | Phase 3 |
| **Schemathesis** (property-based, generated from the schema) | 500s and contract violations on inputs nobody thought to test | Phase 3 |
| Generated TypeScript client | A frontend calling an endpoint that no longer exists → becomes a compile error | Phase 4 |
| `axe-core` in Playwright + the ported contrast manifest | Accessibility regressions | Phase 4 |
| Playwright E2E of the full 10-stage pipeline | "It works" claims that were never actually run | Phase 4 |
| `ruff check` + `bandit` **in CI** (currently absent) | The 55-violation class of debt that accumulated invisibly before | Phase 0 |
| Linux CI runner | Windows-only assumptions in code destined for a Linux server | Phase 0 |

---

## Target architecture

```
uadas-core/            ← pure Python, Qt-free, pip-installable, no Django import
  readers/ cleaning/ analysis/ forecasting/ visualization/
  ai/ reports/ database/ plugins/ engine/ provenance/  results/  (renderers lifted from src/ui/results/)
        ▲                                    ▲
        │ imported by                        │ imported by
  apps/api/            ← Django 6 + Django Ninja        (Python)
    accounts/ workspaces/ pipeline/ ai/ exports/ billing/
    ├─ Postgres 17          (metadata, provenance DAG, users)
    ├─ S3 / MinIO           (uploaded files, Parquet materializations, exports)
    ├─ Redis               (task broker, cache, rate limits)
    └─ worker process       (django.tasks API → Celery/RQ backend)
        │  OpenAPI 3.1  →  generated TS client
        ▼
  apps/web/            ← Vite + React 19 + TypeScript SPA
    Plotly.js (reuses fig.to_json() verbatim) · TanStack Query/Table/Virtual/Router
    Tailwind + shadcn/ui (Radix) · cmdk command palette · Zustand
```

**The invariant that must never be violated:** `uadas-core` never imports Django, and Django never reaches into presentation concerns. The core is a library with a headless engine; the web app is one adapter over it. This preserves the option of a CLI, a notebook kernel, or a Pyodide build later — and it is what makes the local-first mode (F10) possible at all.

### Why Django, specifically (you asked)

Django + **Django Ninja**, not Django + DRF, and not bare FastAPI.

- **Django earns its place** for exactly what this project now needs and lacks: an ORM with migrations (the provenance graph is relational and will change shape repeatedly), `django.contrib.auth` + django-allauth (real auth, free), the admin (a free ops console for a solo maintainer running a hosted instance), `django-storages` (S3/MinIO), and the `django.tasks` framework shipped in Django 6.0 (Jan 2026) as a standard background-job API.
- **Django Ninja, not DRF**, because it is Pydantic v2 + type hints + automatic OpenAPI 3.1 + async endpoints. DRF's serializer layer would mean re-declaring every dataclass this codebase already has; Ninja schemas map onto the existing `Dataset` / `ForecastResult` / `AnalysisLogEntry` / result-section dataclasses almost directly. DRF stays the safer pick only for CRUD-dominant admin apps — this is not one.
- **Not bare FastAPI**, because you would then hand-build auth, admin, migrations and storage — and this project's bottleneck is developer time, not request throughput.
- **Caveat, stated honestly:** `django.tasks` in 6.0 defines the API but **ships no worker**. You still run Celery or RQ behind it. It is an interface standard, not a Celery replacement.

### Postman — correcting the premise (you asked)

**Postman does not link a backend to a frontend.** Nothing does, in that sense. What links them is an **HTTP contract described by an OpenAPI schema**. Postman is an API *client, testing and documentation* platform that sits beside that contract.

The actual linkage in this plan:

1. Django Ninja **generates** OpenAPI 3.1 from your Python type hints — no hand-written spec.
2. That schema is **committed to the repo**; CI regenerates it and fails on drift.
3. `openapi-typescript` + `openapi-fetch` generate the **TypeScript client** from it. A backend field rename becomes a frontend *compile error*, not a runtime 500 a user finds.

Where Postman genuinely helps: manual exploration while building; **mock servers** so the frontend can be built before an endpoint exists; shareable API docs; collections run in CI via the Postman CLI (Newman). Where it is weaker for a solo maintainer: you hand-write every assertion, and its free tier is now tightly limited.

**Recommendation:** use **Schemathesis** as the automated layer — it reads the same OpenAPI schema and generates thousands of property-based requests, finding crashes and contract violations you would never write a test for. For the manual/exploratory layer use **Bruno** (open-source, offline, collections stored as plain files *in the repo*, no cloud account) rather than Postman — it fits this project's everything-in-git discipline. Postman stays fine if you specifically want its mock servers and team workspaces.

---

## Phase 0 — Ground truth and cleanup

*No migration code. This phase exists because starting a migration on top of unmerged work, drifted docs and ungated CI is how the last engagement lost time.*

- **0.0** Copy this plan to `plans/web-transition-glass-box-studio.md` in the repo.
- **0.1 Ship the 50 commits to `main`.** Confirm the GitHub Actions result for `d9d7252` is genuinely green *via the API*, then merge. Do not start a migration from an unmerged branch.
- **0.2 Fix the doc-vs-tree contradictions.** `docs/ARCHITECTURE.md:150-155` claims CI gates ruff and bandit (it does not); `:22-27` lists `database`/`plugins`/`workers`/`reports` as "empty — not yet built" while the same file's closing section says the opposite; both it and the status report miss that `src/utils/` is empty; `docs/ROADMAP.md` is frozen at Milestone 14 and claims no committed tooling config or CI gate exists. Mark ADR `0001-unpinned-llm-sdk-dependencies` superseded. Fix the two stale `CLAUDE.md` sections (chart rendering, dock model).
- **0.3 Untrack `config/config.yaml`.** Committed at a pre-milestone-7 schema *and* the working-tree copy carries machine-local state including a named Groq provider profile. Replace with `config/config.example.yaml` + a `.gitignore` entry. Live secrets-adjacent hazard, not housekeeping.
- **0.4 Delete dead scaffolding.** Remove both stray worktrees and add `.claude/worktrees/` to `.gitignore`. Delete the three empty `src/` packages — `src/models/`, `src/resources/`, `src/utils/` — no milestone across either plan ever named a purpose for them, and the codebase's real convention is dataclasses co-located with their consumers (`Dataset` in `workspace_service.py`, `AnalysisLog` in `analysis_orchestrator_service.py`), not a central `models/` package. If the provenance DAG types later want a dedicated home, it arrives in Phase 1.7 named for its role (`uadas_core/provenance/`), not as a resurrected `models/`.
- **0.5 Add `[project]` metadata to `pyproject.toml`** so the codebase becomes pip-installable. Everything downstream depends on this.
- **0.6 Close the CI gaps:** add `ruff check` and `bandit -r src -q` as gating steps; add an `ubuntu-latest` job (the server is Linux; the suite has only ever run on Windows). Resolve the live conflict where `.claude/hooks/quality-check.ps1:31` runs `ruff format` that `.pre-commit-config.yaml:22-29` explicitly forbids as fighting `black`.
- **0.7 Adopt a lockfile** (`uv lock` or `pip-tools`). ~50 of 60 dependencies are entirely unpinned; two undeclared runtime deps (`plotly-resampler`, `camelot-py`) have already been found this way, each via a reproduced CI failure.
- **0.8 Set the licence and contributor flow before the repo goes public.** Add a top-level `AGPL-3.0` `LICENSE` file plus SPDX headers consistent with the project's `# File:` convention. Stand up the contributor agreement now, not later: **DCO** (a `Signed-off-by` line, enforced by a CI check — lighter, no paperwork) is the pragmatic default; a **CLA** (contributors sign an actual agreement, e.g. via CLA Assistant) is the stronger pick if commercial dual-licensing is a near-term intent. Either way it must be in force from the first migration commit — retrofitting consent across accumulated contributors is the expensive path. Record the choice in `CONTRIBUTING.md`.

**Verification:** `main` contains the merge commit; a top-level `LICENSE` (AGPL-3.0) and `CONTRIBUTING.md` (DCO/CLA) exist and the DCO/CLA check is wired into CI; `src/models/`, `src/resources/`, `src/utils/` are gone; `ruff check src/ tests/` and `bandit -r src -q` both pass **in a CI run**, not locally; the Linux job is green; a clean clone + `pip install -e .` imports `src`.

---

## Phase 1 — Extract a Qt-free, headless, installable core

*Highest-leverage phase. Also proves the central assumption for real instead of by grep.*

- **1.1 Rename and package.** `src/` → `uadas_core/` as a real distribution. Add the **import-linter contract**: no module in `uadas_core` may import `PySide6`, none may import `django`. Wire into CI. This makes "Qt-free" a permanent, machine-checked property rather than a claim that decays.
- **1.2 Replace the Qt worker.** `src/workers/base_worker.py`'s contract is already Qt-free in shape: `BaseWorker(fn, *args, report_progress=…, **kwargs)` wraps an arbitrary plain callable and injects a `progress_callback: Callable[[int, str], None]`. Nothing inside any wrapped function knows about Qt. Replace with a `JobRunner` protocol backed by `ThreadPoolExecutor` in-process and `django.tasks` on the server. Delete the leftover temporary `[diag]` logging the file's own comments say to remove.
- **1.3 De-globalize process state.** Four import-time module-level mutable registries — `reader_registry._PLUGIN_READERS`, `cleaning.operation_registry._REGISTRY`, `visualization.chart_registry._REGISTRY`, and `src/ui/actions/action_registry._REGISTRY` (lift this one into core with the renderers) — become instances resolved from the container. Same for `logger._configured`'s one-shot root-logger mutation and the `PROJECT_ROOT`-anchored `CONFIG_DIR`/`LOG_DIR`/`PROJECTS_DIR` constants (`constants.py:37-44`). Fix the latent bug where `tool_registry._CHART_BUILDERS` snapshots `chart_registry.list_charts()` at import time, so a plugin chart registered afterwards never appears.
- **1.4 Make services session-scopeable.** Every service is currently a process singleton registered in `bootstrap.py:148-221`. Introduce a `Session` scope so `WorkspaceService`, `AnalysisOrchestratorService`, `ProjectService` and friends are per-user, not per-process. Keep `DependencyContainer` but give `resolve()` a real generic signature — `resolve(self, key: type[T]) -> T` — which also erases **29 of the ~72 catalogued mypy errors** in one change.
- **1.5 Lift the result-rendering layer into the core.** `src/ui/results/base_result_renderer.py`, `result_view.py`, `result_renderer_registry.py` and all of `renderers/` are already Qt-free — move them into `uadas_core/results/`. They become the backend's serialization layer for analysis/forecast results: `sections(result, level)` → JSON, `FigureSection.figure` → `figure.to_json()`. `result_card.py`'s six `isinstance→widget` branches are the *only* Qt in that package and are exactly what the React renderer replaces 1:1.
- **1.6 Build the persistence layer the app has never had.** New serialization contract:
  - `Dataset` → Parquet in object storage (`pyarrow` is already a dep) + a metadata row carrying `parent_dataset_id` and `derivation_description`.
  - `Visualization` → **never store `go.Figure`.** Store `{dataset_id, chart_type, chart_parameters}` and rebuild via the chart registry on demand. Figures become a cache, not a record.
  - `Dashboard`/`DashboardTile` → already ID-referenced; straight to JSON/relational.
- **1.7 Promote the provenance model to first class.** `AnalysisLog`/`AnalysisLogEntry` already carry stage, tool name, exact inputs, outputs, explanation and timestamp with working `to_dict()`/`from_dict()`. Reshape from a flat per-dataset list into a real **DAG** keyed on dataset lineage, and define the portable **Recipe** format (the DAG minus the data). Everything in Phase 5 depends on this being right, so it is done here, once.
- **1.8 Security fixes that are latent on the desktop and critical on a server:**
  - Add an **iteration cap** to the `while True:` tool-dispatch loop (`assistant_service.py:271`).
  - Fix the zip-slip-adjacent extraction in `archive_reader.py:168`.
  - Move API keys from `os.environ`-only reads (`provider_rotation.py:170`) to injected credentials, so one process can serve many users' keys.
  - Gate `base_connection.py:267`'s arbitrary-SQL `execute_query` behind an explicit capability.

**Verification:** in a fresh venv **with PySide6 uninstalled**, `python -c "import uadas_core"` succeeds and the 56 non-UI test files pass — **on Linux**. `lint-imports` is green in CI. A dataset survives a save/load round trip including a derived dataset (which the current code silently drops).

---

## Phase 2 — Retire the desktop UI

**Mine before deleting.** Concrete extraction inventory (all paths verified):

| Asset | Path | Becomes |
|---|---|---|
| Design tokens (3 themes) | `src/ui/theme/tokens.py` — `as_qss_mapping()` already a flat `dict[str,str]` | CSS custom properties (`:root`) |
| Density ↔ expertise map | `src/ui/theme/tokens.py:85` `DENSITY_BY_EXPERTISE_LEVEL` | Layout-density rule in the SPA |
| Plotly theme + config dicts | `src/ui/theme/plotly_theme.py` — no Plotly import | Fed straight into Plotly.js (`plotly_config` already encodes the WCAG "always-visible modebar" call) |
| WCAG contrast math + thresholds | `src/ui/theme/contrast.py` | ~50-line TS port |
| Contrast manifest (theme-independent, token names not hexes) | `src/ui/a11y/contrast_manifest.py` `CONTRAST_REQUIREMENTS` | Automated token-contrast test in CI |
| A11y rule catalog (8 rules, IDs + severity model) | `src/ui/a11y/rules.py:531` `DEFAULT_RULES` | axe-core custom-rule config (check *bodies* are Qt-specific and discarded) |
| `describe()` call-site metadata | every `describe(...)` across `src/ui/` | `aria-label` / `aria-describedby` / `data-help-anchor` triples |
| Action registry data (24 actions) | `src/ui/actions/action_registry.py` + `builtin_actions.py` | `/api/actions` + the cmdk palette; 3 `predicate` lambdas re-expressed server-side or as a tiny expression DSL |
| Enablement context (10 booleans/counts) | `src/ui/actions/action_context.py:68-77` | exactly a `/api/capabilities` payload shape |
| Pipeline IA + rationale copy | `src/services/analysis_orchestrator_service.py:44,70,80` (`PipelineStage`, `_AUTO_PROPOSED_STAGES`, `_STAGE_RATIONALE`) | survives untouched — already outside `src/ui/` |
| Guidance model + expertise ranking weights | `src/services/guidance_service.py` (`Suggestion`, `_EXPERTISE_STAGE_WEIGHT:143`) | survives 100% — never imports `src.ui` |
| Stage-status vocabulary (non-colour) | `src/ui/workbench/stage_rail.py:30` `_STATUS_PREFIX` | keep the `✓ / → / ·` encoding |
| Manual content + anchor index | `docs/manual/` (81 `.md`) + `src/ui/help/manual_index.py` (Qt-free) | in-app help drawer / docs site, near-zero rework |
| Empty/error state copy + illustrations | `src/ui/widgets/empty_state.py`, `error_state.py`; `resources/icons/illustrations/*.svg` | component contract + copy port; SVGs use `currentColor` → CSS-themeable free |
| Onboarding tour copy | `src/ui/dialogs/first_run_tour_dialog.py:31-44` `_BODY_HTML` | extract to Markdown/JSON |
| Schema-driven parameter forms | `src/ui/dialogs/analysis_parameter_dialog.py` reads `ToolDefinition.input_schema` (JSON Schema) | drive a web form generator (RJSF) from the *source schemas* directly |
| AI turn envelope | `src/ai/assistant_service.py:80` `AssistantTurnResult` | ready-made API response shape (add streaming separately) |
| Cell formatters (zero Qt, deliberately) | `src/ui/widgets/data_table/column_formatters.py` | port directly for the web grid |
| Icon set (43 + 3 SVG, `stroke="currentColor"`) | `resources/icons/` | drop into the SPA; theming free via CSS `color` |
| Chart bridge JS semantics (newPlot→react, relayout-for-theme) | `resources/web/chart_bridge.js` | transfers; the QWebChannel wrapper does not |

**Then delete, and enjoy how much complexity leaves with it** (~76–79% of `src/ui/`'s 16,526 lines is Qt-only plumbing):

| Removed | Why it goes | Scale |
|---|---|---|
| `src/ui/` | Replaced by the SPA (portable ~2,400 lines lifted first, per the table above) | **101 files, 48.6% of `src/`** |
| `tests/ui/` | Tests only deleted code | **90 of 146 test files** |
| `src/core/app.py`, `main.py`'s Qt path | `QApplication` entry point | 2 files |
| `src/workers/` | Replaced in 1.2 | 2 files |
| `scripts/run_tests_and_exit_cleanly.py` | Exists **solely** to survive a Windows CPython/Qt interpreter-shutdown access violation | — |
| `scripts/screenshot_app_state.py` | Qt offscreen screenshots → Playwright | — |
| `tests/ui/conftest.py` harness | The `QT_QPA_PLATFORM=offscreen` dance, the never-torn-down session `QApplication`, the autouse modal-blocker | — |
| `webengine` + `uia_integration` markers, `tests/ui/a11y/test_uia_integration.py`, the non-blocking CI job | pywinauto/UIA is Windows-desktop-only | — |
| The `test_worker_runner.py` intermittent flake | Deleted with its subject | a long-standing open item |
| `resources/styles/base.qss.template` | QSS is Qt-only (tokens survive, the template does not) | — |
| `PySide6`, `pywinauto`, `pytest-qt` | — | 3 deps |
| `polars`, `dask`, `numba`, `joblib`, `networkx`, `ydata-profiling`, `watchdog`, `aiohttp` | **Declared but imported nowhere in `src/`** — verified by grep | 8 deps |
| `xgboost`, `lightgbm`, `catboost` | Also never imported. `SPECIFICATION.md` plans XGBoost as a forecasting model — **re-add when that model is actually built** | 3 deps |
| _(`src/models/`, `src/resources/`, `src/utils/` — three empty packages — are deleted earlier, in Phase 0.4)_ | | |

**Guard against over-pruning — these stay:** the `Base*` registry pattern (exactly right for a web plugin system too); the non-mutating `Dataset` rule (now the *product's differentiator*, not a code style); `SPECIFICATION.md`'s no-TODO / docstring / type-hint discipline (the reason the backend is liftable at all); `kaleido` and `reportlab` (static report export still needs them — note kaleido needs headless-Chrome system libraries in the container).

**Verification:** `grep -r PySide6 .` returns nothing outside history; the surviving suite passes on Linux; `docs/MYPY_DEBT.md` is regenerated (expected to shrink sharply — `src/ui/main_window.py` alone is 29 of the errors).

---

## Phase 3 — Backend: Django 6 + Django Ninja

- **3.1 Skeleton.** `apps/api/` Django project depending on `uadas-core`. Apps: `accounts`, `workspaces`, `pipeline`, `ai`, `exports`. Dev/prod settings split; 12-factor env vars replace `config/config.yaml` as *deployment* config (the schema idea survives as per-user settings rows).
- **3.2 Data model.** `User`, `Organization`, `Membership`, `Project`, `DatasetRecord` (with `parent_dataset_id`, storage key, row/column counts), `PipelineNode` + `PipelineEdge` (the provenance DAG), `ChartSpec`, `Dashboard`, `Report`, `Recipe`, `AuditEvent`. Every row tenant-scoped; a tenant-isolation test is written before the second model.
- **3.3 Auth.** django-allauth — email + OAuth. Session cookies for the same-site SPA. Per-tenant roles.
- **3.4 Storage.** `django-storages` → S3-compatible. MinIO locally, S3/R2 in production. Uploaded originals + Parquet materializations + generated exports.
- **3.5 Jobs.** `django.tasks` API with a Celery or RQ worker behind it. Every long operation is a job: reads, profiles, cleans, analyses, forecasts, exports. Progress reported through the `progress_callback` seam Phase 1.2 preserved.
- **3.6 API surface**, one router per pipeline stage, mirroring the existing `PipelineStage` enum so the IA is unchanged. Result payloads are the Phase 1.5 section model, serialized. OpenAPI 3.1 auto-generated, committed, CI drift-checked.
- **3.7 Streaming.** **New capability — none exists today.** SSE over an async Django view for AI token streaming and job progress. SSE over WebSockets deliberately: one-way, auto-reconnects with `Last-Event-ID`, multiplexes over HTTP/2, every proxy already understands it, and every major LLM provider chose it. Django Channels + Redis is not needed for this and is added only if/when Phase 5's collaboration lands.
- **3.8 Security — mandatory given the open/self-hostable + hosted choice.** This is where desktop-safe assumptions become exploitable:
  - **Disable the plugin loader by default in server mode.** `plugin_loader.py:115` imports an arbitrary module path from a manifest and `:237` permanently mutates `sys.path`. On a shared server that is remote code execution. A sandboxed plugin story is a separate, later project.
  - **Sandbox file parsing.** The 20 readers parse untrusted PDF/Word/Excel/image/XML/ZIP uploads via camelot, PyMuPDF, pdfplumber, python-docx, openpyxl, lxml, OpenCV and Tesseract — a large, well-known CVE surface. Parse in an isolated worker: no network, memory/CPU limits, wall-clock timeout, size caps.
  - Raw-SQL `execute_query` behind an explicit capability, against read-only DB roles, with statement timeouts.
  - Per-tenant quotas: rows, storage, job minutes, LLM tokens.
  - Secrets via env / secret manager only. The existing design already never writes passwords or API keys to config — preserve that.

**Verification:** `docker compose up` from a clean clone gives a working stack; **Schemathesis** passes against the live schema; tenant-isolation tests pass; an upload of a deliberately malformed PDF fails safe inside the sandbox without taking down the worker.

---

## Phase 4 — Frontend: Vite + React + TypeScript

- **4.1** Generate the TS client from the committed OpenAPI schema (`openapi-typescript` + `openapi-fetch` — fastest generator by a wide margin on large specs, zero runtime dependency).
- **4.2 Design system.** Emit the ported tokens as CSS custom properties, then Tailwind + shadcn/ui. Radix primitives are accessible by construction, which preserves the real M28 accessibility work rather than restarting it. The ported contrast manifest becomes an automated token test.
- **4.3 The workbench shell.** Reproduce the StageRail IA — the same 10 stages, the same guided flow, the same `_STAGE_RATIONALE` copy, the same "auto-navigate only from the welcome page, never yank an expert who's already roaming" rule. This is the product's validated information architecture; do not redesign it during a port. The `QDockWidget` float/redock model has no clean web analogue — express left-tree / right-tabbed-panels / bottom-console as a resizable panel layout.
- **4.4 Charts.** Plotly.js consuming `figure.to_json()` from the *unchanged* Python chart classes; `ChartView` collapses to `Plotly.newPlot`/`react`/`relayout` on a `<div>`; `chart_host.html`, `chart_bridge.js`, `web_assets.py` all evaporate (the browser *is* the web engine). One caveat: `continuous_charts.py` returns a `plotly_resampler.FigureResampler` above 5,000 rows — its own docstring confirms this survives static export with no live server, which is exactly the property needed.
- **4.5 Data grid.** TanStack Table + TanStack Virtual for virtualized viewing; server-side paging and sorting pushed to the backend. Reuse `column_formatters.py`.
- **4.6** TanStack Query (server state) + Zustand (UI state) + TanStack Router. `cmdk` command palette fed by the ported action registry; the "disabled actions still appear" rule is kept.
- **4.7** Render `docs/manual/`'s 81 Markdown files as in-app help, preserving the existing anchor system; port `tests/ui/help/test_manual_anti_rot.py` (it already asserts every `help_anchor` in the codebase resolves).
- **4.8** SSE client for AI streaming and job progress. Render assistant tool-results through the *same* result renderer as the rest of the app (the desktop deliberately does this — keep it).

**Verification:** Playwright E2E walking the complete `UPLOAD → … → REPORT` pipeline; `axe-core` clean; Lighthouse ≥ 90; the generated client compiles against the committed schema.

---

## Phase 5 — The differentiators

Each is scoped to build on something that already exists, which is what makes them realistic.

| # | Feature | Built on | Why nobody else has it |
|---|---|---|---|
| **F1** | **Provenance Graph** — every dataset, transform, test, chart and forecast is an inspectable node; click any node to see the data as it was at that point | `AnalysisLog` + `parent_dataset_id`, already recorded | Chat analysts have no record; notebooks destroy kernel state |
| **F2** | **Replayable Recipes** — export the DAG as a portable artifact, re-point it at next month's file, schedule it | `reproduce()` already implemented | Turns a one-off exploration into a durable asset |
| **F3** | **Time-travel & fork** — branch a what-if from any historical node | Non-mutating `Dataset` rule → every intermediate state still exists | Structurally impossible in a notebook |
| **F4** | **Expertise-adaptive UI**, not just adaptive prose — beginner hides parameters and explains; expert exposes every knob and the generated code; density follows too | `ExpertiseLevel` StrEnum (6 levels), `GuidanceService` re-ranking, `DENSITY_BY_EXPERTISE_LEVEL`, `ExplanationPanel`'s per-level disclosure map — all already wired | Collapses the market's three-way segmentation into one product |
| **F5** | **Assumption Sentinel** — every statistical test checks its own assumptions (normality, variance, independence, sample size) and warns or refuses before running; surfaced via the existing `AssumptionsSection` | `src/analysis/normality.py` + the `AssumptionsSection` result type both already exist | Every AI-analyst tool will happily run a t-test on non-normal data and say nothing |
| **F6** | **AI proposes, never mutates** — the assistant emits a *proposed* pipeline step shown as a diff (rows affected, before/after profile) that the user accepts or rejects | The tool-dispatch loop already produces discrete, logged tool calls | Makes the AI simultaneously safer and auditable |
| **F7** | **Living Reports** — published reports where every chart stays interactive and every number shows its provenance | `HtmlReportExporter` is already CDN-Plotly-based, no Qt | Static PDF is the industry default |
| **F8** | **Semantic typing & auto-join proposals** across uploaded datasets | `readers/type_inference.py` | Prerequisite for cross-file questions |
| **F9** | **Collaboration anchored to graph nodes** — comment on "the outlier-removal step", not "cell A3" (Yjs/CRDT) | F1 | Comments in every other tool are anchored to documents, not to reasoning |
| **F10** | **Local-first privacy mode** — the same Recipe executes entirely in-browser via DuckDB-WASM (+ Pyodide for the stats path); the server stores the DAG, never the data | The Recipe/DAG split from Phase 1.7 | A serious regulated-industry wedge; credible because `duckdb` and `pyarrow` are already dependencies. **Highest technical risk in this plan — prototype before committing** |

---

## Phase 6 — Ship it

Docker Compose self-host path · one-command dev setup · hosted instance on Fly.io/Railway/Render + Neon/Supabase + Cloudflare R2 · Sentry · OpenTelemetry · `AGPL-3.0` `LICENSE` and the DCO/CLA flow already in place from Phase 0.8 (the AGPL copyleft is what stops a competitor hosting a closed fork; the contributor agreement is what keeps a future commercial dual-licence possible) · `CONTRIBUTING.md` · security policy · a marketing site as a separate static build.

---

## Tooling: what exists, what changes, what is new

### Already installed — no action needed

`task-observer`, `skill-inspector`/`skillspector`, `dev-resource-map` (global). MCP servers `github` and `context7`, both verified functional with real calls. `chrome-devtools` MCP — idle for a Qt app, genuinely useful from Phase 4 on. Plugins `duckdb-skills` (becomes core rather than incidental) and `mlflow` (real value once Phase 5 compares forecasting models).

**The single biggest finding here: the `ecc` plugin already ships nearly every agent and skill this migration needs.** No authoring required for: agents `django-reviewer`, `react-reviewer`, `typescript-reviewer`, `database-reviewer`, `security-reviewer`, `e2e-runner`, `a11y-architect`, `performance-optimizer`, `django-build-resolver`, `react-build-resolver`; skills `django-patterns`, `django-security`, `django-tdd`, `django-celery`, `react-patterns`, `react-performance`, `react-testing`, `vite-patterns`, `frontend-a11y`, `design-system`, `postgres-patterns`, `redis-patterns`, `docker-patterns`, `deployment-patterns`, `e2e-testing`, `api-design`, `contract-first`, `database-migrations`, `security-review`, `accessibility`, `opensource-pipeline`. Plus `superpowers`' `writing-plans` / `executing-plans` / `test-driven-development` / `verification-before-completion`. `vercel:*` skills are available if the hosted instance goes to Vercel (frontend only — the Django backend needs a container host).

### Retire or rewrite (project-local `.claude/`)

| Item | Action |
|---|---|
| `.claude/skills/pyside6-development/` | **Delete** — dead the moment Phase 2 lands |
| `.claude/skills/dataviz-development/` | **Rewrite** for Plotly.js + web rendering |
| `.claude/skills/project-architecture/` | **Rewrite** for the core/api/web split |
| `.claude/skills/milestone-verification/` | **Rewrite** — verification becomes Playwright + Schemathesis + API, not offscreen Qt |
| `.claude/agents/a11y-reviewer.md` | **Rewrite** for web, or retire in favour of `ecc:a11y-architect` |
| `.claude/hooks/quality-check.ps1` | Fix the live `ruff format` vs `black` conflict; add a `.ts/.tsx` branch (prettier + eslint) |
| `.claude/hooks/pre-commit-check.ps1` | Rewrite — suite composition changes completely; add frontend checks |
| `.claude/skills/add-extension/` | Keep, extend with API-endpoint and chart-spec scaffolds |
| `.claude/skills/model-orchestration/`, `milestone-doc-sync/` | Keep; update routing tables |

### New project skills to author (3)

- **`provenance-model`** — the DAG invariants. The single most load-bearing rule in the product; it needs an enforceable written form.
- **`web-api-development`** — Django Ninja conventions, schema-first workflow, the `uadas_core` boundary rule.
- **`frontend-development`** — React/TS conventions, design-token usage, the accessibility floor.

### New external dependencies (install list)

**Local machine:** Node.js 22 LTS + pnpm · Docker Desktop · Playwright browsers · `uv` (lockfiles) · optionally Bruno.
**Services (via Docker locally):** PostgreSQL 17 · Redis 7 · MinIO.
**Python packages:** `django>=6.0`, `django-ninja`, `django-allauth`, `django-storages[s3]`, `django-cors-headers`, `psycopg[binary]`, `celery` or `rq`, `sentry-sdk`, `import-linter`, `schemathesis`, `pytest-django`, `pytest-cov`.
**Accounts to create:** a Postgres host (Neon/Supabase), object storage (Cloudflare R2/S3), an app host (Fly.io/Railway/Render), Sentry (free tier), a domain.

### Deliberately NOT adopted

Kubernetes · Kafka · a data warehouse · Airflow · a feature store · GraphQL · Next.js (RSC buys little for a client-heavy workbench and adds a second runtime) · a sandboxed plugin system in v1 · Semgrep (its OAuth flow is confirmed broken on this machine and it was already removed; `bandit` remains the SAST floor).

---

## Risks, honestly

| Risk | Mitigation |
|---|---|
| **Scope.** Six phases and a new product thesis on top of a 29-milestone codebase | Phases 0–4 are a port with a hard parity definition. Phase 5 is optional value on a shipped foundation. Do not blur them |
| **Deleting 101 UI files feels like destroying work** | Not deleted until its assets are extracted (Phase 2 table), and it stays in git history forever. Keeping it alive doubles the cost of every future feature |
| **Multi-tenancy retrofitted onto process singletons** | Addressed in Phase 1.4 *before* any Django code, not after |
| **The reader dependency stack (camelot/PyMuPDF/OpenCV/Tesseract) on untrusted uploads** | Sandboxed workers, Phase 3.8. Treat this as the primary security surface of the whole product |
| **F10 (in-browser execution) may not be achievable for the full stats path** | Prototype before committing. The DuckDB/Arrow half is well-proven; Pyodide for scipy/statsmodels is the uncertain half |
| **Velocity signal: 15 of the last 16 commits were CI firefighting** | Phase 0's CI hardening and Phase 2's deletion of the Qt test harness aim squarely at this |
| **Two acceptance boxes were never closed** (M28's NVDA screen-reader pass; M16's `ChartView` accessible name) | Both become moot with Qt gone, but the *obligation* transfers: the web app needs a real screen-reader pass |
| **AI-layer hallucination in the product itself** | F6 (AI proposes, never mutates) + F1 (every action is a logged, inspectable node) make a wrong AI step visible and reversible instead of silently applied |

---

## Verification summary

| Phase | The command that proves it |
|---|---|
| 0 | Green CI run including `ruff check` + `bandit` + a Linux job; `main` contains the merge |
| 1 | `python -c "import uadas_core"` in a venv with PySide6 uninstalled, on Linux; `lint-imports` green; a derived dataset survives save/load |
| 2 | `grep -r PySide6 .` empty; surviving suite green on Linux; regenerated `MYPY_DEBT.md` |
| 3 | `docker compose up` from a clean clone; Schemathesis green; tenant-isolation tests; malformed-upload sandbox test |
| 4 | Playwright E2E of the full pipeline; axe-core clean; generated client compiles |
| 5 | Per-feature acceptance criteria, written before implementation |

---

## Open questions for you

Two of the three original questions are resolved (see the header, Phase 0.4, Phase 0.8): licence = AGPL-3.0 + DCO/CLA from commit one; `src/models/` = delete. One remains, deliberately deferred to a later session:

1. **Name and domain** — "Universal AI Data Analytics & Visualization Studio" is a category description, not a product name. The positioning points at the glass-box idea. Blocks nothing; settle it before the repo goes public.
