# File: apps/api/tests/test_storage_lifecycle.py
"""Row <-> object lifecycle (3.4): deleting a row owes its objects' deletion, durably.

Why: Phase 3.2 left ``DatasetRecord.delete()`` / ``Report.delete()`` orphaning the bucket
object. The design here: a ``post_delete`` receiver writes ``OrphanedObject`` rows *inside
the delete's own transaction* (so a rolled-back delete owes nothing and a crash cannot lose
the obligation), and the objects are deleted only **after commit**, idempotently, with a
failure leaving the entry for the next sweep. A row delete by any route (instance, queryset,
cascade) goes through the receiver; ``QuerySet._raw_delete`` and raw SQL are the documented
exceptions. The reconciliation report is read-only.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.db import models, transaction
from factories import factory_for, make_organization
from storage_support import FaultyBackend

from uadas_api.exports.models import Report
from uadas_api.storage import keys, lifecycle
from uadas_api.storage.errors import StorageUnavailableError
from uadas_api.storage.lifecycle import (
    purge_orphaned_objects,
    queue_object_deletion,
    reconcile_tenant_storage,
)
from uadas_api.storage.memory import InMemoryBackend
from uadas_api.storage.models import OrphanedObject, WorkspaceHead
from uadas_api.storage.store import get_store, override_backend
from uadas_api.workspaces.models import DatasetRecord, Project

pytestmark = pytest.mark.django_db

BIN = {"application/octet-stream"}
Capture = Callable[..., Any]


def _put(org: Any, key: str, data: bytes = b"x") -> None:
    get_store(org).put(
        key,
        io.BytesIO(data),
        content_type="application/octet-stream",
        allowed_content_types=BIN,
    )


def _dataset_with_objects(org: Any) -> tuple[DatasetRecord, str, str]:
    """A dataset row plus an original and a frame under its directory."""
    record = factory_for(DatasetRecord).create(org)
    original = keys.dataset_original_key(org, record.pk)
    frame = keys.dataset_frame_key(org, record.pk, keys.new_save_token(1))
    record.storage_key = original
    record.save()
    _put(org, original)
    _put(org, frame)
    return record, original, frame


def _exists(org: Any, key: str) -> bool:
    return get_store(org).exists(key)


# --- deleting a row owes its objects ------------------------------------------------


def test_deleting_a_dataset_queues_its_objects_and_removes_them_only_after_commit(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    record, original, frame = _dataset_with_objects(org)
    other, other_original, _ = _dataset_with_objects(org)
    record_id = record.pk  # Django clears the instance's pk once it is deleted

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        record.delete()

    # In the delete's transaction: the debt is recorded, nothing is deleted yet.
    assert not DatasetRecord.objects.filter(pk=record_id).exists()
    owed = {
        (o.storage_key, o.is_prefix)
        for o in OrphanedObject.objects.for_organization(org)
    }
    assert (keys.dataset_prefix(org, record_id).rstrip("/"), True) in owed
    assert _exists(org, original) and _exists(org, frame)

    for callback in callbacks:  # the commit happens
        callback()

    assert not _exists(org, original) and not _exists(org, frame)
    assert not OrphanedObject.objects.for_organization(org).exists()
    assert _exists(org, other_original)  # another dataset is untouched
    assert DatasetRecord.objects.filter(pk=other.pk).exists()


def test_a_queryset_delete_goes_through_the_same_path(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    record, original, frame = _dataset_with_objects(org)
    with django_capture_on_commit_callbacks(execute=True):
        DatasetRecord.objects.for_organization(org).filter(pk=record.pk).delete()
    assert not _exists(org, original) and not _exists(org, frame)


def test_a_key_outside_the_dataset_directory_is_queued_as_its_own_entry(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    record = factory_for(DatasetRecord).create(
        org
    )  # factory key: <org>/datasets/<uuid>.parquet
    _put(org, record.storage_key)
    with django_capture_on_commit_callbacks(execute=True):
        record.delete()
    assert not _exists(org, record.storage_key)


def test_deleting_a_report_queues_its_file_and_a_pending_report_queues_nothing(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    ready = factory_for(Report).create(
        org, status="ready", storage_key=keys.export_key(org, uuid.uuid4(), "pdf")
    )
    pending = factory_for(Report).create(org)  # no object yet
    _put(org, ready.storage_key)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        pending.delete()
    assert callbacks == []
    assert not OrphanedObject.objects.for_organization(org).exists()
    with django_capture_on_commit_callbacks(execute=True):
        ready.delete()
    assert not _exists(org, ready.storage_key)


def test_a_rolled_back_delete_owes_nothing_and_removes_nothing(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    record, original, frame = _dataset_with_objects(org)
    record_id = record.pk
    with (
        django_capture_on_commit_callbacks(execute=True) as callbacks,
        pytest.raises(RuntimeError),
        transaction.atomic(),
    ):
        record.delete()
        raise RuntimeError("the unit of work fails after the delete")
    assert callbacks == []
    assert DatasetRecord.objects.filter(pk=record_id).exists()
    assert not OrphanedObject.objects.for_organization(org).exists()
    assert _exists(org, original) and _exists(org, frame)


# --- retry, idempotence, isolation ---------------------------------------------------


def test_a_failed_object_delete_stays_queued_and_a_later_sweep_finishes_it(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    record, original, frame = _dataset_with_objects(org)
    faulty = FaultyBackend(InMemoryBackend())
    with override_backend(faulty):
        _put(org, original)
        _put(org, frame)
        faulty.fail("delete")
        with django_capture_on_commit_callbacks(execute=True):
            record.delete()  # the purge runs after commit and fails -- the delete itself did not
        entry = OrphanedObject.objects.for_organization(org).get(is_prefix=True)
        assert entry.attempts == 1
        assert entry.last_error == "StorageUnavailableError"
        assert _exists(org, original)

        faulty.heal()
        report = purge_orphaned_objects(org)
        assert report.deleted == 1 and report.failed == 0
        assert not _exists(org, original) and not _exists(org, frame)
        assert not OrphanedObject.objects.for_organization(org).exists()
        assert purge_orphaned_objects(org).deleted == 0  # idempotent


def test_a_purge_that_raises_inside_the_commit_hook_does_not_break_the_commit(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    record, *_ = _dataset_with_objects(org)
    faulty = FaultyBackend(InMemoryBackend())
    faulty.fail("list", exc=StorageUnavailableError("store down"))
    with override_backend(faulty):
        with django_capture_on_commit_callbacks(execute=True):
            record.delete()  # must not raise
        assert OrphanedObject.objects.for_organization(org).exists()


def test_each_orphan_is_purged_through_its_own_organizations_handle() -> None:
    org_a, org_b = make_organization(), make_organization()
    a_key = f"{org_a.pk}/exports/{uuid.uuid4()}/a.pdf"
    b_key = f"{org_b.pk}/exports/{uuid.uuid4()}/b.pdf"
    _put(org_a, a_key)
    _put(org_b, b_key)
    factory_for(OrphanedObject).create(org_a, storage_key=a_key)
    factory_for(OrphanedObject).create(org_b, storage_key=b_key)
    report = purge_orphaned_objects()
    assert report.deleted == 2
    assert not _exists(org_a, a_key) and not _exists(org_b, b_key)


def test_an_entry_never_deletes_into_another_organization() -> None:
    """A row edited (raw SQL) to carry another tenant's key is refused by the facade."""
    org_a, org_b = make_organization(), make_organization()
    victim = f"{org_b.pk}/exports/{uuid.uuid4()}/victim.pdf"
    _put(org_b, victim)
    entry = factory_for(OrphanedObject).create(org_a)
    # Bypass every model guard (TenantQuerySet.update would refuse this key), as a database
    # editor would: the base QuerySet.update writes the column directly.
    models.QuerySet.update(
        OrphanedObject.objects.filter(pk=entry.pk), storage_key=victim
    )
    report = purge_orphaned_objects(org_a)
    assert report.failed == 1
    assert _exists(org_b, victim)  # org A's handle refused it; nothing was deleted
    assert OrphanedObject.objects.get(pk=entry.pk).attempts == 1


