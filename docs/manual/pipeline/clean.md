---
title: "Clean"
anchors:
  - pipeline.clean
---

# Clean

Third stage of the guided pipeline. **Rationale:** address data-quality issues found during
[Understand](understand.md) (missing values, duplicates, ambiguous types) before analyzing, so
results aren't skewed by fixable problems.

Runs one of the five [cleaning operations](../cleaning/drop_missing_values.md) against the
active dataset and shows the result **before and after, side by side** -- two independent data
table views, not one view toggled between two states, so you can compare cell-by-cell without
relying on memory.

## Cleaning never overwrites your data

Every cleaning operation returns a **new, derived dataset** -- your original data is never
modified in place. The new dataset records which dataset it came from and a plain-language
description of what changed (its lineage), which this page's lineage view displays: the chain
of ancestors above the current dataset, and any datasets already derived from it below.
[Undo](../edit/undo.md)/[Redo](../edit/redo.md) work by switching which dataset in this lineage
is active, not by reverting edits.

## The five operations

- [Drop Missing Values](../cleaning/drop_missing_values.md)
- [Fill Missing Values](../cleaning/fill_missing_values.md)
- [Drop Duplicates](../cleaning/drop_duplicates.md)
- [Normalize Text](../cleaning/normalize_text.md)
- [Convert Type](../cleaning/convert_type.md)

**Next, typically:** [Explore](explore.md), once the data looks right.
