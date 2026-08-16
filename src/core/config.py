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

from src.core.constants import (
    AVAILABLE_THEMES,
    CONFIG_FILE_PATH,
    DEFAULT_LOG_FILE_BACKUP_COUNT,
    DEFAULT_LOG_FILE_MAX_BYTES,
    DEFAULT_LOG_LEVEL,
    DEFAULT_THEME,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
)
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
            # Milestone 7: a list of provider profiles rather than one
            # provider/api_key_env_var pair — lets the user configure
            # several Groq keys (or a mix of providers) and have
            # AssistantService fail over between them, and delivers
            # provider-agnostic AI (including local-first Ollama, which
            # needs no api_key_env_var at all) rather than hardcoding a
            # single active provider. Each profile:
            #   name: user-facing label, e.g. "Groq key 1".
            #   provider_type: "anthropic" | "gemini" | "groq" | "ollama".
            #   api_key_env_var: name of the environment variable holding
            #     the key; None for providers that need no key (ollama).
            #   model: provider-specific model override, or None to use
            #     that provider class's own default.
            "providers": [],
            "active_provider_index": 0,
            "rotation_enabled": False,
            # Milestone 8: drives both the AI system prompt's register
            # (see assistant_service._SYSTEM_PROMPT) and, once milestone
            # 10 builds result panels, their density/vocabulary — see
            # src.core.expertise_level.ExpertiseLevel for the full set
            # of valid values. Stored as a plain string (not the enum
            # itself) for the same reason every other config value is a
            # plain string/int/bool: config.yaml is plain YAML.
            "expertise_level": "beginner",
        },
        "plugins": {
            "enabled": True,
            "search_paths": [],
            # Milestone 12: names the user has chosen to disable via
            # the Plugins settings panel — plain plugin-manifest
            # names, not paths, so a plugin stays disabled even if its
            # directory moves within a search path.
            "disabled_plugin_names": [],
        },
        "forecasting": {
            "default_horizon_periods": 30,
        },
        "reports": {
            "default_export_format": "pdf",
        },
        "database": {
            # Milestone 14: saved "Connect to Database" profiles.
            # Deliberately metadata-only — name/db_type/host/port/
            # database/username. No password field exists anywhere in
            # this list on purpose: a password typed into the "Connect
            # to Database" dialog lives only in
            # DatabaseConnectionService's in-memory session state (see
            # that module's own docstring for the full reasoning) and
            # is never written to this plain-text config file.
            "profiles": [],
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
    "database": dict,
}

_NESTED_SCHEMA: dict[str, dict[str, type]] = {
    "window": {"width": int, "height": int},
    "autosave": {"enabled": bool, "interval_minutes": int},
    "logging": {"level": str, "max_bytes": int, "backup_count": int},
    "ai": {
        "enabled": bool,
        "providers": list,
        "active_provider_index": int,
        "rotation_enabled": bool,
        "expertise_level": str,
    },
    "plugins": {
        "enabled": bool,
        "search_paths": list,
        "disabled_plugin_names": list,
    },
    "forecasting": {"default_horizon_periods": int},
    "reports": {"default_export_format": str},
    "database": {"profiles": list},
}


def _migrate_legacy_ai_section(data: dict[str, Any]) -> None:
    """Rewrite a pre-milestone-7 ``ai`` section into the current provider-list shape, in place.

    Before milestone 7, ``ai`` held a single ``provider``/
    ``api_key_env_var`` pair instead of a ``providers`` list. Without
    this step, any ``config.yaml`` written before this milestone would
    fail :func:`validate_config_structure` on the very next startup —
    breaking this module's own documented self-healing promise ("a
    missing *or invalid* config is repaired, not fatal"). Detected by
    the absence of the ``providers`` key rather than a version number,
    since no config schema version field exists in this project; if
    that changes later, prefer switching this check to it.

    Does nothing if ``data["ai"]`` is missing entirely or already has
    the current shape — safe to call unconditionally from
    :func:`load_config` before validation runs.
    """
    ai_section = data.get("ai")
    if not isinstance(ai_section, dict):
        return  # missing/malformed entirely; validation will catch it

    if "providers" not in ai_section:
        legacy_provider = ai_section.get("provider")
        legacy_api_key_env_var = ai_section.get("api_key_env_var")
        providers = (
            [
                {
                    "name": f"{legacy_provider} (migrated)",
                    "provider_type": legacy_provider,
                    "api_key_env_var": legacy_api_key_env_var,
                    "model": None,
                }
            ]
            if legacy_provider
            else []
        )
        data["ai"] = {
            "enabled": ai_section.get("enabled", False),
            "providers": providers,
            "active_provider_index": 0,
            "rotation_enabled": False,
            "expertise_level": "beginner",
        }
        _bootstrap_logger.warning(
            "config.yaml's 'ai' section used the pre-milestone-7 single-provider "
            "shape — migrated it to the new provider-list shape in memory. Save "
            "settings once (e.g. via the Settings dialog) to persist this change."
        )
        return

    # Separately: a config.yaml saved between milestones 7 and 8 has the
    # current providers-list shape but predates 'expertise_level' —
    # back-fill just that one key rather than routing through the
    # legacy-migration branch above, which would incorrectly discard an
    # already-current providers list.
    if "expertise_level" not in ai_section:
        ai_section["expertise_level"] = "beginner"
        _bootstrap_logger.warning(
            "config.yaml's 'ai' section predates milestone 8's "
            "'expertise_level' key — defaulted it to 'beginner' in memory. "
            "Save settings once to persist this change."
        )


