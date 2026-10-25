# File: apps/api/uadas_api/quotas/signals.py
"""Give a deleted dataset's rows and stored bytes back to its organization's standing totals.

Why a ``post_delete`` receiver and not a line in the delete view: a dataset can disappear by more
than one road (the delete endpoint, a cascade from a deleted project, an admin), and the standing
quotas must not drift on whichever the next one is. The receiver runs inside the deleting
transaction, so the release commits or rolls back with the delete.

Only the ledger keys this codebase charged are released: ``rows:<id>`` (ingest) and
``upload:<id>`` (the upload that became the dataset). A derived dataset (a cleaning result) was
never charged for its original bytes, so releasing its keys is a harmless no-op -- :func:`release`
reports ``False`` for a key that has no charge.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_delete
from django.dispatch import receiver

from uadas_api.quotas import service
from uadas_api.quotas.choices import UsageKind
from uadas_api.workspaces.models import DatasetRecord


@receiver(post_delete, sender=DatasetRecord, dispatch_uid="uadas_quota_dataset_delete")
def release_dataset_usage(sender: Any, instance: DatasetRecord, **kwargs: Any) -> None:
    """Release the rows and stored bytes charged for the dataset that was just deleted."""
    service.release(
        instance.organization_id, UsageKind.ROWS, service.rows_key(instance.pk)
    )
    service.release(
        instance.organization_id,
        UsageKind.STORAGE_BYTES,
        service.upload_key(instance.pk),
    )
