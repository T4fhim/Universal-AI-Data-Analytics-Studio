# Phase 1.7 — Provenance DAG & Recipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` or
> `superpowers:executing-plans`, task-by-task. Steps use `- [ ]`. **Abortable sub-step**
> (pre-flight A5): hit a wall → stop and report, do **not** force past it, do **not** rebase the
> worktree.

**Goal:** Add a Qt-free `uadas_core/provenance/` package that reshapes the *set* of per-dataset
`AnalysisLog`s into a lineage DAG and a portable Recipe (the DAG minus the data), proven by a
C-2 round-trip test over every `AnalysisLog` shape the suite builds.

**Architecture:** A new package *alongside* `AnalysisOrchestratorService`, purely additive.
`dag.py` = the DAG value types + `analysis_logs_to_dag`; `recipe.py` = `Recipe` +
`analysis_logs_to_recipe` / `recipe_to_analysis_logs`. `Explanation` gains `from_dict`;
`AnalysisLogEntry.from_dict` gains ISO-timestamp validation; `AnalysisOrchestratorService` gains
one `get_all_logs()` accessor. No existing dataclass changes shape.

**Tech Stack:** Python 3.13, stdlib `dataclasses` + `json` + `datetime` + `uuid`, `pytest`. **No
new runtime dependencies.**

**Spec:** `plans/phase-1-7-provenance-dag.md` — the R0.4 sign-off + the two 2026-09-10 folds
(the second after the `ecc:architect` opus re-check: *shape sound, no model rework*). Read it
with this plan.

## Global Constraints

- New module: `# File: <path>` line 1, then `from __future__ import annotations`, then a
  why-this-exists / how-it-relates-to-neighbours docstring (`CLAUDE.md` convention).
- `uadas_core/` stays Qt-free: `.venv/Scripts/lint-imports.exe` → **`1 kept, 0 broken`** after
  every task adding a module. `provenance/` may import `uadas_core.services` /
  `uadas_core.analysis` / `uadas_core.core`; **`services/` must never import `provenance/`**.
- **Additive only.** The single documented behaviour choice: a Recipe round-trip **drops
  `outputs`** (a function of the data; `reproduce()` regenerates them) — pre-flight Part E item
  11; name it in the end-of-range review.
- `mypy`: add `uadas_core/provenance` to the CI `mypy (clean packages)` `run:` list in Task 7
  (only once it is already clean).
- Full suite = the two-invocation command in `CLAUDE.md`, `QT_QPA_PLATFORM=offscreen`. A
  non-zero exit (`0xC0000005` / `139`) on **invocation 2** *after* a clean pytest result is the
  Windows/Qt-teardown SIGSEGV — **CI-green-equivalent** under `Max(exit1, exit2)`.
- Baseline **before** 1.7: **1438 passed / 92 skipped / 0 failed** (`plans/phase-1-baseline.md`).
  Any delta beyond the tests a task adds = regression, stop.
- `screenshot_app_state.py` stays byte-identical to `plans/baseline-app.png` (16,294 bytes).
- Commits: `feat(phase-1.7): …` / `test(phase-1.7): …` / `docs(phase-1.7): …`; every message
  ends with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- `quality-check.ps1` (PostToolUse) auto-runs `isort`→`black`→`ruff check --fix` on every `.py`
  Edit — do **not** re-run them by hand; **add an import and its first use in the same edit** or
  the hook strips the import (observation 0021).

## Verified anchors (current tree, 2026-09-10)

| Symbol | Location | Shape |
|---|---|---|
| `Explanation` | `uadas_core/analysis/explanation.py:29` | `@dataclass`; `what/why_it_matters/how_calculated/confidence_or_uncertainty: str=""`; `assumptions/limitations/alternative_approaches: list[str]=field(default_factory=list)`; `to_dict` `:76`; **no `from_dict`** (body ends `:93`) |
| `AnalysisLogEntry` | `uadas_core/services/analysis_orchestrator_service.py:138` | `@dataclass`; `stage: PipelineStage`, `tool_name: str\|None`, `inputs: dict`, `outputs: dict`, `explanation: dict\|None`, `timestamp: str`; `to_dict` `:168`, `from_dict` `:179` |
| `AnalysisLog` | `…:190` | `@dataclass`; `dataset_id: str`, `entries: list[AnalysisLogEntry]`; `to_dict` `:214`, `from_dict` `:221`; `completed_stages()` `:211` |
| `AnalysisOrchestratorService._logs` | `…:246` | `dict[str, AnalysisLog]`; `get_log` `:248`, `load_log` `:252`, `reproduce` `:436` |
| CLEAN marker (the ONE predicate) | `_summarize_result` `…:416-421`; `reproduce` `:488` | `"new_dataset_id" in entry.outputs`. Never key on `stage`. |
| `_summarize_result` | `…:404-434` | `Dataset`→`{new_dataset_id, derivation_description}` (`:416-421`); `go.Figure`→`{visualization_id}` (`:422-431`); dict→passthrough (`:432-433`); else `{"result": result}` (`:434` — the one unsound path) |
| EXPLAIN entry | `…:360-367` | `tool_name=None`, `inputs={}`, `outputs={}`, `explanation=<dict>` |
| `profile_dataset` real output | (via dict passthrough) | `{row_count, column_count, duplicate_row_count, ambiguous_type_columns, columns:[...]}` — **no `null_counts`** |
| `PipelineStage` | StrEnum | `understand \| clean \| explore \| analyze \| visualize \| predict \| explain` |
| `Dataset` lineage | `uadas_core/services/workspace_service.py:109-111` | `dataset_id`, `parent_dataset_id: str\|None`, `derivation_description: str\|None` |
| dangling-parent handling to mirror | `workspace_service.get_lineage:403-405`; `_reject_parent_cycles:215` | walk stops (no raise) on a dangling `parent_dataset_id`; cycle check is loader-boundary only |
| `ServiceError` | `uadas_core/core/exceptions.py` | already imported in `analysis_orchestrator_service.py` |

