# Phase 1 — Golden Baseline (R0.1)

**Captured:** 2026-09-07 · **against `main` = `1f06bdc`** (`1f06bdced9910f1159022c12a646d6d072d65b14`).

This is the pass criterion for **Control A9**: after step 1.1's `git mv`, the full suite must
reproduce **these exact numbers**. A delta of one test = something was lost or broken by the
move — abort and fix the codemod (Risk A abort criterion).

Reproduce with `scripts/run_tests_and_exit_cleanly.py` exactly as below (mirrors CI's
two-invocation split; `QT_QPA_PLATFORM=offscreen`).

---

## Suite result

| Invocation | Command | Result |
|---|---|---|
| **1** | `run_tests_and_exit_cleanly.py tests/ui/test_worker_runner.py -q --tb=no` | **10 passed**, 0 skipped · 0.18 s · exit `0` |
| **2** | `run_tests_and_exit_cleanly.py tests/ -q -m "not uia_integration" --ignore=tests/ui/test_worker_runner.py --tb=no` | **1371 passed, 103 skipped, 3 deselected**, 0 failed, 0 errored, 0 xfailed, 0 xpassed · 44 warnings · 539.95 s · process exit `-1073741819` |
| **combined** | — | **1381 passed · 103 skipped · 3 deselected · 0 failed** |

**Wall clock** (both invocations, this machine): **546 s (~9.1 min)**.

### The invocation-2 exit code is expected and is CI-green-equivalent

`-1073741819` = `0xC0000005`, a Windows access violation during CPython/Qt interpreter
teardown — *after* pytest has printed its fully-clean result. This is the exact condition
`scripts/run_tests_and_exit_cleanly.py` and `.github/workflows/ci.yml` are built around:
CI's `test` step ends with `exit ([Math]::Max($exit1, $exit2))`, and because `0xC0000005` is a
**negative** signed int, `Max(0, -1073741819) = 0` — the job is green. A *real* pytest failure
returns a positive code (1–5), which `Max` would surface. So this baseline run == a green CI
`test` job. The clean counts above are pytest's own fully-determined result and are what A9
compares.

---

## Collected-test counts (`pytest --collect-only`)

| Selection | Collected |
|---|---|
| `-m "not uia_integration"` | **1484** (of 1487; 3 deselected) |
| full (incl. `uia_integration`) | **1487** |

So: **1487 total** · **1484 non-uia_integration** · **3 uia_integration** (run as their own CI job, not part of this baseline).

---

## App screenshot

`scripts/screenshot_app_state.py --output plans/baseline-app.png` → exit `0`,
**`plans/baseline-app.png`** (16,294 bytes), committed beside this file. Boot path exercised
clean: `bootstrap()` → 0 plugins → `MainWindow` constructed → theme `dark`/comfortable applied
→ chart web-assets staged → screenshot saved → window closed. Step 1.1 verification ⑦
visual-diffs the post-carve-out screenshot against this one.

*(This resolves one plan Unverified item: `screenshot_app_state.py` boots cleanly on the
pre-carve-out tree.)*

---

## Post-1.1 adjustment (recorded 2026-09-07)

Step 1.1's carve-out moves ~112 `.py` files from `src/` to `uadas_core/` and adds one new
`uadas_core/__init__.py`. `tests/ui/test_import_layering.py::test_nothing_outside_ui_imports_ui`
is parametrized over *every* source module (so the "nothing outside `src/ui` imports `src.ui`"
rule is enforced file-by-file); it was widened in 1.1 to also scan `uadas_core/`, so it keeps
enforcing that rule over the moved code. Net effect on the counts: **exactly +1** parametrized
case (the new package `__init__.py`), which passes.

**Post-1.1 expected numbers** — collected **1488 / 1485 non-uia** (was 1487 / 1484); suite
**1382 passed, 103 skipped, 0 failed** (was 1381 passed). Any *other* delta = a real
regression from the move (Risk A abort criterion still applies to everything except this
one documented +1).

---

## Environment

- Python **3.13.14**, `.venv` at repo root
- `PySide6` present (desktop shell intact)
- Windows 11; `QT_QPA_PLATFORM=offscreen`
- Tooling pins (from `requirements.txt`): `black==26.5.1`, `isort==8.0.1`, `mypy==2.1.0`,
  `ruff==0.16.3`, `bandit==1.9.4`, `import-linter==2.15` (added at R0.5)
