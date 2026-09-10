---
title: "Chi-Square Test of Independence"
anchors:
  - results.chi_square
  - statistics.chi_square
---

# Chi-Square Test of Independence

`uadas_core.analysis.chi_square.chi_square_test` -- via `scipy.stats`. Tests whether two categorical
columns are independent of each other, over the same contingency table
[cross-tabulation](../pipeline/explore.md) builds (`uadas_core.analysis.crosstab.cross_tabulate`) --
reused rather than re-derived, so the two features cannot silently disagree about what counts
as a valid pair of columns.

## Result

- **Chi-square statistic**, **p-value**, and **degrees of freedom**.
- The observed-frequency contingency table the test was computed over.
- A convenience flag: `significant_at_0_05` -- evidence the two columns are *not* independent.

A significant result means the two columns' values are associated; it does not by itself say
how strong that association is or in which direction.
