# Phase 1 — whole-branch diagnosis (before the DoD + PR to main)

**Purpose:** pin-point and dig out any error / bug / gap accumulated across sub-steps 1.1–1.7
on `phase-1/extract-uadas-core` before the Definition-of-Done and the single PR to `main`.
Read-only specialist sweep → triage → fix → re-verify. Fires **after 1.7 lands and
`graphify update .` has run** (so the graph carries `uadas_core/provenance/`).

**Surface:** `32c45ec..phase-1/extract-uadas-core` — 53 commits + 1.7's ~8. Merge-base
`32c45ec`. Sub-step SHA ranges: see `.superpowers/sdd/phase-1/progress.md`.

## Sub-step boundaries (for scoping each agent)

| Sub-step | What changed | Highest-risk facet |
|---|---|---|
| 1.1 carve-out | ~112 `.py` moved `src/` → `uadas_core/`; import rewrites | a missed `from src.` import; a test that stopped covering moved code |
| 1.5 lift renderers | `src/ui/results/` → `uadas_core/results/` | same class of import/coverage gap |
| 1.2 JobRunner | new `uadas_core/jobs/` adapter; `WorkerSignals`/`BaseWorker` frozen | silent-failure in the adapter; a caching regression |
| 1.8 security ×4 | iteration-cap, zip-slip, injected-secrets, SQL-capability-refused | a fix that regressed or is bypassable |
| 1.3 de-globalize | 3 `_register_builtins()` moved import→`bootstrap()`; `_CHART_BUILDERS`/`_CHART_REGISTRY` → live fns | collection-time side-effects; a registry that double-registers |
| 1.4 typed resolve() | `resolve()` `@overload` pair; `src/app.py` drops 3 casts | overload-overlap; a resolve() call that now mis-types |
| 1.6 persistence | new `uadas_core/persistence/`; SQLite+Parquet; `DashboardTile.tile_id`; `load_snapshot`; `_warn_about_skipped_datasets` removed | SQL injection (B608 CI-OFF); path-traversal on `dataset_id`; atomicity; a dangling-ref that now raises |
| 1.7 provenance | new `uadas_core/provenance/`; `Explanation.from_dict`; `get_all_logs` | silent-failure in "synthesize `partial`, never raise"; `_creation_order` loop; `from_dict` tolerance vs data loss |

## Specialist batch — non-author, read-only (RESOURCE_ORCHESTRATION §1.4)

Every prompt: carries the sub-step table above + verified `file:line` anchors inline; ends with
*"report back caveman-compressed (`caveman` full): one line per finding — `file:line` · claim ·
fix. Group by sub-step. No prose."* (§1.7).

**Wave 1 (highest yield — fire together):**
1. `ecc:silent-failure-hunter` — swallowed errors / bad fallbacks / missing propagation across
   `uadas_core/jobs/`, `uadas_core/persistence/`, `uadas_core/provenance/`, and the 1.3 registry
   moves. The single highest-yield facet for hidden bugs.
2. `ecc:architect` (opus) — boundary integrity of `uadas_core/` as a Qt-free core: dependency
   directions (`lint-imports` passes, but does anything import *upward*?), `Base*` pattern
   adherence, the `bootstrap()` sequence with all of 1.2/1.3/1.6/1.7's registrations, the three
   separate cycle-checkers (1.6 ×2 + 1.7) staying consistent.
3. `security-reviewer` (repo) — 1.8's four fixes still intact + not bypassable; 1.6 SQL still
   `?`-parameterized end to end (B608 is CI-OFF — this pass is the only gate); `dataset_id`
   uuid4-validated before every path-join on **both** save and load; readers (moved in 1.1/1.5)
   — no path-traversal regression.
4. `test-engineer` — behaviour coverage vs line coverage: the A9 baseline deltas
   (`plans/phase-1-baseline.md`) — is any added test a tautology? are the 1.6 structural-failure
   paths and the 1.7 C-2 multi-log case actually asserted, not just imported?

**Wave 2 (after Wave 1 triage, or parallel if rate limits allow):**
5. `ecc:python-reviewer` — idiom / type-hints / PEP8 / obvious perf over the branch diff.
6. `ecc:type-design-analyzer` — 1.4 `resolve()` overloads + the new value dataclasses
   (`SaveReport`, `WorkspaceSnapshot`, `DashboardTile`, `DatasetMeta`, `Dag`, `Recipe`,
   `RecipeStep`) — invariants expressed in the type, or left to callers?
7. `code-reviewer` (repo, haiku) — general quality / regression over `32c45ec..HEAD`.

Drop `comment-analyzer` / `performance-analyzer` / `a11y-reviewer` — low yield here (no
data-volume or UI change; comment rot is not "a bug").

