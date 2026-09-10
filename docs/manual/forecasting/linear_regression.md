---
title: "Linear Regression Forecast"
anchors:
  - forecasting.linear_regression
---

# Linear / Polynomial Regression Forecast

`uadas_core.forecasting.linear_regression_forecast.forecast_linear_regression` -- via scikit-learn.

The simplest of the five forecasters: fits a polynomial trend against elapsed time (days from
the series' first date) and projects it forward, with **no seasonality component at all**.
This makes it a fast, interpretable baseline (and a useful contrast candidate in
[Automatic Model Competition](../results/forecast_comparison.md)) for a series that genuinely
is trend-dominated, and a poor choice for anything with real periodicity.

Distinct from [the statistical Linear Regression result](../results/regression.md), which uses
the same underlying method for a different purpose (explaining a relationship between columns,
not projecting a time series forward) and reports inferential statistics this forecaster does
not.
