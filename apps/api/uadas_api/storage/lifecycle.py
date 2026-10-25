# File: apps/api/uadas_api/storage/lifecycle.py
"""Row <-> object lifecycle: owed deletions, their sweeper, and a read-only reconciliation.

The problem (``plans/phase-3-2-data-model.md``): ``PROTECT`` on a project does not protect a
dataset's or report's *object*, and ``DatasetRecord.delete()`` used to leave it in the bucket
forever. No distributed transaction exists between PostgreSQL and an object store, so the
design is the standard outbox:

1. **Record the debt in the same transaction as its cause.** ``post_delete`` receivers
   (``signals``) and the workspace save (``workspace``) call :func:`queue_object_deletion`,
   which inserts an ``OrphanedObject`` row. If the surrounding transaction rolls back, so
   does the debt (a rolled-back delete deletes nothing); if the process dies right after
   commit, the debt is on disk.
2. **Pay it after commit** (:func:`schedule_purge` -> ``transaction.on_commit``):
   :func:`purge_orphaned_objects` deletes through the owning organization's store handle,
   idempotently, and removes the entry only when the object is really gone. A failure is
   logged (error *class* only), counted on the entry, and left for the next sweep -- a save
   or a delete never fails because of garbage collection.
3. **Sweep.** ``manage.py purge_orphaned_objects`` (run from cron or a worker) retries
   every owed entry. That is the documented sweeper; there is no background thread.

Why not delete first, or inside the transaction: an object delete cannot be rolled back.
Deleting before commit loses data if the commit then fails; deleting after commit can only
leak (an object with no row), which is exactly what the outbox and the reconciliation report
exist to repair.

**A saved workspace's objects are never deleted from under it.** Before paying a debt the
sweeper subtracts every key a current ``WorkspaceHead`` still references: a dataset row
deleted while the saved workspace still contains its frame must not leave that workspace
unloadable. The entry stays (``deferred``) until a later save drops the frame from the
manifest. Callers wanting to close a dataset should save a new workspace without it.

Not covered: ``QuerySet._raw_delete``, raw SQL and ``loaddata`` skip signals; a bucket
lifecycle rule (age-based expiry of abandoned uploads) is the operator's complement.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import F

from uadas_api.storage import keys as _keys
from uadas_api.storage.errors import (
    InvalidKeyError,
    StorageError,
    StorageUnavailableError,
)
from uadas_api.storage.manifest import keys_of
from uadas_api.storage.models import OrphanedObject, WorkspaceHead
from uadas_api.storage.store import TenantObjectStore, get_store
from uadas_api.tenancy import OrganizationRef

_logger = logging.getLogger(__name__)

_DEFAULT_PURGE_LIMIT = 200


@dataclass(frozen=True)
class PurgeReport:
    """Outcome of one sweep. ``deferred`` entries are still owed but must wait (referenced)."""

    deleted: int = 0
    failed: int = 0
    deferred: int = 0


@dataclass(frozen=True)
class RowFinding:
    """A database row whose object is missing: which row, and the key it names."""

    model: str
    pk: str
    key: str


@dataclass(frozen=True)
class ReconciliationReport:
    """Facts about one organization's rows versus its objects. Decides and deletes nothing."""

    rows_without_objects: list[RowFinding]
    objects_without_rows: list[str]
    pending_deletion: list[str]


def _org_pk(organization: OrganizationRef) -> Any:
    return organization.pk if hasattr(organization, "pk") else organization


def queue_object_deletion(
    organization: OrganizationRef,
    key: str,
    *,
    is_prefix: bool = False,
    reason: str = "",
) -> bool:
    """Record that ``key`` (or the directory ``key``) owes deletion; return whether it was queued.

    Call it inside the transaction that made the object garbage. Idempotent (an existing
    entry for the same key and kind is kept, not duplicated). An invalid key is logged and skipped, never
    raised: it must not be able to abort the delete or save that triggered it.
    """
    try:
        if is_prefix:
            _keys.check_prefix(organization, f"{key}/")
            if not _keys.is_deletable_prefix(organization, key):
                # Only a dataset's or a project's own directory may be queued wholesale.
                raise InvalidKeyError("not a dataset or project directory")
        else:
            _keys.check_key(organization, key)
    except StorageError:
        _logger.error("not queueing an invalid storage key for deletion (%s)", reason)
        return False
    org = _org_pk(organization)
    if not OrphanedObject.objects.filter(
        organization_id=org, storage_key=key, is_prefix=is_prefix
    ).exists():
        OrphanedObject.objects.create(
            organization_id=org,
            storage_key=key,
            is_prefix=is_prefix,
            reason=reason[:32],
        )
    return True


class _PurgeAfterCommit:
    """The after-commit hook of one organization's sweep (a named type so it can be coalesced)."""

    def __init__(self, organization_id: Any) -> None:
        self.organization_id = organization_id

    def __call__(self) -> None:
        purge_orphaned_objects(self.organization_id)