## Scope decisions (confirmed by the opus re-check, 2026-09-10)

1. **Recipe disk persistence → Phase 3.** 1.7 = in-memory converters + `Recipe.to_dict()` /
   `from_dict()` + `json.dumps` round-trip (C-2 needs them). **No `project_service` change.**
2. **Artifact-node identity** = `(dataset_id, entry_index)`; positional, like `steps[].id`
   (spec §5). `timestamp` rides as data.
3. **`get_all_logs() -> list[AnalysisLog]`** is added — needed, not optional (the converter
   type-hints `AnalysisLog`; the accessor adds no *reverse* dependency edge).
4. **Linear chains only** (spec §5). `recipe_to_analysis_logs` rebuilds a root→derived→derived
   chain; a forest (>1 root) raises; branching is out of scope, no test.
5. **One predicate everywhere:** `"new_dataset_id" in entry.outputs` → transform edge; else →
   artifact node. Keyed on `outputs`, never `stage`.
6. **Edge wins over metadata:** if `DatasetMeta.parent_dataset_id` disagrees with an edge's
   `from_dataset_id` for the same child, the edge is authoritative.

## File Structure

- **Create** `uadas_core/provenance/__init__.py` — marker + why-docstring; re-exports the public
  names.
- **Create** `uadas_core/provenance/dag.py` — `DatasetMeta` (frozen), `DatasetNode`,
  `TransformEdge`, `ArtifactNode`, `Dag`; `analysis_logs_to_dag(logs, datasets) -> Dag`; helpers
  `_is_clean_entry`, `_reject_dataset_id_cycles` (loader-boundary, dangling-tolerant — a
  deliberate sibling of `workspace_service._reject_parent_cycles` and
  `persistence_service._reject_parent_dataset_id_cycles`; cross-reference all three in the
  docstring, **do not cross-import**).
- **Create** `uadas_core/provenance/recipe.py` — `RecipeStep`, `Recipe` (`to_dict`/`from_dict`);
  `analysis_logs_to_recipe(logs) -> Recipe`; `recipe_to_analysis_logs(data, *,
  new_root_dataset_id) -> list[AnalysisLog]`; helper `_creation_order(logs) -> list[AnalysisLog]`.
  Imports `dag.py`.
- **Modify** `uadas_core/analysis/explanation.py` — `Explanation.from_dict`.
- **Modify** `uadas_core/services/analysis_orchestrator_service.py` — `get_all_logs`; ISO
  validation in `AnalysisLogEntry.from_dict`.
- **Create** `tests/provenance/__init__.py`, `tests/provenance/conftest.py`,
  `tests/provenance/test_dag.py`, `tests/provenance/test_recipe.py`.
- **Modify** the `Explanation` test file (confirm path: `git ls-files 'tests/**explanation*'`).
- **Modify** `.github/workflows/ci.yml` (mypy list), `docs/ARCHITECTURE.md`.
- **Modify** (Task 8) `plans/phase-1-baseline.md`, `.superpowers/sdd/phase-1/progress.md`,
  `plans/phase-1-7-provenance-dag.md` (`## §as-built`).

---

## Task 1: `Explanation.from_dict()` + round-trip proof

**Files:** modify `uadas_core/analysis/explanation.py` (classmethod after `to_dict`, `:93`);
test in the `Explanation` test file.

**Produces:** `Explanation.from_dict(data: dict[str, Any]) -> Explanation` — missing keys →
field default; list fields coerced with `list(...)`; unknown keys ignored.
`Explanation.from_dict(e.to_dict()) == e` for all `e`.

- [ ] **Step 1 — failing test**

```python
from uadas_core.analysis.explanation import Explanation

def test_explanation_round_trips_through_from_dict():
    e = Explanation(
        what="Revenue rose 12% QoQ", why_it_matters="Confirms the pricing change landed",
        how_calculated="Percent change of period totals",
        confidence_or_uncertainty="n=2 periods; directional only",
        assumptions=["periods are comparable length"],
        limitations=["does not isolate pricing from seasonality"],
        alternative_approaches=["fit a trend model over more periods"],
    )
    assert Explanation.from_dict(e.to_dict()) == e

def test_explanation_from_dict_tolerates_missing_keys():
    assert Explanation.from_dict({"what": "just a mean"}) == Explanation(what="just a mean")

def test_explanation_from_dict_ignores_unknown_keys():
    assert Explanation.from_dict({"what": "x", "legacy": 1}) == Explanation(what="x")
```

