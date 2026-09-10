# Phase 2 — Execution Playbook

**Status:** DRAFT 2026-09-10 · branch `phase-2/retire-desktop-ui` not yet cut (base `main` @
`4d61b93`) · **sub-step 2.1 does not start until:** R2.3 (`ecc:code-explorer` inventory) +
R2.4 (`architect` structural rulings) + R2.5 (CI-transformation design) each have non-author
reviewer sign-off · the user says "go".

**How to read this.** `phase-2-derisking-and-readiness.md` says *why* each control exists and
*what* proves it. This file says *how the sub-steps are actually run* — the loop, the agent per
role, the exact gate per step, the roll-up to `main`. `phase-2-resource-plan.md` is the
per-sub-step resource matrix. Part D order (in the de-risking doc) is fixed.

---

## 1. The per-sub-step loop (from `superpowers:subagent-driven-development`)

Every sub-step 2.1 … 2.8 is one pass of this loop. No sub-step overlaps another.

1. **JIT bite-sized plan.** Immediately before the sub-step, author its own
   `plans/phase-2-<step>-plan.md` with `superpowers:writing-plans` — bite-sized tasks (TDD
   where there is code to test), written against the tree *as it is at that moment*, carrying an
   `## Unverified` section. For 2.1 / 2.2 / 2.3 the "plan" is largely the scripted
   `git mv` + import-rewrite recipe; for 2.4 it is the per-asset extraction + fidelity-test
   list; for 2.5 it is the `git rm` group list from the R2.3 checklist.
2. **Ledger.** `.superpowers/sdd/phase-2/progress.md` — survives compaction; the commits it
   names are the recovery map. Created at branch cut with the sub-step skeleton.
3. **Write.** The orchestrator runs the mechanical `git mv` / import-rewrite / `git rm`
   directly for 2.1 / 2.2 / 2.3 / 2.5 (serial, single-purpose — a writer subagent adds a
   cold-context round-trip and buys nothing; `docs/RESOURCE_ORCHESTRATION.md` §1.2). `2.2`'s
   `models/` extraction goes to an `implementer` **in a worktree only if** R2.4 rules the type
   partition large enough to be abortable; default is inline. `2.7` (D4 atomicity) is an
   `implementer` in a worktree (greenfield-ish, test-first, additive). Never self-review.
4. **Verify.** Run the sub-step's named verification commands (§below); paste the output. A
   code read is never evidence (A4).
5. **Review.** `superpowers` `review-package` → a **fresh agent that did not write it**
   (mapping in §2). Fix loop ≤ 5 rounds; rulings recorded in the ledger.
6. **Sub-step sign-off (A2/A3).** No per-step GitHub sub-PRs — all work stays on
   `phase-2/retire-desktop-ui` (A1 keeps `main` safe). Each sub-step's commit range + its
   independent reviewer + verdict is recorded in the SDD ledger. A sub-step's own CI run
   (`test` + `lint` + `linux_import`, and `uia_integration` until 2.6 deletes it) must be green
   before the next sub-step starts — checked via `gh`.
7. **Baseline check.** After every behaviour-frozen step (2.1 / 2.2 / 2.3) the full suite must
   still reproduce the R2.1 baseline **1542 / 92 / 0** exactly (A10 — those steps change no
   behaviour and delete no test). From 2.5 on, the check is the A9 *delta* rule: the collected
   count drops by exactly the R2.1 test-deletion manifest, nothing else.

**Model tiers** (always passed explicitly): mechanical steps (2.1, 2.3, 2.5) — orchestrator-run
+ cheap-tier `code-reviewer` per commit. Structural step (2.2) — `ecc:architect` (opus) rules
the boundary once (folded into R2.4), then inline or `implementer` + mid-tier `code-reviewer`.
Asset extraction (2.4) — inline + `a11y-reviewer` spot-check on the a11y extracts. CI rework
(2.6) — orchestrator + `code-reviewer`, Risk-C controls. D4 (2.7) — `implementer` +
`security-reviewer`. Docs (2.8) — inline + `ecc:doc-updater`.

---

## 2. The sub-steps (Part D order)

Writer ≠ verifier on every row (A3).

