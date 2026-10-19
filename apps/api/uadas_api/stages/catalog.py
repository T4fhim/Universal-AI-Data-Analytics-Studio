# File: apps/api/uadas_api/stages/catalog.py
"""What each pipeline stage can run, generated from the core's live registry.

Why derived and not hand-written: the operations, their descriptions and their JSON-Schema
parameters already exist in ``uadas_core.ai.tool_registry`` (the registry the AI chat and the
guided orchestrator dispatch through, so a stage run here and a chat tool call produce identical
results and lineage). :func:`get_anthropic_tool_schemas` is used because it refreshes the one
registry-derived enum (``build_chart``'s ``chart_type``) from the *live* chart registry.

The one thing that cannot be derived is which stage an operation belongs to: the registry is flat.
:data:`STAGE_OPERATIONS` is that mapping (the registry-plus-hardcoded-consumer gap CLAUDE.md warns
about), so ``tests/test_web_stages.py`` pins it in both directions: every registered tool belongs
to exactly one stage, and every name here is a registered tool. A tool added to the core fails that
test until someone decides its stage. Stages with nothing runnable (``upload`` is a multipart
endpoint, ``explain`` needs an AI provider, ``report`` and ``reproduce`` have their own resources)
have an empty catalog -- nothing is stubbed.

Parameters are validated against the tool's own schema (``additionalProperties: false`` added, so
a misspelt parameter is a ``422`` instead of a ``TypeError`` in a worker).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from jsonschema import Draft202012Validator

from uadas_core.ai.tool_registry import get_anthropic_tool_schemas
from uadas_core.services.analysis_orchestrator_service import (
    _STAGE_RATIONALE,
    PipelineStage,
)


class OperationKind(StrEnum):
    """What a stage operation produces."""

    DATASET = "dataset"  # a derived dataset (cleaning): parent_dataset_id + derivation_description
    RESULT = "result"  # result sections (profile, statistics, forecasts)
    FIGURE = "figure"  # a Plotly figure


STAGE_OPERATIONS: dict[PipelineStage, tuple[str, ...]] = {
    PipelineStage.UPLOAD: (),
    PipelineStage.UNDERSTAND: ("profile_dataset",),
    PipelineStage.CLEAN: (
        "drop_missing_values",
        "fill_missing_values",
        "drop_duplicates",
        "normalize_text",
        "convert_type",
    ),
    PipelineStage.EXPLORE: ("aggregate", "cross_tabulate"),
    PipelineStage.ANALYZE: (
        "compute_correlation",
        "independent_t_test",
        "paired_t_test",
        "one_way_anova",
        "chi_square_test",
        "linear_regression",
        "check_normality",
        "compute_pca",
        "k_means_clustering",
    ),
    PipelineStage.VISUALIZE: ("build_chart",),
    PipelineStage.PREDICT: (
        "forecast_exponential_smoothing",
        "forecast_prophet",
        "forecast_linear_regression",
        "forecast_arima",
        "forecast_random_forest",
        "compare_forecast_models",
    ),
    PipelineStage.EXPLAIN: (),
    PipelineStage.REPORT: (),
    PipelineStage.REPRODUCE: (),
}

_KIND_BY_STAGE: dict[PipelineStage, OperationKind] = {
    PipelineStage.CLEAN: OperationKind.DATASET,
    PipelineStage.VISUALIZE: OperationKind.FIGURE,
}


@dataclass(frozen=True)
class Operation:
    """One runnable operation of one stage."""

    name: str
    stage: PipelineStage
    description: str
    parameters: dict[str, Any]
    kind: OperationKind


def stage_rationale(stage: PipelineStage) -> str:
    """The orchestrator's plain-language reason for the stage ('' where it has none)."""
    return _STAGE_RATIONALE.get(stage, "")


# The tool schemas leave these integers unbounded ("how many future periods": 1e9 would make a
# worker allocate a date range that size). The API refuses a request outside these inclusive bounds
# -- a resource cap on what one run may ask for, not a statistical judgement (the core still
# validates the method's own minimums, e.g. k >= 2).
PARAMETER_BOUNDS: dict[str, tuple[int, int]] = {
    "periods": (1, 1_000),
    "k": (2, 100),
    "n_components": (1, 100),
    "seasonal_periods": (2, 400),
    "degree": (1, 5),
}


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    properties = {
        name: (
            {
                **spec,
                "minimum": spec.get("minimum", PARAMETER_BOUNDS[name][0]),
                "maximum": spec.get("maximum", PARAMETER_BOUNDS[name][1]),
            }
            if name in PARAMETER_BOUNDS and spec.get("type") == "integer"
            else spec
        )
        for name, spec in schema.get("properties", {}).items()
    }
    return {**schema, "properties": properties, "additionalProperties": False}


def operations(stage: PipelineStage) -> list[Operation]:
    """The operations of ``stage`` that exist in the core's registry right now, in a fixed order."""
    live = {item["name"]: item for item in get_anthropic_tool_schemas()}
    kind = _KIND_BY_STAGE.get(stage, OperationKind.RESULT)
    return [
        Operation(
            name=name,
            stage=stage,
            description=live[name]["description"],
            parameters=_strict(live[name]["input_schema"]),
            kind=kind,
        )
        for name in STAGE_OPERATIONS[stage]
        if name in live
    ]


def find(stage: PipelineStage, name: str) -> Operation | None:
    """The operation ``name`` of ``stage``, or ``None`` (a name of another stage is ``None`` too)."""
    for operation in operations(stage):
        if operation.name == name:
            return operation
    return None


def validate_parameters(
    operation: Operation, parameters: Any, *, max_bytes: int
) -> dict[str, Any]:
    """``parameters`` if they satisfy the operation's schema; raises ``ValueError`` (no value echoed)."""
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    try:
        encoded = json.dumps(parameters, sort_keys=True)
    except (TypeError, ValueError):
        raise ValueError("parameters must be JSON") from None
    if len(encoded) > max_bytes:
        raise ValueError("parameters are too large")
    validator = Draft202012Validator(operation.parameters)
    for error in validator.iter_errors(parameters):
        # The path says *where*; the message (which quotes the value) is never used.
        where = ".".join(str(part) for part in error.absolute_path) or "(root)"
        raise ValueError(f"invalid parameter at {where}")
    return parameters
