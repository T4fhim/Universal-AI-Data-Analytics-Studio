# File: src/ui/results/renderers/multivariate.py
"""Renderers for PCA and k-means clustering -- the two multi-column, multi-row result types.

Grouped together because both operate over a set of numeric columns at once (rather than one or
two named columns, like the statistical tests) and both report a per-row-and-per-column-shaped
result too large to usefully render row-by-row -- :class:`PcaResultRenderer` and
:class:`ClusteringResultRenderer` both summarize (component loadings, cluster centers) rather
than dumping ``transformed``/``labels`` in full.
"""

from __future__ import annotations

from src.analysis.clustering import ClusteringResult
from src.analysis.pca import PcaResult
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.base_result_renderer import (
    BaseResultRenderer,
    KeyValueSection,
    MetricSection,
    ResultSection,
    TableSection,
)


class PcaResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.pca.PcaResult`."""

    @classmethod
    def title(cls, result: PcaResult) -> str:
        return "Principal Component Analysis"

    @classmethod
    def headline(cls, result: PcaResult, level: ExpertiseLevel) -> str:
        n_components = len(result.explained_variance_ratio)
        cumulative = (
            result.cumulative_variance_ratio[-1]
            if result.cumulative_variance_ratio
            else 0.0
        )
        return f"{n_components} component(s) explain {cumulative * 100:.1f}% of total variance."

    @classmethod
    def sections(cls, result: PcaResult, level: ExpertiseLevel) -> list[ResultSection]:
        component_names = [
            f"PC{i + 1}" for i in range(len(result.explained_variance_ratio))
        ]
        return [
            KeyValueSection(
                title="Summary",
                items=(("Included columns", ", ".join(result.included_columns)),),
            ),
            TableSection(
                title="Explained Variance",
                columns=("Component", "Variance Ratio", "Cumulative"),
                rows=tuple(
                    (name, f"{ratio:.4f}", f"{cumulative:.4f}")
                    for name, ratio, cumulative in zip(
                        component_names,
                        result.explained_variance_ratio,
                        result.cumulative_variance_ratio,
                    )
                ),
            ),
            TableSection(
                title="Component Loadings",
                columns=("Column",) + tuple(component_names),
                rows=tuple(
                    (column,)
                    + tuple(
                        f"{loadings.get(column, 0.0):.4f}"
                        for loadings in result.component_loadings
                    )
                    for column in result.included_columns
                ),
            ),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.pca"


class ClusteringResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.clustering.ClusteringResult`."""

    @classmethod
    def title(cls, result: ClusteringResult) -> str:
        return f"K-Means Clustering (k={result.k})"

    @classmethod
    def headline(cls, result: ClusteringResult, level: ExpertiseLevel) -> str:
        return f"Grouped {len(result.labels)} row(s) into {result.k} cluster(s)."

    @classmethod
    def sections(
        cls, result: ClusteringResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        return [
            MetricSection(
                title="Inertia",
                value=f"{result.inertia:.4f}",
                caption="Sum of squared distances to each row's cluster center; lower is tighter.",
            ),
            TableSection(
                title="Cluster Sizes",
                columns=("Cluster", "Size"),
                rows=tuple(
                    (str(cluster), str(size))
                    for cluster, size in sorted(result.cluster_sizes.items())
                ),
            ),
            TableSection(
                title="Cluster Centers",
                columns=("Cluster",) + tuple(result.included_columns),
                rows=tuple(
                    (str(cluster_index),)
                    + tuple(
                        f"{center.get(column, 0.0):.4f}"
                        for column in result.included_columns
                    )
                    for cluster_index, center in enumerate(result.cluster_centers)
                ),
            ),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.clustering"
