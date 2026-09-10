# Phase 1 — Golden Baseline (R0.1)

**Captured:** 2026-09-07 · **against `main` = `1f06bdc`** (`1f06bdced9910f1159022c12a646d6d072d65b14`).

This is the pass criterion for **Control A9**: after step 1.1's `git mv`, the full suite must
reproduce **these exact numbers**. A delta of one test = something was lost or broken by the
move — abort and fix the codemod (Risk A abort criterion).

Reproduce with `scripts/run_tests_and_exit_cleanly.py` exactly as below (mirrors CI's
two-invocation split; `QT_QPA_PLATFORM=offscreen`).

---

## Suite result

| Invocation | Command | Result |
|---|---|---|
| **1** | `run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q --tb=no` | **10 passed**, 0 skipped · 0.18 s · exit `0` |
| **2** | `run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py --tb=no` | **1371 passed, 103 skipped, 3 deselected**, 0 failed, 0 errored, 0 xfailed, 0 xpassed · 44 warnings · 539.95 s · process exit `-1073741819` |
| **combined** | — | **1381 passed · 103 skipped · 3 deselected · 0 failed** |

**Wall clock** (both invocations, this machine): **546 s (~9.1 min)**.

### The invocation-2 exit code is expected and is CI-green-equivalent

`-1073741819` = `0xC0000005`, a Windows access violation during CPython/Qt interpreter
teardown — *after* pytest has printed its fully-clean result. This is the exact condition
`scripts/run_tests_and_exit_cleanly.py` and `.github/workflows/ci.yml` are built around:
CI's `test` step ends with `exit ([Math]::Max($exit1, $exit2))`, and because `0xC0000005` is a
**negative** signed int, `Max(0, -1073741819) = 0` — the job is green. A *real* pytest failure
returns a positive code (1–5), which `Max` would surface. So this baseline run == a green CI
`test` job. The clean counts above are pytest's own fully-determined result and are what A9
compares.

---

## Collected-test counts (`pytest --collect-only`)

| Selection | Collected |
|---|---|
| `-m "not uia_integration"` | **1484** (of 1487; 3 deselected) |
| full (incl. `uia_integration`) | **1487** |

So: **1487 total** · **1484 non-uia_integration** · **3 uia_integration** (run as their own CI job, not part of this baseline).

---

## App screenshot

`scripts/screenshot_app_state.py --output plans/baseline-app.png` → exit `0`,
**`plans/baseline-app.png`** (16,294 bytes), committed beside this file. Boot path exercised
clean: `bootstrap()` → 0 plugins → `MainWindow` constructed → theme `dark`/comfortable applied
→ chart web-assets staged → screenshot saved → window closed. Step 1.1 verification ⑦
visual-diffs the post-carve-out screenshot against this one.

*(This resolves one plan Unverified item: `screenshot_app_state.py` boots cleanly on the
pre-carve-out tree.)*

---

## Post-1.1 adjustment (recorded 2026-09-07)

Step 1.1's carve-out moves ~112 `.py` files from `src/` to `uadas_core/` and adds one new
`uadas_core/__init__.py`. `tests/ui/test_import_layering.py::test_nothing_outside_ui_imports_ui`
is parametrized over *every* source module (so the "nothing outside `src/ui` imports `src.ui`"
rule is enforced file-by-file); it was widened in 1.1 to also scan `uadas_core/`, so it keeps
enforcing that rule over the moved code. Net effect on the counts: **exactly +1** parametrized
case (the new package `__init__.py`), which passes.

**Post-1.1 expected numbers** — collected **1488 / 1485 non-uia** (was 1487 / 1484); suite
**1382 passed, 103 skipped, 0 failed** (was 1381 passed). Any *other* delta = a real
regression from the move (Risk A abort criterion still applies to everything except this
one documented +1).

**Post-1.5 (lift `src/ui/results/` renderers → `uadas_core/results/`):** ~11 renderer modules
leave `src/ui/`, so the two `src/ui/`-scoped meta-tests (`test_module_size.py`,
`test_i18n_wrapped_strings.py`) correctly stop parametrizing over them — collected drops to
**~1469** (−19). `test_import_layering.py` (which scans both trees since 1.1) still covers the
renderers, now via its `uadas_core` branch. Suite **1374 passed / 92 skipped / 0 failed**.

