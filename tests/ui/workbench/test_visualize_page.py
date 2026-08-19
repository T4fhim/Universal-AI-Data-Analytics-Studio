# File: tests/ui/workbench/test_visualize_page.py
"""Tests for VisualizePage -- milestone 24's three acceptance criteria, end to end.

1. Treemap/Radar are buildable from a real column selection (previously AI-only).
2. Every chart_recommender suggestion resolves in the chart registry and can actually be
   built through this page's recommendation flow.
3. Clicking a data point in the built chart filters the paired DataTableView, driven through
   the real ChartBridge.point_clicked signal -- see src/ui/web/chart_bridge.py's own docstring
   for why that signal existed, unconsumed, since milestone 16.

Nothing mocked: a real Dataset, real chart_registry/chart_recommender functions, and a real
ChartBridge signal emission, matching this project's "real Qt widgets/services" test convention
(see tests/ui/workbench/test_clean_page.py's own docstring for the same rule applied to its
milestone).
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication

from src.services.workspace_service import Dataset
from src.ui.widgets.column_multi_select import ColumnMultiSelect
from src.ui.workbench.pages.visualize_page import VisualizePage
from src.visualization.chart_recommender import recommend_charts


def _make_dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "region": ["east", "east", "west", "west", "north", "north"],
            "product": ["a", "b", "a", "b", "a", "b"],
            "revenue": [10, 20, 30, 40, 50, 60],
            "cost": [1, 2, 3, 4, 5, 6],
            "profit": [9, 18, 27, 36, 45, 54],
        }
    )
    return Dataset(name="visualize-demo", dataframe=frame, source_format="csv")


def test_set_dataset_populates_column_select_and_table(qapp: QApplication) -> None:
    page = VisualizePage()
    dataset = _make_dataset()

    page.set_dataset(dataset)

    assert page.column_select.count() == 5
    assert page.data_table.dataset_id == dataset.dataset_id


def test_all_twelve_chart_types_are_offered(qapp: QApplication) -> None:
    page = VisualizePage()
    assert page.chart_type_combo.count() == 12
    names = {page.chart_type_combo.itemText(i) for i in range(12)}
    assert "Treemap" in names
    assert "Radar" in names


# -- Acceptance criterion 1: Treemap/Radar buildable from a real column selection -----------


def test_build_treemap_from_a_multi_column_selection(qapp: QApplication) -> None:
    page = VisualizePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    combo_index = page.chart_type_combo.findData("treemap")
    page.chart_type_combo.setCurrentIndex(combo_index)
    page._column_fields["path_columns"].set_selected_columns(["region", "product"])
    page._column_fields["value_column"].setCurrentText("revenue")

    built: list[tuple] = []
    page.visualization_built.connect(lambda *args: built.append(args))

    page.build_chart(dataset)

    assert len(built) == 1
    figure, chart_type, parameters = built[0]
    assert chart_type == "treemap"
    assert parameters["path_columns"] == ["region", "product"]
    assert figure.data  # a real Plotly figure with at least one trace


def test_build_radar_from_a_multi_column_selection(qapp: QApplication) -> None:
    page = VisualizePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    combo_index = page.chart_type_combo.findData("radar")
    page.chart_type_combo.setCurrentIndex(combo_index)
    page._column_fields["category_column"].setCurrentText("region")
    page._column_fields["value_columns"].set_selected_columns(
        ["revenue", "cost", "profit"]
    )

    built: list[tuple] = []
    page.visualization_built.connect(lambda *args: built.append(args))

    page.build_chart(dataset)

    assert len(built) == 1
    _figure, chart_type, parameters = built[0]
    assert chart_type == "radar"
    assert parameters["value_columns"] == ["revenue", "cost", "profit"]


# -- Acceptance criterion 2: every recommendation resolves and builds -----------------------


def test_get_recommendations_populates_the_recommendation_list(
    qapp: QApplication,
) -> None:
    page = VisualizePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    suggestions = page.get_recommendations(dataset, ["region", "revenue"])

    assert len(suggestions) > 0
    assert page.recommendation_list.count() == len(suggestions)


def test_every_possible_recommendation_can_be_applied_and_built(
    qapp: QApplication,
) -> None:
    """Drives every suggestion recommend_charts can produce for this dataset's full column
    set through apply_recommendation() + build_chart() -- proving the registry-key fix (not
    just resolving in chart_registry, but actually buildable end to end through this page).
    """
    page = VisualizePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    suggestions = recommend_charts(dataset.dataframe, max_suggestions=100)
    assert suggestions  # sanity: this dataset produces at least one suggestion

    for suggestion in suggestions:
        built: list[tuple] = []
        page.visualization_built.connect(lambda *args: built.append(args))
        page.apply_recommendation(suggestion)
        page.build_chart(dataset)
        page.visualization_built.disconnect()

        assert len(built) == 1, f"{suggestion.chart_type} did not build"
        figure, chart_type, _parameters = built[0]
        assert chart_type == suggestion.chart_type
        assert figure.data


# -- Acceptance criterion 3: chart-click filters the paired table ---------------------------


def test_clicking_a_chart_point_filters_the_paired_table(qapp: QApplication) -> None:
    page = VisualizePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    combo_index = page.chart_type_combo.findData("bar")
    page.chart_type_combo.setCurrentIndex(combo_index)
    page._column_fields["category_column"].setCurrentText("region")
    page._column_fields["value_column"].setCurrentText("revenue")
    page.build_chart(dataset)

    # Real ChartBridge emission, the same shape notify_point_clicked forwards from JS --
    # see src/ui/web/chart_bridge.py's own docstring for the payload shape.
    page.chart_view.bridge.point_clicked.emit(
        {"curveNumber": 0, "pointIndex": 0, "x": "east", "y": 30}
    )

    assert page.data_table._filter_bar.text() == "east"
    # The model's filter mask actually narrowed the visible rows.
    assert page.data_table.model is not None
    assert page.data_table.model.rowCount() < dataset.row_count


def test_clicking_a_chart_point_with_no_x_in_payload_is_a_no_op(
    qapp: QApplication,
) -> None:
    page = VisualizePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    page.chart_view.bridge.point_clicked.emit({"curveNumber": 0, "pointIndex": 0})

    assert page.data_table._filter_bar.text() == ""


# -- Manual builder: dynamic field widgets ---------------------------------------------------


def test_selecting_treemap_gives_a_multi_select_path_columns_field(
    qapp: QApplication,
) -> None:
    page = VisualizePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    combo_index = page.chart_type_combo.findData("treemap")
    page.chart_type_combo.setCurrentIndex(combo_index)

    assert isinstance(page._column_fields["path_columns"], ColumnMultiSelect)
