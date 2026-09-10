# Phase 1.7 — Provenance DAG & Recipe Format

**Status:** R0.4 design doc · produced 2026-09-07 (repo `architect`) · **R0.4 sign-off 2026-09-08
by `ecc:architect` (opus, NOT the author — the prior "architect APPROVE" was self-review, an A3
violation): APPROVE-WITH-CHANGES.** The core shape (dataset-node / transform-edge / Recipe =
DAG-minus-data) is right and serves F2/F3. **Six changes below, two blocking.** 1.7 is last in
Part D order, so this did not block 1.3/1.4/1.6.

**2026-09-10 — the six §R0.4 changes folded into the body, then a second fold after the
`ecc:architect` (opus) re-check** (verdict: *shape sound, no model rework*; 5 local fixes):
the CHANGE 4 rationale + citations were wrong (`_summarize_result` normalizes `Dataset`/`Figure`
returns; the unsound path is `analysis_orchestrator_service.py:434`, not `tool_registry.py`);
§3.1's `null_counts` was still fabricated (real `profile_dataset` output has no such key); §4's
F10 row contradicted CHANGE 4; the §3.3 test can't sort by id after id-minting; edge/artifact
must key on one predicate (`"new_dataset_id" in outputs`), not on `stage`. All applied below.
The §R0.4 section is kept verbatim as the audit trail. **Implementation-ready** — proceed to the
C-2 prototype.

---

## §R0.4 sign-off — required changes (2026-09-08)

**BLOCKING 1 — the source is a *set* of logs, not one.** `AnalysisOrchestratorService._logs:
dict[str, AnalysisLog]` (`uadas_core/services/analysis_orchestrator_service.py:246`) — one log
**per dataset**. `run_stage` appends to the caller's `dataset_id` log (`:368,:395`); a CLEAN
entry lands in the **parent's** log with `new_dataset_id` in `outputs` (`:418-421`); work on
the derived dataset lands in the **derived** log. `reproduce()` switches `current_dataset_id`
after each CLEAN (`:488-489`). Persistence agrees: `project.contents["analysis_logs"]` is
`{dataset_id: log_dict}` (`project_service.py:352-353,:377`). **→ converter signature must be
`analysis_logs_to_dag(logs: Iterable[AnalysisLog], datasets: Mapping[str, DatasetMeta]) -> Dag`.**
An edge's `to_dataset_id` = `entry.outputs["new_dataset_id"]`; its `from_dataset_id` = the
**enclosing log's** `dataset_id` (not recoverable from the entry alone). C-2 must include ≥1
multi-log fixture or it proves nothing about the case that actually occurs.

**BLOCKING 2 — §3.1's "real payload" is fabricated.** It puts three entries under one
`dataset_id` where the third (`analyze`, `row_count: 3`) evidently ran against the *derived*
dataset — `run_stage` would have written that into the derived dataset's log. Replace with a
two-log payload (root `[understand, clean]`; derived `[analyze]`) or restore `row_count` to 5.
Shipping a hand-written payload into a design doc violates the living-truth discipline.

**CHANGE 3 — node-per-dataset can't serve F1** ("every dataset, transform, **test, chart and
forecast** is an inspectable node; click any node"). Under §1 a chart / t-test is an
*annotation* with no identity. Add a third element: an `artifact` node per non-CLEAN entry
hanging off its dataset node, carrying `{entry_index, stage, tool_name, timestamp}` + (VISUALIZE)
the `visualization_id` the orchestrator already emits (`:431`). ~15 lines, no Recipe impact.
Needed for F1 and F9 (comment-on-a-step).

**CHANGE 4 — DAG ≠ Recipe.** F1 wants "click a node → see the data as it was"; F10 says "the
server stores the DAG, never the data". Resolve: the **DAG retains `outputs` verbatim** (every
`tool_registry` handler returns a plain dict — `:121-123,:142-145,:158,:165`); only the
**Recipe** drops them. F10 then reads "server stores Recipe + DAG topology; result payloads and
data are client-side."

