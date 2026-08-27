# File: tests/ui/results/test_result_renderer_registry.py
"""Registry tests, including milestone 22's acceptance criterion 2's contract test.

No ``qapp`` fixture anywhere in this file -- the registry itself (``result_renderer_registry.py``)
imports no Qt, matching every other file under ``tests/ui/results/`` that tests the Qt-free half
of this package.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ai.tool_registry import TOOLS
from src.analysis.aggregation import aggregate
from src.analysis.anova import AnovaResult, one_way_anova
from src.analysis.chi_square import ChiSquareResult, chi_square_test
from src.analysis.clustering import ClusteringResult, k_means_clustering
from src.analysis.correlation import CorrelationResult, compute_correlation
from src.analysis.crosstab import cross_tabulate
from src.analysis.dataset_profile import DatasetProfile, profile_dataset
from src.analysis.normality import NormalityResult, check_normality
from src.analysis.pca import PcaResult, compute_pca
from src.analysis.regression import RegressionResult, linear_regression
from src.analysis.t_test import TTestResult, independent_t_test, paired_t_test
from src.core.exceptions import ServiceError
from src.services.workspace_service import Dataset
from src.ui.results import result_renderer_registry
from src.ui.results.renderers.generic import GenericResultRenderer
from src.ui.results.renderers.profiling import DatasetProfileRenderer


# The 12 orphaned src.analysis functions this milestone's acceptance criterion 2 names,
# mapped to a callable(dataset) -> real result object -- i.e. exactly what a caller of that
# tool_registry entry actually gets back from src.analysis itself, before src.ai.tool_registry's
# own handler flattens it into a JSON dict (see src/ui/workbench/pages/analyze_page.py's own
# docstring for why that flattening matters and why this test does not go through the handler).
def _make_dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
            "group": ["a", "a", "a", "b", "b", "b", "c", "c", "c"],
            "category": ["x", "y", "x", "y", "x", "y", "x", "y", "x"],
            "other": [8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.5],
        }
    )
    return Dataset(name="demo", dataframe=frame, source_format="csv")


_ANALYSIS_TOOL_TO_REAL_CALL: dict[str, object] = {
    "profile_dataset": lambda ds: profile_dataset(ds),
    "compute_correlation": lambda ds: compute_correlation(ds.dataframe),
    "aggregate": lambda ds: aggregate(ds.dataframe, ["group"], "value", "mean"),
    "cross_tabulate": lambda ds: cross_tabulate(ds.dataframe, "group", "category"),
    "independent_t_test": lambda ds: independent_t_test(
        ds.dataframe, "value", "group", "a", "b"
    ),
    "paired_t_test": lambda ds: paired_t_test(ds.dataframe, "value", "other"),
    "one_way_anova": lambda ds: one_way_anova(ds.dataframe, "value", "group"),
    "chi_square_test": lambda ds: chi_square_test(ds.dataframe, "group", "category"),
    "linear_regression": lambda ds: linear_regression(ds.dataframe, "value", ["other"]),
    "check_normality": lambda ds: check_normality(ds.dataframe, "value"),
    "compute_pca": lambda ds: compute_pca(ds.dataframe, columns=["value", "other"]),
    "k_means_clustering": lambda ds: k_means_clustering(
        ds.dataframe, 2, columns=["value", "other"]
    ),
}


def test_every_analysis_producing_tool_in_the_registry_has_a_real_call_mapped() -> None:
    """Guards the test itself: every tool name this test believes is analysis-producing must
    actually be a registered tool_registry.TOOLS entry -- catching a typo in this test's own
    dict before it silently under-tests the acceptance criterion."""
    tool_names = {t.name for t in TOOLS}
    for name in _ANALYSIS_TOOL_TO_REAL_CALL:
        assert name in tool_names, f"{name!r} is not a registered tool_registry tool"


@pytest.mark.parametrize("tool_name", sorted(_ANALYSIS_TOOL_TO_REAL_CALL))
def test_every_orphaned_analysis_function_resolves_via_get_renderer(
    tool_name: str,
) -> None:
    """Milestone 22's acceptance criterion 2: iterate tool_registry's tool metadata and assert
    each analysis-producing tool's real result type resolves via
    result_renderer_registry.get_renderer.

    tool_registry.ToolDefinition carries no explicit "return type" field (its handlers all
    return a JSON-friendly dict or Dataset -- see that module's own docstring); this test calls
    the underlying src.analysis function directly, the same real object
    src/ui/workbench/pages/analyze_page.py's dispatch table hands to ResultCard, and resolves
    *that* object's type -- the type get_renderer is actually asked to resolve in the running
    application.
    """
    dataset = _make_dataset()
    result = _ANALYSIS_TOOL_TO_REAL_CALL[tool_name](dataset)

    renderer = result_renderer_registry.get_renderer(type(result))

    assert (
        renderer is not None
    )  # get_renderer never raises/returns None -- see its own docstring


def test_nine_of_the_twelve_have_a_dedicated_non_generic_renderer() -> None:
    """aggregate/cross_tabulate return a plain DataFrame (no dedicated dataclass -- see
    result_renderer_registry's own docstring), so they legitimately resolve to the generic
    fallback; the other 10 calls (profile_dataset plus the 9 dataclass-returning functions --
    paired_t_test and independent_t_test share TTestResult) must resolve to a real renderer.
    """
    dataset = _make_dataset()
    dedicated_expected = set(_ANALYSIS_TOOL_TO_REAL_CALL) - {
        "aggregate",
        "cross_tabulate",
    }

    for tool_name in dedicated_expected:
        result = _ANALYSIS_TOOL_TO_REAL_CALL[tool_name](dataset)
        renderer = result_renderer_registry.get_renderer(type(result))
        assert (
            renderer is not GenericResultRenderer
        ), f"{tool_name} fell through to the generic renderer"

    for tool_name in ("aggregate", "cross_tabulate"):
        result = _ANALYSIS_TOOL_TO_REAL_CALL[tool_name](dataset)
        renderer = result_renderer_registry.get_renderer(type(result))
        assert renderer is GenericResultRenderer


def test_get_renderer_resolves_exact_type() -> None:
    assert (
        result_renderer_registry.get_renderer(DatasetProfile) is DatasetProfileRenderer
    )


def test_get_renderer_resolves_via_mro_walk() -> None:
    class _DatasetProfileSubclass(DatasetProfile):
        pass

    assert (
        result_renderer_registry.get_renderer(_DatasetProfileSubclass)
        is DatasetProfileRenderer
    )


def test_get_renderer_falls_back_to_generic_for_an_unknown_type() -> None:
    class _NeverRegistered:
        pass

    assert (
        result_renderer_registry.get_renderer(_NeverRegistered) is GenericResultRenderer
    )


def test_register_renderer_rejects_a_duplicate_result_type() -> None:
    with pytest.raises(ServiceError):
        result_renderer_registry.register_renderer(
            DatasetProfile, DatasetProfileRenderer
        )


def test_unregister_then_reregister_round_trips() -> None:
    try:
        result_renderer_registry.unregister_renderer(TTestResult)
        assert (
            result_renderer_registry.get_renderer(TTestResult) is GenericResultRenderer
        )
    finally:
        from src.ui.results.renderers.statistical_tests import TTestResultRenderer

        result_renderer_registry.register_renderer(TTestResult, TTestResultRenderer)
    assert (
        result_renderer_registry.get_renderer(TTestResult).__name__
        == "TTestResultRenderer"
    )


def test_list_renderers_covers_every_dedicated_result_type() -> None:
    registered = result_renderer_registry.list_renderers()
    for result_type in (
        DatasetProfile,
        CorrelationResult,
        TTestResult,
        AnovaResult,
        ChiSquareResult,
        NormalityResult,
        RegressionResult,
        PcaResult,
        ClusteringResult,
    ):
        assert result_type in registered
