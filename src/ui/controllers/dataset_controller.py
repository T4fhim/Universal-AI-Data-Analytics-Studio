# File: src/ui/controllers/dataset_controller.py
"""Owns dataset-open, table-selection, double-click-to-view, and the dataset-read result path.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists.
:meth:`DatasetController.load_dataset` is the one method here that is a new
public entry point rather than a straight rename: it is what a
successfully-read dataset from *any* source (a file dialog, a connected
database) funnels through, so :mod:`~src.ui.controllers.database_controller`
can reuse the exact same "add to workspace, set active, refresh dock,
report warnings" sequence :meth:`_on_dataset_read` always applied, instead
of duplicating it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox, QWidget

from src.core.exceptions import ApplicationError, ServiceError
from src.core.logger import get_logger
from src.readers.reader_registry import get_reader_for_path
from src.services.workspace_service import Dataset, WorkspaceService
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner

_logger = get_logger(__name__)

# Mirrors the extensions each reader in src.readers declares via its own
# SUPPORTED_EXTENSIONS class attribute (see src.readers.base_reader.
# BaseReader). Not built dynamically from those attributes at import time --
# Qt's file-dialog filter syntax groups extensions under one
# human-readable label per format, which doesn't map cleanly onto a flat
# set union the way reader_registry.get_reader_for_path's own
# error-message construction does; a hardcoded filter string here is
# clearer than deriving one generically. This constant needs a manual
# update whenever a new reader is added to src.readers, since nothing
# enforces the two staying in sync automatically.
_DATASET_FILE_FILTER = (
    "All Supported Datasets (*.csv *.tsv *.json *.txt *.xlsx *.xls "
    "*.db *.sqlite *.sqlite3 *.pdf *.docx *.xml *.png *.jpg *.jpeg "
    "*.bmp *.tiff *.tif *.ods *.yaml *.yml *.parquet *.feather *.pptx "
    "*.html *.htm *.zip *.gz *.gzip);;"
    "CSV Files (*.csv *.tsv);;"
    "JSON Files (*.json);;"
    "Text Files (*.txt);;"
    "Excel Files (*.xlsx *.xls);;"
    "SQLite Databases (*.db *.sqlite *.sqlite3);;"
    "PDF Files (*.pdf);;"
    "Word Documents (*.docx);;"
    "XML Files (*.xml);;"
    "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif);;"
    "OpenDocument Spreadsheets (*.ods);;"
    "YAML Files (*.yaml *.yml);;"
    "Parquet Files (*.parquet);;"
    "Feather Files (*.feather);;"
    "PowerPoint Presentations (*.pptx);;"
    "HTML Files (*.html *.htm);;"
    "Archives (*.zip *.gz *.gzip)"
)

# Sentinel distinct from None: None is already a legitimate return value
# from _resolve_table_name (meaning "single-table file, no selection was
# needed"), so the user cancelling the table-picker dialog needs its own,
# different marker -- conflating the two would mean a cancelled dialog
# silently proceeds as if the file only had one table, which is a real,
# distinct bug from simply not offering a picker at all.
_TABLE_SELECTION_CANCELLED = object()

# A second, separately distinct sentinel: zero tables available at all.
# Added in milestone 2c-i, when PDF and Word readers introduced a case
# 2a/2b's readers never faced -- a genuinely valid, unremarkable document
# (a text-only PDF; a Word doc with no tables) that simply has nothing
# tabular in it. This is not an error (the document isn't malformed) and
# it is not the same as "exactly one table" (there is nothing to read at
# all) -- see src.readers.base_reader.BaseReader.list_tables's own
# docstring for how readers report this.
_NO_TABLES_AVAILABLE = object()


class DatasetController:
    """Handles opening a dataset file, table selection, and viewing a dataset's table.

    Args:
        parent: The window dialogs should be parented to.
        workspace_service: Datasets are added and activated here.
        dock_manager: For refreshing the Dataset Explorer, opening a data
            table tab, and appending console messages.
        status_bar: For busy/progress/message feedback.
        state_bus: Refreshed after a dataset load, since
            ``has_active_dataset`` just became true.
        worker_runner: Runs the actual file read off the UI thread.
    """

    def __init__(
        self,
        parent: QWidget,
        workspace_service: WorkspaceService,
        dock_manager: DockManager,
        status_bar: ApplicationStatusBar,
        state_bus: UiStateBus,
        worker_runner: WorkerRunner,
    ) -> None:
        self._parent = parent
        self._workspace_service = workspace_service
        self._dock_manager = dock_manager
        self._status_bar = status_bar
        self._state_bus = state_bus
        self._worker_runner = worker_runner

    def open_dataset(self) -> None:
        file_path_str, _selected_filter = QFileDialog.getOpenFileName(
            self._parent, "Open Dataset", "", _DATASET_FILE_FILTER
        )
        if not file_path_str:
            return  # user cancelled the dialog

        dataset_path = Path(file_path_str)

        try:
            reader_class = get_reader_for_path(dataset_path)
        except ApplicationError as exc:
            QMessageBox.critical(self._parent, "Failed to Open Dataset", str(exc))
            _logger.warning("No reader available for %s: %s", file_path_str, exc)
            return

        table_name = self._resolve_table_name(reader_class, dataset_path)
        if table_name is _TABLE_SELECTION_CANCELLED:
            return  # user cancelled the table-picker dialog
        if table_name is _NO_TABLES_AVAILABLE:
            # Not an error dialog (QMessageBox.critical) -- a document
            # with no detectable tables is not malformed, it simply has
            # nothing tabular in it (a prose-only PDF; a Word doc with no
            # tables). QMessageBox.information matches how this project
            # already distinguishes "something went wrong" from "nothing
            # to report" elsewhere.
            QMessageBox.information(
                self._parent,
                "No Tables Found",
                f"'{dataset_path.name}' does not appear to contain "
                f"any tables that could be extracted as a dataset.",
            )
            _logger.info("No tables found in %s; nothing to load.", file_path_str)
            return

        # Milestone 6: the actual file read -- one of the named hot spots
        # in the milestone plan alongside project reload -- runs on a
        # worker thread. Everything above this point (dialogs,
        # list_tables) must stay on the UI thread since it drives Qt
        # dialogs directly; only the read() call itself, which can
        # genuinely take a while for a large file, moves off it.
        self._status_bar.show_busy(f"Loading {dataset_path.name}…")
        self._worker_runner.run(
            reader_class.read,
            dataset_path,
            table_name=table_name,
            on_result=self.load_dataset,
            on_error=lambda exc, tb: self._on_dataset_read_error(
                file_path_str, exc, tb
            ),
            on_progress=self._status_bar.show_progress,
            on_finished=self._status_bar.hide_busy,
        )

    def on_dataset_double_clicked(self, dataset_id: str) -> None:
        """Open a data-table tab for the double-clicked Dataset Explorer entry.

        Milestone 18: before this, there was no ``QTableView``/
        ``QAbstractTableModel`` anywhere in the application -- a user
        could open a dataset and never see a single cell value, only the
        Dataset Explorer's ``"name (N rows x M cols)"`` summary text.
        """
        try:
            dataset = self._workspace_service.get_dataset(dataset_id)
        except ServiceError as exc:
            # Not fatal -- the item's dataset_id can be stale if the
            # dataset was closed after the tree was last rebuilt but
            # before this double-click was processed. Logged, not shown
            # as a dialog: a double-click on a no-longer-existing item is
            # a timing edge case, not something the user did wrong.
            _logger.warning(
                "Double-clicked dataset %s is no longer loaded: %s",
                dataset_id,
                exc,
            )
            return
        self._dock_manager.display_dataset_table(dataset)

    def load_dataset(self, dataset: Dataset) -> None:
        """Apply a successfully read dataset to the workspace (UI thread).

        The single entry point every successfully-read dataset funnels
        through regardless of source -- a file opened via :meth:`open_dataset`
        (this milestone's worker-result callback) or a table read via a
        connected database (:mod:`~src.ui.controllers.database_controller`).
        """
        self._workspace_service.add_dataset(dataset)
        self._workspace_service.set_active_dataset(dataset.dataset_id)
        self._dock_manager.refresh_dataset_list(self._workspace_service.list_datasets())
        self._state_bus.request_refresh()  # has_active_dataset just became True

        self._status_bar.show_message(
            f"Loaded dataset: {dataset.name} "
            f"({dataset.row_count} rows × {dataset.column_count} cols)"
        )
        self._dock_manager.append_console_message(
            f"Loaded dataset '{dataset.name}' "
            f"({dataset.row_count} rows × {dataset.column_count} cols)."
        )
        _logger.info(
            "Dataset opened via UI: %s (%d rows, %d cols, %d warning(s))",
            dataset.name,
            dataset.row_count,
            dataset.column_count,
            len(dataset.read_warnings),
        )

        if dataset.read_warnings:
            # Informational, not an error dialog -- the load succeeded;
            # these are non-fatal issues the reader flagged along the way
            # (a skipped malformed row, an encoding fallback, an
            # ambiguous-type column -- see the individual readers in
            # src.readers for what each one can report here). Surfaced as
            # a dialog rather than folded into the transient status bar
            # message (which times out and could be missed entirely) or
            # left purely in the log (which a user would never see
            # without deliberately opening the Log dock) -- these
            # warnings represent real, specific data-quality information
            # the reader worked out, and discarding that silently after a
            # successful load would waste it.
            warnings_text = "\n".join(f"• {w}" for w in dataset.read_warnings)
            QMessageBox.information(
                self._parent,
                "Dataset Loaded with Warnings",
                f"'{dataset.name}' was loaded successfully, but the "
                f"following was noted while reading it:\n\n{warnings_text}",
            )

    def close_dataset(self, dataset_id: str) -> None:
        """Remove ``dataset_id`` from the workspace -- milestone 23's "data accumulates until
        exit" fix. Connected to :meth:`~src.ui.dock_manager.DockManager.
        connect_dataset_close_requested`'s "Close Dataset" context-menu action.

        Per :meth:`~src.services.workspace_service.WorkspaceService.close_dataset`'s own
        docstring, this does **not** cascade to datasets derived from ``dataset_id`` -- a
        dangling ``parent_dataset_id`` on a child dataset is expected, not an error this
        method guards against (see that method's own reasoning).
        """
        try:
            self._workspace_service.close_dataset(dataset_id)
        except ServiceError as exc:
            # Stale id (double-close via a rebuild race) -- logged, not shown as a dialog,
            # matching on_dataset_double_clicked's own "not fatal" handling of the same
            # class of timing edge case.
            _logger.warning("Could not close dataset %s: %s", dataset_id, exc)
            return
        self._dock_manager.refresh_dataset_list(self._workspace_service.list_datasets())
        self._state_bus.request_refresh()
        self._status_bar.show_message("Closed dataset.")
        self._dock_manager.append_console_message(f"Closed dataset {dataset_id}.")
        _logger.info("Dataset closed via UI: %s", dataset_id)

    def _on_dataset_read_error(
        self, file_path_str: str, exc: Exception, traceback_text: str
    ) -> None:
        # Mirrors the try/except this replaced: reader_class.read()
        # normally raises ApplicationError for expected failure modes
        # (malformed file, unsupported encoding); the worker forwards
        # whatever it caught unchanged, so this handler treats it the
        # same as the old synchronous except block did.
        QMessageBox.critical(self._parent, "Failed to Open Dataset", str(exc))
        self._dock_manager.append_console_message(f"⚠ Failed to open dataset: {exc}")
        _logger.warning("Failed to open dataset from %s: %s", file_path_str, exc)

    def _resolve_table_name(self, reader_class, dataset_path: Path):
        """Determine which table to read, prompting the user if more than one exists.

        Calls :meth:`~src.readers.base_reader.BaseReader.list_tables`
        unconditionally rather than only for readers known to be
        multi-table -- every reader supports this method (single-table
        readers inherit a default that returns one name derived from the
        file itself; see ``BaseReader.list_tables``'s own docstring), so
        this method does not need to know or check which kind of reader
        it was given.

        Returns:
            ``None`` if the source has exactly one table (no picker was
            needed; :meth:`~src.readers.base_reader.BaseReader.read`
            should be called with ``table_name=None``, which every reader
            handles correctly for the single-table case). A table name
            string if the user picked one from a multi-table source.
            :data:`_TABLE_SELECTION_CANCELLED` if the source has more than
            one table and the user cancelled the picker dialog.
            :data:`_NO_TABLES_AVAILABLE` if the source has zero tables --
            a genuinely valid state for some formats (a text-only PDF, a
            Word document with no tables; see
            :mod:`src.readers.pdf_reader` and
            :mod:`src.readers.word_reader`), not an error condition.
            Callers must check for both sentinels specifically (not just
            falsiness) before proceeding, since ``None`` is itself a
            legitimate, different return value from either.

        If :meth:`list_tables` itself raises (a corrupted file, for
        instance), this method does not catch that -- it propagates to
        :meth:`open_dataset`'s caller, which already wraps the subsequent
        :meth:`~src.readers.base_reader.BaseReader.read` call in the same
        kind of error handling; letting this propagate the same way
        (rather than duplicating a try/except here) keeps error handling
        for "this file is unreadable" in one place regardless of which
        step first discovers it.
        """
        available_tables = reader_class.list_tables(dataset_path)

        if len(available_tables) == 0:
            return _NO_TABLES_AVAILABLE

        if len(available_tables) == 1:
            return None

        chosen_name, user_confirmed = QInputDialog.getItem(
            self._parent,
            "Select Table",
            f"'{dataset_path.name}' contains {len(available_tables)} "
            f"tables. Which one would you like to open?",
            available_tables,
            0,
            False,  # editable=False: user must pick from the list, not type a name
        )
        if not user_confirmed:
            return _TABLE_SELECTION_CANCELLED
        return chosen_name
