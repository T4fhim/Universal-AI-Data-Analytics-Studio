# Phase 1.3 — De-globalize registries: executable plan

> **For agentic workers:** implement task-by-task, one commit per task. Behaviour-frozen
> (Control A10) *except* the one named `_CHART_BUILDERS` exemption in Task 3. Every functional
> commit reproduces the rolling golden baseline exactly (Control A9) + `screenshot_app_state.py`
> byte-identical + the B-3 characterization test green.

**Design doc:** `plans/phase-1-3-startup-graph.md` (Control B-1, opus-verified — read its §3a first).
**Playbook:** `plans/phase-1-execution-playbook.md` §1.3.
**Doctrine:** `docs/RESOURCE_ORCHESTRATION.md` — inline implementation (serial refactor); the only
subagent inside a per-commit cycle is the per-commit `code-reviewer`; `architect` +
`ecc:python-reviewer` + `ecc:silent-failure-hunter` run once over the whole range at the end.

## Global constraints

- **Rolling baseline at start (`cf3231c`): 1413 passed / 92 skipped / 0 failed.** Collected
  1488 / 1485 non-uia (per `plans/phase-1-baseline.md`). Re-verify by reproduction run before
  Task 1.
- A9: any suite delta other than a *documented* new authored test = abort (`git reset --hard`,
  fix, retry).
- A10: no behaviour/logic change **except** Task 3's `_CHART_BUILDERS` fix, which ships a named
  exemption worded like the four 1.8 security fixes.
- Never touch/stage/commit `config/config.yaml`.
- Suite command (mirrors CI, `QT_QPA_PLATFORM=offscreen`):
  ```
  python scripts/run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q --tb=no
  python scripts/run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py --tb=no
  ```
  inv-2 exiting `139` / `-1073741819` (`0xC0000005`) *after* a clean pytest summary = CI-green-equivalent.
- Screenshot: `python scripts/screenshot_app_state.py --output <tmp>.png` then compare bytes to
  `plans/baseline-app.png`.

## The core mechanic (applies to Tasks 2, 3, 4)

Today `operation_registry`, `chart_registry`, `result_renderer_registry` each call
`_register_builtins()` at **module import** (unconditional, process-wide). 1.3 moves that call
into `bootstrap()`. Two consequences, both handled per-task:

1. **`bootstrap()` runs 5x per session** (`tests/core/test_bootstrap.py:37,47,100,124,135`). A
   plain move makes the 2nd call raise `ServiceError: already registered`. -> **`_register_builtins()`
   must become idempotent**: module-level `_builtins_registered: bool = False` guard, mirroring
   `logger.py::_configured`. (Doc §3a offered "fixture *or* keep idempotent"; the 5x-bootstrap
   fact makes idempotency mandatory regardless.)
2. **~30 tests read the registry with no bootstrap** (`tests/cleaning/test_operation_registry.py`,
   `tests/visualization/test_chart_registry.py`, `tests/plugins/test_plugin_manager.py`,
   `tests/ui/help/test_manual_anti_rot.py`, `tests/ui/results/test_result_renderer_registry.py`,
   `tests/ui/workbench/test_clean_page.py`, plus the `tests/services/` + `tests/ai/` tiers via
   `tool_registry`). -> **one session-scoped `autouse=True` fixture in root `tests/conftest.py`**
   (`_seed_builtin_registries`) calls the same `_register_builtins()` functions. Adds 0 collected
   tests, so A9 survives; omitting it fails the suite outright.

`bootstrap.py` seeding goes **between `container = DependencyContainer()` (~:132) and
`plugin_manager.load_plugins()` (~:225)** - invariant: builtins present before plugins register.
(Per doc §3a corrected invariant 7, only operations + charts are true `load_plugins()`
prerequisites - `PluginManager` has no renderer category - but seeding all three in one place is
simplest and the renderer ordering is still "before first `get_renderer()`", trivially satisfied.)

---

## Task 1 - Safety net + `reader_registry` no-op (docs/test only)

**Files:**
- Create: `tests/core/test_startup_registry_characterization.py`
- Modify: `plans/phase-1-3-startup-graph.md` (add "§9 - as-built" stub, note reader row is a no-op)

