---
title: "Line Chart"
anchors:
  - charts.line
---

# Line Chart

`src.visualization.continuous_charts.LineChart`. **Required:** a y (value) column.
**Optional:** an x column (defaults to row order/index).

Above 5,000 rows, the line is downsampled to about 1,000 points for a responsive chart --
confirmed by direct testing to genuinely reduce point count in the static HTML export this
application embeds, not merely in an interactive live-server view. Below that threshold, every
point renders directly at no added cost.
