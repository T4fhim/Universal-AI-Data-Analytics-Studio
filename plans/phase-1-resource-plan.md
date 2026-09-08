# Phase 1 — Resource Plan (per-sub-step matrix + corrected facts)

Companion to `docs/RESOURCE_ORCHESTRATION.md` (§6) and `plans/phase-1-execution-playbook.md`.
Plugin baseline **`ecc/2.2.0`**. Auto-hooks are listed so they are *not* redone by hand, not
invoked.

---

## Corrected facts (verified this session — supersede the stale docs)

1. **Rolling baseline is 1413 / 92 / 0** (post-1.8), not R0.1's 1381 / 103 / 0. Every
   "== baseline" gate and the abort rule mean **this** number. `plans/phase-1-execution-playbook.md`
   and `plans/phase-1-derisking-and-readiness.md` Part E still quote the old figure.
2. **1.3 converts 6 registries, not 4.** Order below. `_BUILTIN_READERS` (a frozen `tuple` in
   `reader_registry.py`) stays as-is — only `_PLUGIN_READERS` is mutable state.
3. **`Session` scope is cut from 1.4.** 1.4 ships the typed generic `resolve()` only; the
   multi-tenancy scope defers to Phase 3 where an HTTP request is a real consumer.
4. **R0.4 is not signed off** — the recorded "architect APPROVE both docs" is
   architect-reviewing-its-own-doc (an A3 violation). Redone in pre-flight A5 with non-author
   agents.
5. **No Linux runtime CI job exists** — the `ubuntu-latest` job installs only lint tools. DoD
   bullets 1–2 (`python -c "import uadas_core"` in a PySide6-free venv; 45 non-UI test files on
   Linux) are unbuilt infrastructure. Built in pre-flight A3.
6. **No per-step sub-PRs were ever created** for 1.1–1.8. A3 "independent sign-off" is satisfied
   by ledger annotation (reviewer / verdict / commit-range in `.superpowers/sdd/phase-1/progress.md`).
7. **The local commit gate never fired this session** — cause is the `"Bash"`-only matcher in
   `.claude/settings.json` (PowerShell-tool commits never matched), fixed to `"Bash|PowerShell"`
   in pre-flight A1. Takes effect after a session reload.
8. **The `_CHART_BUILDERS` fix is a behaviour change** in a step marked A10-frozen — it makes
   plugin charts visible to the AI assistant and changes the LLM tool schema. Needs a named
   behaviour-change exemption from the pre-flight A4 architect pass, same as 1.8's four fixes.
9. **The generic `resolve()` needs an `@overload` pair, not a signature narrowing** —
   `DependencyContainer.register()` accepts any hashable key (`dependency_container.py:63-65`),
   so narrowing `resolve` to `type[T]` unilaterally contradicts it.
10. **`docs/MYPY_DEBT.md` measures the wrong tree** — its reproduce command is `python -m mypy
    src/`, which post-1.1 misses the ~113 files in `uadas_core/`. Corrected in pre-flight A7.
11. **1.6's acyclic `parent_dataset_id` check and 1.7's `outputs`-dropping round-trip are
    behaviour changes** inside steps billed "additive". Name them in the A4 / A5 reviews or a
    reviewer flags them late.

---

## Recurring activities

