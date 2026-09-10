# Phase 2 — De-Risking & Readiness Plan

**Status:** 2026-09-10 · **Readiness Gate COMPLETE** — R2.1 (baseline), R2.3 (`ecc:code-explorer`
extraction inventory → `plans/phase-2-execution-playbook.md` §5a), R2.4 (`ecc:architect` opus
rulings → `plans/phase-2-structural-moves.md`, verdict **READY-WITH-CHANGES**, folded below),
R2.5 (CI-transformation design → playbook §5b), R2.6 (branch `phase-2/retire-desktop-ui` cut
from `main` @ `8ab95f6`) all done. Deliverables pending non-author `code-reviewer` sign-off,
then sub-step 2.1 begins.

**What Phase 2 is** (from
[web-transition-glass-box-studio.md](web-transition-glass-box-studio.md#phase-2--retire-the-desktop-ui)):
**retire the PySide6 desktop UI** — mine every reusable asset out of `src/ui/` first, then
delete `src/ui/`, `tests/ui/`, the Qt entry paths, `src/workers/`, the Qt-only scripts and
markers, and the Qt / never-imported dependencies. The Qt-free domain core (`uadas_core/`,
extracted in Phase 1) is untouched except for three structural moves it was waiting on (D1, D2,
D5 from the Phase 1 diagnosis).

**What this document is.** The Phase-1-style de-risking layer for Phase 2: for every risk, the
concrete control that reduces it to near-zero and the command that proves the control worked;
the **Readiness Gate** (checks that must pass before the first line of Phase 2 change); and the
abort criterion per sub-step. It is a sibling of the two documents authored with it —
`plans/phase-2-execution-playbook.md` (the loop, the agent per role, the per-step gate) and
`plans/phase-2-resource-plan.md` (the per-sub-step resource matrix).

**What this is NOT.** The bite-sized, TDD, task-by-task implementation plan. Each Phase 2
sub-step (2.1 … 2.8) gets its own such plan, authored with `superpowers:writing-plans` and
reviewed, *after* this readiness plan is accepted and *immediately before* that sub-step runs —
against the tree as it actually is at that moment.

**Ground-truth date.** All counts and paths below were re-checked against the working tree on
2026-09-10, on `main` at `4d61b93` (Phase 1 merged). Where they differ from
`web-transition-glass-box-studio.md` — which was written 2026-09-02, pre-carve-out, and cites
`src/…` paths for code that is now under `uadas_core/…` — **this file's number governs** (per
observation-log 0014 / 0016 and `docs/RESOURCE_ORCHESTRATION.md` §3; never carry a load-bearing
count forward unverified).

| `web-transition` plan says (2026-09-02, pre-Phase-1) | Verified 2026-09-10 (`main` @ `4d61b93`) |
|---|---|
| "`src/ui/` — 101 files, 48.6% of `src/`" | **`src/ui/` + `src/workers/` = 92 `.py` files** (Phase 1 left `src/` as `ui/` + `workers/` + `app.py`; everything else moved to `uadas_core/`) |
| "`tests/ui/` — 90 of 146 test files" | **76 `test_*.py` under `tests/ui/` of 130 total** = 58% of the suite retires with the desktop UI |
| extraction inventory cites `src/ui/theme/…`, `src/services/…`, `src/ai/…` | Phase-1-era paths: `src/services/*` and `src/ai/*` are now `uadas_core/services/*` / `uadas_core/ai/*` (already Qt-free, already safe). Only the `src/ui/…` rows are still in scope. R2.3 re-verifies every row against the current tree. |
| "Design tokens / plotly theme / contrast math / manual index / column formatters — port to web" | These are **already Qt-free modules still stranded in `src/ui/`** (Phase 1 diagnosis D5). Phase 2 *lifts them into `uadas_core/`* (sub-step 2.1) rather than re-porting — they are Python, not TS-to-be. |
| `.importlinter` — 1 forbidden contract | **2 contracts** (`forbidden` Qt/Django + `provenance-is-a-leaf`), both `KEPT`. Phase 2 adds a 3rd (`layers`). |

---

## Part A — Standing controls (bind to every Phase 2 sub-step)

Adapted from Phase 1 Part A. A1–A8 carry over almost unchanged; **A9 and A10 change shape for a
deletion phase**, and **A11 is new**.

| # | Control | Enforced by |
|---|---|---|
| A1 | **`main` stays releasable.** All Phase 2 work lands on branch `phase-2/retire-desktop-ui`. Nothing merges to `main` until the Phase 2 Definition of Done (Part E) passes in one CI run. If Phase 2 is abandoned, `main` is untouched — and `main` still has a working desktop app until the moment Phase 2 merges. | branch discipline; no direct commits to `main` |
| A2 | **One sub-step at a time, each independently green before the next starts.** No per-step GitHub sub-PRs (same amendment as Phase 1, `.superpowers/sdd/phase-1/progress.md`): each sub-step's commit range + its independent reviewer + verdict is recorded in `.superpowers/sdd/phase-2/progress.md`, and its own CI run must be green before the next sub-step begins (checked via `gh`). | SDD ledger; CI required |
| A3 | **Writer ≠ verifier.** `implementer` (or the orchestrator, for pure-mechanical `git mv` / `git rm` steps) writes; a *fresh* agent that did not write it verifies — `code-reviewer` for the lifts, `architect` for the `models/` boundary and the `layers` contract (2.2 / 2.3), `ecc:code-explorer` for the extraction-inventory completeness check (R2.3), **`ecc:refactor-cleaner` for dangling-reference sweep after each deletion commit (2.5)** — now in-scope, unlike Phase 1 where it was excluded as behaviour-adjacent. No self-review, ever. | transition-plan §"Anti-hallucination regime" rule 4; `docs/RESOURCE_ORCHESTRATION.md` §5 Phase map |
| A4 | **Every sub-step ends with a named verification command and its pasted output.** A `grep` returning zero, a suite summary line, a `lint-imports` result — not "it passes". A code read is never evidence. | regime rules 1–2 |
| A5 | **Subagents' negative claims are spot-checked.** "nothing imports this", "already lifted", "dead code, safe to delete" get verified against the actual tree (a fresh `graphify query` / `grep`) before being believed. | regime rule 3; observation-log 0006 |
| A6 | **Assumptions are written as assumptions.** Every sub-step plan carries an `## Unverified` section. | regime rule 5 |
| A7 | **No history rewrite once pushed.** No `git rebase` / `--force` on `phase-2/retire-desktop-ui` after it is shared. Every `git mv` / `git rm` is a plain, `git revert`-able commit. | branch discipline |
| A8 | **The import-linter contracts are live on every commit.** The 2 existing contracts must stay `KEPT` through every sub-step; sub-step 2.3 adds the 3rd (`layers`) in the same commit as the `bootstrap.py` move, so `uadas_core` layering is machine-checked from that point on. | `.importlinter` + `lint-imports` in `ci.yml` |
| **A9** | **The pass criterion is "the surviving suite is green and the delta is *exactly* the deleted test set".** Phase 2 deletes ~76 `tests/ui/` files by design, so "reproduce the exact pre-phase count" (Phase 1's A9) does not apply. Instead: R2.1 records the pre-Phase-2 baseline **and the explicit list of test files expected to disappear**. After 2.5, `collected(before) − collected(after)` must equal exactly the tests in those files — not one test more. A surviving non-UI test that starts failing, or a non-`tests/ui/` test file that vanishes, is an abort. | R2.1 baseline file + recorded deletion manifest |
| **A10** | **`git mv` + import-fix only — no logic changes — in 2.1, 2.2, 2.3.** Those three are behaviour-frozen moves (same discipline as Phase 1's 1.1 / 1.5): same inputs → same outputs, diff review is "did any non-import line change? if yes, reject". 2.4 (asset extraction to data files) adds no code. 2.5 (deletion), 2.6 (CI rework) and 2.7 (D4 atomicity follow-up) are the only sub-steps that change behaviour, each in a named, bounded way. **Collected-count caveat (2.1):** three `tests/ui/` policy meta-tests are parametrized over a **`src/ui/**` file glob** — `test_module_size::…line_budget`, `test_i18n_wrapped_strings::…label_or_title_calls`, and `test_import_layering::test_nothing_outside_ui_imports_ui` (the last globs `src/** + uadas_core/**`). When a module leaves `src/ui/` its case leaves those parametrizations (and, for the layering test, reappears under `uadas_core/…` — a skip→pass swap). So a behaviour-frozen 2.1 lift does **not** hold the exact `1542 / 92 / 0`; the real invariant is **0 failed, 0 errors, no *named* (non-glob-parametrized) test lost or newly skipped**, and the collected delta fully accounted for by those three globs. R2.1's `phase-2-baseline.md` records the per-sub-step expected count. `uadas_core/`-scoped counterparts of the size/i18n policies are a Phase 2.8 / Phase 3 consideration, not a 2.1 change. | reviewer checks diff intent + glob-delta arithmetic |
| **A11** | **After 2.5 there is no runnable application** until Phase 4 ships the SPA. Screenshot parity (`scripts/screenshot_app_state.py` vs `plans/baseline-app.png`) is **retired** at 2.5 — it is a Qt-offscreen artifact and its subject is being deleted. From 2.5 on, the verification floor is: `python -c "import uadas_core"` in a **PySide6-free** venv **on Linux**, the surviving suite green on Linux, `lint-imports` green (3 contracts). This capability gap (Phase 2 → Phase 4: headless core + tests, no UI) is deliberate and is called out in `web-transition-glass-box-studio.md` ("Port to parity first"). | Part E; the master plan's phase sequencing |

---

## Part B — Readiness Gate (must pass before ANY Phase 2 change)

Run in order. Each produces an artifact committed to the repo so the baseline is not "in
someone's memory".

### R2.1 — Capture the pre-Phase-2 baseline — ◑ PARTIAL 2026-09-10 (suite + gates captured; manifests + `phase-2-baseline.md` pending branch cut)

Baseline at `main` = `4d61b93` (Phase 1 merged). Mirrors Phase 1's R0.1.

**Captured 2026-09-10 (health-gate + baseline in one, on `main` @ `4d61b93`):**

- inv-1 `tests/ui/test_worker_runner.py`: **10 passed** on isolated re-run (0.13 s). The
  loaded two-invocation run flaked once on
  `test_a_raising_on_result_is_never_silently_lost` — the CLAUDE.md-documented real-QThreadPool
  timing flake ("must run FIRST"; 16.97 s under first-run import load vs 0.13 s isolated). Not
  a regression.
- inv-2 `tests/ -m "not uia_integration" --ignore=…/test_worker_runner.py`:
  **1532 passed · 92 skipped · 3 deselected · 0 failed** in 624 s (10:24). `run_tests_and_exit_cleanly.py` exit 0.
- **Rolling baseline total: 1542 passed / 92 skipped / 0 failed** — identical to the
  post-Phase-1-diagnosis figure in `plans/phase-1-baseline.md`.
- Static gates: `black --check` ✓ (379 files) · `isort --check-only` ✓ ·
  `lint-imports` ✓ **2 kept / 0 broken** · `bandit -r src uadas_core -q --skip B101,B107,B608`
  ✓ exit 0 · `mypy` CI clean-package list ✓ **"Success: no issues found in 153 source files"** ·
  `screenshot_app_state.py` ✓ **byte-identical** to `plans/baseline-app.png` (16 294 bytes).

**Still to do at R2.1 (after `git checkout -b phase-2/retire-desktop-ui`):** write
`plans/phase-2-baseline.md` (the two summary lines + collected count + wall-clock + SHA), and
commit the two deletion manifests.

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python scripts/run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q --tb=no
python scripts/run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py --tb=no
python -m pytest --collect-only -q -m "not uia_integration" | Select-Object -Last 1
python scripts/screenshot_app_state.py --output plans/baseline-app.png   # LAST screenshot before the app dies
git ls-files 'tests/ui/*test_*.py' > plans/phase-2-deletion-manifest-tests.txt   # the A9 expected-disappearance set
git ls-files 'src/ui/*' 'src/workers/*' 'src/app.py' > plans/phase-2-deletion-manifest-src.txt
```

**Deliverable:** `plans/phase-2-baseline.md` — the two suite summary lines, the collected-test
count, the suite wall-clock, the `main` SHA (`4d61b93`), the last `plans/baseline-app.png`, and
the two deletion manifests (`…-tests.txt`, `…-src.txt`) checked in beside it. This file is what
A9 compares against.

> _Numbers to be filled from the run finishing now — health-gate + baseline in one:
> static gates all green (`black` / `isort` / `lint-imports` 2-kept-0-broken / `bandit`
> `--skip B101,B107,B608` exit 0 / `mypy` CI list "Success: 153 files" / screenshot
> byte-identical to `plans/baseline-app.png`); `test_worker_runner.py` 10/10 on isolated
> re-run (one known real-QThreadPool flake in the loaded run — CLAUDE.md-documented);
> full suite `<N> passed / <M> skipped / 0 failed`._

### R2.2 — Confirm `main` is green (done)

`main` = `4d61b93`. The pre-merge PR-CI run `34447838928` was fully green (`test`, `lint`,
`linux_import`, `uia_integration`, `dco` all `pass`); `82f59e1` on top of the reviewed content
is doc-only. The merge is a merge commit whose second parent is `82f59e1`. Recorded for
completeness — nothing to do.

### R2.3 — Re-verify the extraction inventory against the current tree — ✅ DONE 2026-09-10 (`ecc:code-explorer`) → `plans/phase-2-execution-playbook.md` §5a

**Result:** lift-2.1 **10** modules (the 7 lift-safe D5 modules + `actions/{action_registry,
builtin_actions,action_context}` — the first two MUST lift because `tests/services/
test_guidance_service.py`, a *surviving* test, imports them) · extract-2.4 **5** · phase-4-note
**4** · already-safe/done **7** · delete-only ~78 `src/ui` + 2 `src/workers` + `main.py` +
`src/app.py` run-path + 90 `tests/ui`. Corrections: **`src/core/` no longer exists** (Phase 1
removed it — entry points are `main.py` + `src/app.py` only); the master table is **20 data
rows**, not 24; `src/ui/workbench/stage_registry.py` (a named D5 module) is **NOT lift-safe** —
it imports the Qt `StagePage` type — so it drops to delete-only + a phase-4-note.

_Original R2.3 scope (for reference):_ `web-transition-glass-box-studio.md`'s Phase 2 asset
table (**20 data rows**, lines 224-243), written 2026-09-02
against pre-carve-out `src/…` paths. `ecc:code-explorer` (non-author) produces the definitive
Phase 2 extraction checklist:

- Every asset row resolved against `main` @ `4d61b93` — `src/ui/…` paths that still exist,
  `src/services/…` / `src/ai/…` paths that are now `uadas_core/…` (already safe, drop from
  scope), anything already lifted in Phase 1 (e.g. `results/` renderers — 1.5).
- For each surviving `src/ui/…` row: is it **(a)** a Qt-free module → lift in 2.1, or **(b)**
  data embedded in a Qt file (copy strings / a `dict` / an SVG set) → extract to a committed
  data file in 2.4, or **(c)** a semantics note that transfers as documentation (e.g.
  `chart_bridge.js` newPlot→react) → capture in a Phase-4 hand-off note.
- `grep -rlnE "PySide6|PyQt" src --include=*.py` → the exact Qt-coupled file set. Every file
  **not** in that grep and **not** already under `uadas_core/` is a lift candidate (2.1);
  every file **in** it is deletion-only (2.5).
- Cross-check against Phase 1 diagnosis **D5** (the 8 named stranded modules) and **D7** (the 2
  import-time `_register_builtins()` the 1.3 plan named but did not move).

**Deliverable:** a `## Extraction checklist` section appended to
`plans/phase-2-execution-playbook.md` — one row per asset, disposition (lift 2.1 / extract 2.4 /
Phase-4 note / already-safe / already-done), current path, target path. 2.5 may not delete
`src/ui/` until every row is ticked and a reviewer confirms it.

### R2.4 — Architect rulings on the three structural moves — ✅ DONE 2026-09-10 (`ecc:architect` opus) → `plans/phase-2-structural-moves.md`

**Verdict: READY-WITH-CHANGES.** Four changes, all folded into this doc + `phase-2-structural-moves.md`:

1. **`Project` (`project_service.py:46`) joins the `models/` move.** Not in D1's scope, but
   `core/application_state.py:49` imports it from `services` under `TYPE_CHECKING`, and
   import-linter 2.15 counts `TYPE_CHECKING` edges — so without moving `Project`, `core` cannot
   be the bottom layer of contract 3. `models/` = `models/workspace.py` (`Dataset`,
   `Visualization`, `DashboardTile`, `Dashboard`) + `models/project.py` (`Project`) +
   `__init__.py` re-export. `_reject_parent_cycles` stays in `workspace_service.py`.
   `SaveReport`/`WorkspaceSnapshot`/`RecipeStep` stay put.
2. **The `services ↔ ai` cycle does NOT fully break** by moving value types (as Risk B
   predicted). The residual `assistant_service → workspace_service.WorkspaceService` edge is a
   bare constructor annotation; fix = **one documented `ignore_imports` line** in contract 3,
   plus a 2.7/Phase-3 follow-up to make it a `Protocol`. NOT a `TYPE_CHECKING` move (doesn't
   help — 2.15 counts them).
3. **Corrected `layers` stanza** (13 layers, `provenance` at the TOP, the flat sibling tier
   decomposed) — the exact text is in `plans/phase-2-structural-moves.md` Ruling 3.
4. **2.1 AND 2.2 must also extend contract 2's (`provenance-is-a-leaf`) hand-enumerated
   `source_modules` list** — a missing entry there is a silent enforcement gap, not a CI
   failure.

Part D order confirmed — no hard dependency error. `models/` keeps pandas/plotly
`TYPE_CHECKING`-only. `uadas_core/core/__init__.py:1` has a stale `# File: src/__init__.py`
header (fix in 2.3).

_Original R2.4 scope (for reference):_

One batched `architect` pass (repo `architect` for the note, `ecc:architect` opus for the
rulings — the §1.4 delegation rule: batch interacting rulings into one opus call), non-author:

1. **`uadas_core/models/` (D1).** Which value types move out of
   `uadas_core/services/workspace_service.py` — `Dataset` (L40), `Visualization` (L124),
   `DashboardTile` (L169), `Dashboard` (L191) — and their enums / helpers. Confirm the move
   actually breaks the `services` ↔ `ai` import cycle the diagnosis flagged (produce the cycle
   with `graphify path`). Rule on whether `models/` may depend on `pandas` (`Dataset.dataframe`
   is a `pd.DataFrame`) — expected yes, `pandas` is already a `uadas_core` dependency and not a
   layering violation. Rule on `SaveReport` / `WorkspaceSnapshot` / `RecipeStep` — do they move
   too or stay with their services.
2. **`bootstrap.py` relocation (D2).** `uadas_core/core/bootstrap.py` → `uadas_core/bootstrap.py`
   (top-level). Confirm nothing in `uadas_core/core/*` other than `bootstrap` imports it (it is
   the composition root — it should be a leaf consumer, imported only by entry points).
3. **The `layers` contract (contract 3).** The exact layer order for the `import-linter`
   `[importlinter:contract:3]` `type = layers` stanza — e.g.
   `models` < `core` < `{readers, cleaning, analysis, forecasting, visualization, ai, database,
   plugins, reports, results, jobs, persistence}` < `services` < `provenance` < `bootstrap`.
   Must be provable `KEPT` against the tree *as it will be after 2.2 + 2.3*, so it lands in
   2.3's commit, not before.
4. **Sub-step order.** Confirm Part D (below) has no hard dependency error.

**Deliverable:** `plans/phase-2-structural-moves.md` — the type-move list, the `bootstrap.py`
target, the `layers` stanza text, `graphify path` output showing the cycle, an `## Unverified`
section. Reviewed by repo `code-reviewer` before 2.1.

### R2.5 — The CI-transformation design — ✅ DONE 2026-09-10 → `plans/phase-2-execution-playbook.md` §5b

**Key finding:** the existing `linux_import` CI job *already* runs the exact surviving suite
(`pytest tests/ -q -m "not uia_integration" --ignore=tests/ui` → the 451 non-`tests/ui/`
tests). So 2.6 is **promote `linux_import` → `test`, delete the Windows `test` job +
`uia_integration` job + `run_tests_and_exit_cleanly.py` + `screenshot_app_state.py`**, add a
Risk-C `--collect-only` count assertion (band ≈ 451), and rewrite `pre-commit-check.ps1`'s
suite command. Full design + rollout (C-3 run-it-first, C-4 keep-old-1-commit) in playbook §5b.

_Original R2.5 scope (for reference):_ Phase 2 is where CI stops being Windows-Qt-shaped:

- **What the `test` job becomes:** `ubuntu-latest`, single `python -m pytest tests/ -q`
  invocation (no `QT_QPA_PLATFORM=offscreen`, no two-invocation split, no
  `scripts/run_tests_and_exit_cleanly.py` — its entire reason for existing, the Windows
  CPython/Qt `Py_Finalize()` access violation, is gone with Qt).
- **What is deleted:** `scripts/run_tests_and_exit_cleanly.py`, `scripts/screenshot_app_state.py`,
  the `uia_integration` job + marker, the `webengine` marker,
  `tests/ui/a11y/test_uia_integration.py`, `tests/ui/conftest.py` (the offscreen dance +
  never-torn-down `QApplication` + autouse modal-blocker), the `linux_import` job folds into
  the now-Linux `test` job (or stays as a fast PySide6-free smoke gate — decide here).
- **What stays:** `lint` (ruff / black / isort / bandit / `lint-imports`), `dco` (now
  `DCO_ENFORCING=1`, set this session), the OpenAPI-drift check is **not** added here (Phase 3).
- **`.claude/hooks/pre-commit-check.ps1`:** its two-stage pytest invocation is rewritten to the
  single Linux-shaped run; still `bandit -r … --skip B101,B107,B608`. (The hook stays
  PowerShell — this is still a Windows dev machine — but the suite command inside it changes.)

**Deliverable:** a `## CI transformation` section in `plans/phase-2-execution-playbook.md`, and
a matching update queued for `docs/RESOURCE_ORCHESTRATION.md` §2 (the CI + `0xC0000005` notes go
stale at 2.6).

### R2.6 — Branch — ✅ DONE 2026-09-10

`phase-2/retire-desktop-ui` cut from `main` @ `8ab95f6`. `plans/phase-2-baseline.md` +
`plans/phase-2-deletion-manifest-tests.txt` (76 `test_*.py` files) +
`plans/phase-2-deletion-manifest-src.txt` (95 files: `src/ui/**` + `src/workers/**` +
`src/app.py` + `src/__init__.py` + `main.py`) committed.

**Gate verdict:** ✅ R2.1, R2.3, R2.4, R2.5, R2.6 all complete. Non-author `code-reviewer`
sign-off on the R2.3/R2.4/R2.5 deliverables is the last item before sub-step 2.1.

---

## Part C — Per-risk resolution

### Risk A — deleting ~92 `src/` files + ~76 test files "feels like destroying work" and can hide a real dependency

| Aspect | Detail |
|---|---|
| **Why it's risky** | A file in `src/ui/` that is actually Qt-free and imported by `uadas_core/` or by a surviving test would break `import uadas_core` or the suite the moment it is `git rm`-ed. The Phase 1 diagnosis already found 8 such modules (D5) — there may be more the diagnosis did not enumerate. |
| **Control A-1** | **R2.3 — `ecc:code-explorer` produces the exhaustive lift-vs-delete partition** before any deletion, cross-checked against `grep -rlnE "PySide6|PyQt" src` and Phase 1 D5 / D7. |
| **Control A-2** | **Lift before delete, as separate sub-steps.** 2.1 (lift the Qt-free stranded modules) and 2.4 (extract embedded data) both land and go green *before* 2.5 deletes anything. 2.5's diff is pure `git rm` — no file both moves and dies in one commit. |
| **Control A-3** | **`graphify query "what imports src.ui.<x>"` before every deletion group**, and a `grep -rn "src\.ui\.<x>\|src/ui/<x>"` sweep re-run to zero after. `graphify update .` after each sub-step. |
| **Control A-4** | **`ecc:refactor-cleaner` after each 2.5 deletion commit** — catches dangling imports, now-unused helpers in surviving files, stale `pyproject.toml` / `ci.yml` / `.claude/` references. |
| **Control A-5** | **`git rm` (not filesystem delete) in one reviewable commit per logical group** (e.g. `src/ui/` tree; `tests/ui/` tree; `src/workers/` + `src/app.py` + `main.py` Qt path; the Qt scripts + markers; the QSS + deps). Per-file history preserved; every group `git revert`-able. |
| **Verification** | ① `grep -rnE "\bPySide6\b\|\bPyQt" --include=*.py .` → **0** outside `.venv/` and history. ② fresh venv, `pip uninstall PySide6`, `python -c "import uadas_core"` → exit 0, **on Linux**. ③ surviving suite green on Linux; `collected(before) − collected(after)` == exactly the R2.1 test-deletion manifest. ④ `lint-imports` → 3 contracts `KEPT`. ⑤ branch CI green. |
| **Abort criterion** | ② fails, or ③'s delta ≠ the manifest → `git revert` the offending deletion group, return to R2.3, re-partition. Because groups are separate commits, one bad deletion never contaminates the others. |

### Risk B — the `uadas_core/models/` extraction (D1) reorders imports and can mask or move a cycle

| Aspect | Detail |
|---|---|
| **Why it's risky** | `Dataset` / `Visualization` / `Dashboard` currently live *inside* `services/workspace_service.py`; ~everything imports them *from* there. Moving them to a new leaf package rewrites a large fan-in of imports and changes module-load order — the same class of risk as Phase 1's Risk B (bootstrap side-effect ordering). |
| **Control B-1** | **`architect` first proves the current cycle** with `graphify path "uadas_core.services.workspace_service" "uadas_core.ai.<x>"` and states which edge the move cuts (R2.4). No edit before the cycle is on paper. |
| **Control B-2** | **Behaviour-frozen (A10).** A re-export shim (`from uadas_core.models import *` left behind in `workspace_service.py`) is *not* used — it would leave the cycle intact. Callers are rewritten to `from uadas_core.models import Dataset` directly; the scripted import rewrite is the whole diff; one non-import line changing = reject. |
| **Control B-3** | **Characterization test for `bootstrap()`** (reuse Phase 1.3's if it survives the UI deletion, else a minimal `import uadas_core; bootstrap()` resolves-every-service test) — run before and after 2.2. |
| **Control B-4** | **`lint-imports` gains the `layers` contract in 2.3, immediately after** — so the very next commit machine-proves the cycle is gone and cannot silently return. |
| **Verification** | characterization test green + full suite == R2.1 baseline (2.2 is behaviour-frozen, pre-deletion, so the count is unchanged here) + `graphify` shows the cut edge gone + (after 2.3) `lint-imports` `layers` contract `KEPT`. |
| **R2.4 outcome** | The cycle does **not** fully break by moving value types — confirmed. Residual `assistant_service → workspace_service.WorkspaceService` edge is handled by **one documented `ignore_imports`** in contract 3 (+ a 2.7/Phase-3 `Protocol` follow-up). **`Project` also moves** to `models/project.py` (needed for `core` to bottom out). Full spec: `plans/phase-2-structural-moves.md`. |
| **Abort criterion** | `models/` + the one `ignore_imports` still can't make the `layers` contract `KEPT` (e.g. a second real `ai → services` runtime edge appears) → stop, return to R2.4, widen the partition. |

### Risk C — CI transformation (2.6) can go green while silently testing less

| Aspect | Detail |
|---|---|
| **Why it's risky** | Rewriting the `test` job from "Windows, offscreen, two-invocation, `run_tests_and_exit_cleanly.py`" to "Linux, single `pytest`" is exactly the shape of observation-log **0022** (a CI step that stopped running looked like config, not failure, and hid a red job for a whole phase). A typo in the new `pytest` invocation, or a marker filter that over-excludes, passes as "green". |
| **Control C-1** | **R2.5 design doc first** — the exact new invocation, written down and reviewer-accepted, before `ci.yml` is touched. |
| **Control C-2** | **Assert the collected count in CI.** The new `test` job runs `pytest --collect-only -q` and fails if the number is not within the expected post-deletion range recorded in `plans/phase-2-baseline.md`. A silently-shrinking suite becomes a red check. |
| **Control C-3** | **Run the new job on a throwaway commit first** — push a no-op commit with the reworked `ci.yml`, confirm via `gh run view` that the `test` job actually executed *N* tests (not 0, not "skipped"), then proceed. (observation 0022's lesson: check the step *ran*, not just that it's green.) |
| **Control C-4** | **Keep the old `test` job alongside the new one for one commit**, both required, then delete the old one in a follow-up commit once the new one has a green history. |
| **Verification** | `gh run view <id> --log` shows the Linux `test` job collected and ran the expected count; `lint` still green; `dco` green with `DCO_ENFORCING=1`; a deliberately-broken test on a scratch branch turns the new job red (proves it's actually asserting). |
| **Abort criterion** | the new job passes with a collected count outside the expected band, or C-3 shows it ran 0 tests → revert `ci.yml`, fix the invocation, re-run C-3. |

### Risk D — "writer ≠ verifier" (this is a control, stated for completeness)

Same as Phase 1 Risk D. For Phase 2 concretely: the orchestrator runs the mechanical
`git mv` / import-rewrite / `git rm` directly (2.1 / 2.2 / 2.3 / 2.5); a **different** agent
reviews each — `code-reviewer` for the lifts and deletions, `architect` for the `models/`
boundary and `layers` contract, `ecc:code-explorer` for inventory completeness,
`ecc:refactor-cleaner` for the post-deletion dangling-ref sweep. A sub-step with no independent
review pass is not merged.

### Per-sub-step residual risks (lower, but named)

| Sub-step | Residual risk | Control |
|---|---|---|
| **2.1** lift stranded modules | one of the 8 D5 modules imports Qt transitively (e.g. via a sibling `src/ui/` helper) and would break `lint-imports` if moved | `lint-imports` runs on the 2.1 commit; if it breaks, that module drops back to deletion-only and its `uadas_core/` consumers (if any) get an inline copy. `theme/plotly_theme.py` is the load-bearing one — it themes the `go.Figure`s `uadas_core/visualization` returns; confirm its imports are pure-stdlib/pandas first. |
| **2.2** `models/` extraction | a test does `mock.patch("uadas_core.services.workspace_service.Dataset")` and breaks when the symbol moves | Control A-3's grep sweep includes `mock.patch("…workspace_service\.(Dataset\|Visualization\|Dashboard)` — those patch targets move to `uadas_core.models.*` in the same commit (A9 forbids a test-count delta). |
| **2.3** `bootstrap.py` move + `layers` | the `layers` contract is stricter than the tree and half of `uadas_core` fails it | Contract lands *after* 2.2's cycle-cut; `architect` drafts the stanza against the post-2.2 tree in R2.4; if still broken, the contract ships with an explicit `ignore_imports` allowlist documented inline, and the remaining edges become Phase-3 debt items, not a blocker. |
| **2.4** asset extraction | a copy string / dict / SVG set is extracted lossily and the loss is only noticed in Phase 4 | Each extracted data file gets a tiny round-trip or snapshot test committed with it (e.g. `test_action_registry_export.py` asserts the JSON has all 24 actions with their predicates); `a11y-reviewer` spot-checks the contrast-manifest and a11y-rules extracts for fidelity. |
| **2.5** deletion | `kaleido` / `reportlab` (static report export) or `plotly` get pruned by over-eager dep cleanup | The dep-drop list is explicit and reviewed row-by-row (Part D 2.5): drop only `PySide6`, `pywinauto`, `pytest-qt`, and the 8 verified-never-imported (`polars`, `dask`, `numba`, `joblib`, `networkx`, `ydata-profiling`, `watchdog`, `aiohttp`) + 3 unbuilt-model (`xgboost`, `lightgbm`, `catboost`). **Keep** `kaleido`, `reportlab`, `plotly`, `pyarrow`, `duckdb`. Re-grep `uadas_core/` for each dropped name → 0 before removing it from `requirements.txt`. |
| **2.6** CI | see Risk C | see Risk C |
| **2.7** D4 atomicity follow-up | it is a behaviour change in `uadas_core/persistence/` billed as a Phase-2 tidy | Own red-then-green test (a crash injected between the frame write and the `.db` `os.replace` leaves no orphan `.parquet` and the old `.db` intact); `security-reviewer` re-checks the `.parquet.tmp` path derivation (same `dataset_id`-keyed-path surface reviewed in 1.6). Optional — can defer to Phase 3 if scope tightens. |

---

## Part D — Risk-optimized execution order

The master plan describes Phase 2 as one "mine then delete" motion. For *risk*, it is better
split into the sequence below — **locked as the order of record** (`architect` may flag a hard
dependency error at R2.4; nothing else re-opens it):

1. **2.0** scope lock — R2.3 (`ecc:code-explorer` inventory → playbook §5a) + R2.4 (`ecc:architect`
   opus rulings → `plans/phase-2-structural-moves.md`) + R2.5 (CI design → playbook §5b). **DONE.**
2. **2.1** lift the **10** Qt-free modules (7 D5 + `actions/{action_registry,builtin_actions,
   action_context}`) into `uadas_core/{theme,a11y,help,actions,...}` — `git mv` + import fix +
   `lint-imports`-guarded; **also extend contract 2's `source_modules` list**. Lowest risk;
   *reduces* what 2.5 deletes. Behaviour-frozen (A10). (`workbench/stage_registry.py` is NOT
   lift-safe — delete-only + phase-4-note.)
3. **2.2** extract `uadas_core/models/` (D1) — `models/workspace.py` (`Dataset`, `Visualization`,
   `DashboardTile`, `Dashboard`) + `models/project.py` (`Project`); scripted rewrite of ~33
   call sites (`from uadas_core.models import …`), incl. `mock.patch` targets; **extend contract
   2's `source_modules`**. Cuts the `analysis_orchestrator_service → tool_registry →
   workspace_service` loop; the residual `assistant_service → WorkspaceService` edge is left for
   2.3's `ignore_imports`. Behaviour-frozen (A10).
4. **2.3** move `bootstrap.py` → `uadas_core/bootstrap.py`, fix its `core/__init__.py:1` stale
   header, add the corrected 13-layer `layers` contract (contract 3, with the one
   `ignore_imports` line) + extend contract 2's `source_modules` — all in the same commit (D2).
   Behaviour-frozen (A10). **Re-run `lint-imports` and adjust the stanza's `theme`/`help`/
   `actions` tier placement to whatever 2.1 actually created** — don't paste blindly. After
   this, `uadas_core` layering is machine-checked (3 contracts kept).
5. **2.4** mine the remaining reusable assets to committed data files (design tokens, a11y rule
   catalog, action-registry data + enablement-context shape, empty/error/onboarding copy, icon
   set, chart-bridge semantics note, manual anchor index if not already a lifted module). No
   deletion. Each extract carries a fidelity test.
6. **2.5** the deletion — `git rm` in reviewable groups: `src/ui/` tree · `tests/ui/` tree ·
   `src/workers/` + `src/app.py` + `main.py`'s Qt path · the Qt-only scripts + markers +
   `tests/ui/conftest.py` + `test_uia_integration.py` · `resources/styles/*.qss*` · the dep
   drops in `requirements.txt`. `ecc:refactor-cleaner` sweep after each group. Screenshot
   parity retired here (A11).
7. **2.6** CI transformation (R2.5 design) — `test` job → Linux single-invocation; delete
   `run_tests_and_exit_cleanly.py` / `screenshot_app_state.py` references; drop the
   `uia_integration` job. Risk-C controls (collect-count assertion, run-it-first, keep-old-for-
   one-commit).
8. **2.7** D4 persistence-atomicity follow-up (`.parquet.tmp` staging + post-swap GC) —
   additive, test-guarded, `security-reviewer`. *Optional; defer to Phase 3 if scope tightens.*
9. **2.8** doc + tooling sync — `docs/ARCHITECTURE.md`, `CLAUDE.md`,
   `docs/RESOURCE_ORCHESTRATION.md` (advance Phase map to Phase 3 active; kill the two-invocation
   / `0xC0000005` / offscreen notes); `docs/MYPY_DEBT.md` regenerate (expect sharp shrink);
   retire `.claude/skills/pyside6-development/`, queue `dataviz-development` /
   `project-architecture` / `milestone-verification` / `a11y-reviewer.md` rewrites for Phase 4;
   fix `quality-check.ps1`'s `ruff format` vs `black` conflict; re-run the `.claude/` de-stale
   pass properly (D8 — ~112 stale `src/<pkg>/` refs across 10 files).

**Rationale for the split:** lift (2.1) and type-extraction (2.2/2.3) are behaviour-frozen and
must be green *before* the irreversible-feeling deletion (2.5); asset mining (2.4) is the
"mine" half and gates 2.5; CI rework (2.6) needs the deletion done so the new job tests the
real surviving suite; the persistence tidy (2.7) is unrelated and last; docs (2.8) close it.

---

## Part E — Phase 2 Definition of Done

Merges to `main` only when, in a single CI run on `phase-2/retire-desktop-ui`:

- [ ] `grep -rnE "\bPySide6\b|\bPyQt" --include=*.py .` returns nothing outside `.venv/` and
      git history.
- [ ] In a **fresh virtualenv with `PySide6` uninstalled**, on **Linux**:
      `python -c "import uadas_core"` exits 0, **and the full surviving test suite passes there**
      (this is now the primary test run, not a supplementary import smoke).
- [ ] `collected(pre-Phase-2) − collected(post)` equals **exactly** the tests in
      `plans/phase-2-deletion-manifest-tests.txt` (A9) — no surviving non-UI test lost or newly
      failing.
- [ ] `lint-imports` green in CI — **3 contracts** `KEPT` (Qt/Django forbidden ·
      provenance-is-a-leaf · the new `layers` contract).
- [ ] The R2.3 extraction checklist is 100% ticked — every asset row lifted (2.1) or extracted
      as committed data (2.4), reviewer-confirmed before 2.5.
- [ ] `docs/MYPY_DEBT.md` regenerated; the scoped `mypy` list in `ci.yml` no longer names any
      `src/ui/*` module; two-tree error count down sharply (`src/ui/main_window.py` alone was
      ~29).
- [ ] The `test` CI job runs on `ubuntu-latest` as a single `pytest` invocation and asserts its
      own collected count (Risk C, C-2); `scripts/run_tests_and_exit_cleanly.py` and the
      `uia_integration` job are gone.
- [ ] `DCO_ENFORCING=1` (set this session) and every Phase 2 commit is `git commit -s`.
- [ ] Every sub-step (2.1–2.8) had an independent reviewer sign-off (A3), recorded in
      `.superpowers/sdd/phase-2/progress.md`.
- [ ] `docs/ARCHITECTURE.md`, `CLAUDE.md`, `docs/RESOURCE_ORCHESTRATION.md` updated to describe
      the post-desktop `uadas_core/`-only layout (`models/`, top-level `bootstrap.py`, no
      shell, no Qt notes) — the `milestone-doc-sync` skill.
- [ ] One PR `phase-2/retire-desktop-ui → main`, whole-branch review on the most capable model
      (`superpowers:requesting-code-review`), CI green, merge commit (A7 — squash only on an
      explicit recorded decision).

---

## Unverified (carried into execution as assumptions, not facts)

- **The surviving-suite count** post-deletion is unknown until 2.5 runs — R2.1 records the
  *pre* number and the deletion manifest; the *post* number is derived, not forecast.
- **Whether all 8 D5 modules are lift-safe** — `lint-imports` on the 2.1 commit is the proof;
  `theme/plotly_theme.py`'s import list is the one to check first.
- **Whether the `services ↔ ai` cycle is the only one** the `models/` move must consider —
  R2.4's `graphify path` pass enumerates; there may be a `services ↔ persistence` or
  `services ↔ provenance` edge too.
- **Whether the `layers` contract can be `KEPT` with a flat stanza** or needs an
  `ignore_imports` allowlist — R2.4 drafts it against the post-2.2 tree; residual edges become
  Phase-3 debt, not a Phase-2 blocker.
- **The 20-row extraction inventory is complete** — it was written 2026-09-02; R2.3's
  `code-explorer` pass is what makes it current and exhaustive.
- **`main.py`'s exact Qt-entry shape** post-Phase-1 — R2.3 confirms what `main.py` still
  imports and how much of it is the desktop path vs. a future headless entry point.
- Effort framing here is estimate, not measurement (same caveat as every prior plan doc).
