# Phase 1.3 — Startup Dependency Graph (Control B-1)

**Status:** produced 2026-09-08 by the repo `architect`; **verified 2026-09-08 by `ecc:architect`
(opus)** — writer ≠ verifier (A3). Verdict: **§2 confirmed; §3 amended (see §3a); §7 rulings
decided (see §7); two §1 claims corrected.** Ready for 1.3 with the §3a additions in force.

Maps the import-time → side-effect graph, the `bootstrap()` sequence with load-bearing reasons,
and per-registry conversion hazards for the six items Phase 1.3 de-globalizes. Line numbers are
approximate (`~:NN`) — re-verify at implementation time (living-truth discipline).

---

## 1. Module-import → side-effect graph

### 1.1 `uadas_core/readers/reader_registry.py`
- `_BUILTIN_READERS: tuple[...]` (~:47-64) — **frozen tuple, stays as-is** (converting it is churn).
- `_PLUGIN_READERS: list[...]` (~:72) — mutable, initialized empty at import, populated by
  `PluginManager.load_plugins()` at `bootstrap.py ~:225`.
- **Import-time readers:** none take a snapshot.
- **If import-time init removed:** nothing breaks — already bootstrap-safe; the only import
  effect is the empty-list initialization.

### 1.2 `uadas_core/cleaning/operation_registry.py`
- `_REGISTRY: dict[str, type[BaseOperation]]` (~:35); `_register_builtins()` **called at import**
  (~:105), registers ~5 operations.
- **Import-time readers:** none snapshot.
- **If the import-time call removed:** `PluginManager.load_plugins()` (`~:225`) cannot register
  operations unless `_register_builtins()` has run first. Move the call into `bootstrap()`
  **between container creation and `load_plugins()`**.

### 1.3 `uadas_core/visualization/chart_registry.py` — **entangled with the `_CHART_BUILDERS` bug**
- `_REGISTRY: dict[str, ChartRegistration]` (~:84); `_register_builtins()` **called at import**
  (~:223), registers ~12 charts.
- **Import-time readers that snapshot:**
  - `uadas_core/ai/tool_registry.py:51-64` — imports `list_charts` and **freezes** a
    `_CHART_BUILDERS` dict at `:62-64`. A chart a plugin registers *after* import never appears
    there (and never reaches the LLM tool schema at `tool_registry.py:836`). This is the B-4 bug.
  - `src/ui/dialogs/create_visualization_dialog.py:44,58-68` — builds a `_CHART_REGISTRY`
    snapshot at import.
  - `uadas_core/services/guidance_service.py` — imports `list_charts` at module level
    (snapshot-vs-live-read unverified — §8).
- **If the import-time call removed:** `_CHART_BUILDERS` is empty when `tool_registry` imports.
  De-globalizing `chart_registry` and fixing `_CHART_BUILDERS` are the **same commit's problem**.

### 1.4 `uadas_core/results/result_renderer_registry.py`
- `_REGISTRY: dict[type, type[BaseResultRenderer]]` (~:70); `_register_builtins()` **called at
  import** (~:157), registers ~11 renderers.
- **Import-time readers:** `src/ui/results/result_card.py` imports from the registry (import- vs
  runtime read unverified — §8). There is a `GenericResultRenderer` fallback (~:104-117), so an
  empty registry degrades presentation rather than crashing.
- **If the import-time call removed:** move it into `bootstrap()` **before `load_plugins()`**.

### 1.5 `uadas_core/core/logger.py::_configured`
- `_configured: bool = False` (~:45); `if _configured: return` early-return (~:76-78); set `True`
  (~:106). Idempotence guard for `configure_logging()`, called from `bootstrap.py ~:119`.
- **If removed:** a second `configure_logging()` call (test re-init) attaches duplicate handlers
  → duplicate log lines. The module docstring's contract text ("calling it again is a no-op…
  but it also will not apply new settings") must travel with any conversion.

### 1.6 `uadas_core/core/constants.py` path constants
- `PROJECT_ROOT = Path(__file__).resolve().parents[2]` (~:37) + `CONFIG_DIR`, `CONFIG_FILE_PATH`,
  `LOG_DIR`, `PROJECTS_DIR` derived (~:38-44).
- **Bound as default-argument values at def-time:** `bootstrap.py:84-85`
  (`config_path=CONFIG_FILE_PATH, log_dir=LOG_DIR`), `config.py:462,588`, `logger.py:51`,
  `settings_service.py:56`.
