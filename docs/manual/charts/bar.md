---
title: "Bar Chart"
anchors:
  - charts.bar
---

# Bar Chart

`src.visualization.categorical_charts.BarChart`. **Required:** a category column. **Optional:**
a value column (aggregated per category; if omitted, bars show value counts).

A categorical column with dozens or hundreds of distinct values produces an unreadable chart
(illegible axis labels) if charted directly. This chart caps the number of categories shown
(15) and groups the remainder into an "Other" bucket -- a documented, visible transformation of
what is shown, not a silent truncation.