## Triage rubric

- **CRITICAL / HIGH** (wrong result, crash, security bypass, data loss) → fix on the branch now,
  TDD, before the DoD. Re-run the affected sub-step's tests + `pytest tests/<area>/`.
- **MEDIUM** (silent-failure that masks a real error, a missing structural check, a type hole) →
  fix if < ~30 min and localized; else log in §findings with a Phase-2 owner.
- **LOW** (doc / idiom / naming) → batch into one `chore(phase-1): diagnosis nits` commit, or
  defer.
- Every accepted finding gets a one-line §findings entry (id, sub-step, severity, verdict,
  fixing commit).

## Then

DoD (`plans/phase-1-derisking-and-readiness.md` Part E) → one PR `phase-1/extract-uadas-core →
main` (whole-branch review by sub-step commit range; A7 → ~60 commits ride; squash is an
explicit A7 decision) → flip `DCO_ENFORCING` to `"1"` at some Phase-1 commit.

## §findings — Wave 1 (2026-09-10, over `32c45ec..cde42aa`)

**Agents:** `ecc:silent-failure-hunter` (1 HIGH / 6 MED / 6 LOW) · `security-reviewer`
(APPROVE-WITH-CHANGES — **all four 1.8 fixes verified INTACT + bypass-resistant**; 1.6 SQL fully
`?`-parameterized + uuid4-validated both paths; readers XXE/zip-slip clean) · `ecc:architect`
(SOUND-WITH-NOTES — no CRITICAL/HIGH) · `test-engineer` (GAPS-FOUND — no production bugs).

**Cross-cutting theme:** `except` clauses across 1.6/1.7 too narrow for the failure modes the
surrounding graceful-degradation path promises to handle.

### Fixed on the branch — commit `7def88b` `fix(phase-1): whole-branch diagnosis sweep`

| # | Sev | Where | What | Test |
|---|---|---|---|---|
| F1 | HIGH | `persistence_service._rebuild_visualization` | `except ServiceError` only → a `KeyError`/`ValueError`/plugin exception from `build()` aborted the whole `load_workspace`. Now `except Exception` → `_RebuildFailed` (contract §2.2). | `test_a_non_serviceerror_build_failure_is_a_rebuild_failure_not_a_load_abort` |
| F2 | MED | `AnalysisLogEntry.from_dict` / `AnalysisLog.from_dict` | raised bare `KeyError`/`ValueError` past `restore_logs_for_project`'s `except ServiceError` (1.7 B2). Every malformed-payload case → `ServiceError`, uniform w/ `RecipeStep.from_dict`. | `test_entry_from_dict_rejects_an_unknown_stage` / `…_missing_required_key` / `test_log_from_dict_rejects_a_missing_dataset_id` |
| F3 | MED | `jobs/ThreadPoolExecutorJobRunner._wrapped` | `fn` raises + `on_error is None` → exception dropped into the discarded Future, no trace. Now `_logger.exception`. Callback that itself raises → logged, not swallowed. | `test_a_job_that_fails_with_no_on_error_callback_is_logged_not_silent` |
| F4 | MED→LOW | `jobs.set_default_job_runner` | re-install (2nd `bootstrap()`, or a test swap) leaked the previous pool's idle threads → tears the old runner down if it has `shutdown()`. | (covered by the contract fixture teardown) |
| F5 | MED-HIGH (test gap) | `persistence_service._gc_orphan_parquet` | zero test — over-delete = silent data loss. | `test_gc_orphan_parquet_deletes_a_stray_frame_but_keeps_live_ones` |
| F6 | MED (test gap) | 1.6 structural aborts | no test for corrupt / missing `workspace.db`, missing `.parquet`. | `test_load_rejects_a_corrupt_workspace_db` / `…_bare_directory_with_no_workspace_db` / `…_missing_parquet_frame` |
| F7 | MED (test gap) | `provenance/dag.Dag.roots()` | new public method, zero direct test. | `test_roots_is_the_single_chain_start_for_a_two_log_set` / `…_excludes_a_derived_node_even_when_its_meta_lost_parent_dataset_id` |
| F8 | LOW | `persistence_service` `json.loads(read_warnings)` | bare `JSONDecodeError` on a hand-edited `.db` → `ServiceError`. | — |
| F9 | LOW | `archive_reader._is_safe_archive_member` | a dropped zip-slip/symlink member was silent → `_logger.warning`. | — |
| F10 | LOW | `pipeline_controller.restore_logs_for_project` | now logs a `skipped` count. | — |
| F11 | LOW (security) | `sqlite_reader` `SELECT * FROM {table_name}` | `table_name` (already `sqlite_master`-validated, read-only conn — **not exploitable**) now quoted as an identifier. | — |
| F12 | LOW | `.importlinter` `provenance-is-a-leaf` | `source_modules` listed 5 of 14 subpackages → all 14. Still `2 kept / 0 broken`. | — |
| F13 | LOW | `workspace_service.load_snapshot` docstring | false "datasets must be topologically ordered" precondition removed. | — |

