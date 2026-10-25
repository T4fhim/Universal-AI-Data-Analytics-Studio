# Phase 2.2 — Extract `uadas_core/models/` (D1)

**Status:** READY 2026-09-11 · branch `phase-2/retire-desktop-ui` @ `8140f10` · authored per
`plans/phase-2-execution-playbook.md` §1 step 1 (JIT plan), spec = `plans/phase-2-structural-moves.md`
Ruling 1. Behaviour-frozen (A10, strained per Ruling-4-residual-risk-4: `Project`'s move + ~33
call-site rewrites were not in D1's original scope, still purely mechanical — flagged to the
reviewer up front, not scope creep).

Governing skill: `safe-refactor`. Writer: orchestrator (inline, not a worktree — R2.4 default;
the type partition is well-bounded and each step independently verifiable). Reviewer: repo
`code-reviewer` + `architect` (boundary ruling already done in R2.4; confirms the extraction
matches it) + `lint-imports`.

---

## Exact extraction (verified against the tree at `8140f10`, line numbers match Ruling 1 exactly)

| Symbol | From | Lines | To |
|---|---|---|---|
| `Dataset`, `Visualization`, `DashboardTile`, `Dashboard` | `uadas_core/services/workspace_service.py` | 39-212 (4 `@dataclass` blocks, contiguous) | `uadas_core/models/workspace.py` |
| `Project` (+ `to_json_dict`/`from_json_dict`) | `uadas_core/services/project_service.py` | 45-112 | `uadas_core/models/project.py` |

**Stay put (confirmed no runtime construction/isinstance elsewhere makes this unsafe):**
- `_reject_parent_cycles` (workspace_service.py:215-241) — `load_snapshot`'s policy, not a value
  type's shape; one caller, private.
- `WorkspaceService` / `ProjectService` classes themselves.
- `SaveReport`/`WorkspaceSnapshot` (persistence_service.py), `RecipeStep` (provenance/recipe.py).

**New-file imports** (verified: none of the 4 workspace types are constructed/isinstance-checked
within `WorkspaceService`'s own body — all 26 references there are type-hint-only, safe under
`from __future__ import annotations`; `Project` **is** constructed at runtime in `ProjectService`
— 16 real references, `from uadas_core.models import Project` there is load-bearing, not just typing):

- `uadas_core/models/workspace.py`: `from __future__ import annotations`; `uuid`;
  `dataclasses.{dataclass,field}`; `pathlib.Path`; `typing.TYPE_CHECKING`; `TYPE_CHECKING`-only
  `pandas as pd` / `plotly.graph_objects as go`. No `ServiceError`, no logger (unused by these 4
  classes).
- `uadas_core/models/project.py`: `from __future__ import annotations`;
  `dataclasses.{dataclass,field}`; `pathlib.Path`; `typing.Any`;
  `uadas_core.core.exceptions.ServiceError` (real — `from_json_dict` raises it).
- `uadas_core/models/__init__.py`: re-exports all 5 — `from uadas_core.models.project import
  Project` + `from uadas_core.models.workspace import Dashboard, DashboardTile, Dataset,
  Visualization`, `__all__` — **every call site imports `from uadas_core.models import X`**, never
  `...models.workspace`/`...models.project` (Ruling 1a: keeps a later file split invisible, one
  clean `X -> uadas_core.models` layers-contract edge).
