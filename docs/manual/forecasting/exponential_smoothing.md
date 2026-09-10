---
title: "Exponential Smoothing"
anchors:
  - forecasting.exponential_smoothing
---

# Exponential Smoothing

`uadas_core.forecasting.exponential_smoothing.forecast_exponential_smoothing` -- Holt-Winters, via
`statsmodels`.

Fast, and works well on short series; handles trend and, optionally, seasonality (additive or
multiplicative). The better default choice of this application's five forecasters for a series
without enough history to benefit from [Prophet](prophet.md)'s more elaborate seasonality
decomposition. Requesting a seasonal model against fewer than 10 observations is rejected with
a specific message, rather than left to fail deep inside `statsmodels` with a less useful error.

See [Forecast results](../results/forecast.md) for what the result card shows.
