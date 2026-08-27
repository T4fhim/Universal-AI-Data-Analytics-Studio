# File: src/services/database_connection_service.py
"""Session-scoped tracking of saved connection profiles and live database connections.

Two separate lifetimes, deliberately not conflated:

* **Saved profiles** (:class:`~src.database.connection_profile.
  ConnectionProfile`) persist across restarts, via
  :class:`~src.services.settings_service.SettingsService`'s
  ``database.profiles`` config key (see :mod:`src.core.config`'s
  three-place schema update for this milestone). They hold no
  password.
* **Live connections** (:class:`~src.database.base_connection.
  BaseDatabaseConnection` instances, and the plaintext passwords used
  to open them) exist only in this service's own in-memory
  dictionaries, for the lifetime of the running process. Closing the
  application discards every open connection and every password it was
  given — there is no "remember my password" option, by design (see
  :class:`~src.database.connection_profile.ConnectionProfile`'s own
  docstring for the full reasoning, flagged in the milestone plan for
  a security-reviewer pass).

Registered as a bootstrap singleton alongside :class:`~src.services.
workspace_service.WorkspaceService`, which is exactly the pattern this
service's own "profiles persist, connections don't" split mirrors at a
smaller scale: :class:`~src.services.workspace_service.WorkspaceService`
also holds only in-memory, session-scoped state for the live objects it
tracks (datasets, visualizations), while long-term persistence goes
through a different, explicit save step
(:class:`~src.services.project_service.ProjectService`).
"""

from __future__ import annotations

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.database.base_connection import BaseDatabaseConnection
from src.database.connection_profile import ConnectionProfile
from src.database.connection_registry import get_connector_class
from src.services.settings_service import SettingsService

_logger = get_logger(__name__)


class DatabaseConnectionService:
    """Manages saved connection profiles and live database connections for the current session.

    Args:
        settings_service: Where saved profiles are persisted, under
            the ``database.profiles`` config key.
    """

    def __init__(self, settings_service: SettingsService) -> None:
        self._settings_service = settings_service
        self._live_connections: dict[str, BaseDatabaseConnection] = {}

    # -- Saved profiles (persisted, credential-free) ---------------------------

    def list_profiles(self) -> list[ConnectionProfile]:
        """Return every saved connection profile, from config."""
        raw_profiles = self._settings_service.get("database", "profiles", default=[])
        return [ConnectionProfile.from_dict(entry) for entry in raw_profiles]

    def save_profile(self, profile: ConnectionProfile) -> None:
        """Add or update ``profile`` in the saved profiles list and persist it.

        Matches by :attr:`~src.database.connection_profile.
        ConnectionProfile.profile_id` — saving a profile whose ID
        already exists replaces that entry (an edit), any other ID
        appends a new one.
        """
        profiles = self.list_profiles()
        replaced = False
        for index, existing in enumerate(profiles):
            if existing.profile_id == profile.profile_id:
                profiles[index] = profile
                replaced = True
                break
        if not replaced:
            profiles.append(profile)

        self._settings_service.set(
            "database", "profiles", value=[p.to_dict() for p in profiles]
        )
        self._settings_service.save()
        _logger.info(
            "%s connection profile '%s' (%s).",
            "Updated" if replaced else "Saved",
            profile.name,
            profile.db_type.value,
        )

    def delete_profile(self, profile_id: str) -> None:
        """Remove the saved profile with ``profile_id``, if one exists. A no-op otherwise."""
        profiles = [p for p in self.list_profiles() if p.profile_id != profile_id]
        self._settings_service.set(
            "database", "profiles", value=[p.to_dict() for p in profiles]
        )
        self._settings_service.save()
        self.close_connection(profile_id)

    # -- Live connections (in-memory only, this session) ---------------------------

    def open_connection(
        self, profile: ConnectionProfile, password: str = ""
    ) -> BaseDatabaseConnection:
        """Open (or reopen) a live connection for ``profile`` and track it by ``profile_id``.

        Args:
            profile: Which connection to open.
            password: Held only in the returned connection object and
                this service's in-memory tracking dict — never
                persisted (see this module's own docstring).

        Raises:
            ServiceError: If no connector is registered for
                ``profile.db_type``, or the connection cannot be
                configured (propagated from
                :meth:`~src.database.base_connection.
                BaseDatabaseConnection.connect`).
        """
        self.close_connection(profile.profile_id)

        connector_class = get_connector_class(profile.db_type)
        connection = connector_class(profile, password)
        connection.connect()

        self._live_connections[profile.profile_id] = connection
        _logger.info(
            "Opened connection '%s' (%s).", profile.name, profile.db_type.value
        )
        return connection

    def get_connection(self, profile_id: str) -> BaseDatabaseConnection:
        """Return the currently open connection for ``profile_id``.

        Raises:
            ServiceError: If no connection is currently open for this
                profile — a caller must call :meth:`open_connection`
                first; this method does not implicitly reconnect,
                since doing so without a password on hand cannot
                succeed for any server-based connector.
        """
        connection = self._live_connections.get(profile_id)
        if connection is None:
            raise ServiceError(
                f"No open connection for profile id {profile_id!r}. "
                f"Call open_connection() first."
            )
        return connection

    def close_connection(self, profile_id: str) -> None:
        """Close and forget the live connection for ``profile_id``, if one is open. A no-op otherwise."""
        connection = self._live_connections.pop(profile_id, None)
        if connection is not None:
            connection.close()

    def close_all_connections(self) -> None:
        """Close every currently open connection — used on application shutdown."""
        for profile_id in list(self._live_connections):
            self.close_connection(profile_id)
