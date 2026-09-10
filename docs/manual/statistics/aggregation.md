---
title: "Aggregation"
anchors:
  - statistics.aggregation
---

# Aggregation

`uadas_core.analysis.aggregation.aggregate`, run from the [Explore](../pipeline/explore.md) stage.

Groups a dataset by one or more categorical columns and summarizes a numeric column within
each group, using `sum`, `mean`, `median`, `min`, `max`, `count`, or `std`. Any function other
than `count` requires the aggregated column to be genuinely numeric.

Returns one row per unique combination of the group-by values. Since this has no dedicated
result type of its own, it renders through [the generic result card](../results/generic.md) as
a plain table.
