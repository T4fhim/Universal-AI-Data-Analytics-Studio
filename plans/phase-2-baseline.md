# Phase 2 — Pre-Deletion Baseline (R2.1)

**Captured 2026-09-10** · `main` @ `8ab95f6` (Phase 1 merged via PR #3 `4d61b93`; DCO-enforce +
Phase 2 planning triad merged via PR #4 `8ab95f6`) · branch `phase-2/retire-desktop-ui` cut
from this SHA.

This file is what **Control A9** compares against: after sub-step 2.5, the collected-test count
must drop by *exactly* the tests under `tests/ui/` (`plans/phase-2-deletion-manifest-tests.txt`)
plus any test file removed alongside `src/workers/` — and not one test more. A surviving
non-UI test that starts failing, or a non-`tests/ui/` file that vanishes, is an abort.

## Suite (two-invocation, `QT_QPA_PLATFORM=offscreen`)

| Invocation | Command | Result |
|---|---|---|
| 1 | `run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q` | **10 passed** (isolated re-run; one documented real-QThreadPool timing flake in the loaded run — CLAUDE.md "must run FIRST") |
| 2 | `run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py` | **1532 passed · 92 skipped · 3 deselected · 0 failed** in 624 s |
| **Total** | | **1542 passed / 92 skipped / 0 failed** |

Identical to the post-Phase-1-diagnosis rolling baseline in `plans/phase-1-baseline.md`.

## Collected-test partition (the A9 arithmetic)

`pytest --collect-only -q -m "not uia_integration"`:

| Scope | Collected | Test files |
|---|---|---|
| **Total (not uia_integration)** | **1634** | 130 `test_*.py` |
| under `tests/ui/` | 1183 (+ 3 `uia_integration` = 1186) | **76** — the expected-disappearance set |
| **outside `tests/ui/`** | **451** | **54** — the expected survivors |

**Predicted post-Phase-2 surviving collected count ≈ 451** (before R2.3 confirms whether any
`tests/` file outside `tests/ui/` is coupled to `src/workers/` and also leaves). This is the
band the 2.6 CI `--collect-only` assertion (Risk C, C-2) is set against.

## Static gates (all green on `8ab95f6`)

| Gate | Command | Result |
|---|---|---|
| black | `black --check src/ tests/ uadas_core/` | 379 files unchanged |
| isort | `isort --check-only src/ tests/ uadas_core/` | clean |
| import-linter | `lint-imports` | **2 kept / 0 broken** (Qt/Django forbidden · provenance-is-a-leaf) |
| bandit | `bandit -r src uadas_core -q --skip B101,B107,B608` | exit 0 |
| mypy (CI list) | the `ci.yml` "mypy (clean packages)" target list | **"Success: no issues found in 153 source files"** |
| screenshot | `screenshot_app_state.py --output <tmp>` | **byte-identical** to `plans/baseline-app.png` (16 294 bytes) — the last screenshot before the app is deleted at 2.5 (A11) |

## Deletion manifests (committed beside this file)

- `plans/phase-2-deletion-manifest-tests.txt` — **76** paths, `git ls-files 'tests/ui/**test_*.py'`.
- `plans/phase-2-deletion-manifest-src.txt` — **95** paths, `git ls-files 'src/ui/**' 'src/workers/**' 'src/app.py' 'src/__init__.py' 'main.py'` (`src/core/` no longer exists — Phase 1 removed it; R2.3).

## Reproduce

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python scripts/run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q --tb=no
python scripts/run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py --tb=no
python -m pytest --collect-only -q -m "not uia_integration"                 # 1634
python -m pytest --collect-only -q -m "not uia_integration" --ignore=tests/ui  # 451 (survivors)
python scripts/screenshot_app_state.py --output out.png                     # cmp out.png plans/baseline-app.png
```
