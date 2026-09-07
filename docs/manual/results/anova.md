---
title: "One-Way ANOVA"
anchors:
  - results.anova
  - statistics.anova
---

# One-Way ANOVA

`uadas_core.analysis.anova.one_way_anova` -- via `scipy.stats`. The multi-group equivalent of the
[t-test](t_test.md): compares the means of three or more groups (split by one categorical
column) on a single numeric measure, in one test, rather than running repeated pairwise
t-tests, which would inflate the false-positive rate.

Requires at least three groups, each with at least two observations.

## Result

- **F statistic** and **p-value** for the null hypothesis that all group means are equal.
- Mean and observation count per group.
- A convenience flag for significance at the 0.05 level.

A significant ANOVA result tells you *that* the group means differ, not *which* groups differ
from which -- a post-hoc pairwise comparison (not currently a separate tool in this
application) would be the next step to localize the difference.
