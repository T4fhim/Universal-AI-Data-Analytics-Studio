# File: src/plugins/plugin_manifest.py
"""The on-disk plugin manifest format and its loading.

A plugin is a directory containing a ``plugin.json`` manifest plus an
importable Python package of the same name, laid out as:

.. code-block:: text

    <search_path>/
        my_plugin/
            plugin.json
            __init__.py
            readers.py

``plugin.json``::

    {
        "name": "my_plugin",
        "version": "1.0.0",
        "description": "Adds a reader for ExampleCorp's proprietary format.",
        "provides": {
            "readers": ["my_plugin.readers:ExampleCorpReader"]
        }
    }

Each entry under ``provides`` is a category name (see
:data:`SUPPORTED_CATEGORIES`) mapping to a list of ``module.path:ClassName``
strings — :class:`~src.plugins.plugin_loader.PluginLoader` imports each
one and validates it against the category's ``Base*`` ABC before
registering it.

JSON rather than YAML (unlike ``config.yaml`` elsewhere in this
project) because a plugin manifest is a small, machine-authored,
rarely hand-edited file shipped alongside plugin code — the same
reasoning this project's own project files (``*.uads.json``) already
use JSON for, whereas ``config.yaml`` is deliberately YAML because a
user is expected to hand-edit it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.core.exceptions import ServiceError

# Milestone 12 supports these three categories — each has a real
# Base* ABC already established (BaseReader, BaseOperation, BaseChart)
# to validate a plugin-provided class against. "forecast_models" and
# "ai_providers" from the milestone plan's own text are deliberately
# not included yet: forecasting is a set of plain functions with no
# Base* shape at all (see src.forecasting's own modules), and
# BaseLLMProvider is this project's one stateful exception to the
# stateless-classmethod Base* pattern, whose provider_rotation.py
# wiring would need its own dedicated design rather than reusing this
# generic loader unchanged. Both are tracked as a known gap, not
# silently dropped.
SUPPORTED_CATEGORIES = ("readers", "cleaning_operations", "charts")


@dataclass(frozen=True)
class PluginManifest:
    """A validated ``plugin.json``.

    Attributes:
        name: The plugin's identifier — also its package directory
            name, so ``provides`` entries' module paths are expected to
            start with this name.
        version: Free-form version string (not parsed or compared —
            this project has no plugin update/compatibility mechanism
            yet, so a version field is recorded for display purposes
            only at this milestone).
        description: Human-readable summary, shown in the Plugins
            settings panel.
        provides: Category name -> list of ``module.path:ClassName``
            strings.
        manifest_path: Where this manifest was loaded from — kept so
            :class:`~src.plugins.plugin_loader.PluginLoader` can
            resolve ``provides`` entries relative to the manifest's own
            directory without needing that path threaded through
            separately.
    """

    name: str
    version: str
    description: str
    provides: dict[str, list[str]]
    manifest_path: Path

    @classmethod
    def from_dict(cls, data: dict, manifest_path: Path) -> PluginManifest:
        """Build a :class:`PluginManifest` from parsed JSON, validating required fields.

        Args:
            data: The parsed ``plugin.json`` contents.
            manifest_path: Where ``data`` was loaded from — used only
                for :attr:`manifest_path` and for naming the file in
                error messages, never re-read here.

        Raises:
            ServiceError: If ``name`` is missing/empty, ``provides``
                is not a dict, or any category key under ``provides``
                is not in :data:`SUPPORTED_CATEGORIES`.
        """
        name = data.get("name")
        if not name or not isinstance(name, str):
            raise ServiceError(
                f"{manifest_path}: 'name' is required and must be a non-empty string."
            )

        provides = data.get("provides", {})
        if not isinstance(provides, dict):
            raise ServiceError(f"{manifest_path}: 'provides' must be an object.")

        unsupported_categories = set(provides) - set(SUPPORTED_CATEGORIES)
        if unsupported_categories:
            raise ServiceError(
                f"{manifest_path}: unsupported 'provides' categor"
                f"{'y' if len(unsupported_categories) == 1 else 'ies'}: "
                f"{', '.join(sorted(unsupported_categories))}. Supported: "
                f"{', '.join(SUPPORTED_CATEGORIES)}."
            )

        return cls(
            name=name,
            version=str(data.get("version", "0.0.0")),
            description=str(data.get("description", "")),
            provides={k: list(v) for k, v in provides.items()},
            manifest_path=manifest_path,
        )

    @classmethod
    def load(cls, manifest_path: Path) -> PluginManifest:
        """Read and validate ``plugin.json`` at ``manifest_path``.

        Raises:
            ServiceError: If the file cannot be read, is not valid
                JSON, or fails :meth:`from_dict`'s validation.
        """
        try:
            raw_text = manifest_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ServiceError(f"Could not read {manifest_path}: {exc}") from exc

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ServiceError(f"{manifest_path} is not valid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ServiceError(
                f"{manifest_path} must contain a JSON object at the top level."
            )

        return cls.from_dict(data, manifest_path)
