// File: apps/web/src/pipeline.ts
// The 10-stage guided-analysis IA, ported verbatim from the desktop backend:
//   src/services/analysis_orchestrator_service.py
//     - PipelineStage (StrEnum): UPLOAD -> ... -> REPRODUCE
//     - _AUTO_PROPOSED_STAGES: the 7 stages the orchestrator auto-proposes
//     - _STAGE_RATIONALE: the why-this-stage copy shown to the user
// This survives the desktop->web move untouched (it already lives outside
// src/ui/). The web API in Phase 3 exposes one router per stage, mirroring
// this same enum so the information architecture does not change.

export type StageId =
  | "upload"
  | "understand"
  | "clean"
  | "explore"
  | "analyze"
  | "visualize"
  | "predict"
  | "explain"
  | "report"
  | "reproduce";

export interface Stage {
  id: StageId;
  label: string;
  /** _STAGE_RATIONALE[stage] from the backend, verbatim. Empty for the
   *  entry/terminal stages the backend does not auto-propose. */
  rationale: string;
  /** true when the stage is in _AUTO_PROPOSED_STAGES. */
  autoProposed: boolean;
}

export const STAGES: Stage[] = [
  {
    id: "upload",
    label: "Upload",
    rationale: "",
    autoProposed: false,
  },
  {
    id: "understand",
    label: "Understand",
    rationale:
      "Profile the dataset first — row/column counts, missing values, and types — before deciding what cleaning or analysis makes sense.",
    autoProposed: true,
  },
  {
    id: "clean",
    label: "Clean",
    rationale:
      "Address data-quality issues found during UNDERSTAND (missing values, duplicates, ambiguous types) before analyzing, so results aren't skewed by fixable problems.",
    autoProposed: true,
  },
  {
    id: "explore",
    label: "Explore",
    rationale:
      "Look at relationships between columns (crosstabs, grouped aggregates) before committing to a specific statistical test.",
    autoProposed: true,
  },
  {
    id: "analyze",
    label: "Analyze",
    rationale:
      "Run a targeted statistical analysis (e.g. correlation) now that the data is understood and cleaned.",
    autoProposed: true,
  },
  {
    id: "visualize",
    label: "Visualize",
    rationale:
      "Build a chart of the analysis result — a visual is often clearer than a table of numbers for spotting what the analysis found.",
    autoProposed: true,
  },
  {
    id: "predict",
    label: "Predict",
    rationale:
      "If the dataset has a time dimension, forecast it — the orchestrator runs every applicable model and picks the best one by holdout accuracy (Automatic Model Competition).",
    autoProposed: true,
  },
  {
    id: "explain",
    label: "Explain",
    rationale:
      "Every prior stage's result should be interpreted in plain language before reporting — this is the AI's role: interpret, not invent new numbers.",
    autoProposed: true,
  },
  {
    id: "report",
    label: "Report",
    rationale: "",
    autoProposed: false,
  },
  {
    id: "reproduce",
    label: "Reproduce",
    rationale: "",
    autoProposed: false,
  },
];

export type StageStatus = "done" | "active" | "pending";

// Non-colour status vocabulary, kept from src/ui/workbench/stage_rail.py::_STATUS_PREFIX
export const STATUS_PREFIX: Record<StageStatus, string> = {
  done: "✓", // ✓
  active: "→", // →
  pending: "·", // ·
};

// ---------------------------------------------------------------------------
// Mock provenance ledger. Shape ported from
// src/services/analysis_orchestrator_service.py::AnalysisLogEntry
// (stage, tool_name, inputs, outputs, explanation, timestamp) + to_dict().
// In the real app these rows come from /api/pipeline/<project>/log and each
// one is a node in the provenance DAG (Phase 1.7 / F1).
// ---------------------------------------------------------------------------

export interface LogEntry {
  stage: StageId;
  toolName: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  explanation: string;
  timestamp: string;
}

export const MOCK_LOG: LogEntry[] = [
  {
    stage: "upload",
    toolName: "csv_reader.read",
    inputs: { path: "quarterly_sales.csv", delimiter: "," },
    outputs: { dataset_id: "ds_01", rows: 18422, columns: 9 },
    explanation:
      "Loaded 18,422 rows x 9 columns. Detected header row, comma delimiter, UTF-8.",
    timestamp: "2026-09-06T09:41:02Z",
  },
  {
    stage: "understand",
    toolName: "profiler.profile",
    inputs: { dataset_id: "ds_01" },
    outputs: {
      missing_cells: 231,
      duplicate_rows: 12,
      numeric_columns: 5,
      datetime_columns: 1,
    },
    explanation:
      "region has 231 missing values (1.3%); 12 exact-duplicate rows; order_date parsed as datetime.",
    timestamp: "2026-09-06T09:41:05Z",
  },
  {
    stage: "clean",
    toolName: "drop_duplicates.apply",
    inputs: { dataset_id: "ds_01", subset: "all" },
    outputs: { dataset_id: "ds_02", parent_dataset_id: "ds_01", rows: 18410 },
    explanation:
      "Removed 12 exact-duplicate rows. New dataset ds_02 derived from ds_01 (original kept — every intermediate state is preserved).",
    timestamp: "2026-09-06T09:41:09Z",
  },
  {
    stage: "analyze",
    toolName: "correlation.pearson",
    inputs: { dataset_id: "ds_02", columns: ["ad_spend", "revenue"] },
    outputs: { r: 0.71, p_value: 0.0003, n: 18410 },
    explanation:
      "ad_spend and revenue are strongly positively correlated (r = 0.71, p < 0.001).",
    timestamp: "2026-09-06T09:41:14Z",
  },
];
