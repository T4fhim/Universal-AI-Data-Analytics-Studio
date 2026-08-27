---
title: "Automatic Model Competition"
anchors:
  - results.forecast_comparison
---

# Automatic Model Competition

The result of `src.forecasting.model_comparison.compare_forecast_models`
(`ModelComparisonResult`), run from the [Predict](../pipeline/predict.md) stage when you choose
"Automatic Model Competition" instead of a single forecaster.

## How the winner is chosen

Every applicable model is fit against a held-out tail of the series and scored by how well it
predicted the values it did not see (MAPE, with RMSE reported alongside) -- the same
train/holdout evaluation methodology a human analyst would use, not a heuristic guess based on
the series' shape. The model that ships as each candidate's actual forecast is still fit on the
**full** series; the holdout split exists only to decide which model to trust, not to discard
the most recent data from the forecast you actually get.

## Result

- **Summary** -- how many candidates were evaluated, and which one won.
- **Ranked candidates** -- a table of every model tried, its MAPE and RMSE, ranked best to
  worst. The winning row's model name is marked with a literal `(Winner)` suffix in the cell
  text itself, not by color alone, so the winner is unambiguous to a screen reader and a
  colorblind user exactly as it is to anyone else.
- **Forecast comparison chart** -- every candidate's projection overlaid on the same historical
  data, with the winning model's trace drawn more prominently.
