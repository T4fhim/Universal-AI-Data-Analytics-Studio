# File: src/ui/results/renderers/correlation.py
"""Renders :class:`~src.analysis.correlation.CorrelationResult` -- ``compute_correlation``'s result."""

from __future__ import annotations

from src.analysis.correlation import CorrelationResult
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.base_result_renderer import (
    BaseResultRenderer,
    KeyValueSection,
    ProseSection,
    ResultSection,
    TableSection,
)


class CorrelationResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.correlation.CorrelationResult`."""

    @classmethod
    def title(cls, result: CorrelationResult) -> str:
        return f"{result.method.title()} Correlation"

    @classmethod
    def headline(cls, result: CorrelationResult, level: ExpertiseLevel) -> str:
        return f"Computed over {len(result.included_columns)} numeric column(s)."

    @classmethod
    def sections(
        cls, result: CorrelationResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        columns = tuple(str(c) for c in result.matrix.columns)
        sections: list[ResultSection] = [
            KeyValueSection(
                title="Summary",
                items=(
                    ("Method", result.method),
                    ("Included columns", ", ".join(result.included_columns)),
                ),
            ),
            TableSection(
                title="Correlation Matrix",
                columns=("",) + columns,
                rows=tuple(
                    (str(row_label),) + tuple(f"{value:.3f}" for value in row_values)
                    for row_label, row_values in result.matrix.iterrows()
                ),
            ),
        ]
        if result.excluded_columns:
            sections.append(
                ProseSection(
                    title="Excluded Columns",
                    text="; ".join(
                        f"{name}: {reason}"
                        for name, reason in result.excluded_columns.items()
                    ),
                )
            )
        return sections

    @classmethod
    def help_anchor(cls) -> str:
        return "results.correlation"
