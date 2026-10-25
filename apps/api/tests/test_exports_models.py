# File: apps/api/tests/test_exports_models.py
"""``Report``: lifecycle and the (conditionally blank) storage key.

Why: a report exists as a request before its file does, so ``storage_key`` may be empty
while ``pending``/``failed`` -- the one deliberate difference from ``DatasetRecord`` --
but a ``ready`` report must name an object, and any key that is present must sit under the
organization's prefix. The generic prefix checks run for ``Report`` in the tenant harness;
these tests pin the lifecycle rule and the blank handling.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from factories import factory_for, make_organization

from uadas_api.exports.choices import ReportFormat, ReportStatus
from uadas_api.exports.models import Report

pytestmark = pytest.mark.django_db


def test_a_new_report_is_pending_with_no_object_yet() -> None:
    org = make_organization()
    report = factory_for(Report).create(org)
    assert report.status == ReportStatus.PENDING
    assert report.storage_key == ""


def test_a_ready_report_with_a_prefixed_key_is_accepted() -> None:
    org = make_organization()
    report = factory_for(Report).create(
        org,
        status=ReportStatus.READY,
        format=ReportFormat.HTML,
        storage_key=f"{org.pk}/reports/r.html",
    )
    assert Report.objects.get(pk=report.pk).status == "ready"


def test_a_ready_report_must_name_its_object() -> None:
    org = make_organization()
    report = factory_for(Report).build(org, status=ReportStatus.READY, storage_key="")
    with pytest.raises(IntegrityError), transaction.atomic():
        report.save()


def test_a_present_key_must_use_the_organization_prefix() -> None:
    org = make_organization()
    report = factory_for(Report).build(org, storage_key="reports/r.pdf")
    with pytest.raises(ValidationError) as excinfo:
        report.save()
    assert "storage_key" in excinfo.value.error_dict


def test_format_and_status_are_closed_sets_enforced_by_the_database() -> None:
    org = make_organization()
    for field, value in (("format", "exe"), ("status", "unknown")):
        report = factory_for(Report).build(org, **{field: value})
        with pytest.raises(IntegrityError), transaction.atomic():
            report.save()


def test_a_project_that_owns_a_report_cannot_be_deleted() -> None:
    org = make_organization()
    report = factory_for(Report).create(org)
    with pytest.raises(ProtectedError):
        report.project.delete()
