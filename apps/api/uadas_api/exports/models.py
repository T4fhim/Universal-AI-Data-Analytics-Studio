# File: apps/api/uadas_api/exports/models.py
"""``Report``: the record of one generated (or being generated) report file.

Why a row and not just a file: a report is produced by a background job (3.5), so there
is a period where it exists as a request (``pending``) before the file does. The row
tracks that lifecycle and, once ``ready``, names the stored object.

``storage_key`` follows the same tenant-prefix rule as
:class:`~uadas_api.workspaces.models.DatasetRecord`, with one deliberate difference: it
may be empty while the report is ``pending`` or ``failed`` (there is no object yet), and
the database refuses a ``ready`` report without one. When present it must start with
``"<organization_id>/"``. The project foreign key is ``PROTECT``, which only stops
``Project.delete()`` while reports exist: ``Report.delete()`` itself succeeds and leaves
the stored file behind, so deleting a report must go through a service that removes the
object first (Phase 3.4).
"""

from __future__ import annotations

from typing import Any

from django.db import models

from uadas_api.exports.choices import ReportFormat, ReportStatus
from uadas_api.tenancy import TenantOwnedModel
from uadas_api.workspaces.models import Project


class Report(TenantOwnedModel):
    """One report: what was asked for, its state, and where the file is once ready."""

    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="reports"
    )
    title = models.CharField(max_length=255)
    format = models.CharField(max_length=16, choices=ReportFormat.choices)
    status = models.CharField(
        max_length=16, choices=ReportStatus.choices, default=ReportStatus.PENDING
    )
    storage_key = models.CharField(max_length=512, blank=True)
    config: models.JSONField[Any] = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(format__in=ReportFormat.values),
                name="ck_report_format",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ReportStatus.values),
                name="ck_report_status",
            ),
            models.CheckConstraint(
                condition=~models.Q(status=ReportStatus.READY)
                | ~models.Q(storage_key=""),
                name="ck_report_ready_has_key",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "project", "created_at"],
                name="ix_report_org_proj_ts",
            ),
        ]

    # Same rule as DatasetRecord, except "no object yet" (blank) is legal until ready.
    storage_key_field = "storage_key"
    storage_key_may_be_blank = True

    def __str__(self) -> str:
        return self.title
