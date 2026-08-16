# File: src/visualization/chart_recommender.py
"""Smart Visualization Selection: ranks candidate chart types for a dataset with a stated reason.

Backs both the orchestrator's VISUALIZE stage
(:class:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService`)
and a "suggest a chart" affordance in the chart-builder dialog, per the
milestone 11 plan. Reuses :func:`~src.analysis.column_profile.profile_column`
rather than re-deriving type/cardinality signals independently — the
same "one place this computation lives" reasoning behind every other
reuse in this milestone (:mod:`~src.analysis.chi_square` reusing
``cross_tabulate``, :class:`~src.visualization.advanced_charts.HeatmapChart`
reusing ``compute_correlation``).

Deliberately rule-based rather than a learned/statistical recommender:
the rules below encode well-established chart-selection heuristics
(a numeric-vs-numeric pair suggests a scatter; a date column plus a
numeric column suggests a line/time series; low-cardinality
categorical plus numeric suggests a bar) that don't need training data
to state, and a stated, inspectable reason for each suggestion matters
more here than marginal accuracy a black-box model might offer instead
— consistent with this project's "Explain Everything" defining
feature.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.analysis.column_profile import profile_column
from src.readers.type_inference import find_ambiguous_type_columns

# A categorical column with more distinct values than this is
# considered high-cardinality for chart-recommendation purposes — past
# this point, a bar/pie chart of it would need the same "Other"
# bucketing categorical_charts.py already applies when actually
# building one, so it's a weaker recommendation than a chart type that
# doesn't run into that problem at all.
_LOW_CARDINALITY_THRESHOLD = 15


@dataclass
class ChartSuggestion:
    """One recommended chart type.

    Attributes:
        chart_type: Matches a key in
            :mod:`~src.ai.tool_registry`'s ``_CHART_BUILDERS`` /
            :mod:`~src.ui.dialogs.create_visualization_dialog`'s
            ``_CHART_REGISTRY`` naming.
        columns: Which column(s) this suggestion is for, in the order
            the corresponding chart builder expects them.
        reason: Human-readable explanation of why this chart type fits
            these columns — always populated, never a bare score,
            matching this project's "Explain Everything" principle.
        score: Relative ranking within the returned list (higher is a
            better fit) — not a calibrated probability or statistical
            measure, purely an ordering device.
    """

    chart_type: str
    columns: list[str]
    reason: str
    score: float


def recommend_charts(
    dataframe: pd.DataFrame, max_suggestions: int = 5
) -> list[ChartSuggestion]:
    """Rank candidate chart types for ``dataframe`` with a stated reason for each.

    Args:
        dataframe: The dataset to suggest charts for.
        max_suggestions: Maximum number of suggestions to return,
            highest-scored first.

    Returns:
        Suggestions sorted best-first. An empty list is a valid result
        (e.g. a dataframe with no columns) — this function never
        raises for a dataframe that simply has nothing worth
        suggesting a chart for, since "no good chart exists yet" is a
        legitimate, expected state early in an analysis session, not
        an error condition.
    """
    if dataframe.empty or len(dataframe.columns) == 0:
        return []

    ambiguous_columns = find_ambiguous_type_columns(dataframe)
    profiles = {
        column: profile_column(dataframe, column, ambiguous_columns=ambiguous_columns)
        for column in dataframe.columns
    }

    numeric_columns = [
        c
        for c in dataframe.columns
        if c not in ambiguous_columns and pd.api.types.is_numeric_dtype(dataframe[c])
    ]
    datetime_columns = [
        c
        for c in dataframe.columns
        if pd.api.types.is_datetime64_any_dtype(dataframe[c])
    ]
    categorical_columns = [
        c
        for c in dataframe.columns
        if c not in numeric_columns
        and c not in datetime_columns
        and c not in ambiguous_columns
    ]
    low_cardinality_categorical = [
        c
        for c in categorical_columns
        if profiles[c].unique_count <= _LOW_CARDINALITY_THRESHOLD
    ]

    suggestions: list[ChartSuggestion] = []

    if datetime_columns and numeric_columns:
        suggestions.append(
            ChartSuggestion(
                chart_type="Line",
                columns=[datetime_columns[0], numeric_columns[0]],
                reason=(
                    f"'{datetime_columns[0]}' is a date/time column and "
                    f"'{numeric_columns[0]}' is numeric — a line chart "
                    f"shows how it changes over time."
                ),
                score=10.0,
            )
        )

    if len(numeric_columns) >= 2:
        suggestions.append(
            ChartSuggestion(
                chart_type="Scatter",
                columns=[numeric_columns[0], numeric_columns[1]],
                reason=(
                    f"'{numeric_columns[0]}' and '{numeric_columns[1]}' are "
                    f"both numeric — a scatter plot shows their relationship."
                ),
                score=9.0,
            )
        )

    if len(numeric_columns) >= 2:
        suggestions.append(
            ChartSuggestion(
                chart_type="Heatmap",
                columns=numeric_columns,
                reason=(
                    f"{len(numeric_columns)} numeric columns are available — "
                    f"a correlation heatmap shows how strongly each pair "
                    f"of them moves together."
                ),
                score=7.0,
            )
        )

    if low_cardinality_categorical and numeric_columns:
        cat = low_cardinality_categorical[0]
        suggestions.append(
            ChartSuggestion(
                chart_type="Bar",
                columns=[cat, numeric_columns[0]],
                reason=(
                    f"'{cat}' has {profiles[cat].unique_count} distinct "
                    f"values (few enough to read clearly) — a bar chart "
                    f"compares '{numeric_columns[0]}' across them."
                ),
                score=8.0,
            )
        )

    if low_cardinality_categorical and not numeric_columns:
        cat = low_cardinality_categorical[0]
        suggestions.append(
            ChartSuggestion(
                chart_type="Pie",
                columns=[cat],
                reason=(
                    f"'{cat}' has {profiles[cat].unique_count} distinct "
                    f"values and no numeric column was found to pair it "
                    f"with — a pie chart shows the share each category "
                    f"holds by row count."
                ),
                score=5.0,
            )
        )

    if numeric_columns:
        suggestions.append(
            ChartSuggestion(
                chart_type="Histogram",
                columns=[numeric_columns[0]],
                reason=(
                    f"'{numeric_columns[0]}' is numeric — a histogram "
                    f"shows the shape of its distribution."
                ),
                score=4.0,
            )
        )

    if low_cardinality_categorical and numeric_columns:
        cat = low_cardinality_categorical[0]
        suggestions.append(
            ChartSuggestion(
                chart_type="Box Plot",
                columns=[numeric_columns[0], cat],
                reason=(
                    f"'{numeric_columns[0]}' broken down by '{cat}' — a "
                    f"box plot compares the distribution across groups, "
                    f"not just their averages."
                ),
                score=6.0,
            )
        )

    suggestions.sort(key=lambda s: s.score, reverse=True)
    return suggestions[:max_suggestions]
