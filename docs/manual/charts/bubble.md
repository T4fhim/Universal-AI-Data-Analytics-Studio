---
title: "Bubble Chart"
anchors:
  - charts.bubble
---

# Bubble Chart

`uadas_core.visualization.advanced_charts.BubbleChart`. **Required:** x, y, and size columns (all
numeric; size must be non-negative). **Optional:** a color column.

A scatter plot with a third numeric dimension mapped to marker size. Marker size is scaled so
the largest bubble is a fixed, reasonable size regardless of the size column's actual units,
rather than rendering raw values that could be invisible or off-screen depending on scale.
