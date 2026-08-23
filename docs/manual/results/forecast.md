---
title: "Forecast"
anchors:
  - results.forecast
---

# Forecast

The result of running a single forecaster from the [Predict](../pipeline/predict.md) stage
(`src.forecasting.exponential_smoothing.ForecastResult`, the shared result type every one of
the five forecasters returns).

## Result

- **Summary** -- which method ran, how many historical points it fit on, and how many periods
  ahead it projected.
- **Forecast values** -- a table of projected dates and values (capped at 200 rows for display;
  the underlying result itself is not truncated).
- **Forecast chart** -- historical values and the projection overlaid on the same axes, since a
  table of numbers alone does not communicate "does this trend look right" the way a chart
  does. This is the first result type in the application to embed a chart directly in its
  result card rather than tables and metrics alone.

See each forecaster's own page for what "method" means and when to prefer it:
[Exponential Smoothing](../forecasting/exponential_smoothing.md),
[ARIMA](../forecasting/arima.md), [Prophet](../forecasting/prophet.md),
[Linear Regression](../forecasting/linear_regression.md),
[Random Forest](../forecasting/random_forest.md). To have the application choose among them
automatically, see [Automatic Model Competition](forecast_comparison.md).
