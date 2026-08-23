---
title: "Analyze"
anchors:
  - pipeline.analyze
---

# Analyze

Fifth stage of the guided pipeline. **Rationale:** run a targeted statistical analysis now that
the data has been explored and cleaned.

Pick a statistical test, configure its parameters in a form built directly from that tool's own
schema, and run it -- producing a real `ResultCard` with the statistic, p-value, and (where the
method has one) an assumptions section, **with no AI provider configured**. Like
[Explore](explore.md), this page calls `src.analysis` functions directly rather than through
the AI layer, so the typed result reaches the correct renderer.

## Available tests

- [Correlation](../results/correlation.md)
- [Independent / paired t-test](../results/t_test.md)
- [One-way ANOVA](../results/anova.md)
- [Chi-square test of independence](../results/chi_square.md)
- [Normality test](../results/normality.md) (Shapiro-Wilk or D'Agostino-Pearson)
- [Linear regression](../results/regression.md)
- [Principal component analysis (PCA)](../results/pca.md)
- [K-means clustering](../results/clustering.md)

Every result recorded here is also available for [Explain](explain.md) (an AI interpretation,
once a provider is configured) and [Report](report.md) (export).

**Next, typically:** [Visualize](visualize.md), to chart what Analyze found.
