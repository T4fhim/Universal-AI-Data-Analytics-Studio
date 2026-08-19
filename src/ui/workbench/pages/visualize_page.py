# File: src/ui/workbench/pages/visualize_page.py
"""The VISUALIZE stage's page: pick columns, get recommendations, build any of the 12 chart types.

Milestone 24's primary acceptance criteria: Treemap and Radar creatable from a real column
selection (previously AI-tool-only -- see :mod:`~src.ui.dialogs.create_visualization_dialog`'s
own docstring for how :class:`~src.ui.widgets.column_multi_select.ColumnMultiSelect` unlocked
both), every :func:`~src.visualization.chart_recommender.recommend_charts` suggestion resolving
in :mod:`~src.visualization.chart_registry`, and clicking a data point in the built chart
filtering the paired :class:`~src.ui.widgets.data_table.data_table_view.DataTableView`.

**Shares its column-picker/field-rebuild machinery with ``CreateVisualizationDialog``, not the
class itself.** Both read the same :func:`~src.visualization.chart_registry.list_dialog_charts`
registry and build the same per-field ``QComboBox``/``ColumnMultiSelect`` shape, but this page
additionally offers a recommendation flow the modal dialog has no room for (a picked-column list,
a ranked suggestion list, and a chart+table split all visible together) -- inlining the dialog's
logic here rather than trying to reuse ``CreateVisualizationDialog`` as a non-modal embedded
widget, which its own ``QDialog`` base and ``exec()``/``accept()`` flow are not shaped for. A
future milestone extracting a shared, dialog-independent "chart field form" widget is a
reasonable follow-up, not something this milestone forces by duplicating ~40 lines of field-
rebuild logic between two files that otherwise serve genuinely different UI shapes (modal
one-shot vs. persistent stage page).

**Recommendation columns don't map onto a chart's required-fields order.** :class:`~src.
visualization.chart_recommender.ChartSuggestion.columns`'s own docstring says its order matches
"the order the corresponding chart builder expects them" -- true for most of
:func:`~src.visualization.chart_recommender.recommend_charts`'s seven suggestion kinds, but not
for its Line suggestion: it returns ``[date_column, numeric_column]`` (x before y), while
:class:`~src.visualization.continuous_charts.LineChart.build`'s signature -- and
``chart_registry``'s own ``required_fields=("y_column",)`` -- puts ``y_column`` first.
:data:`_RECOMMENDATION_FIELD_ORDER` below is an explicit, per-chart-type map from suggestion-
column-position to field name, built directly from :mod:`~src.visualization.chart_recommender`'s
own seven branches, rather than trusting a positional match against ``required_fields`` that
would silently swap Line's x/y on every recommendation-driven build.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.exceptions import ApplicationError
from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import PipelineStage
from src.services.workspace_service import Dataset
from src.ui.a11y.accessible import describe
from src.ui.widgets.chart_view import ChartView
from src.ui.widgets.column_multi_select import ColumnMultiSelect
from src.ui.widgets.data_table.data_table_view import DataTableView
from src.ui.workbench.stage_page import StagePage
from src.visualization.chart_recommender import ChartSuggestion, recommend_charts
from src.visualization.chart_registry import display_name_for, list_dialog_charts

_logger = get_logger(__name__)

_DEFAULT_GUIDANCE = (
    "Check two or more columns and click 'Get Recommendations' for a suggested chart, or "
    "pick any chart type directly and choose its columns. Clicking a point in the built "
    "chart filters the table beside it to matching rows."
)

# See this module's own docstring for why this cannot be derived positionally from
# ChartRegistration.required_fields -- Line's suggestion order and its build() signature
# order genuinely disagree. Only the seven chart_types recommend_charts can actually
# produce need an entry; any other chart type built through the manual picker below has no
# recommendation to prefill from in the first place.
_RECOMMENDATION_FIELD_ORDER: dict[str, tuple[str, ...]] = {
    "line": ("x_column", "y_column"),
    "scatter": ("x_column", "y_column"),
    "bar": ("category_column", "value_column"),
    "pie": ("category_column",),
    "histogram": ("column",),
    "box_plot": ("value_column", "group_column"),
    # "heatmap" has no column fields at all (ChartRegistration.required_fields == ()) --
    # deliberately absent here, not an oversight.
}

_SUGGESTION_ROLE = 0x0100  # first free Qt.ItemDataRole.UserRole+n slot this page uses


def _humanize(field_name: str) -> str:
    """Turn a snake_case parameter name into a readable label -- matches
    :func:`~src.ui.dialogs.create_visualization_dialog._humanize`/:func:`~src.ui.dialogs.
    analysis_parameter_dialog._humanize` exactly, kept as a private copy for the same reason
    those two already are (see ``AnalysisParameterDialog``'s own docstring)."""
    return field_name.replace("_", " ").capitalize()


class VisualizePage(StagePage):
    """The VISUALIZE stage's workbench page: column picker, recommendations, chart+table split."""

    stage: ClassVar[PipelineStage] = PipelineStage.VISUALIZE
    help_anchor: ClassVar[str] = "pipeline.visualize"

    # Carries (figure, chart_type_name, parameters) -- the same shape
    # CreateVisualizationDialog.get_result() returns, so a caller wiring this page up
    # (main_window.py) can reuse VisualizationController's existing registration logic
    # rather than needing a second one just for this page's own builds.
    visualization_built = Signal(object, str, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        self._dataset: Dataset | None = None
        super().__init__(parent)

    def _build_form(self, layout: QVBoxLayout) -> None:
        describe(self, name="Visualize stage form", description="", focusable=False)

        self.column_select = ColumnMultiSelect(self)
        describe(
            self.column_select,
            name="Columns to consider",
            description="Check two or more columns for a chart recommendation.",
        )
        layout.addWidget(self.column_select)

        self.recommend_button = QPushButton("Get Recommendations", self)
        self.recommend_button.setObjectName("visualizeRecommendButton")
        describe(
            self.recommend_button,
            name="Get chart recommendations",
            description="Suggests chart types for the checked columns.",
        )
        self.recommend_button.clicked.connect(self._on_recommend_clicked)
        layout.addWidget(self.recommend_button)

        self.recommendation_list = QListWidget(self)
        self.recommendation_list.setObjectName("visualizeRecommendationList")
        describe(
            self.recommendation_list,
            name="Recommended charts",
            description="Double-click a suggestion to load it into the builder below.",
        )
        self.recommendation_list.itemActivated.connect(
            self._on_recommendation_activated
        )
        layout.addWidget(self.recommendation_list)

        self.title_field = QLineEdit(self)
        describe(
            self.title_field,
            name="Chart title",
            description="Optional title for the built chart.",
        )
        layout.addWidget(self.title_field)

        self.chart_type_combo = QComboBox(self)
        self.chart_type_combo.setObjectName("visualizeChartTypeCombo")
        for name in list_dialog_charts():
            self.chart_type_combo.addItem(display_name_for(name), name)
        describe(
            self.chart_type_combo,
            name="Chart type",
            description="Which chart type to build.",
        )
        self.chart_type_combo.currentIndexChanged.connect(self._rebuild_field_widgets)
        layout.addWidget(self.chart_type_combo)

        self._field_form_container = QWidget(self)
        self._field_form_layout = QFormLayout(self._field_form_container)
        self._field_form_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._field_form_container)
        self._column_fields: dict[str, QComboBox | ColumnMultiSelect] = {}

        self.build_button = QPushButton("Build Chart", self)
        self.build_button.setObjectName("visualizeBuildButton")
        describe(
            self.build_button,
            name="Build chart",
            description="Builds the selected chart type from the chosen columns.",
            help_anchor=self.help_anchor,
        )
        self.build_button.clicked.connect(self._on_build_clicked)
        layout.addWidget(self.build_button)

        split_container = QWidget(self)
        split_layout = QHBoxLayout(split_container)
        split_layout.setContentsMargins(0, 0, 0, 0)

        self.chart_view = ChartView(split_container)
        describe(
            self.chart_view,
            name="Built chart",
            description="The most recently built chart. Click a point to filter the table.",
        )
        self.chart_view.bridge.point_clicked.connect(self._on_chart_point_clicked)

        self.data_table = DataTableView(split_container)
        describe(
            self.data_table,
            name="Chart data table",
            description="The active dataset's rows, filterable by clicking a chart point.",
        )

        split_layout.addWidget(self.chart_view, stretch=1)
        split_layout.addWidget(self.data_table, stretch=1)
        layout.addWidget(split_container, stretch=1)

        self._rebuild_field_widgets()
        self.set_guidance(_DEFAULT_GUIDANCE)

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Store the dataset this page's pickers/builder act on -- see :meth:`~src.ui.
        workbench.pages.analyze_page.AnalyzePage.set_dataset`'s own docstring for the shape
        rationale every sibling stage page follows."""
        self._dataset = dataset
        self.recommendation_list.clear()
        if dataset is not None:
            column_names = [str(c) for c in dataset.dataframe.columns]
            self.column_select.set_columns(column_names)
            self.data_table.load_dataset(dataset)
            self._rebuild_field_widgets()
        else:
            self.column_select.set_columns([])

    # -- Recommendations ---------------------------------------------------------

    def _on_recommend_clicked(self) -> None:
        if self._dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before requesting recommendations.",
            )
            return

        selected_columns = self.column_select.selected_columns()
        if len(selected_columns) < 2:
            QMessageBox.information(
                self,
                "Select Columns",
                "Check two or more columns to get a chart recommendation.",
            )
            return

        self.get_recommendations(self._dataset, selected_columns)

    def get_recommendations(
        self, dataset: Dataset, selected_columns: list[str]
    ) -> list[ChartSuggestion]:
        """Populate :attr:`recommendation_list` from ``dataset``'s ``selected_columns`` subset.

        The method both the button and a test call directly -- see :meth:`~src.ui.workbench.
        pages.explore_page.ExplorePage.run_exploration`'s own docstring for why a test calls a
        plain method rather than driving a click sequence through a real button.
        """
        subset = dataset.dataframe[selected_columns]
        suggestions = recommend_charts(subset)

        self.recommendation_list.clear()
        for suggestion in suggestions:
            item = QListWidgetItem(
                f"{display_name_for(suggestion.chart_type)}: {suggestion.reason}"
            )
            item.setData(_SUGGESTION_ROLE, suggestion)
            self.recommendation_list.addItem(item)

        if not suggestions:
            self.set_result_text(
                "No chart recommendation for these columns -- pick a chart type manually."
            )
        else:
            self.set_result_text(f"{len(suggestions)} chart recommendation(s).")
        return suggestions

    def _on_recommendation_activated(self, item: QListWidgetItem) -> None:
        suggestion: ChartSuggestion = item.data(_SUGGESTION_ROLE)
        self.apply_recommendation(suggestion)

    def apply_recommendation(self, suggestion: ChartSuggestion) -> None:
        """Load ``suggestion`` into the manual builder: select its chart type, prefill its
        columns. Does not build the chart itself -- the user still confirms via
        :attr:`build_button`, matching every other stage page's "form fills in, Run button
        commits" shape rather than auto-building on selection."""
        combo_index = self.chart_type_combo.findData(suggestion.chart_type)
        if combo_index < 0:
            _logger.warning(
                "Recommended chart_type %r not found in chart_type_combo.",
                suggestion.chart_type,
            )
            return
        self.chart_type_combo.setCurrentIndex(
            combo_index
        )  # triggers _rebuild_field_widgets

        field_order = _RECOMMENDATION_FIELD_ORDER.get(suggestion.chart_type, ())
        for field_name, column_name in zip(field_order, suggestion.columns):
            widget = self._column_fields.get(field_name)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(column_name)
            elif isinstance(widget, ColumnMultiSelect):
                widget.set_selected_columns([column_name])

    # -- Manual chart-type/field picking ---------------------------------------------------

    def _rebuild_field_widgets(self, *_args: object) -> None:
        while self._field_form_layout.rowCount() > 0:
            self._field_form_layout.removeRow(0)
        self._column_fields.clear()

        chart_type_name = self.chart_type_combo.currentData()
        if not chart_type_name:
            return
        registration = list_dialog_charts()[chart_type_name]
        column_names = (
            [str(c) for c in self._dataset.dataframe.columns]
            if self._dataset is not None
            else []
        )

        for field_name in registration.required_fields:
            widget = self._build_field_widget(field_name, column_names)
            self._field_form_layout.addRow(f"{_humanize(field_name)}:", widget)
            self._column_fields[field_name] = widget

        for field_name in registration.optional_fields:
            widget = self._build_field_widget(field_name, column_names, optional=True)
            self._field_form_layout.addRow(
                f"{_humanize(field_name)} (optional):", widget
            )
            self._column_fields[field_name] = widget

    def _build_field_widget(
        self, field_name: str, column_names: list[str], *, optional: bool = False
    ) -> QComboBox | ColumnMultiSelect:
        chart_type_name = self.chart_type_combo.currentData()
        registration = list_dialog_charts()[chart_type_name]
        if field_name in registration.list_fields:
            multi_select = ColumnMultiSelect(self)
            multi_select.set_columns(column_names)
            return multi_select
        combo = QComboBox(self)
        if optional:
            combo.addItem("(none)")
        combo.addItems(column_names)
        return combo

    # -- Building ---------------------------------------------------------

    def _on_build_clicked(self) -> None:
        if self._dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before building a chart.",
            )
            return
        self.build_chart(self._dataset)

    def build_chart(self, dataset: Dataset) -> None:
        """Build the currently selected chart type/columns and render the chart+table split.

        The method both :attr:`build_button` and a test call directly -- same "plain method a
        test can call without driving a full click sequence" shape as :meth:`get_recommendations`.
        """
        chart_type_name = self.chart_type_combo.currentData()
        if not chart_type_name:
            self.set_result_text("No chart type selected.")
            return
        registration = list_dialog_charts()[chart_type_name]

        parameters: dict = {}
        missing: list[str] = []
        for field_name, widget in self._column_fields.items():
            if isinstance(widget, ColumnMultiSelect):
                selected = widget.selected_columns()
                if selected:
                    parameters[field_name] = selected
                elif field_name in registration.required_fields:
                    missing.append(field_name)
            else:
                value = widget.currentText()
                if value and value != "(none)":
                    parameters[field_name] = value
                elif field_name in registration.required_fields:
                    missing.append(field_name)

        if missing:
            QMessageBox.warning(
                self,
                "Missing Required Fields",
                "Please select a column for: "
                + ", ".join(_humanize(f) for f in missing),
            )
            return

        title = self.title_field.text().strip()
        if title:
            parameters["title"] = title

        self.clear_error()
        try:
            figure = registration.chart_class.build(dataset.dataframe, **parameters)
        except ApplicationError as exc:
            # Milestone 27: an in-page ErrorState, not QMessageBox.critical -- see
            # StagePage.show_error's own docstring.
            self.show_error("Failed to Build Chart", str(exc))
            _logger.warning("Chart build failed: %s", exc)
            return
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- shown to the user, not swallowed silently
            self.show_error("Failed to Build Chart", f"Unexpected error: {exc}")
            _logger.error("Chart build failed unexpectedly: %s", exc)
            return

        self.chart_view.display_figure(figure)
        self.data_table.load_dataset(dataset)
        self.set_result_text(f"Built {display_name_for(chart_type_name)} chart.")
        _logger.info("Built chart '%s' via Visualize page.", chart_type_name)
        self.visualization_built.emit(figure, chart_type_name, parameters)

    # -- Chart click -> table filter (milestone 24 acceptance criterion) --------------------

    def _on_chart_point_clicked(self, payload: dict) -> None:
        """Filter :attr:`data_table` to rows matching a clicked point's ``x`` value.

        ``payload`` is whatever :meth:`~src.ui.web.chart_bridge.ChartBridge.
        notify_point_clicked` forwarded -- ``x`` is present on every chart type this page can
        build (categorical axis label or numeric x value alike), so it is the one field usable
        as a filter term regardless of which chart type produced the click, unlike ``y``/
        ``curveNumber``/``pointIndex`` which are chart-type-specific.
        """
        if "x" not in payload:
            return
        self.data_table.filter_by_text(str(payload["x"]))
