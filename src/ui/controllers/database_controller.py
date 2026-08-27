# File: src/ui/controllers/database_controller.py
"""Owns the Connect to Database dialog flow.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QWidget

from src.services.database_connection_service import DatabaseConnectionService
from src.services.workspace_service import Dataset
from src.ui.dialogs.connect_database_dialog import ConnectDatabaseDialog


class DatabaseController:
    """Handles the Connect to Database dialog and forwarding its resulting dataset.

    Args:
        parent: The window the dialog should be parented to.
        database_service: Manages saved profiles and live connections --
            resolved from the shared
            :class:`~src.core.bootstrap.DependencyContainer`.
        on_dataset_loaded: Called with the dataset the dialog read, if any
            -- typically
            :meth:`~src.ui.controllers.dataset_controller.DatasetController.load_dataset`,
            so a table read from a database goes through the exact same
            add-to-workspace/activate/refresh/warn sequence a file-based
            dataset does, rather than duplicating that logic here.
    """

    def __init__(
        self,
        parent: QWidget,
        database_service: DatabaseConnectionService,
        on_dataset_loaded: Callable[[Dataset], None],
    ) -> None:
        self._parent = parent
        self._database_service = database_service
        self._on_dataset_loaded = on_dataset_loaded

    def connect_database(self) -> None:
        # Synchronous, not worker-offloaded -- see ConnectDatabaseDialog's
        # own module docstring for why a live database connection is a
        # deliberate exception to this application's usual "slow work
        # runs off the UI thread" rule.
        dialog = ConnectDatabaseDialog(self._database_service, self._parent)
        if dialog.exec() != ConnectDatabaseDialog.DialogCode.Accepted:
            return

        dataset = dialog.get_result()
        if dataset is None:
            return  # dialog accepted without a table having been read; nothing to add

        self._on_dataset_loaded(dataset)
