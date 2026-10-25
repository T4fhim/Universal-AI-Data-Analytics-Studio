# File: apps/api/tests/test_web_assistant_quota.py
"""The assistant against the monthly LLM-token quota (3.8): refused up front, charged by what it cost.

Why: an LLM key bills a person, and the assistant is the one route where a tenant spends it. What is
proven, each with its positive twin: an organization that has used up its tokens is refused before
the provider is called; the turn that crosses the limit is allowed (usage is only known afterwards) and
the next is refused -- the documented one-turn overshoot, no more; the charge is what the provider
reported, or an estimate when it reported nothing (so silence is not a free ride); a turn that failed
charges nothing; and another organization's allowance is its own.
"""

from __future__ import annotations

from typing import Any

import pytest
from test_web_assistant import FakeProvider, ask, use
from web_support import World, make_world

from uadas_api.ai import assistant
from uadas_api.quotas import service as quotas
from uadas_api.quotas.choices import UsageKind
from uadas_api.quotas.models import UsageLedger
from uadas_core.ai.llm_provider import LLMTurn, LLMUsage
from uadas_core.core.exceptions import ServiceError

pytestmark = pytest.mark.django_db(transaction=True)

TOKENS = UsageKind.LLM_TOKENS.value
SECRET = "sk-ant-THIS-MUST-NEVER-LEAVE-THE-SERVER"


@pytest.fixture
def world(settings: Any) -> World:
    settings.UADAS_API = {"sse_heartbeat_seconds": 5.0, "assistant_turn_seconds": 5.0}
    settings.UADAS_ASSISTANT = {"provider": "anthropic", "api_key": SECRET, "model": ""}
    built = make_world()
    for who in ("owner", "admin", "editor", "viewer", "other", "outsider"):
        built.api(who)
    return built


def limit(settings: Any, tokens: int | None) -> None:
    settings.UADAS_QUOTA = {**settings.UADAS_QUOTA, "max_llm_tokens": tokens}


def used(world: World) -> int:
    return quotas.usage_for(world.org, TOKENS)


def reply(text: str = "Hello", usage: LLMUsage | None = None) -> FakeProvider:
    return FakeProvider(LLMTurn(text=text, tool_calls=[], usage=usage))


# ------------------------------------------------------------------- the pre-check


def test_an_organization_out_of_tokens_is_refused_before_the_provider_is_called(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = use(monkeypatch, reply())
    limit(settings, 100)
    quotas.charge(world.org, TOKENS, 100, "earlier")
    status, body = ask(world)
    assert status == 429 and b'"code":"quota_exceeded"' in body.replace(b" ", b"")
    assert b"assistant tokens" in body
    assert provider.seen == {}  # the provider was never asked
    assert used(world) == 100


def test_an_organization_with_tokens_left_is_answered(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = use(monkeypatch, reply(usage=LLMUsage(10, 5)))
    limit(settings, 100)
    quotas.charge(world.org, TOKENS, 99, "earlier")  # one token of room is room
    assert ask(world)[0] == 200
    assert provider.seen != {}


def test_another_organizations_tokens_are_not_mine(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, reply(usage=LLMUsage(1, 1)))
    limit(settings, 100)
    quotas.charge(world.other_org, TOKENS, 10**6, "someone-else")
    assert ask(world)[0] == 200


# ----------------------------------------------------------------------- charging


def test_a_turn_is_charged_what_the_provider_reported(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, reply(usage=LLMUsage(input_tokens=120, output_tokens=30)))
    assert ask(world)[0] == 200
    assert used(world) == 150
    entry = UsageLedger.objects.for_organization(world.org).get(kind=TOKENS)
    assert entry.source_key.startswith("assistant:") and entry.amount == 150


def test_a_provider_that_reports_nothing_is_still_metered_by_an_estimate(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, reply(text="x" * 400, usage=None))
    assert ask(world, body={"message": "y" * 400})[0] == 200
    assert used(world) == 200  # (400 + 400) characters / 4


def test_each_turn_is_its_own_charge(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, reply(usage=LLMUsage(10, 10)))
    ask(world)
    ask(world)
    assert used(world) == 40
    assert (
        UsageLedger.objects.for_organization(world.org).filter(kind=TOKENS).count() == 2
    )


def test_the_turn_that_crosses_the_limit_is_allowed_and_the_next_is_refused(
    world: World, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = use(monkeypatch, reply(usage=LLMUsage(300, 100)))
    limit(settings, 100)
    assert ask(world)[0] == 200  # 0 used: admitted; costs 400, well past the limit
    assert (
        used(world) == 400
    )  # recorded in full: the overshoot is one turn, never hidden
    provider.seen = {}
    status, _body = ask(world)
    assert status == 429 and provider.seen == {}


def test_a_failed_turn_charges_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(
        monkeypatch, FakeProvider(error=ServiceError("Anthropic API call failed: boom"))
    )
    status, body = ask(world)
    assert (
        status == 200 and b"provider_error" in body
    )  # the stream reports it as an event
    assert used(world) == 0 and not UsageLedger.objects.exists()


def test_a_billing_failure_does_not_fail_the_answered_turn(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    use(monkeypatch, reply(usage=LLMUsage(5, 5)))

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(quotas, "charge", broken)
    status, body = ask(world)
    assert status == 200 and b"event: done" in body and b"provider_error" not in body


# ----------------------------------------------------------------- the pure pieces


def test_turn_tokens_prefers_the_providers_count_over_the_estimate() -> None:
    reported = LLMTurn(text="x" * 4000, tool_calls=[], usage=LLMUsage(7, 3))
    assert assistant.turn_tokens(reported, "y" * 4000) == 10
    silent = LLMTurn(text="x" * 8, tool_calls=[], usage=None)
    assert assistant.turn_tokens(silent, "y" * 8) == 4
    assert assistant.turn_tokens(LLMTurn("", [], None), "") == 0


def test_charge_turn_ignores_a_zero_cost(world: World) -> None:
    assistant.charge_turn(world.org, 0)
    assert not UsageLedger.objects.exists()
    assistant.charge_turn(world.org, 3)
    assert used(world) == 3