| Activity | Agent / tier | Skill | Tool | Auto-hooks (don't redo) |
|---|---|---|---|---|
| JIT bite-sized plan per sub-step | inline | `superpowers:writing-plans` | — | — |
| Characterization / red-green test | inline for B-3; `test-engineer` (sonnet, worktree) for C-2 / C-3 | `superpowers:test-driven-development`, `ecc:tdd-guide` | `scripts/run_tests_and_exit_cleanly.py` (2-invocation) | commit gate (post-reload) |
| Per-commit verification | inline | `verify-and-stop`, `milestone-verification` | `screenshot_app_state.py`, `lint-imports`, `mypy` | `quality-check.ps1` (isort→black→ruff --fix on every `.py` Edit — never re-run by hand; add import + first use in ONE Edit) |
| CI status per step | inline | — | `gh` at `C:\Program Files\GitHub CLI\gh.exe` via PowerShell tool | — |
| Code review | `code-reviewer` (haiku) per commit; `ecc:python-reviewer` (sonnet) once per sub-step | `superpowers:requesting-code-review` / `receiving-code-review` | — | — |
| Unexpected failure | `debugger` (sonnet, worktree) | `investigate-first` → `superpowers:systematic-debugging` | — | — |
| Doc sync | inline + `ecc:doc-updater` | `milestone-doc-sync` | — | `quality-check.ps1` (`.py` only) |

**`0xC0000005`:** a non-zero exit from `run_tests_and_exit_cleanly.py` on the *second* invocation
is the expected Windows Qt-shutdown access violation *after* a clean pytest result —
CI-green-equivalent. Tell any Bash-capable subagent this.

---

## 1.3 — de-globalize registries (6 commits, serial, A10-frozen)

| Slot | Resource |
|---|---|
| B-1 startup-graph doc (write) | repo `architect` (haiku) → `plans/phase-1-3-startup-graph.md` |
| B-1 verify + 4 rulings | `ecc:architect` (opus), one batched pass (pre-flight A4) |
| Blast radius | `graphify` — query per commit |
| Characterization (B-3) | `superpowers:test-driven-development` + `test-engineer` (sonnet, worktree); committed in the first B-2 commit, run before **and** after every subsequent one |
| Implementation | **INLINE** via `safe-refactor` — B-2 makes 1.3 irreducibly serial (one registry per commit, one suite run per commit); a writer subagent adds a cold-read round-trip and buys nothing |
| `_CHART_BUILDERS` fix | `superpowers:test-driven-development` red→green, inline; then `ecc:silent-failure-hunter` (sonnet) — an import-time snapshot is a silent-failure shape |
| Per-commit review | repo `code-reviewer` (haiku), 6× |
| Sub-step review | `ecc:python-reviewer` (sonnet), once, over the 6-commit range |
| Per-commit verify | full suite (== **1413 / 92 / 0**) + `screenshot_app_state.py` diff (B-5) + characterization test |
| Exclude | `ecc:code-simplifier`, `ecc:refactor-cleaner` (behaviour-adjacent under A10); `a11y-reviewer`, `performance-analyzer` (nothing visual / data-volume) |

**Corrected B-2 order (6 registries):**
`reader_registry` (`_PLUGIN_READERS` only) →
`cleaning/operation_registry` →
`visualization/chart_registry` →
`results/result_renderer_registry` (the 5th — arrived via 1.5, absent from the original B-2 list) →
`core/logger.py::_configured` →
`core/constants.py` `PROJECT_ROOT`-anchored path constants (`:37-44`; bound as default-arg
values at def-time across `bootstrap` / `config` / `logger` / `settings_service` — the riskiest).

**A4 rulings feed 1.3:** `_CHART_BUILDERS` → in-scope with a behaviour-change exemption;
`src/ui/actions/action_registry.py` → keep the global (outside `uadas_core/`, Phase 2 deletes
it); the 2 disposable JobRunner globals (`uadas_core/jobs/__init__.py::_default_job_runner`,
`src/workers/base_worker.py::_fallback_job_runner`) → keep, documented, die with `BaseWorker` in
Phase 2. Both are pinned by tests that `monkeypatch.setattr` the module attribute directly — any
change needs matching test edits in the same commit (A9 forbids a test-count delta).

---

## 1.4 — typed generic `resolve()` only (Session scope deferred)

| Slot | Resource |
|---|---|
| Design ruling | `ecc:architect` (opus) — folded into pre-flight A4 (mypy-scope decision; confirm Session deferred) |
| The generic | `ecc:type-design-analyzer` (sonnet) **scopes first** — must rule on the `register(key: object)` / `resolve(key: type[T])` asymmetry; the answer is an `@overload` pair (`dependency_container.py:63-65,102`) — then **INLINE** implementation |
| Proof | `mypy` / `dmypy` before/after counts; the ~29 errors radiate from 8 `resolve()` calls in `src/ui/main_window.py:117-125,265` |
| Review | repo `code-reviewer` (haiku) + `ecc:type-design-analyzer` re-read of the final signature |
| Exclude | `ecc:spec-miner` (opus) — specs already written; opus-tier mining of a doc is pure cost |

**mypy-scope note:** the 29 errors are in `src/ui/main_window.py`, which Phase 2 deletes. A4
ruling recommends *not* adding that file to CI's mypy list; prove the generic with a recorded
before/after `mypy src/ui/main_window.py` count in `docs/MYPY_DEBT.md`, and fold
`uadas_core/core/dependency_container.py` into `ci.yml`'s clean list instead.

---

## 1.6 — persistence (additive, greenfield)

| Slot | Resource |
|---|---|
| Gate (blocking) | R0.4 sign-off — pre-flight A5 (repo `code-reviewer` + `security-reviewer` on the contract) |
| Doc re-verification | `ecc:code-explorer` — every citation in the doc is a pre-1.1 `src/` path |
| Governing skills | `lean-build` (scope + stop condition) + `migration` (reversibility, preservation proof) |
| C-3 test first | `superpowers:test-driven-development`, red→green — save `{dataset, derived dataset, visualization, dashboard tile}` → load → full equality **including the derived dataset** |
| Implementation | repo `implementer` (sonnet, **worktree**) — genuinely greenfield; new `uadas_core/persistence/` |
| Security | repo `security-reviewer` **scopes first, verifies after**; **plus** `ecc:security-reviewer` (sonnet) — justified because CI's `bandit --skip B608` means the SQL-injection check is OFF for the new module; manual review is the only gate on `dataset_id`-keyed paths and SQL construction |
| Coupling flag | figure re-derivation on load calls `chart_registry.get(chart_type).build(...)`; if 1.3 makes `chart_registry` a container instance, persistence needs it injected, not imported — settle in the A4 architect pass |
| Exclude | `duckdb-skills:*` — the contract is SQLite + Parquet via pandas / pyarrow |

Additional: 1.6 adds an acyclic `parent_dataset_id` check to `workspace_service.add_dataset`
(a behaviour change; whether any fixture builds a cycle is Unverified — check first) and closes
the derived-dataset drop in `project_service.py`.

---

## 1.7 — provenance DAG + Recipe (additive, abortable)

| Slot | Resource |
|---|---|
| Gate (blocking) | R0.4 sign-off — pre-flight A5 (`ecc:architect` opus, **not** the repo architect that authored it) + fixture enumeration (`ecc:code-explorer`) |
| C-2 prototype first | repo `implementer` (sonnet, **worktree**) — the worktree is load-bearing: 1.7 is the only step with a mid-implementation **abort** clause, and under A7 an inline abort leaves a dirty shared branch. Read `docs/WORKTREE_TROUBLESHOOTING.md` first |
| `Explanation.from_dict()` | INLINE, TDD — `Explanation` is a `@dataclass` so `__eq__` is value-based; `Explanation(**e.to_dict()) == e` is a real proof (`uadas_core/analysis/explanation.py:29-30,76`) |
| Lossiness review | `ecc:silent-failure-hunter` (sonnet) — the round-trip deliberately drops `outputs` and re-derives on replay; confirm that's the only designed loss |
| Review | repo `code-reviewer` + `ecc:type-design-analyzer` on the Recipe dataclass shape |

**Abort:** a real `AnalysisLog` fixture that can't round-trip → stop, return to R0.4, redesign.
"Every fixture" is an unenumerated set until pre-flight A5's `ecc:code-explorer` pass writes the
list into `plans/phase-1-7-provenance-dag.md`.

---

## Definition of Done + the single PR

| Slot | Resource |
|---|---|
| Linux job | built in pre-flight A3, not here |
| Test-file list | pinned in the Linux job (the "45 non-UI test files" is unverified today) |
| Whole-branch review | `superpowers:requesting-code-review` → `ecc:code-reviewer` (sonnet) + `ecc:architect` (opus), **by sub-step commit range**, not one 25-commit diff |
| Test dimension | `ecc:pr-test-analyzer` — genuine value at exactly this point |
| Comment sweep | `ecc:comment-analyzer` (haiku), batched once — targets: `uadas_core/ai/tool_registry.py:55` ("src.ui.dialogs…"), `docs/MYPY_DEBT.md:19`, `src/`-era language in `.claude/agents/*.md` |
| Docs | `milestone-doc-sync` + `ecc:doc-updater` → `docs/ARCHITECTURE.md`, `CLAUDE.md` |
| Completion gate | `milestone-verification` (primary) + `verify-and-stop` / `superpowers:verification-before-completion` (backstop) — not all three as separate passes |
| PR mechanics | `gh` (full path / PowerShell tool). A7 forbids rebase → the PR carries ~25 commits. Squash = an explicit, recorded A7 decision |
