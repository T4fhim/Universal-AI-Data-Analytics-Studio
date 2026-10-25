# File: apps/api/uadas_api/jobs/events.py
"""The job-progress event stream's logic: what an event says, its id, and the polling loop (3.7).

How a stream learns about progress: the worker writes ``progress`` / ``message`` / ``status`` to the
:class:`~uadas_api.jobs.models.Job` row (:mod:`uadas_api.jobs.progress`, a different process), and the
stream **re-reads that row** -- the database is the only source of truth, so a missed notification can
never leave a client stale. Chosen over a Redis pub/sub nudge (kept as a later optimisation, see
``plans/phase-3-7-streaming.md``): polling needs no second moving part, cannot be lost, and already
degrades to nothing when Redis is down. The cost is bounded and paid per open stream: one indexed
primary-key ``SELECT`` per poll (1 s, jittered, backing off x1.5 to 5 s while nothing changes) plus a
membership check every 30 s, and a connection that is opened for the query and closed straight after
(:func:`uadas_api.web.streams.release_connections`) so no connection or transaction is held across a
sleep. The per-user and per-organization stream caps bound the total.

**An event carries only** the job id, ``status``, ``progress``, the handler's fixed ``message`` and the
closed ``error_code`` -- never ``params``, ``result`` or any row of data.

**Event ids are derived from the state, not counted**: ``attempts * 10_000 + rank * 1_000 + progress``
with ``rank`` 0 queued, 1 running, 2 terminal. A retry bumps ``attempts``, so ids only grow within a job,
and any server can compute the id of the state it sees. ``Last-Event-ID`` therefore needs no stored
history: a reconnecting client is always sent the *current* state first (never a replay), and the one
place the id is compared is the end: a client that already holds the terminal id gets ``204`` (which
tells ``EventSource`` to stop reconnecting) instead of an endless close/reconnect loop.
"""

from __future__ import annotations

import asyncio
import random
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from uadas_api.accounts.models import Membership
from uadas_api.jobs.choices import TERMINAL_STATUSES, JobStatus
from uadas_api.jobs.models import Job
from uadas_api.web.config import ApiConfig
from uadas_api.web.sse import encode_comment, encode_event, encode_retry

_RANK = {JobStatus.QUEUED.value: 0, JobStatus.RUNNING.value: 1}
_TERMINAL_RANK = 2


@dataclass(frozen=True)
class JobSnapshot:
    """The part of a job row an event may reveal (nothing here holds user data)."""

    job_id: uuid.UUID
    status: str
    progress: int
    message: str
    error_code: str
    attempts: int

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def event_id(self) -> int:
        rank = _TERMINAL_RANK if self.terminal else _RANK.get(self.status, 0)
        return self.attempts * 10_000 + rank * 1_000 + self.progress

    @property
    def change_key(self) -> tuple[str, int, str, str, int]:
        return (
            self.status,
            self.progress,
            self.message,
            self.error_code,
            self.attempts,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error_code": self.error_code,
        }


def read_snapshot(
    organization_id: uuid.UUID, project_id: uuid.UUID, job_id: uuid.UUID
) -> JobSnapshot | None:
    """The job's current state if it is a job of this project of this organization, else ``None``."""
    row = (
        Job.objects.for_organization(organization_id)
        .filter(pk=job_id, project_id=project_id)
        .values("status", "progress", "message", "error_code", "attempts")
        .first()
    )
    if row is None:
        return None
    return JobSnapshot(job_id=job_id, **row)


def is_member(user_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    """Whether ``user_id`` is still an active member of the organization."""
    return Membership.objects.filter(
        user_id=user_id, organization_id=organization_id, user__is_active=True
    ).exists()


async def job_event_stream(
    *,
    read: Callable[[], Awaitable[JobSnapshot | None]],
    still_member: Callable[[], Awaitable[bool]],
    config: ApiConfig,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    jitter: Callable[[], float] = random.random,
) -> AsyncIterator[bytes]:
    """Yield SSE frames for one job until it is terminal, vanishes, loses its viewer or times out.

    ``read`` and ``still_member`` are the database touch points (each closes its connection
    before returning); everything else is arithmetic on ``clock``, so tests can drive it with a fake
    clock and no sleeping.
    """
    yield encode_retry(config.sse_retry_ms)
    started = last_write = last_check = clock()
    interval = config.sse_poll_seconds
    sent: tuple[str, int, str, str, int] | None = None
    while True:
        snapshot = await read()
        if snapshot is None:  # the job (or its project) was deleted
            return
        if snapshot.change_key != sent:
            sent = snapshot.change_key
            interval = config.sse_poll_seconds
            yield encode_event(
                snapshot.payload(),
                event="job",
                event_id=snapshot.event_id,
                max_bytes=config.sse_max_event_bytes,
            )
            last_write = clock()
            if snapshot.terminal:
                return
        else:
            interval = min(interval * 1.5, config.sse_poll_max_seconds)
        now = clock()
        remaining = config.sse_max_seconds - (now - started)
        if remaining <= 0:
            return  # the client reconnects (Last-Event-ID) and is sent the current state
        if now - last_check >= config.sse_recheck_seconds:
            last_check = now
            if not await still_member():
                return
        if now - last_write >= config.sse_heartbeat_seconds:
            yield encode_comment()
            last_write = now
        until_heartbeat = config.sse_heartbeat_seconds - (now - last_write)
        delay = interval * (0.8 + 0.4 * jitter())
        await sleep(max(0.0, min(delay, remaining, until_heartbeat)))
