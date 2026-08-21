# File: tests/ui/results/test_renderers.py
"""Renderer tests: pure Python, zero ``QApplication`` -- deliberately no ``qapp`` fixture import
anywhere in this file, per milestone 22's acceptance criterion "Renderer tests require zero
QApplication -- sections() returns comparable dataclasses."

Each test builds a real result dataclass with plausible numbers (no mocking of
:mod:`src.analysis` itself -- these are the exact dataclasses those functions return) and asserts
against ``sections()``'s output using plain ``==``/``isinstance``, proving
:class:`~src.ui.results.base_result_renderer.ResultSection` values really are comparable
dataclasses, not opaque objects that happen to be constructible.
"""

from __future__ import annotations

import pandas as pd

from src.analysis.anova import AnovaResult
from src.analysis.chi_square import ChiSquareResult
from src.analysis.clustering import ClusteringResult
from src.analysis.column_profile import ColumnProfile
from src.analysis.correlation import CorrelationResult
from src.analysis.dataset_profile import DatasetProfile
from src.analysis.normality import NormalityResult
from src.analysis.pca import PcaResult
from src.analysis.regression import RegressionResult
from src.analysis.t_test import TTestResult
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.base_result_renderer import (
    AssumptionsSection,
    KeyValueSection,
    MetricSection,
    ProseSection,
    TableSection,
)
from src.ui.results.renderers.correlation import CorrelationResultRenderer
from src.ui.results.renderers.generic import GenericResultRenderer
from src.ui.results.renderers.multivariate import (
    ClusteringResultRenderer,
    PcaResultRenderer,
)
from src.ui.results.renderers.profiling import DatasetProfileRenderer
from src.ui.results.renderers.regression import RegressionResultRenderer
from src.ui.results.renderers.statistical_tests import (
    AnovaResultRenderer,
    ChiSquareResultRenderer,
    NormalityResultRenderer,
    TTestResultRenderer,
)


def test_t_test_renderer_sections_include_statistic_p_value_and_assumptions() -> None:
    result = TTestResult(
        statistic=2.5,
        p_value=0.013,
        degrees_of_freedom=18.0,
        group_a_mean=10.2,
        group_b_mean=8.7,
        test_type="independent",
        significant_at_0_05=True,
    )

    sections = TTestResultRenderer.sections(result, ExpertiseLevel.BEGINNER)

    metric_titles = {s.title for s in sections if isinstance(s, MetricSection)}
    assert "T-Statistic" in metric_titles
    assert "P-Value" in metric_titles
    statistic_section = next(
        s for s in sections if isinstance(s, MetricSection) and s.title == "T-Statistic"
    )
    assert statistic_section.value == "2.5000"

    assumptions = [s for s in sections if isinstance(s, AssumptionsSection)]
    assert len(assumptions) == 1
    assert len(assumptions[0].assumptions) > 0

    assert TTestResultRenderer.title(result) == "Independent T-Test"
    assert TTestResultRenderer.help_anchor() == "results.t_test"


def test_t_test_renderer_headline_reflects_significance() -> None:
    significant = TTestResult(1.0, 0.001, 10.0, 1.0, 2.0, "independent", True)
    not_significant = TTestResult(1.0, 0.8, 10.0, 1.0, 2.0, "independent", False)

    assert "a statistically significant" in TTestResultRenderer.headline(
        significant, ExpertiseLevel.ANALYST
    )
    assert "no statistically significant" in TTestResultRenderer.headline(
        not_significant, ExpertiseLevel.ANALYST
    )


def test_anova_renderer_sections_are_comparable_dataclasses() -> None:
    result = AnovaResult(
        f_statistic=4.2,
        p_value=0.02,
        group_means={"a": 1.0, "b": 2.0},
        group_sizes={"a": 5, "b": 5},
        significant_at_0_05=True,
    )
    sections = AnovaResultRenderer.sections(result, ExpertiseLevel.RESEARCHER)
    table = next(s for s in sections if isinstance(s, TableSection))
    assert table == TableSection(
        title="Group Means",
        columns=("Group", "Mean", "Size"),
        rows=(("a", "1.0000", "5"), ("b", "2.0000", "5")),
    )
    assert any(isinstance(s, AssumptionsSection) for s in sections)


def test_chi_square_renderer_sections_include_contingency_table() -> None:
    table_df = pd.DataFrame({"x": [10, 20], "y": [5, 15]}, index=["row1", "row2"])
    result = ChiSquareResult(
        statistic=3.1,
        p_value=0.04,
        degrees_of_freedom=1,
        contingency_table=table_df,
        significant_at_0_05=True,
    )
    sections = ChiSquareResultRenderer.sections(result, ExpertiseLevel.ENGINEER)
    table_sections = [s for s in sections if isinstance(s, TableSection)]
    assert len(table_sections) == 1
    assert table_sections[0].columns == ("", "x", "y")
    assert any(isinstance(s, AssumptionsSection) for s in sections)


