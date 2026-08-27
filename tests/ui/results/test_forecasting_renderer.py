# File: tests/ui/results/test_forecasting_renderer.py
"""Tests for src.ui.results.renderers.forecasting -- milestone 25's own two renderers.

Pure Python, zero ``QApplication`` -- same "renderer tests require zero QApplication" convention
tests/ui/results/test_renderers.py's own docstring establishes. Real ``ForecastResult``/
``ModelComparisonResult`` objects produced by real forecasters/``compare_forecast_models`` (not
hand-built fixtures), so this test proves the actual milestone-25 acceptance criteria: a ranked
table with the winner marked, and an overlay chart with one trace per candidate.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.core.expertise_level import ExpertiseLevel
from src.forecasting.exponential_smoothing import forecast_exponential_smoothing
from src.forecasting.model_comparison import compare_forecast_models
from src.ui.results.base_result_renderer import (
    FigureSection,
    KeyValueSection,
    TableSection,
)
from src.ui.results.renderers.forecasting import (
    ForecastResultRenderer,
    ModelComparisonResultRenderer,
)


def _series(n: int = 20) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    values = [10.0 + i * 0.7 for i in range(n)]
    return pd.DataFrame({"date": dates, "value": values})


# -- ForecastResultRenderer (single forecaster) ----------------------------------------------


def test_forecast_result_renderer_title_names_the_method() -> None:
    result = forecast_exponential_smoothing(_series(), "date", "value", periods=5)
    assert ForecastResultRenderer.title(result) == "Exponential Smoothing Forecast"


def test_forecast_result_renderer_sections_include_a_table_and_a_figure() -> None:
    result = forecast_exponential_smoothing(_series(), "date", "value", periods=5)

    sections = ForecastResultRenderer.sections(result, ExpertiseLevel.BEGINNER)

    kinds = [type(s) for s in sections]
    assert KeyValueSection in kinds
    assert TableSection in kinds
    assert FigureSection in kinds

    table = next(s for s in sections if isinstance(s, TableSection))
    assert table.columns == ("Date", "Value")
    assert len(table.rows) == 5  # one row per projected period

    figure_section = next(s for s in sections if isinstance(s, FigureSection))
    assert isinstance(figure_section.figure, go.Figure)


def test_forecast_result_renderer_help_anchor() -> None:
    assert ForecastResultRenderer.help_anchor() == "results.forecast"


# -- ModelComparisonResultRenderer (Automatic Model Competition) ------------------------------


def test_model_comparison_renderer_title_and_headline_name_the_winner() -> None:
    result = compare_forecast_models(_series(), "date", "value", periods=5)

    assert ModelComparisonResultRenderer.title(result) == "Automatic Model Competition"
    headline = ModelComparisonResultRenderer.headline(result, ExpertiseLevel.BEGINNER)
    assert result.winner.method.replace("_", " ").title() in headline


def test_model_comparison_renderer_table_is_ranked_with_the_winner_marked() -> None:
    """Milestone 25 acceptance criterion: "renders as a ranked table with the winner
    highlighted" -- the winner's row names it "(Winner)" in plain text, a non-color-only signal
    (per this overhaul's A7 accessibility rule) that survives ResultCard's plain QTableWidget
    rendering unmodified."""
    result = compare_forecast_models(_series(), "date", "value", periods=5)

    sections = ModelComparisonResultRenderer.sections(result, ExpertiseLevel.BEGINNER)
    table = next(s for s in sections if isinstance(s, TableSection))

    assert table.columns == ("Rank", "Model", "MAPE", "RMSE")
    assert len(table.rows) == len(result.candidates)

    # Ranked: row order matches result.candidates' own best-first order.
    assert [row[0] for row in table.rows] == [
        str(i) for i in range(1, len(result.candidates) + 1)
    ]

    # Exactly one row is marked as the winner, and it is the first (best-ranked) row.
    winner_rows = [row for row in table.rows if "(Winner)" in row[1]]
    assert len(winner_rows) == 1
    assert winner_rows[0] is table.rows[0]
    assert result.winner.method.replace("_", " ").title() in winner_rows[0][1]


def test_model_comparison_renderer_overlay_chart_has_one_trace_per_candidate_plus_history() -> (
    None
):
    """Milestone 25 acceptance criterion: "an overlay chart of every candidate model's
    forecast"."""
    result = compare_forecast_models(_series(), "date", "value", periods=5)

    sections = ModelComparisonResultRenderer.sections(result, ExpertiseLevel.BEGINNER)
    figure_section = next(s for s in sections if isinstance(s, FigureSection))

    assert isinstance(figure_section.figure, go.Figure)
    trace_names = [trace.name for trace in figure_section.figure.data]
    assert trace_names[0] == "Historical"
    assert len(trace_names) == 1 + len(result.candidates)
    # The winner's trace is named distinctly from every other candidate's.
    winner_trace_names = [name for name in trace_names if "(Winner)" in name]
    assert len(winner_trace_names) == 1


def test_model_comparison_renderer_help_anchor() -> None:
    assert ModelComparisonResultRenderer.help_anchor() == "results.forecast_comparison"
