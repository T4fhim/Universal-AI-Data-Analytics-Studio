# File: apps/api/tests/test_jobs_events.py
"""The job-progress stream's logic (3.7), driven with a fake clock: no sleeping, no HTTP.

What is pinned: the frame order (retry hint, current state first, one event per change), ids that
only grow, polling that backs off while nothing changes and resets on a change, comment heartbeats
for idle proxies, and every way a stream ends (terminal state, hard maximum, a viewer who lost
access, a deleted job). The database half proves an event can carry only the closed fields -- never
``params`` or ``result`` -- and that a job is read only inside its own organization and project.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterable
from typing import Any

import pytest
from factories import factory_for
from web_support import make_world

from uadas_api.jobs import events
from uadas_api.jobs.choices import JobStatus
from uadas_api.jobs.events import JobSnapshot
from uadas_api.jobs.models import Job, allow_status_write
from uadas_api.web.config import ApiConfig

JOB = uuid.uuid4()


def snap(
    status: str = "running", progress: int = 0, attempts: int = 1, **kw: Any
) -> JobSnapshot:
    return JobSnapshot(
        job_id=JOB,
        status=status,
        progress=progress,
        message=kw.get("message", ""),
        error_code=kw.get("error_code", ""),
        attempts=attempts,
    )


class FakeClock:
    """Time that only moves when the stream sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def drive(
    reads: Iterable[JobSnapshot | None],
    *,
    config: ApiConfig | None = None,
    members: Iterable[bool] = (),
    clock: FakeClock | None = None,
) -> list[bytes]:
    """Run the stream to its end against scripted reads (the last one repeats) and return its frames."""
    script, member_script = list(reads), list(members)
    fake = clock or FakeClock()
    position = {"read": 0, "member": 0}

    async def read() -> JobSnapshot | None:
        index = min(position["read"], len(script) - 1)
        position["read"] += 1
        return script[index]

    async def still_member() -> bool:
        index = min(position["member"], len(member_script) - 1) if member_script else 0
        position["member"] += 1
        return member_script[index] if member_script else True

    async def collect() -> list[bytes]:
        return [
            frame
            async for frame in events.job_event_stream(
                read=read,
                still_member=still_member,
                config=config or ApiConfig(),
                sleep=fake.sleep,
                clock=fake,
                jitter=lambda: 0.5,  # factor 1.0: sleeps are exactly the interval
            )
        ]

    return asyncio.run(asyncio.wait_for(collect(), 30))


def jobs_of(frames: list[bytes]) -> list[dict[str, Any]]:
    out = []
    for frame in frames:
        text = frame.decode()
        if text.startswith("event: job"):
            out.append(json.loads(text.split("data: ", 1)[1]))
    return out


def ids_of(frames: list[bytes]) -> list[int]:
    return [
        int(f.decode().split("id: ")[1].split("\n")[0]) for f in frames if b"id: " in f
    ]


# ----------------------------------------------------------------- ids and payloads


def test_event_ids_grow_with_state_and_a_retry_bumps_the_attempt() -> None:
    order = [
        snap("queued", 0, attempts=0),
        snap("running", 0, attempts=1),
        snap("running", 60, attempts=1),
        snap("succeeded", 100, attempts=1),
        snap("running", 0, attempts=2),  # a later attempt of the same job
    ]
    ids = [s.event_id for s in order]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert snap("failed", 40, error_code="x").event_id == snap("succeeded", 40).event_id
    assert not snap("running").terminal and snap("cancelled").terminal


def test_the_payload_is_exactly_the_closed_field_set() -> None:
    payload = snap(
        "failed", 30, message="Parsing file", error_code="parse_failed"
    ).payload()
    assert set(payload) == {"job_id", "status", "progress", "message", "error_code"}
    assert payload["job_id"] == str(JOB)


# ----------------------------------------------------------------- the loop


def test_the_current_state_is_sent_first_then_each_change_then_it_closes_on_terminal() -> (
    None
):
    frames = drive(
        [
            snap("queued", 0, attempts=0),
            snap("queued", 0, attempts=0),
            snap("running", 20),
            snap("running", 20),
            snap("running", 80, message="Writing"),
            snap("succeeded", 100),
        ]
    )
    assert frames[0] == b"retry: 3000\n\n"
    seen = jobs_of(frames)
    assert [(e["status"], e["progress"]) for e in seen] == [
        ("queued", 0),
        ("running", 20),
        ("running", 80),
        ("succeeded", 100),
    ]
    assert ids_of(frames) == sorted(
        set(ids_of(frames))
    )  # strictly increasing: no replay of stale state


