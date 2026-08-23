---
title: "ARIMA / SARIMA"
anchors:
  - forecasting.arima
---

# ARIMA / SARIMA

`src.forecasting.arima_forecast.forecast_arima` -- via `pmdarima`'s `auto_arima` over
`statsmodels`.

Uses `auto_arima` rather than requiring you to specify `(p, d, q)` orders directly -- like this
application's other forecasters, it avoids asking for hyperparameters you are unlikely to know
how to choose; `auto_arima` searches the order space itself via stepwise AIC minimization.
Below 10 observations, that search has too little data to reliably distinguish candidate
orders, and is rejected with a specific message rather than silently settling on a degenerate
model that is really just the series mean.

See [Forecast results](../results/forecast.md) for what the result card shows.
