---
title: "Prophet"
anchors:
  - forecasting.prophet
---

# Prophet

`uadas_core.forecasting.prophet_forecast.forecast_prophet` -- via Meta's `prophet` library.

Better than [Exponential Smoothing](exponential_smoothing.md) for longer series with multiple
seasonal patterns (e.g. both weekly and yearly cycles) and series with missing dates or
outliers, which Prophet is built to tolerate. Heavier and slower to fit -- for a short series
with one simple seasonal pattern, exponential smoothing is usually the better default. This is
the slowest of the five forecasters, which is why [Automatic Model Competition](../results/forecast_comparison.md)
runs on a background worker rather than the UI thread.

See [Forecast results](../results/forecast.md) for what the result card shows.
