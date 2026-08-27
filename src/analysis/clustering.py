# File: src/analysis/clustering.py
"""K-means clustering, via scikit-learn.

Standardizes columns before fitting for the same reason
:mod:`~src.analysis.pca` does — unscaled columns with larger numeric
ranges would dominate the distance metric k-means clusters on purely
because of units. Reuses the same ambiguous-type-aware numeric-column
selection as :mod:`~src.analysis.correlation` and :mod:`~src.analysis.pca`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.readers.type_inference import find_ambiguous_type_columns

_logger = get_logger(__name__)

_MIN_K = 2


@dataclass
class ClusteringResult:
    """Result of a k-means clustering run.

    Attributes:
        included_columns: Numeric columns the clustering was computed
            over.
        k: Number of clusters requested and fit.
        labels: Cluster assignment (0-indexed) per row, indexed the
            same as the input dataframe after dropping missing values.
        cluster_sizes: Number of rows assigned to each cluster.
        cluster_centers: Centroid coordinates per cluster, in the
            original (unscaled) column space — keyed by column name
            for readability, since a plain array of scaled coordinates
            would not be directly interpretable against the source
            data.
        inertia: Sum of squared distances of samples to their closest
            cluster center — lower is tighter clustering; primarily
            useful for comparing different values of ``k`` against
            each other (an "elbow" plot), not as a value meaningful in
            isolation.
    """

    included_columns: list[str]
    k: int
    labels: pd.Series
    cluster_sizes: dict[int, int]
    cluster_centers: list[dict[str, float]]
    inertia: float


def k_means_clustering(
    dataframe: pd.DataFrame,
    k: int,
    columns: list[str] | None = None,
    random_state: int = 42,
) -> ClusteringResult:
    """Cluster ``dataframe``'s rows into ``k`` groups by their numeric columns.

    Args:
        dataframe: The source data.
        k: Number of clusters. Must be at least 2 (a single cluster is
            not a clustering) and no more than the number of rows
            available.
        columns: Which columns to cluster on. If omitted, every
            genuinely numeric (non-ambiguous-type) column is used.
        random_state: Seed for k-means' centroid initialization, for
            reproducible results across repeated calls with the same
            data — matches
            :mod:`~src.forecasting.model_comparison`'s holdout split
            using a fixed convention rather than an unseeded default
            that would silently vary run to run.

    Raises:
        ServiceError: If any named column does not exist or is not
            numeric, fewer than 2 numeric columns are available,
            ``k`` is below 2, or ``k`` exceeds the number of complete
            rows available.
    """
    if columns is not None:
        missing = [c for c in columns if c not in dataframe.columns]
        if missing:
            raise ServiceError(
                f"Column(s) not found: {', '.join(missing)}. Available "
                f"columns: {', '.join(str(c) for c in dataframe.columns)}."
            )
        non_numeric = [
            c for c in columns if not pd.api.types.is_numeric_dtype(dataframe[c])
        ]
        if non_numeric:
            raise ServiceError(
                f"Column(s) must be numeric for clustering: {', '.join(non_numeric)}."
            )
        included_columns = list(columns)
    else:
        ambiguous_columns = find_ambiguous_type_columns(dataframe)
        included_columns = [
            c
            for c in dataframe.columns
            if c not in ambiguous_columns
            and pd.api.types.is_numeric_dtype(dataframe[c])
        ]

    if len(included_columns) < 2:
        raise ServiceError(
            f"Clustering requires at least 2 numeric columns; found "
            f"{len(included_columns)}."
        )

    working = dataframe[included_columns].dropna()

    if k < _MIN_K:
        raise ServiceError(f"k must be at least {_MIN_K}; got {k}.")
    if k > len(working):
        raise ServiceError(
            f"k ({k}) cannot exceed the number of complete rows "
            f"available ({len(working)})."
        )

    scaler = StandardScaler()
    scaled = scaler.fit_transform(working)

    model = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    labels = model.fit_predict(scaled)

    centers_original_space = scaler.inverse_transform(model.cluster_centers_)
    centers = [
        {
            col: float(centers_original_space[i][j])
            for j, col in enumerate(included_columns)
        }
        for i in range(k)
    ]

    label_series = pd.Series(labels, index=working.index, name="cluster")
    sizes = {
        int(cluster_id): int(count)
        for cluster_id, count in label_series.value_counts().items()
    }

    _logger.info(
        "K-means clustering: k=%d over %d column(s), %d rows, inertia=%.4f.",
        k,
        len(included_columns),
        len(working),
        model.inertia_,
    )

    return ClusteringResult(
        included_columns=[str(c) for c in included_columns],
        k=k,
        labels=label_series,
        cluster_sizes=sizes,
        cluster_centers=centers,
        inertia=float(model.inertia_),
    )