- **Read at import in `src/ui/`:** `manual_index.py` (`MANUAL_ROOT`), `web_assets.py`
  (`_SOURCE_WEB_ROOT`), and `icon_provider.py` / `qss_compiler.py` / `empty_state.py` (exact
  lines unverified — §8) — each builds a further module-level path.
- **If converted to container-resolved:** every function above must accept `None` and resolve at
  runtime, rippling to every call site (`main.py`, tests, scripts, CLI). These are *immutable*
  (computed once from the source file's location), unlike the mutable registries — arguably not
  "global mutable state" at all. See §7d.

---

## 2. `bootstrap()` ordering — the load-bearing sequence

Every side-effecting statement in `uadas_core/core/bootstrap.py`, in order (line numbers approx):

| ~Line | Statement | Depends on | Critical for |
|---|---|---|---|
| :114 | `config = AppConfig.load(config_path)` | (first) | logger reads `config.log_level` / `log_max_bytes` / `log_backup_count` |
| :119-124 | `configure_logging(...)` | config (:114) | every downstream logger call |
| :125 | `logger = get_logger(__name__)` | configure_logging | logging at :126+ |
| :132 | `container = DependencyContainer()` | logger | registration events log at DEBUG |
| :133 | `container.register(AppConfig, …)` | container | — |
| :141-142 | `state = ApplicationState()` / register | — | — |
| :153-154 | `SettingsService(config, config_path)` / register | config | `DatabaseConnectionService` (:204) |
| :157-158 | `ProjectService(…)` / register | `config.recent_projects` | — |
| :161-162 | `WorkspaceService()` / register | — | `AnalysisOrchestratorService` (:170), `ReportService` (:196) |
| :170-175 | `AnalysisOrchestratorService(workspace_service)` / register | workspace_service | `GuidanceService` (:186), `ReportService` (:196) |
| :186-188 | `GuidanceService(analysis_orchestrator_service)` / register | analysis_orchestrator_service | — |
| :196-198 | `ReportService(workspace_service, analysis_orchestrator_service)` / register | both | — |
| :204-208 | `DatabaseConnectionService(settings_service)` / register | settings_service | — |
| :220-227 | `PluginManager(…); load_plugins(); register` | **all 4 registries populated + `logger._configured` in place** | plugin registration of charts / operations / renderers / readers |
| :243-246 | `ThreadPoolExecutorJobRunner(…)`; register; `set_default_job_runner` | — | `BaseWorker.run()` at runtime (Phase-1.2 bridge) |
| :248-260 | `BootstrapContext(…)`; return | all services | app entry point |

`config.py` deliberately does **not** import the project logger (it is a dependency of the
logger, not a consumer). Keep that.

---

## 3. Load-bearing invariants (non-negotiable — 1.3 must preserve all)

1. Config loaded **before** logger configured (`configure_logging` reads config values).
2. Logger configured **before** any downstream code logs.
3. Container created **after** logger configured (registration logging).
4. `WorkspaceService` **before** `AnalysisOrchestratorService` (constructor arg).
5. `AnalysisOrchestratorService` **before** `GuidanceService` and `ReportService` (constructor args).
6. `SettingsService` **before** `DatabaseConnectionService` (constructor arg).
7. ~~All four registries + `logger._configured` before `load_plugins()`~~ — **see §3a, this was
   over-broad and is not the true pivot.**
8. `JobRunner` registered **after** `PluginManager` (no plugin depends on it at load time).

---

## 3a. Amendments from opus verification (in force — read before any 1.3 code)

**Invariant 7, corrected — THREE registries, not four.** `PluginManager` registers exactly
`readers`, `cleaning_operations`, `charts` (`uadas_core/plugins/plugin_manager.py:118-129`,
`plugin_loader.py:130,151-165`). **There is no renderer plugin category.** So
`result_renderer_registry`'s position relative to `load_plugins()` is **not load-bearing** —
its only constraint (invariant 8') is "populated before the first `get_renderer()` call", which
is UI runtime, strictly weaker. §4 row 4's "plugins can't register renderers" hazard is false.

**Invariant 9 (the real behaviour change 1.3 makes — B-1 originally missed this).** Today the
four `_register_builtins()` calls run at **module import** — unconditional, process-wide,
before `bootstrap()`'s first statement (the import graph seeds them via `bootstrap.py:45` →
`PluginManager` → the registry modules). Moving a call into `bootstrap()` makes registry
population **conditional on `bootstrap()` having run**. Consequences that will fail the suite if
unhandled:
- `tests/cleaning/test_operation_registry.py:19-23` asserts `len(list_operations()) == 5` with
  **no bootstrap**; its `:37-41` comment names "populate at import time" as load-bearing.
- `tests/visualization/test_chart_registry.py:20-24` asserts `len(list_charts()) >= 12`, no bootstrap.
- `uadas_core/ai/tool_registry.py:62-64` builds `_CHART_BUILDERS` from `list_charts()` at *its*
  import; consumed by `AnalysisOrchestratorService.run_stage` (`analysis_orchestrator_service.py:378`)
  and the whole `tests/services/` tier — none of which bootstrap.

**→ Each B-2 commit that de-globalizes a registry MUST ship an autouse session fixture (or keep
`_register_builtins()` import-time-idempotent) that seeds that registry for the
non-bootstrapping test tiers.** A fixture adds zero collected tests, so A9 survives — but
*omitting* it fails the suite outright. This is the single most important thing for the 1.3
implementer.

**`PluginManager.__init__` signature change.** When a registry becomes a container instance,
`PluginManager._unregister_plugin` (`plugin_manager.py:118-129`) — which calls the module-level
`unregister_*` it imported at `:18,21,22` — must be handed the registry instances instead. That
is a **constructor signature change at `bootstrap.py:220-224`**, part of rows 2/3's diff.

**§1 corrections:**
- **Delete the `guidance_service.py` bullet in §1.3** — `guidance_service.py:55` imports
  `display_name_for` (a pure string function, `chart_registry.py:157-159`), **not** `list_charts`.
  It reads no registry.
- **Strike the `result_card.py` caveat in §1.4 / §8-2** — `src/ui/results/result_card.py:44`
  imports the *function* `get_renderer`; the call is at `:103` in a method. Runtime read, no
  import-time snapshot, no hazard.

**§4 row 1 (`reader_registry._PLUGIN_READERS`) — restate as no-op / drop from the B-2 sequence.**
It needs no conversion; and `tests/readers/test_reader_registry.py:69,75,82,91` monkeypatch that
exact module attribute, so *converting* it would force test edits inside an A9/A10-frozen step
for zero benefit. If B-2 keeps it as commit 1, that commit is documentation-only.

**§4 row 6 (path constants) — upgrade "recommend keep" to "CANNOT convert."** Three test modules
read `PROJECT_ROOT` at **collection** time to build `@pytest.mark.parametrize` id lists
(`tests/ui/test_module_size.py:69`, `test_i18n_wrapped_strings.py:126`, `test_import_layering.py:106`).
Container-resolving `PROJECT_ROOT` makes those lists unbuildable at collection → the
**collected-test count changes** → instant A9 abort. (Cosmetic follow-up, not 1.3:
`constants.py:12-13` docstring still says "→ src → project root"; `parents[2]` is numerically
still correct.)

**§4 row 4 (`_register_builtins()` side effects) — the only per-call effects are the dict write
and one `_logger.debug` per registration.** No object construction (registered values are
classes). The real cost is transitive import (`result_renderer_registry.py:35-66` pulls all of
`uadas_core.analysis` + `uadas_core.forecasting`; `chart_registry.py:25-36` pulls plotly) —
Phase-3 cold-start relevant, not 1.3.

---

## 4. Per-registry conversion + hazard (the 6 B-2 commits)

| # | Item | Conversion | Hazard |
|---|---|---|---|
| 1 | `reader_registry._PLUGIN_READERS` | none needed — already container-safe | none |
| 2 | `operation_registry._REGISTRY` | move `_register_builtins()` into `bootstrap()` between `:132` and `:225` | placed after `:225` → plugins can't register operations |
| 3 | `chart_registry._REGISTRY` | move `_register_builtins()` as above **AND** fix `_CHART_BUILDERS` (`tool_registry.py:62-64,424,427,429,836`) from a frozen dict to a live `list_charts()` call at use time | **behaviour change** — plugin charts newly appear in the AI tool registry + schema. §7b ruling. B-4 red→green |
| 4 | `result_renderer_registry._REGISTRY` | move `_register_builtins()` as above | placed after `:225` → plugins can't register renderers; UI degrades to `GenericResultRenderer` |
| 5 | `logger._configured` | **recommend keep as-is** — a one-call-site guard with no dependency chain; converting adds complexity for nothing | if removed: double `configure_logging()` → duplicate handlers |
| 6 | `constants.py` path constants | **recommend keep as module constants** — immutable, computed once from `__file__`; not "global mutable state" like the registries; converting ripples to every default-arg call site | if converted badly: every `bootstrap`/`config`/`logger`/`settings_service` call site changes signature |

---

## 5. `src/ui/actions/action_registry.py` — skip in 1.3
Same pattern (`_REGISTRY` at ~:128, `builtin_actions.py:269` calls `_register_builtins()` at
import, `main_window.py:46` imports it). It is in the `src/ui/` shell Phase 2 deletes. **Do not
convert** (§7c).

## 6. JobRunner globals — keep the documented bridges
`uadas_core/jobs/__init__.py:47` (`_default_job_runner`) and `src/workers/base_worker.py:58-59`
(`_fallback_job_runner`, `_fallback_lock`) are Phase-1.2-only bridges; `BaseWorker` dies in
Phase 2. **Keep as-is** (§7d). Test coupling (corrected by opus verify):
`tests/jobs/test_default_job_runner_registry.py:25-30` does a raw `jobs_pkg._default_job_runner
= None … = saved` save/restore in `try/finally` (not `monkeypatch.setattr`); `base_worker.py`'s
`_fallback_job_runner` / `_fallback_lock` are touched by **no test**. Renaming still breaks the
first test and A9 forbids a test-count delta, so the conclusion holds.

---

## 7. Rulings — DECIDED 2026-09-08 (`ecc:architect` opus)

- **7a — §2 order invariant: ACCEPTED as correct/complete. §3 REJECTED as written → replaced by
  §3a** (invariant 7 → three registries; new invariant 9 = the import→bootstrap visibility
  change + its autouse-fixture requirement; invariant 8' for `result_renderer_registry`).
- **7b — `_CHART_BUILDERS`: fix in the SAME commit as the `chart_registry` de-globalization,
  with a named A10 behaviour-change exemption (worded as 1.8's four were). NOT optional** — once
  `_register_builtins()` leaves import time, `tool_registry.py` freezes `{}` and `:424` / `:429`
  / `:836` hard-fail, so a split "1.3b" would ship a knowingly-broken green-less commit
  (A2 violation). The fix moves **all four** sites (`:62-64`, `:424`, `:427`, `:429`, `:836`) to
  a live `list_charts()` call. B-4 red→green (register a chart post-import, assert it reaches the
  `enum` at `:836`) is the acceptance gate.
- **7c — `src/ui/actions/action_registry.py`: SKIP.** Outside `uadas_core/`, outside the
  import-linter contract, Phase 2 deletes it; `tests/ui/test_command_palette.py:26` monkeypatches
  `_REGISTRY` directly so converting = a guaranteed test edit in a frozen step. Add a one-line
  pointer in the doc that it dies with `src/ui/`.
- **7d — JobRunner globals + `constants.py` path constants: KEEP both.** JobRunner globals are
  self-documenting Phase-1.2 bridges; converting means editing `BaseWorker.__init__` (A10
  violation) or `test_worker_runner.py` (A10 forbids). Path constants: converting changes the
  collected-test count (§3a row 6) → A9 abort. Both are hard "cannot", not soft "recommend".

## 7b. Carried into 1.4 (from the same opus pass)

- The typed generic is an `@overload` pair with a **`-> Any`** fallback (not `-> object` — that
  triggers `overload-overlap` on `dependency_container.py`, which is already in CI's mypy scope,
  turning 1.4's own target red).
- "Fold `dependency_container.py` into `ci.yml:122`" is a **no-op** — `uadas_core/core` is
  already entry #1 there. Instead: record the before/after `mypy src/ui/main_window.py` count in
  `docs/MYPY_DEBT.md` (31 → N) as the A4 evidence, **and add `src/app.py` to `ci.yml:122`** — it
  carries 3 `cast()` calls that exist only because `resolve()` returns `object` (`src/app.py:155-165`),
  the generic deletes them, `src/app.py` survives Phase 2, and it closes a silent post-1.1
  mypy-coverage regression (`ci.yml:104-106` comment says `src/core/app.py` is covered via
  `src/core`, but `src/core` is no longer on the list).
- `Session` scope: **CUT from 1.4, deferred to Phase 3.** Amend
  `plans/web-transition-glass-box-studio.md:377` to say 1.4 delivers the typed-resolution half
  and Phase 3 owns scope. Cheap forward-compat: one sentence in `DependencyContainer`'s class
  docstring noting the arbitrary-hashable-key path is the intended Phase-3 `(session, type)` seam.

---

## 8. Unverified

1. Exact lines in `icon_provider.py` / `qss_compiler.py` / `empty_state.py` where `PROJECT_ROOT`
   is read at import.
2. `src/ui/results/result_card.py` — is the `result_renderer_registry` read at import or runtime?
3. `uadas_core/services/guidance_service.py` — snapshot vs. live read of `list_charts()`.
4. Side effects of the four `_register_builtins()` calls beyond populating the dict (logging?
   object construction? external calls?).
5. Plugin-disable path: `PluginManager` calling `unregister_chart/operation/renderer` against a
   container-resolved registration.

*(1–2 moot: those modules stay as-is under the opus-narrowed scope. 3: resolved by §3a —
`guidance_service.py:55` imports `display_name_for`, not `list_charts`. 4: resolved by §3a
row 4 — dict write + one `_logger.debug` per registration, no construction. 5: `PluginManager`
keeps calling the module-level `unregister_*`; the registry modules keep their module-level
`_REGISTRY` — 1.3 only moves *when* `_register_builtins()` runs, not *where* the dict lives.)*

---

## 9. As-built (Phase 1.3 — filled in during execution)

**Executable plan:** `plans/phase-1-3-plan.md` (6 tasks, one commit each).

**Scope, as narrowed by opus verification and confirmed against the tree 2026-09-08:** 1.3 does
**not** convert any `_REGISTRY` to a container instance. It moves the import-time
`_register_builtins()` call into `bootstrap()` for the three registries that have one
(`cleaning/operation_registry`, `visualization/chart_registry`,
`results/result_renderer_registry`), makes each `_register_builtins()` idempotent, adds a
session-autouse seed fixture in `tests/conftest.py` for the non-bootstrapping test tiers, and
fixes the `_CHART_BUILDERS` import-time snapshot (Task 3, named A10 exemption below).

- **`reader_registry._PLUGIN_READERS` — no-op (Task 1).** Already container-safe (empty list at
  import, populated by `PluginManager.load_plugins()`). `tests/readers/test_reader_registry.py`
  lines 69/75/82/91 monkeypatch that exact module attribute — converting it would force test
  edits inside an A9/A10-frozen step for zero benefit. Task 1 is the B-3 characterization test
  (`tests/core/test_startup_registry_characterization.py`) + this note only.

- **Idempotency is mandatory (Tasks 2–4).** `tests/core/test_bootstrap.py` calls `bootstrap()`
  five times in one pytest session (lines 37/47/100/124/135). Moving `_register_builtins()`
  into `bootstrap()` without a guard makes the 2nd call raise `ServiceError: already
  registered`. Each `_register_builtins()` gets a module-level `_builtins_registered: bool`
  flag, mirroring `uadas_core/core/logger.py::_configured`.

- **A10 behaviour-change exemption (Task 3) — live chart-registry reads.** Two module-level
  dicts were frozen from the chart registry at *their* import time and never refreshed:
  `uadas_core/ai/tool_registry.py::_CHART_BUILDERS` (fed `_build_chart`'s dispatch at `:424-429`
  and `build_chart`'s `chart_type` enum in the `TOOLS` literal at `:836`) and
  `src/ui/dialogs/create_visualization_dialog.py::_CHART_REGISTRY` (fed the dialog's chart-type
  combo and field layout). Once `chart_registry._register_builtins()` moved into `bootstrap()`
  — which runs *after* both modules import — both snapshots were empty, so Task 3 had to convert
  them in the same commit:
  - `_CHART_BUILDERS` → `_chart_builders()` function (live `list_charts()` read); `_build_chart`
    calls it; `get_anthropic_tool_schemas()` refreshes the `build_chart` enum per call via a new
    `_live_input_schema()` helper (returns a copy — never mutates the shared `TOOLS` entry).
  - `_CHART_REGISTRY` → `_chart_registry()` function (live `list_dialog_charts()` read); the
    dialog's 3 call sites updated.
  **Observable behaviour change:** a chart a plugin registers during `bootstrap()` now appears
  in the AI `build_chart` tool schema *and* the create-visualization dialog — previously it
  reached neither. No built-in chart's schema or dialog entry changes. Same class of scoped,
  test-guarded change as the four 1.8 security fixes. Guarded by
  `tests/ai/test_tool_registry_chart_builders.py` (B-4, red→green) + the existing
  `tests/ui/dialogs/test_create_visualization_dialog.py` / `tests/ui/workbench/test_visualize_page.py`
  suites. Also fixed a latent pre-existing leak: `tests/visualization/test_chart_registry.py
  ::test_register_chart_new_name_succeeds` now `unregister_chart()`s in a `finally` (it was
  polluting `list_charts()` for every later test — masked only by collection order).

- **`logger._configured` — KEPT (Task 5).** *(Filled in at Task 5.)*
- **`constants.py` path constants — KEPT / CANNOT convert (Task 5).** *(Filled in at Task 5.)*