- [ ] **Step 2 — run, verify fail** — `AttributeError: … has no attribute 'from_dict'`.
- [ ] **Step 3 — implement**

```python
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Explanation:
        """Rebuild an :class:`Explanation` from its :meth:`to_dict` form.

        Inverse of :meth:`to_dict`. Missing keys fall back to the field
        default (every field is independently optional — see the class
        docstring); list fields are copied defensively; unknown keys are
        ignored so a payload from a newer version still loads. Added in
        web-transition 1.7 (:mod:`uadas_core.provenance`) so a serialized
        ``Explanation`` inside an ``AnalysisLogEntry`` or a Recipe step
        reconstructs, rather than being carried as an opaque dict.
        """
        return cls(
            what=data.get("what", ""),
            why_it_matters=data.get("why_it_matters", ""),
            how_calculated=data.get("how_calculated", ""),
            confidence_or_uncertainty=data.get("confidence_or_uncertainty", ""),
            assumptions=list(data.get("assumptions", [])),
            limitations=list(data.get("limitations", [])),
            alternative_approaches=list(data.get("alternative_approaches", [])),
        )
```

- [ ] **Step 4 — run tests** → 3 pass.
- [ ] **Step 5 — commit** `feat(phase-1.7): add Explanation.from_dict() with round-trip proof`

---

## Task 2: ISO-timestamp validation + `get_all_logs()`

**Files:** modify `uadas_core/services/analysis_orchestrator_service.py` (`from_dict` `:179`;
method by `get_log` `:248`); test `tests/services/test_analysis_orchestrator_service.py`.

**Produces:** `AnalysisLogEntry.from_dict` raises `ServiceError` when `timestamp` is not
`datetime.datetime.fromisoformat`-parseable (accepts trailing `Z` on 3.11+); valid unchanged.
`AnalysisOrchestratorService.get_all_logs() -> list[AnalysisLog]` = `list(self._logs.values())`.

- [ ] **Step 1 — failing tests**

```python
import pytest
from uadas_core.core.exceptions import ServiceError
from uadas_core.services.analysis_orchestrator_service import AnalysisLogEntry

def test_from_dict_rejects_a_non_iso_timestamp():
    bad = {"stage": "understand", "tool_name": "profile_dataset", "inputs": {},
           "outputs": {}, "explanation": None, "timestamp": "last Tuesday"}
    with pytest.raises(ServiceError, match="timestamp"):
        AnalysisLogEntry.from_dict(bad)

def test_from_dict_accepts_a_trailing_z_timestamp():
    ok = {"stage": "understand", "tool_name": "profile_dataset", "inputs": {},
          "outputs": {}, "explanation": None, "timestamp": "2026-09-07T14:32:15Z"}
    assert AnalysisLogEntry.from_dict(ok).timestamp == "2026-09-07T14:32:15Z"

def test_get_all_logs_returns_every_dataset_log(workspace_service):
    from uadas_core.services.analysis_orchestrator_service import AnalysisOrchestratorService
    svc = AnalysisOrchestratorService(workspace_service)
    svc.get_log("root"); svc.get_log("derived")
    assert {l.dataset_id for l in svc.get_all_logs()} == {"root", "derived"}
```

(Use whatever `workspace_service` fixture the file already has; if none, pass a minimal stub —
`get_all_logs` only touches `_logs`.)

- [ ] **Step 2 — run, verify fail.**
- [ ] **Step 3 — implement**

```python
# in AnalysisLogEntry.from_dict, before constructing:
        timestamp = data["timestamp"]
        try:
            datetime.datetime.fromisoformat(timestamp)
        except (TypeError, ValueError) as exc:
            raise ServiceError(
                f"AnalysisLogEntry.timestamp is not an ISO-8601 string: {timestamp!r}"
            ) from exc
        return cls(
            stage=PipelineStage(data["stage"]),
            tool_name=data.get("tool_name"),
            inputs=dict(data.get("inputs", {})),
            outputs=dict(data.get("outputs", {})),
            explanation=data.get("explanation"),
            timestamp=timestamp,
        )
```

```python
# on AnalysisOrchestratorService, right after get_log():
    def get_all_logs(self) -> list[AnalysisLog]:
        """Every dataset's log, insertion order — the read seam :mod:`uadas_core.provenance` uses.

        A CLEAN stage records its entry in the *parent* dataset's log with
        ``new_dataset_id`` in ``outputs``; work on the derived dataset lands
        in that dataset's own log (see :class:`AnalysisLog`). Rebuilding a
        lineage DAG needs the whole set, not one log. Added in
        web-transition 1.7 so ``provenance`` never touches ``self._logs``.
        """
        return list(self._logs.values())
```