def test_an_unchanged_state_is_not_resent_and_polling_backs_off_then_resets() -> None:
    clock = FakeClock()
    config = ApiConfig(
        sse_poll_seconds=1.0, sse_poll_max_seconds=4.0, sse_heartbeat_seconds=1000.0
    )
    frames = drive(
        [snap("running", 10)] * 6 + [snap("running", 11)] + [snap("succeeded", 100)],
        config=config,
        clock=clock,
    )
    assert len(jobs_of(frames)) == 3  # 10, 11, done -- the five repeats were silent
    # after the first event the interval is 1.0; unchanged polls grow it x1.5 up to the cap of 4.0
    assert clock.sleeps[:6] == [1.0, 1.5, 2.25, 3.375, 4.0, 4.0]
    assert clock.sleeps[6] == 1.0  # a change resets it


def test_polling_is_jittered_within_twenty_percent() -> None:
    clock = FakeClock()
    jitters = iter([0.0, 1.0])

    async def run() -> None:
        reads = iter(
            [
                snap("running", 1),
                snap("running", 1),
                snap("running", 1),
                snap("succeeded", 100),
            ]
        )

        async def read() -> JobSnapshot | None:
            return next(reads)

        async def member() -> bool:
            return True

        async for _ in events.job_event_stream(
            read=read,
            still_member=member,
            config=ApiConfig(),
            sleep=clock.sleep,
            clock=clock,
            jitter=lambda: next(jitters, 0.5),
        ):
            pass

    asyncio.run(run())
    assert clock.sleeps[0] == pytest.approx(0.8) and clock.sleeps[1] == pytest.approx(
        1.5 * 1.2
    )


def test_an_idle_stream_sends_comment_heartbeats_and_ends_at_the_hard_maximum() -> None:
    clock = FakeClock()
    config = ApiConfig(sse_max_seconds=100.0, sse_heartbeat_seconds=15.0)
    frames = drive([snap("running", 5)], config=config, clock=clock)
    beats = [f for f in frames if f == b": keep-alive\n\n"]
    assert len(jobs_of(frames)) == 1
    assert 5 <= len(beats) <= 8  # ~100 s / 15 s
    assert (
        100.0 <= clock.now < 101.0 + config.sse_poll_max_seconds
    )  # closed by the cap, not forever


def test_a_viewer_who_loses_access_is_cut_off_and_one_who_keeps_it_is_not() -> None:
    config = ApiConfig(sse_max_seconds=100.0, sse_recheck_seconds=30.0)
    lost = FakeClock()
    drive([snap("running", 5)], config=config, members=[False], clock=lost)
    assert lost.now < 40  # closed at the first recheck (30 s), not at the 100 s maximum
    kept = FakeClock()
    drive([snap("running", 5)], config=config, members=[True], clock=kept)
    assert kept.now >= 100


def test_a_deleted_job_ends_the_stream_without_an_event() -> None:
    frames = drive([None])
    assert frames == [b"retry: 3000\n\n"]


def test_an_already_terminal_job_gets_its_one_event_and_closes_at_once() -> None:
    clock = FakeClock()
    frames = drive([snap("failed", 50, error_code="parse_failed")], clock=clock)
    assert [e["status"] for e in jobs_of(frames)] == ["failed"]
    assert clock.sleeps == []


# ----------------------------------------------------------------- the database half


@pytest.mark.django_db
def test_an_event_never_carries_params_or_results_and_reads_stay_in_their_organization() -> (
    None
):
    world = make_world()
    job = factory_for(Job).create(world.org, project=world.project)
    Job.objects.filter(pk=job.pk).update(
        params={"secret": "S3CRET-PARAM"}, result={"rows": [["S3CRET-ROW"]]}
    )
    with allow_status_write():
        Job.objects.filter(pk=job.pk).update(
            status=JobStatus.RUNNING, progress=40, message="Parsing file"
        )
    shown = events.read_snapshot(world.org.pk, world.project.pk, job.pk)
    assert shown is not None and shown.status == "running" and shown.progress == 40
    wire = json.dumps(shown.payload())
    assert "S3CRET" not in wire and "params" not in wire and "result" not in wire

    # the twin of each refusal is the call above: same job, its own organization and project
    assert events.read_snapshot(world.other_org.pk, world.project.pk, job.pk) is None
    assert events.read_snapshot(world.org.pk, world.other_project.pk, job.pk) is None
    assert events.read_snapshot(world.org.pk, world.project.pk, uuid.uuid4()) is None


@pytest.mark.django_db
def test_membership_is_checked_against_the_organization_and_an_active_user() -> None:
    world = make_world()
    assert events.is_member(world.viewer.user_id, world.org.pk)
    assert not events.is_member(world.viewer.user_id, world.other_org.pk)
    assert not events.is_member(world.outsider.pk, world.org.pk)
    type(world.viewer.user).objects.filter(pk=world.viewer.user_id).update(
        is_active=False
    )
    assert not events.is_member(world.viewer.user_id, world.org.pk)
