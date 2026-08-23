---
title: "K-Means Clustering"
anchors:
  - results.clustering
  - statistics.clustering
---

# K-Means Clustering

`src.analysis.clustering.k_means_clustering` -- via scikit-learn. Groups rows into `k` clusters
based on a set of numeric columns, using the same standardization
(zero mean, unit variance) [PCA](pca.md) applies, and the same reasoning: unscaled columns with
larger numeric ranges would otherwise dominate the distance metric k-means clusters on purely
because of units. `k` must be at least 2.

## Result

- **Inertia** -- sum of squared distances from each row to its cluster's center; lower is
  tighter clustering. Primarily useful for comparing different values of `k` against each
  other (an "elbow" plot, run manually across a few `k` values), not as a number meaningful in
  isolation.
- **Cluster sizes** -- how many rows landed in each cluster.
- **Cluster centers** -- centroid coordinates per cluster, reported in the original (unscaled)
  column space so they are directly interpretable against your source data, not the internal
  standardized scale k-means actually fit on.