- [ ] **Step 4 — run tests** (incl. the existing `::test_analysis_log_round_trips_through_to_dict_from_dict:235` — must still pass).
- [ ] **Step 5 — commit** `feat(phase-1.7): validate AnalysisLogEntry timestamp + add get_all_logs()`

---

## Task 3: `tests/provenance/conftest.py` — the C-2 fixture catalog

**Files:** create `tests/provenance/__init__.py` (empty), `tests/provenance/conftest.py`.

**Produces:** `ALL_ANALYSIS_LOG_FIXTURES: list[list[AnalysisLog]]` (each element = a *set* of
logs), covering the §C-2 inventory: 1-UNDERSTAND; 1-CLEAN; 1-VISUALIZE; 1-EXPLAIN
(`tool_name=None`, populated `Explanation` dict); a 7-entry single log; a **two-log set** (root
`[understand, clean]`, derived `[analyze]` — spec §3.1, **real `profile_dataset` output keys**);
an **empty** `AnalysisLog(dataset_id="d1")`; a fully-populated single entry. Plus
`datasets_for(logs) -> dict[str, DatasetMeta]` and `_creation_order(logs) -> list[AnalysisLog]`
helpers, and a parametrized `analysis_log_set` fixture.

- [ ] **Step 1 — write the module** (test infra — exercised by Tasks 4/6). Use real
  `AnalysisLogEntry(...)` values, ISO timestamps, and the verified `profile_dataset` shape:

```python
from __future__ import annotations
import pytest
from uadas_core.provenance.dag import DatasetMeta
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisLog, AnalysisLogEntry, PipelineStage,
)

_TS = "2026-09-07T14:32:{:02d}Z".format
_PROFILE = {"row_count": 5, "column_count": 2, "duplicate_row_count": 0,
            "ambiguous_type_columns": [], "columns": ["region", "revenue"]}

def _e(stage, tool, *, outputs=None, explanation=None, i=0, inputs=None):
    return AnalysisLogEntry(PipelineStage(stage), tool, inputs or {}, outputs or {},
                            explanation, _TS(i))

def _two_log_set():
    root = AnalysisLog("550e8400-e29b-41d4-a716-446655440000", [
        _e("understand", "profile_dataset", outputs=dict(_PROFILE), i=15),
        _e("clean", "drop_missing_values",
           outputs={"new_dataset_id": "d3a8f2c1-9e4b-4a7c-b1c2-3f5e7a9b2d1c",
                    "derivation_description": "Removed 2 rows with any null values"}, i=20),
    ])
    derived = AnalysisLog("d3a8f2c1-9e4b-4a7c-b1c2-3f5e7a9b2d1c", [
        _e("analyze", "profile_dataset",
           outputs={**_PROFILE, "row_count": 3}, i=25),
    ])
    return [root, derived]

# _single_understand / _single_clean / _single_visualize (outputs={"visualization_id": "v1"}) /
# _single_explain (tool_name=None, explanation=Explanation(what="done").to_dict()) /
# _seven_stage (understand,clean,analyze,visualize,explain,understand,analyze on the two ids) /
# _empty() -> [AnalysisLog("d1")] / _fully_populated() (all entry fields + populated Explanation)
# — one function each, real values.

ALL_ANALYSIS_LOG_FIXTURES: list[list[AnalysisLog]] = [
    _single_understand(), _single_clean(), _single_visualize(), _single_explain(),
    _seven_stage(), _two_log_set(), _empty(), _fully_populated(),
]

def datasets_for(logs):
    ids = set()
    for log in logs:
        ids.add(log.dataset_id)
        for e in log.entries:
            if "new_dataset_id" in e.outputs:
                ids.add(e.outputs["new_dataset_id"])
    return {i: DatasetMeta(i, f"ds-{i[:8]}", 5, 2, "csv", parent_dataset_id=None) for i in ids}

def _creation_order(logs):
    produced = {e.outputs["new_dataset_id"]
                for l in logs for e in l.entries if "new_dataset_id" in e.outputs}
    roots = [l for l in logs if l.dataset_id not in produced]
    if len(roots) != 1:
        raise AssertionError(f"expected 1 root log, found {len(roots)}")
    by_id = {l.dataset_id: l for l in logs}
    ordered, cur, seen = [], roots[0], set()
    while cur is not None and cur.dataset_id not in seen:
        seen.add(cur.dataset_id); ordered.append(cur); nxt = None
        for e in cur.entries:
            if "new_dataset_id" in e.outputs:
                nxt = by_id.get(e.outputs["new_dataset_id"])
        cur = nxt
    return ordered

@pytest.fixture(params=ALL_ANALYSIS_LOG_FIXTURES,
                ids=lambda f: f"{len(f)}log-{sum(len(l.entries) for l in f)}entry")
def analysis_log_set(request):
    return request.param
```

- [ ] **Step 2 — order note:** `conftest` imports `uadas_core.provenance.dag`, so **Task 4
  lands first (or in the same commit)**. Kept separate here for reviewability only.
- [ ] **Step 3 — commit** with Task 4.

---

## Task 4: `uadas_core/provenance/dag.py` + `analysis_logs_to_dag`