**Steps:**
1. Write `tests/core/test_startup_registry_characterization.py` (B-3): after a `bootstrap()` with
   an isolated `config_path`/`log_dir` (copy the fixture pattern from `tests/core/test_bootstrap.py`),
   assert `len(list_operations()) == 5`, `len(list_charts()) >= 12`, `len(list_renderers()) == 11`,
   and that `container.resolve(T)` succeeds for every service `bootstrap()` registers
   (`AppConfig, ApplicationState, SettingsService, ProjectService, WorkspaceService,
   AnalysisOrchestratorService, GuidanceService, ReportService, DatabaseConnectionService,
   PluginManager, JobRunner`). This is the invariant every later task must keep green.
2. Run it - expect PASS today (registries import-populated, bootstrap wires services).
3. `plans/phase-1-3-startup-graph.md`: add `## 9. As-built (1.3)` - "Commit 1: B-3
   characterization test only; `reader_registry._PLUGIN_READERS` needs no conversion (already
   container-safe; `tests/readers/test_reader_registry.py:69,75,82,91` monkeypatch that exact
   attribute - converting would force test edits in a frozen step)."
4. Full suite -> **1413 + (B-3 count)**. Record the exact number in `plans/phase-1-baseline.md`
   as the Task-1 line.
5. Commit: `test(phase-1.3): B-3 startup-registry characterization test + reader_registry no-op note`
6. `code-reviewer` (haiku) on the diff.

---

## Task 2 - `operation_registry`: move `_register_builtins()` import -> `bootstrap()`

**Files:**
- Modify: `uadas_core/cleaning/operation_registry.py` (idempotency flag; delete `:105` call; docstring)
- Modify: `uadas_core/core/bootstrap.py` (import + call after `:134`)
- Modify: `tests/conftest.py` (new `_seed_builtin_registries` autouse session fixture)

**Steps:**
1. `operation_registry.py`: add `_builtins_registered: bool = False` beside `_REGISTRY`; top of
   `_register_builtins()` -> `global _builtins_registered` / `if _builtins_registered: return`;
   set `_builtins_registered = True` after the 5 `register_operation(...)` lines; delete the
   bare `_register_builtins()` at `:105`; change the function docstring "Called at import time"
   -> "Called from `uadas_core.core.bootstrap.bootstrap()` (web-transition 1.3 moved this off
   module import so import has no global-state side effect); idempotent so the 5x-per-session
   `bootstrap()` calls in the test suite are safe."
2. `bootstrap.py`: add `from uadas_core.cleaning import operation_registry` to imports; after the
   `logger.debug("Registered ApplicationState...")` line (~:143), before the SettingsService
   block, add:
   ```python
   # Web-transition 1.3: registry built-ins are populated here rather than as a
   # module-import side effect (plans/phase-1-3-startup-graph.md). Idempotent.
   operation_registry._register_builtins()
   ```
   (Placed after the container exists, well before `load_plugins()` at ~:225.)
3. `tests/conftest.py`: add
   ```python
   @pytest.fixture(scope="session", autouse=True)
   def _seed_builtin_registries() -> None:
       """Populate the built-in registries once per test session.

       web-transition 1.3 moved uadas_core.*.{operation,chart,result_renderer}_registry
       ._register_builtins() off module import into bootstrap(); tests that read a
       registry without calling bootstrap() need it seeded here. Idempotent, so a test
       that *does* call bootstrap() is unaffected.
       """
       from uadas_core.cleaning import operation_registry

       operation_registry._register_builtins()
   ```
4. Run `tests/cleaning/test_operation_registry.py` + `tests/core/test_startup_registry_characterization.py`
   + `tests/core/test_bootstrap.py` -> all PASS.
5. Full suite -> **== Task-1 number** (fixture adds 0). Screenshot byte-identical.
6. Commit: `refactor(phase-1.3): populate cleaning-operation built-ins in bootstrap(), not at import`
7. `code-reviewer` (haiku).

---

## Task 3 - `chart_registry` + `_CHART_BUILDERS` live fix (A10 exemption)

