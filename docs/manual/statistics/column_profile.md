---
title: "Per-Column Profile"
anchors:
  - statistics.column_profile
---

# Per-Column Profile

`uadas_core.analysis.column_profile.profile_column` -- the per-column building block of
[Dataset Profile](../results/dataset_profile.md), run once per column during
[Understand](../pipeline/understand.md).

For every column: dtype, missing count and percentage, distinct (unique) value count, and
whether the column was flagged ambiguous-type (a mix of numeric and non-numeric values under a
text dtype -- see [Convert Type](../cleaning/convert_type.md)). Type-appropriate detail beyond
that:

- **Numeric columns** -- min, max, mean, median, and standard deviation.
- **Text/categorical columns** -- the five most frequent values with their counts.
- **Datetime columns** -- the earliest and latest date present.

A numeric column has no "most frequent value" reported and a text column has no numeric
statistics -- each column gets only the detail that is actually meaningful for its type.
