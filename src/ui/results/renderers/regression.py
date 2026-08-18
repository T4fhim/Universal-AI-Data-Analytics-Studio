# File: src/ui/results/renderers/regression.py
"""Renders :class:`~src.analysis.regression.RegressionResult` -- ``linear_regression``'s result."""

from __future__ import annotations

from src.analysis.regression import RegressionResult
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.base_result_renderer import (
    AssumptionsSection,
    BaseResultRenderer,
    KeyValueSection,
    MetricSection,
    ResultSection,
    TableSection,
)

_ASSUMPTIONS = (
    "The relationship between features and target is linear.",
    "Residuals are independent and approximately normally distributed.",
    "Residuals have constant variance across the range of predicted values (homoscedasticity).",
    "Features are not highly correlated with each other (limited multicollinearity).",
)


class RegressionResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.regression.RegressionResult`."""

    @classmethod
    def title(cls, result: RegressionResult) -> str:
        return f"Linear Regression: {result.target_column}"

    @classmethod
    def headline(cls, result: RegressionResult, level: ExpertiseLevel) -> str:
        return (
            f"The model explains {result.r_squared * 100:.1f}% of the variance in "
            f"{result.target_column} (R-squared)."
        )

    @classmethod
    def sections(
        cls, result: RegressionResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        return [
            MetricSection(
                title="R-Squared",
                value=f"{result.r_squared:.4f}",
                caption=f"Adjusted R-squared: {result.adjusted_r_squared:.4f}.",
            ),
            KeyValueSection(
                title="Summary",
                items=(
                    ("Target", result.target_column),
                    ("Intercept", f"{result.intercept:.4f}"),
                    ("Observations", str(result.observation_count)),
                ),
            ),
            TableSection(
                title="Coefficients",
                columns=("Feature", "Coefficient", "P-Value"),
                rows=tuple(
                    (
                        feature,
                        f"{result.coefficients.get(feature, 0.0):.4f}",
                        f"{result.p_values.get(feature, 1.0):.4f}",
                    )
                    for feature in result.feature_columns
                ),
            ),
            AssumptionsSection(title="Assumptions", assumptions=_ASSUMPTIONS),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.regression"
