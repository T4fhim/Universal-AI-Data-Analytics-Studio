---
title: "Principal Component Analysis (PCA)"
anchors:
  - results.pca
  - statistics.pca
---

# Principal Component Analysis (PCA)

`uadas_core.analysis.pca.compute_pca` -- via scikit-learn. Reduces a set of numeric columns to a
smaller number of uncorrelated components that capture as much of the original variance as
possible.

## How it works

Every included column is standardized (zero mean, unit variance) before fitting -- without
this, a column with a much larger numeric scale than the others would dominate the components
purely because of its units, not because it genuinely carries more variance worth explaining.
The same ambiguous-type-aware numeric-column selection [correlation](correlation.md) uses
applies here too.

## Result

- **Explained variance ratio** per component, and the running **cumulative variance ratio** --
  how much of the total variance the first N components explain together.
- **Component loadings** -- how much each original column contributes to each component.
- The original rows projected onto the components (`PC1`, `PC2`, ...) -- computed, but not
  currently shown in the result card's own tables, which summarize variance and loadings only.

The headline states how many components were computed and what fraction of total variance they
explain together, so the "is this worth keeping" question has a direct answer without needing
to read every row of the variance table.
