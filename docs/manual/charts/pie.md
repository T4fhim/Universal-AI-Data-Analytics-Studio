---
title: "Pie Chart"
anchors:
  - charts.pie
---

# Pie Chart

`uadas_core.visualization.categorical_charts.PieChart`. **Required:** a category column. **Optional:**
a value column (aggregated per category; if omitted, slices show value counts).

Same high-cardinality guard as [the Bar chart](bar.md): more than 15 distinct categories are
grouped into an "Other" slice rather than producing indistinguishable slivers.

`variant="donut"` (a value, not a column) cuts a hole in the pie and writes the total in it: the
sum of every slice, "Other" included, with the value column's name beneath it (or "Count" when
slices are row counts). Whole totals have no decimals, fractional ones have two, and a long total
is set in a smaller size so it stays inside the hole. A legend table beside the ring, with the
value and share of each slice, is not part of the chart.

`panel_column` (a column) draws one pie per value of that column, in a grid of up to four pies to
a row (twelve panels are four columns by three rows), titled with the value: small multiples, to
compare how the slices divide in each group. Every pie has the same slices, so a category keeps
one colour throughout and a single legend serves the grid; a category a panel has no rows for is
a zero-size slice. More than 12 panels are grouped into an "Other" pie, by the same rule as the
15-category cap, and the 15-category cap applies to the slices across the whole data. It cannot
be combined with `variant`, and the panel column must differ from the category column.