**Post-1.2 (JobRunner):** strictly additive — new `uadas_core/jobs/` package + its tests.
Suite **1405 passed / 92 skipped / 0 failed** (inv-2: 1395, was 1364, **+31**: +28 authored
JobRunner tests, +3 structural from `test_import_layering` parametrizing over the 3 new
`uadas_core/jobs/*.py` modules — same mechanism as the Phase 1.1 `+1`). Screenshot
byte-identical. `WorkerSignals` + `BaseWorker.__init__` + `src/ui/worker_runner.py`
byte-for-byte unchanged (A10). Independently re-verified by the orchestrator 2026-09-07.

**Post-1.2 review fixups (`caa5d0b`):** +1 caching regression test → **1406 passed / 92 / 0**.

**Post-1.8 (four security fixes):** four named behaviour changes (A10 does not apply to 1.8),
each test-guarded. Strictly additive to the test count — **+7 authored tests**, no source
modules added so no `test_import_layering` structural delta. Suite **1413 passed / 92 skipped /
0 failed** (inv-1 `test_worker_runner` 10; inv-2 **1403 passed, 92 skipped, 3 deselected, 0
failed**, process exit `139` = the same post-clean-result Windows/Qt teardown SIGSEGV the inv-2
note above describes → CI-green-equivalent under `Max(exit1, exit2)`). Wall clock inv-2 ~6.5
min. `bandit -r src uadas_core -q --skip B101,B107,B608` → exit 0. The +7: iteration-cap (1),
zip-slip traversal + symlink (2), injected-secrets + env-fallback (2), SQL-capability refused
on `execute_query` + on `read_query` (2). Any *other* delta would be a regression.

**Post-1.3 (de-globalize registries — commits `0443013` `54c69fa` `746897e` `efa61ce` `e5c3fee`
`b4ca38c` + review-fixups):** behaviour-frozen (A10) except **one named exemption** in `746897e`
(Task 3): `tool_registry`'s `_CHART_BUILDERS` and `create_visualization_dialog`'s `_CHART_REGISTRY`
— both frozen-at-import chart snapshots — became live functions, so a plugin chart registered
during `bootstrap()` now reaches the AI `build_chart` tool and the create-visualization dialog
(it reached neither before). No built-in chart's schema/entry changes. **Test count +7 authored,
no other delta:** +2 B-3 (`tests/core/test_startup_registry_characterization.py`), +4 B-4
(`tests/ai/test_tool_registry_chart_builders.py`), +1 import-side-effect subprocess guard (also
in the B-3 file, from the review-fixups commit); the three `_register_builtins()` moves, the
`tests/conftest.py` seeding, and the `test_chart_registry.py` leak-cleanup fix each add 0
collected tests. Suite **1420 passed / 92 skipped / 0 failed** (inv-1 `test_worker_runner` 10;
inv-2 **1410 passed, 92 skipped, 3 deselected, 0 failed**, process exit `0` on the fixup run —
earlier 1.3 runs exited `139`, the usual post-clean Windows/Qt teardown SIGSEGV; both are
CI-green-equivalent under `Max(exit1, exit2)`). `screenshot_app_state.py` byte-identical (16,294
bytes) at every commit. `mypy` (CI list, 147 files) clean. `bandit -r src uadas_core -q --skip
B101,B107,B608` → exit 0.

**Collected-count refresh (was stale here since 1.2/1.8):** `pytest -m "not uia_integration"
--collect-only` = **1512 selected / 1515 collected** (3 deselected = the `uia_integration`
tests) as of the review-fixups commit. The R0.1 "1484 / 1487" and post-1.1 "1485 / 1488" figures
earlier in this file were never updated for 1.2's +31, 1.8's +7, or 1.3's +7; the
**passed / skipped** chain (`1413 → 1420`) is the live A9 signal, not the collected line.

**Post-1.4 (typed generic `DependencyContainer.resolve()` — commits `49a539d` `85130d7`
`a0442e0`):** typing-only, **zero test-count delta** — suite stays **1420 passed / 92 skipped
/ 0 failed**. `mypy src/ui/main_window.py` 31 → 2; CI mypy list 147 → 148 files (added
`src/app.py`); screenshot byte-identical.

