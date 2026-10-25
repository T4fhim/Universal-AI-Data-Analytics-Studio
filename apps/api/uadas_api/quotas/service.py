# File: apps/api/uadas_api/quotas/service.py
"""Reserve, charge, release: the only code that moves a usage counter.

Why this shape: a quota check written as "read the counter, compare, write the counter" is a race --
two requests both read ``used = limit - 1`` and both pass. So the *database* arbitrates:
:func:`reserve` is a conditional ``UPDATE usage_counter SET used = used + n WHERE ... AND used <=
limit - n`` and the **row count is the verdict** (same device as the job claim in
:mod:`uadas_api.jobs.services`). Concurrent reservations serialize on the counter's row lock and each
re-evaluates the condition against the other's committed result, so the limit is never overshot by
a reservation. Nothing in this module reads a counter in order to decide a write.

Idempotency is the ledger: every charge inserts ``UsageLedger(organization, kind, source_key)``,
unique, in the *same transaction* as the counter update. A replay (retry, redelivery, a re-run
attempt) hits the unique constraint and is recognised -- it adds nothing -- and a charge that the
counter refuses rolls its ledger row back with it, so a refusal leaves no trace to replay.

Three verbs, because three situations exist:

* :func:`reserve` -- *strict*. Before the work: refused with :class:`QuotaExceededError` if it would
  not fit. Used where the amount is known up front (stored bytes of an upload).
* :func:`charge` -- *after the fact*. The work already happened (a job ran, a model answered), so
  refusing it would only lose the record; the amount is added even past the limit, and the **next**
  request is the one refused (:func:`assert_available`). The overshoot this allows is bounded by
  what can be in flight at once -- stated at each call site, never hidden.
* :func:`release` -- give a reservation back (upload failed, dataset deleted); idempotent, and the
  ledger row stays so the same key can be reserved again cleanly.

:func:`assert_available` is the *pre-check* for the charge-after kinds. It reads, and a read before
a write is a race by construction -- which is why it is only ever paired with :func:`charge`, whose
overshoot is bounded, and never used to guard a reservation.

Limits: a row in ``OrganizationQuota`` wins, else ``settings.UADAS_QUOTA``; ``None`` is unlimited
(usage is still counted). Nothing here logs a limit, a usage figure or a source key.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Model
from django.db.models.functions import Greatest
from django.utils import timezone

from uadas_api.quotas.choices import UsageKind, period_start
from uadas_api.quotas.errors import QuotaExceededError
from uadas_api.quotas.models import OrganizationQuota, UsageCounter, UsageLedger
from uadas_api.tenancy import OrganizationRef


@dataclass(frozen=True)
class Charge:
    """The outcome of :func:`reserve` / :func:`charge`: whether this call added to the counter."""

    kind: str
    amount: int
    applied: bool  # False: the key was already charged (a replay), nothing was added


def upload_key(dataset_id: uuid.UUID | str) -> str:
    """The ledger key of the stored bytes of the upload that became ``dataset_id``."""
    return f"upload:{dataset_id}"


def rows_key(dataset_id: uuid.UUID | str) -> str:
    """The ledger key of the rows of ``dataset_id``."""
    return f"rows:{dataset_id}"


def job_key(job_id: uuid.UUID | str, attempt: int) -> str:
    """The ledger key of the run time of one attempt of one job."""
    return f"job:{job_id}:{attempt}"


def _org_id(organization: OrganizationRef) -> uuid.UUID | str:
    if isinstance(organization, Model):
        return organization.pk  # type: ignore[no-any-return, unused-ignore]
    return organization


def _check(kind: str, amount: int, source_key: str) -> None:
    if kind not in UsageKind.values:
        raise ValueError("unknown usage kind")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError("a usage amount is a non-negative integer")
    if not source_key or len(source_key) > 160:
        raise ValueError("a source key is 1-160 characters")


def limit_for(organization: OrganizationRef, kind: str) -> int | None:
    """The limit that applies to ``organization`` for ``kind``: its own override, else the default."""
    override = (
        OrganizationQuota.objects.for_organization(_org_id(organization))
        .filter(kind=kind)
        .values_list("limit", flat=True)
        .first()
    )
    if override is not None:
        return int(override)
    default = settings.UADAS_QUOTA.get(f"max_{kind}")
    return None if default is None else int(default)


def usage_for(
    organization: OrganizationRef, kind: str, *, now: datetime.datetime | None = None
) -> int:
    """What ``organization`` has used of ``kind`` in the current window (a plain read)."""
    used = (
        UsageCounter.objects.for_organization(_org_id(organization))
        .filter(kind=kind, period_start=period_start(kind, now or timezone.now()))
        .values_list("used", flat=True)
        .first()
    )
    return int(used or 0)


def assert_available(
    organization: OrganizationRef, kind: str, *, now: datetime.datetime | None = None
) -> None:
    """Raise :class:`QuotaExceededError` if ``organization`` has already used up ``kind``.

    The pre-check for work whose size is unknown until it is done (a job's run time, a model's
    tokens): it refuses *new* work once the limit is reached, and :func:`charge` records what the
    work then cost. Two requests that both pass here may both run, so the limit can be overshot by
    the work in flight at that moment -- never by more, because the next check sees the charge.
    """
    limit = limit_for(organization, kind)
    if limit is not None and usage_for(organization, kind, now=now) >= limit:
        raise QuotaExceededError(kind)


def remaining(
    organization: OrganizationRef, kind: str, *, now: datetime.datetime | None = None
) -> int | None:
    """How much of ``kind`` is left in the current window (``None``: unlimited; never negative)."""
    limit = limit_for(organization, kind)
    if limit is None:
        return None
    return max(limit - usage_for(organization, kind, now=now), 0)


def _add(
    org: uuid.UUID | str,
    kind: str,
    period: datetime.date,
    amount: int,
    limit: int | None,
) -> bool:
    """Add ``amount`` to the counter; with ``limit``, only if it fits. ``True`` if it was added.

    THE conditional update. The counter row is created on first use with ``ON CONFLICT DO NOTHING``
    (two first requests both try; one wins; both then go to the same row), and the arbiter is the
    ``UPDATE``'s row count -- ``used <= limit - amount`` is evaluated by the database under the
    row lock, so a concurrent charge that commits first is seen by the second.
    """
    counter = UsageCounter.objects.for_organization(org).filter(
        kind=kind, period_start=period
    )
    if limit is not None:
        counter = counter.filter(used__lte=limit - amount)
    if counter.update(used=F("used") + amount):
        return True
    UsageCounter.objects.bulk_create(
        [UsageCounter(organization_id=org, kind=kind, period_start=period, used=0)],
        ignore_conflicts=True,
    )
    return bool(counter.update(used=F("used") + amount))


def _apply(
    organization: OrganizationRef,
    kind: str,
    amount: int,
    source_key: str,
    *,
    strict: bool,
    now: datetime.datetime | None,
) -> Charge:
    _check(kind, amount, source_key)
    org = _org_id(organization)
    moment = now or timezone.now()
    period = period_start(kind, moment)
    limit = limit_for(org, kind) if strict else None
    with transaction.atomic():
        ledger = UsageLedger.objects.for_organization(org).filter(
            kind=kind, source_key=source_key
        )
        try:
            with transaction.atomic():
                UsageLedger.objects.create(
                    organization_id=org,
                    kind=kind,
                    source_key=source_key,
                    amount=amount,
                    period_start=period,
                )
        except IntegrityError:
            # The key is known: a replay -- unless it was released, which makes it chargeable
            # again (a fenced flip, so two revivals cannot both charge).
            revived = ledger.filter(released=True).update(
                released=False,
                released_at=None,
                amount=amount,
                period_start=period,
            )
            if not revived:
                if not ledger.exists():
                    raise  # not a duplicate key: a real integrity failure (e.g. no such organization)
                return Charge(kind, amount, applied=False)
        if not _add(org, kind, period, amount, limit):
            # Rolls the ledger row back with it (this atomic block), leaving nothing to replay.
            raise QuotaExceededError(kind)
    return Charge(kind, amount, applied=True)


def reserve(
    organization: OrganizationRef,
    kind: str,
    amount: int,
    source_key: str,
    *,
    now: datetime.datetime | None = None,
) -> Charge:
    """Charge ``amount`` of ``kind`` if (and only if) it fits; else raise :class:`QuotaExceededError`.

    Exactly at the limit is allowed; one over is refused. A repeat of ``source_key`` is a replay:
    nothing is added and ``applied`` is ``False`` -- even if the limit has been reached since, because
    the original reservation already holds its share. Call it inside the transaction that does the
    work it pays for, or release it when that work fails.
    """
    return _apply(organization, kind, amount, source_key, strict=True, now=now)


def charge(
    organization: OrganizationRef,
    kind: str,
    amount: int,
    source_key: str,
    *,
    now: datetime.datetime | None = None,
) -> Charge:
    """Record ``amount`` of ``kind`` that has already been spent; never refused, idempotent per key.

    For the charge-after kinds (see the module docstring): the work happened, so the record is
    kept even past the limit and the *next* :func:`assert_available` refuses.
    """
    return _apply(organization, kind, amount, source_key, strict=False, now=now)


def release(
    organization: OrganizationRef,
    kind: str,
    source_key: str,
    *,
    now: datetime.datetime | None = None,
) -> bool:
    """Give back the charge for ``source_key``. ``True`` if this call did; ``False`` if none/already.

    Fenced like a job transition: the ledger row flips ``released`` in one conditional update, and
    only the call that flipped it gives the amount back (to the window it was charged in), so two
    racing releases cannot subtract twice. The counter never goes below zero.
    """
    _check(kind, 0, source_key)
    org = _org_id(organization)
    with transaction.atomic():
        ledger = UsageLedger.objects.for_organization(org).filter(
            kind=kind, source_key=source_key
        )
        if not ledger.filter(released=False).update(
            released=True, released_at=now or timezone.now()
        ):
            return False
        amount, period = ledger.values_list("amount", "period_start").get()
        UsageCounter.objects.for_organization(org).filter(
            kind=kind, period_start=period
        ).update(used=Greatest(F("used") - amount, 0))
    return True


def rekey(organization: OrganizationRef, kind: str, old_key: str, new_key: str) -> bool:
    """Rename a charge's ``source_key`` (a hold taken before the final key was known).

    ``True`` if renamed; ``False`` if ``old_key`` has no charge or ``new_key`` is already taken (the
    caller then releases ``old_key``: the thing it paid for is already paid for elsewhere).
    """
    _check(kind, 0, old_key)
    _check(kind, 0, new_key)
    org = _org_id(organization)
    try:
        with transaction.atomic():
            return bool(
                UsageLedger.objects.for_organization(org)
                .filter(kind=kind, source_key=old_key, released=False)
                .update(source_key=new_key)
            )
    except IntegrityError:
        return False
