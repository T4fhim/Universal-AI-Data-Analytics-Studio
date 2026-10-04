# File: apps/api/uadas_api/workspaces/models.py
"""Workspace rows: ``Project``, ``DatasetRecord``, ``ChartSpec``, ``Dashboard``.

Why: these are the database form of the core's session value types
(``uadas_core.models.workspace``: ``Dataset``, ``Visualization``, ``Dashboard``) and of
its ``Project``. They deliberately store *descriptions*, never data: a dataset's frame
lives in object storage under ``storage_key`` (3.4), a chart is its ``spec`` (the chart
name and parameters, so it can be rebuilt), a dashboard is a ``layout`` of tile
references.

The core's non-cascade rule is preserved, not "fixed": ``DatasetRecord.parent_dataset_id``
is a plain nullable UUID, **not** a foreign key, exactly as ``Dataset.parent_dataset_id``
is a plain string. Deleting a dataset never deletes or nulls its children, and an
orphaned ``parent_dataset_id`` (parent closed or never saved) is normal state that
lineage readers must tolerate. ``ChartSpec.dataset`` is ``SET_NULL`` for the same reason
(a visualization may outlive its dataset). Project containment cascades for rows that
own no stored object (``ChartSpec``, ``Dashboard``, the pipeline rows); the rows that *do*
own one (``DatasetRecord``, ``Report``) hold their project with ``PROTECT``.

What that ``PROTECT`` does and does not do: it stops ``Project.delete()`` while such rows
exist. It does **not** protect the stored object -- ``DatasetRecord.delete()`` and
``Report.delete()`` succeed and leave the object in the bucket. Deleting a row that owns a
stored object must therefore go through a service that deletes the object first (Phase
3.4, storage); until then nothing here prevents orphaned objects.

``parent_dataset_id`` may dangle (the parent was closed, or never saved) but may not name
a dataset of *another organization*; that is checked on every write path.

``DatasetRecord.id`` is the core ``Dataset.dataset_id`` (a UUID string) so a record and
the in-memory dataset it persists share one identity.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.db import models

from uadas_api.tenancy import TenantOwnedModel
from uadas_api.workspaces.choices import ChartType, SourceFormat


class Project(TenantOwnedModel):
    """A named workspace inside an organization; the unit datasets and charts belong to."""

    name = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"], name="uq_project_org_name"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "created_at"], name="ix_project_org_ts"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class DatasetRecord(TenantOwnedModel):
    """The persisted description of one dataset (the data itself is in object storage)."""

    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="datasets"
    )
    name = models.CharField(max_length=255)
    source_format = models.CharField(max_length=32, choices=SourceFormat.choices)
    # Plain UUID, NOT a ForeignKey: mirrors the core's non-cascade lineage rule.
    parent_dataset_id = models.UUIDField(null=True, blank=True)
    storage_key = models.CharField(max_length=512)
    row_count = models.PositiveBigIntegerField()
    column_count = models.PositiveBigIntegerField()
    derivation_description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(row_count__gte=0), name="ck_dataset_rows_nonneg"
            ),
            models.CheckConstraint(
                condition=models.Q(column_count__gte=0), name="ck_dataset_cols_nonneg"
            ),
            models.CheckConstraint(
                condition=~models.Q(parent_dataset_id=models.F("id")),
                name="ck_dataset_not_own_parent",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "project", "created_at"],
                name="ix_dataset_org_proj_ts",
            ),
            models.Index(
                fields=["organization", "parent_dataset_id"],
                name="ix_dataset_org_parent",
            ),
        ]

    # Enforced by TenantOwnedModel on every write path: starts with "<organization_id>/".
    storage_key_field = "storage_key"
    # Lineage may dangle (core non-cascade rule) but must not point into another tenant.
    soft_tenant_refs: ClassVar[dict[str, str]] = {
        "parent_dataset_id": "workspaces.DatasetRecord"
    }

    def __str__(self) -> str:
        return self.name


class ChartSpec(TenantOwnedModel):
    """A saved chart: which chart, with what parameters, optionally over which dataset."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="chart_specs"
    )
    dataset = models.ForeignKey(
        DatasetRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="chart_specs",
    )
    chart_type = models.CharField(max_length=32, choices=ChartType.choices)
    spec: models.JSONField[Any] = models.JSONField(default=dict, blank=True)
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        indexes = [
            models.Index(
                fields=["organization", "project", "created_at"],
                name="ix_chart_org_proj_ts",
            ),
        ]

    def __str__(self) -> str:
        return self.title or self.chart_type


class Dashboard(TenantOwnedModel):
    """An arrangement of saved charts; ``layout`` holds the tile grid."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="dashboards"
    )
    name = models.CharField(max_length=200)
    layout: models.JSONField[Any] = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        indexes = [
            models.Index(
                fields=["organization", "project", "created_at"],
                name="ix_dash_org_proj_ts",
            ),
        ]

    def __str__(self) -> str:
        return self.name
