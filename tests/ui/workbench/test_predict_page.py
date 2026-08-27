# File: tests/ui/workbench/test_predict_page.py
"""Tests for PredictPage -- milestone 25's four acceptance criteria, end to end.

1. All 5 forecasters plus compare_forecast_models are reachable from a real page (first non-AI
   UI path to any of src.forecasting).
2. compare_forecast_models renders as a ranked table with the winner highlighted, plus an
   overlay chart of every candidate.
3. validate_time_series failures surface as a pre-flight warning in the page, not a stack trace.
4. Progress reporting is visible in the status bar during a comparison run -- the first real
   consumer of WorkerSignals.progress.

Nothing mocked: a real Dataset, real src.forecasting functions, a real WorkerRunner over the
real QThreadPool for the progress test, and a real ApplicationStatusBar -- matching this
project's "real Qt widgets/services" test convention (see tests/ui/workbench/test_clean_page.py's
own docstring for the same rule applied to its milestone).
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication, QMainWindow, QTableWidget

from src.core.expertise_level import ExpertiseLevel
from src.services.workspace_service import Dataset
from src.ui.status_bar import ApplicationStatusBar
from src.ui.workbench.pages.predict_page import PredictPage
from src.ui.worker_runner import WorkerRunner
from tests.ui.qt_helpers import wait_for_signal


def _make_dataset(n: int = 20) -> Dataset:
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    frame = pd.DataFrame({"date": dates, "value": [10.0 + i * 0.7 for i in range(n)]})
    return Dataset(name="predict-demo", dataframe=frame, source_format="csv")


# -- Acceptance criterion 1: all 5 forecasters + compare are reachable ------------------------


def test_run_forecast_reports_a_service_error_via_the_in_page_error_state(
    qapp: QApplication, block_modals
) -> None:
    # Milestone 27: a failed forecast is shown via the page's own in-page ErrorState, not a
    # QMessageBox.critical -- see StagePage.show_error's own docstring.
    page = PredictPage()
    dataset = _make_dataset()

    # No date_column/value_column keys at all -- skips the pre-flight validate_time_series
    # check entirely (see run_forecast's own "if date_column and value_column" guard) and
    # reaches forecast_arima itself with missing required kwargs, a real exception.
    page.run_forecast(
        dataset, "forecast_arima", {"periods": 5}, ExpertiseLevel.BEGINNER
    )

    assert not any(call.kind == "critical" for call in block_modals)
    assert page._error_state.isHidden() is False
    assert page._error_state._heading_label.text() == "Forecast Failed"


def test_all_five_forecasters_plus_compare_are_offered(qapp: QApplication) -> None:
    page = PredictPage()
    tool_names = {page._tool_combo.itemData(i) for i in range(page._tool_combo.count())}
    assert tool_names == {
        "compare_forecast_models",
        "forecast_exponential_smoothing",
        "forecast_prophet",
        "forecast_linear_regression",
        "forecast_arima",
        "forecast_random_forest",
    }
    assert page._tool_combo.itemText(0) == "Automatic Model Competition"


def test_running_each_single_forecaster_renders_a_result_card(
    qapp: QApplication,
) -> None:
    page = PredictPage()
    dataset = _make_dataset()

    for tool_name in (
        "forecast_exponential_smoothing",
        "forecast_linear_regression",
        "forecast_arima",
        "forecast_random_forest",
    ):
        page.run_forecast(
            dataset,
            tool_name,
            {"date_column": "date", "value_column": "value", "periods": 5},
            ExpertiseLevel.BEGINNER,
        )
        kinds = [
            w.property("resultSectionKind") for w in page.result_card.section_widgets
        ]
        assert "FigureSection" in kinds, f"{tool_name} did not render a figure"
        assert "TableSection" in kinds, f"{tool_name} did not render a table"


# -- Acceptance criterion 2: ranked table + overlay chart, winner highlighted -----------------


def test_running_automatic_model_competition_without_collaborators_runs_synchronously(
    qapp: QApplication,
) -> None:
    """No set_worker_collaborators() call -- the graceful synchronous fallback (see
    PredictPage._run_comparison's own docstring)."""
    page = PredictPage()
    dataset = _make_dataset()

    worker = page.run_forecast(
        dataset,
        "compare_forecast_models",
        {"date_column": "date", "value_column": "value", "periods": 5},
        ExpertiseLevel.BEGINNER,
    )

    assert worker is None  # synchronous path started no BaseWorker
    assert page.result_card._title_label.text() == "Automatic Model Competition"
    section_titles = {w.title() for w in page.result_card.section_widgets}
    assert "Ranked Candidates" in section_titles
    assert "Forecast Comparison" in section_titles

    table = next(
        w
        for w in page.result_card.section_widgets
        if w.property("resultSectionKind") == "TableSection"
        and w.title() == "Ranked Candidates"
    )
    # The winner row is textually marked -- find it via the underlying QTableWidget.
    qtable = table.findChild(QTableWidget)
    assert qtable is not None
    winner_cells = [
        qtable.item(row, 1).text()
        for row in range(qtable.rowCount())
        if "(Winner)" in qtable.item(row, 1).text()
    ]
    assert len(winner_cells) == 1


# -- Acceptance criterion 3: pre-flight validation warning, not a stack trace -----------------


def test_a_non_numeric_value_column_surfaces_as_an_inline_warning_not_a_crash(
    qapp: QApplication,
) -> None:
    frame = pd.DataFrame(
        {"date": pd.date_range("2023-01-01", periods=10), "value": ["a"] * 10}
    )
    dataset = Dataset(name="bad-demo", dataframe=frame, source_format="csv")
    page = PredictPage()

    # isHidden() (an explicit hide()/setVisible(False) state), not isVisible() -- this page
    # is never shown as a real top-level window offscreen, so isVisible() would be False
    # regardless of setVisible(True) here (Qt: isVisible() also requires every ancestor to be
    # shown). isHidden() reflects this widget's own explicit visibility flag directly.
    assert page._validation_label.isHidden() is True

    page.run_forecast(
        dataset,
        "forecast_exponential_smoothing",
        {"date_column": "date", "value_column": "value", "periods": 3},
        ExpertiseLevel.BEGINNER,
    )

    assert page._validation_label.isHidden() is False
    assert "must be numeric" in page._validation_label.text()
    assert "Pre-flight validation failed" in page._result_label.text()
    # No result was rendered -- the failure was caught before ever calling the forecaster.
    assert page.result_card.section_widgets == []


def test_a_missing_column_surfaces_as_an_inline_warning_for_compare_too(
    qapp: QApplication,
) -> None:
    dataset = _make_dataset()
    page = PredictPage()

    page.run_forecast(
        dataset,
        "compare_forecast_models",
        {"date_column": "date", "value_column": "not_a_real_column", "periods": 3},
        ExpertiseLevel.BEGINNER,
    )

    assert page._validation_label.isHidden() is False
    assert "not found" in page._validation_label.text()


def test_run_with_no_active_dataset_shows_an_informative_message(
    qapp: QApplication, block_modals
) -> None:
    page = PredictPage()
    page._on_run_clicked()

    assert any(call.kind == "information" for call in block_modals)


# -- Acceptance criterion 4: progress reporting visible in the status bar ---------------------


def test_comparison_run_reports_progress_to_a_real_status_bar(
    qapp: QApplication,
) -> None:
    """First real consumer of WorkerSignals.progress -- a genuine QThreadPool worker, wired
    straight through to ApplicationStatusBar.show_progress via compare_forecast_models' own new
    progress_callback parameter."""
    window = QMainWindow()
    status_bar = ApplicationStatusBar(window)
    worker_runner = WorkerRunner()

    page = PredictPage()
    page.set_worker_collaborators(worker_runner, status_bar)
    dataset = _make_dataset()

    assert page.run_button.isEnabled() is True

    worker = page.run_forecast(
        dataset,
        "compare_forecast_models",
        {"date_column": "date", "value_column": "value", "periods": 5},
        ExpertiseLevel.BEGINNER,
    )
    assert worker is not None
    # The run button is disabled the instant the worker starts -- proves this really went
    # through the async path, not a same-call synchronous shortcut.
    assert page.run_button.isEnabled() is False
    # isHidden(), not isVisible() -- window is never shown offscreen, see this module's own
    # non_numeric test comment for why isVisible() would be uninformative here.
    assert status_bar._busy_indicator.isHidden() is False

    wait_for_signal(worker.signals.finished, timeout_ms=30000)

    # The busy indicator was switched to determinate and reached 100% -- real progress, not
    # merely the indeterminate busy spinner show_busy() alone would leave behind.
    assert status_bar._busy_indicator.maximum() == 100
    assert status_bar._busy_indicator.value() == 100
    assert status_bar._busy_indicator.isHidden() is True  # hide_busy() ran on finish
    assert page.run_button.isEnabled() is True

    assert page.result_card._title_label.text() == "Automatic Model Competition"
