# File: apps/api/uadas_api/storage/manifest.py
"""The manifest a ``WorkspaceHead`` commits: which immutable objects make up one saved workspace.

Why a typed, strictly validated structure: the manifest lives in a JSON column, i.e. in a
place a bug (or a database editor) can fill with anything, and it is what decides *which
objects the server fetches and trusts*. So it is parsed, never indexed blindly: every key
must pass the organization's key check (a manifest naming another tenant's object is
refused), every hash must be 64 hex characters, every dataset id a canonical UUID.
``keys_of`` is the tolerant counterpart used by the lifecycle code, which must be able to say
"what does this head still reference?" even for a head it will not load.

Shape (``format`` 1)::

    {"format": 1, "token": "g0000003-1a2b3c4d5e6f",
     "workspace_db": {"key": ..., "sha256": ..., "size": N},
     "datasets": {"<dataset uuid>": {"key": ..., "sha256": ..., "size": N,
                                      "name": ..., "rows": N, "columns": N}}}

Every ``key`` is immutable once written (see :mod:`uadas_api.storage.keys`); the sizes and
hashes are what a loader verifies each object against *independently* of the object's own
metadata.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from uadas_api.storage import keys as _keys
from uadas_api.storage.errors import InvalidKeyError, ManifestError
from uadas_api.tenancy import OrganizationRef

FORMAT = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class ObjectRef:
    """One immutable stored object: where it is and what it must hash to."""

    key: str
    sha256: str
    size: int


@dataclass(frozen=True)
class DatasetEntry(ObjectRef):
    """A dataset's frame plus the facts a listing needs without fetching the frame."""

    name: str = ""
    rows: int = 0
    columns: int = 0


@dataclass(frozen=True)
class Manifest:
    """A validated manifest."""

    token: str
    workspace_db: ObjectRef
    datasets: Mapping[str, DatasetEntry]

    def keys(self) -> set[str]:
        """Every object this manifest references."""
        return {self.workspace_db.key, *(entry.key for entry in self.datasets.values())}

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "token": self.token,
            "workspace_db": _ref_json(self.workspace_db),
            "datasets": {
                dataset_id: {
                    **_ref_json(entry),
                    "name": entry.name,
                    "rows": entry.rows,
                    "columns": entry.columns,
                }
                for dataset_id, entry in sorted(self.datasets.items())
            },
        }

    @classmethod
    def from_json(
        cls, raw: object, organization: OrganizationRef, project_id: Any = None
    ) -> Manifest:
        """Parse and validate ``raw`` for ``organization`` (and ``project_id``); raise :class:`ManifestError`.

        With a ``project_id`` every key is also bound to its namespace: the database must lie
        under ``<org>/projects/<project_id>/workspace/`` and each dataset's frame under
        ``<org>/datasets/<that dataset's id>/frames/``. Without that binding an edited manifest
        could name another project's (or dataset's) objects of the same organization and have a
        later save or discard queue them for deletion.
        """
        try:
            return cls._parse(raw, organization, project_id)
        except (InvalidKeyError, KeyError, TypeError, ValueError) as error:
            raise ManifestError("the stored workspace manifest is invalid") from error

    @classmethod
    def _parse(
        cls, raw: object, organization: OrganizationRef, project_id: Any
    ) -> Manifest:
        org = _keys.organization_id(organization)
        db_prefix = (
            f"{org}/projects/{_keys.uuid_text(project_id, 'project id')}/workspace/"
            if project_id is not None
            else None
        )
        if not isinstance(raw, dict) or raw.get("format") != FORMAT:
            raise ValueError("unsupported manifest")
        token = raw["token"]
        if not isinstance(token, str) or not token:
            raise ValueError("token")
        datasets_raw = raw["datasets"]
        if not isinstance(datasets_raw, dict):
            raise ValueError("datasets")
        datasets: dict[str, DatasetEntry] = {}
        for dataset_id, entry in datasets_raw.items():
            canonical = _keys.uuid_text(dataset_id, "dataset id")
            ref = _ref(
                entry,
                organization,
                f"{org}/datasets/{canonical}/frames/" if db_prefix else None,
            )
            datasets[canonical] = DatasetEntry(
                key=ref.key,
                sha256=ref.sha256,
                size=ref.size,
                name=str(entry.get("name", "")),
                rows=_count(entry.get("rows", 0)),
                columns=_count(entry.get("columns", 0)),
            )
        return cls(
            token=token,
            workspace_db=_ref(raw["workspace_db"], organization, db_prefix),
            datasets=datasets,
        )


def _ref_json(ref: ObjectRef) -> dict[str, Any]:
    return {"key": ref.key, "sha256": ref.sha256, "size": ref.size}


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("count")
    return value


def _ref(
    raw: object, organization: OrganizationRef, required_prefix: str | None
) -> ObjectRef:
    if not isinstance(raw, dict):
        raise ValueError("object reference")
    sha256 = raw["sha256"]
    if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
        raise ValueError("sha256")
    key = _keys.check_key(organization, raw["key"])
    if required_prefix is not None and not key.startswith(required_prefix):
        raise ValueError("object outside its namespace")
    return ObjectRef(
        key=key,
        sha256=sha256,
        size=_count(raw["size"]),
    )


def owned_keys_of(
    raw: object, organization: OrganizationRef, project_id: Any
) -> set[str]:
    """The subset of :func:`keys_of` that lies in this project's own namespaces.

    What a save or a discard may *delete*: the database under the project's workspace
    directory and each frame under its own dataset's frames directory. A key an edited
    manifest points elsewhere (another project, another tenant) is ignored, never queued.
    """
    org = _keys.organization_id(organization)
    owned: set[str] = set()
    if not isinstance(raw, dict):
        return owned
    db_prefix = f"{org}/projects/{_keys.uuid_text(project_id, 'project id')}/workspace/"
    db = raw.get("workspace_db")
    if (
        isinstance(db, dict)
        and isinstance(db.get("key"), str)
        and db["key"].startswith(db_prefix)
    ):
        owned.add(db["key"])
    datasets = raw.get("datasets")
    if isinstance(datasets, dict):
        for dataset_id, entry in datasets.items():
            if not (isinstance(entry, dict) and isinstance(entry.get("key"), str)):
                continue
            try:
                frames = f"{org}/datasets/{_keys.uuid_text(dataset_id, 'dataset id')}/frames/"
            except InvalidKeyError:
                continue
            if entry["key"].startswith(frames):
                owned.add(entry["key"])
    return owned


def keys_of(raw: object) -> set[str]:
    """Return every string that looks like a referenced key in ``raw``, without validating.

    For the lifecycle code, which asks "is this key still referenced?" about heads it may
    never load: a malformed manifest must not make a referenced object look deletable, so
    this errs towards *over*-reporting (any ``key`` string found in the known places).
    """
    found: set[str] = set()
    if not isinstance(raw, dict):
        return found
    db = raw.get("workspace_db")
    if isinstance(db, dict) and isinstance(db.get("key"), str):
        found.add(db["key"])
    datasets = raw.get("datasets")
    if isinstance(datasets, dict):
        for entry in datasets.values():
            if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                found.add(entry["key"])
    return found