**Files:** create `uadas_core/provenance/__init__.py`, `uadas_core/provenance/dag.py`; test
`tests/provenance/test_dag.py`.

**Consumes:** `AnalysisLog`, `AnalysisLogEntry`, `PipelineStage`
(`uadas_core.services.analysis_orchestrator_service`); `ServiceError`
(`uadas_core.core.exceptions`).

**Produces:**
- `DatasetMeta` — `@dataclass(frozen=True)`: `dataset_id: str`, `name: str | None`,
  `row_count: int | None`, `column_count: int | None`, `source_format: str | None`,
  `parent_dataset_id: str | None`, `partial: bool = False`.
- `DatasetNode` — `dataset_id: str`, `meta: DatasetMeta`.
- `TransformEdge` — `from_dataset_id: str`, `to_dataset_id: str`, `tool_name: str | None`,
  `inputs: dict[str, Any]`, `stage: str`, `explanation: dict[str, Any] | None`,
  `timestamp: str`, `outputs: dict[str, Any]`.
- `ArtifactNode` — `dataset_id: str`, `entry_index: int`, `stage: str`,
  `tool_name: str | None`, `timestamp: str`, `visualization_id: str | None`.
- `Dag` — `@dataclass`: `nodes: list[DatasetNode]`, `edges: list[TransformEdge]`,
  `artifacts: list[ArtifactNode]`; `roots() -> list[DatasetNode]` (nodes whose
  `meta.parent_dataset_id` is `None` or not a node id, AND that are not an edge `to`).
- `analysis_logs_to_dag(logs: Iterable[AnalysisLog], datasets: Mapping[str, DatasetMeta]) -> Dag`.

**Reshape rules (spec §1):**
1. One `DatasetNode` per id that is a log key **or** an edge `to`/`from`. `meta = datasets[id]`;
   if absent → `DatasetMeta(id, None, None, None, None, None, partial=True)` — **never raise**.
2. Per entry: `_is_clean_entry(e)` = `"new_dataset_id" in e.outputs`.
   - clean → `TransformEdge(from_dataset_id=<enclosing log>.dataset_id,
     to_dataset_id=e.outputs["new_dataset_id"], …, outputs=dict(e.outputs))` (verbatim).
   - not clean → `ArtifactNode(log.dataset_id, index, e.stage.value, e.tool_name, e.timestamp,
     e.outputs.get("visualization_id"))`.
3. Build `links = {child: parent}` from **both** `{node_id: meta.parent_dataset_id}` and
   `{edge.to_dataset_id: edge.from_dataset_id}` (the edge value wins on conflict). Run
   `_reject_dataset_id_cycles(links)` — per-start visited-set walk, dangling = clean stop,
   repeat-visit → `ServiceError(f"parent_dataset_id cycle: {' -> '.join(path)}")`. Copy the
   shape from `workspace_service._reject_parent_cycles:215`; **do not import it**.

- [ ] **Step 1 — `__init__.py` + failing `test_dag.py`**

```python
# uadas_core/provenance/__init__.py
# File: uadas_core/provenance/__init__.py
"""Lineage DAG + portable Recipe over the orchestrator's per-dataset AnalysisLogs.

Web-transition 1.7. A read-only *view* beside
:class:`~uadas_core.services.analysis_orchestrator_service.AnalysisOrchestratorService`:
:func:`~uadas_core.provenance.dag.analysis_logs_to_dag` reshapes the *set* of
per-dataset logs into dataset-node / transform-edge / artifact-node form, and
:mod:`~uadas_core.provenance.recipe` strips it to a data-free Recipe that replays
on a fresh dataset. Nothing here mutates orchestrator state or imports Qt.
"""
from __future__ import annotations

from uadas_core.provenance.dag import (
    ArtifactNode, Dag, DatasetMeta, DatasetNode, TransformEdge, analysis_logs_to_dag,
)

__all__ = [
    "ArtifactNode", "Dag", "DatasetMeta", "DatasetNode", "TransformEdge", "analysis_logs_to_dag",
]
```