**CHANGE 5 — stale refs + a wrong rationale.** The field-source header (lines 10-12) cites
`src/services/…` / `src/analysis/…` — now `uadas_core/…`; `AnalysisLogEntry` is `:138-187`,
`AnalysisLog` `:190-225`. The `Unverified` bullet "all `outputs` JSON-serializable —
`_summarize_result` wraps non-dicts" has a wrong rationale: the fallback is
`return {"result": result}` (`:434`), which does not serialize an arbitrary object — it holds
only because every current handler already returns a dict. Add a `json.dumps(log.to_dict())`
assertion to C-2 so the claim is enforced.

**CHANGE 6 — `steps[].id` is positional (`"s1"`, `"s2"`).** F2 (re-point at next month's file)
and F9 (comments anchored to steps) need ids stable across re-export. Make it content-derived
(`hash(stage, tool_name, canonical inputs, ordinal)`) or write one line declaring positional
ids out of scope for 1.7.

**Confirmed as-is (no change):** `Explanation` / `AnalysisLogEntry` / `AnalysisLog` are all
plain `@dataclass` (value-based `__eq__`), so `Explanation(**e.to_dict()) == e` is a real proof;
`Explanation` has **no `from_dict`** (class body ends `explanation.py:93`) — 1.7 adding it is a
genuine gap. The §5 scope fence and the timestamp-validation fix are well drawn — keep verbatim.

---

## §C-2 fixture inventory (2026-09-08, `ecc:code-explorer`)

**No `@pytest.fixture` returns an `AnalysisLog`.** Every log in the suite is built inline via
`AnalysisLog(...)` / `AnalysisLogEntry(...)`, produced by `AnalysisOrchestratorService.run_stage`,
or written as a `to_dict()`-shaped dict. The C-2 "every fixture round-trips" target = the
log-shapes these tests build:

- **`tests/services/test_analysis_orchestrator_service.py`** — `::test_run_stage_understand…:66`
  (1 UNDERSTAND entry), `::…_clean…:85` (1 CLEAN, `outputs.new_dataset_id`), `::…_visualize…:103`
  (1 VISUALIZE), `::…_explain…:127` (1 EXPLAIN, `tool_name=None`, `Explanation` dict),
  `::test_propose_next_stage_reaches_report…:165` (7-entry multi-stage log incl. EXPLAIN
  `Explanation(what="done")`), `::test_reproduce_replays…:204` (2-entry UNDERSTAND+CLEAN then
  `reproduce()`), **`::test_analysis_log_round_trips_through_to_dict_from_dict:235`** (the
  existing dict round-trip test — 1-entry), `::test_load_log_installs_a_restored_log:249`.
- **`tests/services/test_project_service_analysis_log.py`** — `:16`, `:38` (empty), `:46` (real
  file save/reopen) — all `to_dict`-shaped dicts, `explanation: None`.
- **`tests/services/test_report_service.py`** — `:91`, `:117` — 2-entry logs with populated
  `Explanation`.
- **`tests/services/test_guidance_service.py`** — `:128` (≤8-entry loop), `:259` (5-entry) — log
  content not asserted.
- **`tests/ui/controllers/test_pipeline_controller.py`** — `:79`, `:109`, `:161` (persist only
  non-empty), `:181` (persist→restore), **`:218`** (real project-file round trip preserves the log).
- **`tests/ui/workbench/test_workbench.py`** — 7 tests build **empty** `AnalysisLog(dataset_id="d1")`.
- **`tests/ui/workbench/test_pages.py::test_report_page_update_log…:68`** — the one fully-populated
  `AnalysisLogEntry` built inline (all fields incl. an ISO `timestamp`).
- **`Explanation`-only:** `tests/ui/workbench/test_explain_page.py` (`:13`,`:22`),
  `tests/ui/results/test_explanation_panel.py` (`_make_explanation` helper `:26` = all 7 fields;
  `::test_every_level_has_at_least_one_expanded_field:97` parametrized over every `ExpertiseLevel`).

Canonical: `AnalysisLogEntry` `@dataclass` `uadas_core/services/analysis_orchestrator_service.py:138`
(`to_dict`:168, `from_dict`:179 — keeps `explanation` as a plain dict); `AnalysisLog` `:190`
(`to_dict`:214, `from_dict`:221); `Explanation` `@dataclass` `uadas_core/analysis/explanation.py:29`
(`to_dict`:76, **no `from_dict`**).

**Purpose.** Reshape the *set* of flat per-dataset `AnalysisLog`s into one lineage DAG, and
define a portable **Recipe** (the DAG minus the data) that replays on a fresh dataset. This is
the substrate Phase 5's transparency features (F1–F3, F10) build on. Additive: a new
`uadas_core/provenance/` package *alongside* `AnalysisOrchestratorService`, changing nothing for
existing callers.

Canonical field sources (current tree, verified 2026-09-10):
`AnalysisLogEntry` `@dataclass` `uadas_core/services/analysis_orchestrator_service.py:138`
(`to_dict` `:168`, `from_dict` `:179` — keeps `explanation` as a plain dict);
`AnalysisLog` `:190` (`to_dict` `:214`, `from_dict` `:221`);
`AnalysisOrchestratorService._logs: dict[str, AnalysisLog]` `:246`;
`Explanation` `@dataclass` `uadas_core/analysis/explanation.py:29` (`to_dict` `:76`,
**no `from_dict`** — class body ends `:93`; 1.7 adds it).

---

## 1. DAG model — three elements

```python
def analysis_logs_to_dag(
    logs: Iterable[AnalysisLog],
    datasets: Mapping[str, DatasetMeta],
) -> Dag: ...
```

**The source is a set of per-dataset logs, not one** (BLOCKING 1). `_logs: dict[str,
AnalysisLog]` (`analysis_orchestrator_service.py:246`) holds one log per dataset. A CLEAN entry
lands in the **parent** dataset's log with `outputs["new_dataset_id"]` set (`:418-421`); every
non-CLEAN entry, and all work on a derived dataset, lands in *that* dataset's log.
`reproduce()` switches `current_dataset_id` after each CLEAN (`:488-489`). Persistence agrees:
`project.contents["analysis_logs"]` is `{dataset_id: log_dict}` (`project_service.py`). So an
edge's `from_dataset_id` is the **enclosing log's** `dataset_id` — *not* recoverable from the
entry alone — and `to_dataset_id` is `entry.outputs["new_dataset_id"]`.

The DAG is a *view* over the logs, not a parallel source of truth.

| Element | Identity | Carries | Built from |
|---|---|---|---|
| **dataset node** | `dataset_id` | `name`, `row_count`, `column_count`, `source_format`, `parent_dataset_id` (root: `None`) | the `datasets` mapping — one `DatasetMeta` per id any log references |
| **transform edge** | `(from_dataset_id, to_dataset_id)` | `from_dataset_id` (enclosing log id), `to_dataset_id`, `tool_name`, `inputs` (tool kwargs), `stage` (`PipelineStage`), `explanation` (opt), `timestamp`, **`outputs` verbatim** | an entry with `"new_dataset_id" in entry.outputs` |
| **artifact node** | `(dataset_id, entry_index)` (positional — §5) | `stage`, `tool_name`, `timestamp`; `visualization_id = entry.outputs.get("visualization_id")` | an entry **without** `new_dataset_id` in `outputs` — hangs off its dataset node, no edge |

**One predicate, per entry** (opus fix): `"new_dataset_id" in entry.outputs` → transform edge;
else → artifact node. Keyed on `outputs`, **never on `stage`** — `run_stage` does not constrain
the stage↔tool pairing (the work is "entirely determined by `tool_name`"), so an ANALYZE entry
that ran a cleaning tool still yields an edge, and a CLEAN entry that ran `profile_dataset` is an
artifact. `_summarize_result` (`analysis_orchestrator_service.py:416-421`) is what puts
`new_dataset_id` there.

**Why the artifact node** (CHANGE 3): F1 wants "every dataset, transform, **test, chart and
forecast** … an inspectable node; click any node"; F9 wants comment-on-a-step. Without it a
t-test or a chart has no identity. ~15 lines, zero Recipe impact (the Recipe's `steps[]` already
enumerate non-edge operations).

**`outputs` retained in the DAG** (CHANGE 4, opus-corrected): `AnalysisLogEntry.outputs` is
already a JSON-friendly *summary* — `_summarize_result` (`analysis_orchestrator_service.py:404-434`)
normalizes a `Dataset` return to `{new_dataset_id, derivation_description}` (`:416-421`) and a
`go.Figure` to `{visualization_id}` (`:422-431`); a dict handler passes through (`:432-433`). The
**DAG is a client-side assembly** that keeps each edge's `outputs` verbatim, so a viewer can
inspect the transform's own result summary. The **Recipe** drops `outputs` (§2) — they are a
function of the data and `reproduce()` regenerates them on replay. Note: "see the data as it
was" (F1) comes from the **retained intermediate `Dataset`** (the non-mutating-Dataset rule, F3),
not from `outputs`.

**DAG vs Recipe on the server** (F10): the server stores the **Recipe** and the DAG
**topology** — nodes + edges *without* `outputs`; DataFrames and result payloads never leave the
browser. An unqualified "DAG with `outputs`" is a client-only object.

**Dangling reference** (mirrors `WorkspaceService.get_lineage` `:403-405` / the 1.6 cycle
checks): an edge `to`/`from` id, or a `parent_dataset_id`, absent from `datasets` → synthesize
the node `name=None`, `partial=True`; never raise. A cycle in the assembled
`{child: parent_dataset_id}` map **or** the edge `{to: from}` map → `ServiceError`
(loader-boundary only, same rule as 1.6). **When `DatasetMeta.parent_dataset_id` disagrees with
an edge's `from_dataset_id` for the same child, the edge wins** — `parent_dataset_id` is
metadata; the transform edge is the observed lineage.

---

## 2. Recipe format (DAG minus data)

Portable JSON: structure + operations + params, **no DataFrames and no `outputs`**, so it
replays on a new dataset with a compatible schema. The DAG keeps `outputs` (§1); the Recipe is
the only place they are dropped — `AnalysisOrchestratorService.reproduce()` regenerates them on
replay, and F10 keeps result payloads + data client-side.

`steps[].id` is **positional** (`"s1"`, `"s2"`) in 1.7. Content-derived ids (stable across
re-export, needed once Phase 3 stores step-anchored F9 comments server-side) are out of scope —
see §5.

```json
{
  "version": "1.0",
  "name": "Sales data cleaning",
  "description": "clean then profile",
  "source_dataset": {
    "name": "sales", "row_count": 5, "column_count": 2, "source_format": "csv",
    "schema": { "region": "object", "revenue": "float64" }
  },
  "steps": [
    { "id": "s1", "label": "Profile the dataset", "stage": "understand",
      "tool_name": "profile_dataset", "inputs": {}, "produces_dataset": false,
      "explanation": null, "timestamp": "2026-09-07T14:32:15Z" },
    { "id": "s2", "label": "Remove rows with missing values", "stage": "clean",
      "tool_name": "drop_missing_values", "inputs": {}, "produces_dataset": true,
      "explanation": null, "timestamp": "2026-09-07T14:32:20Z" }
  ]
}
```

| field | meaning |
|---|---|
| `version` | Recipe format version — allows later evolution without breaking old files |
| `source_dataset.schema` | `{col: str(df[col].dtype)}` — used on replay to check a new dataset has compatible columns (missing col → error if used; dtype change → warn, proceed) |
| `steps[].stage` | one of the `PipelineStage` StrEnum values ("understand"|"clean"|"explore"|"analyze"|"visualize"|"predict"|"explain") |
| `steps[].tool_name` | tool-registry name, or `null` for an EXPLAIN-only step |
| `steps[].inputs` | tool kwargs (must include any RNG seed — see scope fence) |
| `steps[].produces_dataset` | `true` for CLEAN-type steps that yield a derived dataset |
| `steps[].explanation` | serialized `Explanation` (`to_dict()` shape) or `null` |

---

## 3. Worked round-trip (the C-2 test — must pass on *every* real `AnalysisLog` fixture)

### 3.1 Real payload — a **two-log** set (BLOCKING 2)

`run_stage` writes the post-clean `profile_dataset` into the *derived* dataset's log, never the
parent's. So a realistic `_logs` snapshot after "profile → drop nulls → profile again" is two
logs, `[understand, clean]` on the root and `[analyze]` on the derived dataset:

`profile_dataset`'s real return (via `_summarize_result`'s dict passthrough) is
`{row_count, column_count, duplicate_row_count, ambiguous_type_columns, columns: [...]}` — **no
`null_counts` key** (an earlier draft invented one). A `drop_missing_values` CLEAN entry returns
a `Dataset`, which `_summarize_result` normalizes to `{new_dataset_id, derivation_description}`.