**Files:**
- Modify: `uadas_core/visualization/chart_registry.py` (idempotency flag; delete `:223` call; docstring)
- Modify: `uadas_core/core/bootstrap.py` (add `chart_registry._register_builtins()`)
- Modify: `uadas_core/ai/tool_registry.py` (`_CHART_BUILDERS` dict -> live `_chart_builders()`; 3
  handler sites; `:836` literal; `get_anthropic_tool_schemas()` live-enum route)
- Modify: `tests/conftest.py` (add chart seeding)
- Create: `tests/ai/test_tool_registry_chart_builders.py` (B-4 red->green)
- Modify: `plans/phase-1-3-startup-graph.md` §9 (name the exemption)

**Steps:**
1. `chart_registry.py`: same idempotency-flag treatment as Task 2; delete `:223`; docstring update.
2. `bootstrap.py`: add `from uadas_core.visualization import chart_registry` +
   `chart_registry._register_builtins()` right after the operations call.
3. `tool_registry.py`:
   - Replace `_CHART_BUILDERS = { ... }` (`:62-64`) with:
     ```python
     def _chart_builders() -> dict[str, type]:
         """Live name -> chart-class map from the shared chart registry.

         web-transition 1.3 (named A10 behaviour-change exemption, like the four 1.8
         security fixes): this was a module dict frozen at import, so a chart a plugin
         registered during bootstrap() -- after this module imports -- never reached the
         AI tool schema (the build_chart enum) or _build_chart's dispatch. Recomputed per
         call so plugin charts are reachable by the assistant.
         """
         return {name: reg.chart_class for name, reg in list_charts().items()}
     ```
   - `_build_chart` (`:424-429`): `builders = _chart_builders()` then use `builders` in the
     membership check, the error message, and the lookup.
   - `:836`: `"enum": sorted(_chart_builders())` (import-time value = a sane default; the read
     path below overrides it live).
   - Add `_live_input_schema(tool: ToolDefinition) -> dict[str, Any]`: returns `tool.input_schema`
     unchanged for every tool except `build_chart`, for which it returns a shallow-merged copy
     with `["properties"]["chart_type"]["enum"] = sorted(_chart_builders())`.
   - `get_anthropic_tool_schemas()`: `"input_schema": _live_input_schema(t)` instead of
     `t.input_schema`.
4. `tests/conftest.py`: add `from uadas_core.visualization import chart_registry` +
   `chart_registry._register_builtins()` to `_seed_builtin_registries`.
5. Create `tests/ai/test_tool_registry_chart_builders.py`:
   - `test_plugin_chart_registered_after_import_reaches_build_chart_enum`: `register_chart(
     "_b4_probe", ChartRegistration(HistogramChart, ("column",)))`; in `try/finally`
     (`unregister_chart`), get `get_anthropic_tool_schemas()`, find the `build_chart` entry,
     assert `"_b4_probe" in schema["input_schema"]["properties"]["chart_type"]["enum"]`.
   - `test_build_chart_handler_dispatches_a_post_import_registered_chart`: same register, assert
     `_build_chart` does not raise `Unknown chart_type` for `"_b4_probe"` (stub dataset / assert
     it reaches `builder.build`).
   - Run against **current** `tool_registry` first to confirm RED (frozen dict), then apply
     step 3 and confirm GREEN.
6. `plans/phase-1-3-startup-graph.md` §9: add
   "**A10 behaviour-change exemption (1.3-3).** Before: a chart registered after
   `uadas_core.ai.tool_registry` import was invisible to the assistant (`_CHART_BUILDERS` frozen
   at `:62-64`; `build_chart` enum at `:836`; `_build_chart` dispatch at `:424-429`). After:
   `get_anthropic_tool_schemas()` and `_build_chart` read the chart registry live via
   `_chart_builders()`. No built-in chart's schema changes; the only observable difference is
   that plugin charts now appear in the `build_chart` tool. Same class of scoped, test-guarded
   behaviour change as the four 1.8 security fixes."
