# Phase 1.7 — Provenance DAG & Recipe Format

**Status:** R0.4 design doc · produced 2026-09-07 (architect) · **needs `architect` sign-off against the Phase 5 feature list before any 1.7 code** (Gate verdict).

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