```python
# tests/provenance/test_dag.py
import pytest
from uadas_core.core.exceptions import ServiceError
from uadas_core.provenance.dag import DatasetMeta, analysis_logs_to_dag
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisLog, AnalysisLogEntry, PipelineStage,
)
from tests.provenance.conftest import datasets_for


def test_nodes_cover_every_mentioned_dataset_id(analysis_log_set):
    dag = analysis_logs_to_dag(analysis_log_set, datasets_for(analysis_log_set))
    mentioned = {l.dataset_id for l in analysis_log_set} | {
        e.outputs["new_dataset_id"]
        for l in analysis_log_set for e in l.entries if "new_dataset_id" in e.outputs
    }
    assert {n.dataset_id for n in dag.nodes} == mentioned


def test_one_edge_per_clean_entry_from_the_enclosing_log(analysis_log_set):
    dag = analysis_logs_to_dag(analysis_log_set, datasets_for(analysis_log_set))
    expected = {(l.dataset_id, e.outputs["new_dataset_id"])
                for l in analysis_log_set for e in l.entries if "new_dataset_id" in e.outputs}
    assert {(e.from_dataset_id, e.to_dataset_id) for e in dag.edges} == expected


def test_every_non_clean_entry_is_an_artifact_node(analysis_log_set):
    dag = analysis_logs_to_dag(analysis_log_set, datasets_for(analysis_log_set))
    expected = {(l.dataset_id, i)
                for l in analysis_log_set for i, e in enumerate(l.entries)
                if "new_dataset_id" not in e.outputs}
    assert {(a.dataset_id, a.entry_index) for a in dag.artifacts} == expected


def test_missing_meta_is_synthesized_partial_not_raised():
    log = AnalysisLog("root", [AnalysisLogEntry(
        PipelineStage.CLEAN, "drop_missing_values", {},
        {"new_dataset_id": "child", "derivation_description": "x"}, None,
        "2026-09-07T14:32:20Z")])
    dag = analysis_logs_to_dag([log], {})
    assert {n.dataset_id for n in dag.nodes} == {"root", "child"}
    assert all(n.meta.partial for n in dag.nodes)


def test_a_dataset_id_cycle_raises_serviceerror():
    metas = {"a": DatasetMeta("a", "a", 1, 1, "csv", "b"),
             "b": DatasetMeta("b", "b", 1, 1, "csv", "a")}
    with pytest.raises(ServiceError, match="cycle"):
        analysis_logs_to_dag([AnalysisLog("a"), AnalysisLog("b")], metas)


def test_stage_is_never_the_edge_predicate():
    # ANALYZE entry that produced a dataset -> still an edge
    log = AnalysisLog("root", [AnalysisLogEntry(
        PipelineStage.ANALYZE, "drop_duplicates", {},
        {"new_dataset_id": "child", "derivation_description": "x"}, None,
        "2026-09-07T14:32:20Z")])
    dag = analysis_logs_to_dag([log], {})
    assert len(dag.edges) == 1 and not dag.artifacts
```

- [ ] **Step 2 — run, verify fail** (`ModuleNotFoundError: uadas_core.provenance.dag`).
- [ ] **Step 3 — implement `dag.py`** per Interfaces + reshape rules. `# File:` header +
  why-docstring cross-referencing `AnalysisLog`, `workspace_service._reject_parent_cycles`,
  `persistence_service._reject_parent_dataset_id_cycles`.
- [ ] **Step 4 — run** `pytest tests/provenance/ -q` → PASS; `.venv/Scripts/lint-imports.exe` →
  `1 kept, 0 broken`; `python -m mypy uadas_core/provenance --ignore-missing-imports
  --follow-imports=silent` → clean.
- [ ] **Step 5 — commit** (with Task 3 files)
  `feat(phase-1.7): analysis_logs_to_dag — dataset/transform/artifact DAG over the log set`

---

## Task 5: `uadas_core/provenance/recipe.py` — `Recipe` + `analysis_logs_to_recipe`

**Files:** create `uadas_core/provenance/recipe.py`; modify `__init__.py`; test
`tests/provenance/test_recipe.py`.

**Consumes:** `analysis_logs_to_dag` / DAG types (`.dag`); `AnalysisLog` types.

**Produces:**
- `RecipeStep` — `@dataclass`: `id: str` (`"s1"`,`"s2"`,…, positional), `label: str`,
  `stage: str`, `tool_name: str | None`, `inputs: dict[str, Any]`, `produces_dataset: bool`,
  `explanation: dict[str, Any] | None`, `timestamp: str`. **No `outputs` field.**
- `Recipe` — `@dataclass`: `version: str = "1.0"`, `name: str = ""`, `description: str = ""`,
  `source_dataset: dict[str, Any] = field(default_factory=dict)`,
  `steps: list[RecipeStep] = field(default_factory=list)`; `to_dict()`; `from_dict(data)`.
- `analysis_logs_to_recipe(logs, *, name="", description="") -> Recipe` — flatten via
  `_creation_order`, one `RecipeStep` per entry, `produces_dataset = "new_dataset_id" in
  entry.outputs`, `label` from a small static `(stage, tool_name)` map (fallback
  `f"{stage}: {tool_name}"`). `source_dataset` = `{name,row_count,column_count,source_format}`
  of the root's `DatasetMeta` + `"schema": {}` (schema left `{}` — needs a live dataset, out of
  scope; documented).
