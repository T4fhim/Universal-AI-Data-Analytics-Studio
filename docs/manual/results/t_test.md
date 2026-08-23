---
title: "t-Test"
anchors:
  - results.t_test
  - statistics.t_test
---

# Independent / Paired t-Test

`src.analysis.t_test` -- via `scipy.stats`. Two separate entry points, not one function with a
`paired` flag, since the two take genuinely different inputs: two independent columns/groups,
versus two paired columns of equal length.

## Result

- **Statistic** and **p-value** (two-sided).
- **Degrees of freedom.**
- **Group A / Group B mean.**
- A convenience flag for significance at the 0.05 level.

## Assumptions

Shown as their own assumptions section on the result card, named but not automatically
verified -- run a [normality test](normality.md) first if you need to check whether the
parametric assumption actually holds for your data:

- Each group is approximately normally distributed.
- For the independent test, the two groups have similar variance.
- Observations within each group are independent of one another.

## Independent vs. paired

Use the **independent** test to compare the means of two separate groups (e.g. treatment vs.
control). Use the **paired** test when the same subjects are measured twice (e.g. before/after)
-- the two value columns must be the same length, row-for-row.