### Fixed — doc commit `_(this commit)_`

| # | Where | What |
|---|---|---|
| F14 | `CLAUDE.md` ×2, `docs/ARCHITECTURE.md` | `_REGISTERED_READERS` → `_BUILTIN_READERS` (verified `reader_registry.py:47`) — a symbol name that does not exist. |
| F15 | `CLAUDE.md` workspace-model rule | added the one deliberate save-boundary exception: `save_workspace` drops a visualization whose dataset was closed (`SaveReport.skipped_visualization_ids`, 1.6 §2.4) — so it doesn't read as a non-cascading-rule violation. |

### Deferred — dispositioned, tracked for the Phase-1 DoD / Phase 2 / Phase 3

| # | Sev | Item | Owner |
|---|---|---|---|
| D1 | MED (arch) | `Dataset` / `Visualization` / `Dashboard` value types live in `services/workspace_service.py` → `services` ↔ `ai` package cycle. Extract to a leaf `uadas_core/models/`. Multi-file move, not additive. | **Phase 2** (first refactor) |
| D2 | MED (arch) | `bootstrap.py` (composition root) sits in `core/`, blocking an import-linter `layers` contract. Move to `uadas_core/bootstrap.py` top-level. | **Phase 2** (after D1) |
| D3 | MED | `bootstrap()` is not idempotent — a 2nd call in one process silently degrades every plugin to `loaded_successfully=False` (instance-local unregister guard vs process-global registries). Needs a registry `reset()`. | **Phase 3** (multi-request re-entrancy) |
| D4 | MED | `save_workspace` frame writes + orphan GC run **before** the atomic `.db` `os.replace`, with no rollback — a crash mid-save can leave new frames + old `.db`. Stage frames to `.parquet.tmp`, GC after the swap. | **Phase 2** (1.6 follow-up) |
| D5 | MED | ~8 Qt-free modules stranded in `src/ui/` (`theme/plotly_theme.py` — most load-bearing, themes the `go.Figure`s `uadas_core/visualization` returns; `theme/tokens.py`, `theme/contrast.py`, `a11y/contrast_manifest.py`, `help/manual_index.py`, `help/manual_renderer.py`, `widgets/data_table/column_formatters.py`, `workbench/stage_registry.py`). Lift into `uadas_core/`. | **1.9 / early Phase 2** |
| D6 | MED | `src/workers/base_worker.py`: `_on_error` logs at WARNING without `formatted_traceback`; `done.wait()` has no timeout (a contract-violating JobRunner hangs the pool thread). A10 froze this file in 1.2 — not touched now. | **Phase 2** (when `BaseWorker` is deleted / rewritten) |
| D7 | LOW | 2 import-time `_register_builtins()` the 1.3 plan named but did not move: `src/ui/actions/builtin_actions.py`, `src/ui/workbench/stage_registry.py` (the `action_registry` §4 row). | note in the PR description |
| D8 | LOW | ~112 stale `src/<pkg>/` path refs across 10 `.claude/` skill+agent files (`agents/{architect,debugger,implementer,performance-analyzer,security-reviewer}`, `skills/{add-extension,dataviz-development,model-orchestration,project-architecture,pyside6-development}`) — pre-flight A6 was incomplete. Misroutes future agent runs; blocks nothing. | **dedicated de-stale pass** (re-run A6 properly) before/with the PR |
| D9 | LOW | `provenance/` has zero non-test callers — Phase-5 substrate, intentionally uncalled. | state in the PR description so it isn't flagged as dead code |
| D10 | LOW | `Recipe.from_dict` `steps`/`version` strictness; `fromisoformat` accepts naive / date-only. | **Phase 3** (Recipe disk persistence + versioning) |
| D11 | LOW | `caa5d0b` "caching regression" test is single-threaded — doesn't pin the race it was filed for; the `base_worker` sync-`run()`-raise guard is "verified by inspection". | add threaded tests — **Phase 2 / opportunistic** |
| D12 | LOW | `get_all_logs()` / `get_log()` return live `AnalysisLog` refs (a caller could mutate orchestrator state). No current mutator; consistent with `get_log`. | note; revisit if a mutating consumer appears |

**Verification after `7def88b`:** targeted suites 202 passed; `lint-imports` 2 kept / 0 broken;
`mypy` clean; full suite — _see `plans/phase-1-baseline.md` Post-diagnosis entry_.
