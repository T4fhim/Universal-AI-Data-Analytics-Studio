# File: src/ui/results/renderers/statistical_tests.py
"""Renderers for the four hypothesis-test result types: t-test, ANOVA, chi-square, normality.

Grouped together (rather than one file each) because they share a real shape: a test statistic,
a p-value, a significance flag, and a fixed set of named assumptions the test relies on but does
not itself verify -- see :class:`~src.analysis.explanation.Explanation.assumptions`'s own
docstring for why "named, not verified" is the right framing. Milestone 22's acceptance
criterion ("Running a t-test from the Analyze page renders a ``ResultCard`` with statistic,
p-value, and an ``AssumptionsSection`` -- with no API key configured") is what
:class:`TTestResultRenderer` exists to satisfy: every field it needs comes straight off
:class:`~src.analysis.t_test.TTestResult`, no AI call involved.
"""

from __future__ import annotations

from src.analysis.anova import AnovaResult
from src.analysis.chi_square import ChiSquareResult
from src.analysis.normality import NormalityResult
from src.analysis.t_test import TTestResult
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.base_result_renderer import (
    AssumptionsSection,
    BaseResultRenderer,
    KeyValueSection,
    MetricSection,
    ResultSection,
    TableSection,
)
from src.ui.results.result_view import significance_caption

# Named per test_type -- an independent t-test additionally assumes equal variance only when
# the caller opted into Student's (rather than Welch's) formulation, which TTestResult does not
# itself record (see that dataclass's own docstring: it has no `equal_variance` field), so this
# list stays common to both variants rather than trying to guess which formulation ran.
_T_TEST_ASSUMPTIONS = (
    "The two groups' values are independent of each other.",
    "Each group's values are approximately normally distributed (or the sample is large "
    "enough for the Central Limit Theorem to apply).",
    "Observations within each group do not influence one another.",
)

_ANOVA_ASSUMPTIONS = (
    "Each group's values are approximately normally distributed.",
    "The groups have approximately equal variances (homoscedasticity).",
    "Observations are independent both within and across groups.",
)

_CHI_SQUARE_ASSUMPTIONS = (
    "Observations are independent of each other.",
    "Expected frequency in each contingency-table cell is at least 5 for the test statistic "
    "to be reliably chi-square distributed.",
)

_NORMALITY_ASSUMPTIONS = (
    "The sample was drawn independently and identically from the population being tested.",
    "The test's own null hypothesis is 'the data is normally distributed' -- a low p-value is "
    "evidence against normality, not proof of it, and a high p-value is failure to reject "
    "normality, not proof of it either.",
)


class TTestResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.t_test.TTestResult` (independent and paired)."""

    @classmethod
    def title(cls, result: TTestResult) -> str:
        return f"{result.test_type.title()} T-Test"

    @classmethod
    def headline(cls, result: TTestResult, level: ExpertiseLevel) -> str:
        verdict = (
            "a statistically significant"
            if result.significant_at_0_05
            else "no statistically significant"
        )
        return f"Found {verdict} difference between the two groups' means."

    @classmethod
    def sections(
        cls, result: TTestResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        return [
            MetricSection(
                title="T-Statistic",
                value=f"{result.statistic:.4f}",
                caption=f"{result.degrees_of_freedom:.1f} degrees of freedom.",
            ),
            MetricSection(
                title="P-Value",
                value=f"{result.p_value:.4f}",
                caption=significance_caption(
                    result.p_value, result.significant_at_0_05
                ),
            ),
            KeyValueSection(
                title="Group Means",
                items=(
                    ("Group A mean", f"{result.group_a_mean:.4f}"),
                    ("Group B mean", f"{result.group_b_mean:.4f}"),
                ),
            ),
            AssumptionsSection(title="Assumptions", assumptions=_T_TEST_ASSUMPTIONS),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.t_test"


class AnovaResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.anova.AnovaResult`."""

    @classmethod
    def title(cls, result: AnovaResult) -> str:
        return "One-Way ANOVA"

    @classmethod
    def headline(cls, result: AnovaResult, level: ExpertiseLevel) -> str:
        verdict = (
            "at least one group mean differs"
            if result.significant_at_0_05
            else "no group mean differs"
        )
        return f"Across {len(result.group_means)} group(s), {verdict} significantly."

    @classmethod
    def sections(
        cls, result: AnovaResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        return [
            MetricSection(
                title="F-Statistic",
                value=f"{result.f_statistic:.4f}",
            ),
            MetricSection(
                title="P-Value",
                value=f"{result.p_value:.4f}",
                caption=significance_caption(
                    result.p_value, result.significant_at_0_05
                ),
            ),
            TableSection(
                title="Group Means",
                columns=("Group", "Mean", "Size"),
                rows=tuple(
                    (name, f"{mean:.4f}", str(result.group_sizes.get(name, 0)))
                    for name, mean in result.group_means.items()
                ),
            ),
            AssumptionsSection(title="Assumptions", assumptions=_ANOVA_ASSUMPTIONS),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.anova"


class ChiSquareResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.chi_square.ChiSquareResult`."""

    @classmethod
    def title(cls, result: ChiSquareResult) -> str:
        return "Chi-Square Test of Independence"

    @classmethod
    def headline(cls, result: ChiSquareResult, level: ExpertiseLevel) -> str:
        verdict = (
            "are not independent"
            if result.significant_at_0_05
            else "appear independent"
        )
        return f"The two columns {verdict} of each other."

    @classmethod
    def sections(
        cls, result: ChiSquareResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        table = result.contingency_table
        columns = tuple(str(c) for c in table.columns)
        return [
            MetricSection(
                title="Chi-Square Statistic",
                value=f"{result.statistic:.4f}",
                caption=f"{result.degrees_of_freedom} degrees of freedom.",
            ),
            MetricSection(
                title="P-Value",
                value=f"{result.p_value:.4f}",
                caption=significance_caption(
                    result.p_value, result.significant_at_0_05
                ),
            ),
            TableSection(
                title="Contingency Table",
                columns=("",) + columns,
                rows=tuple(
                    (str(row_label),) + tuple(str(v) for v in row_values)
                    for row_label, row_values in table.iterrows()
                ),
            ),
            AssumptionsSection(
                title="Assumptions", assumptions=_CHI_SQUARE_ASSUMPTIONS
            ),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.chi_square"


class NormalityResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.normality.NormalityResult`."""

    @classmethod
    def title(cls, result: NormalityResult) -> str:
        return f"Normality Test ({result.method.replace('_', ' ').title()})"

    @classmethod
    def headline(cls, result: NormalityResult, level: ExpertiseLevel) -> str:
        verdict = "appears" if result.appears_normal_at_0_05 else "does not appear"
        return f"The column {verdict} normally distributed at the 0.05 level."

    @classmethod
    def sections(
        cls, result: NormalityResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        return [
            MetricSection(
                title="Test Statistic",
                value=f"{result.statistic:.4f}",
                caption=f"Based on {result.observation_count} observation(s).",
            ),
            MetricSection(
                title="P-Value",
                value=f"{result.p_value:.4f}",
                caption=significance_caption(
                    result.p_value, not result.appears_normal_at_0_05
                ),
            ),
            AssumptionsSection(title="Assumptions", assumptions=_NORMALITY_ASSUMPTIONS),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.normality"
