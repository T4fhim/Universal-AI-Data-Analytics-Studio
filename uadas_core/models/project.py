# File: uadas_core/models/project.py
"""The Qt-free, service-free value type a saved project session is built from.

Extracted from :mod:`uadas_core.services.project_service` in the desktop->web
transition's Phase 2.2 (D1) -- :class:`Project` carries no service-layer
behaviour (``to_json_dict``/``from_json_dict`` are the value type's own
serialization *shape*, not I/O -- actually reading/writing the file is
:class:`~uadas_core.services.project_service.ProjectService`'s job) and no
Qt dependency, so nothing about it requires living next to that service.
This is also what lets :mod:`uadas_core.core.application_state` type-hint
``Project`` without importing the services layer (see Phase 2.3's
``layers`` contract -- :mod:`uadas_core.core` must sit at the bottom of the
stack).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from uadas_core.core.exceptions import ServiceError


@dataclass
class Project:
    """A single working session, serializable to and from disk.

    Attributes:
        name: Display name for the project. Does not need to match
            the filename.
        path: Location of this project's file on disk. ``None`` for a
            newly created, not-yet-saved project — see
            :meth:`~uadas_core.services.project_service.ProjectService.new_project`.
        contents: Open-ended project data. This milestone does not
            define what goes in here beyond the empty dict a new
            project starts with; later milestones (dataset tracking,
            visualization tracking) will read and write specific keys
            of this dict rather than this class growing a typed field
            per feature.
        last_saved_at: Unix timestamp of the last successful save, or
            ``None`` if never saved.
    """

    name: str
    path: Path | None = None
    contents: dict[str, Any] = field(default_factory=dict)
    last_saved_at: float | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of this project.

        ``path`` is intentionally excluded: a project's file location
        is where it lives, not data it contains about itself, and
        serializing it would let a copied or moved project file
        silently disagree with its own actual location on disk.
        """
        return {
            "name": self.name,
            "contents": self.contents,
            "last_saved_at": self.last_saved_at,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any], path: Path) -> Project:
        """Reconstruct a :class:`Project` from a loaded JSON dict.

        Args:
            data: The parsed JSON contents of a project file.
            path: The file path this data was loaded from — supplied
                by the caller (see
                :meth:`~uadas_core.services.project_service.ProjectService.open_project`)
                rather than read from ``data`` itself, since ``path``
                is deliberately not part of the serialized form.

        Raises:
            ServiceError: If ``data`` is missing the required ``name``
                key or has the wrong shape for any field.
        """
        if "name" not in data:
            raise ServiceError(
                f"Project file at {path} is missing the required 'name' field."
            )
        if not isinstance(data.get("contents", {}), dict):
            raise ServiceError(
                f"Project file at {path} has a 'contents' field that is not a mapping."
            )
        return cls(
            name=data["name"],
            path=path,
            contents=data.get("contents", {}),
            last_saved_at=data.get("last_saved_at"),
        )
