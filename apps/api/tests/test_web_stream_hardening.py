# File: apps/api/tests/test_web_stream_hardening.py
"""Review fixes for 3.7: leaked slots, abandoned provider threads, counter expiry, event sizes.

Each test reproduces a defect an independent security review found and has a positive twin (the
same scenario without the fault succeeds), so the guard is the fix and not a refusal of everything:

* a client that disconnects while the request is still being opened must not leave a stream slot held
  (the slot used to be taken in a worker thread whose result a cancelled handler dropped);
* an assistant turn whose client left keeps its slot -- and its place among the process's bounded
  provider threads -- until the provider call really ends, then frees both;
* the per-user throttle also counts across organizations;
* a stream-cap counter does not expire while streams are open;
* a reply is split by *encoded* size (an emoji costs 12 bytes), and nested SDK argument containers
  survive instead of being counted as dropped.
"""

from __future__ import annotations

import asyncio
import collections.abc
import json
import threading
import time
from typing import Any

import pytest
from asgi_support import Conn, sse_events
from factories import factory_for
from test_web_assistant import SECRET, FakeProvider, ask, url, use
from test_web_streaming import FAST, events_url, run
from web_support import World, make_world

from uadas_api.accounts.models import Role
from uadas_api.ai import assistant
from uadas_api.jobs.models import Job
from uadas_api.web import assistant as web_assistant
from uadas_api.web import job_events, streams
from uadas_core.ai.llm_provider import LLMTurn, PendingToolCall

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def world(settings: Any) -> World:
    settings.UADAS_API = dict(FAST)
    settings.UADAS_ASSISTANT = {"provider": "anthropic", "api_key": SECRET, "model": ""}
    built = make_world()
    for who in ("owner", "admin", "editor", "viewer", "other", "outsider"):
        built.api(who)
    return built


@pytest.fixture
def job(world: World) -> Job:
    return factory_for(Job).create(world.org, project=world.project)


def slow(monkeypatch: pytest.MonkeyPatch, module: Any, seconds: float) -> Any:
    """Make ``module._open`` (the thread that opens a request) take ``seconds``; returns the original."""
    real = module._open

    def delayed(*args: Any, **kwargs: Any) -> Any:
        time.sleep(seconds)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "_open", delayed)
    return real


# ------------------------------------------------------------ 1. disconnect while opening