```json
{
  "550e8400-e29b-41d4-a716-446655440000": {
    "dataset_id": "550e8400-e29b-41d4-a716-446655440000",
    "entries": [
      { "stage": "understand", "tool_name": "profile_dataset", "inputs": {},
        "outputs": { "row_count": 5, "column_count": 2, "duplicate_row_count": 0,
                     "ambiguous_type_columns": [], "columns": ["region", "revenue"] },
        "explanation": null, "timestamp": "2026-09-07T14:32:15Z" },
      { "stage": "clean", "tool_name": "drop_missing_values", "inputs": {},
        "outputs": { "new_dataset_id": "d3a8f2c1-9e4b-4a7c-b1c2-3f5e7a9b2d1c",
                     "derivation_description": "Removed 2 rows with any null values" },
        "explanation": null, "timestamp": "2026-09-07T14:32:20Z" }
    ]
  },
  "d3a8f2c1-9e4b-4a7c-b1c2-3f5e7a9b2d1c": {
    "dataset_id": "d3a8f2c1-9e4b-4a7c-b1c2-3f5e7a9b2d1c",
    "entries": [
      { "stage": "analyze", "tool_name": "profile_dataset", "inputs": {},
        "outputs": { "row_count": 3, "column_count": 2, "duplicate_row_count": 0,
                     "ambiguous_type_columns": [], "columns": ["region", "revenue"] },
        "explanation": null, "timestamp": "2026-09-07T14:32:25Z" }
    ]
  }
}
```

