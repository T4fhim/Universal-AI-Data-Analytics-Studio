# File: src/ui/results/renderers/profiling.py
"""Renders :class:`~src.analysis.dataset_profile.DatasetProfile` -- ``profile_dataset``'s result.

The first result renderer this milestone shipped a real caller for --
:class:`~src.ui.workbench.pages.understand_page.UnderstandPage.show_profile_summary` formats
this same data informally as one line of text (see that module's own docstring). This renderer
is the real replacement path: :class:`~src.ui.results.result_card.ResultCard` given a
``DatasetProfile`` renders the equivalent (and more -- a per-column table) as real sections, but
``UnderstandPage`` itself is left on its existing text-label rendering for this milestone -- see
this milestone's own scope note in ``plans/ui-overhaul-pioneering-adaptive-workbench.md`` for why
migrating it is not attempted here.
"""

from __future__ import annotations

from src.analysis.dataset_profile import DatasetProfile
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.base_result_renderer import (
    BaseResultRenderer,
    KeyValueSection,
    ProseSection,
    ResultSection,
    TableSection,
)


class DatasetProfileRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.analysis.dataset_profile.DatasetProfile`."""

    @classmethod
    def title(cls, result: DatasetProfile) -> str:
        return f"Dataset Profile: {result.dataset_name}"

    @classmethod
    def headline(cls, result: DatasetProfile, level: ExpertiseLevel) -> str:
        return (
            f"{result.row_count:,} rows x {result.column_count} columns, "
            f"{result.duplicate_row_count:,} duplicate row(s)."
        )

    @classmethod
    def sections(
        cls, result: DatasetProfile, level: ExpertiseLevel
    ) -> list[ResultSection]:
        sections: list[ResultSection] = [
            KeyValueSection(
                title="Summary",
                items=(
                    ("Rows", f"{result.row_count:,}"),
                    ("Columns", str(result.column_count)),
                    ("Duplicate rows", f"{result.duplicate_row_count:,}"),
                    ("Memory usage", f"{result.memory_usage_bytes / 1_048_576:.2f} MB"),
                ),
            ),
            TableSection(
                title="Columns",
                columns=("Name", "Type", "Missing %", "Unique values"),
                rows=tuple(
                    (
                        column.name,
                        column.dtype,
                        f"{column.missing_percentage:.1f}%",
                        str(column.unique_count),
                    )
                    for column in result.column_profiles
                ),
            ),
        ]
        if result.ambiguous_type_columns:
            sections.append(
                ProseSection(
                    title="Ambiguous-Type Columns",
                    text=(
                        "These columns mix numeric and non-numeric values under a text type: "
                        + ", ".join(result.ambiguous_type_columns)
                        + "."
                    ),
                )
            )
        return sections

    @classmethod
    def help_anchor(cls) -> str:
        return "results.dataset_profile"
