---
title: "Random Forest Forecast"
anchors:
  - forecasting.random_forest
---

# Random Forest Forecast

`src.forecasting.random_forest_forecast.forecast_random_forest` -- via scikit-learn.

Unlike this application's other forecasters, a Random Forest has no native notion of "time" --
it is a general regressor. This forecaster turns the series into a supervised-learning problem
by using each point's preceding values (a configurable number of lags, 3 by default) as
features to predict the next value. Forecasting more than one step ahead is done recursively:
each predicted value is fed back in as a lag for predicting the next one, since the model was
only trained to predict a single step ahead at a time.