def test_normality_renderer_sections() -> None:
    result = NormalityResult(
        method="shapiro_wilk",
        statistic=0.97,
        p_value=0.6,
        appears_normal_at_0_05=True,
        observation_count=40,
    )
    sections = NormalityResultRenderer.sections(result, ExpertiseLevel.STUDENT)
    assert any(isinstance(s, AssumptionsSection) for s in sections)
    metrics = [s for s in sections if isinstance(s, MetricSection)]
    assert {m.title for m in metrics} == {"Test Statistic", "P-Value"}


def test_regression_renderer_sections_include_coefficient_table() -> None:
    result = RegressionResult(
        target_column="y",
        feature_columns=["x1", "x2"],
        coefficients={"x1": 1.5, "x2": -0.3},
        intercept=0.2,
        p_values={"x1": 0.01, "x2": 0.4},
        r_squared=0.85,
        adjusted_r_squared=0.83,
        observation_count=100,
        predicted_values=pd.Series([1.0, 2.0]),
    )
    sections = RegressionResultRenderer.sections(result, ExpertiseLevel.RESEARCHER)
    table = next(s for s in sections if isinstance(s, TableSection))
    assert table.columns == ("Feature", "Coefficient", "P-Value")
    assert table.rows == (("x1", "1.5000", "0.0100"), ("x2", "-0.3000", "0.4000"))
    assert "85.0%" in RegressionResultRenderer.headline(
        result, ExpertiseLevel.DECISION_MAKER
    )


def test_correlation_renderer_sections_include_matrix_and_excluded_columns() -> None:
    matrix = pd.DataFrame({"a": [1.0, 0.5], "b": [0.5, 1.0]}, index=["a", "b"])
    result = CorrelationResult(
        matrix=matrix,
        included_columns=["a", "b"],
        excluded_columns={"c": "non-numeric"},
        method="pearson",
    )
    sections = CorrelationResultRenderer.sections(result, ExpertiseLevel.ANALYST)
    assert any(
        isinstance(s, TableSection) and s.title == "Correlation Matrix"
        for s in sections
    )
    assert any(
        isinstance(s, ProseSection) and "c: non-numeric" in s.text for s in sections
    )


def test_pca_renderer_sections_include_variance_and_loadings() -> None:
    result = PcaResult(
        included_columns=["a", "b"],
        explained_variance_ratio=[0.7, 0.3],
        cumulative_variance_ratio=[0.7, 1.0],
        component_loadings=[{"a": 0.9, "b": 0.1}, {"a": 0.1, "b": 0.9}],
        transformed=pd.DataFrame({"PC1": [1.0], "PC2": [2.0]}),
    )
    sections = PcaResultRenderer.sections(result, ExpertiseLevel.ENGINEER)
    assert any(
        s.title == "Explained Variance" for s in sections if isinstance(s, TableSection)
    )
    assert "100.0%" in PcaResultRenderer.headline(result, ExpertiseLevel.ENGINEER)


def test_clustering_renderer_sections_include_cluster_centers() -> None:
    result = ClusteringResult(
        included_columns=["a", "b"],
        k=2,
        labels=pd.Series([0, 1, 0]),
        cluster_sizes={0: 2, 1: 1},
        cluster_centers=[{"a": 1.0, "b": 2.0}, {"a": 3.0, "b": 4.0}],
        inertia=12.5,
    )
    sections = ClusteringResultRenderer.sections(result, ExpertiseLevel.BEGINNER)
    metric = next(s for s in sections if isinstance(s, MetricSection))
    assert metric.value == "12.5000"


def test_dataset_profile_renderer_sections_flag_ambiguous_columns() -> None:
    column = ColumnProfile(
        name="mixed",
        dtype="object",
        missing_count=1,
        missing_percentage=10.0,
        unique_count=5,
        is_ambiguous_type=True,
        numeric_stats=None,
        top_values=[],
    )
    result = DatasetProfile(
        dataset_name="demo",
        row_count=10,
        column_count=1,
        duplicate_row_count=0,
        memory_usage_bytes=1024,
        column_profiles=[column],
        ambiguous_type_columns=["mixed"],
    )
    sections = DatasetProfileRenderer.sections(result, ExpertiseLevel.BEGINNER)
    assert any(isinstance(s, ProseSection) and "mixed" in s.text for s in sections)
    kv = next(s for s in sections if isinstance(s, KeyValueSection))
    assert ("Rows", "10") in kv.items


def test_generic_renderer_handles_a_dataframe_result() -> None:
    frame = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    sections = GenericResultRenderer.sections(frame, ExpertiseLevel.ANALYST)
    assert len(sections) == 1
    assert isinstance(sections[0], TableSection)
    assert "x" in sections[0].columns


def test_generic_renderer_handles_a_dict_result() -> None:
    sections = GenericResultRenderer.sections({"a": 1, "b": 2}, ExpertiseLevel.ANALYST)
    assert sections == [KeyValueSection(title="Fields", items=(("a", "1"), ("b", "2")))]


def test_generic_renderer_falls_back_to_prose_for_anything_else() -> None:
    sections = GenericResultRenderer.sections(object(), ExpertiseLevel.ANALYST)
    assert isinstance(sections[0], ProseSection)
