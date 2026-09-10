---
title: "Create a Chart"
anchors:
  - visualize/create-chart
---

# Create a Chart

**Analysis > Visualize...**, or from the **Visualize** stage page directly. Requires an active
dataset.

Builds a Plotly figure from the active dataset and a handful of column choices, via
`uadas_core.visualization.chart_registry` -- every chart type is a stateless `BaseChart` subclass
whose `build(dataframe, **kwargs)` returns a `go.Figure` directly embedded in the workspace.

## The twelve chart types

| Chart | Required fields | Notes |
|---|---|---|
| [Bar](../charts/bar.md) | category column | High-cardinality columns grouped into "Other". |
| [Pie](../charts/pie.md) | category column | Same grouping as Bar. |
| [Line](../charts/line.md) | y column | Downsampled above 5,000 rows for a responsive chart. |
| [Scatter](../charts/scatter.md) | x, y columns | Also downsampled above 5,000 rows. |
| [Histogram](../charts/histogram.md) | numeric column | Bin count optional. |
| [Box Plot](../charts/box_plot.md) | value column | Optional grouping column. |
| [Heatmap](../charts/heatmap.md) | (none) | A correlation matrix over every numeric column. |
| [Bubble](../charts/bubble.md) | x, y, size columns | Size must be non-negative. |
| [Treemap](../charts/treemap.md) | path column(s), value column | Value must be non-negative. |
| [Radar](../charts/radar.md) | category column, 3+ value columns | One trace per row. |
| [Waterfall](../charts/waterfall.md) | category, value columns | Row order is the sequence shown. |
| [Funnel](../charts/funnel.md) | stage, value columns | Value must be non-negative. |

## Getting a recommendation

The Visualize stage page can rank candidate chart types for the columns you've picked, with a
stated reason for each suggestion (`uadas_core.visualization.chart_recommender.recommend_charts`) --
a rule-based recommender, not a trained model, so every suggestion is inspectable rather than a
black-box guess. A numeric-vs-numeric pair suggests a scatter; a date column plus a numeric
column suggests a line; a low-cardinality categorical column plus a numeric column suggests a
bar, and so on.

## Interacting with a built chart

On the Visualize stage page, clicking a point in the built chart filters the paired data table
to the rows behind that point -- a live link between the chart and the underlying data, not
just a static picture.
