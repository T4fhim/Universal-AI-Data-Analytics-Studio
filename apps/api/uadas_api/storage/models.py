# File: apps/api/uadas_api/storage/models.py
"""Two small tenant tables the storage layer needs: the workspace pointer and the orphan queue.

``WorkspaceHead`` -- *the* pointer of a project's saved workspace, and the compare-and-swap
point of :class:`~uadas_api.storage.workspace.StorageBackedPersistence`. A save writes new
immutable objects and then moves this row from ``version`` *n* to *n + 1* with
``UPDATE ... WHERE version = n``; that single-row update is the object-store equivalent of
the Phase 2.7 ``os.replace(workspace.db.tmp, workspace.db)`` swap, and it is also what makes
two concurrent saves unable to both commit. The row holds the manifest itself (which object
is the workspace database, which is each dataset's frame, with sizes and SHA-256s) rather
than pointing at a manifest *object*: a database row is the one thing in this system that
supports an atomic conditional update on every backend (S3 conditional writes are not
available on every S3-compatible store, and a store that silently ignores ``If-Match`` would
turn "compare-and-swap" into "last writer wins" without anyone noticing).

``OrphanedObject`` -- a durable to-do list of stored objects whose deletion is owed: a deleted
row's file, the frames a save retired. It is written in the *same transaction* as the thing
that made them garbage (the row delete, the pointer swap), so a crash cannot lose the
obligation; ``lifecycle.purge_orphaned_objects`` then does the deletion after commit and
removes the entry only when it succeeded. A failure leaves the entry (with an attempt count
and the error class) for the next sweep. ``storage_key`` is an object key, or -- when
``is_prefix`` -- a directory prefix without its trailing slash.

Both are tenant-owned (the isolation harness covers them) and their stored keys obey the same
prefix rule as every other key: ``OrphanedObject.storage_key`` is the model's ``storage_key_field``;
a head's manifest keys are re-validated by the store facade on every use, so a manifest edited
in the database to name another tenant's object is refused rather than followed.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from uadas_api.tenancy import TenantOwnedModel
from uadas_api.workspaces.models import Project


class WorkspaceHead(TenantOwnedModel):
    """The current saved workspace of one project: a version and the manifest it commits."""

    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="workspace_heads"
    )
    version = models.PositiveIntegerField(default=1)
    manifest: models.JSONField[Any] = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "project"], name="uq_workspace_head_org_project"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="ck_workspace_head_version"
            ),
        ]

    def __str__(self) -> str:
        return f"workspace of {self.project_id} @ v{self.version}"


class OrphanedObject(TenantOwnedModel):
    """An object (or directory) whose deletion is owed; removed once the deletion succeeded."""

    storage_key = models.CharField(max_length=512)
    is_prefix = models.BooleanField(default=False)
    reason = models.CharField(max_length=32, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        # No unique constraint on (key, is_prefix): a duplicate entry is harmless (the second
        # purge finds nothing to delete) and the queue helper de-duplicates on insert (a
        # check-then-insert, so two concurrent writers may both insert). A constraint would
        # have to lead with ``organization`` *and* repeat the key, which the generic tenant
        # harness cannot exercise across organizations. The index serves that existence check.
        indexes = [
            models.Index(
                fields=["organization", "storage_key"], name="ix_orphan_org_key"
            ),
        ]

    storage_key_field = "storage_key"

    def __str__(self) -> str:
        return f"{self.storage_key}{'/' if self.is_prefix else ''}"