`analysis_logs_to_dag` is fed **both** logs (plus a `datasets` mapping with a `DatasetMeta` for
each id). C-2 must include ≥1 multi-log fixture — a single-log input never exercises the
cross-log edge, which is the case that actually occurs. **The C-2 catalog builds these payloads
with real tool-output shapes, not hand-invented keys** (living-truth).

### 3.2 → DAG

- **dataset nodes:** `550e8400…` (5×2, root) ; `d3a8f2c1…` (3×2, `parent_dataset_id=550e8400…`)
- **transform edge:** `550e8400… → d3a8f2c1…` — `drop_missing_values`, stage `clean`, ts `…20Z`,
  `outputs={new_dataset_id, derivation_description}` retained verbatim
- **artifact nodes:** `(550e8400…, 0)` UNDERSTAND `profile_dataset` ; `(d3a8f2c1…, 0)` ANALYZE
  `profile_dataset` — one per entry without `new_dataset_id` in `outputs`, no edge

### 3.3 → Recipe → back to `AnalysisLog`

Compare in **creation order** (root chain first, then each derived log in the order its CLEAN
step produced it) — *not* an id sort: `recipe_to_analysis_logs` mints fresh derived ids, so the
ids differ by construction. Assert list lengths explicitly before zipping — a bare `zip`
silently truncates on a count mismatch.

