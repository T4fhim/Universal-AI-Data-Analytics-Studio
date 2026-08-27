# File: src/ui/dialogs/connect_database_dialog.py
"""The "Connect to Database" dialog: profile fields, test/connect, and a table picker.

Same single-page ``QDialog`` form shape as
:class:`~src.ui.dialogs.create_visualization_dialog.
CreateVisualizationDialog`/:class:`~src.ui.dialogs.
generate_report_dialog.GenerateReportDialog`. "Test Connection" and
"Connect" both call straight into
:class:`~src.services.database_connection_service.
DatabaseConnectionService` synchronously (with a wait-cursor for
feedback), rather than through a :class:`~src.workers.BaseWorker`
thread the way :mod:`src.ui.main_window`'s own slow operations
(dashboard rendering, report generation) are offloaded — a deliberate
scope decision: this dialog is modal already, and threading a
cancellable connect against a potentially slow/unreachable network
host would mean restructuring it into a non-modal flow, which is
larger than this milestone's UI surface calls for. A hung connection
attempt blocks this dialog, not the whole application.

The **password field is never written to a saved profile** — see
:class:`~src.database.connection_profile.ConnectionProfile`'s own
docstring for the full reasoning. "Save this profile" persists only
the name/type/host/port/database/username fields; the password must be
re-entered the next time this profile is used, in this session or a
future one.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from src.core.exceptions import ApplicationError
from src.core.logger import get_logger
from src.database.connection_profile import (
    DEFAULT_PORTS,
    ConnectionProfile,
    DatabaseType,
)
from src.database.connection_registry import get_connector_class, list_supported_types
from src.database.database_reader import DatabaseReader
from src.services.database_connection_service import DatabaseConnectionService
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_NEW_PROFILE_LABEL = "(New profile)"


class ConnectDatabaseDialog(QDialog):
    """Collects connection details, tests/opens a connection, and reads a chosen table into a Dataset.

    Args:
        database_service: Where saved profiles are read from/written
            to, and where the live connection this dialog opens is
            tracked for the rest of the session.
        parent: Parent widget, typically the main window.
    """

    def __init__(
        self, database_service: DatabaseConnectionService, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._database_service = database_service
        self._active_profile: ConnectionProfile | None = None
        self._built_dataset: Dataset | None = None

        self.setWindowTitle(self.tr("Connect to Database"))
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QFormLayout(self)

        self._saved_profile_combo = QComboBox(self)
        self._saved_profile_combo.addItem(_NEW_PROFILE_LABEL, None)
        for profile in database_service.list_profiles():
            self._saved_profile_combo.addItem(profile.name, profile)
        self._saved_profile_combo.currentIndexChanged.connect(
            self._on_saved_profile_selected
        )
        # Milestone 23: "Delete Profile" -- the first UI path to
        # DatabaseConnectionService.delete_profile; before this, a saved profile could only
        # accumulate, never be removed, once written.
        self._delete_profile_button = QPushButton("Delete Profile", self)
        self._delete_profile_button.clicked.connect(self._on_delete_profile)
        saved_profile_row = QWidget(self)
        saved_profile_row_layout = QHBoxLayout(saved_profile_row)
        saved_profile_row_layout.setContentsMargins(0, 0, 0, 0)
        saved_profile_row_layout.addWidget(self._saved_profile_combo, 1)
        saved_profile_row_layout.addWidget(self._delete_profile_button)
        layout.addRow("Saved profile:", saved_profile_row)

        self._name_field = QLineEdit(self)
        layout.addRow("Profile name:", self._name_field)

        self._db_type_combo = QComboBox(self)
        for db_type in list_supported_types():
            # Item data is db_type.value (a plain str), not the
            # DatabaseType member itself — PySide6's QVariant marshaling
            # silently coerces a str-subclassed Enum stored as item
            # data down to a bare str on the way back out through
            # currentData()/findData(), which would make every
            # `db_type == DatabaseType.X` comparison downstream
            # silently false. See _current_db_type() below, which is
            # the one place that re-wraps the retrieved value back into
            # a real DatabaseType.
            self._db_type_combo.addItem(
                db_type.value.replace("_", " ").title(), db_type.value
            )
        self._db_type_combo.currentIndexChanged.connect(self._on_db_type_changed)
        layout.addRow("Database type:", self._db_type_combo)

        self._host_field = QLineEdit(self)
        layout.addRow("Host:", self._host_field)

        self._port_field = QLineEdit(self)
        layout.addRow("Port:", self._port_field)

        self._database_field = QLineEdit(self)
        layout.addRow("Database / file path:", self._database_field)

        self._username_field = QLineEdit(self)
        layout.addRow("Username:", self._username_field)

        self._password_field = QLineEdit(self)
        self._password_field.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Password:", self._password_field)

        self._save_profile_checkbox = QCheckBox(
            "Save this profile (name/host/port/database/username only — "
            "never the password)",
            self,
        )
        layout.addRow("", self._save_profile_checkbox)

        button_row_widget = QWidget(self)
        button_row_layout = QHBoxLayout(button_row_widget)
        button_row_layout.setContentsMargins(0, 0, 0, 0)
        self._test_button = QPushButton("Test Connection", self)
        self._test_button.clicked.connect(self._on_test_connection)
        self._connect_button = QPushButton("Connect", self)
        self._connect_button.clicked.connect(self._on_connect)
        button_row_layout.addWidget(self._test_button)
        button_row_layout.addWidget(self._connect_button)
        layout.addRow(button_row_widget)

        self._table_combo = QComboBox(self)
        self._table_combo.setEnabled(False)
        layout.addRow("Table:", self._table_combo)

        self._on_db_type_changed()

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        _logger.debug("ConnectDatabaseDialog constructed.")

    def _current_db_type(self) -> DatabaseType:
        """Return the selected database type, re-wrapping the combo's plain-str item data.

        See the ``_db_type_combo.addItem(...)`` call above for why item
        data is stored as ``db_type.value`` rather than the
        ``DatabaseType`` member itself.
        """
        return DatabaseType(self._db_type_combo.currentData())

    def _on_saved_profile_selected(self) -> None:
        profile: ConnectionProfile | None = self._saved_profile_combo.currentData()
        if profile is None:
            return
        self._name_field.setText(profile.name)
        index = self._db_type_combo.findData(profile.db_type.value)
        if index >= 0:
            self._db_type_combo.setCurrentIndex(index)
        self._host_field.setText(profile.host)
        self._port_field.setText(str(profile.resolved_port() or ""))
        self._database_field.setText(profile.database)
        self._username_field.setText(profile.username)
        self._password_field.clear()  # never saved — see module docstring

    def _on_delete_profile(self) -> None:
        """Delete the currently selected saved profile -- real, reachable path to
        :meth:`~src.services.database_connection_service.DatabaseConnectionService.
        delete_profile` (milestone 23)."""
        profile: ConnectionProfile | None = self._saved_profile_combo.currentData()
        if profile is None:
            QMessageBox.information(
                self, "No Profile Selected", "Choose a saved profile to delete."
            )
            return
        self._database_service.delete_profile(profile.profile_id)
        index = self._saved_profile_combo.currentIndex()
        self._saved_profile_combo.removeItem(index)
        self._saved_profile_combo.setCurrentIndex(0)  # back to "(New profile)"
        _logger.info("Deleted saved connection profile '%s'.", profile.name)

    def _on_db_type_changed(self) -> None:
        db_type = self._current_db_type()
        is_duckdb = db_type == DatabaseType.DUCKDB

        self._host_field.setEnabled(not is_duckdb)
        self._port_field.setEnabled(not is_duckdb)
        self._username_field.setEnabled(not is_duckdb)
        self._password_field.setEnabled(not is_duckdb)

        default_port = DEFAULT_PORTS.get(db_type)
        if default_port is not None and not self._port_field.text():
            self._port_field.setText(str(default_port))

    def _build_profile(self) -> ConnectionProfile:
        port_text = self._port_field.text().strip()
        return ConnectionProfile(
            name=self._name_field.text().strip() or "Untitled connection",
            db_type=self._current_db_type(),
            database=self._database_field.text().strip(),
            host=self._host_field.text().strip(),
            port=int(port_text) if port_text.isdigit() else None,
            username=self._username_field.text().strip(),
        )

    def _on_test_connection(self) -> None:
        profile = self._build_profile()
        password = self._password_field.text()
        # Cleared immediately after use, win or lose — a plaintext
        # password has no reason to keep sitting in this widget once
        # this method has already read it (see the module docstring's
        # own note on this; a security review of this milestone flagged
        # it as worth doing explicitly rather than only on dialog close).
        self._password_field.clear()

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            connector_class = get_connector_class(profile.db_type)
            connector_class(profile, password).test_connection()
        except ApplicationError as exc:
            QMessageBox.critical(self, "Connection Failed", str(exc))
            return
        finally:
            self.unsetCursor()

        QMessageBox.information(
            self, "Connection Successful", "The connection succeeded."
        )

    def _on_connect(self) -> None:
        profile = self._build_profile()
        password = self._password_field.text()
        self._password_field.clear()  # see _on_test_connection's own comment

        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            connection = self._database_service.open_connection(profile, password)
            tables = connection.list_tables()
        except ApplicationError as exc:
            QMessageBox.critical(self, "Connection Failed", str(exc))
            return
        finally:
            self.unsetCursor()

        self._active_profile = profile
        self._table_combo.clear()
        self._table_combo.addItems(tables)
        self._table_combo.setEnabled(bool(tables))

        if self._save_profile_checkbox.isChecked():
            self._database_service.save_profile(profile)

        _logger.info(
            "Connected to '%s' (%s): %d table(s) found.",
            profile.name,
            profile.db_type.value,
            len(tables),
        )

    def _on_accept(self) -> None:
        if self._active_profile is None or not self._table_combo.currentText():
            QMessageBox.information(
                self,
                "Not Connected",
                "Click Connect and choose a table before continuing.",
            )
            return

        table_name = self._table_combo.currentText()
        try:
            connection = self._database_service.get_connection(
                self._active_profile.profile_id
            )
            self._built_dataset = DatabaseReader.read_table(connection, table_name)
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Read Table", str(exc))
            return

        self.accept()

    def get_result(self) -> Dataset | None:
        """Return the Dataset read from the chosen table after a successful accept, else ``None``."""
        return self._built_dataset
