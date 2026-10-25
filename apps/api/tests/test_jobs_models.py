# File: apps/api/tests/test_jobs_models.py
"""The ``Job`` row: constraints, the state machine, and terminal immutability.

Why these tests exist beyond the discovery-based tenant harness (which already covers
organization scoping, uniqueness per organization and FK isolation for ``Job``): the state
machine is the property every worker, sweeper and cancel request leans on, and it has to hold
on *every* write path -- ``save()``, ``queryset.update()`` and the database's own check
constraints -- not just the one a service happens to use.

Every refusal has a positive twin in the same test (the legal move next to the illegal one).
"""

from __future__ import annotations

import itertools
import uuid
from typing import Any

import pytest
from django.db import IntegrityError, transaction
from factories import factory_for, make_organization, make_user

from uadas_api.jobs.choices import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    JobKind,
    JobStatus,
    can_transition,
    sources_of,
)
from uadas_api.jobs.errors import JobTransitionError
from uadas_api.jobs.models import Job, allow_status_write

pytestmark = pytest.mark.django_db

STATUSES = [s.value for s in JobStatus]


def make_job(**kw: Any) -> Job:
    organization = kw.pop("organization", None) or make_organization()
    job = factory_for(Job).create(organization, **kw)
    assert isinstance(job, Job)
    return job


# ------------------------------------------------------------- the table of moves


def test_the_transition_table_is_closed_over_the_statuses() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(STATUSES)
    for targets in ALLOWED_TRANSITIONS.values():
        assert targets <= set(STATUSES)


def test_terminal_statuses_are_exactly_those_with_no_way_out() -> None:
    assert {s for s, to in ALLOWED_TRANSITIONS.items() if not to} == TERMINAL_STATUSES
    assert {"succeeded", "failed", "cancelled"} == TERMINAL_STATUSES


def test_sources_of_is_the_inverse_of_the_table() -> None:
    for new in STATUSES:
        assert sources_of(new) == {s for s in STATUSES if can_transition(s, new)}
    assert sources_of("queued") == {"running"}
    assert sources_of("running") == {"queued"}


# ----------------------------------------------------------------- save() guards


@pytest.mark.parametrize(
    ("old", "new"), list(itertools.product(STATUSES, STATUSES)), ids=lambda v: str(v)
)
def test_save_allows_exactly_the_legal_transitions(old: str, new: str) -> None:
    job = make_job()
    _force_status(job, old)
    job = Job.objects.get(pk=job.pk)
    job.status = new
    _complete_for_status(job, new)
    if old == new:
        # not a transition: fine for a live job, forbidden for a terminal one (next test)
        if old in TERMINAL_STATUSES:
            with pytest.raises(JobTransitionError):
                job.save()
        else:
            job.save()
    elif can_transition(old, new):
        job.save()
        assert Job.objects.get(pk=job.pk).status == new
    else:
        with pytest.raises(JobTransitionError):
            job.save()
        assert Job.objects.get(pk=job.pk).status == old


def _force_status(job: Job, status: str) -> None:
    """Put a row in ``status`` through the one sanctioned door, with consistent columns."""
    fields: dict[str, Any] = {"status": status}
    if status in TERMINAL_STATUSES:
        fields["finished_at"] = job.created_at
    if status == "failed":
        fields["error_code"] = "internal_error"
        fields["error_message"] = "x"
    with allow_status_write():
        Job.objects.filter(pk=job.pk).update(**fields)


def _complete_for_status(job: Job, status: str) -> None:
    """Fill the columns a row in ``status`` must carry so the DB checks are not the failure."""
    if status in TERMINAL_STATUSES:
        job.finished_at = job.created_at
    if status == "failed":
        job.error_code = "internal_error"
        job.error_message = "x"


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_a_terminal_job_cannot_be_changed_in_any_field(status: str) -> None:
    job = make_job()
    _force_status(job, status)
    job = Job.objects.get(pk=job.pk)
    job.progress = 50
    job.message = "tampered"
    with pytest.raises(JobTransitionError):
        job.save()
    with pytest.raises(JobTransitionError):
        job.save(update_fields=["message"])
    stored = Job.objects.get(pk=job.pk)
    assert (stored.progress, stored.message) == (0, "")


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_a_queryset_update_cannot_touch_a_terminal_job(status: str) -> None:
    job = make_job()
    _force_status(job, status)
    assert Job.objects.filter(pk=job.pk).update(progress=77, message="tampered") == 0
    assert Job.objects.get(pk=job.pk).progress == 0
    # the positive twin: the same update on a live job works
    live = make_job()
    assert Job.objects.filter(pk=live.pk).update(progress=77, message="ok") == 1