- `workspace_service.py` gains `from uadas_core.models import Dashboard, DashboardTile, Dataset,
  Visualization` (mypy + `_reject_parent_cycles`'s annotation).
- `project_service.py` gains `from uadas_core.models import Project`.

## Import-site rewrite (104 lines across ~70 files touching workspace_service/project_service — verified, no `mock.patch`/qualified-runtime-call forms exist for any of the 5 symbols, only `from ... import ...` and `:class:`/`:attr:` doc-refs)

Three shapes, NOT a uniform find-replace (unlike 2.1 — symbols move to a *different* module than
their sibling class that stays):

1. **Pure-stay line** (`WorkspaceService`/`ProjectService` only) — untouched.
2. **Pure-move line** (single or multi name, all of {`Dataset`,`Visualization`,`Dashboard`,
   `DashboardTile`}/{`Project`}) — whole statement rewritten to `from uadas_core.models import
   <names>`.
3. **Mixed line/block** (e.g. `Dataset, WorkspaceService`; the `Dashboard, DashboardTile,
   Visualization, WorkspaceService` multi-line blocks in `visualization_controller.py`,
   `persistence_service.py`, `test_workspace_service.py`, `test_persistence_service.py`,
   `test_visualization_controller.py`, `assistant_service.py`, `analysis_orchestrator_service.py`)
   — split into a `from uadas_core.models import <moved>` line + a `from
   uadas_core.services.workspace_service import <stayed>` line (isort sorts them after).
4. **Doc-refs** (`:class:`/`:attr:` roles, ~35 lines) — literal dotted substitution:
   `uadas_core.services.workspace_service.{Dataset,Visualization,Dashboard,DashboardTile}` /
   `uadas_core.services.project_service.Project` -> `uadas_core.models.<name>` (`\b`-anchored so
   `Dashboard` doesn't eat `DashboardTile`, `Project` doesn't eat `ProjectService`).

**Codemod:** a small Python script (not sed — the split logic needs real parsing of the
comma-separated name list, single-line and parenthesized multi-line forms), run once over
`git ls-files '*.py'` in `src/ tests/ scripts/ uadas_core/`, doing (1) the doc-ref dotted
substitution pass first (reuses 2.1's `\b`-anchored sed approach), then (2) the import-statement
split pass. `isort`/`black` after, as in 2.1.

**Residual `assistant_service -> workspace_service` edge (Ruling 1b, predicted, confirmed by the
recon above: `assistant_service.py`'s block has `WorkspaceService` staying alongside `Dataset,
Visualization` moving):** left as-is in 2.2 — the `ignore_imports` line for it is written in 2.3
alongside the `layers` contract, not here. `tool_registry.py:50` (`Dataset`-only import) drops
its `workspace_service` edge entirely once rewritten to `models` — confirms Ruling 1b's "cycle
reduces to two edges" claim; verify with `graphify path` after.

---

## Per-commit gate

1. `python -m compileall uadas_core -q` -> 0; `python -c "import uadas_core; from uadas_core.models import Dataset, Visualization, Dashboard, DashboardTile, Project"` -> 0
2. `grep -rnE 'from uadas_core\.services\.(workspace_service|project_service) import' --include=*.py src/ tests/ scripts/ uadas_core/` — manually diff against the pre-recorded pure-stay list; every remaining line must import only `WorkspaceService`/`ProjectService` (plus each other in one file). `grep -rnE 'uadas_core\.services\.(workspace_service\.(Dataset|Visualization|Dashboard(Tile)?)|project_service\.Project)\b'` -> 0 (no stale doc-refs).
3. `lint-imports` -> **2 kept / 0 broken** AND `.importlinter` contract 2 (`provenance-is-a-leaf`) gains `uadas_core.models`.
4. `graphify path "uadas_core.ai.tool_registry" "uadas_core.services.workspace_service"` -> **no edge** (tool_registry now imports only `uadas_core.models`). The `assistant_service -> workspace_service` edge (for `WorkspaceService`) is expected to remain — not a failure.
5. Characterization: `bootstrap()` still resolves every registered service (existing `tests/core/test_startup_registry_characterization.py`) — no new test needed, this is exactly what that test already checks.
6. Full suite: **0 failed**, delta from the 2.1-end baseline (`1537/82/0`, collected 1619) explained *only* by the same three `src/ui/**`-glob tests if applicable to any touched `src/ui/` doc-ref file (unlikely here — 2.2 touches `uadas_core/`/`tests/`/a few `src/ui/*.py` doc-comments, not module locations) — expect **no collected-count change at all** this time (no file moves in/out of `src/ui/`, only new files added under `uadas_core/models/`, which the glob tests don't scan since `models/` isn't `src/ui/`). Any unexplained delta = abort.
7. `black --check` / `isort --check-only` / the `ci.yml` mypy list (+ `uadas_core/models`) / `bandit --skip B101,B107,B608` -> green.
8. Screenshot byte-identical (app still alive, A11 not yet in effect).

**Abort:** step 4 shows the edge survives -> re-read Ruling 1b, the fix is scoped to 2.3's
`ignore_imports`, not a 2.2 logic change. Any non-import line changing in `workspace_service.py`/
`project_service.py` beyond the extraction cut + the one new import line = reject (A10).

## Unverified (into execution)

- Exact `isort`/`black` reflow of the ~10 split-block files (mechanical, gate-checked).
- Whether `workspace_service.py`'s or `project_service.py`'s own **module docstring** references
  `Dataset`/`Project` in a way needing a dotted-path fix (bare `:class:`Dataset`` same-module
  refs become cross-module after the move) — checked at exec time alongside the extraction.
