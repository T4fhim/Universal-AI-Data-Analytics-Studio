# File: src/analysis/regression.py
"""Ordinary least squares linear regression (simple or multiple), via statsmodels.

Uses statsmodels rather than scikit-learn because the primary
consumer of this module (the AI assistant's explanation tool, per
CLAUDE.md's :class:`~src.analysis.explanation.Explanation` shape and
this project's "Explain Everything" defining feature) needs the
inferential statistics (p-values, R-squared) that statsmodels' ``OLS``
reports natively — scikit-learn's ``LinearRegression`` deliberately
omits these, since it targets prediction pipelines rather than
statistical inference. Distinct from
:mod:`~src.forecasting.linear_regression_forecast`, which uses the
same underlying model for a different purpose (projecting a time
series forward) with a different result shape
(:class:`~src.forecasting.exponential_smoothing.ForecastResult`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)


@dataclass
class RegressionResult:
    """Result of an OLS regression.

    Attributes:
        target_column: The dependent (predicted) variable.
        feature_columns: The independent (predictor) variable(s), in
            the order their coefficients appear in ``coefficients``.
        coefficients: Fitted coefficient per feature, keyed by column
            name (does not include the intercept).
        intercept: Fitted intercept term.
        p_values: p-value per feature, keyed by column name (does not
            include the intercept).
        r_squared: Coefficient of determination.
        adjusted_r_squared: R-squared adjusted for the number of
            predictors — the more meaningful figure once more than one
            feature is used, since plain R-squared never decreases as
            features are added regardless of whether they help.
        observation_count: Number of rows the model was fit on (after
            dropping missing values).
        predicted_values: Fitted values for the rows the model was
            trained on, indexed the same as ``dataframe`` after
            dropping missing values. Excluded from the dataclass's
            ``repr`` (``field(repr=False)``) since it can be as long
            as the input data and would otherwise dominate any log
            line or debugger display of the result.
    """

    target_column: str
    feature_columns: list[str]
    coefficients: dict[str, float]
    intercept: float
    p_values: dict[str, float]
    r_squared: float
    adjusted_r_squared: float
    observation_count: int
    predicted_values: pd.Series = field(repr=False)


def linear_regression(
    dataframe: pd.DataFrame, target_column: str, feature_columns: list[str]
) -> RegressionResult:
    """Fit ``target_column ~ feature_columns`` via ordinary least squares.

    Args:
        dataframe: The source data.
        target_column: Numeric column to predict.
        feature_columns: One or more numeric columns to predict it
            from. A single column runs simple linear regression;
            more than one runs multiple regression — same function,
            since OLS handles both without a separate code path.

    Raises:
        ServiceError: If a named column does not exist, ``target_column``
            or any ``feature_columns`` entry is not numeric,
            ``feature_columns`` is empty, or fewer rows remain after
            dropping missing values than there are parameters to fit
            (features + intercept) — an underdetermined model cannot
            be fit meaningfully.
    """
    if not feature_columns:
        raise ServiceError("feature_columns must contain at least one column.")

    all_columns = [target_column] + list(feature_columns)
    missing = [c for c in all_columns if c not in dataframe.columns]
    if missing:
        raise ServiceError(
            f"Column(s) not found: {', '.join(missing)}. Available "
            f"columns: {', '.join(str(c) for c in dataframe.columns)}."
        )

    non_numeric = [
        c for c in all_columns if not pd.api.types.is_numeric_dtype(dataframe[c])
    ]
    if non_numeric:
        raise ServiceError(
            f"Column(s) must be numeric for regression: {', '.join(non_numeric)}."
        )

    working = dataframe[all_columns].dropna()
    min_required = len(feature_columns) + 1  # +1 for the intercept
    if len(working) <= min_required:
        raise ServiceError(
            f"At least {min_required + 1} complete rows are required to "
            f"fit a regression with {len(feature_columns)} feature(s); "
            f"found {len(working)} after dropping missing values."
        )

    design_matrix = sm.add_constant(working[feature_columns])
    target = working[target_column]

    try:
        model = sm.OLS(target, design_matrix).fit()
    except Exception as exc:
        raise ServiceError(f"Failed to fit regression model: {exc}") from exc

    _logger.info(
        "Linear regression: '%s' ~ %s (%d observations), R^2=%.4f",
        target_column,
        feature_columns,
        len(working),
        model.rsquared,
    )

    return RegressionResult(
        target_column=target_column,
        feature_columns=list(feature_columns),
        coefficients={c: float(model.params[c]) for c in feature_columns},
        intercept=float(model.params["const"]),
        p_values={c: float(model.pvalues[c]) for c in feature_columns},
        r_squared=float(model.rsquared),
        adjusted_r_squared=float(model.rsquared_adj),
        observation_count=len(working),
        predicted_values=pd.Series(np.asarray(model.fittedvalues), index=working.index),
    )
