# Phase 2.3 — `bootstrap.py` to top level + the `layers` import-linter contract (D2)

**Status:** READY / STANDING BY 2026-10-01 · branch `phase-2/retire-desktop-ui` @ `ca31258` · **not
started — waits for the user's go.** Spec = `plans/phase-2-structural-moves.md` Ruling 2 + 3; this
plan **supersedes Ruling 3's stanza** with one validated against the real post-2.2 tree (below).
Behaviour-frozen (A10): one `git mv` + path rewrites + one contract, zero logic lines.

Governing skill: `safe-refactor` (with the 0027 rules: enumerate every reference form; prove the
move by collect-diff). Writer: orchestrator, inline (1 file moved + ~40 mechanical edits).
Verifiers: `architect` (layer order, **including the finding below**) + repo `code-reviewer`.

---

## 1. Why a dry run came first, and what it found

Ruling 3 was written before 2.1/2.2 added `a11y`, `actions`, `data_table`, `models`, and said
"re-run `lint-imports` and adjust, don't paste blindly". Done in a scratch copy of the post-move
tree (142 `.py` files, `bootstrap.py` at top level, repo untouched):

| Run | Result |
|---|---|
| Ruling 3 stanza **verbatim** | 2 kept / **1 broken**: `core.application_state -> models` (l.49) |
| + `a11y`,`actions`,`data_table` placed + 2nd `ignore_imports` | **3 kept / 0 broken** (2 ignored imports) |

