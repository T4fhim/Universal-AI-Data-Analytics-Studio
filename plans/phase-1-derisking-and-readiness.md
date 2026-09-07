# Phase 1 — De-Risking & Readiness Plan

**Status:** accepted 2026-09-07 · scope + order decisions locked (below) · execution NOT
started — begins only on an explicit "get to work" from the user, after the Readiness Gate
(Part B) passes.

**Decisions locked 2026-09-07 (user):**

1. **Scope = Option A, carve-out.** Only the Qt-free packages move to `uadas_core/`. `src/ui/`,
   the Qt entry path in `src/core/app.py`, and `main.py`'s desktop path stay as a shrinking
   shell that imports *from* `uadas_core`. **Phase 2 deletes `src/ui/` wholesale** — the shell
   is disposable and is not renamed. `architect`'s only remaining R0.3 job is to confirm the
   Qt-free package list is complete against a fresh `grep -rl PySide6 src`.
2. **Execution order = Part D** (`1.0 → 1.1 → 1.5 → 1.2 → 1.8 → 1.3 → 1.4 → 1.6 → 1.7`) is the
   order of record. `architect` may still flag a hard dependency error at R0.3, but the order
   is not re-litigated otherwise.
3. This plan file is committed to the repo alongside `web-transition-glass-box-studio.md`.

**What this is.** For every risk flagged against Phase 1 of
[web-transition-glass-box-studio.md](web-transition-glass-box-studio.md#phase-1--extract-a-qt-free-headless-installable-core),
this document names the concrete controls that reduce it to near-zero and the command that
proves the control worked. It also defines the **Readiness Gate** — the checks that must pass
*before the first line of Phase 1 code* — and the abort criteria for each step.

**What this is NOT.** The bite-sized, TDD, task-by-task implementation plan. Each Phase 1
sub-step (1.1 … 1.8) gets its own such plan, authored with `superpowers:writing-plans` and
reviewed, *after* this readiness plan is accepted and *immediately before* that sub-step runs —
so it is written against the tree as it actually is at that moment, not as forecast now.

**Ground-truth date.** All counts and line numbers below were re-checked against the working
tree on 2026-09-07. Where they differ from the transition-plan document, the transition-plan
document is stale and this file's number governs (per observation-log 0014 / 0016 — never carry
a load-bearing count forward unverified).

| Transition-plan says | Verified 2026-09-07 |
|---|---|
| "56 non-UI test files" | **45** `test_*.py` outside `tests/ui/` (of 120 total) |
| zip-slip "at `archive_reader.py:168`" | the extract logic is at `archive_reader.py:129-136` (`tempfile.mkdtemp()` + `extracted_dir / inner_name`) |
| `assistant_service.py:271` `while True:` | ✅ still there, file is 471 lines |
| `provider_rotation.py:170` `os.environ.get(...)` | ✅ still there, file is 178 lines |

---

## Part A — Standing controls (bind to every Phase 1 step)

These are not optional per-step choices; they are the operating rules for the whole phase.

| # | Control | Enforced by |
|---|---|---|
| A1 | **`main` stays releasable.** All Phase 1 work lands on branch `phase-1/extract-uadas-core`. Nothing merges to `main` until the Phase 1 Definition of Done (Part E) passes in a CI run. If Phase 1 is abandoned, `main` is untouched. | branch discipline; no direct commits to `main` |
| A2 | **One sub-PR per step (1.1 … 1.8), each independently green before the next starts.** A step is not "done" until its own CI run is green AND its reviewer has signed off. Steps do not overlap. | GitHub PR per step; CI required |
| A3 | **Writer ≠ verifier.** `implementer` (or a scripted codemod + the orchestrator for pure-mechanical steps) writes. A *fresh* agent that did not write it verifies: `code-reviewer` for logic, `security-reviewer` for 1.6 / 1.8, `architect` for boundary/ordering questions in 1.2 / 1.3 / 1.4 / 1.7. No self-review, ever. | the anti-hallucination regime, transition-plan §"Anti-hallucination regime" rule 4 |
| A4 | **Every step ends with a named verification command and its pasted output.** "It passes" without the command and its result is not accepted. A code read is never evidence. | transition-plan regime rules 1–2 |
| A5 | **Subagents' negative claims are spot-checked.** "pre-existing", "unrelated", "already handled" get verified against the actual base commit before being believed. | regime rule 3; observation-log 0006 |
| A6 | **Assumptions are written as assumptions.** Every sub-step plan carries an `## Unverified` section. Nothing in it is treated as fact. | regime rule 5 |
| A7 | **No history rewrite once pushed.** No `git rebase`/`--force` on `phase-1/extract-uadas-core` after it is shared. Every commit is a plain, `git revert`-able commit. Fixups are new commits. | branch discipline |
| A8 | **The import-linter contract is live from step 1.1's first commit** and runs in the CI `lint` job on every subsequent commit — so any Qt (or, later, Django) import creeping back into `uadas_core` during 1.2–1.8 is a red CI check, not a discovery months later. | `.importlinter` + `lint-imports` in `ci.yml` |
| A9 | **Golden baseline is the pass criterion, not "green".** After 1.1 the full suite must reproduce the *exact* pre-Phase-1 pass / skip / xfail counts and collected-test count (Part B, R0.1). A delta of even one test = something was lost or broken by the move. | recorded baseline file |
| A10 | **`code/config` changes only — no behavior changes — in 1.1, 1.2, 1.3, 1.5.** Those steps are refactors: same inputs → same outputs. Behavior changes are confined to 1.6 (new persistence), 1.7 (new DAG shape), 1.8 (4 named security fixes). This keeps the existing suite a valid safety net for the refactor steps. | reviewer checks diff intent |