```python
def test_every_analysis_log_fixture_round_trips_through_recipe():
    for logs in ALL_ANALYSIS_LOG_FIXTURES:               # each fixture = a set of logs (§R0.4 B1)
        recipe = analysis_logs_to_recipe(logs)
        logs2  = recipe_to_analysis_logs(recipe.to_dict(), new_root_dataset_id="new-root")

        e1 = [e for log in _creation_order(logs)  for e in log.entries]
        e2 = [e for log in _creation_order(logs2) for e in log.entries]
        assert len(e1) == len(e2)                          # never rely on zip() to catch this
        for a, b in zip(e1, e2):
            assert b.stage       == a.stage
            assert b.tool_name   == a.tool_name
            assert b.inputs      == a.inputs
            assert b.explanation == a.explanation          # plain dict, round-trips via JSON
            assert b.timestamp   == a.timestamp            # provenance-of-origin, not a replay clock
            # outputs (incl. new_dataset_id) are RE-DERIVED on replay — not compared
        assert json.dumps([log.to_dict() for log in logs2])   # CHANGE 5 — outputs JSON-serializable
```

`_creation_order(logs)` = the root log (its `dataset_id` never appears as a `new_dataset_id`),
then follow each CLEAN entry's `new_dataset_id` to the next log. For the empty fixture it is the
single empty log; for a forest (>1 root) it raises — out of 1.7 scope (§5).