**Post-1.6 (persistence layer — commits `b6e22f4`…`45500ae`):** additive greenfield
`uadas_core/persistence/` + two additive `workspace_service.py` items (`DashboardTile.tile_id`,
`WorkspaceService.load_snapshot`) + a `bootstrap()` registration line + the `ProjectController`
save/open wiring. Suite **1420 → 1438 passed / 92 skipped / 0 failed** (inv-1
`test_worker_runner` 10; inv-2 **1428 passed, 92 skipped, 3 deselected, 0 failed**, process
exit `139` — the usual post-clean-result Windows/Qt teardown SIGSEGV, CI-green-equivalent under
`Max(exit1, exit2)`). **The +18 breakdown:** +8 C-3 (`tests/persistence/test_persistence_service.py`),
+6 `tests/services/test_workspace_service.py` (1 `tile_id` + 5 `load_snapshot`), +2
`tests/ui/controllers/test_project_controller.py` (rewritten 3 → 5 — the milestone-19
`_warn_about_skipped_datasets` behaviour is removed in 1.6, contract §9), +2 structural from
`test_import_layering` parametrising over the 2 new `uadas_core/persistence/*.py` modules (same
mechanism as 1.1/1.2). Any *other* delta would be a regression. `screenshot_app_state.py`
byte-identical (16,294 bytes) — persistence adds no visible UI. `mypy` CI list (+
`uadas_core/persistence`) → **Success** (150 source files). `bandit -r src uadas_core -q --skip
B101,B107,B608` → exit 0 (B608 off — the `security-reviewer` ×2 end-of-range pass is the SQL
gate; both APPROVE). `lint-imports` → 1 kept / 0 broken (`uadas_core/persistence` is Qt-free).
No `test_module_size` delta (that guard is `src/ui/`-only).

**Post-1.7 (provenance DAG & Recipe — commits `8d7d63e`…`5208d2a` [implementer], merge
`c1a989a`, review-fix `a3bed35`; + doc commits `e887136` `68bdecc`):** additive greenfield
`uadas_core/provenance/` (`analysis_logs_to_dag` / `analysis_logs_to_recipe` /
`recipe_to_analysis_logs`) + `Explanation.from_dict` + `AnalysisOrchestratorService.get_all_logs`
+ an ISO-8601 timestamp check on `AnalysisLogEntry.from_dict` (spec §R0.4 CHANGE 5). The one
existing-consumer touch: `PipelineController.restore_logs_for_project` now warns-and-skips a
recorded log whose timestamp fails that check (a hand-edited / pre-1.7 project file still
opens — end-of-range review B2). Suite **1438 → 1523 passed / 92 skipped / 0 failed** (inv-1
`test_worker_runner` 10; inv-2 **1513 passed, 92 skipped, 3 deselected, 0 failed**, process exit
`139` — the usual post-clean Windows/Qt teardown SIGSEGV, CI-green-equivalent under
`Max(exit1, exit2)`). **The +85 breakdown:** +27 `tests/provenance/test_dag.py`, +48
`tests/provenance/test_recipe.py` (incl. +8 in review-fix `a3bed35` — the non-linear-log-set
guards + `RecipeStep.from_dict` hardening), +3 `tests/analysis/test_explanation.py`, +3
`tests/services/test_analysis_orchestrator_service.py` (timestamp ×2 + `get_all_logs`), +1
`tests/ui/controllers/test_pipeline_controller.py` (the B2 regression test), +3 structural from
`test_import_layering` over the 3 new `uadas_core/provenance/*.py` modules (same mechanism as
1.1/1.2/1.6). Any *other* delta would be a regression. `screenshot_app_state.py` byte-identical
(16,294 bytes) — provenance adds no visible UI. `mypy` CI list (+ `uadas_core/provenance`) →
**Success** (150 → **153** source files). `bandit -r uadas_core/provenance -q --skip
B101,B107,B608` → exit 0 (pure transform, no SQL / no filesystem — no directed
`security-reviewer` pass required, unlike 1.6). `lint-imports` → **2 kept / 0 broken** (the new
machine-checked `provenance-is-a-leaf` contract: `core`/`analysis`/`services`/`persistence`/`jobs`
must not import `uadas_core.provenance`). No `test_module_size` delta.

---

## Environment

- Python **3.13.14**, `.venv` at repo root
- `PySide6` present (desktop shell intact)
- Windows 11; `QT_QPA_PLATFORM=offscreen`
- Tooling pins (from `requirements.txt`): `black==26.5.1`, `isort==8.0.1`, `mypy==2.1.0`,
  `ruff==0.16.3`, `bandit==1.9.4`, `import-linter==2.15` (added at R0.5)
