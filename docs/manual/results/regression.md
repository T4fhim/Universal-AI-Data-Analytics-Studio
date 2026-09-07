---
title: "Linear Regression"
anchors:
  - results.regression
  - statistics.regression
---

# Linear Regression

`uadas_core.analysis.regression.linear_regression` -- ordinary least squares (simple or multiple), via
`statsmodels`, not scikit-learn: the inferential statistics below (p-values, R-squared)
`statsmodels`' `OLS` reports natively, which is exactly what the AI explanation layer and this
result card need -- scikit-learn's own `LinearRegression` deliberately omits them, since it
targets prediction pipelines rather than statistical inference.

This is distinct from [forecasting's own linear/polynomial trend model](../forecasting/linear_regression.md),
which uses the same underlying method for a different purpose (projecting a time series
forward) and a different result shape.

## Result

- **Coefficients** and **p-value** per predictor (feature) column, plus the intercept.
- **R-squared** and **adjusted R-squared** -- prefer adjusted R-squared once more than one
  predictor is used, since plain R-squared never decreases as predictors are added regardless
  of whether they actually help.
- Number of observations the model was fit on, after dropping rows with missing values in any
  used column.

A small p-value for a coefficient is evidence that predictor has a real relationship with the
target, holding the others constant -- it is not, by itself, a statement about effect size or
practical importance.
