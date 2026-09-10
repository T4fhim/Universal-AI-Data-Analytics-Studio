# Phase 2 — Structural Moves (R2.4 rulings)

**Status:** ACCEPTED 2026-09-10 · `ecc:architect` (opus) ruled, non-author (did not write the
Phase 2 plan triad) · verdict **READY-WITH-CHANGES** — the 4 changes below are folded into
`plans/phase-2-derisking-and-readiness.md` Part C/D. Reviewed by repo `code-reviewer` before 2.1.

Companion to `plans/phase-2-derisking-and-readiness.md` (R2.4) and `-execution-playbook.md`.
This file is the authoritative spec for sub-steps **2.2** (`uadas_core/models/`) and **2.3**
(`bootstrap.py` + the `layers` contract).

---

## Ruling 1 — `uadas_core/models/` (D1)

### 1a — symbol set + layout

| Move | To | Notes |
|---|---|---|
| `Dataset` (`workspace_service.py:40`), `Visualization` (:124), `DashboardTile` (:169), `Dashboard` (:191) | `uadas_core/models/workspace.py` | one file — `Dashboard` holds `list[DashboardTile]`; these are one concept (~175 lines w/ docstrings). Three files = pure intra-package churn. |
| **`Project`** (`project_service.py:46`) | `uadas_core/models/project.py` | **NOT in D1's original scope — required.** `core/application_state.py:49` imports `Project` from `project_service` under `TYPE_CHECKING`; import-linter counts `TYPE_CHECKING` edges (2.15 has no `exclude_type_checking_imports`), so if `Project` stays, `core -> services` survives and `core` cannot be the bottom layer of contract 3. Same shape as the others (plain dataclass + `from_json_dict` classmethod raising `ServiceError`). |
| `models/__init__.py` | re-exports all 5 | Every call site imports `from uadas_core.models import Dataset` — **not** `...models.workspace` — so a later file split stays invisible to all ~33 importers and the layers contract gets one clean `X -> uadas_core.models` edge. |
| `_reject_parent_cycles` (`workspace_service.py:215`) | **stays** in `workspace_service.py` | It is `load_snapshot`'s load-boundary *policy*, not the value types' *shape*; private, one caller. |
| `SaveReport` / `WorkspaceSnapshot` (`persistence_service.py:136/152`), `RecipeStep` (`provenance/recipe.py:69`) | **stay put** | persistence- / provenance-specific. Confirmed. |

### 1b — the `services <-> ai` cycle does NOT fully break (as predicted)

Post-extraction the loop reduces to **two module edges**:
`uadas_core/ai/assistant_service.py:33 -> uadas_core.services.workspace_service` (for
`WorkspaceService` only — `Dataset`/`Visualization` leave) and
`uadas_core/services/analysis_orchestrator_service.py:35 -> uadas_core.ai.tool_registry`.
`tool_registry.py:50` drops out entirely (imports only `Dataset`).

- **`TYPE_CHECKING` guard does NOT help** — `import-linter==2.15` + vendored `grimp` build the
  graph from the AST; a `TYPE_CHECKING` import is a real contract edge (zero matches for
  `exclude_type_checking_imports` in `.venv/.../{importlinter,grimp}`).
- **Removing `get_tool_by_name` is out of scope** — it's a runtime call at
  `analysis_orchestrator_service.py:427`; severing it needs an injected tool-resolver = a logic
  change, which **A10** forbids in 2.2/2.3.
- **Fix = ONE documented `ignore_imports` line** for
  `uadas_core.ai.assistant_service -> uadas_core.services.workspace_service`. `AssistantService`
  uses `WorkspaceService` *only* as a constructor annotation (`assistant_service.py:150,178`) —
  no `isinstance`, no classmethod call — so the edge is genuinely thin and naming it is honest.
  **Follow-up (2.7 / Phase 3 scope — file it now):** replace the annotation with a `Protocol`
  and delete the ignore line.

### 1c — `models/` and pandas/plotly

**Keep both `TYPE_CHECKING`-only, verbatim from `workspace_service.py:32-34`.** The fields
(`dataframe: pd.DataFrame` :103, `figure: go.Figure` :162) are real runtime objects, but the
module never imports the libraries (`from __future__ import annotations` at :22 defers the
annotations). Carrying that keeps `models` a true leaf whose only edge is
`uadas_core.core.exceptions`. Preserve the `:52-59` docstring explaining the choice.

---

## Ruling 2 — `bootstrap.py` -> `uadas_core/bootstrap.py` (D2)

**Sound. Move it.** It is load-bearing for contract 3: while `bootstrap.py` lives in `core/` and
imports `cleaning`/`jobs`/`results`/`visualization`/`persistence`/`plugins` + 6 `services`
modules (`bootstrap.py:42-64`), `uadas_core.core` sits at the top *and* bottom of the graph and
no total order exists. Moving it out makes `core` an actual leaf.

- Verified: **no `uadas_core/` module imports `bootstrap`** (only docstring `:mod:` refs). Real
  importers: `src/app.py:26`, `src/ui/main_window.py:78` (both die in 2.5),
  `tests/core/test_bootstrap.py`, `tests/core/test_startup_registry_characterization.py`
  (survive). Plus whatever Phase 3's headless entry point becomes.
