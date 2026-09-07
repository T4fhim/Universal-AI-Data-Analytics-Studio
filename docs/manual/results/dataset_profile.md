---
title: "Dataset Profile"
anchors:
  - results.dataset_profile
  - statistics.dataset_profile
---

# Dataset Profile

`uadas_core.analysis.dataset_profile.profile_dataset` -- the result of the
[Understand](../pipeline/understand.md) stage. Aggregates a per-column profile
(`uadas_core.analysis.column_profile.profile_column`) plus dataset-wide statistics.

## Result

- **Row and column counts**, and **duplicate row count** -- informs whether
  [Drop Duplicates](../cleaning/drop_duplicates.md) is worth running.
- **Memory usage** -- computed with pandas' deep accounting so text columns are sized by their
  actual string content, not just pointer size, which would understate exactly the columns
  most likely to be large.
- **Per-column profile**, one row per column: dtype, missing count/percentage, uniqueness, and
  type-appropriate statistics (numeric columns get summary statistics; text/categorical columns
  get their most frequent values).
- **Ambiguous-type columns** -- flagged for the same reason every reader that surfaces this
  warning does (see [Open Dataset](../data/open-dataset.md)): a column pandas could not
  confidently infer a single type for.

The headline states row x column count and duplicate row count in one line, so the two numbers
most likely to change what you do next are visible before reading the full per-column table.
