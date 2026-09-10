# Phase 2.1 — Lift the 10 Qt-free modules into `uadas_core/`

**Status:** READY 2026-09-10 · branch `phase-2/retire-desktop-ui` @ `ef27994` · authored per
`plans/phase-2-execution-playbook.md` §1 step 1 (JIT bite-sized plan). Behaviour-frozen (**A10**):
`git mv` + import rewrite only — **zero logic lines change**; diff review is "did any non-import
line change? if yes, reject."

Governing skill: `safe-refactor`. Writer: orchestrator (scripted, serial — a writer subagent
buys nothing, `RESOURCE_ORCHESTRATION` §1.2). Reviewer: repo `code-reviewer` per commit +
`ecc:python-reviewer` once over the range. Every commit `git commit -s` (DCO enforcing).

---

## The 10 modules and their new homes (5 new `uadas_core/` packages)

`uadas_core/` currently has **no** `theme/`, `a11y/`, `help/`, `actions/`, `data_table/` — 2.1
creates all five (each with an `__init__.py`).

| # | Current | -> Target | Imports (verified Qt-free) | # importers to rewrite |
|---|---|---|---|---|
| 1 | `src/ui/theme/tokens.py` | `uadas_core/theme/tokens.py` | `dataclasses`, `enum`, `uadas_core.core.expertise_level` | 28 |
| 2 | `src/ui/theme/plotly_theme.py` | `uadas_core/theme/plotly_theme.py` | `typing`, `-> theme.tokens` (moves with it) | 4 |
| 3 | `src/ui/theme/contrast.py` | `uadas_core/theme/contrast.py` | `dataclasses` only | 4 |
| 4 | `src/ui/a11y/contrast_manifest.py` | `uadas_core/a11y/contrast_manifest.py` | `-> theme.contrast` | 4 |
| 5 | `src/ui/help/manual_index.py` | `uadas_core/help/manual_index.py` | `re`, `yaml`, `pathlib`, `uadas_core.core.{constants,exceptions,logger}` | 7 |
| 6 | `src/ui/help/manual_renderer.py` | `uadas_core/help/manual_renderer.py` | `markdown_it`, `-> help.manual_index` | 5 |
| 7 | `src/ui/widgets/data_table/column_formatters.py` | `uadas_core/data_table/column_formatters.py` | `datetime`, `pandas` | 3 |
| 8 | `src/ui/actions/action_registry.py` | `uadas_core/actions/action_registry.py` | (verify at exec — expect stdlib + `uadas_core.*`) | 18 |
| 9 | `src/ui/actions/builtin_actions.py` | `uadas_core/actions/builtin_actions.py` | `-> actions.action_registry`, `uadas_core.services.*` | 8 |
| 10 | `src/ui/actions/action_context.py` | `uadas_core/actions/action_context.py` | `uadas_core.services.*` | 8 |

**134 import lines total** across `src/` + `tests/` + `scripts/` (`grep -rn "src\.ui\.<mod>"`).
Most importers are in `src/ui/**` (deleted in 2.5) — rewriting them anyway keeps the suite green
through 2.1–2.4 and makes 2.5 a pure `git rm` with no shim cleanup. **No re-export shims.**

**NOT lifted:** `src/ui/workbench/stage_registry.py` — imports `src.ui.workbench.stage_page.StagePage`
(a `QWidget`); stays until 2.5, its stage-vocabulary -> extract-2.4.

---

## Commit grouping (one module-family per commit, ~5 commits, serial)

Each commit: `git mv` the file(s) -> create the package `__init__.py` -> scripted import rewrite
across `src/ tests/ scripts/` -> extend `.importlinter` contract 2 `source_modules` -> run the
per-commit gate -> `code-reviewer`.

| Commit | Modules | Import rewrite | `.importlinter` c2 add |
|---|---|---|---|
| **2.1a** | `theme/{tokens,plotly_theme,contrast}.py` -> `uadas_core/theme/` | `src.ui.theme.` -> `uadas_core.theme.` (and internal `from src.ui.theme.tokens` inside `plotly_theme` / `contrast`) | `uadas_core.theme` |
| **2.1b** | `a11y/contrast_manifest.py` -> `uadas_core/a11y/` | `src.ui.a11y.contrast_manifest` -> `uadas_core.a11y.contrast_manifest`; fix its `from src.ui.theme.contrast` -> `uadas_core.theme.contrast` | `uadas_core.a11y` |
| **2.1c** | `help/{manual_index,manual_renderer}.py` -> `uadas_core/help/` | `src.ui.help.manual_` -> `uadas_core.help.manual_`; internal `from src.ui.help.manual_index` in `manual_renderer`; **repoint `scripts/preview_manual.py`** | `uadas_core.help` |
| **2.1d** | `widgets/data_table/column_formatters.py` -> `uadas_core/data_table/` | `src.ui.widgets.data_table.column_formatters` -> `uadas_core.data_table.column_formatters` | `uadas_core.data_table` |
| **2.1e** | `actions/{action_registry,builtin_actions,action_context}.py` -> `uadas_core/actions/` | `src.ui.actions.` -> `uadas_core.actions.` (incl. `mock.patch("src.ui.actions...` strings in tests) | `uadas_core.actions` |

Order rationale: leaves first (`theme` has the widest fan-in but no internal deps beyond
`core`); `a11y` and `help` depend on `theme`/each-other; `actions` last (largest fan-in, 34
import lines, touches `mock.patch` strings).

---

## Per-commit gate (playbook §2, 2.1 row)

