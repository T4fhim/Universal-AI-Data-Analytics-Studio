# File: apps/api/uadas_api/web/job_events.py
"""``GET .../jobs/{job_id}/events``: a job's progress as a Server-Sent Events stream (3.7).

Same address space as the polled job resource (:mod:`uadas_api.web.jobs`): the job lives under its
project, is resolved through ``for_organization`` *and* the path's project, viewers and above may
read it, and a non-member, a foreign job and a missing job are one ``404``. The stream's logic
(event shape, ids, the polling loop) is :mod:`uadas_api.jobs.events`; this module is the HTTP
edge: authentication, the stream cap, ``Last-Event-ID`` and the response.

It is an **async view** (Django serves it under ASGI; WSGI would pin a worker per stream). Every
ORM call goes through ``sync_to_async`` and ends by closing its connection, so no connection is
held while the stream sleeps. Ninja runs authentication first (session cookie; a GET needs no CSRF
token), so an anonymous caller gets the usual ``401`` before anything else happens.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse
from django.http.response import HttpResponseBase
from ninja import Router

from uadas_api.accounts.models import Role
from uadas_api.jobs import events
from uadas_api.web.config import api_config
from uadas_api.web.errors import not_found, responses
from uadas_api.web.scope import member, project_of
from uadas_api.web.sse import SseResponse, sse_openapi
from uadas_api.web.streams import StreamLease, acquire, release_connections

router = Router(tags=["jobs"])

_LAST_EVENT_ID = re.compile(r"\A[0-9]{1,12}\Z")

_EVENTS: dict[str, Any] = {
    "job": {
        "type": "object",
        "description": "The job's current state; sent first on every (re)connect and on every change.",
        "required": ["job_id", "status", "progress", "message", "error_code"],
        "properties": {
            "job_id": {"type": "string", "format": "uuid"},
            "status": {
                "type": "string",
                "enum": ["queued", "running", "succeeded", "failed", "cancelled"],
            },
            "progress": {"type": "integer", "minimum": 0, "maximum": 100},
            "message": {"type": "string"},
            "error_code": {"type": "string"},
        },
    }
}
_OPENAPI = sse_openapi(
    _EVENTS,
    description=(
        "text/event-stream. Frames: a `retry:` hint, `job` events (with a monotonic `id:`), "
        "and `: keep-alive` comments. Closes after the job's terminal state, after a hard "
        "maximum duration (reconnect with Last-Event-ID), or when the viewer loses access."
    ),
)
_OPENAPI["responses"][204] = {
    "description": "The client's Last-Event-ID is already the job's terminal event: stop reconnecting."
}
_OPENAPI["parameters"] = [
    {
        "name": "Last-Event-ID",
        "in": "header",
        "required": False,
        "schema": {"type": "string", "pattern": "^[0-9]{1,12}$"},
        "description": "Set by EventSource on reconnect; the current state is always sent first.",
    }
]


def _open(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[events.JobSnapshot, uuid.UUID, StreamLease | None]:
    """Everything that needs the database before the stream starts, then the connection is closed.

    Returns the first snapshot, the caller's user id and (unless the client already holds the
    terminal event) a stream-cap lease. Raises ``401``/``404``/``429`` through the usual envelope.
    """
    try:
        membership = member(request, org_id, Role.VIEWER)
        project = project_of(membership, project_id)
        snapshot = events.read_snapshot(project.organization_id, project.pk, job_id)
        if snapshot is None:
            raise not_found()
        last = request.headers.get("Last-Event-ID", "")
        if (
            snapshot.terminal
            and _LAST_EVENT_ID.fullmatch(last)
            and int(last) >= snapshot.event_id
        ):
            return snapshot, membership.user_id, None
        config = api_config()
        lease = acquire(
            "job",
            membership.user_id,
            membership.organization_id,
            user_cap=config.stream_user_cap,
            org_cap=config.stream_org_cap,
            max_seconds=config.sse_max_seconds,
        )
        return snapshot, membership.user_id, lease
    finally:
        release_connections()


async def _guarded(
    chunks: AsyncIterator[bytes], lease: StreamLease
) -> AsyncIterator[bytes]:
    """Pass the frames through; give the stream-cap lease back on every way out (incl. disconnect)."""
    try:
        async for chunk in chunks:
            yield chunk
    finally:
        lease.release()


async def _read(
    organization_id: uuid.UUID, project_id: uuid.UUID, job_id: uuid.UUID
) -> events.JobSnapshot | None:
    def query() -> events.JobSnapshot | None:
        try:
            return events.read_snapshot(organization_id, project_id, job_id)
        finally:
            release_connections()

    return await sync_to_async(query)()


async def _member(user_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    def query() -> bool:
        try:
            return events.is_member(user_id, organization_id)
        finally:
            release_connections()

    return await sync_to_async(query)()


@router.get(
    "/organizations/{org_id}/projects/{project_id}/jobs/{job_id}/events",
    response=responses({200: None}),
    summary="Stream a job's progress as Server-Sent Events (viewer and above)",
    operation_id="jobs_events",
    openapi_extra=_OPENAPI,
)
async def jobs_events(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, job_id: uuid.UUID
) -> HttpResponseBase:
    _first, user_id, lease = await sync_to_async(_open)(
        request, org_id, project_id, job_id
    )
    if lease is None:
        return HttpResponse(status=204)
    config = api_config()
    stream = events.job_event_stream(
        read=partial(_read, org_id, project_id, job_id),
        still_member=partial(_member, user_id, org_id),
        config=config,
    )
    return SseResponse(_guarded(stream, lease), on_close=lease.release)
