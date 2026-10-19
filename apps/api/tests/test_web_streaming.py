# File: apps/api/tests/test_web_streaming.py
"""The job-progress stream over the real ASGI application (3.7).

These tests call ``uadas_api.asgi.application`` through :mod:`asgi_support`, a client that keeps each
body message as it is sent, because the properties that matter cannot be seen any other way: that
events arrive *while the response is still open* (not buffered until it ends), that
``Last-Event-ID`` resumes with the current state, that the stream closes itself after a terminal
state, that a vanished client releases its slot, and that a foreign job yields a ``404`` and not one
byte of data. Every refusal has a positive twin on the same route (the own-organization success).

They use ``transaction=True`` (the application's threads must see committed rows) and write job
state from a thread that closes its connection, so a leaked connection would also surface as
PostgreSQL refusing to drop the test database at the end of the session.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from asgi_support import Conn, sse_events
from django.db import connection, connections
from django.utils import timezone
from factories import factory_for
from web_support import World, make_world

from uadas_api.jobs.models import Job, allow_status_write

pytestmark = pytest.mark.django_db(transaction=True)

FAST = {
    "sse_poll_seconds": 0.03,
    "sse_poll_max_seconds": 0.05,
    "sse_heartbeat_seconds": 5.0,
    "sse_max_seconds": 20.0,
}


def run[T](scenario: Callable[[], Awaitable[T]]) -> T:
    return asyncio.run(asyncio.wait_for(scenario(), 60))


async def db[T](fn: Callable[[], T]) -> T:
    """Run a database call off the loop, in a thread that closes its connection afterwards."""

    def call() -> T:
        try:
            return fn()
        finally:
            connections.close_all()

    return await asyncio.to_thread(call)


def events_url(world: World, job: Job, *, other: bool = False) -> str:
    base = world.other_base if other else world.base()
    return f"{base}/jobs/{job.pk}/events"


def set_state(job: Job, status: str, progress: int = 0, **extra: Any) -> None:
    fields: dict[str, Any] = {"status": status, "progress": progress, **extra}
    if status in {"succeeded", "failed", "cancelled"}:
        fields["finished_at"] = timezone.now()
    if status == "failed":
        fields.setdefault("error_code", "parse_failed")
    if status == "running":
        fields.setdefault("attempts", 1)
    with allow_status_write():
        Job.objects.filter(pk=job.pk).update(**fields)


@pytest.fixture
def world(settings: Any) -> World:
    settings.UADAS_API = dict(FAST)
    built = make_world()
    for who in ("owner", "admin", "editor", "viewer", "other", "outsider"):
        built.api(
            who
        )  # signing in is a (sync) database write: do it before the loop starts
    return built


@pytest.fixture
def job(world: World) -> Job:
    return factory_for(Job).create(world.org, project=world.project)


def test_events_arrive_while_the_stream_is_open_and_it_closes_after_the_terminal_state(
    world: World, job: Job
) -> None:
    async def scenario() -> None:
        conn = await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
        assert conn.status == 200
        assert conn.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert conn.headers["cache-control"] == "no-cache, no-transform"
        assert conn.headers["x-accel-buffering"] == "no"

        first = await conn.until(b"event: job")  # retry hint, then the current state
        assert first[0] == b"retry: 3000\n\n"
        queued = sse_events(first)[0]
        assert queued["data"]["status"] == "queued" and queued["data"]["job_id"] == str(
            job.pk
        )

        # The response is still open: change the job now and the *next* chunk is the change.
        assert not conn.finished
        await db(lambda: set_state(job, "running", 40, message="Parsing file"))
        running = sse_events(await conn.until(b"Parsing file"))[-1]
        assert (
            running["data"]["progress"] == 40
            and running["data"]["message"] == "Parsing file"
        )
        assert int(running["id"]) > int(queued["id"])  # ids only grow

        await db(lambda: set_state(job, "succeeded", 100))
        done = sse_events(await conn.until(b"succeeded"))[-1]
        assert done["data"]["status"] == "succeeded"
        assert await conn.chunk() is None  # and the server closed it by itself
        await conn.wait_done()

    run(scenario)


def test_a_failed_job_reports_its_error_code_and_nothing_else_about_the_job(
    world: World, job: Job
) -> None:
    async def scenario() -> None:
        await db(
            lambda: Job.objects.filter(pk=job.pk).update(params={"x": "S3CRET-PARAM"})
        )
        await db(lambda: set_state(job, "failed", 30, error_code="parse_failed"))
        conn = await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
        body = await conn.body()
        assert b"S3CRET" not in body and b"params" not in body and b"result" not in body
        (event,) = sse_events(body)
        assert set(event["data"]) == {
            "job_id",
            "status",
            "progress",
            "message",
            "error_code",
        }
        assert event["data"]["error_code"] == "parse_failed"

    run(scenario)


def test_last_event_id_resumes_with_the_current_state_never_a_stale_one(
    world: World, job: Job
) -> None:
    async def scenario() -> None:
        await db(lambda: set_state(job, "running", 60))
        api = world.api("viewer")
        for header in (
            {},
            {"Last-Event-ID": "1000"},
            {"Last-Event-ID": "999999"},
            {"Last-Event-ID": "junk\n"},
        ):
            conn = await Conn.open(
                "GET", events_url(world, job), api=api, headers=header
            )
            assert conn.status == 200, header
            (event,) = sse_events(await conn.until(b"event: job"))
            assert (
                event["data"]["status"] == "running" and event["data"]["progress"] == 60
            ), header
            await conn.disconnect()

    run(scenario)


def test_a_client_that_already_holds_the_terminal_event_is_told_to_stop_reconnecting(
    world: World, job: Job
) -> None:
    async def scenario() -> None:
        await db(lambda: set_state(job, "succeeded", 100))
        api = world.api("viewer")
        # no header, or an older id: the twin -- the terminal event is sent once and the stream closes
        for header in ({}, {"Last-Event-ID": "5"}):
            conn = await Conn.open(
                "GET", events_url(world, job), api=api, headers=header
            )
            assert conn.status == 200
            (event,) = sse_events(await conn.body())
            assert event["data"]["status"] == "succeeded"
            terminal_id = event["id"]
        # the terminal id itself (what EventSource sends after the close): 204 stops it
        conn = await Conn.open(
            "GET",
            events_url(world, job),
            api=api,
            headers={"Last-Event-ID": terminal_id},
        )
        assert conn.status == 204 and await conn.body() == b""

    run(scenario)


def test_idle_streams_send_comment_heartbeats(
    world: World, job: Job, settings: Any
) -> None:
    settings.UADAS_API = {**FAST, "sse_heartbeat_seconds": 0.1}

    async def scenario() -> None:
        conn = await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
        await conn.until(b"event: job")
        beats = await conn.until(
            b": keep-alive"
        )  # nothing changed, yet a frame arrives
        assert beats[-1] == b": keep-alive\n\n"
        await conn.disconnect()

    run(scenario)


def test_a_stream_ends_at_its_hard_maximum_duration(
    world: World, job: Job, settings: Any
) -> None:
    settings.UADAS_API = {**FAST, "sse_max_seconds": 0.4}

    async def scenario() -> None:
        conn = await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
        body = await conn.body()  # ends by itself although the job never finishes
        assert [e["data"]["status"] for e in sse_events(body)] == ["queued"]

    run(scenario)


def test_a_member_removed_while_streaming_is_cut_off_but_a_kept_one_is_not(
    world: World, job: Job, settings: Any
) -> None:
    settings.UADAS_API = {**FAST, "sse_recheck_seconds": 0.1, "sse_max_seconds": 1.5}

    async def scenario() -> None:
        kept = await Conn.open("GET", events_url(world, job), api=world.api("editor"))
        cut = await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
        await cut.until(b"event: job")
        await kept.until(b"event: job")
        await db(lambda: world.viewer.delete())
        await asyncio.wait_for(cut.body(), 5)  # closed within a recheck or two
        assert not kept.finished  # the twin: the other member's stream is untouched ...
        await kept.disconnect()  # ... until it leaves

    run(scenario)


# --------------------------------------------------------------------- who may open one


def test_only_members_of_the_jobs_organization_get_a_stream_and_everyone_else_gets_a_plain_404(
    world: World, job: Job
) -> None:
    secret = [str(job.pk), str(world.project.pk), world.project.name]

    async def scenario() -> None:
        # positive twin first: a viewer of the organization is served
        ok = await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
        assert ok.status == 200
        await ok.disconnect()

        for label, url, api in (
            ("another org, own client", events_url(world, job), world.api("other")),
            ("a signed-in non-member", events_url(world, job), world.api("outsider")),
            # B's own organization and project, A's job id:
            ("foreign job id", events_url(world, job, other=True), world.api("other")),
            (
                "unknown job",
                f"{world.base()}/jobs/{uuid.uuid4()}/events",
                world.api("viewer"),
            ),
            # A's job id under A's organization but another project of it
        ):
            conn = await Conn.open("GET", url, api=api)
            assert conn.status == 404, label
            body = (await conn.body()).decode()
            assert '"code":"not_found"' in body.replace(" ", ""), label
            assert not any(s in body for s in secret), label

    run(scenario)


def test_a_job_of_another_project_in_the_same_organization_is_a_404_too(
    world: World,
) -> None:
    from uadas_api.workspaces.models import Project

    sibling = Project.objects.create(organization=world.org, name="Sibling")
    inside = factory_for(Job).create(world.org, project=sibling)

    async def scenario() -> None:
        wrong = await Conn.open(
            "GET", events_url(world, inside), api=world.api("viewer")
        )
        assert (
            wrong.status == 404
        )  # the path names project "Main"; the job belongs to "Sibling"
        right = await Conn.open(
            "GET",
            f"/api/organizations/{world.org.pk}/projects/{sibling.pk}/jobs/{inside.pk}/events",
            api=world.api("viewer"),
        )
        assert right.status == 200
        await right.disconnect()

    run(scenario)


def test_an_anonymous_request_is_a_401(world: World, job: Job) -> None:
    async def scenario() -> None:
        denied = await Conn.open("GET", events_url(world, job), api=None)
        assert denied.status == 401

    run(scenario)


# --------------------------------------------------------------------- caps and cleanup


def test_the_per_user_cap_is_a_429_and_a_disconnect_frees_the_slot(
    world: World, job: Job, settings: Any
) -> None:
    settings.UADAS_API = {**FAST, "stream_user_cap": 2}

    async def scenario() -> None:
        api = world.api("viewer")
        first = await Conn.open("GET", events_url(world, job), api=api)
        second = await Conn.open("GET", events_url(world, job), api=api)
        assert first.status == second.status == 200
        await first.until(b"event: job")
        await second.until(b"event: job")

        refused = await Conn.open("GET", events_url(world, job), api=api)
        assert refused.status == 429
        assert b'"code":"rate_limited"' in (await refused.body()).replace(b" ", b"")

        # another user of the same organization is not affected by this user's cap
        editor = await Conn.open("GET", events_url(world, job), api=world.api("editor"))
        assert editor.status == 200

        await first.disconnect()  # the browser closed the EventSource ...
        again = await Conn.open("GET", events_url(world, job), api=api)
        assert again.status == 200  # ... and the slot is back
        for conn in (second, editor, again):
            await conn.disconnect()
        # everything released: the full allowance is available once more
        refill = [
            await Conn.open("GET", events_url(world, job), api=api) for _ in range(2)
        ]
        assert [c.status for c in refill] == [200, 200]
        for conn in refill:
            await conn.disconnect()

    run(scenario)


def test_the_per_organization_cap_is_a_429_for_every_member(
    world: World, job: Job, settings: Any
) -> None:
    settings.UADAS_API = {**FAST, "stream_user_cap": 5, "stream_org_cap": 2}

    async def scenario() -> None:
        one = await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
        two = await Conn.open("GET", events_url(world, job), api=world.api("editor"))
        assert one.status == two.status == 200
        refused = await Conn.open("GET", events_url(world, job), api=world.api("admin"))
        assert refused.status == 429
        await one.disconnect()
        free = await Conn.open("GET", events_url(world, job), api=world.api("admin"))
        assert free.status == 200  # the twin, once a slot is released
        for conn in (two, free):
            await conn.disconnect()

    run(scenario)


def test_every_way_a_stream_can_end_releases_its_slot(
    world: World, job: Job, settings: Any
) -> None:
    """Terminal close, hard maximum, a deleted job and a disconnect each give the single slot back."""
    settings.UADAS_API = {**FAST, "stream_user_cap": 1, "sse_max_seconds": 0.5}

    async def scenario() -> None:
        api = world.api("viewer")

        async def slot_is_free() -> None:
            probe = await Conn.open("GET", events_url(world, job), api=api)
            assert probe.status == 200, "the previous stream leaked its slot"
            await probe.disconnect()

        conn = await Conn.open("GET", events_url(world, job), api=api)
        await conn.body()  # the hard maximum
        await slot_is_free()

        deleted = await db(
            lambda: factory_for(Job).create(world.org, project=world.project)
        )
        conn = await Conn.open("GET", events_url(world, deleted), api=api)
        await conn.until(b"event: job")
        await db(lambda: Job.objects.filter(pk=deleted.pk).delete())
        await asyncio.wait_for(conn.body(), 5)  # the job vanished: the stream ends
        await slot_is_free()

        finishing = await db(
            lambda: factory_for(Job).create(world.org, project=world.project)
        )
        conn = await Conn.open("GET", events_url(world, finishing), api=api)
        await conn.until(b"event: job")
        await db(lambda: set_state(finishing, "succeeded", 100))
        await conn.body()  # the terminal state
        await slot_is_free()

    run(scenario)


# --------------------------------------------------------------------- connections


def test_open_streams_hold_no_database_connection_while_they_sleep(
    world: World, job: Job, settings: Any
) -> None:
    if connection.vendor != "postgresql":
        if (
            os.environ.get("CI", "").lower() == "true"
        ):  # CI must not lose its leak proof
            pytest.fail(
                "the connection-leak test needs PostgreSQL (DATABASE_URL) in CI"
            )
        pytest.skip("counting server-side connections needs PostgreSQL")
    settings.UADAS_API = {
        **FAST,
        "sse_poll_seconds": 0.5,
        "sse_poll_max_seconds": 0.5,
        "stream_user_cap": 20,
    }
    streams = 8

    def backends() -> int:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND backend_type = 'client backend'"
            )
            return int(cursor.fetchone()[0])

    async def scenario() -> None:
        baseline = await asyncio.to_thread(backends)
        conns = [
            await Conn.open("GET", events_url(world, job), api=world.api("viewer"))
            for _ in range(streams)
        ]
        for conn in conns:
            await conn.until(b"event: job")
        await asyncio.sleep(0.2)  # every stream is now asleep between polls
        during = await asyncio.to_thread(backends)
        # a leak is one connection per stream; the allowance covers a poll that is mid-query
        assert during <= baseline + 2, (baseline, during, streams)
        for conn in conns:
            await conn.disconnect()
        await asyncio.sleep(0.2)
        assert await asyncio.to_thread(backends) <= baseline + 1

    run(scenario)
