# File: src/services/project_service.py
"""Project lifecycle: create, open, save, autosave, and recent-projects tracking.

A "project" in this application is a single ``.json`` file on disk
describing one working session: its name, where it lives, when it was
last saved, and — as of milestone 3b — which source-file-backed
datasets were loaded, so they can be reloaded automatically on open.

:class:`ProjectService` does not depend on
:class:`~src.services.workspace_service.WorkspaceService` — the two
remain independently registered container singletons, per
:mod:`src.core.bootstrap`'s established pattern. Rather than either
service reaching into the other, :meth:`ProjectService.save_project`
and :meth:`ProjectService.open_project` accept dataset references as
explicit parameters; :mod:`src.ui.main_window` (which already holds
references to both services) is responsible for passing the current
dataset list through. This keeps each service's dependencies exactly
as narrow as :mod:`src.core.bootstrap`'s original registration order
already established.

:class:`ProjectService` is the single place that knows how a project
is serialized to and from disk, how "recent projects" is tracked and
capped, and how autosave timing is decided. UI code (built in 1b-ii)
should call into this service rather than reading or writing project
files directly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

PROJECT_FILE_EXTENSION = ".uads.json"
_MAX_RECENT_PROJECTS = 10


@dataclass
class Project:
    """A single working session, serializable to and from disk.

    Attributes:
        name: Display name for the project. Does not need to match
            the filename.
        path: Location of this project's file on disk. ``None`` for a
            newly created, not-yet-saved project — see
            :meth:`ProjectService.new_project`.
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
                by the caller (see :meth:`ProjectService.open_project`)
                rather than read from ``data`` itself, since ``path``
                is deliberately not part of the serialized form.

        Raises:
            ServiceError: If ``data`` is missing the required ``name``
                key or has the wrong shape for any field.
        """
        if "name" not in data:
            raise ServiceError(
                f"Project file at {path} is missing the required "
                f"'name' field."
            )
        if not isinstance(data.get("contents", {}), dict):
            raise ServiceError(
                f"Project file at {path} has a 'contents' field that "
                f"is not a mapping."
            )
        return cls(
            name=data["name"],
            path=path,
            contents=data.get("contents", {}),
            last_saved_at=data.get("last_saved_at"),
        )


class ProjectService:
    """Creates, opens, saves, and tracks recent projects.

    Args:
        recent_projects: Initial list of recent project paths (as
            strings), typically sourced from
            :class:`~src.core.config.AppConfig`'s
            ``recent_projects`` field at construction time. This
            service owns the in-memory list from that point forward;
            it does not re-read config on every access. Persisting an
            updated recent-projects list back to disk is
            :class:`SettingsService`'s job (see
            :mod:`src.services.settings_service`), not this service's
            — ``ProjectService`` reports the current list via
            :meth:`get_recent_projects`, and the caller (UI code, in
            1b-ii) is responsible for handing that list to
            ``SettingsService`` to persist, keeping "what the recent
            list currently is" and "how it gets written to
            config.yaml" as separate responsibilities.
    """

    def __init__(self, recent_projects: list[str] | None = None) -> None:
        self._recent_projects: list[str] = list(recent_projects or [])
        self._active_project: Project | None = None

    def new_project(self, name: str) -> Project:
        """Create a new, unsaved :class:`Project`.

        The returned project has ``path=None`` — it does not exist on
        disk until :meth:`save_project` is called with a destination
        path.

        Args:
            name: Display name for the new project.
        """
        project = Project(name=name)
        self._active_project = project
        _logger.info("Created new project: %s", name)
        return project

    def open_project(self, path: Path) -> Project:
        """Load a project from ``path`` and mark it as active.

        Args:
            path: Location of a ``.uads.json`` project file.

        Raises:
            ServiceError: If the file does not exist, cannot be
                parsed as JSON, or does not match the expected project
                structure.
        """
        if not path.exists():
            raise ServiceError(f"Project file does not exist: {path}")

        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ServiceError(f"Project file at {path} is not valid JSON: {exc}") from exc
        except OSError as exc:
            raise ServiceError(f"Failed to read project file at {path}: {exc}") from exc

        project = Project.from_json_dict(data, path)
        self._active_project = project
        self._add_to_recent(path)
        _logger.info("Opened project: %s (%s)", project.name, path)
        return project

    def save_project(self, project: Project, path: Path | None = None) -> Project:
        """Save ``project`` to disk, returning the saved (updated) project.

        Args:
            project: The project to save. Its ``path`` is used as the
                destination if ``path`` is not supplied.
            path: Destination to save to. Required if
                ``project.path`` is ``None`` (i.e. this project has
                never been saved before — a "Save As" rather than a
                plain "Save"). If supplied, this also becomes the
                project's new ``path`` going forward, matching normal
                "Save As" semantics.

        Raises:
            ServiceError: If neither ``path`` nor ``project.path`` is
                available, or if writing to disk fails.

        Returns:
            The same :class:`Project` instance, mutated in place with
            its resolved ``path`` and updated ``last_saved_at``
            timestamp — returned for convenience so callers can chain
            without needing to separately track that this call
            mutates its argument.
        """
        destination = path or project.path
        if destination is None:
            raise ServiceError(
                "Cannot save a project with no destination path. "
                "Supply a path (Save As) or save a project that was "
                "opened from disk (plain Save)."
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        project.last_saved_at = time.time()
        project.path = destination

        try:
            with destination.open("w", encoding="utf-8") as handle:
                json.dump(project.to_json_dict(), handle, indent=2)
        except OSError as exc:
            raise ServiceError(f"Failed to write project file to {destination}: {exc}") from exc

        self._add_to_recent(destination)
        _logger.info("Saved project: %s (%s)", project.name, destination)
        return project

    def get_active_project(self) -> Project | None:
        """Return the currently active project, or ``None`` if none is set.

        Distinct from raising an exception (as
        :class:`~src.core.application_state.ApplicationState`'s
        ``active_project`` property does) because callers of this
        service — typically UI code checking "is anything open right
        now, to decide whether to enable the Save menu item" — want a
        cheap presence check, not exception-driven control flow for
        what is a completely normal state (no project open yet).
        """
        return self._active_project

    def record_datasets(self, project: Project, datasets: list) -> list[str]:
        """Record which source-file-backed datasets belong to ``project``.

        Writes into ``project.contents["datasets"]`` — a list of
        ``{"name": ..., "source_path": ...}`` records — rather than
        adding a typed field to :class:`Project` itself, matching that
        class's existing "open-ended contents dict" design. Does not
        itself call :meth:`save_project`; callers (typically
        :mod:`src.ui.main_window`) call this to update
        ``project.contents`` and then call :meth:`save_project`
        separately, keeping "what belongs in the project" and "write
        it to disk" as two distinct steps.

        Args:
            project: The project to record datasets into. Mutated in
                place (its ``contents`` dict is updated), matching
                :meth:`save_project`'s own in-place-mutation
                convention.
            datasets: The datasets to record — typically
                :meth:`~src.services.workspace_service.WorkspaceService.
                list_datasets`'s return value. Typed as a plain
                ``list`` rather than ``list[Dataset]`` for the same
                reason :meth:`~src.ui.dock_manager.DockManager.
                refresh_dataset_list` avoids importing
                ``src.services.workspace_service`` for a type hint
                alone — this service has no other dependency on that
                module and importing it here would create exactly the
                kind of cross-service coupling this module's docstring
                explains was deliberately avoided.

        Returns:
            The names of datasets that were skipped because they have
            no ``source_path`` (derived datasets — see milestone 3a's
            ``Dataset.parent_dataset_id`` — are not yet persistable;
            only their source-file-backed ancestors are, per that
            milestone's documented scope). Returned rather than
            silently dropped so a caller can inform the user, if it
            chooses to.
        """
        records = []
        skipped_names = []
        for dataset in datasets:
            if dataset.source_path is None:
                skipped_names.append(dataset.name)
                continue
            records.append(
                {"name": dataset.name, "source_path": str(dataset.source_path)}
            )

        project.contents["datasets"] = records
        _logger.info(
            "Recorded %d dataset(s) into project '%s' (%d skipped, no source path).",
            len(records),
            project.name,
            len(skipped_names),
        )
        return skipped_names

    def get_recorded_dataset_paths(self, project: Project) -> list[tuple[str, Path]]:
        """Return ``(name, source_path)`` pairs recorded in ``project``.

        Reads back what :meth:`record_datasets` wrote. Returns an
        empty list if ``project.contents`` has no ``"datasets"`` key
        at all — a project saved before milestone 3b, or one that had
        no source-file-backed datasets to record, both look identical
        from this method's point of view, and both correctly produce
        "nothing to reload" rather than an error.

        The caller (:mod:`src.ui.main_window`) is responsible for
        actually re-reading each path through
        :func:`~src.readers.reader_registry.get_reader_for_path` and
        registering the result with
        :class:`~src.services.workspace_service.WorkspaceService` —
        this service only reports what was recorded, since actually
        reading files is the readers package's job, not this one's.
        """
        raw_records = project.contents.get("datasets", [])
        return [(record["name"], Path(record["source_path"])) for record in raw_records]

    def get_recent_projects(self) -> list[str]:
        """Return the current recent-projects list, most recent first."""
        return list(self._recent_projects)

    def _add_to_recent(self, path: Path) -> None:
        """Move ``path`` to the front of the recent-projects list.

        If ``path`` is already present, it is moved rather than
        duplicated. The list is capped at
        :data:`_MAX_RECENT_PROJECTS`, dropping the oldest entry once
        the cap is exceeded.
        """
        path_str = str(path)
        if path_str in self._recent_projects:
            self._recent_projects.remove(path_str)
        self._recent_projects.insert(0, path_str)
        if len(self._recent_projects) > _MAX_RECENT_PROJECTS:
            self._recent_projects = self._recent_projects[:_MAX_RECENT_PROJECTS]
