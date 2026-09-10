# Phase 1 — whole-branch diagnosis (before the DoD + PR to main)

**Purpose:** pin-point and dig out any error / bug / gap accumulated across sub-steps 1.1–1.7
on `phase-1/extract-uadas-core` before the Definition-of-Done and the single PR to `main`.
Read-only specialist sweep → triage → fix → re-verify. Fires **after 1.7 lands and
`graphify update .` has run** (so the graph carries `uadas_core/provenance/`).

**Surface:** `32c45ec..phase-1/extract-uadas-core` — 53 commits + 1.7's ~8. Merge-base
`32c45ec`. Sub-step SHA ranges: see `.superpowers/sdd/phase-1/progress.md`.

## Sub-step boundaries (for scoping each agent)

| Sub-step | What changed | Highest-risk facet |
|---|---|---|
| 1.1 carve-out | ~112 `.py` moved `src/` → `uadas_core/`; import rewrites | a missed `from src.` import; a test that stopped covering moved code |
| 1.5 lift renderers | `src/ui/results/` → `uadas_core/results/` | same class of import/coverage gap |
| 1.2 JobRunner | new `uadas_core/jobs/` adapter; `WorkerSignals`/`BaseWorker` frozen | silent-failure in the adapter; a caching regression |
| 1.8 security ×4 | iteration-cap, zip-slip, injected-secrets, SQL-capability-refused | a fix that regressed or is bypassable |
| 1.3 de-globalize | 3 `_register_builtins()` moved import→`bootstrap()`; `_CHART_BUILDERS`/`_CHART_REGISTRY` → live fns | collection-time side-effects; a registry that double-registers |
| 1.4 typed resolve() | `resolve()` `@overload` pair; `src/app.py` drops 3 casts | overload-overlap; a resolve() call that now mis-types |
| 1.6 persistence | new `uadas_core/persistence/`; SQLite+Parquet; `DashboardTile.tile_id`; `load_snapshot`; `_warn_about_skipped_datasets` removed | SQL injection (B608 CI-OFF); path-traversal on `dataset_id`; atomicity; a dangling-ref that now raises |
| 1.7 provenance | new `uadas_core/provenance/`; `Explanation.from_dict`; `get_all_logs` | silent-failure in "synthesize `partial`, never raise"; `_creation_order` loop; `from_dict` tolerance vs data loss |

## Specialist batch — non-author, read-only (RESOURCE_ORCHESTRATION §1.4)

Every prompt: carries the sub-step table above + verified `file:line` anchors inline; ends with
*"report back caveman-compressed (`caveman` full): one line per finding — `file:line` · claim ·
fix. Group by sub-step. No prose."* (§1.7).

**Wave 1 (highest yield — fire together):**
1. `ecc:silent-failure-hunter` — swallowed errors / bad fallbacks / missing propagation across
   `uadas_core/jobs/`, `uadas_core/persistence/`, `uadas_core/provenance/`, and the 1.3 registry
   moves. The single highest-yield facet for hidden bugs.
2. `ecc:architect` (opus) — boundary integrity of `uadas_core/` as a Qt-free core: dependency
   directions (`lint-imports` passes, but does anything import *upward*?), `Base*` pattern
   adherence, the `bootstrap()` sequence with all of 1.2/1.3/1.6/1.7's registrations, the three
   separate cycle-checkers (1.6 ×2 + 1.7) staying consistent.
3. `security-reviewer` (repo) — 1.8's four fixes still intact + not bypassable; 1.6 SQL still
   `?`-parameterized end to end (B608 is CI-OFF — this pass is the only gate); `dataset_id`
   uuid4-validated before every path-join on **both** save and load; readers (moved in 1.1/1.5)
   — no path-traversal regression.
4. `test-engineer` — behaviour coverage vs line coverage: the A9 baseline deltas
   (`plans/phase-1-baseline.md`) — is any added test a tautology? are the 1.6 structural-failure
   paths and the 1.7 C-2 multi-log case actually asserted, not just imported?

**Wave 2 (after Wave 1 triage, or parallel if rate limits allow):**
5. `ecc:python-reviewer` — idiom / type-hints / PEP8 / obvious perf over the branch diff.
6. `ecc:type-design-analyzer` — 1.4 `resolve()` overloads + the new value dataclasses
   (`SaveReport`, `WorkspaceSnapshot`, `DashboardTile`, `DatasetMeta`, `Dag`, `Recipe`,
   `RecipeStep`) — invariants expressed in the type, or left to callers?
7. `code-reviewer` (repo, haiku) — general quality / regression over `32c45ec..HEAD`.

Drop `comment-analyzer` / `performance-analyzer` / `a11y-reviewer` — low yield here (no
data-volume or UI change; comment rot is not "a bug").

## Triage rubric

- **CRITICAL / HIGH** (wrong result, crash, security bypass, data loss) → fix on the branch now,
  TDD, before the DoD. Re-run the affected sub-step's tests + `pytest tests/<area>/`.
- **MEDIUM** (silent-failure that masks a real error, a missing structural check, a type hole) →
  fix if < ~30 min and localized; else log in §findings with a Phase-2 owner.
- **LOW** (doc / idiom / naming) → batch into one `chore(phase-1): diagnosis nits` commit, or
  defer.
- Every accepted finding gets a one-line §findings entry (id, sub-step, severity, verdict,
  fixing commit).

## Then

DoD (`plans/phase-1-derisking-and-readiness.md` Part E) → one PR `phase-1/extract-uadas-core →
main` (whole-branch review by sub-step commit range; A7 → ~60 commits ride; squash is an
explicit A7 decision) → flip `DCO_ENFORCING` to `"1"` at some Phase-1 commit.

## §findings

_(populated when the sweep runs)_
