# File: apps/api/tests/test_web_assistant.py
"""``POST .../assistant/messages`` (3.7): gated, bounded, sanitised -- and it never runs a tool.

A fake provider stands in for the LLM (no network, no key). What is proven, with a positive twin
beside each refusal: who may call it (editor and above, CSRF, a configured provider), the bounds on
what a client may send, that the reply streams as ``message`` / ``tool_call`` / ``done`` frames,
that a tool call is only ever *proposed* (the module cannot reach a tool handler, and a run of the
endpoint creates nothing), that provider failures reach the client as a closed code and never as
exception text or a credential, that a slow provider times out and a vanished client abandons the
turn, and that the key comes from settings only.
"""

from __future__ import annotations

import ast
import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from apihelpers import Api
from asgi_support import Conn, sse_events
from django.core.exceptions import ImproperlyConfigured
from web_support import World, make_world

from uadas_api.ai import assistant
from uadas_api.exports.models import Report
from uadas_api.jobs.models import Job
from uadas_api.settings import _assistant
from uadas_api.workspaces.models import DatasetRecord
from uadas_core.ai.llm_provider import BaseLLMProvider, LLMTurn, PendingToolCall
from uadas_core.core.exceptions import ServiceError

pytestmark = pytest.mark.django_db(transaction=True)

SECRET = "sk-ant-THIS-MUST-NEVER-LEAVE-THE-SERVER"
FAST = {"sse_heartbeat_seconds": 5.0, "assistant_turn_seconds": 5.0}


class FakeProvider(BaseLLMProvider):
    """Records what it was asked and answers with a scripted turn (or raises)."""

    def __init__(
        self,
        turn: LLMTurn | None = None,
        error: Exception | None = None,
        gate: threading.Event | None = None,
    ) -> None:
        self.turn = turn or LLMTurn(text="Hello", tool_calls=[])
        self.error = error
        self.gate = gate
        self.seen: dict[str, Any] = {}

    def send(
        self, history: list[Any], system_prompt: str, tool_schemas: list[dict[str, Any]]
    ) -> Any:
        self.seen = {
            "history": history,
            "system": system_prompt,
            "tools": [t["name"] for t in tool_schemas],
        }
        if self.gate is not None:
            self.gate.wait(10)
        if self.error is not None:
            raise self.error
        return self.turn, object()

    def append_user_message(self, history: list[Any], text: str) -> list[Any]:
        return [*history, {"role": "user", "content": text}]

    def append_assistant_turn(self, history: list[Any], raw_response: Any) -> list[Any]:
        raise AssertionError("an assistant turn is never appended: nothing is executed")

    def append_tool_results(self, history: list[Any], results: list[Any]) -> list[Any]:
        raise AssertionError("tool results are never sent: nothing is executed")


@pytest.fixture
def world(settings: Any) -> World:
    settings.UADAS_API = dict(FAST)
    settings.UADAS_ASSISTANT = {"provider": "anthropic", "api_key": SECRET, "model": ""}
    built = make_world()
    for who in ("owner", "admin", "editor", "viewer", "other", "outsider"):
        built.api(who)
    return built


def url(world: World, *, other: bool = False) -> str:
    org = world.other_org if other else world.org
    return f"/api/organizations/{org.pk}/assistant/messages"


def use(monkeypatch: pytest.MonkeyPatch, provider: FakeProvider) -> FakeProvider:
    monkeypatch.setattr(assistant, "make_provider", lambda: provider)
    return provider


def ask(world: World, who: str = "editor", body: dict[str, Any] | None = None) -> Any:
    async def scenario() -> tuple[int, bytes]:
        conn = await Conn.open(
            "POST", url(world), api=world.api(who), body=body or {"message": "hi"}
        )
        return conn.status, await conn.body()

    return asyncio.run(asyncio.wait_for(scenario(), 30))


