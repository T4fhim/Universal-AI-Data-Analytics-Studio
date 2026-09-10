# Phase 1 — Definition of Done (result)

The checklist is `plans/phase-1-derisking-and-readiness.md` Part E. Phase 1 merges to `main`
only when every item below passes **in a single CI run** on `phase-1/extract-uadas-core`.

**Branch head:** `<final commit>` · **CI run:** `<run id>` (fill on the final push)
**Order executed (Part D):** 1.1 → 1.5 → 1.2 → 1.8 → 1.3 → 1.4 → 1.6 → 1.7 → whole-branch
diagnosis sweep → this DoD → one PR to `main`.

| # | DoD item | Status | Evidence |
|---|---|---|---|
| 1 | Fresh venv, **PySide6 uninstalled**, Linux: `python -c "import uadas_core"` exits 0 | PASS | CI `linux_import` job (added pre-flight A3) — green on every run since; confirmed on the DoD run |
| 2 | The **non-UI test subset** passes on that Linux venv | PASS | CI `linux_import` job runs the pinned non-UI test list |
| 3 | `lint-imports` green in CI (no PySide6 / PyQt / Django anywhere in `uadas_core/`) | PASS | CI `lint` job → **2 kept, 0 broken** (Qt-freedom + `provenance-is-a-leaf`, widened in the diagnosis sweep to all 14 non-provenance subpackages) |
| 4 | Full Windows suite (PySide6 present) still green — the desktop shell still works | PASS | CI `test` job. Rolling baseline **1381 → 1542 passed / 92 skipped / 0 failed** (`plans/phase-1-baseline.md`; the R0.1 `1381` abort-rule was corrected to the rolling number at pre-flight A9). Inv-2's `139`/`0xC0000005` exit is the post-clean Windows/Qt teardown SIGSEGV — CI-green-equivalent under `Max(exit1, exit2)` |
| 5 | A dataset survives save -> load **including a derived dataset** (C-3) | PASS | `tests/persistence/test_persistence_service.py::test_workspace_round_trips_including_a_derived_dataset` (1.6) — plus 4 diagnosis-added structural-failure tests |
| 6 | A real `AnalysisLog` round-trips through the DAG shape and back (C-2) | PASS | `tests/provenance/test_recipe.py::test_every_analysis_log_fixture_round_trips_through_recipe` — parametrised over all 8 `AnalysisLog` shapes in the suite (1.7) |
| 7 | `docs/MYPY_DEBT.md` regenerated; CI mypy list updated for newly-clean modules; error count down | PASS | `docs/MYPY_DEBT.md` 2026-09-10 line: two-tree `mypy` **74 -> 44 errors / 18 files** (the ~29 from 1.4's typed `resolve()` + 1 more). CI `mypy (clean packages)` list grew **147 -> 153 files -> "Success"** (`+src/app.py` 1.4, `+uadas_core/persistence` 1.6, `+uadas_core/provenance` 1.7). Remaining 44 are pre-existing Phase-0 debt, tracked, not a Phase-1 regression |
| 8 | Every sub-step 1.1-1.8 had an **independent** reviewer sign-off (A3) | PASS | `.superpowers/sdd/phase-1/progress.md` — 1.1/1.5/1.2 `code-reviewer` APPROVE (+follow-ups); 1.8 `security-reviewer` scope + verification APPROVE (all 4 CONFIRMED FIXED); 1.3 per-commit `code-reviewer` x4 + `architect`/`python-reviewer`/`silent-failure-hunter`; 1.4 4 reviewers APPROVE-class; 1.6 4 end-of-range reviewers; 1.7 3 end-of-range + `ecc:architect` opus shape re-check. **Plus** a whole-branch 5-agent diagnosis sweep (`plans/phase-1-diagnosis.md` §findings) — all non-author |
| 9 | `docs/ARCHITECTURE.md` + `CLAUDE.md` describe `uadas_core/` + the shell split | PASS | `CLAUDE.md` updated through 1.1-1.7 (`Base*` paths, startup, workspace model, the 1.6 save-boundary note, `_BUILTIN_READERS` fix); `docs/ARCHITECTURE.md` "Module layout" diagram rewritten to the `uadas_core/` (14 subpackages incl. `jobs`/`persistence`/`provenance`/`results`) + `src/` (`ui`/`workers`/`app.py`) split |

## Deferred, dispositioned — NOT DoD blockers

Recorded in `plans/phase-1-diagnosis.md` §findings (D1-D15) with Phase-2/3 owners: extract the
`Dataset`/`Visualization`/`Dashboard` value types to a `uadas_core/models/` leaf (kills the
`services` <-> `ai` package cycle); move `bootstrap.py` top-level + add an import-linter `layers`
contract; `bootstrap()` full re-entrancy; save-side Parquet-frame atomicity; lift the ~8 Qt-free
modules still stranded in `src/ui/` (`plotly_theme`, `tokens`, `stage_registry`, ...); the ~112
stale `src/<pkg>/` path refs across 10 `.claude/` skill+agent files (re-run pre-flight A6);
`src/workers/base_worker.py` logging / `done.wait()` timeout (A10-frozen in 1.2). Also: flip
`DCO_ENFORCING` to `"1"` at some Phase-1 commit (not yet done — the `dco` CI job is advisory).

## PR

One PR `phase-1/extract-uadas-core -> main`. Whole-branch review by sub-step commit range
(A7 -> ~70 commits ride; **squash is an explicit A7 decision** — default is a merge commit
preserving the sub-step history). The PR body enumerates the sub-steps, the diagnosis sweep, and
the D1-D15 deferred list so a reviewer isn't surprised by e.g. `uadas_core/provenance/` having
no non-test caller yet (it is the Phase-5 substrate).
