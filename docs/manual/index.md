---
title: "Universal AI Data Analytics & Visualization Studio -- Manual"
anchors:
  - index
---

# Manual

This is the in-app manual, opened by pressing **F1** anywhere in the application, or from
**Help > About**. It documents what the running application actually does -- every page here
is grounded in a real, shipped module, not a description of a planned feature. If a capability
described in `SPECIFICATION.md` is not covered here, it has not been built yet; check
`docs/ROADMAP.md` for the current list of unbuilt subsystems.

Press F1 again from any screen to return here, or to jump straight to that screen's own
section -- F1 always opens the manual page for whichever control currently has keyboard focus.

## The guided pipeline

The application organizes a data analysis into ten fixed stages, always in the same order.
Each stage's own page explains what it does and why it is proposed at that point:

1. [Upload](pipeline/upload.md) -- get a dataset into the workspace.
2. [Understand](pipeline/understand.md) -- profile it before changing anything.
3. [Clean](pipeline/clean.md) -- fix missing values, duplicates, and type problems.
4. [Explore](pipeline/explore.md) -- look at relationships between columns.
5. [Analyze](pipeline/analyze.md) -- run a targeted statistical test.
6. [Visualize](pipeline/visualize.md) -- build a chart.
7. [Predict](pipeline/predict.md) -- forecast a time series.
8. [Explain](pipeline/explain.md) -- read the AI's plain-language interpretation of a result.
9. [Report](pipeline/report.md) -- export everything recorded so far.
10. [Reproduce](pipeline/reproduce.md) -- replay the recorded pipeline against re-imported data.

Nothing in the pipeline is enforced in order: every stage's page is reachable at any time from
the stage rail, and the guidance panel on each page only ever *suggests* what to do next --
see the Understand page's own manual entry for how that suggestion is computed.

## Reference

- **Readers** -- every file and database format the application can import: see the
  [readers index](readers/csv.md) (linked from [Open Dataset](data/open-dataset.md)) for the
  full list of sixteen.
- **Charts** -- the twelve chart types available from the Visualize stage: see
  [Create a Chart](visualize/create-chart.md) for the full list.
- **Statistics** -- the twelve statistical/profiling methods available from Understand,
  Explore, and Analyze: aggregation, ANOVA, chi-square, clustering, per-column profiling,
  correlation, cross-tabulation, dataset profiling, normality testing, PCA, regression, and
  the t-test. Each result type also has its own manual page, linked from its `ResultCard`.
  See the [statistics glossary](statistics/glossary.md) for terms used across all of them.
- **Forecasting** -- the five forecasting methods available from Predict, plus Automatic
  Model Competition: see [Predict](pipeline/predict.md).
- **AI assistant** -- how the assistant is scoped, how it calls tools, and how to bring your
  own API key: see [the AI layer](ai/overview.md).
- **Plugins** -- how third-party readers, cleaning operations, and charts are discovered and
  loaded: see [the plugin system](plugins/overview.md).

## Application-wide actions

- [New Project](project/new.md), [Open Project](project/open.md),
  [Save](project/save.md), [Save As](project/save-as.md), [Exit](project/exit.md)
- [Open Dataset](data/open-dataset.md), [Connect to Database](data/connect-database.md)
- [Settings](settings.md), [Toggle Theme](view/theme.md)
- [Undo](edit/undo.md), [Redo](edit/redo.md)
- [Generate Report](report/generate.md)
- [Create a Dashboard](visualize/dashboard.md)
