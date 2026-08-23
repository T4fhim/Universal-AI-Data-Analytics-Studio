---
title: "Correlation"
anchors:
  - results.correlation
  - statistics.correlation
---

# Correlation

`src.analysis.correlation.compute_correlation` -- Pearson, Spearman, or Kendall correlation
over a dataset's genuinely numeric columns.

## How it works

Columns are checked against `src.readers.type_inference.find_ambiguous_type_columns` first --
a column a reader already flagged as containing a mix of value types is excluded from the
matrix (and named, with a reason) even if pandas' own dtype inference happens to look
numeric-compatible. Including it would produce a coefficient over data the column's own profile
already says should not be trusted numerically.

At least two genuinely numeric columns are required.

## Reading the result

The result card shows the correlation matrix as a table, the columns that were included, and
which were excluded and why. On the [Visualize](../pipeline/visualize.md) stage, the same
computation backs the [Heatmap chart](../charts/heatmap.md).

## Choosing a method

- **Pearson** (default) -- linear relationships between two numeric variables; sensitive to
  outliers and assumes roughly normal data.
- **Spearman** -- rank-based; captures monotonic (not necessarily linear) relationships and is
  more robust to outliers.
- **Kendall** -- also rank-based; more robust than Spearman on small samples or data with many
  tied ranks, at the cost of being more conservative.
