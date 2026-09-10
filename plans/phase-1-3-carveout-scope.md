# R0.3 — Carve-out scope: the confirmed `uadas_core` package list

**Status:** produced 2026-09-07 · **needs `code-reviewer` / `architect` sign-off before step 1.1 executes** (Gate verdict, `phase-1-derisking-and-readiness.md`).

**What this settles.** The `phase-1-derisking-and-readiness.md` R0.3 open question: *is the Qt-free
carve-out package list exhaustive and correct, and is there a hard dependency-order error in
Part D?* Answered against the working tree at `main` = `1f06bdc`, by direct enumeration.

---

## Method

```
# every top-level entry under src/
ls src/

# packages containing a DIRECT PySide6/PyQt import (line-anchored)
grep -rlE '^\s*(from|import)\s+(PySide6|PyQt5|PyQt6)\b' --include='*.py' src/

# ANY Qt token anywhere (imports inside functions, TYPE_CHECKING blocks, strings)
grep -rnE 'PySide6|PyQt5|PyQt6|QtCore|QtWidgets|QtGui' --include='*.py' <carve-out set>

# transitive proof: import-linter forbidden contract, allow_indirect_imports = False
lint-imports          # -> "Analyzed 264 files, 1389 dependencies. 1 kept, 0 broken."
```

## Per-package result

| `src/` package | .py files | files w/ direct Qt import | any Qt token | verdict |
|---|---:|---:|---|---|
| `ai` | 5 | 0 | none | **carve → `uadas_core/ai`** |
| `analysis` | 14 | 0 | none | **carve → `uadas_core/analysis`** |
| `cleaning` | 7 | 0 | none | **carve → `uadas_core/cleaning`** |
| `core` | 10 | **1** (`app.py`) | only `app.py` | **split** — see below |
| `database` | 10 | 0 | none | **carve → `uadas_core/database`** |
| `forecasting` | 8 | 0 | none | **carve → `uadas_core/forecasting`** |
| `plugins` | 4 | 0 | none | **carve → `uadas_core/plugins`** |
| `readers` | 20 | 0 | none | **carve → `uadas_core/readers`** |
| `reports` | 8 | 0 | none | **carve → `uadas_core/reports`** |
| `services` | 8 | 0 | none | **carve → `uadas_core/services`** ← *was missing from the plan list* |
| `visualization` | 10 | 0 | none | **carve → `uadas_core/visualization`** |
| `ui` | 101 | 63 | pervasive | **stays in the shell** (Phase 2 deletes wholesale) |
| `workers` | 2 | **1** (`base_worker.py`) | `base_worker.py` | **stays in the shell** until 1.2 — see below |

`import-linter` (transitive, indirect imports disallowed) confirms the whole carve-out set has
**no import path to `PySide6` / `PyQt` / `django`** — a stronger check than the token grep.

---

## Corrections to the plan's R0.3 list

The plan (`phase-1-derisking-and-readiness.md` line ~92) named:
`core readers cleaning analysis forecasting visualization ai reports database plugins workers engine` + lifted `results/`.

Three of those are wrong:

1. **`services` was omitted — must be added.** `src/services/` holds `analysis_orchestrator_service.py`,
   `workspace_service.py`, `project_service.py`, `report_service.py`, `settings_service.py`,
   `guidance_service.py`, `database_connection_service.py` — the entire headless
   application-logic layer, zero Qt imports. This is the *core* of `uadas_core`; leaving it in
   the shell would make the extraction pointless. **Add `services` to the 1.1 move.**

2. **`engine` does not exist.** There is no `src/engine/`. Stale reference — **drop it.**

3. **`workers` cannot move at 1.1.** `src/workers/` contains only `base_worker.py` (+ `__init__.py`),
   and `base_worker.py` is a `QThread` subclass — it *is* Qt. The plan's own Part D puts step
   1.2 (JobRunner) *after* 1.1, so at 1.1 there is no Qt-free replacement yet. Fortunately
   `src.workers` is imported **only** by `src/ui/widgets/data_table/data_table_view.py`,
   `src/ui/workbench/pages/predict_page.py`, and `src/ui/worker_runner.py` — all shell code, **zero
   carve-out packages touch it**. So it stays in the shell trivially; step 1.2 builds
   `uadas_core`'s job primitive fresh and leaves `BaseWorker` as a shell adapter (exactly the
   Part D 1.2 residual-risk row). **Remove `workers` from the 1.1 move; it is a 1.2 concern.**

`results/` is not a 1.1 item and was never a contradiction — it is *created* by step 1.5, which
lifts result-renderer files out of `src/ui/`. No change.

---

## The `core` split (confirmed: exactly one file)

`src/core/app.py` is the **only** Qt-touching module in `core`. It imports `PySide6` and
`src.ui.{autosave_timer, dialogs.first_run_tour_dialog, main_window, theme_manager}` (lines
29–32). **Nothing in the carve-out set imports `src.core.app`** (verified). So:

| `src/core/` module | destination |
|---|---|
| `__init__.py`, `application_state.py`, `bootstrap.py`, `config.py`, `constants.py`, `dependency_container.py`, `exceptions.py`, `expertise_level.py`, `logger.py` | → `uadas_core/core/` |
| `app.py` | **stays in the shell** (lands as `src/app.py`, or a thin `src/core/app.py` that imports from `uadas_core.core` — `architect` picks the exact spot at 1.1; low-stakes, Phase 2 deletes it) |

`core/bootstrap.py` and `core/application_state.py` import from `src.services.*` and
`src.plugins.*` — both now inside the carve-out set, so after the codemod these are
`uadas_core.core → uadas_core.services` / `uadas_core.plugins`: **all intra-`uadas_core`, no
boundary crossing.** No dependency-order problem.

---

## Final answer for step 1.1

**Move to `uadas_core/` (11 units, all proven Qt-free):**
`ai · analysis · cleaning · database · forecasting · plugins · readers · reports · services · visualization`
**+ `core/` minus `app.py`** (9 modules).

**Stays in the shell at 1.1** (`src/`): `ui/` (whole) · `core/app.py` · `workers/` · `main.py`'s desktop path.

**File count:** ~113 `.py` files move, vs. 214 under `src/` total — the carve-out is ~53% of the
tree and excludes the 101-file `ui/` package entirely. Consistent with the plan's
"~115, not ~360" estimate.

**Part D order:** no hard dependency error found. Order stands: `1.0 → 1.1 → 1.5 → 1.2 → 1.8 → 1.3 → 1.4 → 1.6 → 1.7`.

---

## `## Unverified`

- The exact landing module for `core/app.py` in the shell — deferred to `architect` at 1.1
  (it is a shell file Phase 2 removes; any of `src/app.py`, `src/core/app.py`, `src/ui/app.py`
  works).
- Whether `src/ui/worker_runner.py` (which bridges `BaseWorker` to the workbench) needs any
  change at 1.1 — assumed no, since it stays entirely in the shell alongside `workers/`.
- The `git mv` granularity (per-package `git mv src/<pkg> uadas_core/<pkg>` vs. one move) —
  a 1.1 codemod-script decision, not a scope decision.
- File counts above are from `find … -name '*.py' | wc -l` on 2026-09-07; the 1.1 plan
  re-counts against the tree at execution time (Control A-3).
