---
title: "Bar Chart"
anchors:
  - charts.bar
---

# Bar Chart

`uadas_core.visualization.categorical_charts.BarChart`. **Required:** a category column. **Optional:**
a value column (aggregated per category; if omitted, bars show value counts).

**Optional, with a series column:** `series_column` stacks each bar from one segment per value of
that column. The categories are not capped here (they are usually time buckets and keep the
column's own order, dates as dates); the series are: the 14 largest stay and the rest are summed
into "Other". Two options need `series_column`. `incomplete_from` (a value of the category
column, as shown on the axis) draws that bucket and every later one as a single hatched
"Incomplete" total; it is never inferred, so set it only when you know the last bucket is partial.
`variant="grouped"` puts the series side by side instead of stacked, each with its own fill
pattern (solid, hatch, stipple, ...) so the series differ by more than colour. The two cannot be
combined.

A categorical column with dozens or hundreds of distinct values produces an unreadable chart
(illegible axis labels) if charted directly. This chart caps the number of categories shown
(15) and groups the remainder into an "Other" bucket -- a documented, visible transformation of
what is shown, not a silent truncation.
