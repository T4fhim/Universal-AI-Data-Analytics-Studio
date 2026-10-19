# File: apps/api/tests/web_support.py
"""Fixtures for the 3.6 API tests: a two-organization world with one client per role, and stored frames.

Why a module: the resource, stage, IDOR and Schemathesis tests all need the same setup -- an
organization with an owner/admin/editor/viewer, a second organization with its own member, a project
with a real Parquet dataset in the (in-memory) object store -- and a browser-like client per user
(:class:`apihelpers.Api`, CSRF enforced). ``store_dataset`` writes the frame exactly as the ingest
job does (a new key under ``<org>/datasets/<id>/frames/``, SHA-256 recorded on the row), so every
read path under test goes through ``TenantObjectStore`` and hash verification, not a shortcut.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa
import pyarrow.parquet as pq
from apihelpers import Api
from factories import make_organization, make_user

from uadas_api.accounts.models import Membership, Organization, Role, User
from uadas_api.storage import keys
from uadas_api.storage.store import get_store
from uadas_api.workspaces.models import DatasetRecord, Project

FRAME_TYPE = "application/vnd.apache.parquet"


def parquet_bytes(frame: pd.DataFrame, row_group_size: int | None = None) -> bytes:
    """``frame`` as Parquet bytes (``row_group_size`` forces several row groups)."""
    buffer = io.BytesIO()
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        buffer,
        row_group_size=row_group_size,
    )
    return buffer.getvalue()


def store_dataset(
    org: Organization,
    project: Project,
    frame: pd.DataFrame,
    *,
    name: str = "data.csv",
    row_group_size: int | None = None,
    source_format: str = "csv",
) -> DatasetRecord:
    """Store ``frame`` as a dataset of ``project`` the way the ingest job does."""
    dataset_id = uuid.uuid4()
    key = keys.dataset_frame_key(org, dataset_id, "t0001")
    stored = get_store(org).put(
        key,
        parquet_bytes(frame, row_group_size),
        content_type=FRAME_TYPE,
        allowed_content_types=(FRAME_TYPE,),
    )
    return DatasetRecord.objects.create(
        id=dataset_id,
        organization=org,
        project=project,
        name=name,
        source_format=source_format,
        storage_key=key,
        sha256=stored.sha256 or "",
        row_count=len(frame),
        column_count=len(frame.columns),
    )


def join(org: Organization, role: Role) -> Membership:
    """A new user who is a member of ``org`` with ``role``."""
    return Membership.objects.create(user=make_user(), organization=org, role=role)


@dataclass
class World:
    """Organization A (four roles, one project, one dataset), organization B (one owner), an outsider."""

    org: Organization
    owner: Membership
    admin: Membership
    editor: Membership
    viewer: Membership
    project: Project
    dataset: DatasetRecord
    other_org: Organization
    other_owner: Membership
    other_project: Project
    outsider: User
    clients: dict[str, Api] = field(default_factory=dict)

    def api(self, who: str) -> Api:
        """A logged-in client for ``who`` (``owner``/``admin``/``editor``/``viewer``/``other``/``outsider``)."""
        if who not in self.clients:
            user = {
                "owner": self.owner.user,
                "admin": self.admin.user,
                "editor": self.editor.user,
                "viewer": self.viewer.user,
                "other": self.other_owner.user,
                "outsider": self.outsider,
            }[who]
            self.clients[who] = Api(user)
        return self.clients[who]

    def base(
        self, org: Organization | None = None, project: Project | None = None
    ) -> str:
        """``/api/organizations/<org>/projects/<project>`` (defaults: organization A's)."""
        return (
            f"/api/organizations/{(org or self.org).pk}"
            f"/projects/{(project or self.project).pk}"
        )

    @property
    def other_base(self) -> str:
        """Organization B's own project URL prefix."""
        return self.base(self.other_org, self.other_project)


SAMPLE = pd.DataFrame(
    {
        "id": list(range(1, 11)),
        "group": ["a", "b"] * 5,
        "value": [1.5, None, 3.5, 4.0, 5.5, 6.0, 7.5, 8.0, 9.5, 10.0],
        "label": [f"row {i}" for i in range(1, 11)],
    }
)


def make_world(frame: pd.DataFrame | None = None) -> World:
    """Build the two-organization world with ``frame`` (default :data:`SAMPLE`) as a dataset of A."""
    org, other = make_organization(), make_organization()
    project = Project.objects.create(organization=org, name="Main")
    other_project = Project.objects.create(organization=other, name="Other")
    return World(
        org=org,
        owner=join(org, Role.OWNER),
        admin=join(org, Role.ADMIN),
        editor=join(org, Role.EDITOR),
        viewer=join(org, Role.VIEWER),
        project=project,
        dataset=store_dataset(org, project, SAMPLE if frame is None else frame),
        other_org=other,
        other_owner=join(other, Role.OWNER),
        other_project=other_project,
        outsider=make_user(),
    )


def error_code(response: Any) -> str:
    """The ``error.code`` of an envelope response."""
    return str(response.json()["error"]["code"])
