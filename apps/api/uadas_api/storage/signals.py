# File: apps/api/uadas_api/storage/signals.py
"""``post_delete`` receivers: a deleted row owes its stored objects' deletion.

Why signals rather than a service everyone must remember to call: ``DatasetRecord.delete()``,
``QuerySet.delete()`` and a cascade all reach ``post_delete``, so every ordinary delete path
queues its objects (:func:`uadas_api.storage.lifecycle.queue_deletions`) inside the delete's
own transaction -- the plan-3.2 obligation ("deletes of rows owning stored objects must go
through something that deletes the object") met without a way to forget. Connecting a
receiver also makes Django collect the rows instead of fast-deleting them, so the signal
cannot be skipped by the fast-delete optimisation. ``QuerySet._raw_delete`` and raw SQL
still bypass it (documented in ``lifecycle``).

A receiver does no I/O beyond inserting queue rows: the objects are deleted after commit.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete
from django.dispatch import receiver

from uadas_api.exports.models import Report
from uadas_api.storage import keys
from uadas_api.storage.lifecycle import queue_deletions
from uadas_api.storage.manifest import owned_keys_of
from uadas_api.storage.models import WorkspaceHead
from uadas_api.workspaces.models import DatasetRecord


@receiver(post_delete, sender=DatasetRecord, dispatch_uid="storage.dataset_deleted")
def dataset_deleted(sender: Any, instance: DatasetRecord, **kwargs: Any) -> None:
    """Queue the dataset's whole directory, plus its ``storage_key`` if that lies elsewhere."""
    org = instance.organization_id
    prefix = keys.dataset_prefix(org, instance.pk)
    items: list[tuple[str, bool]] = [(prefix.rstrip("/"), True)]
    if instance.storage_key and not instance.storage_key.startswith(prefix):
        items.append((instance.storage_key, False))
    queue_deletions(org, items, reason="dataset-deleted")


@receiver(post_delete, sender=Report, dispatch_uid="storage.report_deleted")
def report_deleted(sender: Any, instance: Report, **kwargs: Any) -> None:
    """Queue the report's file (a pending or failed report has none)."""
    if instance.storage_key:
        queue_deletions(
            instance.organization_id,
            [(instance.storage_key, False)],
            reason="report-deleted",
        )


@receiver(post_delete, sender=WorkspaceHead, dispatch_uid="storage.head_deleted")
def head_deleted(sender: Any, instance: WorkspaceHead, **kwargs: Any) -> None:
    """Queue every object the discarded workspace referenced, and the project's directory."""
    org = instance.organization_id
    items: list[tuple[str, bool]] = [
        (keys.project_prefix(org, instance.project_id).rstrip("/"), True),
        # Only keys inside this project's own namespaces: a manifest edited to name another
        # project's (or tenant's) objects must not turn a discard into their deletion.
        *(
            (key, False)
            for key in sorted(
                owned_keys_of(instance.manifest, org, instance.project_id)
            )
        ),
    ]
    queue_deletions(org, items, reason="workspace-discarded")