1. `grep -rn "src\.ui\.<the modules moved in THIS commit>" --include=*.py src/ tests/ scripts/` -> **0**
2. `python -m compileall uadas_core -q` -> 0
3. `python -c "import uadas_core"` -> 0
4. `lint-imports` -> **2 kept / 0 broken** AND contract 2's `source_modules` now names the new subpackage
5. full suite (2-invocation, `QT_QPA_PLATFORM=offscreen`) — **0 failed / 0 errors**, and the
   collected-count delta from `1542 / 92 / 0` fully explained by the three `src/ui/**`-glob
   policy meta-tests (`test_module_size`, `test_i18n_wrapped_strings`,
   `test_import_layering::test_nothing_outside_ui_imports_ui`) losing the just-moved modules
   from their parametrization (A10 collected-count caveat). No *named* test lost or newly
   skipped. Per-commit expected counts:

   | after | passed | skipped | collected (not-uia) | notes |
   |---|---|---|---|---|
   | baseline `9c137e3` | 1542 | 92 | 1634 | R2.1 |
   | 2.1a theme (3 mods + `__init__`) | 1540 | 89 | 1629 | −3 module_size, −3 i18n, layering −3 `src/ui` skip → +4 `uadas_core` (incl. new `__init__.py`) |
   | 2.1b a11y (1 mod + `__init__`) | 1539 | 88 | 1627 | −1 module_size, −1 i18n, layering −1 skip → +2 |
   | 2.1c help (2 mods + `__init__`) | 1538 | 86 | 1624 | −2 module_size, −2 i18n, layering −2 skip → +3 |
   | 2.1d data_table (1 mod + `__init__`) | 1537 | 85 | 1622 | same shape as 2.1b |
   | 2.1e actions (3 mods + `__init__`) | 1535 | 82 | 1617 | same shape as 2.1a |

   The 2.1b–e rows are *projected* from the 2.1a-observed mechanism; each commit's actual
   run is diffed against its predecessor with `pytest --collect-only` + `comm`, and any
   case lost that is **not** one of those three globs is an abort.
6. `black --check src/ uadas_core/ tests/` · `isort --check-only ...` · the `ci.yml` mypy list · `bandit -r src uadas_core -q --skip B101,B107,B608` -> all green
7. `python scripts/screenshot_app_state.py --output <tmp>.png` -> runs; `cmp` vs `plans/baseline-app.png` byte-identical (app still alive)

**After all 5 commits:** `ecc:python-reviewer` over the `2.1a..2.1e` range (confirms no logic
line moved); record commit range + verdict in `.superpowers/sdd/phase-2/progress.md`; confirm
the sub-step's own CI run green via `gh run list --branch phase-2/retire-desktop-ui`.

**Abort (per module):** if `lint-imports` breaks after a module moves (a transitive Qt import
surfaces), `git revert` that commit, drop the module to delete-only (2.5), and give any
`uadas_core/` consumer an inline copy of the needed function (separate reviewed commit). Expected
for none of the 10 — all were import-checked — but `action_registry`'s import list is the one
verified last, at exec time.

---

## Codemod mechanics (avoid the Phase 1.1 traps — SDD ledger notes)

- **Scripted, in the scratchpad**, not hand-edited; `src.ui.<x>` -> `uadas_core.<x>` is a literal
  string replace over `*.py` under `src/ tests/ scripts/` (NOT `.claude/` or `plans/` — those
  keep historical refs; NOT `uadas_core/` itself except the just-moved files' own internal imports).
- The `quality-check.ps1` hook runs `isort`->`black`->`ruff --fix` on every `.py` Edit and
  **strips an import added before its first use** (obs 0021/0023) — irrelevant here (no new
  imports, only path changes on existing lines) but watch the hook's reformat doesn't reorder in
  a way `black --check` then flags in CI (it won't — same tool).
- GateGuard fact-forces the first Edit per file (obs 0025) — a 134-line rewrite across ~50 files
  is a genuinely mechanical batch -> set `ECC_DISABLED_HOOKS=pre:edit-write:gateguard-fact-force`
  for the codemod run (as Phase 1.1 did), re-enable after.
- `.git/worktrees/agent-aeb0b845d41663001` throws a harmless "Permission denied" on every
  commit — ignore, the commit succeeds.
- After each commit: `graphify update .` (AST-only, 0 tokens).

## Verified at exec-start (2026-09-10)

- **All 10 modules confirmed Qt-free**, including `action_registry.py` (stdlib + `uadas_core.core.*`
  + TYPE_CHECKING `uadas_core.services.*` only) → **2.1e does NOT split**.
- **No `mock.patch("src.ui.…")` / dynamic-import string refs** to any of the 10 — the plan's 2.1e
  "patch-string" caveat is moot.
- **One stale cross-ref comment** at `uadas_core/core/constants.py:80` ("must stay in step with
  `src.ui.theme.tokens…`") — the 2.1a codemod rewrites it.
- **The 1542/92/0-exact assumption is wrong for 2.1** — three `tests/ui/` policy meta-tests
  parametrize over a `src/ui/**` glob and lose the moved modules from their case lists (see the
  per-commit expected-count table under §"Per-commit gate" and A10's collected-count caveat).
  2.1a observed: `1540 / 89 / 0`, collected 1629. The gate is now "0 failed + delta ⊆ those three
  globs", diffed per commit with `pytest --collect-only` + `comm`.

## Unverified (into execution)

- Whether any `tests/` file outside `tests/ui/` beyond `tests/services/test_guidance_service.py`
  imports one of the 10 — the codemod's own `grep -> 0` gate catches it either way.
