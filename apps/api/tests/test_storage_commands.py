# File: apps/api/tests/test_storage_commands.py
"""The two operator commands over the storage lifecycle (3.4).

Why commands: the orphan queue needs a sweeper and the reconciliation a way to be read, and
both must work from cron or a shell without a request. ``purge_orphaned_objects`` pays owed
deletions; ``reconcile_storage`` is strictly read-only and exits non-zero when it finds
something, so a scheduled run can alert.
"""

from __future__ import annotations

import io
import json
import uuid
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from factories import factory_for, make_organization

from uadas_api.storage.models import OrphanedObject
from uadas_api.storage.store import get_store
from uadas_api.workspaces.models import DatasetRecord

pytestmark = pytest.mark.django_db


def _put(org: Any, key: str) -> None:
    get_store(org).put(
        key,
        b"x",
        content_type="application/octet-stream",
        allowed_content_types={"application/octet-stream"},
    )


def test_purge_command_deletes_owed_objects_and_reports_the_counts() -> None:
    org = make_organization()
    key = f"{org.pk}/exports/{uuid.uuid4()}/a.pdf"
    _put(org, key)
    factory_for(OrphanedObject).create(org, storage_key=key)
    out = io.StringIO()

    call_command("purge_orphaned_objects", stdout=out)

    assert "deleted=1" in out.getvalue() and "failed=0" in out.getvalue()
    assert not get_store(org).exists(key)
    assert not OrphanedObject.objects.for_organization(org).exists()


def test_purge_command_honours_a_minimum_age_and_rejects_a_negative_one() -> None:
    org = make_organization()
    key = f"{org.pk}/exports/{uuid.uuid4()}/a.pdf"
    _put(org, key)
    factory_for(OrphanedObject).create(org, storage_key=key)
    out = io.StringIO()

    call_command("purge_orphaned_objects", min_age=3600, stdout=out)
    assert "deleted=0" in out.getvalue() and "deferred=1" in out.getvalue()
    assert get_store(org).exists(
        key
    )  # too young: a reader or an in-flight save may need it

    with pytest.raises(CommandError, match="min-age"):
        call_command("purge_orphaned_objects", min_age=-1)

    call_command("purge_orphaned_objects", min_age=0, stdout=io.StringIO())
    assert not get_store(org).exists(
        key
    )  # twin: aged enough (zero grace) it is deleted


def test_purge_command_can_be_limited_to_one_organization() -> None:
    mine, other = make_organization(), make_organization()
    keys = {}
    for org in (mine, other):
        keys[org.pk] = f"{org.pk}/exports/{uuid.uuid4()}/a.pdf"
        _put(org, keys[org.pk])
        factory_for(OrphanedObject).create(org, storage_key=keys[org.pk])

    call_command(
        "purge_orphaned_objects", organization=str(mine.pk), stdout=io.StringIO()
    )

    assert not get_store(mine).exists(keys[mine.pk])
    assert get_store(other).exists(keys[other.pk])  # untouched


def test_purge_command_rejects_a_malformed_organization_id() -> None:
    with pytest.raises(CommandError, match="organization"):
        call_command("purge_orphaned_objects", organization="not-a-uuid")


def test_purge_command_exits_non_zero_when_something_could_not_be_deleted() -> None:
    org = make_organization()
    entry = factory_for(OrphanedObject).create(org)
    # An entry that the facade refuses (a key of another tenant) can never be paid.
    from django.db import models

    models.QuerySet.update(
        OrphanedObject.objects.filter(pk=entry.pk),
        storage_key=f"{uuid.uuid4()}/exports/x.pdf",
    )
    with pytest.raises(CommandError, match="failed"):
        call_command(
            "purge_orphaned_objects", organization=str(org.pk), stdout=io.StringIO()
        )


def test_reconcile_command_prints_a_json_report_and_changes_nothing() -> None:
    org = make_organization()
    stray = f"{org.pk}/exports/{uuid.uuid4()}/stray.pdf"
    _put(org, stray)
    out = io.StringIO()

    with pytest.raises(CommandError, match="discrepanc"):
        call_command("reconcile_storage", str(org.pk), stdout=out)

    report = json.loads(out.getvalue())
    assert report["objects_without_rows"] == [stray]
    assert report["rows_without_objects"] == []
    assert get_store(org).exists(stray)  # read-only


def test_reconcile_command_is_quiet_and_succeeds_when_everything_agrees() -> None:
    org = make_organization()
    record = factory_for(DatasetRecord).create(org)
    _put(org, record.storage_key)
    out = io.StringIO()

    call_command("reconcile_storage", str(org.pk), stdout=out)  # exit 0

    report = json.loads(out.getvalue())
    assert report == {
        "rows_without_objects": [],
        "objects_without_rows": [],
        "pending_deletion": [],
    }


def test_reconcile_command_honours_the_minimum_age() -> None:
    org = make_organization()
    _put(org, f"{org.pk}/exports/{uuid.uuid4()}/fresh.pdf")
    call_command("reconcile_storage", str(org.pk), min_age=3600, stdout=io.StringIO())