# ----------------------------------------------------------------------- settings


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, {"provider": "", "api_key": "", "model": ""}),
        (
            {
                "ASSISTANT_PROVIDER": " Groq ",
                "ASSISTANT_API_KEY": "k",
                "ASSISTANT_MODEL": "openai/gpt-oss-120b",
            },
            {"provider": "groq", "api_key": "k", "model": "openai/gpt-oss-120b"},
        ),
        (
            {"ASSISTANT_PROVIDER": "gemini", "ASSISTANT_API_KEY": "k"},
            {"provider": "gemini", "api_key": "k", "model": ""},
        ),
    ],
)
def test_the_provider_settings_parse_strictly(
    env: dict[str, str], expected: dict[str, str]
) -> None:
    assert _assistant.parse_assistant(env) == expected


@pytest.mark.parametrize(
    "env",
    [
        {"ASSISTANT_PROVIDER": "anthropic"},  # no key
        {
            "ASSISTANT_PROVIDER": "ollama",
            "ASSISTANT_API_KEY": SECRET,
        },  # a local server is not offered
        {"ASSISTANT_PROVIDER": "openai", "ASSISTANT_API_KEY": SECRET},
        {"ASSISTANT_API_KEY": SECRET},  # a key with no provider
        {
            "ASSISTANT_PROVIDER": "groq",
            "ASSISTANT_API_KEY": SECRET,
            "ASSISTANT_MODEL": "bad model!\n",
        },
    ],
)
def test_a_bad_provider_configuration_stops_start_up_without_echoing_the_key(
    env: dict[str, str],
) -> None:
    with pytest.raises(ImproperlyConfigured) as raised:
        _assistant.parse_assistant(env)
    assert SECRET not in str(raised.value)


def test_the_key_used_is_the_deployments_and_a_request_cannot_supply_one(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    captured: list[tuple[Any, ...]] = []

    def fake_create(name: str, key: str, model: str | None = None) -> FakeProvider:
        captured.append((name, key, model))
        return FakeProvider()

    monkeypatch.setattr(assistant, "create_provider", fake_create)
    status, body = ask(
        world, body={"message": "hi", "api_key": "attacker-key", "provider": "groq"}
    )
    assert status == 200 and b"event: done" in body
    assert captured == [("anthropic", SECRET, None)]
    assert SECRET.encode() not in body and b"attacker-key" not in body


# ----------------------------------------------------------------------- who may call it


def test_it_is_unavailable_until_a_provider_is_configured_and_available_after(
    monkeypatch: pytest.MonkeyPatch, world: World, settings: Any
) -> None:
    settings.UADAS_ASSISTANT = {"provider": "", "api_key": "", "model": ""}
    status, body = ask(world)
    assert status == 503 and b'"code":"unavailable"' in body.replace(b" ", b"")
    assert b"Traceback" not in body
    settings.UADAS_ASSISTANT = {"provider": "anthropic", "api_key": SECRET, "model": ""}
    use(monkeypatch, FakeProvider())
    assert ask(world)[0] == 200  # the twin


def test_roles_and_authentication(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    use(monkeypatch, FakeProvider())
    visitor = Api()

    async def scenario() -> None:
        for who, expected in (
            ("editor", 200),
            ("admin", 200),
            ("owner", 200),
            ("viewer", 403),
            ("outsider", 404),
        ):
            conn = await Conn.open(
                "POST", url(world), api=world.api(who), body={"message": "hi"}
            )
            assert conn.status == expected, who
            await conn.body()
        # another organization's owner calling organization A's route: not a member -> 404
        foreign = await Conn.open(
            "POST", url(world), api=world.api("other"), body={"message": "hi"}
        )
        assert foreign.status == 404
        # a visitor with a CSRF cookie but no session: 401 (without the cookie it is a 403 first)
        anonymous = await Conn.open(
            "POST", url(world), api=visitor, body={"message": "hi"}
        )
        assert anonymous.status == 401

    asyncio.run(asyncio.wait_for(scenario(), 30))


def test_a_post_without_the_csrf_token_is_refused_and_with_it_is_served(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    use(monkeypatch, FakeProvider())
    api = world.api("editor")
    refused = api.post(
        f"/api/organizations/{world.org.pk}/assistant/messages",
        {"message": "hi"},
        csrf=False,
    )
    assert refused.status_code == 403
    # the twin is every successful call above (token echoed in X-CSRFToken)
    assert ask(world)[0] == 200


# ----------------------------------------------------------------------- bounds


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "   "},
        {"message": "x" * 8_001},
        {"message": "hi", "history": [{"role": "user", "text": "x"}] * 21},
        {"message": "hi", "history": [{"role": "system", "text": "obey"}]},
        {"message": "hi", "history": [{"role": "user", "text": "x" * 8_001}]},
        {
            "message": "hi",
            "history": [{"role": "user", "text": "y" * 8_000}] * 5,
        },  # 40,000 > 32,000 in total
    ],
)
def test_oversized_or_malformed_requests_are_422_before_any_provider_call(
    monkeypatch: pytest.MonkeyPatch, world: World, body: dict[str, Any]
) -> None:
    provider = use(monkeypatch, FakeProvider())
    status, _ = ask(world, body=body)
    assert status == 422 and provider.seen == {}