def test_only_dataset_and_project_directories_can_be_queued_as_prefixes() -> None:
    org = make_organization()
    refused = [f"{org.pk}", f"{org.pk}/exports", f"{org.pk}/datasets", f"{org.pk}/x/y"]
    for key in refused:
        assert queue_object_deletion(org, key, is_prefix=True) is False
    assert not OrphanedObject.objects.for_organization(org).exists()
    # Positive twins: the two directory shapes the layouts define are accepted.
    assert queue_object_deletion(
        org, f"{org.pk}/datasets/{uuid.uuid4()}", is_prefix=True
    )
    assert queue_object_deletion(
        org, f"{org.pk}/projects/{uuid.uuid4()}", is_prefix=True
    )


def test_a_prefix_entry_that_is_not_a_dataset_or_project_directory_is_never_paid() -> (
    None
):
    """A row edited to name a broad directory is refused at purge time, not just at queue time."""
    org = make_organization()
    survivor = f"{org.pk}/exports/{uuid.uuid4()}/keep.pdf"
    _put(org, survivor)
    factory_for(OrphanedObject).create(
        org, storage_key=f"{org.pk}/exports", is_prefix=True
    )
    report = purge_orphaned_objects(org)
    assert report.failed == 1 and report.deleted == 0
    assert _exists(org, survivor)