def test_a_job_stream_client_that_leaves_while_the_request_opens_leaks_no_slot(
    world: World, job: Job, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.UADAS_API = {**FAST, "stream_user_cap": 1, "stream_org_cap": 1}
    real = slow(monkeypatch, job_events, 0.4)

    async def scenario() -> None:
        api = world.api("viewer")
        gone = await Conn.open("GET", events_url(world, job), api=api, wait_head=False)
        await asyncio.sleep(0.15)  # the handler is inside the slowed open
        await gone.disconnect()
        await asyncio.sleep(0.6)  # the abandoned open has finished by now
        monkeypatch.setattr(job_events, "_open", real)
        # the twin: nothing is held, so the one allowed stream opens, and a second is the cap
        first = await Conn.open("GET", events_url(world, job), api=api)
        assert first.status == 200, "a vanished client leaked its stream slot"
        second = await Conn.open("GET", events_url(world, job), api=api)
        assert second.status == 429
        await first.disconnect()

    run(scenario)


def test_an_assistant_client_that_leaves_while_the_request_opens_leaks_no_slot(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.UADAS_API = {**FAST, "assistant_user_cap": 1, "assistant_org_cap": 1}
    use(monkeypatch, FakeProvider())
    real = slow(monkeypatch, web_assistant, 0.4)

    async def scenario() -> None:
        api = world.api("editor")
        gone = await Conn.open(
            "POST", url(world), api=api, body={"message": "hi"}, wait_head=False
        )
        await asyncio.sleep(0.15)
        await gone.disconnect()
        await asyncio.sleep(0.6)
        monkeypatch.setattr(web_assistant, "_open", real)
        ok = await Conn.open("POST", url(world), api=api, body={"message": "hi"})
        assert ok.status == 200, "a vanished client leaked its assistant slot"
        assert b"event: done" in await ok.body()

    run(scenario)


# ------------------------------------------------------------ 2. abandoned provider threads


def _wait_until_served(world: World, deadline: float = 8.0) -> bool:
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if ask(world)[0] == 200:
            return True
        time.sleep(0.1)
    return False


def test_an_abandoned_turn_keeps_its_slot_until_the_provider_call_ends(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.UADAS_API = {**FAST, "assistant_user_cap": 1, "assistant_org_cap": 5}
    gate = threading.Event()
    use(monkeypatch, FakeProvider(gate=gate))

    async def scenario() -> None:
        api = world.api("editor")
        first = await Conn.open("POST", url(world), api=api, body={"message": "one"})
        await first.until(b": open")
        await asyncio.sleep(0.2)  # the provider call is running on its thread
        await first.disconnect()  # the client left; the thread cannot be interrupted
        again = await Conn.open("POST", url(world), api=api, body={"message": "two"})
        assert (
            again.status == 429
        ), "the slot was freed while the provider thread still ran"
        gate.set()  # the call ends ...

    try:
        run(scenario)
    finally:
        gate.set()
    use(monkeypatch, FakeProvider())
    assert _wait_until_served(world), "the slot was not released when the thread ended"


def test_provider_calls_in_flight_are_bounded_process_wide(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.UADAS_API = {
        **FAST,
        "assistant_max_inflight": 1,
        "assistant_user_cap": 5,
        "assistant_org_cap": 5,
    }
    gate = threading.Event()
    use(monkeypatch, FakeProvider(gate=gate))

    async def scenario() -> None:
        busy = await Conn.open(
            "POST", url(world), api=world.api("editor"), body={"message": "a"}
        )
        await busy.until(b": open")
        await asyncio.sleep(0.2)
        refused = await Conn.open(
            "POST", url(world), api=world.api("admin"), body={"message": "b"}
        )
        assert refused.status == 503
        assert b'"code":"unavailable"' in (await refused.body()).replace(b" ", b"")
        gate.set()
        await busy.body()

    try:
        run(scenario)
    finally:
        gate.set()
    use(monkeypatch, FakeProvider())
    assert _wait_until_served(world)  # the twin: the pool is free again


def test_the_provider_is_called_with_the_configured_time_limit(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.UADAS_API = {**FAST, "assistant_provider_seconds": 12.5}
    seen: list[float | None] = []

    def factory(timeout: float | None = None) -> FakeProvider:
        seen.append(timeout)
        return FakeProvider()

    monkeypatch.setattr(assistant, "make_provider", factory)
    assert ask(world)[0] == 200 and seen == [12.5]
    captured: list[tuple[Any, ...]] = []
    monkeypatch.undo()

    def fake_create(*args: Any, **kwargs: Any) -> FakeProvider:
        captured.append((args, kwargs))
        return FakeProvider()

    monkeypatch.setattr(assistant, "create_provider", fake_create)
    assistant.make_provider(7)
    assert captured[0][1]["timeout"] == 7 and captured[0][0][1] == SECRET


def test_the_assistant_budget_is_also_per_user_across_organizations(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.UADAS_API = {
        **FAST,
        "throttles": {"assistant": "100/60", "assistant_user": "2/60"},
    }
    use(monkeypatch, FakeProvider())
    editor = world.editor.user
    join_other = world.other_org
    from uadas_api.accounts.models import Membership

    Membership.objects.create(user=editor, organization=join_other, role=Role.EDITOR)
    other_url = url(world, other=True)

    async def post(target: str, who: str) -> int:
        conn = await Conn.open(
            "POST", target, api=world.api(who), body={"message": "hi"}
        )
        await conn.body()
        return conn.status

    async def scenario() -> None:
        assert await post(url(world), "editor") == 200
        assert await post(other_url, "editor") == 200
        assert (
            await post(url(world), "editor") == 429
        )  # the per-organization budgets are untouched
        assert (
            await post(url(world), "admin") == 200
        )  # the twin: another user has their own budget

    run(scenario)


# ------------------------------------------------------------ 3. counter expiry


def test_a_counter_with_open_streams_does_not_expire_after_its_creation_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    from django.core.cache import (  # noqa: F401 - the default (locmem) cache is what is aged
        cache,
    )

    from uadas_api.web.errors import ApiError

    offset = [0.0]
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + offset[0])
    user, org = uuid.uuid4(), uuid.uuid4()

    def take() -> streams.StreamLease:
        return streams.acquire(
            "job", user, org, user_cap=2, org_cap=9, max_seconds=100
        )  # ttl 260 s

    first = take()
    offset[0] = 200  # inside the ttl: opening another refreshes the counter's expiry
    second = take()
    offset[0] = (
        400  # past the first slot's creation + 260 s, within the refreshed window
    )
    with pytest.raises(ApiError) as refused:
        take()
    assert (
        refused.value.status_code == 429
    ), "the counter expired under two open streams"
    first.release()
    second.release()
    take()  # the twin: released slots are reusable


# ------------------------------------------------------------ 4. event sizes and argument shapes


def test_a_reply_is_split_by_encoded_size_so_no_part_exceeds_the_event_cap() -> None:
    emoji = "\U0001f600" * 8_000  # 12 bytes each once JSON-escaped: 96 KB in one part
    parts = assistant.split_message(emoji, 64 * 1024)
    assert "".join(parts) == emoji and len(parts) >= 2
    for part in parts:
        frame = f'event: message\ndata: {json.dumps({"index": 0, "text": part})}\n\n'
        assert len(frame.encode()) <= 64 * 1024
    ascii_text = (
        "a" * 20_000
    )  # the twin: plain text still splits by the character limit
    plain = assistant.split_message(ascii_text, 64 * 1024)
    assert [len(p) for p in plain] == [8_000, 8_000, 4_000]
    assert assistant.split_message("", 64 * 1024) == []


def test_an_emoji_heavy_reply_streams_whole_with_no_error(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    emoji = "\U0001f600" * 8_000
    use(monkeypatch, FakeProvider(LLMTurn(emoji, [])))
    status, body = ask(world)
    frames = sse_events(body)
    assert status == 200 and [f["event"] for f in frames][-1] == "done"
    assert (
        "".join(f["data"]["text"] for f in frames if f["event"] == "message") == emoji
    )


class FakeMap(collections.abc.MutableMapping):  # type: ignore[type-arg, unused-ignore]
    """Stands in for protobuf's MapComposite: a mapping that is not a ``dict``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._d = data

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._d[key] = value

    def __delitem__(self, key: str) -> None:
        del self._d[key]

    def __iter__(self) -> Any:
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)


class FakeRepeated(collections.abc.Sequence):  # type: ignore[type-arg, unused-ignore]
    """Stands in for protobuf's RepeatedComposite: a sequence that is not a ``list``."""

    def __init__(self, items: list[Any]) -> None:
        self._i = items

    def __getitem__(self, index: Any) -> Any:
        return self._i[index]

    def __len__(self) -> int:
        return len(self._i)


def test_nested_sdk_containers_in_tool_arguments_are_kept_not_dropped(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = FakeMap(
        {"columns": FakeRepeated(["a", FakeMap({"b": 1})]), "odd": object()}
    )
    use(monkeypatch, FakeProvider(LLMTurn("ok", [PendingToolCall("c1", "drop_missing_values", nested)])))  # type: ignore[arg-type, unused-ignore]
    frames = sse_events(ask(world)[1])
    (call,) = [f["data"] for f in frames if f["event"] == "tool_call"]
    assert call["arguments"]["columns"] == ["a", {"b": 1}]
    assert isinstance(
        call["arguments"]["odd"], str
    )  # an unknown object is its (bounded) text
    assert frames[-1]["data"] == {"tool_calls": 1, "dropped": 0}


def test_to_jsonable_caps_depth_and_passes_scalars_through() -> None:
    deep: Any = "x"
    for _ in range(30):
        deep = [deep]
    json.dumps(assistant.to_jsonable(deep))  # terminates and serialises
    assert assistant.to_jsonable(
        {"n": 1, "f": 1.5, "b": True, "z": None, "s": "t"}
    ) == {
        "n": 1,
        "f": 1.5,
        "b": True,
        "z": None,
        "s": "t",
    }
