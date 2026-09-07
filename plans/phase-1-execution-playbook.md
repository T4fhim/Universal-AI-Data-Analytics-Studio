# Phase 1 — Execution Playbook

**Status:** ready 2026-09-07 · branch `phase-1/extract-uadas-core` (at `32c45ec`) · **step 1.1
does not start until:** R0.3 gets `code-reviewer`/`architect` sign-off · R0.4's two design docs
get reviewer + `security-reviewer` sign-off · the user says "go".

**How to read this.** `phase-1-derisking-and-readiness.md` says *why* each control exists and
*what* proves it. This file says *how the eight sub-steps are actually run* — the loop, the
agent per role, the exact gate per step, the roll-up to `main`. Part D order is fixed.

---

## 1. The per-sub-step loop (from `superpowers:subagent-driven-development`)

Every sub-step 1.1 … 1.7 is one pass of this loop. No sub-step overlaps another.

1. **JIT bite-sized plan.** Immediately before the sub-step, author its own
   `plans/phase-1-<step>-plan.md` with `superpowers:writing-plans` — bite-sized TDD tasks,
   written against the tree *as it is at that moment*, carrying an `## Unverified` section.
   (Design docs already exist for 1.6/1.7; 1.3 needs its startup-dependency-graph doc first —
   Control B-1.)
2. **Ledger.** `.superpowers/sdd/phase-1-<step>/progress.md` — survives compaction; the commits
   it names are the recovery map.
3. **Write.** A fresh `implementer` per task (or the orchestrator runs the scripted codemod
   directly for the pure-mechanical steps 1.1 / 1.5). Never self-review.
4. **Verify.** Run the sub-step's named verification commands (below); paste the output. A code
   read is never evidence (A4).
5. **Review.** `superpowers` `review-package` → a **fresh agent that did not write it**
   (mapping in section 2). Fix loop <= 5 rounds; rulings recorded in the ledger.
6. **Sub-PR.** The sub-step's commits go up as one PR into `phase-1/extract-uadas-core`. Its
   own CI run (`test` + `lint` + `uia_integration`) must be green **and** the reviewer signed
   off before the next sub-step starts (A2).
7. **Baseline check.** After 1.1, and after every behaviour-frozen step (1.2 / 1.3 / 1.5), the
   full suite must reproduce `plans/phase-1-baseline.md` **exactly** — 1381 passed / 103
   skipped / 0 failed, 1487 collected. One test's difference = abort (A9 / Risk A).