---

## Part B — Readiness Gate (must pass before ANY Phase 1 code)

Run in order. Each produces an artifact committed to the repo so the baseline is not "in
someone's memory".

### R0.1 — Capture the golden baseline

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
# exact counts, mirroring CI's two-invocation split:
python scripts/run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q --tb=no | Tee-Object baseline-1.txt
python scripts/run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py --tb=no | Tee-Object baseline-2.txt
python -m pytest --collect-only -q -m "not uia_integration" | Select-Object -Last 1   # collected count
python scripts/screenshot_app_state.py --output baseline-app.png
```

**Deliverable:** `plans/phase-1-baseline.md` containing the two suite summary lines
(`N passed, M skipped, K xfailed …`), the collected-test count, the suite wall-clock, the
current `main` SHA, and `baseline-app.png` checked in beside it. This file is what A9 compares
against.

### R0.2 — Confirm `main` is green (done)

`main` = `6d4a07f`; GitHub Actions `test` / `lint` / `uia_integration` all `success`
(verified 2026-09-06 via the API). Nothing to do — recorded here for completeness.

### R0.3 — Confirm the carve-out package list (1.0)

**The scope decision is made (header): Option A, carve-out.** `git mv` only the Qt-free
packages (`core readers cleaning analysis forecasting visualization ai reports database
plugins workers engine` + the lifted `results/`) into `uadas_core/`. `src/ui/`,
`src/core/app.py`'s Qt entry path, and `main.py`'s desktop path stay in place as a shrinking
shell that imports *from* `uadas_core`; **Phase 2 deletes `src/ui/` wholesale** — no value in
renaming ~100 files about to be deleted. This makes step 1.1 a **~115-file** move instead of
**~360** and shrinks the blast radius of every codemod category in Part C.

`architect`'s remaining job here — the one open question — is narrow and produces a one-page
note reviewed by `code-reviewer`:

- **Is the Qt-free package list above exhaustive and correct?** Confirm against a fresh
  `grep -rl "PySide6\|PyQt" src` — every package *not* in that grep's output goes to
  `uadas_core/`; every package that *is* stays in the shell. Flag any package that imports Qt
  only transitively (e.g. through `src.core`) and would break the import-linter contract if
  moved.
- **Any hard dependency-order error in Part D?** If none, Part D stands as written.

### R0.4 — Design docs for the two new subsystems (1.6, 1.7)

`architect` / `planner` produce, and a reviewer accepts, **before any 1.6 / 1.7 code**:

- `plans/phase-1-6-persistence-contract.md` — the `Dataset` → Parquet + metadata-row schema;
  the `Visualization` → `{dataset_id, chart_type, chart_parameters}` record; the
  `Dashboard`/`DashboardTile` → relational mapping; the save/load round-trip contract
  **explicitly including derived datasets**. With an `## Unverified` section.
- `plans/phase-1-7-provenance-dag.md` — the DAG node/edge model keyed on dataset lineage;
  the portable **Recipe** format (DAG minus data); a worked example of reshaping a real
  `AnalysisLog.to_dict()` payload into the new shape and back. With an `## Unverified` section.

### R0.5 — Author the import-linter contract, prove it locally

```
pip install import-linter==<pin>
# .importlinter:  contract "uadas_core is Qt-free and framework-free"
#   forbidden modules: PySide6, PyQt5, PyQt6, django
lint-imports            # must exit 0 against the carved package boundary
```

