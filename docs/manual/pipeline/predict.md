---
title: "Predict"
anchors:
  - pipeline.predict
---

# Predict

Seventh stage of the guided pipeline. **Rationale:** if the dataset has a time dimension,
forecast it -- Automatic Model Competition runs every applicable model and picks the best one
by holdout accuracy.

Pick one of the five forecasters directly, or run **Automatic Model Competition**
(`uadas_core.forecasting.model_comparison.compare_forecast_models`), which fits every candidate model
against a held-out tail of the series, scores each by how well it predicted values it did not
see, and reports the best-ranked one -- while still fitting every model's *actual* returned
forecast on the full series (the holdout split is only used to choose which model to trust).
Automatic Model Competition runs on a background worker with live progress in the status bar,
since fitting up to five models twice each is measurably slower than a single forecast call.

## The five forecasters

- [Exponential Smoothing](../forecasting/exponential_smoothing.md) (Holt-Winters)
- [ARIMA / SARIMA](../forecasting/arima.md)
- [Prophet](../forecasting/prophet.md)
- [Linear / polynomial regression](../forecasting/linear_regression.md)
- [Random Forest](../forecasting/random_forest.md)

Before fitting, your chosen date and value columns are validated for a genuinely time-ordered,
numeric series -- an unsorted or unparseable date column is rejected with a specific message
rather than silently producing a nonsensical projection.

See [Automatic Model Competition results](../results/forecast_comparison.md) and
[a single forecast's results](../results/forecast.md) for what the result card shows.

**Next, typically:** [Explain](explain.md).
