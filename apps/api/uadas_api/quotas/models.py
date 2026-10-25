# File: apps/api/uadas_api/quotas/models.py
"""The quota tables: an organization's limit overrides, its usage counters, and the usage ledger.

Why three tables:

* :class:`OrganizationQuota` -- *limits*. One optional row per (organization, kind): no row means
  "use the deployment default" (``settings.UADAS_QUOTA``), a row's ``limit`` replaces it. (There is
  no way to say "unlimited" for one organization on a deployment that has a default -- give it a
  very large number; the set of states stays small enough to reason about.)
* :class:`UsageCounter` -- *usage*, one row per (organization, kind, window). This is the row the
  atomic ``UPDATE ... WHERE used <= limit - n`` targets, so concurrent charges serialize on its row
  lock and the database -- not the application -- decides who fits. ``used`` is never negative
  (check constraint).
* :class:`UsageLedger` -- *why*. One row per charge, unique per ``(organization, kind,
  source_key)``: a retried request, a redelivered job message or a re-run attempt carries the same
  ``source_key`` and so cannot be billed twice. A released charge keeps its row (``released``), so a
  later replay of the same key is recognised instead of silently re-charged.

All three are tenant-owned (:class:`~uadas_api.tenancy.TenantOwnedModel`): the isolation harness
covers them, and each unique constraint leads with ``organization``.

What this does **not** do: nothing reconciles the counters against the ledger or the stored data. A
process killed between a reservation and its release (an upload in flight) leaves ``used`` higher
than the truth until the charge is released by hand; a reconcile job is later work.
"""

from __future__ import annotations

from django.db import models

from uadas_api.quotas.choices import UsageKind
from uadas_api.tenancy import TenantOwnedModel


class OrganizationQuota(TenantOwnedModel):
    """One organization's limit for one resource, replacing the deployment default."""

    kind = models.CharField(max_length=24, choices=UsageKind.choices)
    limit = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind"], name="uq_org_quota_org_kind"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=UsageKind.values),
                name="ck_org_quota_kind",
            ),
        ]


class UsageCounter(TenantOwnedModel):
    """What one organization has used of one resource in one window (the atomic-update target)."""

    kind = models.CharField(max_length=24, choices=UsageKind.choices)
    # The first day of the UTC month for a monthly kind; the fixed STANDING_PERIOD otherwise.
    period_start = models.DateField()
    used = models.PositiveBigIntegerField(default=0)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind", "period_start"],
                name="uq_usage_counter_org_kind_period",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=UsageKind.values),
                name="ck_usage_counter_kind",
            ),
        ]


class UsageLedger(TenantOwnedModel):
    """One charge: ``amount`` of ``kind`` for the thing named ``source_key`` (idempotent per key)."""

    kind = models.CharField(max_length=24, choices=UsageKind.choices)
    # What the charge is for, e.g. "upload:<dataset id>" or "job:<job id>:<attempt>". Opaque,
    # never shown to a client and never logged (it names tenant rows).
    source_key = models.CharField(max_length=160)
    amount = models.PositiveBigIntegerField()
    # The window the amount was added to (a release gives it back to *this* window).
    period_start = models.DateField()
    released = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind", "source_key"],
                name="uq_usage_ledger_org_kind_key",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=UsageKind.values),
                name="ck_usage_ledger_kind",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(released=True, released_at__isnull=False)
                    | models.Q(released=False, released_at__isnull=True)
                ),
                name="ck_usage_ledger_released_iff_stamped",
            ),
        ]