def schedule_purge(organization: OrganizationRef) -> None:
    """Pay this organization's owed deletions once the current transaction commits.

    Registers **one** hook per organization per transaction: deleting N rows in a unit of
    work must not run N sweeps, each re-reading every manifest. The existing registrations
    are read from the connection (``run_on_commit``), where a rolled-back savepoint has
    already dropped its own, so a hook cancelled by a rollback never suppresses a later one.
    ``robust=True``: an unexpected error in the sweep is logged by Django and cannot undo or
    break the commit it follows.
    """
    org = _org_pk(organization)
    connection = transaction.get_connection()
    for _savepoints, hook, *_rest in connection.run_on_commit:
        if isinstance(hook, _PurgeAfterCommit) and str(hook.organization_id) == str(
            org
        ):
            return
    transaction.on_commit(_PurgeAfterCommit(org), robust=True)


def referenced_keys(organization: OrganizationRef) -> set[str]:
    """Every object key a current saved workspace of ``organization`` references."""
    found: set[str] = set()
    for manifest in WorkspaceHead.objects.for_organization(organization).values_list(
        "manifest", flat=True
    ):
        found |= keys_of(manifest)
    return found


def _written_after(last_modified: datetime, debt: datetime) -> bool:
    """Whether an object stamped ``last_modified`` may have been written after ``debt`` was queued.

    Conservative about the clock: S3-compatible stores stamp whole seconds (microsecond 0),
    so such an object could have been written up to a second *after* the stamp; one with a
    finer stamp is compared exactly. When in doubt the answer is "yes" -- an object that may
    be newer than the debt is never deleted by it.
    """
    resolution = (
        timedelta(seconds=1) if last_modified.microsecond == 0 else timedelta(0)
    )
    return last_modified + resolution > debt


def _grace_seconds(min_age_seconds: int | None) -> int:
    if min_age_seconds is not None:
        return min_age_seconds
    return int(getattr(settings, "UADAS_STORAGE", {}).get("gc_grace_seconds", 0))


def _purge_entry(
    entry: OrphanedObject,
    store: TenantObjectStore,
    referenced: set[str],
    grace_seconds: int,
) -> str:
    """Pay one debt. Returns ``"deleted"`` or ``"deferred"``; raises ``StorageError`` on failure.

    Three rules keep a sweep from ever deleting something live:

    * an **exact key** is retired garbage: it waits until the debt is ``grace_seconds`` old
      (a reader that loaded the previous workspace, or a save in progress, may still need it)
      and is never deleted while a saved workspace references it;
    * a **directory** entry (re-validated here, not only when queued: a row edited to name
      ``<org>/exports`` is refused) deletes only objects that existed when the debt was
      queued -- one written *after* it cannot be owed by it; the commonest case is an
      in-flight save's upload, which a retried directory purge must not touch -- and only
      those older than ``grace_seconds`` and not referenced by a saved workspace;
    * an entry stays owed (``deferred``) while something it covers is blocked by those rules,
      and is settled once nothing it covers remains.
    """
    now = datetime.now(UTC)
    if not entry.is_prefix:
        if entry.storage_key in referenced or entry.created_at > now - timedelta(
            seconds=grace_seconds
        ):
            return "deferred"
        store.delete(entry.storage_key)
        return "deleted"
    if not _keys.is_deletable_prefix(entry.organization_id, entry.storage_key):
        raise InvalidKeyError("not a dataset or project directory")
    cutoff = now - timedelta(seconds=grace_seconds)
    waiting = False
    doomed: list[str] = []
    for stored in store.list_prefix(f"{entry.storage_key}/"):
        if _written_after(stored.last_modified, entry.created_at):
            continue  # not part of this debt
        if stored.key in referenced or stored.last_modified > cutoff:
            waiting = True
            continue
        doomed.append(stored.key)
    if doomed and store.delete_many(doomed).failed:
        raise StorageUnavailableError("some objects could not be deleted")
    return "deferred" if waiting else "deleted"


