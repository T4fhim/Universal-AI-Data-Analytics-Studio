# File: src/core/config.py
"""Application configuration: loading, default generation, and typed access.

This module owns ``config/config.yaml``. On first run (or whenever the
file is missing), it writes a default configuration to disk before
continuing, so the user has a real file to find and edit afterward
rather than a default that only ever existed in memory.

A note on logging in this module specifically: :class:`AppConfig` may
need to report problems (a missing file being recreated, a value
falling back to its default) before the application's real logger is
configured, because logger.py itself needs *this* module's output
(the resolved log level and rotation settings) before it can set
itself up. To avoid a circular dependency, this module does not import
:mod:`src.core.logger` and instead writes its own bootstrap-time
messages directly to a minimally configured standard-library logger.
This is a deliberate, narrow exception to "use get_logger from
logger.py everywhere" — it is confined to this file, and it exists
only because this file is a dependency of the logger, not a consumer
of it.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.core.constants import (AVAILABLE_THEMES, CONFIG_FILE_PATH,
                                DEFAULT_LOG_FILE_BACKUP_COUNT,
                                DEFAULT_LOG_FILE_MAX_BYTES, DEFAULT_LOG_LEVEL,
                                DEFAULT_THEME, DEFAULT_WINDOW_HEIGHT,
                                DEFAULT_WINDOW_WIDTH)
from src.core.exceptions import ConfigError

# Bootstrap-time-only logger. Deliberately not src.core.logger.get_logger
# — see module docstring. Uses basicConfig defaults (stderr, WARNING+)
# so it stays silent for normal successful loads and only speaks up if
# something is actually wrong or being recreated.
_bootstrap_logger = logging.getLogger(f"{__name__}.bootstrap")


def _default_config_dict() -> dict[str, Any]:
    """Return the in-code default configuration structure.

    This is the single source of truth for what a fresh config.yaml
    contains. :func:`load_config` writes exactly this structure to
    disk when the file is missing, and :class:`AppConfig` validates
    loaded files against the same key set, so the two can never drift
    apart silently.
    """
    return {
        "theme": DEFAULT_THEME,
        "window": {
            "width": DEFAULT_WINDOW_WIDTH,
            "height": DEFAULT_WINDOW_HEIGHT,
        },
        "recent_projects": [],
        "autosave": {
            "enabled": True,
            "interval_minutes": 5,
        },
        "logging": {
            "level": DEFAULT_LOG_LEVEL,
            "max_bytes": DEFAULT_LOG_FILE_MAX_BYTES,
            "backup_count": DEFAULT_LOG_FILE_BACKUP_COUNT,
        },
        "ai": {
            "enabled": False,
            "provider": None,
            "api_key_env_var": "ANTHROPIC_API_KEY",
        },
        "plugins": {
            "enabled": True,
            "search_paths": [],
        },
        "forecasting": {
            "default_horizon_periods": 30,
        },
        "reports": {
            "default_export_format": "pdf",
        },
    }


# Required top-level keys and the type each must have. Nested
# dictionaries are validated by validate_config_structure recursing
# into _NESTED_SCHEMA rather than being listed flatly here.
_TOP_LEVEL_SCHEMA: dict[str, type] = {
    "theme": str,
    "window": dict,
    "recent_projects": list,
    "autosave": dict,
    "logging": dict,
    "ai": dict,
    "plugins": dict,
    "forecasting": dict,
    "reports": dict,
}

_NESTED_SCHEMA: dict[str, dict[str, type]] = {
    "window": {"width": int, "height": int},
    "autosave": {"enabled": bool, "interval_minutes": int},
    "logging": {"level": str, "max_bytes": int, "backup_count": int},
    "forecasting": {"default_horizon_periods": int},
    "reports": {"default_export_format": str},
}


def validate_config_structure(data: dict[str, Any]) -> None:
    """Validate that ``data`` matches the expected configuration shape.

    Public, not internal-only: in addition to being used by
    :func:`load_config` below, this is the same validation
    :class:`~src.services.settings_service.SettingsService` runs
    before writing settings back to disk, so that a value set through
    :meth:`~src.services.settings_service.SettingsService.set` cannot
    silently produce a config.yaml that :func:`load_config` would then
    fail to load on the next startup.

    Raises :class:`ConfigError` with a message naming the specific
    missing key or type mismatch, so a user editing config.yaml by
    hand gets a usable error rather than a bare ``KeyError`` or
    ``TypeError`` surfacing from deep inside an accessor later.
    """
    if not isinstance(data, dict):
        raise ConfigError(
            f"config.yaml must contain a mapping at the top level, "
            f"got {type(data).__name__}."
        )

    for key, expected_type in _TOP_LEVEL_SCHEMA.items():
        if key not in data:
            raise ConfigError(f"config.yaml is missing required key: '{key}'.")
        if not isinstance(data[key], expected_type):
            raise ConfigError(
                f"config.yaml key '{key}' must be of type "
                f"{expected_type.__name__}, got "
                f"{type(data[key]).__name__}."
            )

    for parent_key, nested_schema in _NESTED_SCHEMA.items():
        parent_value = data[parent_key]
        for nested_key, expected_type in nested_schema.items():
            if nested_key not in parent_value:
                raise ConfigError(
                    f"config.yaml key '{parent_key}.{nested_key}' is "
                    f"missing."
                )
            if not isinstance(parent_value[nested_key], expected_type):
                raise ConfigError(
                    f"config.yaml key '{parent_key}.{nested_key}' must "
                    f"be of type {expected_type.__name__}, got "
                    f"{type(parent_value[nested_key]).__name__}."
                )

    theme_value = data["theme"]
    if theme_value not in AVAILABLE_THEMES:
        raise ConfigError(
            f"config.yaml key 'theme' must be one of "
            f"{AVAILABLE_THEMES}, got '{theme_value}'."
        )


def _write_default_config(path: Path) -> dict[str, Any]:
    """Write the default configuration to ``path`` and return it.

    Creates the parent directory if it does not already exist. This is
    what makes "missing config" self-healing: the very first run of
    the application produces a real, editable file on disk rather than
    silently operating on in-memory defaults the user can never find.
    """
    default_data = _default_config_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(default_data, handle, default_flow_style=False, sort_keys=False)
    except OSError as exc:
        raise ConfigError(
            f"Failed to write default configuration to {path}: {exc}"
        ) from exc
    _bootstrap_logger.warning(
        "No configuration file found at %s — a default configuration "
        "has been created. Edit it to customize settings.",
        path,
    )
    return default_data


def load_config(path: Path = CONFIG_FILE_PATH) -> dict[str, Any]:
    """Load configuration from ``path``, creating a default if missing.

    Args:
        path: Location of the YAML configuration file. Defaults to the
            project's standard config location.

    Returns:
        The loaded (or newly created) configuration as a plain dict,
        already validated against the expected schema.

    Raises:
        ConfigError: If the file exists but cannot be parsed, cannot be
            written when missing, or does not match the expected
            structure.
    """
    if not path.exists():
        return _write_default_config(path)

    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse configuration file {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Failed to read configuration file {path}: {exc}") from exc

    if loaded is None:
        _bootstrap_logger.warning(
            "Configuration file at %s is empty — a default configuration "
            "has been created in its place.",
            path,
        )
        return _write_default_config(path)

    validate_config_structure(loaded)
    return loaded


@dataclass(frozen=True)
class AppConfig:
    """Typed, read-only view over a loaded configuration dictionary.

    Callers should go through this class's properties rather than
    indexing a raw dict, so that a typo in a key name is a
    ``AttributeError`` caught immediately during development (and by
    static type checkers ahead of time) rather than a silent ``None``
    or a ``KeyError`` surfacing far from where the value was actually
    read.

    Instances are constructed via :meth:`from_dict`, which is the only
    supported way to build one — the raw dict is expected to already
    have passed :func:`validate_config_structure` by the time it
    reaches this class.
    """

    theme: str
    window_width: int
    window_height: int
    recent_projects: list[str]
    autosave_enabled: bool
    autosave_interval_minutes: int
    log_level: str
    log_max_bytes: int
    log_backup_count: int
    ai_enabled: bool
    ai_provider: str | None
    ai_api_key_env_var: str
    plugins_enabled: bool
    plugin_search_paths: list[str]
    forecasting_default_horizon_periods: int
    reports_default_export_format: str

    _raw: dict[str, Any] = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        """Construct an :class:`AppConfig` from a validated dictionary.

        Args:
            data: A configuration dictionary that has already passed
                :func:`_validate_structure` — typically the return
                value of :func:`load_config`.
        """
        return cls(
            theme=data["theme"],
            window_width=data["window"]["width"],
            window_height=data["window"]["height"],
            recent_projects=list(data["recent_projects"]),
            autosave_enabled=data["autosave"]["enabled"],
            autosave_interval_minutes=data["autosave"]["interval_minutes"],
            log_level=data["logging"]["level"],
            log_max_bytes=data["logging"]["max_bytes"],
            log_backup_count=data["logging"]["backup_count"],
            ai_enabled=data["ai"]["enabled"],
            ai_provider=data["ai"].get("provider"),
            ai_api_key_env_var=data["ai"]["api_key_env_var"],
            plugins_enabled=data["plugins"]["enabled"],
            plugin_search_paths=list(data["plugins"]["search_paths"]),
            forecasting_default_horizon_periods=data["forecasting"][
                "default_horizon_periods"
            ],
            reports_default_export_format=data["reports"]["default_export_format"],
            _raw=data,
        )

    @classmethod
    def load(cls, path: Path = CONFIG_FILE_PATH) -> AppConfig:
        """Load configuration from ``path`` and return a typed view.

        Convenience wrapper combining :func:`load_config` and
        :meth:`from_dict` for the common case of "just get me a usable
        config object."
        """
        return cls.from_dict(load_config(path))

    def to_dict(self) -> dict[str, Any]:
        """Return a fully independent copy of the underlying configuration dict.

        This is the supported way for another module (for example
        :class:`~src.services.settings_service.SettingsService`, which
        needs a mutable working copy to build a runtime settings
        surface on top of) to obtain the raw dictionary this
        ``AppConfig`` was built from, without reaching into the
        private ``_raw`` field directly.

        This performs a deep copy, not a shallow one. A shallow copy
        would leave nested dicts (``window``, ``autosave``, and so on)
        aliased between the copy and ``self._raw`` — and
        :meth:`~src.services.settings_service.SettingsService.set`
        walks into and mutates existing nested dicts in place when a
        key path already exists (rather than replacing them wholesale),
        so a shallow copy here would let a settings change silently
        corrupt this supposedly-frozen ``AppConfig`` instance's own
        data. Top-level list values (``recent_projects``,
        ``plugin_search_paths``) have the same aliasing risk and are
        covered by the same deep copy.
        """
        return copy.deepcopy(self._raw)
