---
title: "Cross-Tabulation"
anchors:
  - statistics.crosstab
---

# Cross-Tabulation

`src.analysis.crosstab.cross_tabulate`, run from the [Explore](../pipeline/explore.md) stage.

Builds a frequency table between two categorical columns. By default it reports raw counts;
set normalization to `index` (each row sums to 1), `columns` (each column sums to 1), or `all`
(the entire table sums to 1) for percentages instead. The two columns must be different --
cross-tabulating a column against itself is always a diagonal matrix and more likely a mistake
than an intended request, so it is rejected rather than silently computed.

The same contingency table this function builds is reused directly by the
[chi-square test](../results/chi_square.md), so the two features cannot silently disagree about
what counts as a valid pair of columns. Since cross-tabulation has no dedicated result type of
its own, it renders through [the generic result card](../results/generic.md) as a plain table.