def test_deferred_and_failing_entries_do_not_starve_newer_ones() -> None:
    org = make_organization()
    project = factory_for(Project).create(org)
    held = [f"{org.pk}/exports/{uuid.uuid4()}/held{i}.pdf" for i in range(2)]
    for key in held:
        _put(org, key)
        factory_for(OrphanedObject).create(org, storage_key=key)  # oldest entries
    _head_referencing(org, project, *held)  # ... and a saved workspace still needs them
    fresh = f"{org.pk}/exports/{uuid.uuid4()}/fresh.pdf"
    _put(org, fresh)
    factory_for(OrphanedObject).create(org, storage_key=fresh)  # newest entry

    first = purge_orphaned_objects(
        org, limit=2
    )  # looks at the two oldest: both deferred
    assert (first.deleted, first.deferred) == (0, 2)
    second = purge_orphaned_objects(org, limit=2)  # the deferred ones now queue behind
    assert second.deleted == 1
    assert not _exists(org, fresh)
    assert all(_exists(org, key) for key in held)


def _backdate_entry(entry: OrphanedObject, seconds_ago: float) -> None:
    models.QuerySet.update(
        OrphanedObject.objects.filter(pk=entry.pk),
        created_at=datetime.now(UTC) - timedelta(seconds=seconds_ago),
    )


def test_a_directory_purge_only_deletes_objects_written_before_the_debt_was_queued() -> (
    None
):
    """An object written after the debt cannot be owed by it (an in-flight save's upload)."""
    org = make_organization()
    dataset_id = uuid.uuid4()
    directory = keys.dataset_prefix(org, dataset_id).rstrip("/")
    memory = InMemoryBackend()
    with override_backend(memory):
        orphan = f"{directory}/original/{uuid.uuid4().hex}"
        in_flight = f"{directory}/frames/g0000002-aaaaaaaaaaaa.parquet"
        _put(org, orphan)
        _put(org, in_flight)
        entry = factory_for(OrphanedObject).create(
            org, storage_key=directory, is_prefix=True
        )
        debt = datetime.now(UTC)
        models.QuerySet.update(
            OrphanedObject.objects.filter(pk=entry.pk), created_at=debt
        )
        memory.set_last_modified(orphan, debt - timedelta(seconds=30))  # older: owed
        memory.set_last_modified(
            in_flight, debt + timedelta(seconds=30)
        )  # newer: not owed

        report = purge_orphaned_objects(org, min_age_seconds=0)

        assert not _exists(
            org, orphan
        )  # positive twin: a genuinely orphaned object goes
        assert _exists(org, in_flight)  # the later write survives
        # Everything the debt covers is paid; the newer object was never part of it, so the
        # entry is settled rather than left owing forever.
        assert (report.deleted, report.deferred) == (1, 0)
        assert not OrphanedObject.objects.for_organization(org).exists()


