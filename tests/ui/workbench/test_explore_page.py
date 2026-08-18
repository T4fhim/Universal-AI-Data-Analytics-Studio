# File: tests/ui/workbench/test_explore_page.py
"""Tests for ExplorePage -- the EXPLORE stage's crosstab/aggregate/correlation page."""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication

from src.core.expertise_level import ExpertiseLevel
from src.services.workspace_service import Dataset
from src.ui.workbench.pages.explore_page import ExplorePage


def _make_dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "group": ["a", "a", "b", "b", "c", "c"],
            "other": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
        }
    )
    return Dataset(name="explore-demo", dataframe=frame, source_format="csv")


def test_run_exploration_with_aggregate_renders_a_table_section(
    qapp: QApplication,
) -> None:
    page = ExplorePage()
    dataset = _make_dataset()

    page.run_exploration(
        dataset,
        "aggregate",
        {"group_by": ["group"], "agg_column": "value", "agg_function": "mean"},
        ExpertiseLevel.BEGINNER,
    )

    kinds = [w.property("resultSectionKind") for w in page.result_card.section_widgets]
    assert "TableSection" in kinds


def test_run_exploration_with_correlation_renders_a_correlation_matrix(
    qapp: QApplication,
) -> None:
    page = ExplorePage()
    dataset = _make_dataset()

    page.run_exploration(dataset, "compute_correlation", {}, ExpertiseLevel.ANALYST)

    assert page.result_card._title_label.text() == "Pearson Correlation"


def test_explore_page_run_button_has_a_real_accessible_name(qapp: QApplication) -> None:
    page = ExplorePage()
    assert page.run_button.accessibleName() == "Configure and run exploration"


def test_run_with_no_active_dataset_shows_an_informative_message(
    qapp: QApplication, block_modals
) -> None:
    page = ExplorePage()
    page._on_run_clicked()

    assert any(call.kind == "information" for call in block_modals)