- `_creation_order(logs)` — as in the conftest helper (root = id never a `new_dataset_id`;
  follow each CLEAN's `new_dataset_id`; >1 root → `ServiceError`).

- [ ] **Step 1 — failing tests**

```python
from uadas_core.provenance.recipe import Recipe, RecipeStep, analysis_logs_to_recipe

def test_step_count_equals_total_entries(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    assert len(r.steps) == sum(len(l.entries) for l in analysis_log_set)

def test_ids_are_positional_and_outputs_absent(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    assert [s.id for s in r.steps] == [f"s{i+1}" for i in range(len(r.steps))]
    assert all("outputs" not in d for d in r.to_dict()["steps"])
    assert not any(f.name == "outputs" for f in RecipeStep.__dataclass_fields__.values())

def test_recipe_dict_round_trips(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    assert Recipe.from_dict(r.to_dict()).to_dict() == r.to_dict()

def test_clean_steps_marked_produces_dataset(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    n = sum(1 for l in analysis_log_set for e in l.entries if "new_dataset_id" in e.outputs)
    assert sum(1 for s in r.steps if s.produces_dataset) == n
```

- [ ] **Step 2 — run, verify fail.**
- [ ] **Step 3 — implement `recipe.py`.** `# File:` header + why-docstring cross-referencing
  `dag.py` + spec §2. Note in the docstring: `timestamp` is provenance-of-origin, not a replay
  clock.
- [ ] **Step 4 — run** `pytest tests/provenance/ -q` PASS; `lint-imports` clean; `mypy` clean.
- [ ] **Step 5 — commit**
  `feat(phase-1.7): Recipe value type + analysis_logs_to_recipe (DAG minus data)`

---

## Task 6: `recipe_to_analysis_logs` + the C-2 every-fixture round-trip (acceptance gate)

**Files:** modify `recipe.py`, `__init__.py`; test `tests/provenance/test_recipe.py`.

**Produces:** `recipe_to_analysis_logs(data: dict[str, Any], *, new_root_dataset_id: str) ->
list[AnalysisLog]` — walk `steps` in order; start a log for `new_root_dataset_id`; each
`produces_dataset` step appends its entry to the *current* log, sets that entry's `outputs` to
`{"new_dataset_id": <minted uuid4>}`, and starts a new derived log (`dataset_id = <minted
uuid4>`); non-producing steps get `outputs={}`; `explanation` restored as the plain dict;
`timestamp` copied. Empty `steps` → `[AnalysisLog(dataset_id=new_root_dataset_id)]`.

- [ ] **Step 1 — the gate test** (spec §3.3, creation-order, explicit length assert):

```python
import json
from uadas_core.provenance.recipe import analysis_logs_to_recipe, recipe_to_analysis_logs
from tests.provenance.conftest import _creation_order

def test_every_analysis_log_fixture_round_trips_through_recipe(analysis_log_set):
    recipe = analysis_logs_to_recipe(analysis_log_set)
    logs2 = recipe_to_analysis_logs(recipe.to_dict(), new_root_dataset_id="new-root")

    e1 = [e for l in _creation_order(analysis_log_set) for e in l.entries]
    e2 = [e for l in _creation_order(logs2) for e in l.entries]
    assert len(e1) == len(e2)                       # never rely on zip() to catch this
    for a, b in zip(e1, e2):
        assert b.stage == a.stage
        assert b.tool_name == a.tool_name
        assert b.inputs == a.inputs
        assert b.explanation == a.explanation       # plain dict, round-trips via JSON
        assert b.timestamp == a.timestamp
        # outputs (incl. new_dataset_id) RE-DERIVED on replay — not compared
    assert json.dumps([l.to_dict() for l in logs2])  # CHANGE 5 — outputs JSON-serializable
```

- [ ] **Step 2 — run, verify fail** (undefined; then mismatches on the empty + two-log
  fixtures drive the impl).
- [ ] **Step 3 — implement** `recipe_to_analysis_logs` (+ re-export). Handle empty `steps` and
  the single-CLEAN → two-log case explicitly.
- [ ] **Step 4 — full provenance suite** `pytest tests/provenance/ -q` → all PASS incl. the
  8-fixture parametrized gate; `lint-imports` clean; `mypy uadas_core/provenance` clean.
- [ ] **Step 5 — commit**
  `feat(phase-1.7): recipe_to_analysis_logs + C-2 round-trip over every fixture`

---

## Task 7: CI mypy scope + docs + import-linter proof

**Files:** modify `.github/workflows/ci.yml`, `docs/ARCHITECTURE.md`.

- [ ] **Step 1** — append `uadas_core/provenance` to the `python -m mypy <list>
  --ignore-missing-imports --follow-imports=silent` line in the `mypy (clean packages)` step
  (the same list 1.4 added `src/app.py` to and 1.6 added `uadas_core/persistence` to). Keep
  alphabetical if it is.
- [ ] **Step 2** — run that exact command locally with the new entry → `Success`; record the
  file-count in the commit body.
- [ ] **Step 3** — `docs/ARCHITECTURE.md`: a "Provenance DAG & Recipe" subsection near the
  workspace-model section — `uadas_core/provenance/` is a read-only view over the orchestrator's
  log set; the three DAG elements; Recipe = DAG minus `outputs` minus data; Recipe *persistence*
  is Phase 3. One paragraph + 3 bullets.
- [ ] **Step 4** — `.venv/Scripts/lint-imports.exe` → `1 kept, 0 broken`.
- [ ] **Step 5 — commit**
  `docs(phase-1.7): add uadas_core/provenance to CI mypy scope + ARCHITECTURE note`

---

## Task 8: End-of-range review, verification, ledgers, land it  *(Part B — orchestrator-run, inline)*

Not a subagent task. The orchestrator runs this against the worktree's reported commit range
before merge.

- [ ] **Step 1** — full suite, both invocations, `QT_QPA_PLATFORM=offscreen`
  (`tests/ui/test_worker_runner.py` first, then the rest). Expect **1438 + N passed / 92
  skipped / 0 failed**; record N and its breakdown (Explanation 3 · orchestrator 3 · test_dag
  6 tests × 8-fixture params where parametrized · test_recipe ~4 + the 8-fixture gate). Inv-2
  exit `139`/`0xC0000005` after a clean result = CI-green-equivalent.
- [ ] **Step 2** — `screenshot_app_state.py --output <tmp>.png` → byte-identical to
  `plans/baseline-app.png` (16,294 bytes).
- [ ] **Step 3** — `bandit -r src uadas_core -q --skip B101,B107,B608` → exit 0. `provenance/`
  is pure transform, no SQL / no filesystem — a directed `security-reviewer` pass is **not**
  required (unlike 1.6); note that in the review record.
- [ ] **Step 4** — end-of-range review over the Task 1–7 range, non-author agents, **one
  parallel batch** (RESOURCE_ORCHESTRATION §1.4). Each prompt ends with the caveman-compressed
  return instruction (§1.7):
  - `ecc:architect` (opus) — `provenance/ → services/` dependency direction; view-not-source-
    of-truth; DAG/Recipe vs Phase 5 F1–F3/F10; the folded design doc matches the code.
  - `ecc:silent-failure-hunter` — the "synthesize `partial`, never raise" paths;
    `_creation_order` / `_reject_dataset_id_cycles` loop guards; `from_dict` tolerance vs
    silent data loss; the `zip` in the gate test.
  - `code-reviewer` (haiku) — whole range, quality / regression.
  Apply must-fix findings; re-run `pytest tests/provenance/ -q` after.
- [ ] **Step 5 — ledgers**
  - `plans/phase-1-baseline.md` — "Post-1.7" entry: 1438 → 1438+N, breakdown, 0 other delta,
    screenshot byte-identical, mypy list +`uadas_core/provenance`, lint-imports `1 kept / 0
    broken`.
  - `.superpowers/sdd/phase-1/progress.md` — `1.7` `[x]` + commit range + review verdicts;
    you-are-here → "Phase 1 DoD".
  - `plans/phase-1-7-provenance-dag.md` — append `## §as-built` (commit range, the 3 review
    verdicts, mypy count delta, deferred item: Recipe disk persistence → Phase 3).
- [ ] **Step 6 — land** — push the worktree branch; merge into `phase-1/extract-uadas-core` (no
  rebase — A7); push. CI: `gh run list --branch phase-1/extract-uadas-core` →
  `gh run view <id>` — `test` / `lint` / `linux_import` / `uia_integration` green (`dco`
  skipped).
- [ ] **Step 7** — `graphify update .` (AST-only, 0 tokens) so the graph carries
  `uadas_core/provenance/` for the Phase-1 diagnosis that follows.

---

## Self-Review (against the spec + the opus re-check)

1. **Spec coverage** — §1 three-element DAG + one predicate → Task 4. §2 Recipe / positional
   ids / drop `outputs` → Task 5. §3 C-2 every-fixture round-trip (creation-order, `len` assert)
   → Task 6. §R0.4 BLOCKING 1 (multi-log converter) → Task 4 signature + Task 3 two-log fixture.
   BLOCKING 2 (real payload) → Task 3 `_PROFILE`. CHANGE 3 (artifact node) → Task 4. CHANGE 4
   (`outputs` in DAG not Recipe) → Tasks 4/5. CHANGE 5 (`json.dumps` + timestamp validation) →
   Tasks 6/2. CHANGE 6 (positional ids) → Task 5 + spec §5. Opus fixes: predicate on `outputs`
   not `stage` → Task 4 `test_stage_is_never_the_edge_predicate`; edge-wins precedence → Task 4
   rule 3; creation-order test → Task 6; Recipe persistence deferred → Task 8 + spec. **All
   covered.**
2. **Placeholder scan** — every code step has real code or a named exact transform. The `label`
   map and `_seven_stage` / `_fully_populated` bodies are described by their field lists, not
   shown in full — implementer fills them. No "add error handling" hand-waves.
3. **Type consistency** — `analysis_logs_to_dag(logs, datasets)` identical in spec §1, Task 4,
   the conftest helper. `DatasetMeta` field list identical in Tasks 3 and 4.
   `recipe_to_analysis_logs(data, *, new_root_dataset_id=…)` identical in spec §3.3 and Task 6.
   `"new_dataset_id" in entry.outputs` is the one CLEAN predicate everywhere.

## Execution handoff

**Subagent-driven** — `implementer` in a `superpowers:using-git-worktrees` worktree off
`phase-1/extract-uadas-core`, Tasks 1–7, one commit per task (Tasks 3+4 share a commit). The
`implementer` has no `Task`/`Skill` tool (observation 0024) — it runs no per-commit reviewer
itself; it reports the SHAs and the orchestrator runs `code-reviewer` over the range in Task 8.
Task 8 is orchestrator-only. Abort = stop and report; never rebase the worktree.
