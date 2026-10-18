# File: apps/api/tests/test_jobs_tasks.py
"""The Celery shell around the job logic: configuration, payload, and the eager round trip.

Why: the safety of the queue rests on a handful of configuration facts (JSON-only, late ack,
prefetch 1, limits, a visibility timeout longer than any task) and on the message being nothing
but an id. They are asserted against the *live* Celery app object, not against the settings
module, so a mis-wired ``config_from_object`` cannot hide behind correct settings.

The hermetic suite runs Celery eagerly (``test`` settings), which exercises the real task
function and the real ``retry`` path in-process; the real broker and worker are covered by
``test_jobs_integration.py`` (opt-in, like the MinIO tests).
"""

from __future__ import annotations

import logging
import pickle
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from factories import make_organization, make_user
from kombu.exceptions import ContentDisallowed, OperationalError
from kombu.serialization import dumps, loads, prepare_accept_content

from uadas_api.accounts.models import Membership, Role
from uadas_api.jobs import queue as job_queue
from uadas_api.jobs import services
from uadas_api.jobs.celery_app import app
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.registry import Completion, JobContext, JobHandler, override_handler
from uadas_api.jobs.tasks import RUN_TASK_NAME, SWEEP_TASK_NAME, run_job, sweep
from uadas_api.storage.errors import StorageUnavailableError
from uadas_api.workspaces.models import Project

KIND = JobKind.INGEST_DATASET.value
OnCommit = Callable[..., Any]


# ------------------------------------------------------------------ configuration


def test_the_live_app_accepts_and_produces_json_only() -> None:
    assert list(app.conf.accept_content) == ["json"]
    assert app.conf.task_serializer == "json"
    assert app.conf.result_serializer == "json"
    assert app.conf.event_serializer == "json"


def test_a_pickled_message_is_refused_by_the_live_configuration() -> None:
    payload = pickle.dumps({"job": "x"})
    with pytest.raises(ContentDisallowed):
        loads(
            payload,
            "application/x-python-serialize",
            "binary",
            accept=prepare_accept_content(app.conf.accept_content),
        )


def test_a_json_message_is_accepted_by_the_live_configuration() -> None:
    # The positive twin of the test above.
    content_type, encoding, body = dumps({"job": "x"}, serializer="json")
    accepted = prepare_accept_content(app.conf.accept_content)
    assert loads(body, content_type, encoding, accept=accepted) == {"job": "x"}


def test_delivery_is_late_acked_with_one_message_prefetched() -> None:
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert run_job.acks_late is True
    assert run_job.reject_on_worker_lost is True


def test_time_limits_and_the_visibility_timeout_are_consistent() -> None:
    soft, hard = app.conf.task_soft_time_limit, app.conf.task_time_limit
    visibility = app.conf.broker_transport_options["visibility_timeout"]
    assert soft < hard < visibility
    from django.conf import settings

    assert visibility > hard + settings.UADAS_JOBS["retry_backoff_max"]


def test_no_result_backend_exists_because_state_lives_in_the_database() -> None:
    assert app.conf.result_backend is None
    assert app.conf.task_ignore_result is True


def test_the_tasks_are_registered_under_their_stable_names() -> None:
    assert RUN_TASK_NAME in app.tasks and SWEEP_TASK_NAME in app.tasks
    assert (RUN_TASK_NAME, SWEEP_TASK_NAME) == ("uadas.jobs.run", "uadas.jobs.sweep")


def test_the_beat_schedule_names_the_sweeper() -> None:
    schedule = app.conf.beat_schedule
    assert [entry["task"] for entry in schedule.values()] == [SWEEP_TASK_NAME]


# ------------------------------------------------------------------------ the payload


def test_enqueue_sends_nothing_but_the_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(
        run_job, "apply_async", lambda *a, **k: calls.append((a, k)), raising=False
    )
    job_id = uuid.uuid4()
    job_queue.enqueue(job_id)
    assert calls == [((), {"args": [str(job_id)]})]


def test_a_broker_error_becomes_queue_unavailable_without_its_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise OperationalError(
            "redis://:s3cret-password@broker.internal:6379/0 refused"
        )

    monkeypatch.setattr(run_job, "apply_async", broken, raising=False)
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(job_queue.QueueUnavailable) as excinfo,
    ):
        job_queue.enqueue(uuid.uuid4())
    assert "s3cret" not in str(excinfo.value)
    assert "s3cret" not in caplog.text
    assert "OperationalError" in caplog.text


def test_an_unrelated_error_is_not_mistaken_for_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise ValueError("a bug, not an outage")

    monkeypatch.setattr(run_job, "apply_async", broken, raising=False)
    with pytest.raises(ValueError):
        job_queue.enqueue(uuid.uuid4())


