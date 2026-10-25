# File: apps/api/tests/test_web_stage_parity.py
"""``RAW_RUNNERS`` (hand-copied in ``stages/execute.py``) cannot drift from the core's tool handlers.

The raw-runner table calls the core's analysis / forecasting functions with the same parameters and
defaults as ``uadas_core.ai.tool_registry``'s handlers, but it is a copy. Name-only parity would let a
default change in one place silently produce different results over the web than in the AI chat, so
this file compares, for **every** result operation of the catalog (18 today): (1) the runner's and the
handler's parameter names and defaults, and (2) the *call actually made* to the underlying core function
-- both paths are run with the function replaced by a recorder, and the recorded, signature-normalised
arguments must be equal. The detectors are themselves tested against a deliberately drifted runner.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest

from uadas_api.stages import catalog, execute
from uadas_api.stages.catalog import OperationKind
from uadas_core.ai import tool_registry
from uadas_core.models import Dataset
from uadas_core.services.analysis_orchestrator_service import PipelineStage

FRAME = pd.DataFrame(
    {"g": ["a", "b"] * 6, "x": range(12), "y": range(12), "t": range(12)}
)
FORECAST = {"date_column": "t", "value_column": "x", "periods": 3}
SAMPLE_PARAMS: dict[str, dict[str, Any]] = {
    "profile_dataset": {},
    "aggregate": {"group_by": ["g"], "agg_column": "x", "agg_function": "sum"},
    "cross_tabulate": {"row_column": "g", "column_column": "g"},
    "compute_correlation": {"method": "spearman"},
    "independent_t_test": {
        "value_column": "x",
        "group_column": "g",
        "group_a": "a",
        "group_b": "b",
        "equal_variance": True,
    },
    "paired_t_test": {"column_a": "x", "column_b": "y"},
    "one_way_anova": {"value_column": "x", "group_column": "g"},
    "chi_square_test": {"row_column": "g", "column_column": "g"},
    "linear_regression": {"target_column": "y", "feature_columns": ["x"]},
    "check_normality": {"column": "x", "method": "dagostino_pearson"},
    "compute_pca": {"columns": ["x", "y"], "n_components": 2},
    "k_means_clustering": {"k": 2, "columns": ["x", "y"]},
    "forecast_exponential_smoothing": {
        **FORECAST,
        "trend": "mul",
        "seasonal": "add",
        "seasonal_periods": 4,
    },
    "forecast_prophet": dict(FORECAST),
    "forecast_linear_regression": {**FORECAST, "degree": 2},
    "forecast_arima": {**FORECAST, "seasonal": True, "seasonal_periods": 4},
    "forecast_random_forest": dict(FORECAST),
    "compare_forecast_models": dict(FORECAST),
}
# Each case is also run with only the required parameters, so a drifted *default* shows up too.
REQUIRED_ONLY: dict[str, dict[str, Any]] = {
    name: {k: v for k, v in params.items() if k in _req}
    for name, params in SAMPLE_PARAMS.items()
    for _req in [
        set(
            next(t for t in tool_registry.TOOLS if t.name == name).input_schema.get(
                "required", []
            )
        )
    ]
}


class _Stop(Exception):
    """Raised by the recorder: we only want the call, not the computation."""


def _result_operations() -> list[str]:
    return [
        op.name
        for stage in PipelineStage
        for op in catalog.operations(stage)
        if op.kind is OperationKind.RESULT
    ]


def _signature_drift(name: str, runner: Callable[..., Any]) -> list[str]:
    """Differences in parameter names / defaults between a runner and the registry handler."""
    handler = tool_registry.get_tool_by_name(name).handler
    ours = list(inspect.signature(runner).parameters.values())[1:]
    theirs = list(inspect.signature(handler).parameters.values())[1:]
    problems = []
    if [p.name for p in ours] != [p.name for p in theirs]:
        problems.append(
            f"{name}: parameter names {[p.name for p in ours]} != {[p.name for p in theirs]}"
        )
    for a, b in zip(ours, theirs, strict=False):
        if a.default != b.default:
            problems.append(f"{name}.{a.name}: default {a.default!r} != {b.default!r}")
    return problems


def _normalise(
    function: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    bound = inspect.signature(function).bind(*args, **kwargs)
    bound.apply_defaults()
    return {
        key: "<frame>" if isinstance(value, pd.DataFrame | Dataset) else value
        for key, value in bound.arguments.items()
    }


def _recorded_call(
    name: str,
    run: Callable[[Dataset], Any],
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
) -> dict[str, Any]:
    original = getattr(
        tool_registry, name
    )  # the real function, for signature normalisation
    seen: list[dict[str, Any]] = []

    def recorder(*args: Any, **kwargs: Any) -> Any:
        seen.append(_normalise(original, args, kwargs))
        raise _Stop

    monkeypatch.setattr(module, name, recorder)
    with pytest.raises(_Stop):
        run(Dataset(name="d", dataframe=FRAME.copy(), source_format="csv"))
    monkeypatch.undo()
    return seen[0]


def _call_drift(
    name: str,
    params: dict[str, Any],
    runner: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any] | None:
    handler = tool_registry.get_tool_by_name(name).handler
    raw = _recorded_call(name, lambda ds: runner(ds, **params), monkeypatch, execute)
    via_tool = _recorded_call(
        name, lambda ds: handler(ds, **params), monkeypatch, tool_registry
    )
    return None if raw == via_tool else {"raw": raw, "tool": via_tool}


def test_the_sample_parameters_cover_exactly_the_result_operations() -> None:
    assert set(SAMPLE_PARAMS) == set(_result_operations()) == set(execute.RAW_RUNNERS)
    assert len(SAMPLE_PARAMS) == 18


@pytest.mark.parametrize("name", sorted(SAMPLE_PARAMS))
def test_a_runner_has_the_same_parameters_and_defaults_as_its_handler(
    name: str,
) -> None:
    assert _signature_drift(name, execute.RAW_RUNNERS[name]) == []


@pytest.mark.parametrize("name", sorted(SAMPLE_PARAMS))
@pytest.mark.parametrize("variant", ["all", "required"])
def test_a_runner_calls_the_core_function_exactly_as_the_handler_does(
    name: str, variant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    params = SAMPLE_PARAMS[name] if variant == "all" else REQUIRED_ONLY[name]
    assert _call_drift(name, params, execute.RAW_RUNNERS[name], monkeypatch) is None


def test_the_detectors_notice_a_runner_that_has_drifted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The twin of the tests above: a copy with another default (or another call) is reported."""
    wrong_default = lambda ds, method="kendall": execute.compute_correlation(
        ds.dataframe, method=method
    )
    assert _signature_drift(
        "compute_correlation", wrong_default
    )  # the handler's default is "pearson"
    wrong_call = lambda ds, method="pearson": execute.compute_correlation(
        ds.dataframe, method="kendall"
    )
    assert (
        _call_drift(
            "compute_correlation", {"method": "spearman"}, wrong_call, monkeypatch
        )
        is not None
    )
    same = lambda ds, method="pearson": execute.compute_correlation(
        ds.dataframe, method=method
    )
    assert (
        _call_drift("compute_correlation", {"method": "spearman"}, same, monkeypatch)
        is None
    )
