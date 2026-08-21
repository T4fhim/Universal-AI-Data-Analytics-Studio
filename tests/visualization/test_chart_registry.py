# File: tests/visualization/test_chart_registry.py
"""Tests for src.visualization.chart_registry."""

from __future__ import annotations

import pytest

from src.core.exceptions import ServiceError
from src.visualization.chart_registry import (
    ChartRegistration,
    display_name_for,
    get_chart,
    list_charts,
    list_dialog_charts,
    register_chart,
)
from src.visualization.distribution_charts import HistogramChart


def test_builtin_charts_are_registered() -> None:
    charts = list_charts()
    assert "bar" in charts
    assert "heatmap" in charts
    assert len(charts) >= 12


def test_list_dialog_charts_includes_every_builtin_including_list_field_charts() -> (
    None
):
    # Milestone 24: ColumnMultiSelect gave CreateVisualizationDialog a real multi-select
    # widget, so Treemap/Radar (both list_fields-typed) are no longer excluded from the
    # dialog -- see ChartRegistration.dialog_compatible's own docstring for the history.
    dialog_charts = list_dialog_charts()
    assert "treemap" in dialog_charts
    assert "radar" in dialog_charts
    assert "bar" in dialog_charts


def test_treemap_and_radar_declare_their_list_typed_fields() -> None:
    assert get_chart("treemap").list_fields == ("path_columns",)
    assert get_chart("radar").list_fields == ("value_columns",)


def test_get_chart_returns_registration() -> None:
    registration = get_chart("histogram")
    assert registration.chart_class is HistogramChart


def test_get_chart_unknown_name_raises() -> None:
    with pytest.raises(ServiceError, match="Unknown chart type"):
        get_chart("not_a_real_chart")


def test_register_chart_duplicate_name_raises() -> None:
    with pytest.raises(ServiceError, match="already registered"):
        register_chart("bar", ChartRegistration(HistogramChart, ("column",)))


def test_register_chart_new_name_succeeds() -> None:
    register_chart(
        "_test_only_chart_type", ChartRegistration(HistogramChart, ("column",))
    )
    assert "_test_only_chart_type" in list_charts()


def test_display_name_for_formats_snake_case() -> None:
    assert display_name_for("box_plot") == "Box Plot"
    assert display_name_for("bar") == "Bar"
