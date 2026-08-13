# File: src/ai/tool_registry.py
"""Maps tool names to schemas and implementations, every tool a thin wrapper over existing code.

No new capability is invented in this module. Every tool below calls
directly into a function already built and tested in an earlier
milestone — :mod:`src.cleaning`, :mod:`src.analysis`,
:mod:`src.forecasting`. This means every validation path those
functions already enforce (column existence, type checks, minimum row
counts) applies identically whether a human calls them through the UI
or the assistant calls them on a human's behalf — there is no
assistant-specific bypass of any check built in earlier phases.

Cleaning tools never mutate the active dataset. Each one returns a new
:class:`~src.services.workspace_service.Dataset` with lineage set,
exactly as :class:`~src.cleaning.base_operation.BaseOperation`
requires when called directly — the assistant is not exempted from
this rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from src.analysis.aggregation import aggregate
from src.analysis.correlation import compute_correlation
from src.analysis.crosstab import cross_tabulate
from src.analysis.dataset_profile import profile_dataset
from src.cleaning.duplicates import DropDuplicates
from src.cleaning.missing_values import DropMissingValues, FillMissingValues
from src.cleaning.text_normalization import NormalizeText
from src.cleaning.type_conversion import ConvertType
from src.services.workspace_service import Dataset


@dataclass
class ToolDefinition:
    """One callable tool: its Anthropic-format schema and its implementation.

    Attributes:
        name: Tool name as sent to and returned by the API.
        description: Shown to the model — what the tool does and when
            to use it.
        input_schema: JSON Schema for the tool's parameters, in the
            exact shape the Anthropic API's ``tools`` parameter
            expects.
        handler: The actual function. Always takes the active
            ``Dataset`` as its first argument plus the tool's declared
            parameters as keyword arguments, and returns either a new
            ``Dataset`` (cleaning tools) or a plain JSON-serializable
            result (analysis/forecast tools) — never mutates its
            input.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]


def _drop_missing_values(dataset: Dataset, columns: list[str] | None = None) -> Dataset:
    return DropMissingValues.apply(dataset, columns=columns)


def _fill_missing_values(dataset: Dataset, fill_value: Any, columns: list[str] | None = None) -> Dataset:
    return FillMissingValues.apply(dataset, fill_value=fill_value, columns=columns)


def _drop_duplicates(dataset: Dataset, columns: list[str] | None = None) -> Dataset:
    return DropDuplicates.apply(dataset, columns=columns)


def _normalize_text(
    dataset: Dataset, columns: list[str], trim_whitespace: bool = True, case: str | None = None
) -> Dataset:
    return NormalizeText.apply(dataset, columns=columns, trim_whitespace=trim_whitespace, case=case)


def _convert_type(dataset: Dataset, column: str, target_type: str) -> Dataset:
    return ConvertType.apply(dataset, column=column, target_type=target_type)


def _profile_dataset(dataset: Dataset) -> dict:
    profile = profile_dataset(dataset)
    return {
        "row_count": profile.row_count,
        "column_count": profile.column_count,
        "duplicate_row_count": profile.duplicate_row_count,
        "ambiguous_type_columns": profile.ambiguous_type_columns,
        "columns": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "missing_percentage": c.missing_percentage,
                "unique_count": c.unique_count,
            }
            for c in profile.column_profiles
        ],
    }


def _compute_correlation(dataset: Dataset, method: str = "pearson") -> dict:
    result = compute_correlation(dataset.dataframe, method=method)
    return {
        "included_columns": result.included_columns,
        "excluded_columns": result.excluded_columns,
        "matrix": result.matrix.round(3).to_dict(),
    }


def _aggregate(
    dataset: Dataset, group_by: list[str], agg_column: str, agg_function: str = "mean"
) -> dict:
    result = aggregate(dataset.dataframe, group_by=group_by, agg_column=agg_column, agg_function=agg_function)
    return {"result": result.reset_index().to_dict(orient="records")}


def _cross_tabulate(dataset: Dataset, row_column: str, column_column: str) -> dict:
    result = cross_tabulate(dataset.dataframe, row_column=row_column, column_column=column_column)
    return {"table": result.to_dict()}


TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="drop_missing_values",
        description="Remove rows with missing values from the active dataset. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to check. Omit to check all columns.",
                }
            },
        },
        handler=_drop_missing_values,
    ),
    ToolDefinition(
        name="fill_missing_values",
        description="Replace missing values with a given value. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "fill_value": {"description": "Value to substitute for missing entries."},
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to fill. Omit to fill all columns.",
                },
            },
            "required": ["fill_value"],
        },
        handler=_fill_missing_values,
    ),
    ToolDefinition(
        name="drop_duplicates",
        description="Remove duplicate rows. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to consider when identifying duplicates. Omit to require all columns to match.",
                }
            },
        },
        handler=_drop_duplicates,
    ),
    ToolDefinition(
        name="normalize_text",
        description="Trim whitespace and/or normalize casing on text columns. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "columns": {"type": "array", "items": {"type": "string"}},
                "trim_whitespace": {"type": "boolean", "default": True},
                "case": {"type": "string", "enum": ["lower", "upper", "title"]},
            },
            "required": ["columns"],
        },
        handler=_normalize_text,
    ),
    ToolDefinition(
        name="convert_type",
        description="Convert a column to a different data type (numeric, integer, string, boolean, datetime). Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "column": {"type": "string"},
                "target_type": {
                    "type": "string",
                    "enum": ["numeric", "integer", "string", "boolean", "datetime"],
                },
            },
            "required": ["column", "target_type"],
        },
        handler=_convert_type,
    ),
    ToolDefinition(
        name="profile_dataset",
        description="Get a statistical profile of the active dataset: row/column counts, missing values, types, duplicates.",
        input_schema={"type": "object", "properties": {}},
        handler=_profile_dataset,
    ),
    ToolDefinition(
        name="compute_correlation",
        description="Compute a correlation matrix over the active dataset's numeric columns.",
        input_schema={
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["pearson", "spearman", "kendall"], "default": "pearson"}
            },
        },
        handler=_compute_correlation,
    ),
    ToolDefinition(
        name="aggregate",
        description="Group the active dataset and aggregate a numeric column.",
        input_schema={
            "type": "object",
            "properties": {
                "group_by": {"type": "array", "items": {"type": "string"}},
                "agg_column": {"type": "string"},
                "agg_function": {
                    "type": "string",
                    "enum": ["sum", "mean", "median", "min", "max", "count", "std"],
                    "default": "mean",
                },
            },
            "required": ["group_by", "agg_column"],
        },
        handler=_aggregate,
    ),
    ToolDefinition(
        name="cross_tabulate",
        description="Cross-tabulate frequency counts between two categorical columns.",
        input_schema={
            "type": "object",
            "properties": {
                "row_column": {"type": "string"},
                "column_column": {"type": "string"},
            },
            "required": ["row_column", "column_column"],
        },
        handler=_cross_tabulate,
    ),
]


def get_anthropic_tool_schemas() -> list[dict[str, Any]]:
    """Return every tool's schema in the exact shape the Anthropic API's ``tools`` parameter expects."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS
    ]


def get_tool_by_name(name: str) -> ToolDefinition:
    """Look up a tool by name.

    Raises:
        KeyError: If no tool with this name is registered — deliberately
            a plain KeyError, not a project ServiceError, since this is
            an internal lookup failure (the model requested a tool name
            that does not exist), not a user-facing data error.
    """
    for tool in TOOLS:
        if tool.name == name:
            return tool
    raise KeyError(f"No tool registered with name: {name!r}")