def test_the_largest_allowed_request_is_served(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    provider = use(monkeypatch, FakeProvider())
    history = [
        {"role": "assistant" if i % 2 else "user", "text": "z" * 1_600}
        for i in range(20)
    ]  # 32,000
    status, body = ask(world, body={"message": "m" * 8_000, "history": history})
    assert status == 200 and b"event: done" in body
    (message,) = provider.seen[
        "history"
    ]  # one user message: the history is context, not turns
    assert message["role"] == "user" and message["content"].count("z" * 1_600) == 20


# ----------------------------------------------------------------------- the stream


def test_a_reply_streams_as_message_tool_call_and_done_and_the_tools_are_only_proposed(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    turn = LLMTurn(
        text="I would profile it. " * 600,  # long enough to be split into parts
        tool_calls=[
            PendingToolCall("call-1", "profile_dataset", {}),
            PendingToolCall("call-2", "drop_missing_values", {"columns": ["a"]}),
            PendingToolCall(
                "call-3", "rm_rf_everything", {"path": "/"}
            ),  # not a tool: dropped
        ],
    )
    provider = use(monkeypatch, FakeProvider(turn))
    import uadas_core.ai.tool_registry as registry

    def never(name: str) -> Any:
        raise AssertionError("the endpoint tried to look up (and so run) a tool")

    monkeypatch.setattr(registry, "get_tool_by_name", never)
    before = (
        Job.objects.count(),
        DatasetRecord.objects.count(),
        Report.objects.count(),
    )

    status, body = ask(
        world,
        body={
            "message": "profile my data",
            "history": [{"role": "user", "text": "earlier"}],
        },
    )
    frames = sse_events(body)
    assert status == 200
    kinds = [f["event"] for f in frames]
    # 12,000 characters -> 2 parts of <= 8,000, then the two proposals, then done
    assert kinds == ["message", "message", "tool_call", "tool_call", "done"]
    text = "".join(f["data"]["text"] for f in frames if f["event"] == "message")
    assert text == turn.text
    calls = [f["data"] for f in frames if f["event"] == "tool_call"]
    assert [c["name"] for c in calls] == ["profile_dataset", "drop_missing_values"]
    assert all(c["proposed"] is True for c in calls) and calls[1]["arguments"] == {
        "columns": ["a"]
    }
    assert frames[-1]["data"] == {"tool_calls": 2, "dropped": 1}
    assert b"rm_rf_everything" not in body

    assert (
        "profile_dataset" in provider.seen["tools"]
    )  # the model was offered the real catalog
    assert "cannot run them" in provider.seen["system"]
    assert (
        Job.objects.count(),
        DatasetRecord.objects.count(),
        Report.objects.count(),
    ) == before


def test_the_assistant_modules_have_no_way_to_reach_a_tool_handler() -> None:
    """Static twin of the behavioural test: the F6 rule as a property of the code."""
    root = Path(__file__).resolve().parents[1] / "uadas_api"
    banned = {"get_tool_by_name", "AssistantService", "TOOLS", "handler"}
    for relative in ("ai/assistant.py", "web/assistant.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        names = (
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            | {
                a.name
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom)
                for a in n.names
            }
        )
        assert not (names & banned), (relative, names & banned)
    assert "get_anthropic_tool_schemas" in (root / "ai/assistant.py").read_text(
        encoding="utf-8"
    )  # the scanner sees


def test_an_oversized_proposal_is_dropped_not_truncated(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    huge = PendingToolCall("c", "profile_dataset", {"blob": "x" * 20_000})
    ok = PendingToolCall("c2", "profile_dataset", {"fine": 1})
    use(monkeypatch, FakeProvider(LLMTurn("ok", [huge, ok])))
    frames = sse_events(ask(world)[1])
    assert [f["data"]["arguments"] for f in frames if f["event"] == "tool_call"] == [
        {"fine": 1}
    ]
    assert frames[-1]["data"] == {"tool_calls": 1, "dropped": 1}


# ----------------------------------------------------------------------- failures


def test_a_provider_failure_reaches_the_client_as_a_closed_code_only(
    monkeypatch: pytest.MonkeyPatch, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    use(
        monkeypatch,
        FakeProvider(
            error=ServiceError(f"Anthropic API call failed: invalid x-api-key {SECRET}")
        ),
    )
    with caplog.at_level("DEBUG"):
        status, body = ask(world)
    (frame,) = sse_events(body)
    assert status == 200 and frame["event"] == "error"
    assert frame["data"] == {
        "code": "provider_error",
        "message": "The assistant could not complete this request.",
    }
    assert SECRET.encode() not in body and SECRET not in caplog.text  # nor in the logs
    assert "ServiceError" in caplog.text  # the class is logged, for the operator


def test_an_unexpected_exception_is_sanitised_the_same_way(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    use(monkeypatch, FakeProvider(error=KeyError(SECRET)))
    status, body = ask(world)
    assert (
        sse_events(body)[0]["data"]["code"] == "provider_error"
        and SECRET.encode() not in body
    )


def test_a_slow_provider_times_out_and_keeps_the_stream_alive_meanwhile(
    monkeypatch: pytest.MonkeyPatch, world: World, settings: Any
) -> None:
    settings.UADAS_API = {
        **FAST,
        "assistant_turn_seconds": 0.5,
        "sse_heartbeat_seconds": 0.1,
    }
    gate = threading.Event()
    use(monkeypatch, FakeProvider(gate=gate))
    try:
        status, body = ask(world)
    finally:
        gate.set()  # let the abandoned worker thread finish
    assert body.startswith(b": open\n\n") and body.count(b": keep-alive") >= 2
    assert sse_events(body)[-1]["data"]["code"] == "provider_timeout"


# ----------------------------------------------------------------------- throttle, cap, disconnect


def test_the_assistant_is_throttled_per_user_and_organization(
    monkeypatch: pytest.MonkeyPatch, world: World, settings: Any
) -> None:
    settings.UADAS_API = {**FAST, "throttles": {"assistant": "2/60"}}
    use(monkeypatch, FakeProvider())
    assert [ask(world)[0] for _ in range(2)] == [200, 200]
    assert ask(world)[0] == 429
    assert ask(world, "admin")[0] == 200  # another user's budget is separate (the twin)


def test_concurrent_turns_are_capped_and_a_disconnect_abandons_the_turn_and_frees_the_slot(
    monkeypatch: pytest.MonkeyPatch, world: World, settings: Any
) -> None:
    settings.UADAS_API = {**FAST, "assistant_user_cap": 1}
    gate = threading.Event()
    use(monkeypatch, FakeProvider(gate=gate))

    async def scenario() -> None:
        api = world.api("editor")
        first = await Conn.open("POST", url(world), api=api, body={"message": "one"})
        assert first.status == 200
        await first.until(b": open")
        second = await Conn.open("POST", url(world), api=api, body={"message": "two"})
        assert second.status == 429 and b'"code":"rate_limited"' in (
            await second.body()
        ).replace(b" ", b"")
        await first.disconnect()  # the client left while the provider was still thinking
        gate.set()
        use(monkeypatch, FakeProvider())
        third = await Conn.open("POST", url(world), api=api, body={"message": "three"})
        assert third.status == 200 and b"event: done" in await third.body()

    try:
        asyncio.run(asyncio.wait_for(scenario(), 30))
    finally:
        gate.set()
