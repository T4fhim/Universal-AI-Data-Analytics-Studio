# File: apps/api/tests/test_jobs_hardening.py
"""Fencing, heartbeats, the sweeper's cleanup, retry timing and terminal immutability (3.5 review).

Why this file exists: a Django/Celery review found that the job layer was correct for *one* worker
and wrong for two. Two workers is not exotic -- it is what a stale heartbeat, a redelivered message or
a slow parse produces -- so each finding is reproduced with two interleaved workers and has its
accepted twin (the live worker, or the sole worker, does the same thing and succeeds):

* **Fencing (J2).** ``attempts`` is incremented by every claim; every worker-side write is
  conditional on the attempt the worker was given, so a superseded worker can no longer fail, requeue,
  cancel, report progress for or commit the run that replaced it.
* **Heartbeat for the whole run (J1).** A thread beats while the handler is busy and silent
  (a 100 MB download, a 120 s parse); a worker that lost its claim learns it from the failed beat.
* **The sweeper cleans up (J3).** A job it fails or cancels gets its kind's abandon hook, so the
  upload and any staged frame reach the deletion outbox.
* **A retry waits (J4).** ``not_before`` keeps the lost-message sweeper from re-sending a job whose
  retry is merely backing off.
* **Terminal means terminal (J7).** A stale in-memory instance cannot resurrect a finished job.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from factories import make_organization, make_user

from uadas_api.accounts.models import Membership, Role
from uadas_api.jobs import queue as job_queue
from uadas_api.jobs import services
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.config import get_config
from uadas_api.jobs.errors import JobErrorCode, JobLostError, JobTransitionError
from uadas_api.jobs.execution import OutcomeKind, execute_job
from uadas_api.jobs.models import Job, allow_status_write
from uadas_api.jobs.progress import Heartbeat, ProgressSink
from uadas_api.jobs.registry import (
    Completion,
    JobContext,
    JobHandler,
    override_handler,
)
from uadas_api.workspaces.models import Project

pytestmark = pytest.mark.django_db

KIND = JobKind.INGEST_DATASET.value
T0 = timezone.now()


class Sent(list[uuid.UUID]):
    """Every job id handed to the broker."""


@pytest.fixture(autouse=True)
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[Sent]:
    # Autouse: creating a job commits (in the transaction=True tests) and would run it eagerly.
    recorder = Sent()
    monkeypatch.setattr(job_queue, "enqueue", lambda job_id: recorder.append(job_id))
    yield recorder


def setup_job() -> tuple[Any, Any, Project, Job]:
    org = make_organization()
    user = make_user()
    Membership.objects.create(user=user, organization=org, role=Role.EDITOR)
    project = Project.objects.create(organization=org, name=f"p-{uuid.uuid4().hex[:6]}")
    handler = JobHandler(validate_params=lambda org, p: dict(p), run=lambda ctx: None)  # type: ignore[arg-type,return-value]
    with override_handler(KIND, handler):
        job = services.create_job(
            project=project, actor=user, kind=KIND, params={"x": 1}
        ).job
    return org, user, project, job


def two_workers(job: Job) -> tuple[Job, Job]:
    """Worker A claims; its heartbeat goes stale; worker B takes the job over."""
    first = services.claim(job.pk, now=T0, stale_after=120)
    second = services.claim(job.pk, now=T0 + timedelta(seconds=500), stale_after=120)
    assert first is not None and second is not None
    assert (first.attempts, second.attempts) == (1, 2)
    return first, second


def state(job: Job) -> tuple[str, int]:
    job.refresh_from_db()
    return job.status, job.attempts


# ------------------------------------------------------------------ J2: fencing


def test_a_superseded_worker_cannot_fail_the_live_run() -> None:
    _, _, _, job = setup_job()
    first, second = two_workers(job)
    assert not services.finish_failed(
        job.pk,
        attempt=first.attempts,
        code=JobErrorCode.PARSE_ERROR,
        now=timezone.now(),
    )
    assert state(job) == ("running", 2)  # untouched
    # twin: the live worker's identical call succeeds
    assert services.finish_failed(
        job.pk,
        attempt=second.attempts,
        code=JobErrorCode.PARSE_ERROR,
        now=timezone.now(),
    )
    assert state(job) == ("failed", 2)


def test_a_superseded_worker_cannot_requeue_the_live_run() -> None:
    _, _, _, job = setup_job()
    first, second = two_workers(job)
    assert not services.requeue_for_retry(
        job.pk, attempt=first.attempts, delay=10, now=timezone.now()
    )
    assert state(job) == ("running", 2)
    assert services.requeue_for_retry(
        job.pk, attempt=second.attempts, delay=10, now=timezone.now()
    )
    assert state(job) == ("queued", 2)


def test_a_superseded_worker_cannot_cancel_or_succeed_the_live_run() -> None:
    _, _, _, job = setup_job()
    first, second = two_workers(job)
    assert not services.finish_cancelled(
        job.pk, attempt=first.attempts, now=timezone.now()
    )
    assert not services.finish_succeeded(
        job.pk, attempt=first.attempts, result={"r": 1}, now=timezone.now()
    )
    assert state(job) == ("running", 2)
    assert services.finish_succeeded(
        job.pk, attempt=second.attempts, result={"r": 1}, now=timezone.now()
    )
    assert state(job) == ("succeeded", 2)


def test_a_superseded_workers_progress_is_refused_and_the_live_workers_is_not() -> None:
    _, _, _, job = setup_job()
    first, second = two_workers(job)
    stale = ProgressSink(job.pk, attempt=first.attempts, min_interval=0)
    live = ProgressSink(job.pk, attempt=second.attempts, min_interval=0)
    with pytest.raises(JobLostError):
        stale.report(50, "from the old worker")
    with pytest.raises(JobLostError):
        stale.check_cancelled()
    live.report(20, "from the live worker")
    live.check_cancelled()
    job.refresh_from_db()
    assert (job.progress, job.message) == (20, "from the live worker")


def test_a_worker_taken_over_mid_run_leaves_no_rows_and_does_not_abandon_the_dataset() -> (
    None
):
    org, user, project, job = setup_job()
    abandoned: list[uuid.UUID] = []

    def run(ctx: JobContext) -> Completion:
        # While this worker (attempt 1) is busy, its heartbeat is judged stale and another worker
        # claims the job (attempt 2).
        Job.objects.filter(pk=job.pk).update(heartbeat_at=T0 - timedelta(days=1))
        assert services.claim(job.pk, now=timezone.now(), stale_after=120) is not None
        return Completion(
            result={"r": 1},
            commit=lambda: Project.objects.create(
                organization=org, name="Must not exist"
            ),
            cleanup=lambda: None,
        )

    handler = JobHandler(
        validate_params=lambda org, p: dict(p),
        run=run,
        on_abandon=lambda j: abandoned.append(j.pk),
    )
    with override_handler(KIND, handler):
        outcome = execute_job(job.pk)
    assert outcome.kind is OutcomeKind.SKIPPED
    assert not Project.objects.filter(name="Must not exist").exists()
    assert abandoned == []  # the live run owns the dataset's objects
    assert state(job) == ("running", 2)


# ---------------------------------------------------------------- J1: heartbeats


def test_a_heartbeat_refreshes_only_the_live_attempts_row() -> None:
    _, _, _, job = setup_job()
    first, second = two_workers(job)
    Job.objects.filter(pk=job.pk).update(heartbeat_at=T0 - timedelta(days=1))
    assert Heartbeat(job.pk, attempt=second.attempts, interval=1).beat() is True
    job.refresh_from_db()
    assert job.heartbeat_at is not None and job.heartbeat_at >= T0  # refreshed to "now"
    # the superseded worker's beat does nothing and reports that the job is no longer its own
    Job.objects.filter(pk=job.pk).update(heartbeat_at=T0)
    old = Heartbeat(job.pk, attempt=first.attempts, interval=1)
    assert old.beat() is False and old.lost.is_set()
    job.refresh_from_db()
    assert job.heartbeat_at == T0


def test_a_lost_heartbeat_stops_the_handler_at_its_next_checkpoint() -> None:
    _, _, _, job = setup_job()
    first, _second = two_workers(job)
    sink = ProgressSink(job.pk, attempt=first.attempts, min_interval=0)
    beat = sink.heartbeat(interval=1)
    beat.beat()  # discovers the takeover
    with pytest.raises(JobLostError):
        sink.check_cancelled()
    with pytest.raises(JobLostError):
        sink.report(10, "still going?")


@pytest.mark.django_db(transaction=True)
def test_the_heartbeat_thread_keeps_a_busy_silent_job_alive() -> None:
    _, _, _, job = setup_job()
    claimed = services.claim(job.pk, now=timezone.now(), stale_after=120)
    assert claimed is not None
    Job.objects.filter(pk=job.pk).update(heartbeat_at=T0 - timedelta(hours=1))
    before = Job.objects.get(pk=job.pk).heartbeat_at
    sink = ProgressSink(job.pk, attempt=claimed.attempts, min_interval=3600)
    with sink.heartbeat(interval=0.05):
        time.sleep(
            0.6
        )  # the handler is "busy": no progress calls, no DB use on this thread
    after = Job.objects.get(pk=job.pk).heartbeat_at
    assert (
        before is not None
        and after is not None
        and after > before + timedelta(minutes=30)
    )
    assert not any(t.name == "uadas-job-heartbeat" for t in threading.enumerate())


@pytest.mark.django_db(transaction=True)
def test_a_heartbeat_thread_of_a_superseded_worker_flags_the_loss() -> None:
    _, _, _, job = setup_job()
    first, _second = two_workers(job)
    sink = ProgressSink(job.pk, attempt=first.attempts, min_interval=3600)
    with sink.heartbeat(interval=0.05):
        time.sleep(0.5)
    with pytest.raises(JobLostError):
        sink.check_cancelled()


def test_the_handler_runs_under_a_heartbeat_that_is_stopped_even_when_it_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    real_start, real_stop = Heartbeat.start, Heartbeat.stop

    def recording_start(self: Heartbeat) -> None:
        events.append("start")
        real_start(self)

    def recording_stop(self: Heartbeat) -> None:
        events.append("stop")
        real_stop(self)

    monkeypatch.setattr(Heartbeat, "start", recording_start)
    monkeypatch.setattr(Heartbeat, "stop", recording_stop)

    def succeed(ctx: JobContext) -> Completion:
        events.append("run")
        return Completion(result={})

    def explode(ctx: JobContext) -> Completion:
        events.append("run")
        raise RuntimeError("boom")

    for run, expected in ((succeed, "succeeded"), (explode, "failed")):
        events.clear()
        _, _, _, job = setup_job()
        handler = JobHandler(validate_params=lambda org, p: dict(p), run=run)
        with override_handler(KIND, handler):
            execute_job(job.pk)
        assert events == ["start", "run", "stop"], events
        assert state(job)[0] == expected


def test_the_heartbeat_interval_is_a_fraction_of_the_stale_window() -> None:
    cfg = get_config()
    assert 1 <= cfg.heartbeat_interval_seconds <= cfg.stale_after_seconds / 3
    tight = replace(cfg, stale_after_seconds=30)
    from uadas_api.jobs.config import heartbeat_interval

    assert heartbeat_interval(tight) < 30 / 2


# ----------------------------------------------- J3: the sweeper cleans up like a worker


def recording_handler(abandoned: list[uuid.UUID]) -> JobHandler:
    return JobHandler(
        validate_params=lambda org, p: dict(p),
        run=lambda ctx: None,  # type: ignore[arg-type,return-value]
        on_abandon=lambda j: abandoned.append(j.pk),
    )


def stale_running(job: Job, *, attempts: int) -> None:
    claimed = services.claim(job.pk, now=T0, stale_after=120)
    assert claimed is not None
    Job.objects.filter(pk=job.pk).update(attempts=attempts, heartbeat_at=T0)


def test_the_sweeper_runs_the_abandon_hook_for_a_job_it_fails_or_cancels(
    sent: Sent,
) -> None:
    abandoned: list[uuid.UUID] = []
    cfg = replace(get_config(), stale_after_seconds=120, max_attempts=3)
    with override_handler(KIND, recording_handler(abandoned)):
        _, _, _, exhausted = setup_job()
        stale_running(exhausted, attempts=3)
        _, _, _, cancelled = setup_job()
        stale_running(cancelled, attempts=1)
        Job.objects.filter(pk=cancelled.pk).update(cancel_requested=True)
        _, _, _, retried = setup_job()
        stale_running(retried, attempts=1)
        report = services.sweep_stale(now=T0 + timedelta(seconds=1000), config=cfg)
    assert (report.failed, report.cancelled, report.requeued) == (1, 1, 1)
    assert sorted(abandoned) == sorted(
        [exhausted.pk, cancelled.pk]
    )  # not the retried one
    assert state(exhausted)[0] == "failed" and state(cancelled)[0] == "cancelled"
    assert state(retried)[0] == "queued"  # twin: a requeue abandons nothing


def test_a_failing_abandon_hook_cannot_stop_the_sweep(sent: Sent) -> None:
    def explode(job: Job) -> None:
        raise RuntimeError("storage on fire")

    handler = JobHandler(
        validate_params=lambda org, p: dict(p),
        run=lambda ctx: None,  # type: ignore[arg-type,return-value]
        on_abandon=explode,
    )
    with override_handler(KIND, handler):
        _, _, _, job = setup_job()
        stale_running(job, attempts=3)
        report = services.sweep_stale(
            now=T0 + timedelta(seconds=1000),
            config=replace(get_config(), stale_after_seconds=120, max_attempts=3),
        )
    assert report.failed == 1 and state(job)[0] == "failed"


def test_cancelling_a_queued_job_runs_the_abandon_hook() -> None:
    abandoned: list[uuid.UUID] = []
    with override_handler(KIND, recording_handler(abandoned)):
        org, user, _, job = setup_job()
        outcome = services.request_cancel(organization=org, job_id=job.pk, actor=user)
    assert outcome is services.CancelOutcome.CANCELLED
    assert abandoned == [job.pk]


def test_cancelling_a_running_job_only_flags_it_and_abandons_nothing() -> None:
    abandoned: list[uuid.UUID] = []
    with override_handler(KIND, recording_handler(abandoned)):
        org, user, _, job = setup_job()
        assert services.claim(job.pk, now=timezone.now(), stale_after=120) is not None
        outcome = services.request_cancel(organization=org, job_id=job.pk, actor=user)
    assert outcome is services.CancelOutcome.REQUESTED
    assert abandoned == []  # the worker will stop at its checkpoint and abandon then


def test_the_sweeper_reaps_the_workspaces_a_killed_worker_left(
    sent: Sent, settings: Any, tmp_path: Any
) -> None:
    import os

    root = tmp_path / "sandbox-root"
    root.mkdir()
    settings.UADAS_SANDBOX = {**settings.UADAS_SANDBOX, "tmp_root": str(root)}
    stale = root / "uadas-sbx-deadworker"
    fresh = root / "uadas-sbx-liveworker"
    stale.mkdir()
    fresh.mkdir()
    (stale / "input.csv").write_text("tenant data")
    two_days_ago = time.time() - 2 * 86400
    os.utime(stale, (two_days_ago, two_days_ago))
    report = services.sweep_stale()
    assert report.workspaces_reaped == 1
    assert not stale.exists() and fresh.exists()


# --------------------------------------------------------------- J4: retry timing


def test_a_retry_that_is_backing_off_is_not_resent_by_the_lost_message_sweeper(
    sent: Sent,
) -> None:
    _, _, _, job = setup_job()
    assert services.claim(job.pk, now=T0, stale_after=120) is not None
    Job.objects.filter(pk=job.pk).update(created_at=T0 - timedelta(days=1))
    assert services.requeue_for_retry(job.pk, attempt=1, delay=200, now=T0)
    job.refresh_from_db()
    assert (
        job.status == "queued" and job.enqueued_at == T0
    )  # the retry message is in flight
    assert job.not_before == T0 + timedelta(seconds=200)
    cfg = replace(get_config(), requeue_after_seconds=30)
    early = services.sweep_stale(now=T0 + timedelta(seconds=60), config=cfg)
    assert early.resent == 0 and sent == []  # by enqueued_at alone it *would* be resent
    late = services.sweep_stale(now=T0 + timedelta(seconds=260), config=cfg)
    assert late.resent == 1 and sent == [job.pk]  # twin: once the backoff is over it is


def test_a_job_with_no_backoff_is_resent_as_before(sent: Sent) -> None:
    _, _, _, job = setup_job()
    Job.objects.filter(pk=job.pk).update(created_at=T0 - timedelta(days=1))
    report = services.sweep_stale(
        now=T0, config=replace(get_config(), requeue_after_seconds=30)
    )
    assert report.resent == 1 and sent == [job.pk]


def test_a_retryable_failure_records_when_it_may_run_again() -> None:
    from uadas_api.storage.errors import StorageUnavailableError

    _, _, _, job = setup_job()

    def fail(ctx: JobContext) -> Completion:
        raise StorageUnavailableError("down")

    handler = JobHandler(validate_params=lambda org, p: dict(p), run=fail)
    before = timezone.now()
    with override_handler(KIND, handler):
        outcome = execute_job(job.pk)
    assert outcome.kind is OutcomeKind.RETRY
    job.refresh_from_db()
    assert job.not_before is not None
    assert job.not_before >= before + timedelta(seconds=outcome.delay * 0.9)
    assert job.enqueued_at is not None


# ------------------------------------------------- J7: terminal means terminal


def test_a_stale_instance_cannot_resurrect_a_finished_job() -> None:
    _, _, _, job = setup_job()
    stale_a = Job.objects.get(pk=job.pk)  # remembers "queued"
    stale_b = Job.objects.get(pk=job.pk)
    claimed = services.claim(job.pk, now=timezone.now(), stale_after=120)
    assert claimed is not None
    assert services.finish_succeeded(
        job.pk, attempt=claimed.attempts, result={"r": 1}, now=timezone.now()
    )
    stale_a.message = "I never heard about the finish"
    with pytest.raises(JobTransitionError):
        stale_a.save()
    stale_b.status = "running"
    with pytest.raises(JobTransitionError):
        stale_b.save()
    job.refresh_from_db()
    assert (job.status, job.message) == ("succeeded", "Finished")


def test_saving_a_job_that_is_still_open_works_and_a_stale_status_cannot_skip_the_machine() -> (
    None
):
    _, _, _, job = setup_job()
    live = Job.objects.get(pk=job.pk)
    live.message = "queued still"
    live.save()  # twin: nothing finished, so the save goes through
    job.refresh_from_db()
    assert job.message == "queued still"
    # In memory this instance believes "queued"; the database says "running". Writing
    # `succeeded` from queued is not a legal move, whatever the instance remembers.
    claimed = services.claim(job.pk, now=timezone.now(), stale_after=120)
    assert claimed is not None
    stale = Job.objects.get(pk=job.pk)
    stale.status = "running"
    with allow_status_write():
        Job.objects.filter(pk=job.pk).update(status="queued", heartbeat_at=None)
    stale.status = "succeeded"
    with pytest.raises(JobTransitionError):
        stale.save()


def test_the_update_path_still_excludes_finished_rows() -> None:
    _, _, _, job = setup_job()
    claimed = services.claim(job.pk, now=timezone.now(), stale_after=120)
    assert claimed is not None
    services.finish_cancelled(job.pk, attempt=claimed.attempts, now=timezone.now())
    assert Job.objects.filter(pk=job.pk).update(message="rewritten") == 0
    job.refresh_from_db()
    assert job.message == "Cancelled"


# ---------------------------------------------------------- worker start-up hook


def test_a_starting_worker_hardens_itself_and_sweeps_dead_workers_dirs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uadas_api.jobs import tasks

    calls: list[str] = []

    def harden() -> bool:
        calls.append("harden")
        return True

    def reap() -> int:
        calls.append("reap")
        return 0

    monkeypatch.setattr(tasks, "harden_worker", harden)
    monkeypatch.setattr(tasks, "reap_workspaces", reap)
    tasks._on_worker_start()
    assert calls == ["harden", "reap"]


def test_a_failing_sweep_at_start_does_not_stop_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uadas_api.jobs import tasks

    def boom() -> int:
        raise OSError("disk gone")

    monkeypatch.setattr(tasks, "harden_worker", lambda: True)
    monkeypatch.setattr(tasks, "reap_workspaces", boom)
    tasks._on_worker_start()  # no exception
