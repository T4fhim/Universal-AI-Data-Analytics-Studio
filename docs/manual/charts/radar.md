---
title: "Radar Chart"
anchors:
  - charts.radar
---

# Radar Chart

`uadas_core.visualization.advanced_charts.RadarChart`. **Required:** a category column (labels each
trace, e.g. a product name) and at least 3 numeric value columns (the radar's axes).

Each row of the dataset becomes one radar trace -- appropriate for a small number of rows (a
handful of products, teams, or scenarios being compared); this application does not enforce a
hard limit on row count, but a radar chart with many overlapping traces stops being readable.
At least 3 value columns are required, since fewer would not form a meaningfully different
shape from a bar chart.