- **`uadas_core/__init__.py` must stay import-free** (currently 7 lines, docstring only).
  Re-exporting `bootstrap()` there would make `import uadas_core` pull in every service/plugin/
  chart registry and create a root `uadas_core -> uadas_core.services` edge.
- **Drive-by:** `uadas_core/core/__init__.py:1` still reads `# File: src/__init__.py` — a stale
  Phase-1.1 carve-out header. Fix in 2.3 while touching this package; a repo-wide `# File:`
  header sweep is cheap in 2.8.

---

## Ruling 3 — the `layers` contract (contract 3)

The Phase-2-plan candidate order was wrong in two places: **`provenance` must be at the TOP**
(`provenance/recipe.py:46`, `dag.py:48` import `services.analysis_orchestrator_service`), and
the "flat 12-module sibling tier" is not flat (`plugins -> {cleaning,readers,visualization}`;
`results -> {analysis,forecasting,visualization}`; `visualization -> {analysis,readers,forecasting}`;
`analysis -> readers.type_inference`). `persistence` imports only `core` + `workspace_service`
(->`models`) + `visualization.chart_registry`.

### Exact stanza (add to `.importlinter` in 2.3, same commit as the `bootstrap.py` move)

```ini
# Phase 2.3: the uadas_core dependency stack, top (imported by nobody) to
# bottom (imports nothing else in uadas_core). A module may import any layer
# below it, never one above. `|` marks independent siblings -- they may not
# import each other either.
[importlinter:contract:uadas-core-layers]
name = uadas_core subpackages form a strict dependency stack
type = layers
layers =
    uadas_core.bootstrap | uadas_core.provenance
    uadas_core.persistence
    uadas_core.services
    uadas_core.ai
    uadas_core.plugins
    uadas_core.results
    uadas_core.visualization
    uadas_core.analysis
    uadas_core.cleaning | uadas_core.forecasting | uadas_core.database | uadas_core.reports | uadas_core.jobs
    uadas_core.readers
    uadas_core.models | uadas_core.theme | uadas_core.help
    uadas_core.core
ignore_imports =
    # The one surviving strand of the old services<->ai cycle (Phase 1
    # diagnosis D1). AssistantService takes WorkspaceService purely as a
    # constructor annotation (assistant_service.py:150,178) -- no runtime
    # use -- but import-linter counts TYPE_CHECKING imports, so guarding it
    # would not help. Remove this line when the annotation becomes a
    # Protocol (tracked for 2.7 / Phase 3).
    uadas_core.ai.assistant_service -> uadas_core.services.workspace_service
```

- **Do NOT add `exclude_type_checking_imports`** — confirmed not a recognised key in 2.15.
- `uadas_core.theme` / `uadas_core.help` are placeholders for 2.1's lifted modules (verified
  they import only `uadas_core.core.*` today). 2.3 **re-runs `lint-imports` and adjusts tier
  placement** against whatever 2.1 actually created — do not paste blindly; if a lifted module
  imports more than `core`, raise it a tier.
- **Full `layers` beats a partial contract** here — the full stack costs exactly one `ignore`
  (well under a 20-ignore bar) and locks the `plugins`/`results`/`visualization` ordering that
  is currently unprotected.
- **Keep contract 2** (`provenance-is-a-leaf`) — partly redundant once `provenance` is a top
  layer, but explicit, and it covers modules the `layers` contract does not enumerate.

---

## Ruling 4 — Part D order

**No dependency error. Order holds as locked.**

- **2.1 <-> 2.2 are mutually independent** — nothing in `uadas_core/` imports `src.*` (zero
  matches for `^\s*(from|import)\s+src[.\s]` across `uadas_core/`); the D5 modules import only
  `uadas_core.core.*` (one-directional). Keeping 2.1 first is fine.
- **2.1 before 2.3 IS required** — 2.3 writes the `layers` stanza; if 2.1 ran after, the lifted
  packages land unenumerated and the contract needs a same-phase amendment.
- **2.2 before 2.3 IS required** (already locked) — the contract can't bottom out at `core`
  until `models/` exists.
- **New checklist item for 2.1 AND 2.2:** each must also extend contract 2's hand-enumerated
  `source_modules` list (`.importlinter:33-46`) with the new subpackages. A missing entry there
  is a **silent** enforcement gap, not a CI failure. Add a comment in `.importlinter` saying so.

---

## Residual risks (from R2.4)

1. The `assistant_service -> workspace_service` `ignore_imports` is permanent unless the
   `Protocol` follow-up is actually filed — **it is written into 2.7's scope now**, not "later".
2. `.importlinter` contract 2's hand-enumerated `source_modules` is a known silent-gap
   generator — 2.1/2.2/2.3 each re-check it.
3. The stanza is written against `8ab95f6`; 2.1's lifted-module names are guesses — 2.3 re-runs
   `lint-imports` and adjusts, doesn't paste blindly.
4. **A10 is strained by 2.2**: `Project`'s move wasn't in D1's scope and ~33 call sites change
   import lines. Still mechanical — flag to the 2.2 reviewer up front so it isn't read as scope
   creep.
5. `uadas_core/core/__init__.py:1` stale `# File:` header ⇒ the Phase-1.1 carve-out left >=1
   header unaudited; repo-wide `# File:` sweep in 2.8.