| # | Sub-step | Writer | Verifier | Behaviour | Rough size |
|---|---|---|---|---|---|
| 2.0 | scope lock — R2.3 inventory + R2.4 structural rulings + R2.5 CI design | `ecc:code-explorer` + `ecc:architect` (opus) | repo `code-reviewer` (reviews the 3 deliverable docs) | n/a — no code | 3 docs |
| 2.1 | lift the 8 Qt-free stranded modules (D5) → `uadas_core/` + import fix | orchestrator (`git mv` + scripted import rewrite) | `code-reviewer` + `lint-imports` | frozen (A10) | ~8 modules moved, 0 logic lines |
| 2.2 | extract `uadas_core/models/` (D1) — `Dataset`/`Visualization`/`Dashboard`/`DashboardTile` out of `workspace_service.py`; cut the `services↔ai` cycle | orchestrator (or `implementer`+worktree if R2.4 says abortable) | `architect` (boundary) + `code-reviewer` | frozen (A10) | 1 new package + fan-in import rewrite |
| 2.3 | move `bootstrap.py` → `uadas_core/bootstrap.py`; add `[importlinter:contract:3] type = layers` in the **same commit** (D2) | orchestrator (`git mv` + `.importlinter` edit) | `architect` (layer order) + `code-reviewer` | frozen (A10) | 1 file moved + 1 contract |
| 2.4 | mine remaining reusable assets → committed data files (tokens, a11y rules, action-registry data, enablement-context shape, empty/error/onboarding copy, icons, chart-bridge note) | inline (per R2.3 checklist) | `a11y-reviewer` (a11y extracts) + `code-reviewer` (the rest) | additive data only | ~10 data files + fidelity tests |
| 2.5 | `git rm` — `src/ui/` · `tests/ui/` · `src/workers/` + `src/core/app.py` + `main.py` Qt path · Qt scripts/markers/`conftest.py`/`test_uia_integration.py` · `resources/styles/*.qss*` · dep drops | orchestrator (`git rm` in groups) | `ecc:refactor-cleaner` (dangling-ref sweep per group) + `code-reviewer` | **removes behaviour by design** | ~92 src + ~76 test files, 14 deps |
| 2.6 | CI transformation — `test` job → `ubuntu-latest` single `pytest`; delete `run_tests_and_exit_cleanly.py` / `screenshot_app_state.py` refs; drop `uia_integration` job; rewrite `pre-commit-check.ps1`'s suite command | orchestrator (`ci.yml` + hook edit) | `code-reviewer` + Risk-C controls (collect-count assert, run-it-first, keep-old-1-commit) | infra | `ci.yml` + 1 hook |
| 2.7 | *(optional — defer to Phase 3 if scope tightens)* D4 persistence atomicity — stage frames to `.parquet.tmp`, GC after the `.db` swap | `implementer` (worktree, test-first) | `security-reviewer` + `code-reviewer` | 1 named behaviour change (crash-safety) | small diff in `uadas_core/persistence/` |
| 2.8 | doc + tooling sync — `ARCHITECTURE.md` / `CLAUDE.md` / `RESOURCE_ORCHESTRATION.md` / `MYPY_DEBT.md`; retire `pyside6-development` skill; fix `quality-check.ps1` ruff-vs-black; re-run `.claude/` de-stale (D8) | inline + `ecc:doc-updater` | `code-reviewer` + `ecc:comment-analyzer` (batched) | docs | ~8 files |

### Per-step gate (the command whose output is the evidence)