**Deliverable:** `.importlinter` committed; `import-linter` pinned in `requirements.txt`;
a `lint-imports` step added to the CI `lint` job (in the *same* commit as the `git mv`, so
it never has a window of not running).

### R0.6 — Branch

```bash
git checkout main && git pull --ff-only
git checkout -b phase-1/extract-uadas-core
```

**Gate verdict:** Phase 1 execution begins only when R0.1, R0.3, R0.4, R0.5, R0.6 are all
complete and R0.4's design docs are reviewer-accepted.

---

## Part C — Per-risk resolution

### Risk A — the 1.1 rename is a large mechanical diff; a missed reference = an import error

| Aspect | Detail |
|---|---|
| **Why it's risky** | Every `from src.` / `import src.` across the codebase, plus config in `pyproject.toml`, `.github/workflows/ci.yml`, `.claude/hooks/*.ps1`, `main.py`, `scripts/*.py`, `tests/`, and `docs/**` must move together. A single missed one is an `ImportError` at collection time — loud, but it means the step failed. |
| **Control A-1** | **Carve-out (R0.3)** cuts the file count roughly in third and removes `src/ui/` — the largest package — from the transform entirely. |
| **Control A-2** | **Scripted, reproducible codemod, zero hand-editing.** Committed as `scripts/codemod_src_to_uadas_core.py` (or a documented `git mv` + `ruff`/`sed` sequence). Re-runnable. The PR diff = script output only. |
| **Control A-3** | **Every transform category enumerated up front with a grep count, and re-grepped to zero after.** Categories: (a) `^(from\|import)\s+src\.` in `**/*.py`; (b) `mock.patch("src.` / `patch('src.` / `patch("src.` in tests; (c) `"src\.` / `'src\.` string literals; (d) `pyproject.toml` `known_first_party`, `[tool.setuptools.packages.find] include`; (e) `ci.yml` — the `mypy` module list, `bandit -r src`, `black/isort/ruff … src/ tests/`; (f) `.claude/hooks/pre-commit-check.ps1` `bandit -r src`; (g) `docs/**/*.md`, `README.md`, `SPECIFICATION.md` path text; (h) `.bandit-baseline.json` (Windows `src\` paths — regenerate, or moot once 1.8 switches the hook to `--skip`); (i) `tests/ui/conftest.py`, `scripts/screenshot_app_state.py`. |
| **Control A-4** | **`git mv src <target>`** (not delete+add) so per-file history is preserved and reviewable. |
| **Control A-5** | **A10** — this step changes *not one line of logic*. Diff review is "did any non-import line change? if yes, reject." |
| **Verification** | ① `grep -rnE '\b(from\|import)\s+src\.\|["'"'"']src\.' --include='*.py' . ` → **0** (outside `.venv/` and git history). ② `python -m compileall uadas_core -q` → exit 0. ③ `python -c "import uadas_core"` → exit 0. ④ `pytest --collect-only -q -m "not uia_integration"` collected count **== R0.1 baseline**. ⑤ full suite pass/skip/xfail **== R0.1 baseline, exactly** (A9). ⑥ `black --check` / `isort --check-only` / `ruff check` / scoped `mypy` / `bandit --skip B101,B107,B608` → all green. ⑦ `python scripts/screenshot_app_state.py --output after.png` → runs; visual diff against `baseline-app.png` shows no change. ⑧ `lint-imports` → green. ⑨ CI on the pushed branch → every job green. |
| **Abort criterion** | Any of ④/⑤/⑦ deviates from baseline → `git reset --hard`, fix the codemod script, re-run. Nothing is built on 1.1 until it is baseline-identical, so a reset costs only the re-run. |

### Risk B — 1.3 touches the bootstrap sequence, whose order CLAUDE.md marks as fixed

| Aspect | Detail |
|---|---|
| **Why it's risky** | `bootstrap()` wires the container in a fixed order (`config` before `logger`, etc. — [docs/ARCHITECTURE.md#application-startup-sequence](../docs/ARCHITECTURE.md#application-startup-sequence)). Converting 4+ import-time module-level registries and `logger._configured` into container-resolved instances can reorder side effects. |
| **Control B-1** | **`architect` first writes the current startup dependency graph** — every import-time side effect and why its position is load-bearing — reviewed before any edit. |
| **Control B-2** | **One registry per commit, one suite run per commit.** Order: `reader_registry` (most isolated) → `cleaning.operation_registry` → `visualization.chart_registry` → `actions/action_registry` → `logger._configured` → the `PROJECT_ROOT`-anchored path constants. Never batched. Each is its own reviewable diff. |
| **Control B-3** | **Characterization test for startup, run before and after every B-2 commit:** a test that calls `bootstrap()` and asserts the fully-wired container resolves *every* registered service and that the registry contents match a recorded snapshot. Committed in the first B-2 commit. |
| **Control B-4** | **The `tool_registry._CHART_BUILDERS` import-time-snapshot bug gets a red test first:** register a chart *after* import, assert it appears in `tool_registry` — fails today — then fix, then green. TDD, not a blind edit. |
| **Control B-5** | **A10** — behavior-preserving. The app must boot and render identically (`screenshot_app_state.py` diff) after each B-2 commit. |
| **Verification** | Per B-2 commit: characterization test green + full suite == baseline + `screenshot_app_state.py` unchanged + `architect` confirms the documented order invariant still holds. Final: `bootstrap()` produces a container functionally identical to `main`'s, proven by the characterization test. |
| **Abort criterion** | A characterization-test failure or a screenshot diff after any single registry conversion → revert that one commit, re-scope with `architect`, retry. Because they are separate commits, one bad conversion never contaminates the others. |

### Risk C — 1.6 (persistence) and 1.7 (provenance DAG) are new subsystems, and Phase 5 rests on 1.7

| Aspect | Detail |
|---|---|
| **Why it's risky** | These are design, not refactor. A wrong persistence contract or DAG shape is cheap to change now and expensive after Phase 3/5 build on it. The current code has *no* persistence for DataFrames/visualizations/dashboards and *silently drops derived datasets* — so there is no existing behavior to preserve, and also no existing safety net for these paths. |
| **Control C-1** | **Design doc before code (R0.4), reviewer-accepted.** No implementer touches 1.6/1.7 until the schema and the round-trip contract are written down and signed off, each with an `## Unverified` section. |
| **Control C-2** | **1.7 is prototyped against real recorded logs before commitment.** Take actual `AnalysisLog.to_dict()` fixtures from the current suite, reshape into the DAG, reshape back, assert equality. If a real log can't round-trip, the shape is wrong — caught in the prototype, not in Phase 5. |
| **Control C-3** | **1.6 round-trip test is written first (TDD, red before green):** save `{dataset, a derived dataset, a visualization, a dashboard tile}` → load → assert full equality, *including the derived dataset the current code drops*. This test is the acceptance criterion. |
| **Control C-4** | **Both are strictly additive.** They add a serialization/DAG layer *alongside* existing structures; they do not modify `WorkspaceService`/`AnalysisOrchestratorService` behavior for existing callers. The existing suite stays valid throughout. |
| **Control C-5** | **`security-reviewer` on 1.6** — object-store keys and Parquet paths derived from user-controlled dataset names are a path-traversal / key-injection surface. Reviewed before merge. |
| **Control C-6** | **Scope fence (`lean-build`):** 1.6/1.7 build *only* what Phase 3 consumes. No speculative fields, no "might need it later". The design doc's scope section is the contract; anything beyond it is rejected in review. |
| **Verification** | 1.6: the C-3 round-trip test green, `security-reviewer` sign-off, full suite == baseline (additive → no regression). 1.7: the C-2 prototype round-trips every `AnalysisLog` fixture in the suite; the Recipe format serializes and re-loads; `architect` sign-off on the shape against the Phase 5 feature list (F1–F3, F10). |
| **Abort criterion** | C-2 prototype can't round-trip a real log, or C-3 can't be made to pass without touching existing behavior → stop, return to R0.4, redesign. Do not implement around a broken design. |

### Risk D — "writer ≠ verifier" (this is a control, stated for completeness)

Not a risk to mitigate — it *is* the mitigation, promoted to a standing rule (A3). Concretely
for Phase 1: the orchestrator dispatches an `implementer` per sub-step (or runs the mechanical
codemod itself for 1.1/1.5), then dispatches a **different** agent to review — `code-reviewer`
for 1.1–1.5, `security-reviewer` for 1.6 and 1.8, `architect` for the 1.2/1.3/1.4/1.7 design
questions. The reviewer gets the diff and the verification-command output, not a summary. A
step with no independent review pass is not merged.

### Per-step residual risks (lower, but named)

| Step | Residual risk | Control |
|---|---|---|
| **1.2** JobRunner | `src/ui/` call sites still consume `BaseWorker` until Phase 2 | Keep the `BaseWorker` public shape (`fn, *args, report_progress, **kwargs` + `progress_callback`) as a thin adapter over `JobRunner` so no call site changes in Phase 1; `architect` designs the protocol, `code-reviewer` checks the adapter preserves the contract; full suite == baseline. |
| **1.4** Session scope | multi-tenancy foundation — a wrong scope model is expensive once Django (Phase 3) builds on it | `architect` designs the `Session` scope + the generic `resolve(self, key: type[T]) -> T` signature *before* code; the ~29 mypy errors it clears are the mechanical proof it's wired correctly (`docs/MYPY_DEBT.md` regenerated and shrunk); no Django code exists yet to constrain it wrongly. |
| **1.5** lift renderers | a renderer secretly imports Qt | `lint-imports` (live since 1.1) fails the commit if `uadas_core/results/` imports `PySide6`; `result_card.py` + `explanation_panel.py` deliberately *stay* in `ui/`. |
| **1.8** security fixes | each is small and localized — the risk is an incomplete fix | Each of the 4 fixes gets its own red-then-green test (iteration-cap hit; a crafted zip entry escaping the temp dir is rejected; a provider resolves an injected key not `os.environ`; `execute_query` refuses without the capability flag). `security-reviewer` scopes the set first and verifies each after. |

---

## Part D — Risk-optimized execution order

The transition plan numbers the steps 1.1 → 1.8. For *risk*, this order is better and is
**locked as the order of record** (header decision 2; `architect` may still flag a hard
dependency error at R0.3, nothing else re-opens it):

1. **1.0** scope decision — `architect`, no code (R0.3).
2. **1.1** `git mv` + codemod + `.importlinter` + `lint-imports` in CI — must be
   baseline-identical (A9) before anything else. Everything imports from here.
3. **1.5** lift result renderers — pure `git mv` + import fix, lowest risk, done while the
   codemod tooling is warm and `lint-imports` is fresh.
4. **1.2** JobRunner — isolated protocol; `BaseWorker` adapter keeps call sites unchanged.
5. **1.8** the 4 security fixes — small, localized, each test-guarded; lands early so the
   server-critical fixes are in before the bigger subsystems.
6. **1.3** de-globalize registries — one per commit, after the imports are stable.
7. **1.4** Session scope — needs 1.3's registries to be instances first.
8. **1.6** persistence — design doc (R0.4) → C-3 test → implement.
9. **1.7** provenance DAG — design doc (R0.4) → C-2 prototype → implement; last, because
   Phase 5 depends on it and it benefits from 1.6's persistence being real.

Rationale for the deviation: 1.1 must be a hard, isolated checkpoint; the cheap mechanical
move (1.5) rides its tooling; the security fixes (1.8) are server-critical and shouldn't wait
behind the two new subsystems; the DI-shape changes (1.3 → 1.4) have a real dependency order;
the design-heavy subsystems (1.6, 1.7) go last when the ground under them is stable.

---

## Part E — Phase 1 Definition of Done

Merges to `main` only when, in a single CI run on `phase-1/extract-uadas-core`:

- [ ] In a **fresh virtualenv with `PySide6` uninstalled**, on **Linux**:
      `python -c "import uadas_core"` exits 0.
- [ ] The **45 non-UI test files** pass on that Linux venv.
- [ ] `lint-imports` is green in CI (no `PySide6` / `django` import anywhere in `uadas_core`).
- [ ] The full suite (Windows CI, PySide6 present) still reproduces the R0.1 golden baseline
      counts — the desktop shell still works while it exists.
- [ ] A dataset survives a save → load round trip **including a derived dataset** (the C-3
      test).
- [ ] A real `AnalysisLog` round-trips through the new DAG shape and back (the C-2 test).
- [ ] `docs/MYPY_DEBT.md` regenerated; the scoped `mypy` list in `ci.yml` updated for any
      newly-clean module; error count down (≈29 from 1.4 alone).
- [ ] Every sub-step (1.1–1.8) had an independent reviewer sign-off (A3).
- [ ] `docs/ARCHITECTURE.md` and `CLAUDE.md` updated to describe `uadas_core` + the shell
      split (the `milestone-doc-sync` skill).

---

## Unverified (carried into execution as assumptions, not facts)

- The R0.1 baseline suite counts are not yet captured — the "1371 passed" figure quoted in
  older docs is from CI logs, never reproduced here. R0.1 establishes the real number.
- Whether `scripts/screenshot_app_state.py` still boots cleanly after the carve-out is
  assumed, not tested — R0.1 captures the "before", 1.1 verification ⑦ tests the "after".
- The exact count of `from src.` references is not yet enumerated; Control A-3's grep does
  that at execution time.
- `import-linter`'s latest version and whether it needs `setup.cfg` vs `.importlinter` vs
  `pyproject.toml` config on this toolchain — resolved at R0.5.
- That the carve-out list of Qt-free packages is complete — the architect confirms against a
  fresh `grep -rl PySide6 src` at R0.3.
