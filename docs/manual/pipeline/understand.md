---
title: "Understand"
anchors:
  - pipeline.understand
---

# Understand

Second stage of the guided pipeline. **Rationale:** profile the dataset first -- row/column
counts, missing values, and types -- before deciding what cleaning or analysis makes sense.

Clicking **Run** calls `src.analysis.dataset_profile.profile_dataset` against the active
dataset and shows:

- Row and column counts.
- Duplicate row count (informs whether [Clean](clean.md)'s duplicate-removal operation is
  worth running).
- Per-column profile: dtype, missing count/percentage, uniqueness, and type-appropriate
  statistics (numeric columns get mean/min/max-style summaries; text columns get their most
  frequent values).
- Ambiguous-type columns -- columns a reader already flagged as containing a mix of value
  types (see [Open Dataset](../data/open-dataset.md)'s reader table), surfaced again here since
  this is the natural place to decide whether to fix them via
  [Convert Type](../cleaning/convert_type.md).

This is the only stage without a parameter form -- there is nothing to configure, since
profiling always runs against every column.

**Next, typically:** [Clean](clean.md), to address anything Understand found.