- **2.1** — (1) `grep -rn "src\.ui\.theme\|src\.ui\.a11y\.contrast_manifest\|src\.ui\.help\|src\.ui\.widgets\.data_table\.column_formatters\|src\.ui\.workbench\.stage_registry" --include=*.py .` → 0 (all consumers re-pointed) · (2) `python -m compileall uadas_core -q` → 0 · (3) `python -c "import uadas_core"` → 0 · (4) `lint-imports` → **2 kept / 0 broken** (the moved modules import no Qt) · (5) full suite == **1542 / 92 / 0** exactly · (6) `black --check` / `isort --check-only` / scoped `mypy` / `bandit --skip B101,B107,B608` green · (7) `screenshot_app_state.py` still runs, byte-identical to `plans/baseline-app.png` (the app is still alive until 2.5). **Abort:** (4) breaks for one module → that module drops back to deletion-only, its `uadas_core/` consumers get an inline copy, re-run.
- **2.2** — (1) `graphify path "uadas_core.services.workspace_service" "uadas_core.ai.*"` shows the cut edge **gone** · (2) `grep -rn 'workspace_service\.\(Dataset\|Visualization\|Dashboard\|DashboardTile\)\|mock\.patch(.*workspace_service\.\(Dataset\|Visualization\|Dashboard\)' --include=*.py .` → 0 (all moved to `uadas_core.models`) · (3) characterization test green (`bootstrap()` resolves every service) · (4) full suite == **1542 / 92 / 0** · (5) `black`/`isort`/`mypy`/`bandit` green. **Abort:** the cycle does not break → back to R2.4, redesign the partition.
- **2.3** — (1) `lint-imports` → **3 kept / 0 broken** (the new `layers` contract holds) · (2) `grep -rn "core\.bootstrap\|core/bootstrap" --include=*.py .` → 0 (all re-pointed to `uadas_core.bootstrap`) · (3) `python -c "import uadas_core.bootstrap; uadas_core.bootstrap.bootstrap()"` → 0 · (4) full suite == **1542 / 92 / 0**. **Abort:** the `layers` contract can't be `KEPT` without further type moves → back to R2.4.
- **2.4** — per extracted data file: its fidelity test green (`test_<asset>_export.py` — e.g. the action-registry JSON has all 24 actions + their 3 predicates; the contrast manifest has every `CONTRAST_REQUIREMENTS` row; the a11y rules JSON has all 8 rule IDs + severities). `a11y-reviewer` confirms the a11y extracts are faithful. Full suite == **1542 / 92 / 0** (additive). No `src/ui/` file deleted yet.
- **2.5** — per `git rm` group: (1) `ecc:refactor-cleaner` sweep → no dangling import in a surviving file · (2) `grep -rn "src\.ui\|src/ui\|src\.workers\|src/workers" --include=*.py .` → 0 outside history after the last group · (3) after all groups: `grep -rnE "\bPySide6\b\|\bPyQt" --include=*.py .` → 0 outside `.venv/`, history · (4) fresh venv, `pip uninstall -y PySide6`, `python -c "import uadas_core"` → 0 **on Linux** · (5) surviving suite green; `collected(before) − collected(after)` == exactly `plans/phase-2-deletion-manifest-tests.txt` (A9) · (6) `lint-imports` → **3 kept / 0 broken** · (7) each dropped dep: `grep -rn "<depname>" uadas_core/ tests/` → 0 before removing it from `requirements.txt`. **Abort:** (4) or (5) fails → `git revert` that group, back to R2.3.
- **2.6** — (1) push a no-op commit with the reworked `ci.yml`; `gh run view <id> --log` shows the `ubuntu-latest` `test` job **collected and ran** the expected count (not 0, not skipped — observation 0022) · (2) the job asserts its own `--collect-only` count against `plans/phase-2-baseline.md`'s post-deletion band · (3) a deliberately-broken test on a scratch branch turns the new job **red** · (4) old `test` job kept required for one commit, then removed in a follow-up · (5) `run_tests_and_exit_cleanly.py` grep → 0 refs in `ci.yml` / hooks / docs. **Abort:** (1) shows 0 tests, or (2) count outside band → revert `ci.yml`, fix, re-run.
- **2.7** — red-then-green test: a crash injected between the Parquet frame write and the `.db` `os.replace` leaves **no** orphan `.parquet` and the **old** `.db` intact. `security-reviewer` sign-off on the `.parquet.tmp` path derivation. Full suite unchanged (additive).
- **2.8** — `docs/MYPY_DEBT.md` regenerated (two-tree count recorded, expected sharply down); `grep -rn "two-invocation\|0xC0000005\|QT_QPA_PLATFORM\|run_tests_and_exit_cleanly" docs/ CLAUDE.md` → only historical mentions; `docs/RESOURCE_ORCHESTRATION.md` §5 Phase map shows **Phase 3 active**; `.claude/` de-stale grep (`grep -rn "src/\(readers\|cleaning\|analysis\|services\|ai\|visualization\|forecasting\|database\|plugins\|reports\)/" .claude/`) → 0.

---

## 3. Roll-up to `main`

- `DCO_ENFORCING=1` was set this session (before Phase 2 branch cut). **Every Phase 2 commit is
  `git commit -s`** from the first one; the `dco` CI job is now gating, not advisory.
