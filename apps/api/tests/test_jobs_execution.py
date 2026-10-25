# File: apps/api/tests/test_jobs_execution.py
"""What a worker does with a job id: claim, re-check, run, commit, classify.

Why: this is the code a redelivered, duplicated or poisoned message meets, so the properties
that matter are about what *does not* happen -- a finished job is not run again, a job another
worker holds is not run twice, a job whose creator lost their role is not run at all, a handler's
side effects do not outlive a job that was cancelled or taken over, an exception's text never
reaches the row or the log.

Handlers here are fakes registered with ``override_handler``; the real ingest handler is covered
by ``test_ingest*.py``. Each guard has its positive twin (the same job, allowed, runs).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from factories import make_organization, make_user

from uadas_api.accounts.models import Membership, Role
from uadas_api.jobs import services
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.config import get_config
from uadas_api.jobs.errors import JobError, JobErrorCode, message_for
from uadas_api.jobs.execution import Outcome, OutcomeKind, execute_job
from uadas_api.jobs.models import Job
from uadas_api.jobs.registry import Completion, JobContext, JobHandler, override_handler
from uadas_api.storage.errors import StorageUnavailableError
from uadas_api.workspaces.models import Project

pytestmark = pytest.mark.django_db

KIND = JobKind.INGEST_DATASET.value
Run = Callable[[JobContext], Completion]


class Recorder:
    """A handler that records its calls and does what ``behaviour`` says."""

    def __init__(self, behaviour: Run | None = None) -> None:
        self.calls: list[JobContext] = []
        self.behaviour = behaviour or (lambda ctx: Completion(result={"ok": True}))

    def handler(self) -> JobHandler:
        def run(ctx: JobContext) -> Completion:
            self.calls.append(ctx)
            return self.behaviour(ctx)

        return JobHandler(validate_params=lambda org, p: dict(p), run=run)


def setup_job(role: Role = Role.EDITOR) -> tuple[Any, Any, Project, Job]:
    org = make_organization()
    user = make_user()
    Membership.objects.create(user=user, organization=org, role=role)
    project = Project.objects.create(organization=org, name=f"p-{uuid.uuid4().hex[:6]}")
    with override_handler(KIND, Recorder().handler()):
        job = services.create_job(
            project=project, actor=user, kind=KIND, params={"x": 1}
        ).job
    return org, user, project, job


def run(job: Job, recorder: Recorder) -> Outcome:
    with override_handler(KIND, recorder.handler()):
        return execute_job(job.pk)


# --------------------------------------------------------------------- success


def test_a_job_runs_once_and_ends_succeeded_with_its_result() -> None:
    org, user, project, job = setup_job()
    recorder = Recorder(lambda ctx: Completion(result={"dataset_id": "d-1", "rows": 3}))
    outcome = run(job, recorder)
    assert outcome == Outcome(OutcomeKind.DONE)
    job.refresh_from_db()
    assert job.status == "succeeded"
    assert (job.progress, job.attempts, job.result) == (
        100,
        1,
        {"dataset_id": "d-1", "rows": 3},
    )
    assert job.finished_at is not None and job.error_code == ""
    assert len(recorder.calls) == 1


def test_the_handler_is_given_rows_resolved_from_the_job_not_from_the_message() -> None:
    org, user, project, job = setup_job()
    recorder = Recorder()
    run(job, recorder)
    ctx = recorder.calls[0]
    assert (
        ctx.organization.pk,
        ctx.project.pk,
        ctx.actor.pk if ctx.actor else None,
    ) == (
        org.pk,
        project.pk,
        user.pk,
    )
    assert dict(ctx.params) == {"x": 1}


def test_progress_reported_by_the_handler_is_visible_on_the_row() -> None:
    _, _, _, job = setup_job()
    seen: list[int] = []

    def behaviour(ctx: JobContext) -> Completion:
        ctx.report(40, "Halfway", force=True)
        seen.append(Job.objects.get(pk=ctx.job.pk).progress)
        return Completion(result={})

    run(job, Recorder(behaviour))
    assert seen == [40]


# ------------------------------------------------------------------ redelivery


def test_a_finished_job_is_not_run_again_when_the_message_is_redelivered() -> None:
    _, _, _, job = setup_job()
    recorder = Recorder()
    assert run(job, recorder).kind is OutcomeKind.DONE
    assert run(job, recorder).kind is OutcomeKind.SKIPPED
    assert run(job, recorder).kind is OutcomeKind.SKIPPED
    assert len(recorder.calls) == 1
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("succeeded", 1)


def test_a_job_another_worker_is_running_is_not_run_a_second_time() -> None:
    _, _, _, job = setup_job()
    assert services.claim(job.pk, now=timezone.now(), stale_after=120) is not None
    recorder = Recorder()
    assert run(job, recorder).kind is OutcomeKind.SKIPPED
    assert recorder.calls == []
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("running", 1)


def test_a_job_whose_worker_died_is_taken_over_and_finished() -> None:
    _, _, _, job = setup_job()
    services.claim(
        job.pk, now=timezone.now() - timedelta(seconds=1000), stale_after=120
    )
    recorder = Recorder()
    assert run(job, recorder).kind is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("succeeded", 2)
    assert len(recorder.calls) == 1


def test_a_missing_job_is_skipped() -> None:
    assert execute_job(uuid.uuid4()).kind is OutcomeKind.SKIPPED


def test_a_malformed_job_id_is_skipped_not_a_crash() -> None:
    assert execute_job("not-a-uuid").kind is OutcomeKind.SKIPPED


def test_a_poison_job_stops_after_the_attempt_limit_without_running() -> None:
    _, _, _, job = setup_job()
    limit = get_config().max_attempts
    Job.objects.filter(pk=job.pk).update(
        attempts=limit
    )  # already redelivered `limit` times
    recorder = Recorder()
    assert run(job, recorder).kind is OutcomeKind.DONE
    assert recorder.calls == []
    job.refresh_from_db()
    assert (job.status, job.error_code) == (
        "failed",
        JobErrorCode.TOO_MANY_ATTEMPTS.value,
    )
    assert job.error_message == message_for("too_many_attempts")


# ----------------------------------------------------------------- cancellation


def test_a_cancel_requested_before_the_worker_starts_is_honoured_without_running() -> (
    None
):
    org, user, _, job = setup_job()
    services.claim(
        job.pk, now=timezone.now() - timedelta(seconds=1000), stale_after=120
    )
    services.request_cancel(
        organization=org, job_id=job.pk, actor=user
    )  # flag on a running job
    recorder = Recorder()
    assert run(job, recorder).kind is OutcomeKind.DONE
    assert recorder.calls == []
    job.refresh_from_db()
    assert job.status == "cancelled"


def test_a_cancel_at_a_checkpoint_stops_the_handler_and_runs_its_cleanup() -> None:
    org, user, _, job = setup_job()
    cleaned: list[str] = []

    def behaviour(ctx: JobContext) -> Completion:
        services.request_cancel(organization=org, job_id=job.pk, actor=user)
        ctx.check_cancelled()  # raises JobCancelledError
        return Completion(
            result={"unreachable": True}, cleanup=lambda: cleaned.append("x")
        )

    recorder = Recorder(behaviour)
    assert run(job, recorder).kind is OutcomeKind.DONE
    job.refresh_from_db()
    assert job.status == "cancelled" and job.result == {}
    assert cleaned == []  # the handler never returned a completion to clean up


def test_a_cancel_that_arrives_after_the_work_is_done_still_cancels_and_cleans_up() -> (
    None
):
    org, user, project, job = setup_job()
    cleaned: list[str] = []
    created: list[str] = []

    def behaviour(ctx: JobContext) -> Completion:
        # the work is finished; the user cancels before the commit step
        services.request_cancel(organization=org, job_id=job.pk, actor=user)
        return Completion(
            result={"r": 1},
            commit=lambda: created.append("row"),
            cleanup=lambda: cleaned.append("object"),
        )

    run(job, Recorder(behaviour))
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert created == [] and cleaned == ["object"]


# ----------------------------------------------------- the commit is all-or-nothing


def test_a_rows_the_job_creates_commit_with_the_success_state() -> None:
    org, user, project, job = setup_job()

    def behaviour(ctx: JobContext) -> Completion:
        return Completion(
            result={"made": "Made by job"},
            commit=lambda: Project.objects.create(organization=org, name="Made by job"),
        )

    run(job, Recorder(behaviour))
    job.refresh_from_db()
    assert job.status == "succeeded"
    assert Project.objects.filter(organization=org, name="Made by job").exists()


def test_a_job_that_lost_its_claim_rolls_back_its_rows_and_cleans_up() -> None:
    org, user, project, job = setup_job()
    cleaned: list[str] = []

    def behaviour(ctx: JobContext) -> Completion:
        # the sweeper gave up on this job while the handler was working
        from uadas_api.jobs.models import allow_status_write

        with allow_status_write():
            Job.objects.filter(pk=job.pk).update(
                status="failed",
                finished_at=timezone.now(),
                error_code=JobErrorCode.WORKER_LOST.value,
            )
        return Completion(
            result={"r": 1},
            commit=lambda: Project.objects.create(
                organization=org, name="Must not exist"
            ),
            cleanup=lambda: cleaned.append("object"),
        )

    outcome = run(job, Recorder(behaviour))
    assert outcome.kind is OutcomeKind.SKIPPED
    assert not Project.objects.filter(name="Must not exist").exists()
    assert cleaned == ["object"]
    job.refresh_from_db()
    assert (job.status, job.error_code) == (
        "failed",
        "worker_lost",
    )  # the sweeper's verdict


def test_a_commit_step_that_raises_fails_the_job_and_cleans_up_with_no_rows_left() -> (
    None
):
    org, user, project, job = setup_job()
    cleaned: list[str] = []

    def commit() -> None:
        Project.objects.create(organization=org, name="Half done")
        raise RuntimeError("boom: /srv/secret/path")

    def behaviour(ctx: JobContext) -> Completion:
        return Completion(
            result={"r": 1}, commit=commit, cleanup=lambda: cleaned.append("o")
        )

    run(job, Recorder(behaviour))
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "internal_error")
    assert not Project.objects.filter(name="Half done").exists()  # rolled back
    assert cleaned == ["o"]


# ---------------------------------------------------------------------- failures


def test_a_handlers_coded_failure_is_stored_with_its_fixed_sentence() -> None:
    _, _, _, job = setup_job()
    recorder = Recorder(
        lambda ctx: (_ for _ in ()).throw(JobError(JobErrorCode.PARSE_ERROR))
    )
    assert run(job, recorder).kind is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "parse_error")
    assert job.error_message == message_for("parse_error")
    assert job.attempts == 1  # not retried: retrying a bad file helps nobody


def test_an_unexpected_exceptions_text_never_reaches_the_row_or_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, _, _, job = setup_job()
    secret = "C:/tenants/acme/salaries.csv password=hunter2 ssn=123-45-6789"

    def explode(ctx: JobContext) -> Completion:
        raise RuntimeError(secret)

    with caplog.at_level(logging.DEBUG):
        run(job, Recorder(explode))
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "internal_error")
    stored = " ".join(
        str(v) for v in (job.error_message, job.message, job.result, job.params)
    )
    logged = caplog.text
    for leak in ("hunter2", "acme", "salaries", "123-45-6789"):
        assert leak not in stored, f"{leak} reached the job row"
        assert leak not in logged, f"{leak} reached the log"
    assert (
        "RuntimeError" in logged
    )  # the operator still learns what kind of failure it was


def test_a_non_json_or_oversized_result_fails_the_job_instead_of_crashing_the_worker() -> (
    None
):
    _, _, _, job = setup_job()
    run(job, Recorder(lambda ctx: Completion(result={"bad": {1, 2}})))
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "internal_error")
    _, _, _, other = setup_job()
    run(other, Recorder(lambda ctx: Completion(result={"big": "x" * 40_000})))
    other.refresh_from_db()
    assert other.status == "failed"


def test_a_handler_that_lost_its_job_stops_without_writing() -> None:
    from uadas_api.jobs.errors import JobLostError

    _, _, _, job = setup_job()

    def behaviour(ctx: JobContext) -> Completion:
        raise JobLostError

    assert run(job, Recorder(behaviour)).kind is OutcomeKind.SKIPPED
    job.refresh_from_db()
    assert job.status == "running"  # not ours to change any more


# ----------------------------------------------------------------------- retries


def test_a_retryable_failure_puts_the_job_back_and_asks_for_a_delayed_retry() -> None:
    _, _, _, job = setup_job()
    recorder = Recorder(
        lambda ctx: (_ for _ in ()).throw(StorageUnavailableError("down"))
    )
    outcome = run(job, recorder)
    assert outcome.kind is OutcomeKind.RETRY
    cfg = get_config()
    assert 0 < outcome.delay <= cfg.retry_backoff_max
    job.refresh_from_db()
    assert (job.status, job.attempts, job.error_code) == ("queued", 1, "")
    assert job.finished_at is None


def test_the_retry_succeeds_when_the_cause_has_gone() -> None:
    _, _, _, job = setup_job()
    state = {"fail": True}

    def behaviour(ctx: JobContext) -> Completion:
        if state["fail"]:
            raise StorageUnavailableError("down")
        return Completion(result={"ok": True})

    recorder = Recorder(behaviour)
    assert run(job, recorder).kind is OutcomeKind.RETRY
    state["fail"] = False
    assert run(job, recorder).kind is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("succeeded", 2)


def test_retries_are_bounded_and_the_last_failure_is_final() -> None:
    _, _, _, job = setup_job()
    recorder = Recorder(
        lambda ctx: (_ for _ in ()).throw(StorageUnavailableError("down"))
    )
    limit = get_config().max_attempts
    outcomes = [run(job, recorder) for _ in range(limit)]
    assert [o.kind for o in outcomes] == [OutcomeKind.RETRY] * (limit - 1) + [
        OutcomeKind.DONE
    ]
    job.refresh_from_db()
    assert (job.status, job.attempts, job.error_code) == (
        "failed",
        limit,
        "storage_unavailable",
    )
    assert (
        run(job, recorder).kind is OutcomeKind.SKIPPED
    )  # and a redelivery changes nothing


def test_retry_delays_grow_and_are_capped() -> None:
    from dataclasses import replace

    from uadas_api.jobs.config import retry_delay

    cfg = replace(get_config(), retry_backoff_base=5, retry_backoff_max=60)
    delays = [retry_delay(n, cfg, jitter=lambda: 1.0) for n in range(1, 8)]
    assert delays[:4] == [5.0, 10.0, 20.0, 40.0]
    assert delays[4:] == [60.0, 60.0, 60.0]
    low = retry_delay(3, cfg, jitter=lambda: 0.0)
    assert low == 10.0  # jitter scales into 50-100 % of the nominal delay
    assert all(retry_delay(n, cfg) <= 60.0 for n in range(1, 50))


# ----------------------------------------------------------------- abandon hook


def run_with_abandon(job: Job, behaviour: Run, abandoned: list[Any]) -> Outcome:
    def run_it(ctx: JobContext) -> Completion:
        return behaviour(ctx)

    handler = JobHandler(
        validate_params=lambda org, p: dict(p),
        run=run_it,
        on_abandon=lambda j: abandoned.append(j.pk),
    )
    with override_handler(KIND, handler):
        return execute_job(job.pk)


def test_the_abandon_hook_runs_when_a_job_fails_for_good() -> None:
    _, _, _, job = setup_job()
    abandoned: list[Any] = []
    run_with_abandon(
        job,
        lambda ctx: (_ for _ in ()).throw(JobError(JobErrorCode.PARSE_ERROR)),
        abandoned,
    )
    assert abandoned == [job.pk]


def test_the_abandon_hook_does_not_run_on_success_or_on_a_retry() -> None:
    _, _, _, job = setup_job()
    abandoned: list[Any] = []
    run_with_abandon(job, lambda ctx: Completion(result={}), abandoned)
    _, _, _, other = setup_job()
    outcome = run_with_abandon(
        other,
        lambda ctx: (_ for _ in ()).throw(StorageUnavailableError("down")),
        abandoned,
    )
    assert outcome.kind is OutcomeKind.RETRY
    assert abandoned == []


def test_the_abandon_hook_runs_when_a_job_is_cancelled_and_when_it_is_poisoned() -> (
    None
):
    org, user, _, job = setup_job()

    def cancel_midway(ctx: JobContext) -> Completion:
        services.request_cancel(organization=org, job_id=job.pk, actor=user)
        ctx.check_cancelled()
        return Completion(result={})

    abandoned: list[Any] = []
    run_with_abandon(job, cancel_midway, abandoned)
    _, _, _, poisoned = setup_job()
    Job.objects.filter(pk=poisoned.pk).update(attempts=get_config().max_attempts)
    run_with_abandon(poisoned, lambda ctx: Completion(result={}), abandoned)
    assert abandoned == [job.pk, poisoned.pk]


def test_a_failing_abandon_hook_cannot_change_the_jobs_outcome() -> None:
    _, _, _, job = setup_job()

    def explode(j: Job) -> None:
        raise RuntimeError("housekeeping broke")

    handler = JobHandler(
        validate_params=lambda org, p: dict(p),
        run=lambda ctx: (_ for _ in ()).throw(JobError(JobErrorCode.PARSE_ERROR)),
        on_abandon=explode,
    )
    with override_handler(KIND, handler):
        assert execute_job(job.pk).kind is OutcomeKind.DONE
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "parse_error")


# --------------------------------------------------------------------- ownership


def test_a_creator_who_lost_their_membership_cannot_get_the_job_run() -> None:
    org, user, _, job = setup_job()
    Membership.objects.filter(user=user, organization=org).delete()
    recorder = Recorder()
    assert run(job, recorder).kind is OutcomeKind.DONE
    assert recorder.calls == []
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", "forbidden")


def test_a_creator_demoted_to_viewer_cannot_get_the_job_run() -> None:
    org, user, _, job = setup_job()
    Membership.objects.filter(user=user, organization=org).update(role=Role.VIEWER)
    recorder = Recorder()
    run(job, recorder)
    assert recorder.calls == []
    job.refresh_from_db()
    assert job.error_code == "forbidden"


def test_a_deactivated_creator_cannot_get_the_job_run() -> None:
    _, user, _, job = setup_job()
    user.is_active = False
    user.save()
    recorder = Recorder()
    run(job, recorder)
    assert recorder.calls == []
    job.refresh_from_db()
    assert job.error_code == "forbidden"


def test_a_job_whose_creator_was_deleted_cannot_run() -> None:
    _, user, _, job = setup_job()
    user.delete()
    recorder = Recorder()
    run(job, recorder)
    assert recorder.calls == []
    job.refresh_from_db()
    assert (job.created_by_id, job.error_code) == (None, "forbidden")


def test_a_role_that_still_holds_the_capability_runs_fine() -> None:
    for role in (Role.EDITOR, Role.ADMIN, Role.OWNER):
        _, _, _, job = setup_job(role)
        recorder = Recorder()
        run(job, recorder)
        assert len(recorder.calls) == 1, role