def test_a_queryset_update_cannot_set_status_outside_the_sanctioned_door() -> None:
    job = make_job()
    with pytest.raises(JobTransitionError):
        Job.objects.filter(pk=job.pk).update(status="running")
    with pytest.raises(JobTransitionError):
        Job.objects.filter(pk=job.pk).bulk_update([job], ["status"])
    with allow_status_write():
        assert Job.objects.filter(pk=job.pk).update(status="running") == 1


def test_the_status_door_is_closed_again_after_the_block() -> None:
    job = make_job()
    with allow_status_write():
        pass
    with pytest.raises(JobTransitionError):
        Job.objects.filter(pk=job.pk).update(status="running")


def test_bulk_create_with_a_non_initial_status_is_refused() -> None:
    org = make_organization()
    project_row = make_job(organization=org)
    bad = factory_for(Job).build(org, status="succeeded", project=project_row.project)
    good = factory_for(Job).build(org, project=project_row.project)
    assert isinstance(bad, Job) and isinstance(good, Job)
    with pytest.raises(JobTransitionError):
        Job.objects.bulk_create([bad])
    Job.objects.bulk_create([good])
    assert Job.objects.filter(pk=good.pk).exists()


def test_a_new_job_must_start_queued() -> None:
    org = make_organization()
    with pytest.raises(JobTransitionError):
        factory_for(Job).create(org, status="running")
    assert make_job(organization=org).status == "queued"


# ------------------------------------------------------- database check constraints


def _raw_update(job: Job, **fields: Any) -> None:
    with transaction.atomic(), allow_status_write():
        Job.objects.filter(pk=job.pk).update(**fields)


@pytest.mark.parametrize("bad", [-1, 101])
def test_progress_is_bounded_by_the_database(bad: int) -> None:
    job = make_job()
    with pytest.raises(IntegrityError):
        _raw_update(job, progress=bad)
    _raw_update(job, progress=100)
    _raw_update(job, progress=0)


def test_a_failed_job_needs_an_error_code_and_only_a_failed_job_may_have_one() -> None:
    job = make_job()
    with pytest.raises(IntegrityError):
        _raw_update(job, status="failed", finished_at=job.created_at, error_code="")
    with pytest.raises(IntegrityError):
        _raw_update(job, error_code="parse_error")  # still queued
    _raw_update(
        job, status="failed", finished_at=job.created_at, error_code="parse_error"
    )


def test_a_terminal_job_needs_a_finish_time_and_a_live_one_must_not_have_one() -> None:
    job = make_job()
    with pytest.raises(IntegrityError):
        _raw_update(job, status="succeeded")
    with pytest.raises(IntegrityError):
        _raw_update(job, finished_at=job.created_at)
    _raw_update(job, status="succeeded", finished_at=job.created_at)


def test_status_and_kind_are_closed_sets_in_the_database() -> None:
    job = make_job()
    with pytest.raises(IntegrityError):
        _raw_update(job, status="exploded")
    other = make_job()
    with pytest.raises(IntegrityError), transaction.atomic():
        Job.objects.filter(pk=other.pk).update(kind="rm_rf")
    assert JobKind.INGEST_DATASET.value == Job.objects.get(pk=other.pk).kind


def test_the_attempt_counter_cannot_be_negative() -> None:
    job = make_job()
    with pytest.raises(IntegrityError):
        _raw_update(job, attempts=-1)


# --------------------------------------------------------------- idempotency key


def test_an_idempotency_key_is_unique_per_organization_and_kind() -> None:
    org_a, org_b = make_organization(), make_organization()
    first = make_job(organization=org_a, idempotency_key="same-key")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_job(organization=org_a, idempotency_key="same-key")
    other_org = make_job(
        organization=org_b, idempotency_key="same-key"
    )  # positive twin
    assert other_org.pk != first.pk


def test_an_idempotency_key_is_required() -> None:
    from django.core.exceptions import ValidationError

    job = factory_for(Job).build(make_organization(), idempotency_key="")
    with pytest.raises(ValidationError):
        job.full_clean()


# --------------------------------------------------------------- misc invariants


def test_the_job_belongs_to_a_project_of_its_organization() -> None:
    from uadas_api.tenancy import TenantIsolationError
    from uadas_api.workspaces.models import Project

    org_a, org_b = make_organization(), make_organization()
    foreign = Project.objects.create(organization=org_b, name="theirs")
    with pytest.raises(TenantIsolationError):
        factory_for(Job).create(org_a, project=foreign)


def test_deleting_the_creator_keeps_the_job() -> None:
    user = make_user()
    job = make_job(created_by=user)
    user.delete()
    assert Job.objects.get(pk=job.pk).created_by_id is None


def test_str_names_no_parameters() -> None:
    job = make_job(
        params={"original_key": "org/secret/path", "filename": "salaries.csv"}
    )
    text = str(job)
    assert "salaries" not in text and "secret" not in text
    assert str(job.pk) in text


def test_ids_are_uuids() -> None:
    assert isinstance(make_job().pk, uuid.UUID)
