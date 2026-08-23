---
title: "Visualize"
anchors:
  - pipeline.visualize
---

# Visualize

Sixth stage of the guided pipeline. **Rationale:** build a chart of the analysis result -- a
visual is often clearer than a table of numbers for spotting what the analysis found.

Pick columns, optionally get a ranked, reasoned recommendation, and build any of the twelve
chart types -- see [Create a Chart](../visualize/create-chart.md) for the full list and how the
recommender works. This page additionally links a built chart to the dataset table directly:
clicking a data point filters the paired table to the rows behind it.

**Next, typically:** [Predict](predict.md) if the dataset has a time dimension worth
forecasting, otherwise [Explain](explain.md).