**The finding (needs the architect's eye at close, not a blocker):** `core` cannot be the strict
bottom layer. `core/application_state.py:49` imports `Dataset, Project, Visualization` from
`models` — a `TYPE_CHECKING`-only edge (verified: no runtime construction/`isinstance` there) —
while `models/project.py` imports `core.exceptions.ServiceError`. So `core <-> models` is a real
two-package cycle; moving `Project` (Ruling 1) turned the old `core -> services` edge into a
`core -> models` edge instead of removing it. Options: **(a, recommended)** a 2nd documented
`ignore_imports` — same nature as the 1st, annotation-only, A10-clean; **(b)** move
`ApplicationState` up out of `core` (more renames, an unruled design change); **(c)** a `Protocol`
in `core` (a logic-adjacent change, A10-forbidden here). Take (a); file (b)/(c) with the existing
2.7 / Phase-3 `Protocol` follow-up for the first ignore.

### The validated stanza (dry-run: KEPT, 2 ignored imports)

```ini
[importlinter:contract:uadas-core-layers]
name = uadas_core subpackages form a strict dependency stack
type = layers
layers =
    uadas_core.bootstrap | uadas_core.provenance
    uadas_core.persistence | uadas_core.actions
    uadas_core.services
    uadas_core.ai
    uadas_core.plugins
    uadas_core.results
    uadas_core.visualization
    uadas_core.analysis
    uadas_core.cleaning | uadas_core.forecasting | uadas_core.database | uadas_core.reports | uadas_core.jobs
    uadas_core.readers | uadas_core.a11y
    uadas_core.models | uadas_core.theme | uadas_core.help | uadas_core.data_table
    uadas_core.core
ignore_imports =
    # (1) Last strand of the services<->ai cycle (Phase 1 diagnosis D1): AssistantService takes
    # WorkspaceService only as a constructor annotation. import-linter counts TYPE_CHECKING imports.
    # Remove when the annotation becomes a Protocol (2.7 / Phase 3).
    uadas_core.ai.assistant_service -> uadas_core.services.workspace_service
    # (2) core <-> models cycle: application_state annotates with Dataset/Project/Visualization
    # (TYPE_CHECKING only) while models.project raises core.exceptions.ServiceError.
    # Remove if ApplicationState moves above core or gets a Protocol.
    uadas_core.core.application_state -> uadas_core.models
```
Do **not** add `exclude_type_checking_imports` (not a key in import-linter 2.15). Keep contract 2.

## 2. The change set (every reference form enumerated *before* any codemod — obs 0027)

| # | Form | Hits (verified 2026-10-01) | Action |
|---|---|---|---|
| A | dotted `uadas_core.core.bootstrap` — **real imports** | 9 lines / 9 files: `src/app.py:26`, `src/ui/main_window.py:77`, `tests/core/test_bootstrap.py:19`, `tests/core/test_startup_registry_characterization.py:30`, `tests/ui/a11y/test_audit.py:24`, `tests/ui/a11y/_uia_target_app.py:79`, `tests/ui/controllers/test_theme_controller.py:19`, `tests/ui/test_main_window_actions.py:20`, `scripts/screenshot_app_state.py:66` | `codemod.sh uadas_core.core.bootstrap uadas_core.bootstrap` (`\b`-anchored) |
| A' | same, in `:func:`/`:mod:`/`:class:` doc roles and comments | ~39 lines, ~27 files (src/ui, tests, scripts, `uadas_core/{cleaning,core,jobs,plugins,results,services,visualization}`) | same pass |
| A'' | same path inside a **runtime string** | `uadas_core/jobs/__init__.py:95` (error message; no test asserts on it) | same pass; text-only change |
| B | `from uadas_core.core import bootstrap` | 0 | — |
| C | relative imports of bootstrap | 0 | — |
| D | bare path prose | `src/ui/command_stack.py:29` ("``bootstrap.py`` lives under ``uadas_core/core/``") | **hand edit** -> ``uadas_core/`` |
| E | **non-`.py`** | **`.github/workflows/ci.yml:406` — `import uadas_core.core.bootstrap` in the `linux_import` job: a HARD CI failure if missed**; `docs/ARCHITECTURE.md:36,53` | edit in the same commit (ci.yml mandatory; ARCHITECTURE.md two lines) |
| — | moved file's own header | `bootstrap.py:1` `# File:` -> `uadas_core/bootstrap.py` | sed line 1 |
| — | stale header found by R2.4 | `uadas_core/core/__init__.py:1` reads `# File: src/__init__.py` | fix to `uadas_core/core/__init__.py` |
| — | mypy continuity | `uadas_core/core` is in the CI mypy list; leaving it drops `bootstrap.py` out of scope | add `uadas_core/bootstrap.py` to the list |
| — | `.importlinter` | contract 2 `source_modules` + `uadas_core.bootstrap`; add contract 3 (stanza above) | edit |

Left for 2.8 (already stale *before* 2.3, from Phase 1): `.claude/agents/architect.md:26` and
`.claude/skills/project-architecture/SKILL.md:54` say `src/core/bootstrap.py`. Historical
`plans/phase-1-*` untouched. `*.egg-info/SOURCES.txt` is generated.

`bootstrap.py` imports `cleaning, core, jobs, persistence, plugins, results, services,
visualization` and **not** `provenance` (verified) — so the two top-tier siblings are independent.
`uadas_core/__init__.py` stays import-free (Ruling 2).

## 3. Per-commit gate

1. `grep -rnE 'uadas_core\.core\.bootstrap\b|core/bootstrap' src/ tests/ scripts/ uadas_core/ .github/ docs/ARCHITECTURE.md` -> **0** (all forms, incl. ci.yml)
2. `python -m compileall uadas_core -q` · `python -c "import uadas_core.bootstrap as b; b.bootstrap()"` -> 0
3. `lint-imports` -> **3 kept / 0 broken (2 ignored imports)**
4. black / isort / mypy list (+`uadas_core/bootstrap.py`) / bandit green
5. Suite. **Predicted `1540 / 82 / 0`, collected 1622 — unchanged.** The only expected collect-diff is
   one parametrized id *renamed*, `test_nothing_outside_ui_imports_ui[uadas_core\core\bootstrap.py]`
   -> `[uadas_core\bootstrap.py]` (1 lost + 1 gained, both passing). Anything else = abort.
6. Screenshot byte-identical to `plans/baseline-app.png`; `graphify update .`.
7. **Commit-gate observation:** this is the first `.py` commit since the gate was re-wired. Commit
   *after* the fast gates (gate on). A PreToolUse hook's stdout is **not shown on success**, so
   "Running pytest…" is invisible even when the gate works — the **~8-minute pause** is the only
   evidence. Pause = gate live: record it and skip a duplicate manual run. Returns in seconds =
   still dead: run the 2-invocation suite by hand **before pushing** (the commit is local and
   amendable). Either way, push only after a green suite. (A *failing* gate does show: it blocks
   the commit with exit 2 and a message.)

**Abort:** `lint-imports` reports any break beyond the two documented ignores -> stop, back to the
architect; a surviving dotted reference anywhere (esp. ci.yml); an unexplained collect-diff.

## 4. Standby: ready-to-send briefs (dispatch only on the user's go + a green gate)

**architect** (opus, read-only, after the commit, verifier role): *"Confirm commit <sha> on
`phase-2/retire-desktop-ui` (C:\Users\mdabu\OneDrive\Documents\Projects\Universal-AI-Data-Analytics-Studio)
implements `plans/phase-2-3-plan.md` §1–§2. Read that plan and `plans/phase-2-structural-moves.md`
Rulings 2–3. Judge specifically: (1) the 12-tier order — run `lint-imports` yourself; (2) the
SECOND `ignore_imports` (`core.application_state -> models`, annotation-only, caused by `Project`
moving to `models` while `models.project` imports `core.exceptions`) — is option (a) the right
call vs moving `ApplicationState` up or a `Protocol`?; (3) nothing from 2.4+ leaked in; (4)
`uadas_core/__init__.py` still import-free. Verdict APPROVE / APPROVE-WITH-CHANGES / mismatch."*

**code-reviewer** (after the commit): *"Review commit <sha>. Behaviour-frozen (A10): only `git mv`
of `uadas_core/core/bootstrap.py` -> `uadas_core/bootstrap.py`, path rewrites, `.importlinter`,
ci.yml. Check every changed line is one of: the dotted-path substitution, the `# File:` headers,
the contract-2 line, contract 3, the ci.yml mypy list/`linux_import` line, ARCHITECTURE.md lines
36/53, the `command_stack.py:29` prose. Then grep for ANY remaining `core.bootstrap`/`core/bootstrap`
in src/ tests/ scripts/ uadas_core/ .github/ (all reference forms — obs 0027). Run `lint-imports`
and `python -c "import uadas_core.bootstrap"`. Verdict + file:line."*

## 5. Unverified (into execution)

- Whether the commit gate runs the suite (see §3.7).
- Exact isort reflow of the 9 import-line files (mechanical; gate-checked).
- Whether `git mv` on Windows keeps the rename at >90% similarity (header line only changes).