**If any real fixture fails this, the Recipe shape is wrong — stop and return to R0.4.**
`outputs` is deliberately not preserved in the Recipe (it is a function of the data);
`AnalysisOrchestratorService.reproduce(dataset_id)` regenerates it on replay.

---

## 4. Feeds Phase 5

| Phase 5 feature | uses |
|---|---|
| **F1 Provenance graph** | DAG nodes/edges — click a node for its data/metadata, an edge for the transform |
| **F2 Replayable recipes** | Recipe (structure + ops, no data) → re-point at a new dataset → `reproduce()` |
| **F3 Time-travel & fork** | DAG + the non-mutating-Dataset rule — every intermediate dataset still exists, so a what-if can branch from any node |
| **F10 Local-first privacy** | server stores the **Recipe + DAG topology** (nodes + edges, *no* `outputs`, no data); DataFrames and result payloads stay in the browser (DuckDB-WASM + Pyodide execute the Recipe client-side) |

---

## 5. Scope fence — NOT in 1.7

DAG UI rendering (Phase 4/5) · branch / merge of recipes (linear only here) ·
non-deterministic tools (a recipe assumes `tool(df, **inputs)` is deterministic; RNG seed must
be *in* `inputs`) · partial replay / "from step N" · tool-version pinning · result caching on
replay · streaming outputs · **content-derived ids** — `steps[].id` (`"s1"`/`"s2"`) *and*
`ArtifactNode` identity (`(dataset_id, entry_index)`) are positional in 1.7; stable-across-
re-export ids for F9 server-side comment anchoring land with Phase 3 · **Recipe disk
persistence** (Phase 3 — see Multi-file touchpoints). Rejected in review if present.

---

## `## Unverified`

- **Every real `AnalysisLog` fixture round-trips** — this is the C-2 acceptance gate, not yet run.
- `Explanation` has `to_dict()` (`explanation.py:76-93`) but **no `from_dict()`** — 1.7 must add
  one and prove `Explanation(**e.to_dict()) == e`. Not covered by the current suite.
- `AnalysisLogEntry.timestamp` is written as `datetime.now(UTC).isoformat()` (~line 351) but
  not validated on `from_dict`; a non-ISO string would pass silently. 1.7 should validate.
- All entry `outputs` are JSON-serializable — `_summarize_result`
  (`analysis_orchestrator_service.py:404-434`) normalizes a `Dataset` return to
  `{new_dataset_id, derivation_description}` and a `go.Figure` to `{visualization_id}`; a dict
  handler passes through. The one unsound path is the `return {"result": result}` fallback at
  **`analysis_orchestrator_service.py:434`** — reached only if a future tool returns a value that
  is not a dict, a `Dataset`, or a `Figure`. C-2's `json.dumps(...)` assertion (§3.3) makes that
  trip the test instead of failing silently on Recipe export.
