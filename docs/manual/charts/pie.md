---
title: "Pie Chart"
anchors:
  - charts.pie
---

# Pie Chart

`src.visualization.categorical_charts.PieChart`. **Required:** a category column. **Optional:**
a value column (aggregated per category; if omitted, slices show value counts).

Same high-cardinality guard as [the Bar chart](bar.md): more than 15 distinct categories are
grouped into an "Other" slice rather than producing indistinguishable slivers.