**Model tiers** (always passed explicitly): mechanical steps (1.1, 1.5) — orchestrator-run
codemod + cheap-tier `code-reviewer`. Refactor steps (1.2, 1.3) — standard `implementer` +
mid-tier `code-reviewer` + `architect` on the boundary question. Design steps (1.4, 1.6, 1.7)
— standard `implementer` + capable-tier reviewer. Security (1.8, and 1.6's key derivation) —
`security-reviewer` scopes first and verifies after.

---

## 2. The eight sub-steps (Part D order)

Writer != verifier on every row (A3).

| # | Sub-step | Writer | Verifier | Behaviour | Rough size |
|---|---|---|---|---|---|
| 1.1 | `git mv` carve-out + codemod + `.importlinter`→`uadas_core` + `lint-imports` in CI | orchestrator (scripted codemod) | `code-reviewer` + `architect` (app.py landing) | frozen (A10) | ~113 files moved, 0 logic lines |
| 1.5 | lift `src/ui/results/` renderers → `uadas_core/results/` | orchestrator (git mv + import fix) | `code-reviewer` | frozen | ~10 files |
| 1.2 | `JobRunner` protocol; `BaseWorker` becomes a shell adapter | `implementer` | `architect` (protocol) + `code-reviewer` (adapter) | frozen for callers | 1 new module + adapter |
| 1.8 | 4 security fixes (iteration cap · zip-slip · injected keys · SQL capability gate) | `implementer` | `security-reviewer` | 4 named behaviour changes | 4 small diffs, each test-guarded |
| 1.3 | de-globalise 4 registries + `logger._configured` + path constants; fix `_CHART_BUILDERS` snapshot bug | `implementer` | `architect` (order) + `code-reviewer` | frozen | one registry per commit |
| 1.4 | `Session` scope + `resolve(self, key: type[T]) -> T` generic | `implementer` | `architect` (scope model) + `code-reviewer` | frozen | clears ~29 mypy errors as proof |
| 1.6 | persistence layer (`plans/phase-1-6-persistence-contract.md`) | `implementer` (C-3 test first, red→green) | `security-reviewer` + `code-reviewer` | **additive** | new `uadas_core/persistence/` |
| 1.7 | provenance DAG + Recipe (`plans/phase-1-7-provenance-dag.md`) | `implementer` (C-2 prototype first) | `architect` (shape vs Phase 5 F1–F3/F10) | **additive** | new `uadas_core/provenance/` |

### Per-step gate (the command whose output is the evidence)

- **1.1** — (1) `grep -rnE '\b(from\|import)\s+src\.' --include='*.py' .` → 0 (outside `.venv/`,
  history) · (2) `python -m compileall uadas_core -q` → 0 · (3) `python -c "import uadas_core"` → 0
  · (4) collected count == 1487 / 1484 non-uia · (5) full suite == baseline **exactly** · (6)
  `black --check` / `isort --check-only` / `ruff check` / scoped `mypy` / `bandit --skip
  B101,B107,B608` all green · (7) `screenshot_app_state.py` runs, visual-diff vs
  `plans/baseline-app.png` unchanged · (8) `lint-imports` green · (9) branch CI all green.
  **Abort:** any of (4)/(5)/(7) deviates → `git reset --hard`, fix the codemod script, re-run.
- **1.5** — `lint-imports` green (`uadas_core/results/` imports no `PySide6`) · full suite ==
  baseline · `result_card.py` + `explanation_panel.py` confirmed *still in* `src/ui/`.
- **1.2** — every `BaseWorker` call site unchanged (grep) · full suite == baseline ·
  `architect` confirms the adapter preserves `fn, *args, report_progress, **kwargs` +
  `progress_callback`.
- **1.8** — 4 red-then-green tests: iteration cap hit; crafted zip entry escaping the temp dir
  rejected; a provider resolves an injected key, not `os.environ`; `execute_query` refuses
  without the capability flag. `security-reviewer` sign-off on the set. Then fold
  `.claude/hooks/pre-commit-check.ps1` bandit onto `--skip B101,B107,B608`, delete
  `.bandit-baseline.json` (deferred from Phase 0, same file).
- **1.3** — per registry commit: characterisation test green (`bootstrap()` resolves every
  service; registry contents match a recorded snapshot) + full suite == baseline +
  `screenshot_app_state.py` unchanged + `architect` confirms the documented startup order.
  `_CHART_BUILDERS`: red test (chart registered after import must appear in `tool_registry`) →
  fix → green.
- **1.4** — `docs/MYPY_DEBT.md` regenerated and shrunk; the scoped `mypy` list in `ci.yml`
  gains the newly-clean modules; error count down ~29. Full suite == baseline.
- **1.6** — the C-3 round-trip test green (save `{dataset, derived dataset, visualization,
  dashboard tile}` → load → full equality, **including the derived dataset**);
  `security-reviewer` sign-off on `dataset_id`-keyed paths; full suite unchanged (additive).
- **1.7** — the C-2 prototype round-trips **every** `AnalysisLog` fixture in the suite through
  DAG → Recipe → back; `Explanation.from_dict()` added and `Explanation(**e.to_dict()) == e`;
  `architect` sign-off on the shape vs F1–F3 / F10. **Abort:** a real fixture can't round-trip
  → stop, back to R0.4, redesign.

---

## 3. Roll-up to `main`

- The `dco` CI job flips `DCO_ENFORCING=1` on the **first** sub-step commit; every commit is
  `git commit -s` from then on.
- After 1.7, the **Phase 1 Definition of Done** (`phase-1-derisking-and-readiness.md` Part E)
  runs in **one** CI pass on `phase-1/extract-uadas-core`: fresh venv, `PySide6` uninstalled,
  **on Linux**, `python -c "import uadas_core"` → 0; the 45 non-UI test files pass there;
  `lint-imports` green; the Windows full suite still reproduces the golden baseline; C-3 + C-2
  tests green; `docs/MYPY_DEBT.md` shrunk; every sub-step had an independent sign-off;
  `docs/ARCHITECTURE.md` + `CLAUDE.md` updated (`milestone-doc-sync`).
- Then **one PR**: `phase-1/extract-uadas-core → main`, whole-branch review on the most capable
  model (`superpowers:requesting-code-review`), CI green, merge. `main` was releasable the
  entire time (A1).
- **Deferred, folded in where noted:** bulk `SPDX-License-Identifier` headers across `src/` →
  its own reviewed mechanical commit early in 1.1's PR or just after; the `pre-commit-check.ps1`
  bandit `--skip` fold → with 1.8.

---

## 4. Still-open before 1.1 can start

1. **R0.3** (`plans/phase-1-3-carveout-scope.md`) — `code-reviewer` or `architect` signs off
   the corrected carve-out list (add `services`, drop `engine`, defer `workers`) and the
   `core/app.py` split.
2. **R0.4** (`plans/phase-1-6-*`, `plans/phase-1-7-*`) — a reviewer accepts both; `security-
   reviewer` accepts 1.6's storage-key design.
3. **User go-ahead.**

These three are cheap (read-only agent passes + one word from the user). Nothing else blocks.

---

## 5. Residual risks / friction (honest)

- **The commit gate is not firing in this session.** `1f06bdc` fixed the trigger regex in
  `.claude/settings.json`, but a VS Code *window reload* did not reload hook config — commits
  `32c45ec` (and earlier) skipped the full-suite gate. Needs a **full VS Code restart** or
  "Developer: Restart Extension Host". Until then, sub-step commits are guarded only by CI, not
  the local pre-commit hook. (Observation-log candidate.)
- **CI status is not checkable from this environment** (no `gh`, no Actions MCP). Sub-step
  PRs' green/red must be read off the GitHub UI. The R0 commits are docs + inert config, so
  low risk, but 1.1+ genuinely needs the CI signal — confirm each sub-PR on GitHub before the
  next starts.
- **`0xC0000005` on the second test invocation** is expected (Windows Qt-shutdown AV, after a
  clean result; CI neutralises it via `Max(0, negative)`). Do not treat a non-zero exit from
  `run_tests_and_exit_cleanly.py` as failure without checking the printed summary line.
- **GateGuard fact-forces every file write** this session — it slows mechanical batches (obs
  0015). Recommend re-adding `{"env": {"ECC_GATEGUARD": "off"}}` to `.claude/settings.local.json`
  (gitignored, session-scoped) before 1.1's codemod, as was done for Phase 0.
- **`import-linter` at 1.1** — must confirm the config file form it wants after the rename
  (`.importlinter` vs `pyproject.toml [tool.importlinter]`); today's `.importlinter` INI works.