# ---------------------------------------------------------------- the eager round trip


@pytest.fixture
def editor_project() -> tuple[Any, Any, Project]:
    org = make_organization()
    user = make_user()
    Membership.objects.create(user=user, organization=org, role=Role.EDITOR)
    return org, user, Project.objects.create(organization=org, name="p")


@pytest.fixture
def handler_state() -> Iterator[dict[str, Any]]:
    state: dict[str, Any] = {"calls": 0, "fail_first": 0}

    def run(ctx: JobContext) -> Completion:
        state["calls"] += 1
        if state["calls"] <= state["fail_first"]:
            raise StorageUnavailableError("down")
        ctx.report(50, "Halfway", force=True)
        return Completion(result={"calls": state["calls"]})

    handler = JobHandler(validate_params=lambda org, p: dict(p), run=run)
    with override_handler(KIND, handler):
        yield state


@pytest.mark.django_db
def test_creating_a_job_runs_it_through_the_real_task_after_commit(
    editor_project: tuple[Any, Any, Project],
    handler_state: dict[str, Any],
    django_capture_on_commit_callbacks: OnCommit,
) -> None:
    _, user, project = editor_project
    with django_capture_on_commit_callbacks(execute=True):
        job = services.create_job(
            project=project, actor=user, kind=KIND, params={"a": 1}
        ).job
    job.refresh_from_db()
    assert (job.status, job.result, job.attempts) == ("succeeded", {"calls": 1}, 1)
    assert handler_state["calls"] == 1


@pytest.mark.django_db
def test_the_task_does_not_run_before_the_commit(
    editor_project: tuple[Any, Any, Project],
    handler_state: dict[str, Any],
    django_capture_on_commit_callbacks: OnCommit,
) -> None:
    _, user, project = editor_project
    with django_capture_on_commit_callbacks(execute=False):
        job = services.create_job(project=project, actor=user, kind=KIND, params={}).job
        assert handler_state["calls"] == 0
    job.refresh_from_db()
    assert job.status == "queued"


@pytest.mark.django_db
def test_a_retryable_failure_is_retried_through_celery_and_then_succeeds(
    editor_project: tuple[Any, Any, Project],
    handler_state: dict[str, Any],
    django_capture_on_commit_callbacks: OnCommit,
) -> None:
    _, user, project = editor_project
    handler_state["fail_first"] = 1
    with django_capture_on_commit_callbacks(execute=True):
        job = services.create_job(project=project, actor=user, kind=KIND, params={}).job
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("succeeded", 2)
    assert handler_state["calls"] == 2


@pytest.mark.django_db
def test_endless_retryable_failures_end_failed_after_the_attempt_limit(
    editor_project: tuple[Any, Any, Project],
    handler_state: dict[str, Any],
    django_capture_on_commit_callbacks: OnCommit,
) -> None:
    from uadas_api.jobs.config import get_config

    _, user, project = editor_project
    handler_state["fail_first"] = 10_000
    with django_capture_on_commit_callbacks(execute=True):
        job = services.create_job(project=project, actor=user, kind=KIND, params={}).job
    job.refresh_from_db()
    assert job.status == "failed"
    assert job.error_code == "storage_unavailable"
    assert job.attempts == get_config().max_attempts == handler_state["calls"]


@pytest.mark.django_db
def test_a_redelivered_message_for_a_finished_job_changes_nothing(
    editor_project: tuple[Any, Any, Project],
    handler_state: dict[str, Any],
    django_capture_on_commit_callbacks: OnCommit,
) -> None:
    _, user, project = editor_project
    with django_capture_on_commit_callbacks(execute=True):
        job = services.create_job(project=project, actor=user, kind=KIND, params={}).job
    run_job.apply(
        args=[str(job.pk)]
    ).get()  # the broker delivers the same message again
    run_job.apply(args=[str(job.pk)]).get()
    job.refresh_from_db()
    assert (job.status, job.attempts, handler_state["calls"]) == ("succeeded", 1, 1)


@pytest.mark.django_db
def test_the_sweep_task_returns_a_plain_report() -> None:
    report = sweep.apply().get()
    assert set(report) == {
        "requeued",
        "failed",
        "cancelled",
        "resent",
        "send_failures",
        "workspaces_reaped",
    }
    assert all(isinstance(value, int) for value in report.values())


@pytest.mark.django_db
def test_garbage_ids_are_acknowledged_not_retried() -> None:
    run_job.apply(args=["not-a-uuid"]).get()
    run_job.apply(args=[str(uuid.uuid4())]).get()
