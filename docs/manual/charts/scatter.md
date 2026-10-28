---
title: "Scatter Chart"
anchors:
  - charts.scatter
---

# Scatter Chart

`uadas_core.visualization.continuous_charts.ScatterChart`. **Required:** x and y columns.
**Optional:** a color column, and a label column (each point's label, read out on hover).

Two options are values, not columns. `frontier` is one of `upper_left`, `upper_right`,
`lower_left` or `lower_right`: the corner where a point is best (`upper_left` is a low x with a
high y, a cheap model that scores well). The chart then draws the Pareto frontier of all the
points -- those no other point beats -- as a dashed line named "Pareto frontier"; rows with a
missing coordinate are left out. `pin` is a value of the label column: that point is ringed and its
label written on the chart. It needs the label column, and a value that is not in it is an error.

Unlike [the Line chart](line.md) the scatter is not downsampled: chart a window of a very large
table rather than all of it.
