---
title: "KPI Card"
anchors:
  - charts.kpi
---

# KPI Card

`uadas_core.visualization.advanced_charts.KpiChart`. **Required:** a numeric value column, with its
rows in time order. **Optional:** an x column giving each row's period for the mini chart (the row
order is used if you leave it out).

The card shows the **latest value** (the last row that has one) as a large number, with its
**change from the value before it** underneath, as an absolute figure with an arrow: direction is
carried by the arrow as well as by the green or red colour. A series of one value has no change.
Under the number is a **mini chart** of the whole series, with no axes: the card is read at a
glance and the figures are in the number. The card is titled with the column's name.

`variant` (a value, not a column) picks the mini chart: `"line"` (the default; a dot marks the
latest value), `"bars"`, `"dashes"` (bars in a dash pattern, so segmented) or `"lollipop"` (a stem
per value with a dot on its head). Whole numbers have no decimals; otherwise two are shown.