def purge_orphaned_objects(
    organization: OrganizationRef | None = None,
    *,
    limit: int = _DEFAULT_PURGE_LIMIT,
    min_age_seconds: int | None = None,
) -> PurgeReport:
    """Delete up to ``limit`` owed objects (of one organization, or of all) and settle the queue.

    Safe to run any number of times and concurrently: a delete of an absent object is a
    no-op, and an entry is removed only after its object is gone. ``min_age_seconds`` is the
    grace period (default: ``STORAGE_GC_GRACE_SECONDS``, one hour); see :func:`_purge_entry`
    for what it and the debt's own timestamp protect. Entries are taken least-attempted
    first, oldest first, and an entry that fails or has to wait has its ``attempts`` raised --
    so a backlog of stuck entries cannot starve newer ones. What the saved workspaces
    reference is read once per organization per sweep: anything a save commits mid-sweep was
    uploaded after the debt (or reuses an object the earlier head already referenced), so the
    rules above already protect it. One organization's failure (an unreadable store, an
    error reading its heads) is counted and does not stop the sweep for the others.
    """
    grace = _grace_seconds(min_age_seconds)
    entries = (
        OrphanedObject.objects.for_organization(organization)
        if organization is not None
        else OrphanedObject.objects.all()
    ).order_by("attempts", "created_at")[:limit]
    deleted = failed = deferred = 0
    stores: dict[Any, TenantObjectStore] = {}
    referenced_by_org: dict[Any, set[str]] = {}
    for entry in list(entries):
        org = entry.organization_id
        try:
            if org not in stores:
                stores[org] = get_store(org)
                referenced_by_org[org] = referenced_keys(org)
            outcome = _purge_entry(entry, stores[org], referenced_by_org[org], grace)
        except (StorageError, DatabaseError) as error:
            failed += 1
            _logger.warning(
                "could not delete an owed object (%s)", type(error).__name__
            )
            OrphanedObject.objects.filter(pk=entry.pk).update(
                attempts=F("attempts") + 1, last_error=type(error).__name__
            )
            continue
        if outcome == "deleted":
            deleted += 1
            entry.delete()
        else:
            deferred += 1
            OrphanedObject.objects.filter(pk=entry.pk).update(
                attempts=F("attempts") + 1, last_error="deferred"
            )
    return PurgeReport(deleted=deleted, failed=failed, deferred=deferred)


def queue_deletions(
    organization: OrganizationRef,
    items: Iterable[tuple[str, bool]],
    *,
    reason: str,
) -> None:
    """Queue every ``(key, is_prefix)`` in ``items`` and schedule one purge after commit."""
    queued = [
        queue_object_deletion(organization, key, is_prefix=is_prefix, reason=reason)
        for key, is_prefix in items
    ]
    if any(queued):
        schedule_purge(organization)


def reconcile_tenant_storage(
    organization: OrganizationRef,
    *,
    min_age_seconds: int = 0,
    store: TenantObjectStore | None = None,
) -> ReconciliationReport:
    """Compare ``organization``'s rows with its bucket namespace; report, never repair.

    * ``rows_without_objects`` -- a dataset / report row (or saved-workspace manifest) names
      an object that is not in the bucket: the data is gone and the row is a dead pointer.
    * ``objects_without_rows`` -- an object nothing references: a leaked upload, a crashed
      save's new generation. ``min_age_seconds`` skips objects younger than that, because an
      upload in flight (written, not yet committed) looks exactly like a leak.
    * ``pending_deletion`` -- objects already queued in ``OrphanedObject``; not leaks.

    One listing of the organization's prefix, plus a few small queries. Deleting anything it
    finds is a separate, deliberate step (``purge_orphaned_objects`` for queued entries).
    """
    from uadas_api.exports.models import Report
    from uadas_api.workspaces.models import DatasetRecord

    handle = store or get_store(organization)
    listed = {
        stored.key: stored
        for stored in handle.list_prefix(_keys.organization_prefix(organization))
    }

    expected: dict[str, RowFinding] = {}
    for pk, key in DatasetRecord.objects.for_organization(organization).values_list(
        "pk", "storage_key"
    ):
        expected[key] = RowFinding("workspaces.DatasetRecord", str(pk), key)
    for pk, key in (
        Report.objects.for_organization(organization)
        .exclude(storage_key="")
        .values_list("pk", "storage_key")
    ):
        expected[key] = RowFinding("exports.Report", str(pk), key)
    for pk, manifest in WorkspaceHead.objects.for_organization(
        organization
    ).values_list("pk", "manifest"):
        for key in keys_of(manifest):
            expected.setdefault(key, RowFinding("storage.WorkspaceHead", str(pk), key))

    owed_keys: set[str] = set()
    owed_prefixes: list[str] = []
    for key, is_prefix in OrphanedObject.objects.for_organization(
        organization
    ).values_list("storage_key", "is_prefix"):
        if is_prefix:
            owed_prefixes.append(f"{key}/")
        else:
            owed_keys.add(key)

    def is_owed(key: str) -> bool:
        # str.startswith with a tuple is one C-level scan per key, not a Python loop.
        return key in owed_keys or key.startswith(tuple(owed_prefixes))

    owing = {key for key in listed if is_owed(key)}  # computed once, used twice below

    cutoff = datetime.now(UTC) - timedelta(seconds=min_age_seconds)
    return ReconciliationReport(
        rows_without_objects=sorted(
            (finding for key, finding in expected.items() if key not in listed),
            key=lambda finding: (finding.model, finding.pk),
        ),
        objects_without_rows=sorted(
            key
            for key, stored in listed.items()
            if key not in expected
            and key not in owing
            and (min_age_seconds <= 0 or stored.last_modified <= cutoff)
        ),
        pending_deletion=sorted(owing),
    )