- After 2.8, the **Phase 2 Definition of Done** (`phase-2-derisking-and-readiness.md` Part E)
  runs in **one** CI pass on `phase-2/retire-desktop-ui`: `grep -r PySide6` empty; fresh
  PySide6-free venv on **Linux** runs `import uadas_core` + the full surviving suite green; the
  A9 collected-count delta == the deletion manifest; `lint-imports` 3 contracts `KEPT`;
  `MYPY_DEBT.md` regenerated + shrunk; the new Linux `test` job asserts its own count; every
  sub-step had an independent sign-off; `ARCHITECTURE.md` / `CLAUDE.md` /
  `RESOURCE_ORCHESTRATION.md` updated (`milestone-doc-sync`).
- Then **one PR**: `phase-2/retire-desktop-ui → main`, whole-branch review on the most capable
  model (`superpowers:requesting-code-review`) — **by sub-step commit range**, not one giant
  deletion diff — CI green, merge **commit** (A7 forbids rebase; squash only on an explicit
  recorded decision). `main` was releasable — with a working desktop app — the entire time (A1).
- **Deferred, folded in where noted:** D7 (2 unmoved `_register_builtins()`) → note in the PR
  description if not resolved by the `src/ui/` deletion. D9 (`provenance/` has no non-test
  callers) → state in the PR description so it isn't flagged as dead code. D11 (threaded
  `base_worker` caching-regression test) → opportunistic in 2.5's `src/workers/` removal or
  explicitly deferred.

---

## 4. Still-open before 2.1 can start

1. **R2.3** — `ecc:code-explorer` produces the extraction checklist (24 master-plan rows
   resolved against `main` @ `4d61b93`); `code-reviewer` signs it off.
2. **R2.4** — `ecc:architect` (opus) rules the `models/` partition, the `bootstrap.py` target,
   the `layers` stanza, and confirms Part D order; `code-reviewer` accepts
   `plans/phase-2-structural-moves.md`.
3. **R2.5** — the CI-transformation design is written into this file's `## CI transformation`
   section and `code-reviewer`-accepted.
4. **R2.6** — branch cut; `plans/phase-2-baseline.md` + the two deletion manifests committed.
5. **User go-ahead.**

R2.3 / R2.4 / R2.5 are read-only agent passes + doc writes — cheap. Nothing else blocks.

---

## 5. Residual risks / friction (honest)

- **After 2.5 there is no app to look at** (A11). Any "does it still work" question is answered
  by `import uadas_core` + the suite, not a screenshot, until Phase 4. Reviewers used to the
  Phase-1 screenshot-diff evidence must be told this is expected, not a gap.
- **`graphify` graph goes stale fast during 2.5.** Every `git rm` group invalidates a chunk of
  `graphify-out/graph.json`. Run `graphify update .` (AST-only, 0 tokens) after **each** 2.5
  group, not just at sub-step end, or the "what imports X" queries for the next group are wrong.
- **The `.claude/` skills that assume a Qt app** (`pyside6-development`,
  `milestone-verification`'s offscreen-Qt checklist, `a11y-reviewer.md`, `dataviz-development`'s
  `QWebEngineView` framing) will mis-route agent runs *during* Phase 2 if consulted. 2.8
  retires/rewrites them, but until then, prefer the plan docs over those skills for Phase 2
  work.
- **`pre-commit-check.ps1` still runs the two-invocation Windows suite** until 2.6. On a branch
  that has deleted `tests/ui/` (post-2.5, pre-2.6) the `--ignore=tests/ui/test_worker_runner.py`
  arg points at a deleted path — pytest tolerates a missing `--ignore` target, but confirm the
  hook doesn't hard-fail on it; if it does, 2.6's hook rewrite moves earlier.
- **`main.py`** — R2.3 must pin exactly what it imports post-Phase-1. If it already imports
  only `uadas_core` + a thin Qt bootstrap, 2.5's edit is small; if it still wires a lot of
  `src/ui`, that shapes 2.5's `main.py` group.
- **CI status is checkable** this session (`gh` at `C:\Program Files\GitHub CLI\gh.exe` via the
  PowerShell tool, authed as `T4fhim`) — unlike early Phase 1. Use `gh run list --branch
  phase-2/retire-desktop-ui` after each sub-step.
- **GateGuard fact-forces every first file edit** and the drive-letter `C:`↔`c:` case flip-flop
  defeats its per-file dedup (observation 0025) — a long mechanical batch (2.1's import rewrite,
  2.5's deletions) pays the fact-block tax repeatedly. Consider
  `ECC_DISABLED_HOOKS=pre:edit-write:gateguard-fact-force` for the genuinely mechanical
  sub-steps (as was done for Phase 1's codemod), re-enabled for 2.7's behaviour change.
