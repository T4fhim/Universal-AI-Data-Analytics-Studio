# File: src/ui/workbench/pages/predict_page.py
"""The PREDICT stage's page: forecast a time series with any of the 5 forecasters, or let
:func:`~src.forecasting.model_comparison.compare_forecast_models` pick the best one automatically.

Milestone 25's primary acceptance criterion: this is the first non-AI UI path to anything in
:mod:`src.forecasting` at all -- before this milestone that package was reachable only by typing
English at the AI chat (see this overhaul's own Context section, "src/analysis/,
src/forecasting/, and src/cleaning/ are 100% orphaned -- no src/ui/ file imports any of them").
:mod:`~src.ui.workbench.pages.clean_page`/:mod:`~src.ui.workbench.pages.analyze_page` already
closed that gap for their own packages in milestones 23/22; this page closes it for forecasting.

Like :class:`~src.ui.workbench.pages.analyze_page.AnalyzePage`, this page calls straight into
:mod:`src.forecasting`'s own functions rather than through :mod:`src.ai.tool_registry`'s
handlers -- those handlers convert the typed ``ForecastResult``/``ModelComparisonResult`` into a
plain JSON dict (see :func:`~src.ai.tool_registry._forecast_result_to_dict`), which would defeat
:mod:`~src.ui.results.result_renderer_registry`'s type-based dispatch to
:mod:`~src.ui.results.renderers.forecasting`'s two dedicated renderers. It does still reuse
:class:`~src.ai.tool_registry.ToolDefinition`'s ``input_schema`` (via
:class:`~src.ui.dialogs.analysis_parameter_dialog.AnalysisParameterDialog`, the same generic
parameter form ``AnalyzePage``/``ExplorePage`` already use) purely for the parameter *form* --
the schema and the handler are two independent things on the same ``ToolDefinition``, and this
page only wants the former.

**Why "Automatic Model Competition" runs on a background worker and a single forecaster does
not.** A single ``forecast_*`` call fits one model once -- the same "fast enough to run
synchronously on the UI thread" shape ``AnalyzePage``/``ExplorePage`` already rely on for every
one of their tools. :func:`~src.forecasting.model_comparison.compare_forecast_models` fits up to
five models *twice each* (once against a holdout split, once against the full series) -- Prophet
alone is the slowest of the five, so running all ten fits on the UI thread would freeze the
window for a genuinely noticeable stretch. This page offloads only the comparison path through
:class:`~src.ui.worker_runner.WorkerRunner`, wired to
:meth:`~src.ui.status_bar.ApplicationStatusBar.show_progress` via ``compare_forecast_models``'s
own new ``progress_callback`` parameter -- the first real consumer of
:attr:`~src.workers.base_worker.WorkerSignals.progress` this codebase has ever had (see that
status bar method's own docstring, which named this exact milestone as where it would land).

**Why this page holds a direct ``WorkerRunner``/``ApplicationStatusBar`` reference, unlike its
stage-page siblings.** :mod:`~src.ui.workbench`'s own docstring says a stage page "holds no
service references and calls nothing in ``src.services`` or ``src.ui.controllers`` directly."
Neither :class:`~src.ui.worker_runner.WorkerRunner` nor :class:`~src.ui.status_bar.
ApplicationStatusBar` is a ``src.services`` service or a ``src.ui.controllers`` controller --
both are plain UI infrastructure ``main_window.py`` already constructs directly (not resolved
from the ``DependencyContainer``) and hands straight to every milestone-19 controller as
constructor arguments. Routing a live, in-flight progress percentage through a signal all the way
out to a controller and back into this page would add a layer of indirection with nothing behind
it -- this page is the one place that both knows a comparison run is in progress and needs to
show that on screen, so :meth:`set_worker_collaborators` hands it what it needs directly, the same
way ``PipelineController`` itself already receives both as plain constructor arguments.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QVBoxLayout

from src.ai.tool_registry import get_tool_by_name
from src.core.exceptions import ApplicationError, ServiceError
from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.forecasting.arima_forecast import forecast_arima
from src.forecasting.exponential_smoothing import (
    ForecastResult,
    forecast_exponential_smoothing,
)
from src.forecasting.forecast_input import validate_time_series
from src.forecasting.linear_regression_forecast import forecast_linear_regression
from src.forecasting.model_comparison import (
    ModelComparisonResult,
    compare_forecast_models,
)
from src.forecasting.prophet_forecast import forecast_prophet
from src.forecasting.random_forest_forecast import forecast_random_forest
from src.services.analysis_orchestrator_service import PipelineStage
from src.services.workspace_service import Dataset
from src.ui.a11y.accessible import describe
from src.ui.dialogs.analysis_parameter_dialog import AnalysisParameterDialog
from src.ui.results.result_card import ResultCard
from src.ui.status_bar import ApplicationStatusBar
from src.ui.workbench.stage_page import StagePage
from src.ui.worker_runner import WorkerRunner
from src.workers.base_worker import BaseWorker

_logger = get_logger(__name__)

_DEFAULT_GUIDANCE = (
    "Forecast a numeric column over time -- pick one of the five forecasting methods "
    "directly, or let Automatic Model Competition fit every method and report the most "
    "accurate one."
)

# Tool name -> callable(dataframe, date_column, value_column, periods, **extra) -> ForecastResult.
# Matches AnalyzePage._ANALYZE_DISPATCH's exact shape and its own reason for calling
# src.forecasting directly rather than through src.ai.tool_registry's dict-returning handlers
# (see this module's own docstring).
_SINGLE_FORECAST_DISPATCH: dict[str, Callable[..., ForecastResult]] = {
    "forecast_exponential_smoothing": forecast_exponential_smoothing,
    "forecast_prophet": forecast_prophet,
    "forecast_linear_regression": forecast_linear_regression,
    "forecast_arima": forecast_arima,
    "forecast_random_forest": forecast_random_forest,
}

_COMPARE_TOOL_NAME = "compare_forecast_models"

# Every tool this page's combo offers, in display order -- the five single forecasters plus the
# comparison tool, which is deliberately listed first: it is the recommended default for a user
# who has not already decided which method to use (see compare_forecast_models's own
# tool_registry description, "use this instead of a single forecast_* tool when the user hasn't
# specified a method").
_TOOL_NAMES: tuple[str, ...] = (
    _COMPARE_TOOL_NAME,
    "forecast_exponential_smoothing",
    "forecast_prophet",
    "forecast_linear_regression",
    "forecast_arima",
    "forecast_random_forest",
)


class PredictPage(StagePage):
    """The PREDICT stage's workbench page: choose a forecaster (or compare all five), configure
    it, render its ``ResultCard``."""

    stage: ClassVar[PipelineStage] = PipelineStage.PREDICT
    help_anchor: ClassVar[str] = "pipeline.predict"

    def __init__(self, parent=None) -> None:
        self._dataset: Dataset | None = None
        self._expertise_level = ExpertiseLevel.BEGINNER
        self._worker_runner: WorkerRunner | None = None
        self._status_bar: ApplicationStatusBar | None = None
        super().__init__(parent)

    def _build_form(self, layout: QVBoxLayout) -> None:
        self._tool_combo = QComboBox(self)
        self._tool_combo.setObjectName("predictToolCombo")
        for tool_name in _TOOL_NAMES:
            label = (
                "Automatic Model Competition"
                if tool_name == _COMPARE_TOOL_NAME
                else tool_name.replace("forecast_", "").replace("_", " ").title()
            )
            self._tool_combo.addItem(label, tool_name)
        describe(
            self._tool_combo,
            name="Forecasting method",
            description="Which forecaster to run against the active dataset, or Automatic "
            "Model Competition to run every method and report the most accurate one.",
        )
        layout.addWidget(self._tool_combo)

        self.run_button = QPushButton("Configure && Run", self)
        self.run_button.setObjectName("predictRunButton")
        describe(
            self.run_button,
            name="Configure and run forecast",
            description="Opens a parameter form for the selected method, then runs it.",
            help_anchor=self.help_anchor,
        )
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)

        # Pre-flight validation warning -- see this module's own docstring and
        # validate_time_series's own docstring for what it rejects. Shown inline in the page
        # (hidden by default) rather than only as a modal dialog, so "why did nothing happen"
        # stays visible instead of disappearing the moment a QMessageBox is dismissed.
        self._validation_label = QLabel(self)
        self._validation_label.setObjectName("predictValidationWarning")
        self._validation_label.setWordWrap(True)
        self._validation_label.setVisible(False)
        describe(
            self._validation_label,
            name="Time series validation warning",
            description="Shows problems found in the selected columns before forecasting.",
        )
        layout.addWidget(self._validation_label)

        self.result_card = ResultCard(self)
        layout.addWidget(self.result_card)

        self.set_guidance(_DEFAULT_GUIDANCE)

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Store the dataset this page's Run button acts on -- see :meth:`~src.ui.workbench.
        pages.analyze_page.AnalyzePage.set_dataset`'s own docstring for the shape rationale.
        """
        self._dataset = dataset

    def set_expertise_level(self, level: ExpertiseLevel) -> None:
        self._expertise_level = level

    def set_worker_collaborators(
        self, worker_runner: WorkerRunner, status_bar: ApplicationStatusBar
    ) -> None:
        """Give this page what it needs to run a comparison off the UI thread with visible
        progress -- see this module's own docstring for why this page holds these two directly
        rather than routing through a controller."""
        self._worker_runner = worker_runner
        self._status_bar = status_bar

    # -- Running --------------------------------------------------------

    def _on_run_clicked(self) -> None:
        if self._dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before forecasting.",
            )
            return

        tool_name = self._tool_combo.currentData()
        tool = get_tool_by_name(tool_name)
        column_names = [str(c) for c in self._dataset.dataframe.columns]
        dialog = AnalysisParameterDialog(tool, column_names, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.run_forecast(
            self._dataset, tool_name, dialog.get_parameters(), self._expertise_level
        )

    def run_forecast(
        self,
        dataset: Dataset,
        tool_name: str,
        parameters: dict,
        level: ExpertiseLevel,
    ) -> BaseWorker | None:
        """Run ``tool_name`` against ``dataset`` and render the result -- see
        :meth:`~src.ui.workbench.pages.analyze_page.AnalyzePage.run_analysis`'s own docstring for
        why both the Run button and a test call a plain method rather than driving the dialog
        through a full click sequence.

        Returns whatever :meth:`_run_comparison` returns (``None`` for every single-forecaster
        tool, which always runs synchronously) -- see that method's own docstring for why this
        is worth returning at all.
        """
        self._expertise_level = level
        date_column = parameters.get("date_column")
        value_column = parameters.get("value_column")
        self.clear_error()

        # Pre-flight validation (milestone 25 acceptance criterion): validate_time_series
        # failures must surface as a warning in the page, not an unhandled stack trace or a
        # crash from deep inside a forecaster's own call to the same validator.
        self._validation_label.setVisible(False)
        if date_column and value_column:
            try:
                validate_time_series(dataset.dataframe, date_column, value_column)
            except ServiceError as exc:
                self._validation_label.setText(f"⚠ {exc}")
                self._validation_label.setVisible(True)
                self.set_result_text(
                    "Pre-flight validation failed -- see the warning above."
                )
                _logger.warning("Predict pre-flight validation failed: %s", exc)
                return None

        if tool_name == _COMPARE_TOOL_NAME:
            return self._run_comparison(dataset, parameters, level)

        handler = _SINGLE_FORECAST_DISPATCH.get(tool_name)
        if handler is None:
            self.set_result_text(f"Unknown forecasting tool: {tool_name!r}.")
            return None

        try:
            result = handler(dataset.dataframe, **parameters)
        except ApplicationError as exc:
            # Milestone 27: an in-page ErrorState, not QMessageBox.critical -- see
            # StagePage.show_error's own docstring.
            self.show_error("Forecast Failed", str(exc))
            _logger.warning("Forecast '%s' failed: %s", tool_name, exc)
            return None
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- shown to the user, not swallowed silently
            self.show_error("Forecast Failed", f"Unexpected error: {exc}")
            _logger.error("Forecast '%s' failed unexpectedly: %s", tool_name, exc)
            return None

        self._display_result(result, level, f"Ran {tool_name.replace('_', ' ')}.")
        return None

    def _run_comparison(
        self, dataset: Dataset, parameters: dict, level: ExpertiseLevel
    ) -> BaseWorker | None:
        """Run ``compare_forecast_models`` -- via :attr:`_worker_runner` with live progress when
        collaborators are set (see :meth:`set_worker_collaborators`), synchronously otherwise
        (a graceful fallback rather than a hard requirement, so this method still works -- just
        without a progress bar -- for a caller that has not wired collaborators).

        Returns the started :class:`~src.workers.base_worker.BaseWorker` when the async path
        runs (``None`` on the synchronous fallback, or if the pre-flight validation/comparison
        itself failed before a worker was ever started) -- purely so a test can wait on the real
        worker's own ``signals.finished`` rather than polling, matching
        :meth:`~src.ui.worker_runner.WorkerRunner.run`'s own "hand back the started worker in
        case a caller needs it" rationale.
        """
        if self._worker_runner is None or self._status_bar is None:
            try:
                result = compare_forecast_models(dataset.dataframe, **parameters)
            except ApplicationError as exc:
                self.show_error("Forecast Comparison Failed", str(exc))
                _logger.warning("Forecast comparison failed: %s", exc)
                return None
            self._display_result(result, level, "Ran Automatic Model Competition.")
            return None

        self.run_button.setEnabled(False)
        self._status_bar.show_busy("Comparing forecast models…")
        return self._worker_runner.run(
            compare_forecast_models,
            dataset.dataframe,
            report_progress=True,
            on_progress=self._status_bar.show_progress,
            on_result=lambda result: self._on_comparison_result(result, level),
            on_error=self._on_comparison_error,
            on_finished=self._on_comparison_finished,
            **parameters,
        )

    def _on_comparison_result(
        self, result: ModelComparisonResult, level: ExpertiseLevel
    ) -> None:
        self._display_result(result, level, "Ran Automatic Model Competition.")

    def _on_comparison_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Forecast comparison failed: %s\n%s", exc, traceback_text)
        self.show_error("Forecast Comparison Failed", str(exc))

    def _on_comparison_finished(self) -> None:
        if self._status_bar is not None:
            self._status_bar.hide_busy()
        self.run_button.setEnabled(True)

    def _display_result(
        self,
        result: ForecastResult | ModelComparisonResult,
        level: ExpertiseLevel,
        message: str,
    ) -> None:
        self.result_card.display(result, level)
        self.set_result_text(message)
        _logger.info("Predict page rendered a %s result.", type(result).__name__)