def test_a_retired_object_is_only_deleted_once_its_debt_has_aged_past_the_grace_period() -> (
    None
):
    org = make_organization()
    key = f"{org.pk}/exports/{uuid.uuid4()}/retired.pdf"
    _put(org, key)
    entry = factory_for(OrphanedObject).create(org, storage_key=key)

    young = purge_orphaned_objects(org, min_age_seconds=3600)
    assert (young.deleted, young.deferred) == (0, 1)
    assert _exists(org, key)  # a reader that loaded the old workspace may still need it

    _backdate_entry(entry, 7200)
    aged = purge_orphaned_objects(org, min_age_seconds=3600)
    assert aged.deleted == 1
    assert not _exists(org, key)


def test_the_default_grace_period_comes_from_the_settings(settings: Any) -> None:
    org = make_organization()
    key = f"{org.pk}/exports/{uuid.uuid4()}/retired.pdf"
    _put(org, key)
    factory_for(OrphanedObject).create(org, storage_key=key)
    settings.UADAS_STORAGE = {**settings.UADAS_STORAGE, "gc_grace_seconds": 3600}
    assert (
        purge_orphaned_objects(org).deleted == 0
    )  # no argument: the configured hour applies
    assert _exists(org, key)
    settings.UADAS_STORAGE = {**settings.UADAS_STORAGE, "gc_grace_seconds": 0}
    assert purge_orphaned_objects(org).deleted == 1


def test_one_sweep_reads_what_a_workspace_references_once_per_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, other = make_organization(), make_organization()
    for owner in (org, org, org, other):
        key = f"{owner.pk}/exports/{uuid.uuid4()}/x.pdf"
        _put(owner, key)
        factory_for(OrphanedObject).create(owner, storage_key=key)
    calls: list[Any] = []
    real = lifecycle.referenced_keys

    def counting(organization: Any) -> set[str]:
        calls.append(organization)
        return real(organization)

    monkeypatch.setattr(lifecycle, "referenced_keys", counting)
    assert purge_orphaned_objects().deleted == 4
    assert len(calls) == 2  # once per organization, not once per entry