def _migrate_legacy_plugins_section(data: dict[str, Any]) -> None:
    """Back-fill milestone 12's ``disabled_plugin_names`` key into an older ``plugins`` section, in place.

    Same reasoning and shape as
    :func:`_migrate_legacy_ai_section`'s ``expertise_level`` back-fill:
    a ``config.yaml`` saved before this milestone has ``plugins.enabled``
    and ``plugins.search_paths`` (both existed since milestone 1)
    but predates ``disabled_plugin_names`` — without this, such a file
    would fail :func:`validate_config_structure` on the very next
    startup, breaking this module's self-healing promise.
    """
    plugins_section = data.get("plugins")
    if not isinstance(plugins_section, dict):
        return  # missing/malformed entirely; validation will catch it

    if "disabled_plugin_names" not in plugins_section:
        plugins_section["disabled_plugin_names"] = []
        _bootstrap_logger.warning(
            "config.yaml's 'plugins' section predates milestone 12's "
            "'disabled_plugin_names' key — defaulted it to an empty list "
            "in memory. Save settings once to persist this change."
        )


def _migrate_legacy_database_section(data: dict[str, Any]) -> None:
    """Back-fill milestone 14's ``database`` section into a config saved before it existed, in place.

    Unlike :func:`_migrate_legacy_ai_section`/
    :func:`_migrate_legacy_plugins_section` (which back-fill one key
    within an already-present section), a ``config.yaml`` saved before
    this milestone has no ``database`` key at all — this adds the whole
    section, empty, so :func:`validate_config_structure` does not fail
    on the very next startup for a user upgrading from an older
    version.
    """
    if "database" not in data or not isinstance(data.get("database"), dict):
        data["database"] = {"profiles": []}
        _bootstrap_logger.warning(
            "config.yaml predates milestone 14's 'database' section — "
            "added an empty one in memory. Save settings once to "
            "persist this change."
        )
    elif "profiles" not in data["database"]:
        data["database"]["profiles"] = []


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
                    f"config.yaml key '{parent_key}.{nested_key}' is missing."
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
            yaml.safe_dump(
                default_data, handle, default_flow_style=False, sort_keys=False
            )
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

    _migrate_legacy_ai_section(loaded)
    _migrate_legacy_plugins_section(loaded)
    _migrate_legacy_database_section(loaded)
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
    ai_providers: list[dict[str, Any]]
    ai_active_provider_index: int
    ai_rotation_enabled: bool
    ai_expertise_level: str
    plugins_enabled: bool
    plugin_search_paths: list[str]
    plugin_disabled_names: list[str]
    forecasting_default_horizon_periods: int
    reports_default_export_format: str
    database_profiles: list[dict[str, Any]]

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
            ai_providers=list(data["ai"]["providers"]),
            ai_active_provider_index=data["ai"]["active_provider_index"],
            ai_rotation_enabled=data["ai"]["rotation_enabled"],
            ai_expertise_level=data["ai"]["expertise_level"],
            plugins_enabled=data["plugins"]["enabled"],
            plugin_search_paths=list(data["plugins"]["search_paths"]),
            plugin_disabled_names=list(data["plugins"]["disabled_plugin_names"]),
            forecasting_default_horizon_periods=data["forecasting"][
                "default_horizon_periods"
            ],
            reports_default_export_format=data["reports"]["default_export_format"],
            database_profiles=list(data["database"]["profiles"]),
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