- `str(df[col].dtype)` for the schema map works for standard dtypes; pandas extension dtypes
  (`StringDtype`, `CategoricalDtype`) untested — implementation must degrade gracefully.
- Recipe `version` is fixed at `"1.0"`; no migration path defined (Phase 3 adds one).

---

## Multi-file touchpoints

- **new** `uadas_core/provenance/__init__.py` · `uadas_core/provenance/dag.py` (`Dag`,
  `DatasetMeta`, `analysis_logs_to_dag`) · `uadas_core/provenance/recipe.py` (`Recipe`,
  `analysis_logs_to_recipe`, `recipe_to_analysis_logs`).
- `uadas_core/analysis/explanation.py` — add `Explanation.from_dict()` + prove
  `Explanation(**e.to_dict()) == e`; validate a non-ISO `timestamp` is rejected on
  `AnalysisLogEntry.from_dict` (currently silent — §Unverified).
- `uadas_core/services/analysis_orchestrator_service.py` — no dataclass change. Adds
  `get_all_logs() -> list[AnalysisLog]` (**needed**, not optional): the converter already
  type-hints `AnalysisLog`, so `provenance/ → services/` is an unavoidable edge; `get_all_logs`
  returns no DAG type so it adds no *reverse* edge, and it beats callers reaching into `_logs`.
  Relocating the log dataclasses out of `services/` is the real dependency fix — out of 1.7.
- `tests/provenance/test_recipe.py` — C-2, every `AnalysisLog` shape in the suite (§C-2
  inventory), incl. ≥1 multi-log fixture and the `json.dumps` assertion.
- **Recipe disk persistence → deferred to Phase 3** (opus re-check). 1.7 ships
  `Recipe.to_dict()` / `from_dict()` + the `json.dumps` round-trip (C-2 §3.3 needs them). **No
  `project_service` change** — a Recipe is a pure function of the `AnalysisLog`s that 1.6
  already persists; a second stored copy is a stale-state hazard for zero gain.
- `steps[].timestamp` (and `TransformEdge.timestamp`) is **provenance-of-origin**, not an
  execution clock — a Recipe-reconstructed log handed to `reproduce()` must not read it as a
  replay time.
- **`outputs`-dropping round-trip is a documented behaviour choice** inside an otherwise
  additive step (pre-flight Part E item 11) — name it in the end-of-range review.

---

## §as-built (2026-09-10)

**Commits:** implementer Tasks 1–7 `8d7d63e`,`7458266`,`728db2e`,`3283d64`,`1bfcd53`,`5208d2a`
(worktree, off `3e53456`) → merge `c1a989a` → end-of-range review fixes `a3bed35`. Design/plan
commits: `e887136` (RESOURCE_ORCHESTRATION §1.7–1.8), `68bdecc` (this doc's two folds +
`phase-1-7-plan.md` + `phase-1-diagnosis.md`).

**Built:** `uadas_core/provenance/{__init__,dag,recipe}.py`; `Explanation.from_dict` +
round-trip proof; `AnalysisLogEntry.from_dict` ISO-8601 timestamp validation (CHANGE 5);
`AnalysisOrchestratorService.get_all_logs()`. `uadas_core/provenance` added to the CI mypy
clean list (150 → 153 files). `docs/ARCHITECTURE.md` gained a "Provenance DAG & Recipe"
subsection.

**End-of-range review** over `3e53456..5208d2a` (all non-author):

| Reviewer | Verdict | Actioned |
|---|---|---|
| `code-reviewer` (haiku) | APPROVE | — |
| `ecc:architect` (opus) | FIX-FIRST | B1, B2, item 5 + 5 tweaks — all in `a3bed35` |
| `ecc:silent-failure-hunter` | ISSUES-FOUND | 1 MED (= B1) + LOW hardening — the actionable ones in `a3bed35` |

**`a3bed35` — what the review changed:**