def test_deleting_many_rows_in_one_transaction_schedules_one_sweep_per_organization(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org, other = make_organization(), make_organization()
    records = [_dataset_with_objects(org)[0] for _ in range(3)]
    foreign = _dataset_with_objects(other)[0]
    with (
        django_capture_on_commit_callbacks(execute=False) as callbacks,
        transaction.atomic(),
    ):
        for record in records:
            record.delete()
        foreign.delete()
    assert len(callbacks) == 2  # one for each organization, not one per deleted row
    for callback in callbacks:
        callback()
    assert not OrphanedObject.objects.exists()


def test_a_rolled_back_savepoint_does_not_suppress_the_next_sweep_registration(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    first, _, _ = _dataset_with_objects(org)
    second, _, _ = _dataset_with_objects(org)
    with (
        django_capture_on_commit_callbacks(execute=False) as callbacks,
        transaction.atomic(),
    ):
        with pytest.raises(RuntimeError), transaction.atomic():
            first.delete()
            raise RuntimeError("rolled back: its sweep registration is discarded too")
        second.delete()
    assert (
        len(callbacks) == 1
    )  # `second`'s registration survived the sibling's rollback


@pytest.mark.django_db(transaction=True)
def test_a_non_storage_error_inside_the_commit_hook_never_breaks_the_commit() -> None:
    """``on_commit(..., robust=True)``: an unexpected exception is logged, the delete stands."""
    org = make_organization()
    record, _, _ = _dataset_with_objects(org)
    record_id = record.pk
    faulty = FaultyBackend(InMemoryBackend())
    faulty.fail("list", exc=RuntimeError("injected: not a StorageError"))
    with override_backend(faulty):
        record.delete()  # a real commit; the sweep after it blows up with a RuntimeError
    assert not DatasetRecord.objects.filter(pk=record_id).exists()
    assert OrphanedObject.objects.for_organization(org).exists()  # still owed


def test_the_purge_limit_bounds_one_sweep() -> None:
    org = make_organization()
    for i in range(5):
        key = f"{org.pk}/exports/{uuid.uuid4()}/{i}.pdf"
        _put(org, key)
        factory_for(OrphanedObject).create(org, storage_key=key)
    assert purge_orphaned_objects(org, limit=2).deleted == 2
    assert OrphanedObject.objects.for_organization(org).count() == 3


# --- objects a live workspace still references are never deleted ----------------------


def _head_referencing(org: Any, project: Any, *object_keys: str) -> WorkspaceHead:
    manifest = {
        "format": 1,
        "token": "g0000001-aaaaaaaaaaaa",
        "workspace_db": {"key": object_keys[0], "sha256": "0" * 64, "size": 1},
        "datasets": {
            str(uuid.uuid4()): {"key": k, "sha256": "0" * 64, "size": 1}
            for k in object_keys[1:]
        },
    }
    return factory_for(WorkspaceHead).create(org, project=project, manifest=manifest)


def test_a_dataset_frame_a_saved_workspace_still_references_survives_the_row_delete(
    django_capture_on_commit_callbacks: Capture,
) -> None:
    org = make_organization()
    record, original, frame = _dataset_with_objects(org)
    db_key = keys.workspace_db_key(org, record.project_id, keys.new_save_token(1))
    _put(org, db_key)
    head = _head_referencing(org, record.project, db_key, frame)

    with django_capture_on_commit_callbacks(execute=True):
        record.delete()

    assert not _exists(org, original)  # nothing references it
    assert _exists(
        org, frame
    )  # the head does: deleting it would break the saved workspace
    assert OrphanedObject.objects.for_organization(org).exists()  # still owed
    head.delete()  # the workspace is discarded ...
    purge_orphaned_objects(org)
    assert not _exists(org, frame)  # ... and now the owed deletion completes


# --- reconciliation ------------------------------------------------------------------


def test_reconciliation_reports_rows_without_objects_and_objects_without_rows() -> None:
    org = make_organization()
    present, _, _ = _dataset_with_objects(org)
    missing_row = factory_for(DatasetRecord).create(
        org
    )  # storage_key points at nothing
    stray = f"{org.pk}/exports/{uuid.uuid4()}/stray.pdf"
    _put(org, stray)

    report = reconcile_tenant_storage(org)

    assert [(r.model, r.pk) for r in report.rows_without_objects] == [
        ("workspaces.DatasetRecord", str(missing_row.pk))
    ]
    assert stray in report.objects_without_rows
    # The present dataset's original is referenced by its row; its frame is not referenced
    # by any head, so it is reported as a stray too (the report states facts, it decides nothing).
    assert present.storage_key not in report.objects_without_rows


def test_reconciliation_is_read_only_and_ignores_objects_already_queued_for_deletion() -> (
    None
):
    org = make_organization()
    queued = f"{org.pk}/exports/{uuid.uuid4()}/queued.pdf"
    stray = f"{org.pk}/exports/{uuid.uuid4()}/stray.pdf"
    _put(org, queued)
    _put(org, stray)
    factory_for(OrphanedObject).create(org, storage_key=queued)
    before = (OrphanedObject.objects.count(), get_store(org).head(stray))

    report = reconcile_tenant_storage(org)

    assert report.pending_deletion == [queued]
    assert report.objects_without_rows == [stray]
    assert _exists(org, queued) and _exists(org, stray)  # nothing was deleted
    assert (OrphanedObject.objects.count(), get_store(org).head(stray)) == before


def test_reconciliation_can_skip_objects_younger_than_a_minimum_age() -> None:
    org = make_organization()
    fresh = f"{org.pk}/exports/{uuid.uuid4()}/fresh.pdf"
    _put(org, fresh)
    assert (
        reconcile_tenant_storage(org, min_age_seconds=3600).objects_without_rows == []
    )
    assert reconcile_tenant_storage(org, min_age_seconds=0).objects_without_rows == [
        fresh
    ]


def test_reconciliation_only_looks_at_its_own_organization() -> None:
    org_a, org_b = make_organization(), make_organization()
    _put(org_b, f"{org_b.pk}/exports/{uuid.uuid4()}/b.pdf")
    factory_for(DatasetRecord).create(org_b)
    report = reconcile_tenant_storage(org_a)
    assert report.objects_without_rows == [] and report.rows_without_objects == []
    assert keys.organization_prefix(org_a) not in " ".join(report.objects_without_rows)