7. Full suite -> **== Task-2 number + 2** (the two B-4 tests). Screenshot byte-identical.
8. Commit: `refactor(phase-1.3): chart built-ins in bootstrap() + live _CHART_BUILDERS (A10 exemption)`
9. `code-reviewer` (haiku) - explicitly ask it to check the `_live_input_schema` copy does not
   mutate the shared `TOOLS` entry.

---

## Task 4 - `result_renderer_registry`: move `_register_builtins()` import -> `bootstrap()`

**Files:**
- Modify: `uadas_core/results/result_renderer_registry.py` (idempotency flag; delete `:157` call; docstring)
- Modify: `uadas_core/core/bootstrap.py` (add `result_renderer_registry._register_builtins()`)
- Modify: `tests/conftest.py` (add renderer seeding)

**Steps:**
1. Same idempotency-flag treatment; delete `:157`; docstring update.
2. `bootstrap.py`: add import + `result_renderer_registry._register_builtins()` after the chart call.
3. `tests/conftest.py`: add renderer seeding to `_seed_builtin_registries`.
4. Run `tests/ui/results/test_result_renderer_registry.py` + the B-3 test -> PASS.
5. Full suite -> **== Task-3 number**. Screenshot byte-identical.
6. Commit: `refactor(phase-1.3): result-renderer built-ins in bootstrap(), not at import`
7. `code-reviewer` (haiku).

---

## Task 5 - Record the keep-decisions + close out

**Files:**
- Modify: `plans/phase-1-3-startup-graph.md` §9 (logger._configured + path constants: KEPT, why)
- Modify: `docs/ARCHITECTURE.md` ("Application startup sequence" - built-ins now seeded in bootstrap())
- Modify: `plans/phase-1-baseline.md` (Post-1.3 section, final counts)
- Modify: `.superpowers/sdd/phase-1-3/progress.md` + `.superpowers/sdd/phase-1/progress.md` (1.3 DONE)

**Steps:**
1. §9: "`logger._configured` - KEPT as-is (§7d): one-call-site idempotence guard, no dependency
   chain, converting adds complexity for nothing. `constants.py` `PROJECT_ROOT` + derived path
   constants - CANNOT convert (§3a row 6): `tests/ui/test_module_size.py:69`,
   `test_i18n_wrapped_strings.py:126`, `test_import_layering.py:106` read `PROJECT_ROOT` at
   pytest **collection** time to build parametrize id lists; container-resolving it changes the
   collected-test count -> instant A9 abort. They are immutable (`Path(__file__)`-derived), not
   global mutable state."
2. `docs/ARCHITECTURE.md`: one paragraph in the startup-sequence section - the three built-in
   registries are populated by `bootstrap()` (idempotent `_register_builtins()` calls) rather
   than as a module-import side effect, so importing `uadas_core` has no global-state effect
   (Phase-3 / multi-instance readiness).
3. `plans/phase-1-baseline.md`: Post-1.3 section - final suite counts, the +N breakdown (B-3
   tests, B-4 x2, autouse fixture adds 0), screenshot byte-identical, `bandit` clean.
4. SDD ledgers: 1.3 DONE with commit range, per-commit `code-reviewer` verdicts, the end-of-range
   `architect` / `ecc:python-reviewer` / `ecc:silent-failure-hunter` verdicts.
5. Full suite once more for the recorded final number. Commit:
   `docs(phase-1.3): record keep-decisions, startup-sequence doc, post-1.3 baseline`

---

## End-of-range review (after Task 5, before final push verdict)

1. Repo `architect` (haiku): confirm `bootstrap.py`'s startup order still honours invariants
   1-8 + §3a (config->logger->container->services->**registry seeds**->plugins->JobRunner).
2. `ecc:python-reviewer` over `cf3231c..HEAD`.
3. `ecc:silent-failure-hunter` over the same range (focus: the `_chart_builders()` /
   `_live_input_schema` paths, the idempotency guards).
4. Fix loop <= 5 rounds; verdicts into the SDD ledger.
5. `git push`; confirm branch CI (`test` + `lint` + `linux_import` + `uia_integration`) green via `gh`.
6. **Stop. Report. Await go-ahead for 1.4.**
