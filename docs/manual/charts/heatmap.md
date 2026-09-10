---
title: "Heatmap"
anchors:
  - charts.heatmap
---

# Heatmap

`uadas_core.visualization.advanced_charts.HeatmapChart`. No columns to choose -- it charts a
[correlation matrix](../results/correlation.md) over every genuinely numeric column in the
active dataset (method: Pearson by default). Reuses the same correlation computation the
Explore/Analyze stages use, rather than recomputing it, so the two features cannot disagree.
