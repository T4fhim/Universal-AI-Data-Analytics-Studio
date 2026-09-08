# Phase 1.7 — Provenance DAG & Recipe Format

**Status:** R0.4 design doc · produced 2026-09-07 (repo `architect`) · **R0.4 sign-off 2026-09-08
by `ecc:architect` (opus, NOT the author — the prior "architect APPROVE" was self-review, an A3
violation): APPROVE-WITH-CHANGES.** The core shape (dataset-node / transform-edge / Recipe =
DAG-minus-data) is right and serves F2/F3. **Six changes below, two blocking, must land in this
doc before the C-2 prototype is written.** 1.7 is last in Part D order, so this does not block
1.3/1.4/1.6.

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

**Purpose.** Reshape the flat per-dataset `AnalysisLog` into a lineage DAG, and define a
portable **Recipe** (the DAG minus the data) that can be replayed on a fresh dataset. This is
the substrate Phase 5's transparency features (F1–F3, F10) build on. Additive: a layer
*alongside* `AnalysisOrchestratorService`, changing nothing for existing callers.

Field sources: `AnalysisLogEntry` `src/services/analysis_orchestrator_service.py:157-162`;
`AnalysisLog.to_dict()` / `from_dict()` around lines 170-214; `Explanation`
`src/analysis/explanation.py:76-93`.

---

## 1. DAG node / edge model

- **Node = a dataset** (`dataset_id`). Carries `name`, `row_count`, `column_count`,
  `source_format`, and `parent_dataset_id` (root node has none).
- **Edge = a transformation** that produced one dataset from another. Carries `from_dataset_id`,
  `to_dataset_id`, `tool_name`, `inputs` (the tool kwargs), `stage` (`PipelineStage`),
  `explanation` (optional), `timestamp`.

### Reshaping from `AnalysisLogEntry`

The DAG is a *view* of the log, not a parallel source of truth. Rule:

| Log entry | Becomes |
|---|---|
| entry whose `outputs` contains `new_dataset_id` (CLEAN-type) | an **edge** `parent → new_dataset_id` |
| entry with no `new_dataset_id` (UNDERSTAND / ANALYZE / VISUALIZE — statistics only) | an **annotation** on the current node, not an edge |

`AnalysisLogEntry.outputs` is a JSON-friendly summary (line 160, `dict[str, Any]`); for CLEAN
stages it carries `new_dataset_id` + `derivation_description` (matches
`Dataset.derivation_description`).

---

## 2. Recipe format (DAG minus data)

Portable JSON: structure + operations + params, **no DataFrames**, so it replays on a new
dataset with a compatible schema.

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

### 3.1 Real `AnalysisLog.to_dict()` payload (UNDERSTAND → CLEAN → ANALYZE)

```json
{
  "dataset_id": "550e8400-e29b-41d4-a716-446655440000",
  "entries": [
    { "stage": "understand", "tool_name": "profile_dataset", "inputs": {},
      "outputs": { "row_count": 5, "column_count": 2, "null_counts": {"region": 1, "revenue": 1} },
      "explanation": null, "timestamp": "2026-09-07T14:32:15Z" },
    { "stage": "clean", "tool_name": "drop_missing_values", "inputs": {},
      "outputs": { "new_dataset_id": "d3a8f2c1-9e4b-4a7c-b1c2-3f5e7a9b2d1c",
                   "derivation_description": "Removed 2 rows with any null values" },
      "explanation": null, "timestamp": "2026-09-07T14:32:20Z" },
    { "stage": "analyze", "tool_name": "profile_dataset", "inputs": {},
      "outputs": { "row_count": 3, "column_count": 2, "null_counts": {} },
      "explanation": null, "timestamp": "2026-09-07T14:32:25Z" }
  ]
}
```

### 3.2 → DAG

- nodes: `550e8400…` (5×2, root) ; `d3a8f2c1…` (3×2, parent = `550e8400…`)
- edges: `550e8400… → d3a8f2c1…` (`drop_missing_values`, stage `clean`, ts `…20Z`)
- the two `profile_dataset` entries → annotations on their respective nodes (no edge)

### 3.3 → Recipe → back to `AnalysisLog`

```python
def test_every_analysis_log_fixture_round_trips_through_recipe():
    for log in ALL_ANALYSIS_LOG_FIXTURES:                 # every fixture in the suite
        recipe = analysis_log_to_recipe(log)
        log2   = recipe_to_analysis_log(recipe.to_dict(), new_root_dataset_id="new-root")

        e1, e2 = log.to_dict()["entries"], log2.to_dict()["entries"]
        assert len(e1) == len(e2)
        for a, b in zip(e1, e2):
            assert b["stage"]       == a["stage"]
            assert b["tool_name"]   == a["tool_name"]
            assert b["inputs"]      == a["inputs"]
            assert b["explanation"] == a["explanation"]   # round-trips via JSON
            assert b["timestamp"]   == a["timestamp"]
            # outputs (incl. new_dataset_id) are RE-DERIVED on replay — not compared
```

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
| **F10 Local-first privacy** | server stores only Recipe/DAG; the data never leaves the browser (DuckDB-WASM + Pyodide execute the Recipe client-side) |

---

## 5. Scope fence — NOT in 1.7

DAG UI rendering (Phase 4/5) · branch / merge of recipes (linear only here) ·
non-deterministic tools (a recipe assumes `tool(df, **inputs)` is deterministic; RNG seed must
be *in* `inputs`) · partial replay / "from step N" · tool-version pinning · result caching on
replay · streaming outputs. Rejected in review if present.

---

## `## Unverified`

- **Every real `AnalysisLog` fixture round-trips** — this is the C-2 acceptance gate, not yet run.
- `Explanation` has `to_dict()` (`explanation.py:76-93`) but **no `from_dict()`** — 1.7 must add
  one and prove `Explanation(**e.to_dict()) == e`. Not covered by the current suite.
- `AnalysisLogEntry.timestamp` is written as `datetime.now(UTC).isoformat()` (~line 351) but
  not validated on `from_dict`; a non-ISO string would pass silently. 1.7 should validate.
- All tool `outputs` are JSON-serializable — true for current tools (`_summarize_result` wraps
  non-dicts), not formally enforced.
- `str(df[col].dtype)` for the schema map works for standard dtypes; pandas extension dtypes
  (`StringDtype`, `CategoricalDtype`) untested — implementation must degrade gracefully.
- Recipe `version` is fixed at `"1.0"`; no migration path defined (Phase 3 adds one).

---

## Multi-file touchpoints

`uadas_core/services/analysis_orchestrator_service.py` (add converter entry points, no
dataclass change) · `uadas_core/analysis/explanation.py` (add `from_dict()`) · **new**
`uadas_core/provenance/dag.py` + `uadas_core/provenance/recipe.py` ·
`tests/provenance/test_recipe.py` (C-2, every fixture) · `project_service` persists recipes
beside logs (1.6 owns AnalysisLog persistence; 1.7 adds Recipe export/import).
