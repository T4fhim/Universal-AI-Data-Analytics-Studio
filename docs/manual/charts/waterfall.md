---
title: "Waterfall Chart"
anchors:
  - charts.waterfall
---

# Waterfall Chart

`src.visualization.advanced_charts.WaterfallChart`. **Required:** a category column (labels
each step) and a numeric value column (each step's change, positive or negative).

Shows the cumulative effect of a sequence of changes. Row order is treated as the intended
sequence and is never re-sorted -- if your data needs a specific chronological order, establish
it (e.g. sort, or a [cleaning](../pipeline/clean.md) step) before building this chart.
