---
title: "Statistics Glossary"
anchors:
  - statistics.glossary
---

# Statistics Glossary

Terms used across this application's twelve statistical/profiling methods
([aggregation](aggregation.md), [ANOVA](../results/anova.md), [chi-square](../results/chi_square.md),
[clustering](../results/clustering.md), [per-column profile](column_profile.md),
[correlation](../results/correlation.md), [cross-tabulation](crosstab.md),
[dataset profile](../results/dataset_profile.md), [normality](../results/normality.md),
[PCA](../results/pca.md), [regression](../results/regression.md), [t-test](../results/t_test.md))
and its five [forecasters](../pipeline/predict.md).

**p-value** -- the probability of seeing a result at least as extreme as the one observed, if
the null hypothesis (usually "no effect" or "no difference") were actually true. A small
p-value (conventionally below 0.05, the threshold every applicable result in this application
checks against as `significant_at_0_05`) is evidence against the null hypothesis -- it is not
the probability the null hypothesis is true, and it says nothing about effect size.

**Statistic** -- the single number a test reduces your data to before consulting its own
reference distribution to produce a p-value (a t statistic, an F statistic, a chi-square
statistic). Its magnitude is only interpretable relative to that test's own distribution, which
is why the p-value, not the raw statistic, is usually the number worth reading first.

**Degrees of freedom** -- roughly, how many independent pieces of information went into
computing a statistic. Needed to select the correct reference distribution for a p-value;
reported alongside the statistic for every applicable test in this application, not something
you need to compute separately.

**Null hypothesis** -- the "nothing interesting is happening" baseline a test is designed to
argue against: no difference between groups ([t-test](../results/t_test.md),
[ANOVA](../results/anova.md)), no association between two columns
([chi-square](../results/chi_square.md)), the data is normally distributed
([normality test](../results/normality.md)).

**Assumptions** -- conditions a statistical method is derived under (e.g. normally distributed
groups). This application names a method's assumptions in its own `AssumptionsSection`, but
does **not** automatically verify them for you -- run a [normality test](../results/normality.md)
first if you need to check whether a parametric method's assumption actually holds.

**R-squared** -- for [regression](../results/regression.md), the fraction of variance in the
target variable explained by the model. Never decreases as more predictors are added regardless
of whether they help, which is why **adjusted R-squared** (penalized for predictor count) is
the more meaningful figure once more than one predictor is used.

**MAPE / RMSE** -- the two accuracy metrics [Automatic Model Competition](../results/forecast_comparison.md)
ranks candidate forecasters by. MAPE (mean absolute percentage error) is scale-independent and
easy to interpret as "off by X% on average"; it is undefined when actual values are zero, in
which case only RMSE (root mean squared error, in the series' own units) is reported.

**Explained variance ratio** -- for [PCA](../results/pca.md), the fraction of a dataset's total
variance a given component captures. The **cumulative** variance ratio is the running total
across the first N components together -- the number that actually answers "how many
components should I keep."

**Inertia** -- for [k-means clustering](../results/clustering.md), the sum of squared distances
from each row to its assigned cluster's center. Lower means tighter clusters; meaningful mainly
for comparing different values of `k` against each other, not as a number meaningful alone.

**Ambiguous-type column** -- a column a reader could not confidently infer a single type for
(a mix of numeric and text values under one dtype). Every numeric-only method in this
application (correlation, PCA, clustering) excludes ambiguous-type columns automatically and
names them, rather than silently including data its own profile says should not be trusted
numerically. See [Convert Type](../cleaning/convert_type.md) to resolve one.
