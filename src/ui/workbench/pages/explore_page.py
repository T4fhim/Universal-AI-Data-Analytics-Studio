# File: src/ui/workbench/pages/explore_page.py
"""The EXPLORE stage's page: relationships between columns -- crosstabs, aggregates, correlation.

Sibling of :class:`~src.ui.workbench.pages.analyze_page.AnalyzePage`, sharing its exact
dispatch-and-render shape (see that module's own docstring for why it calls :mod:`src.analysis`
functions directly rather than through :mod:`src.ai.tool_registry`/the orchestrator). Split into
its own page rather than folded into ``AnalyzePage`` because the plan's own per-stage rationale
text (:data:`~src.services.analysis_orchestrator_service._STAGE_RATIONALE`) describes EXPLORE
and ANALYZE as two different moments in the guided pipeline -- "look at relationships ... before
committing to a specific statistical test" versus "run a targeted statistical analysis" -- and
this page's three tools (:func:`~src.analysis.aggregation.aggregate`,
:func:`~src.analysis.crosstab.cross_tabulate`, :func:`~src.analysis.correlation.
compute_correlation`) are exactly the exploratory ones that rationale names.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from PySide6.QtWidgets import QComboBox, QMessageBox, QPushButton, QVBoxLayout

from src.ai.tool_registry import get_tool_by_name
from src.analysis.aggregation import aggregate
from src.analysis.correlation import compute_correlation
from src.analysis.crosstab import cross_tabulate
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
    "Look at relationships between columns -- crosstabs, grouped aggregates, or a correlation "
    "matrix -- before committing to a specific statistical test."
)

# Tool name -> callable(dataframe, **params) -> result (a DataFrame for the first two, a
# CorrelationResult for the third -- see this module's own docstring for why this dispatches to
# src.analysis directly rather than through src.ai.tool_registry's dict-returning handlers).
_EXPLORE_DISPATCH: dict[str, Callable[..., object]] = {
    "aggregate": aggregate,
    "cross_tabulate": cross_tabulate,
    "compute_correlation": compute_correlation,
}


class ExplorePage(StagePage):
    """The EXPLORE stage's workbench page: choose a relationship view, configure it, render it."""

    stage: ClassVar[PipelineStage] = PipelineStage.EXPLORE
    help_anchor: ClassVar[str] = "pipeline.explore"

    def __init__(self, parent=None) -> None:
        self._dataset: Dataset | None = None
        self._expertise_level = ExpertiseLevel.BEGINNER
        super().__init__(parent)

    def _build_form(self, layout: QVBoxLayout) -> None:
        self._tool_combo = QComboBox(self)
        self._tool_combo.setObjectName("exploreToolCombo")
        for tool_name in _EXPLORE_DISPATCH:
            self._tool_combo.addItem(tool_name.replace("_", " ").title(), tool_name)
        describe(
            self._tool_combo,
            name="Exploration view",
            description="Which relationship view to build against the active dataset.",
        )
        layout.addWidget(self._tool_combo)

        self.run_button = QPushButton("Configure && Run", self)
        self.run_button.setObjectName("exploreRunButton")
        describe(
            self.run_button,
            name="Configure and run exploration",
            description="Opens a parameter form for the selected view, then runs it.",
            help_anchor=self.help_anchor,
        )
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)

        self.result_card = ResultCard(self)
        layout.addWidget(self.result_card)

        self.set_guidance(_DEFAULT_GUIDANCE)

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Store the dataset this page's Run button acts on -- see :class:`~src.ui.workbench.
        pages.analyze_page.AnalyzePage.set_dataset`'s own docstring for the shape rationale.
        """
        self._dataset = dataset

    def set_expertise_level(self, level: ExpertiseLevel) -> None:
        self._expertise_level = level

    def _on_run_clicked(self) -> None:
        if self._dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before exploring it.",
            )
            return

        tool_name = self._tool_combo.currentData()
        tool = get_tool_by_name(tool_name)
        column_names = [str(c) for c in self._dataset.dataframe.columns]
        dialog = AnalysisParameterDialog(tool, column_names, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.run_exploration(
            self._dataset, tool_name, dialog.get_parameters(), self._expertise_level
        )

    def run_exploration(
        self,
        dataset: Dataset,
        tool_name: str,
        parameters: dict,
        level: ExpertiseLevel,
    ) -> None:
        """Run ``tool_name`` against ``dataset`` and render the result -- see
        :meth:`~src.ui.workbench.pages.analyze_page.AnalyzePage.run_analysis`'s own docstring for
        why both the Run button and tests call a plain method rather than driving the dialog.
        """
        handler = _EXPLORE_DISPATCH.get(tool_name)
        if handler is None:
            self.set_result_text(f"Unknown exploration tool: {tool_name!r}.")
            return

        self.clear_error()
        try:
            result = handler(dataset.dataframe, **parameters)
        except ApplicationError as exc:
            # Milestone 27: an in-page ErrorState, not QMessageBox.critical -- this page stays
            # visible and re-runnable afterward, so the failure is persistent page state, not a
            # one-shot interruption. See StagePage.show_error's own docstring.
            self.show_error("Exploration Failed", str(exc))
            _logger.warning("Exploration '%s' failed: %s", tool_name, exc)
            return
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- shown to the user, not swallowed silently
            self.show_error("Exploration Failed", f"Unexpected error: {exc}")
            _logger.error("Exploration '%s' failed unexpectedly: %s", tool_name, exc)
            return

        self.result_card.display(result, level)
        self.set_result_text(f"Ran {tool_name.replace('_', ' ')}.")
        _logger.info("Ran exploration '%s' via Explore page.", tool_name)
