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

**A pivot matrix of any two columns.** Give `row_column` and `column_column` (both, and different
columns) and the chart is a matrix instead: one row per value of the first column, one column per
value of the second, each cell the sum of an optional numeric `value_column` over its rows (or the
row count). Rows and columns keep their own order (dates in date order, numbers in numeric order, an
ordered category in its own order) with the first row at the top; a combination with no rows is an
empty cell, not a zero. An axis with more than 40 values keeps its 39 largest and sums the rest into
an "Other" row or column. The colour scale is one hue.

`variant` (a value, pivot matrix only) picks the look: `"numbers"` writes each cell's value in it
(whole numbers have no decimals, otherwise two), and `"grid"` is a monochrome grid of cells set
apart by a gap, with no numbers. The cells are as square as the chart's own proportions make them;
the chart cannot force squares.