- **B1 (silent branch loss).** `_creation_order` silently kept only the *last* `new_dataset_id`
  when one log had >1 dataset-producing entry (a clean stage re-run with different params — a
  *reachable* fan-out the single-root guard missed), dropping the other branch's log from the
  Recipe with no error. Now raises `ServiceError` on any fan-out, and on
  `len(ordered) != len(logs)` after the walk (a disconnected / cyclic set). The spec §5 "linear
  chains only" fence is now actually enforced. +3 tests.
- **B2 (open-project regression).** 1.7's `AnalysisLogEntry.from_dict` timestamp raise reached
  the *unguarded* `PipelineController.restore_logs_for_project` restore loop
  (`project_controller.open_project_at_path`'s `try` covers only `open_project`), so a
  hand-edited / pre-1.7 project file with a non-ISO timestamp crashed the open instead of
  loading. Now the loop catches `ServiceError`, logs a warning, and skips that one log —
  matching the workspace model's "an orphaned reference is expected state, not corruption to
  guard against". +1 regression test.
- **CHANGE-5 gap.** `recipe_to_analysis_logs` builds `AnalysisLogEntry` *directly* from
  `RecipeStep`s (not via `AnalysisLogEntry.from_dict`), so a bad timestamp in a Recipe payload
  rode in unchecked. `RecipeStep.from_dict` now applies the same `fromisoformat` guard;
  `produces_dataset` is a required key. +2 tests.
- **Item 5.** `analysis_logs_to_recipe` built a whole throwaway `Dag` with `datasets={}` just to
  read `roots()[0].meta` — always `partial=True` all-`None`, so §2's populated `source_dataset`
  was unreachable, and `roots()[0]` was an unguarded index. Now takes an optional
  `datasets: Mapping[str, DatasetMeta] | None`, reads the root meta directly, and drops the DAG
  build. `source_dataset` carries a `partial` flag. +2 tests.
- **Tweaks:** `recipe_to_analysis_logs` wraps `PipelineStage(step.stage)` → `ServiceError` (was
  a bare `ValueError`); `_is_clean_entry` typed `AnalysisLogEntry`, not `Any`; a machine-checked
  `.importlinter` `provenance-is-a-leaf` `forbidden` contract (`core`/`analysis`/`services`/
  `persistence`/`jobs` → `uadas_core.provenance`) — `lint-imports` **2 kept, 0 broken**; `dag.py`
  docstring corrected: the three cycle-checkers are *deferred debt*, and
  `_reject_dataset_id_cycles(links: Mapping[str, str | None])` *is* the intended shared
  signature (`workspace_service` / `persistence_service` build that map inline).

**Verification:** full suite **1438 → 1523 / 92 / 0** (inv-2 exit `139` = post-clean Qt SIGSEGV,
CI-green-equivalent). Screenshot byte-identical (16,294 B). mypy CI list → Success (153 files).
`bandit uadas_core/provenance` exit 0. Branch CI: _pending push_.

**Deferred (recorded, not scheduled):**

- **Recipe disk persistence → Phase 3.** A Recipe is a pure function of the `AnalysisLog`s 1.6
  already persists; a second stored copy is a stale-state hazard. 1.7 ships the in-memory
  converters + `to_dict`/`from_dict` + the `json.dumps` round-trip only.
- **Unify the three cycle-checkers** into `uadas_core/core/validation.py` — the architect's
  post-1.6 deferral still stands; `links`-map form is the shared signature. Touches `services/` +
  `persistence/`, so it belongs in Phase 2's deletion/consolidation work, not an additive step.
- **`docs/ARCHITECTURE.md` "Module layout" diagram** still shows pre-1.1 `src/` paths and omits
  `persistence` / `jobs` / `results` / `provenance` (it lagged from 1.3–1.6 already) — a Phase-1
  DoD docs task, tracked in `plans/phase-1-diagnosis.md`.
- **`Recipe.from_dict` version/`steps` strictness** and **`fromisoformat` accepting naive /
  date-only** strings — LOW, revisit when Phase 3 adds Recipe versioning + disk persistence.
