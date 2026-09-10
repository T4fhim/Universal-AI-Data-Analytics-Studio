---
title: "Funnel Chart"
anchors:
  - charts.funnel
---

# Funnel Chart

`uadas_core.visualization.advanced_charts.FunnelChart`. **Required:** a stage column (labels each
stage) and a numeric value column (each stage's count; must be non-negative).

Shows sequential drop-off across stages, top to bottom in the row order you provide -- typically
decreasing values for a conversion funnel, but this is not enforced.
