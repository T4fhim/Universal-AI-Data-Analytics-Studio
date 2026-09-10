# Phase 2 — Resource Plan (per-sub-step matrix + corrected facts)

Companion to `docs/RESOURCE_ORCHESTRATION.md` (§5 Phase map row for Phase 2, §6 to be
re-pointed here at Phase 2 kickoff) and `plans/phase-2-execution-playbook.md`. Plugin baseline
**`ecc/2.2.0`**. Auto-hooks are listed so they are *not* redone by hand, not invoked.

**Status:** DRAFT 2026-09-10 · not in force until Phase 2 execution is authorised.

---

## Corrected facts (verified this session — supersede the stale docs)

1. **`main` is at `4d61b93`** — Phase 1 merged (PR #3, merge commit). `origin/main` == local
   `main`. The 71-commit sub-step history is preserved (merge commit, not squash).
2. **Pre-Phase-2 baseline is 1542 / 92 / 0** (`main` @ `4d61b93`), identical to the
   post-Phase-1-diagnosis figure. Every "== baseline" gate for the behaviour-frozen sub-steps
   (2.1 / 2.2 / 2.3) means **this** number. `plans/phase-2-baseline.md` (written at branch cut)
   is the live record.
3. **`DCO_ENFORCING` is `"1"` from this session** (`.github/workflows/ci.yml`). The `dco` job
   is now gating, not advisory. **Every Phase 2 commit is `git commit -s`** — a missing
   `Signed-off-by` is a red CI check, not a warning.
4. **`src/ui/` + `src/workers/` = 92 `.py` files; `tests/ui/` = 76 `test_*.py` of 130.** Not
   the master plan's "101 / 90" (that counted the pre-carve-out tree).
5. **The 8 D5 stranded modules all exist** at their diagnosis paths (verified 2026-09-10):
   `src/ui/theme/plotly_theme.py`, `theme/tokens.py`, `theme/contrast.py`,
   `a11y/contrast_manifest.py`, `help/manual_index.py`, `help/manual_renderer.py`,
   `widgets/data_table/column_formatters.py`, `workbench/stage_registry.py`.
6. **`Dataset` / `Visualization` / `DashboardTile` / `Dashboard`** live in
   `uadas_core/services/workspace_service.py` at L40 / L124 / L169 / L191 — the D1 move target.
7. **`bootstrap.py` is at `uadas_core/core/bootstrap.py`** — there is no top-level
   `uadas_core/bootstrap.py` yet (the D2 target).
8. **`.importlinter` has 2 contracts** (`forbidden` Qt/Django + `provenance-is-a-leaf`), both
   `KEPT`. Phase 2 adds the 3rd (`layers`, contract 3) in 2.3.
9. **`ecc:refactor-cleaner` / `ecc:code-simplifier` are now in-scope.** `docs/RESOURCE_ORCHESTRATION.md`
   §4 and §5 both say so explicitly — they were excluded in Phase 1 as behaviour-adjacent
   under A10, but "they *do* belong in Phase 2, which is deletion work".
10. **CI status is checkable** — `gh` at `C:\Program Files\GitHub CLI\gh.exe` (PowerShell tool,
    authed `T4fhim`). Unlike early Phase 1, every sub-step's CI can be confirmed with
    `gh run list --branch phase-2/retire-desktop-ui`.
11. **After 2.5 there is no runnable app** (A11). `scripts/screenshot_app_state.py` and its
    baseline-diff verification are retired at 2.5 — not a resource for the back half of Phase 2.
12. **The 20-row extraction inventory in `web-transition-glass-box-studio.md` is stale on
    paths** (2026-09-02, pre-carve-out). R2.3's `ecc:code-explorer` pass is what makes it
    current — do not action a row from the master plan without R2.3 confirming its path.

---

## Recurring activities

| Activity | Agent / tier | Skill | Tool | Auto-hooks (don't redo) |
|---|---|---|---|---|
| JIT bite-sized plan per sub-step | inline | `superpowers:writing-plans` | — | — |
| Blast radius before a move/deletion | inline | `graphify` | `graphify query \| path \| explain`; `graphify update .` after **each** commit (0 tokens) | `graphify hook-guard` (advisory nudge on Bash/Grep/Read) |
| Behaviour-frozen move (2.1/2.2/2.3) | **INLINE** (`safe-refactor`) — serial, single-purpose; a writer subagent buys nothing (§1.2) | `safe-refactor` | scripted `git mv` + import rewrite; `lint-imports`; `compileall` | `quality-check.ps1` (isort→black→ruff --fix on every `.py` Edit — never re-run by hand; add import + first use in ONE Edit — obs 0021/0023) |
| Characterization / fidelity test | inline, TDD | `superpowers:test-driven-development`, `ecc:tdd-guide` | `run_tests_and_exit_cleanly.py` (2-invocation, until 2.6) | commit gate (`pre-commit-check.ps1`, `Bash\|PowerShell`) |
| Deletion (2.5) | **INLINE** (`git rm` in groups) + `ecc:refactor-cleaner` sweep after each group | `safe-refactor` (removal is structural) | `git rm`; `grep` sweep to 0; `graphify update .` | — |
| Per-commit verification | inline | `verify-and-stop`, `milestone-verification` *(Qt-offscreen parts stale — use for the suite/lint parts only)* | `lint-imports`, `mypy`, (until 2.5) `screenshot_app_state.py` | `quality-check.ps1` |
| CI status per sub-step | inline | — | `gh` (full path / PowerShell tool) — `gh run list --branch phase-2/retire-desktop-ui` | — |
| Code review | repo `code-reviewer` (haiku) per commit; `ecc:python-reviewer` (sonnet) once per sub-step for 2.1/2.2 | `superpowers:requesting-code-review` / `receiving-code-review` | — | — |
| Dangling-ref / dead-code sweep | `ecc:refactor-cleaner` (sonnet) — **now appropriate** | — | its own `knip`/`ts-prune`-style analysis, adapted to Python `grep`/`vulture` | — |
| Unexpected failure | `debugger` (sonnet, worktree) | `investigate-first` → `superpowers:systematic-debugging` | — | — |
| Doc sync (2.8) | inline + `ecc:doc-updater` | `milestone-doc-sync` | — | `quality-check.ps1` (`.py` only) |

**`0xC0000005`:** until 2.6, a non-zero exit from `run_tests_and_exit_cleanly.py` on the
*second* invocation is still the expected Windows Qt-shutdown access violation *after* a clean
result — CI-green-equivalent. Tell any Bash-capable subagent. **After 2.6 this note is dead** —
the Linux single-invocation job has no such teardown.

---

## 2.0 — scope lock (no code)

| Slot | Resource |
|---|---|
| R2.3 extraction-inventory pass | `ecc:code-explorer` — resolve all 24 master-plan asset rows against `main` @ `4d61b93`; partition every surviving `src/ui/` file into lift-2.1 / extract-2.4 / delete-only / already-safe; cross-check D5 + D7. **Report back caveman-compressed** (`caveman` full): one row per asset — `path` · disposition · target. No prose (§1.7). |
| R2.3 Qt-coupling grep | inline — `grep -rlnE "PySide6\|PyQt" src --include=*.py` |
| R2.4 structural rulings (batched) | `ecc:architect` (opus), **one** pass — the `models/` type partition + cycle proof (`graphify path`), the `bootstrap.py` target, the `layers` stanza text against the *post-2.2* tree, Part D order confirmation. Repo `architect` (haiku) writes the `plans/phase-2-structural-moves.md` skeleton first. |
| R2.5 CI-transformation design | inline — write the `## CI transformation` section into `plans/phase-2-execution-playbook.md`; `dev-resource-map` consult is **not** needed here (no new tooling — this is subtraction). |
| Review of all 3 deliverables | repo `code-reviewer` (haiku), one batched pass over the 3 docs |
| Exclude | `planner` (the plan exists — master plan + these docs); `security-reviewer` (no attack surface in a scoping pass); `dev-resource-map` (Phase 3/4 kickoff tool, not Phase 2). |

---

## 2.1 — lift the 8 Qt-free stranded modules (D5) — behaviour-frozen

| Slot | Resource |
|---|---|
| Import-safety pre-check | inline — for each of the 8, `grep "^import\|^from"` / a quick `ast` scan to confirm no Qt import (transitive included); `plotly_theme.py` first (load-bearing — themes `uadas_core/visualization`'s figures). |
| Move + rewrite | **INLINE** `safe-refactor` — `git mv src/ui/theme/*.py uadas_core/theme/` etc.; scripted `src.ui.theme` → `uadas_core.theme` rewrite across all consumers (incl. `tests/`, `mock.patch` strings). One module family per commit (theme / a11y / help / widgets / workbench) — ~5 commits. |
| Blast radius per commit | `graphify query "what imports src.ui.theme.plotly_theme"` before; `grep` sweep to 0 after; `graphify update .` after. |
| Per-commit review | repo `code-reviewer` (haiku), ~5× |
| Sub-step review | `ecc:python-reviewer` (sonnet), once, over the commit range — confirms no logic line moved |
| Per-commit verify | `lint-imports` (**2 kept / 0 broken**) + `python -c "import uadas_core"` + full suite (== **1542 / 92 / 0**) + (app still alive) `screenshot_app_state.py` byte-identical |
| Exclude | `implementer` (serial mechanical); `security-reviewer`, `a11y-reviewer` (a lift changes nothing — the a11y *data* extraction with its fidelity check is 2.4); `performance-analyzer` |

**Abort:** `lint-imports` breaks for a module → it drops to deletion-only (2.5); any
`uadas_core/` consumer of it gets an inline copy of the needed function, reviewed separately.

---

## 2.2 — extract `uadas_core/models/` (D1) — behaviour-frozen, cycle-cutting

| Slot | Resource |
|---|---|
| Design ruling | `ecc:architect` (opus) — folded into R2.4: which types move (`Dataset`/`Visualization`/`DashboardTile`/`Dashboard` + enums; rule on `SaveReport`/`WorkspaceSnapshot`/`RecipeStep`), the `models`-may-depend-on-`pandas` question, the exact cycle edge cut. |
| Cycle proof | `graphify path "uadas_core.services.workspace_service" "uadas_core.ai.<module>"` — recorded in `plans/phase-2-structural-moves.md` before and after. |
| The move | **INLINE** (default) — `git mv` the class bodies into `uadas_core/models/*.py`; scripted rewrite of the fan-in (`from uadas_core.services.workspace_service import Dataset` → `from uadas_core.models import Dataset`), incl. `mock.patch` targets, in the same commit (A9 forbids a test-count delta). **`implementer` + worktree only if** R2.4 rules the partition large/abortable. |
| Characterization | reuse Phase 1.3's `bootstrap()` characterization test if it survives; else a minimal "import + `bootstrap()` resolves every registered service" test, committed first, run before + after. |
| Review | `architect` (boundary — did the cycle actually break?) + repo `code-reviewer` (haiku) + `ecc:type-design-analyzer` (sonnet) re-read of the new `models/` package shape (it will get `to_dict` consumers in Phase 3 — worth a design pass now). |
| Verify | `graphify` shows the edge gone + characterization green + full suite == **1542 / 92 / 0** + `mypy` CI list still "Success" (add `uadas_core/models` to the list). |
| Exclude | `security-reviewer` (pure move); `lean-build` (not greenfield — it is a partition of existing types). |

**Abort:** the cycle does not break, or `mypy`/`layers` (in 2.3) can't be made clean without
moving more types → stop, return to R2.4, widen the partition.

---

## 2.3 — `bootstrap.py` → top-level + the `layers` contract (D2) — behaviour-frozen

| Slot | Resource |
|---|---|
| Layer-order ruling | `ecc:architect` (opus), folded into R2.4 — the exact `[importlinter:contract:3]` `type = layers` stanza, provable `KEPT` against the *post-2.2* tree; whether an `ignore_imports` allowlist is needed for residual edges. |
| The move | **INLINE** — `git mv uadas_core/core/bootstrap.py uadas_core/bootstrap.py`; rewrite `uadas_core.core.bootstrap` → `uadas_core.bootstrap` across `main.py`, `src/app.py` (alive until 2.5), tests; add the `layers` stanza to `.importlinter` **in the same commit**. |
| Review | `architect` (layer order sound?) + repo `code-reviewer` (haiku) |
| Verify | `lint-imports` → **3 kept / 0 broken** + `python -c "import uadas_core.bootstrap; uadas_core.bootstrap.bootstrap()"` → 0 + full suite == **1542 / 92 / 0** |
| Exclude | everything heavier — this is a one-file move + one INI stanza. |

**Abort:** `layers` can't be `KEPT` even with an `ignore_imports` allowlist → ship the contract
with the allowlist documented inline, log the residual edges as Phase-3 debt (`D`-series), do
**not** block Phase 2 on a perfect layering.

---

## 2.4 — mine remaining reusable assets to committed data files (additive data)

| Slot | Resource |
|---|---|
| Per-asset extraction list | from R2.3's checklist — each row that is "data embedded in a Qt file". Expected set (subject to R2.3): design-token dicts already covered by 2.1's `tokens.py` lift; **a11y rule catalog** (`src/ui/a11y/rules.py` `DEFAULT_RULES` — 8 rules, IDs+severity → JSON, check bodies discarded); **action-registry data** (`src/ui/actions/action_registry.py` + `builtin_actions.py` — 24 actions, 3 predicate lambdas → JSON + a tiny expression note); **enablement-context shape** (`action_context.py:68-77` → a documented `/api/capabilities` payload shape); **empty/error/onboarding copy** (`widgets/empty_state.py`, `error_state.py`, `dialogs/first_run_tour_dialog.py` `_BODY_HTML` → Markdown/JSON); **icon set** (`resources/icons/` — 43+3 SVG, `currentColor` → copy to `resources/web-assets/` or leave in place + inventory); **chart-bridge semantics** (`resources/web/chart_bridge.js` newPlot→react, relayout-for-theme → a Phase-4 hand-off note). |
| Extraction | **INLINE** — read the Qt file, write the data file, delete nothing. |
| Fidelity tests | `superpowers:test-driven-development` — one `tests/exports/test_<asset>_export.py` per file, asserting completeness (all 24 actions; every `CONTRAST_REQUIREMENTS` row; all 8 rule IDs). Committed **with** the data file. |
| a11y-extract review | `a11y-reviewer` (haiku) — confirms the contrast manifest + rules JSON are faithful to `src/ui/a11y/` before 2.5 deletes the source. |
| Rest review | repo `code-reviewer` (haiku) |
| Governing skill | `lean-build` — scope fence: extract **only** what Phases 3/4 consume; no speculative fields. |
| Exclude | `security-reviewer` (static copy strings); `implementer` (inline read→write). |

---

## 2.5 — the deletion (removes behaviour by design)

| Slot | Resource |
|---|---|
| Precondition (blocking) | R2.3 checklist 100% ticked + reviewer-confirmed; 2.1 + 2.4 green on the branch. |
| `git rm` groups | **INLINE**, one reviewable commit per group: (a) `src/ui/` tree · (b) `tests/ui/` tree · (c) `src/workers/` + `src/app.py` + `main.py` Qt path · (d) `scripts/run_tests_and_exit_cleanly.py` + `scripts/screenshot_app_state.py` + `tests/ui/conftest.py` + `tests/ui/a11y/test_uia_integration.py` + the `webengine`/`uia_integration` markers in `pyproject.toml` · (e) `resources/styles/*.qss*` + `resources/web/` QWebChannel wrapper · (f) `requirements.txt` dep drops. |
| Blast radius per group | `graphify query "what imports <target>"` before; `grep -rn` sweep to 0 after; **`graphify update .` after each group** (the graph rots fast — playbook §5). |
| Dangling-ref sweep | `ecc:refactor-cleaner` (sonnet) after **each** group — dead imports in surviving files, stale `pyproject.toml`/`ci.yml`/`.claude/` refs, now-unused helpers. **Report caveman-compressed** (§1.7). |
| Dep-drop safety | per dropped name (`PySide6`, `pywinauto`, `pytest-qt`, `polars`, `dask`, `numba`, `joblib`, `networkx`, `ydata-profiling`, `watchdog`, `aiohttp`, `xgboost`, `lightgbm`, `catboost`): `grep -rn "<name>" uadas_core/ tests/` → **0** before it leaves `requirements.txt`. **Keep** `kaleido`, `reportlab`, `plotly`, `pyarrow`, `duckdb`. |
| Per-group review | repo `code-reviewer` (haiku) |
| Sub-step review | `ecc:python-reviewer` (sonnet), once, over the deletion range |
| Verify (final) | `grep -rnE "\bPySide6\b\|\bPyQt"` → 0 outside `.venv/`/history · fresh PySide6-free venv on **Linux**: `import uadas_core` + surviving suite green · `collected` delta == `plans/phase-2-deletion-manifest-tests.txt` (A9) · `lint-imports` **3 kept / 0 broken** |
| Exclude | `security-reviewer` (removal has no new surface); `a11y-reviewer` (its input was captured in 2.4); `performance-analyzer` |

**Abort:** Linux `import uadas_core` fails, or the collected delta ≠ manifest → `git revert`
the offending group, return to R2.3, re-partition. Groups are separate commits — one bad
deletion never contaminates the others (A7 keeps them `revert`-able).

---

## 2.6 — CI transformation (infra)

| Slot | Resource |
|---|---|
| Design (blocking) | R2.5 — the `## CI transformation` section, `code-reviewer`-accepted. |
| The rewrite | **INLINE** — `.github/workflows/ci.yml` `test` job → `ubuntu-latest`, single `python -m pytest tests/ -q -m "not <retired markers>"`, `--collect-only` count assertion against `plans/phase-2-baseline.md`; drop the `uia_integration` job; fold or keep `linux_import` as a fast smoke; rewrite `.claude/hooks/pre-commit-check.ps1`'s suite command. |
| Risk-C controls | (C-3) no-op commit first, `gh run view <id> --log` proves the job **ran N tests** (obs 0022); (C-4) keep the old `test` job required for one commit, delete in a follow-up; a scratch-branch broken test proves the new job goes **red**. |
| Review | repo `code-reviewer` (haiku) + inline `gh` log inspection |
| Exclude | `ecc:build-error-resolver` / language build-resolvers (not a build failure — a deliberate rewrite); `dev-resource-map` (no new tool). |

---

## 2.7 — D4 persistence atomicity (optional; defer to Phase 3 if scope tightens)

| Slot | Resource |
|---|---|
| Governing skills | `surgical-patch` (narrowest layer) + `migration` (reversibility, crash-safety proof) |
| Test first | `superpowers:test-driven-development`, red→green — inject a crash between the Parquet frame write and the `.db` `os.replace`; assert **no** orphan `.parquet`, **old** `.db` intact. |
| Implementation | repo `implementer` (sonnet, **worktree**) — small, additive, behaviour-changing; `.parquet.tmp` staging + post-swap GC in `uadas_core/persistence/persistence_service.py`. |
| Security | repo `security-reviewer` — re-check the `.parquet.tmp` path derivation (same `dataset_id`-keyed-path surface reviewed in 1.6; CI `bandit --skip B608` means manual review is the only SQL/path gate). |
| Review | repo `code-reviewer` (haiku) |
| Exclude | `ecc:database-reviewer` (that is Phase 3 — Postgres; this is SQLite + local Parquet). |

---

## Definition of Done + the single PR

| Slot | Resource |
|---|---|
| Linux runtime job | already exists (`linux_import`, Phase 1) — 2.6 promotes it to run the full suite, not just `import uadas_core`. |
| Deletion manifest | `plans/phase-2-deletion-manifest-tests.txt` (committed at R2.6) is the A9 oracle. |
| Whole-branch review | `superpowers:requesting-code-review` → `ecc:code-reviewer` (sonnet) + `ecc:architect` (opus), **by sub-step commit range** — a large deletion diff reviewed as one blob is not a review. |
| Test dimension | `ecc:pr-test-analyzer` — confirms the surviving suite still covers what matters after 76 test files leave (did any non-UI behaviour lose its only test?). |
| Comment sweep | `ecc:comment-analyzer` (haiku), batched once — targets: any `src.ui…` / "the shell" / "desktop" language left in `uadas_core/` docstrings + comments; `docs/` Qt-era phrasing. |
| Docs | `milestone-doc-sync` + `ecc:doc-updater` → `docs/ARCHITECTURE.md` (drop the PySide6/Qt layer section + "shell"), `CLAUDE.md` (same; new `models/` + top-level `bootstrap.py`; the Commands/Tests section loses the two-invocation dance), `docs/RESOURCE_ORCHESTRATION.md` (§2 CI note, §5 Phase map → **Phase 3 active**, §6 → point at Phase 3 docs). |
| MYPY_DEBT | regenerate; record the new two-tree count (expected sharply down — the whole `src/ui/` debt evaporates). |
| Completion gate | `milestone-verification` (suite + lint parts; its Qt-offscreen checklist is retired — flag for the 2.8 rewrite) + `verify-and-stop` backstop — not both as separate passes. |
| PR mechanics | `gh` (full path / PowerShell tool). A7 forbids rebase → the PR carries the full sub-step commit history. Squash = an explicit, recorded decision. `git commit -s` on every commit (DCO now gating). |
| `.claude/` skill retire/rewrite | 2.8 deletes `pyside6-development`; queues `dataviz-development` / `project-architecture` / `milestone-verification` / `.claude/agents/a11y-reviewer.md` rewrites **for Phase 4** (they need the web target to be real first) — do not rewrite them speculatively in Phase 2. |

---

## Excluded for the whole phase (ceremony / wrong domain)

- `security-reviewer` except on 2.7 (D4 path derivation) — deletion and mechanical moves add no
  attack surface.
- `performance-analyzer`, `a11y-reviewer` (except the 2.4 a11y-extract fidelity check) —
  nothing data-volume or visually-rendered changes; the a11y work is being *preserved as data*,
  not modified.
- `dev-resource-map`, `context7` / `ecc:docs-lookup` — Phase 3/4 kickoff resources (new
  frameworks); Phase 2 is subtraction, no new library.
- `ecc:django-*`, `ecc:react-*`, `vercel:*`, `mlflow:*`, `duckdb-skills:*` — later phases.
- The `caveman-*` family as an output mode — used only for the §1.7 agent→orchestrator
  compression on the R2.3 inventory and the 2.5 `refactor-cleaner` sweeps, never for written
  code, commit messages, or the user-facing summary.
- `planner` — the plan is this triad + the master plan; nothing to plan from prose.
