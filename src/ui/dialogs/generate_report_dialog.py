# File: src/ui/dialogs/generate_report_dialog.py
"""The "Generate Report" wizard: format, sections, expertise level, and output path.

A single-page ``QDialog`` form rather than a multi-step ``QWizard`` —
matching :class:`~src.ui.dialogs.create_visualization_dialog.
CreateVisualizationDialog`'s and :class:`~src.ui.dialogs.
settings_dialog.SettingsDialog`'s existing shape in this project (a
form the user fills in once and accepts), since the milestone plan's
"small wizard" has few enough fields (format, sections, expertise
level, title, output path) that a multi-page flow would add navigation
overhead without a real benefit. This dialog only collects choices —
it does not build the report itself; the actual export runs on a
:class:`~src.workers.BaseWorker` thread from
:mod:`src.ui.main_window`, per milestone 6's "must not block the UI
thread" rule for anything this slow (report generation rasterizes
every chart via kaleido and writes a real file).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import PipelineStage
from src.services.report_service import available_formats

_logger = get_logger(__name__)

# Matches src.services.report_service's _EXPORTERS keys — kept as its
# own small mapping here (format key -> (Qt file-dialog filter, default
# extension)) since the file-picker filter string is a UI concern the
# service layer has no reason to know about.
_FORMAT_FILE_FILTERS: dict[str, tuple[str, str]] = {
    "pdf": ("PDF Document (*.pdf)", "pdf"),
    "html": ("HTML Report (*.html)", "html"),
    "docx": ("Word Document (*.docx)", "docx"),
    "xlsx": ("Excel Workbook (*.xlsx)", "xlsx"),
}

# Human-readable checklist labels, in pipeline order — mirrors
# src.services.report_service's own _STAGE_DISPLAY_NAMES so a section
# the user unchecks here matches the label they'll see (or not see) in
# the generated report exactly.
_STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.UPLOAD: "Upload",
    PipelineStage.UNDERSTAND: "Understand",
    PipelineStage.CLEAN: "Clean",
    PipelineStage.EXPLORE: "Explore",
    PipelineStage.ANALYZE: "Analyze",
    PipelineStage.VISUALIZE: "Visualize",
    PipelineStage.PREDICT: "Predict",
    PipelineStage.EXPLAIN: "Explain",
}


class GenerateReportDialog(QDialog):
    """Collects report options: format, which logged stages to include, expertise level, and output path.

    Args:
        dataset_name: The active dataset's display name — used to
            build the default report title and shown so the user
            confirms which dataset they're reporting on.
        available_stages: Which
            :class:`~src.services.analysis_orchestrator_service.
            PipelineStage` values currently have at least one
            :class:`~src.services.analysis_orchestrator_service.
            AnalysisLogEntry` for this dataset — only these appear as
            checkable section options, since a stage with no log entry
            has nothing to include (see
            :meth:`~src.services.analysis_orchestrator_service.
            AnalysisLog.completed_stages`).
        parent: Parent widget, typically the main window.
    """

    def __init__(
        self,
        dataset_name: str,
        available_stages: list[PipelineStage],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataset_name = dataset_name
        self._available_stages = available_stages
        self._output_path: Path | None = None

        self.setWindowTitle("Generate Report")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._title_field = QLineEdit(f"{dataset_name} Report", self)
        form.addRow("Report title:", self._title_field)

        self._format_combo = QComboBox(self)
        for format_key in available_formats():
            label, _extension = _FORMAT_FILE_FILTERS.get(
                format_key, (format_key.upper(), format_key)
            )
            self._format_combo.addItem(label.split(" (")[0], format_key)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        form.addRow("Format:", self._format_combo)

        self._expertise_combo = QComboBox(self)
        for level in ExpertiseLevel:
            self._expertise_combo.addItem(
                level.name.replace("_", " ").title(), level.value
            )
        form.addRow("Explain results for:", self._expertise_combo)

        self._output_path_field = QLineEdit(self)
        self._output_path_field.setReadOnly(True)
        browse_button = QPushButton("Browse...", self)
        browse_button.clicked.connect(self._on_browse_output_path)
        form.addRow("Save to:", self._output_path_field)
        form.addRow("", browse_button)

        layout.addLayout(form)

        sections_box = QGroupBox("Sections to include", self)
        sections_layout = QVBoxLayout(sections_box)
        self._section_checkboxes: dict[PipelineStage, QCheckBox] = {}
        for stage in available_stages:
            checkbox = QCheckBox(
                _STAGE_LABELS.get(stage, stage.value.title()), sections_box
            )
            checkbox.setChecked(True)
            sections_layout.addWidget(checkbox)
            self._section_checkboxes[stage] = checkbox
        if not available_stages:
            placeholder = QCheckBox(
                "No pipeline stages have run for this dataset yet — the "
                "report will only contain the dataset summary.",
                sections_box,
            )
            placeholder.setEnabled(False)
            sections_layout.addWidget(placeholder)
        layout.addWidget(sections_box)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        _logger.debug("GenerateReportDialog constructed for dataset %r.", dataset_name)

    def _on_format_changed(self) -> None:
        # Clears a previously chosen output path when the format
        # changes, rather than silently keeping a path whose extension
        # no longer matches the newly selected format — the user must
        # re-browse (which derives a corrected extension itself in
        # _on_browse_output_path) rather than this dialog quietly
        # writing e.g. a .pdf file under a .html name.
        self._output_path = None
        self._output_path_field.clear()

    def _on_browse_output_path(self) -> None:
        format_key = self._format_combo.currentData()
        file_filter, extension = _FORMAT_FILE_FILTERS.get(
            format_key, ("All Files (*)", "")
        )
        default_name = f"{self._title_field.text().strip() or 'report'}.{extension}"

        file_path_str, _selected_filter = QFileDialog.getSaveFileName(
            self, "Save Report As", default_name, file_filter
        )
        if not file_path_str:
            return  # user cancelled the dialog

        path = Path(file_path_str)
        if extension and path.suffix.lower() != f".{extension}":
            path = path.with_suffix(f".{extension}")
        self._output_path = path
        self._output_path_field.setText(str(path))

    def _on_accept(self) -> None:
        if self._output_path is None:
            QMessageBox.information(
                self, "No Output Path", "Choose where to save the report first."
            )
            return
        self.accept()

    def get_result(self) -> dict:
        """Return the chosen report options after a successful accept.

        Only meaningful after :meth:`exec` has returned
        ``QDialog.DialogCode.Accepted`` — matches
        :meth:`~src.ui.dialogs.create_visualization_dialog.
        CreateVisualizationDialog.get_result`'s own convention.

        Returns:
            A dict with keys ``title`` (str), ``report_format`` (str),
            ``expertise_level`` (:class:`ExpertiseLevel`),
            ``included_stages`` (``set[PipelineStage]``, possibly
            empty if the user unchecked every section), and
            ``output_path`` (:class:`~pathlib.Path`).
        """
        included_stages = {
            stage
            for stage, checkbox in self._section_checkboxes.items()
            if checkbox.isChecked()
        }
        return {
            "title": self._title_field.text().strip() or f"{self._dataset_name} Report",
            "report_format": self._format_combo.currentData(),
            "expertise_level": ExpertiseLevel(self._expertise_combo.currentData()),
            "included_stages": included_stages,
            "output_path": self._output_path,
        }
