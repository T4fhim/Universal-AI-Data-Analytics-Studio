# File: src/ui/workbench/pages/analyze_page.py
"""The ANALYZE stage's page: pick a statistical test, configure it, see a real result card.

Milestone 22's primary acceptance-criterion page: "Running a t-test from the Analyze page
renders a ``ResultCard`` with statistic, p-value, and an ``AssumptionsSection`` -- with no API
key configured." This page calls straight into :mod:`src.analysis` (the same functions
:mod:`src.ai.tool_registry`'s handlers wrap) rather than through the AI layer or
:meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.run_stage` --
deliberately, not as a shortcut: ``run_stage`` returns an :class:`~src.services.
analysis_orchestrator_service.AnalysisLogEntry` whose ``outputs`` is a JSON-friendly ``dict``
(see that class's own docstring), because :mod:`src.ai.tool_registry` handlers convert every
analysis dataclass to a plain dict before returning it. Handing a ``dict`` to :class:`~src.ui.
results.result_card.ResultCard` would defeat :mod:`~src.ui.results.result_renderer_registry`'s
entire type-based dispatch (every renderer in :mod:`~src.ui.results.renderers` is keyed on the
*real* result dataclass -- ``TTestResult``, not ``dict``) -- it would resolve to
:class:`~src.ui.results.renderers.generic.GenericResultRenderer`'s dict branch every time,
regardless of which test ran. Calling :mod:`src.analysis` directly keeps the typed result object
intact end to end. Recording these runs into the pipeline's own :class:`~src.services.
analysis_orchestrator_service.AnalysisLog` (so they show up in Reproducible Analysis /
lineage) is a real integration gap this milestone does not close -- see this milestone's own
scope note in the plan document.

Like :class:`~src.ui.workbench.pages.understand_page.UnderstandPage`, this page holds no
*service* reference (see ``src/ui/workbench/__init__.py``'s "display-only" rule) -- but it does
hold a plain :class:`~src.services.workspace_service.Dataset` handed to it via :meth:`set_dataset`,
the same way :class:`~src.ui.widgets.data_table.data_table_view.DataTableView.load_dataset`
takes a ``Dataset`` directly without needing a ``WorkspaceService`` reference of its own. A
future milestone wiring ``main_window.py``'s ``_refresh_workbench`` to call
``analyze_page.set_dataset(active_dataset)`` is what would make this page's Run button reachable
end to end through the live app; a test in this milestone calls :meth:`set_dataset` and
:meth:`run_analysis` directly instead of driving that wiring, since it does not exist yet.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PySide6.QtWidgets import QComboBox, QMessageBox, QPushButton, QVBoxLayout

from src.ai.tool_registry import get_tool_by_name
from src.analysis.anova import one_way_anova
from src.analysis.chi_square import chi_square_test
from src.analysis.clustering import k_means_clustering
from src.analysis.normality import check_normality
from src.analysis.pca import compute_pca
from src.analysis.regression import linear_regression
from src.analysis.t_test import independent_t_test, paired_t_test
from src.core.exceptions import ApplicationError
from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import PipelineStage
from src.services.workspace_service import Dataset
from src.ui.a11y.accessible import describe
from src.ui.dialogs.analysis_parameter_dialog import AnalysisParameterDialog
from src.ui.results.result_card import ResultCard
from src.ui.workbench.stage_page import StagePage

_logger = get_logger(__name__)

_DEFAULT_GUIDANCE = (
    "Run a targeted statistical test now that the data is understood and cleaned -- a "
    "t-test, ANOVA, chi-square, regression, normality check, PCA, or clustering."
)

# Tool name -> callable(dataframe, **params) -> result dataclass. Deliberately calls
# src.analysis functions directly rather than the src.ai.tool_registry handlers wrapping them --
# see this module's own docstring for why (the handlers discard the typed dataclass in favor of
# a JSON dict, which is exactly what this page must not lose).
_ANALYZE_DISPATCH: dict[str, Callable[..., object]] = {
    "independent_t_test": independent_t_test,
    "paired_t_test": paired_t_test,
    "one_way_anova": one_way_anova,
    "chi_square_test": chi_square_test,
    "linear_regression": linear_regression,
    "check_normality": check_normality,
    "compute_pca": compute_pca,
    "k_means_clustering": k_means_clustering,
}


class AnalyzePage(StagePage):
    """The ANALYZE stage's workbench page: choose a test, configure it, render its ``ResultCard``."""

    stage: ClassVar[PipelineStage] = PipelineStage.ANALYZE
    help_anchor: ClassVar[str] = "pipeline.analyze"

    def __init__(self, parent=None) -> None:
        self._dataset: Dataset | None = None
        self._expertise_level = ExpertiseLevel.BEGINNER
        super().__init__(parent)

    def _build_form(self, layout: QVBoxLayout) -> None:
        self._tool_combo = QComboBox(self)
        self._tool_combo.setObjectName("analyzeToolCombo")
        for tool_name in _ANALYZE_DISPATCH:
            self._tool_combo.addItem(tool_name.replace("_", " ").title(), tool_name)
        describe(
            self._tool_combo,
            name="Statistical test",
            description="Which analysis to run against the active dataset.",
        )
        layout.addWidget(self._tool_combo)

        self.run_button = QPushButton("Configure && Run", self)
        self.run_button.setObjectName("analyzeRunButton")
        describe(
            self.run_button,
            name="Configure and run analysis",
            description="Opens a parameter form for the selected test, then runs it.",
            help_anchor=self.help_anchor,
        )
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)

        self.result_card = ResultCard(self)
        layout.addWidget(self.result_card)

        self.set_guidance(_DEFAULT_GUIDANCE)

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Store the dataset this page's Run button acts on -- see this module's own docstring."""
        self._dataset = dataset

    def set_expertise_level(self, level: ExpertiseLevel) -> None:
        """Set which :class:`~src.core.expertise_level.ExpertiseLevel` ``run_analysis`` renders for."""
        self._expertise_level = level

    def _on_run_clicked(self) -> None:
        if self._dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before running an analysis.",
            )
            return

        tool_name = self._tool_combo.currentData()
        tool = get_tool_by_name(tool_name)
        column_names = [str(c) for c in self._dataset.dataframe.columns]
        dialog = AnalysisParameterDialog(tool, column_names, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.run_analysis(
            self._dataset, tool_name, dialog.get_parameters(), self._expertise_level
        )

    def run_analysis(
        self,
        dataset: Dataset,
        tool_name: str,
        parameters: dict,
        level: ExpertiseLevel,
    ) -> None:
        """Run ``tool_name`` against ``dataset`` and render the result -- the method both the
        Run button and a test call directly (see this module's own docstring on why a test
        calls this rather than driving the dialog through a full click sequence)."""
        handler = _ANALYZE_DISPATCH.get(tool_name)
        if handler is None:
            self.set_result_text(f"Unknown analysis tool: {tool_name!r}.")
            return

        self.clear_error()
        try:
            result = handler(dataset.dataframe, **parameters)
        except ApplicationError as exc:
            # Milestone 27: an in-page ErrorState, not QMessageBox.critical -- see
            # StagePage.show_error's own docstring.
            self.show_error("Analysis Failed", str(exc))
            _logger.warning("Analysis '%s' failed: %s", tool_name, exc)
            return
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- shown to the user, not swallowed silently
            self.show_error("Analysis Failed", f"Unexpected error: {exc}")
            _logger.error("Analysis '%s' failed unexpectedly: %s", tool_name, exc)
            return

        self.result_card.display(result, level)
        self.set_result_text(f"Ran {tool_name.replace('_', ' ')}.")
        _logger.info("Ran analysis '%s' via Analyze page.", tool_name)
