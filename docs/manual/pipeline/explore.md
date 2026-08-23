---
title: "Explore"
anchors:
  - pipeline.explore
---

# Explore

Fourth stage of the guided pipeline. **Rationale:** look at relationships between columns
(crosstabs, grouped aggregates) before committing to a specific statistical test.

Runs one of three exploratory tools directly against the active dataset and renders a real
`ResultCard` -- these calls go straight into `src.analysis`, not through the AI layer or the
orchestrator's generic dispatch, so the exact typed result object (not a JSON dict) reaches the
result-rendering machinery:

- **Aggregate** (`src.analysis.aggregation.aggregate`) -- summarize a numeric column, grouped
  by one or more categorical columns (sum, mean, median, min, max, count, or standard
  deviation).
- **Cross-tabulate** (`src.analysis.crosstab.cross_tabulate`) -- a frequency table between two
  categorical columns, optionally normalized to row, column, or overall percentages.
- **Correlation** (`src.analysis.correlation.compute_correlation`) -- a Pearson, Spearman, or
  Kendall correlation matrix over the dataset's genuinely numeric columns (ambiguous-type
  columns are excluded and named, not silently included).

**Next, typically:** [Analyze](analyze.md), once a relationship worth testing formally has been
spotted here.
