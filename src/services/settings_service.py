# File: src/services/settings_service.py
"""Runtime settings access and persistence, distinct from startup config loading.

:class:`~src.core.config.AppConfig` (built in milestone 1a) is a
frozen, typed snapshot of ``config.yaml`` as it existed at bootstrap
time — it has no write path, by design, since its job is to hand
startup a validated, immutable view of configuration. This module is
the complementary piece: a mutable, in-session settings surface that
UI code (menus, a settings dialog) reads from and writes to, which
this service then persists back to ``config.yaml`` on demand.

The relationship: ``AppConfig`` is what config *was* when the
application started. ``SettingsService`` is what config *is* right
now, in this running session, and knows how to save that back to disk.
Two frozen ``AppConfig`` snapshots loaded before and after a
``SettingsService.save()`` call would differ; that is the intended
behavior, not a bug — it's exactly how "the user changed a setting and
it persisted" is supposed to look from the outside.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.core.config import AppConfig, load_config, validate_config_structure
from src.core.constants import CONFIG_FILE_PATH
from src.core.exceptions import ConfigError, ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)


class SettingsService:
    """Mutable, session-scoped settings, backed by ``config.yaml``.

    Args:
        initial_config: The :class:`~src.core.config.AppConfig`
            snapshot loaded at bootstrap. This service copies the
            underlying raw dictionary out of it as its own mutable
            working copy — it does not mutate the ``AppConfig``
            instance itself, since that instance is frozen by design
            and other parts of the application may be holding a
            reference to it and expecting it to stay exactly as it
            was at load time.
        config_path: Location ``config.yaml`` should be written to and
            reloaded from. Defaults to the project's standard config
            location; overridable primarily for tests.
    """

    def __init__(
        self,
        initial_config: AppConfig,
        config_path: Path = CONFIG_FILE_PATH,
    ) -> None:
        self._config_path = config_path
        # to_dict() returns a fully independent (deep-copied) working
        # copy — see AppConfig.to_dict()'s docstring for why a shallow
        # copy would be unsafe given how set() below mutates nested
        # dicts in place.
        self._data: dict[str, Any] = initial_config.to_dict()

    def get(self, *key_path: str, default: Any = None) -> Any:
        """Return a nested settings value.

        Args:
            *key_path: One or more keys describing the path to the
                value, e.g. ``get("window", "width")`` for
                ``data["window"]["width"]``.
            default: Value to return if the path does not exist.

        Example:
            >>> service.get("autosave", "interval_minutes")
            5
        """
        current: Any = self._data
        for key in key_path:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def set(self, *key_path: str, value: Any) -> None:
        """Set a nested settings value, creating intermediate dicts as needed.

        Args:
            *key_path: One or more keys describing the path to set,
                e.g. ``set("window", "width", value=1920)``.
            value: The value to store.

        Raises:
            ServiceError: If ``key_path`` is empty, or if a
                non-terminal segment of the path already holds a
                non-dict value (which would mean silently overwriting
                an existing scalar setting with a nested structure).
        """
        if not key_path:
            raise ServiceError("set() requires at least one key.")

        current = self._data
        for key in key_path[:-1]:
            if key not in current:
                current[key] = {}
            elif not isinstance(current[key], dict):
                raise ServiceError(
                    f"Cannot set nested value at {'.'.join(key_path)}: "
                    f"'{key}' already holds a non-dict value "
                    f"({current[key]!r})."
                )
            current = current[key]

        current[key_path[-1]] = value
        _logger.debug("Setting updated: %s = %r", ".".join(key_path), value)

    def save(self) -> None:
        """Validate and write the current in-memory settings to disk.

        Raises:
            ConfigError: If the current in-memory settings no longer
                match the expected configuration structure (for
                example, if :meth:`set` was used to write a value of
                the wrong type) — this prevents a mistake made through
                :meth:`set` from being written to disk as a config
                file :func:`~src.core.config.load_config` would then
                fail to load on the next startup.
            ServiceError: If writing to disk fails for any other
                reason.
        """
        validate_config_structure(self._data)

        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with self._config_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    self._data, handle, default_flow_style=False, sort_keys=False
                )
        except OSError as exc:
            raise ServiceError(
                f"Failed to write settings to {self._config_path}: {exc}"
            ) from exc

        _logger.info("Settings saved to %s.", self._config_path)

    def reload(self) -> None:
        """Discard in-memory changes and reload settings from disk.

        Useful for a settings dialog's "Cancel" action: any values
        changed via :meth:`set` since the last :meth:`save` (or since
        construction) are discarded, and the in-memory state is
        replaced with whatever is currently on disk.

        Raises:
            ConfigError: If the on-disk file cannot be loaded — see
                :func:`~src.core.config.load_config`.
        """
        self._data = load_config(self._config_path)
        _logger.info("Settings reloaded from %s.", self._config_path)
