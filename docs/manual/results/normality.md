---
title: "Normality Test"
anchors:
  - results.normality
  - statistics.normality
---

# Normality Test

`uadas_core.analysis.normality` -- Shapiro-Wilk or D'Agostino-Pearson, via `scipy.stats`, for a single
numeric column. This is a precondition check to run *before* choosing a test, such as
[t-test](t_test.md) or [ANOVA](anova.md), that assumes normally distributed data -- not a step
inside either of those tests.

## Choosing a method

- **Shapiro-Wilk** -- generally more powerful for smaller samples. Reliable up to about 5,000
  observations in this application's implementation; beyond that the p-value becomes overly
  sensitive to trivial deviations, which is reported as a known limitation rather than silently
  returning a misleading answer.
- **D'Agostino-Pearson** -- based on skewness and kurtosis; needs at least 8 observations to be
  meaningful (fewer than that, its underlying tests are unreliable even though scipy itself only
  warns as low as 8).

## Result

- The test statistic and p-value for the null hypothesis that the data is normally distributed.
- A convenience flag, `appears_normal_at_0_05` -- note this is `p_value >= 0.05` (**failing to
  reject** normality), which is a genuinely weaker claim than "proven normal."
