# File: src/analysis/pca.py
"""Principal component analysis, via scikit-learn.

Standardizes each included column (zero mean, unit variance) before
fitting — without this, a column with a much larger numeric scale than
the others would dominate the components purely due to units, not
because it genuinely carries more variance worth explaining. Reuses
:func:`~src.readers.type_inference.find_ambiguous_type_columns` and
the same numeric-column-selection logic as
:mod:`~src.analysis.correlation`, for the same reason: an
ambiguous-type column should not silently participate in a
variance-based method any more than in a correlation matrix.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.readers.type_inference import find_ambiguous_type_columns

_logger = get_logger(__name__)


@dataclass
class PcaResult:
    """Result of a PCA decomposition.

    Attributes:
        included_columns: Numeric columns that went into the analysis.
        explained_variance_ratio: Fraction of total variance each
            component explains, in order.
        cumulative_variance_ratio: Running total of
            ``explained_variance_ratio`` — how much variance the first
            N components explain together.
        component_loadings: For each component, the contribution of
            each original column (keyed by column name) — how much
            that column drives that component.
        transformed: The original rows projected onto the components,
            one column per component (named ``"PC1"``, ``"PC2"``, …).
    """

    included_columns: list[str]
    explained_variance_ratio: list[float]
    cumulative_variance_ratio: list[float]
    component_loadings: list[dict[str, float]]
    transformed: pd.DataFrame


def compute_pca(
    dataframe: pd.DataFrame,
    columns: list[str] | None = None,
    n_components: int | None = None,
) -> PcaResult:
    """Run PCA over ``dataframe``'s genuinely numeric columns.

    Args:
        dataframe: The source data.
        columns: Which columns to include. If omitted, every
            genuinely numeric (non-ambiguous-type) column is used —
            the same inclusion rule
            :func:`~src.analysis.correlation.compute_correlation` uses.
        n_components: How many components to compute. Defaults to the
            number of included columns (the maximum meaningful count).

    Raises:
        ServiceError: If any named column does not exist or is not
            numeric, fewer than 2 numeric columns are available,
            ``n_components`` exceeds the number of included columns,
            or fewer rows remain than columns after dropping missing
            values.
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
                f"Column(s) must be numeric for PCA: {', '.join(non_numeric)}."
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
            f"PCA requires at least 2 numeric columns; found {len(included_columns)}."
        )

    working = dataframe[included_columns].dropna()
    if len(working) < len(included_columns):
        raise ServiceError(
            f"At least as many complete rows as columns are required "
            f"for PCA; found {len(working)} rows for "
            f"{len(included_columns)} columns."
        )

    resolved_n_components = n_components or len(included_columns)
    if resolved_n_components > len(included_columns):
        raise ServiceError(
            f"n_components ({resolved_n_components}) cannot exceed the "
            f"number of included columns ({len(included_columns)})."
        )

    scaled = StandardScaler().fit_transform(working)
    model = PCA(n_components=resolved_n_components)
    transformed_values = model.fit_transform(scaled)

    component_names = [f"PC{i + 1}" for i in range(resolved_n_components)]
    cumulative = 0.0
    cumulative_ratios = []
    for ratio in model.explained_variance_ratio_:
        cumulative += float(ratio)
        cumulative_ratios.append(cumulative)

    loadings = [
        {col: float(model.components_[i][j]) for j, col in enumerate(included_columns)}
        for i in range(resolved_n_components)
    ]

    _logger.info(
        "PCA over %d column(s), %d component(s): %.1f%% cumulative variance explained.",
        len(included_columns),
        resolved_n_components,
        cumulative_ratios[-1] * 100,
    )

    return PcaResult(
        included_columns=[str(c) for c in included_columns],
        explained_variance_ratio=[float(r) for r in model.explained_variance_ratio_],
        cumulative_variance_ratio=cumulative_ratios,
        component_loadings=loadings,
        transformed=pd.DataFrame(
            transformed_values, columns=component_names, index=working.index
        ),
    )
