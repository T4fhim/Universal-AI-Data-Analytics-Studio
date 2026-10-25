# File: tests/ai/test_llm_provider.py
"""Tests for uadas_core.ai.llm_provider.create_provider().

create_provider()'s own docstring (read in full before writing this
file) documents exactly three accepted identifier strings — "anthropic",
"gemini", "groq" — and states it raises ServiceError for anything else.
Each provider's __init__ only constructs its underlying SDK client
object (``anthropic.Anthropic(...)``, ``genai.Client(...)``,
``openai.OpenAI(...)``) and stores config; none of the three SDKs used
here make a network call at client-construction time (confirmed by
reading each __init__ in uadas_core/ai/llm_provider.py: every one just stores
a client handle, a model name string, and — for GroqProvider — the
base_url string. No ``.models.list()``/handshake/auth-check call
happens during __init__), so constructing each provider with an
obviously-fake key is safe to do directly, without mocking the SDK
constructors, and confirms create_provider() wires the right concrete
class to the right identifier without ever reaching the network.

SECRET HYGIENE: every key string below is an obviously-fake
placeholder (e.g. "sk-test-not-a-real-key"), never a real credential.
Per this work item's instructions: .claude/hooks/protect-files.ps1
only blocks writes by filename pattern (.env*, secrets.json,
credentials.json, *.pem, *.key); it does not scan file content for
secret-shaped strings, so this file's safety is enforced by careful
authoring alone, not by that hook.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from uadas_core.ai.llm_provider import (
    AnthropicProvider,
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    LLMTurn,
    LLMUsage,
    OllamaProvider,
    OpenRouterProvider,
    create_provider,
)
from uadas_core.core.exceptions import ServiceError

_FAKE_ANTHROPIC_KEY = "sk-ant-test-not-a-real-key"
_FAKE_GEMINI_KEY = "test-not-a-real-gemini-key"
_FAKE_GROQ_KEY = "gsk-test-not-a-real-key"


def test_create_provider_anthropic_returns_anthropic_provider_without_network_call() -> (
    None
):
    provider = create_provider("anthropic", _FAKE_ANTHROPIC_KEY)
    assert isinstance(provider, AnthropicProvider)
    assert isinstance(provider, BaseLLMProvider)


def test_create_provider_gemini_returns_gemini_provider_without_network_call() -> None:
    provider = create_provider("gemini", _FAKE_GEMINI_KEY)
    assert isinstance(provider, GeminiProvider)
    assert isinstance(provider, BaseLLMProvider)


def test_create_provider_groq_returns_groq_provider_without_network_call() -> None:
    provider = create_provider("groq", _FAKE_GROQ_KEY)
    assert isinstance(provider, GroqProvider)
    assert isinstance(provider, BaseLLMProvider)
    # GroqProvider is documented as using the openai SDK pointed at
    # Groq's OpenAI-compatible endpoint, not a groq-specific SDK —
    # confirm that wiring directly rather than assuming it.
    assert provider._client.base_url is not None
    assert "groq.com" in str(provider._client.base_url)


def test_create_provider_rejects_unknown_provider_name() -> None:
    with pytest.raises(ServiceError, match="Unknown provider"):
        create_provider("openai", "sk-test-not-a-real-key")


def test_create_provider_error_message_lists_the_three_valid_identifiers() -> None:
    with pytest.raises(ServiceError) as excinfo:
        create_provider("not-a-real-provider", "sk-test-not-a-real-key")
    message = str(excinfo.value)
    assert "anthropic" in message
    assert "gemini" in message
    assert "groq" in message


# --- the bounded-call options the web server passes (Phase 3.7) --------------------------------
# A server must not let one provider call hold a worker thread for the SDKs' default (about ten
# minutes, with retries on top): ``timeout`` caps the call and turns the SDK's own retries off.
# Without ``timeout`` every provider keeps its desktop defaults (the twins below).


def test_anthropic_timeout_bounds_the_call_and_disables_sdk_retries() -> None:
    bounded = create_provider("anthropic", _FAKE_ANTHROPIC_KEY, timeout=30)
    assert bounded._client.timeout == 30 and bounded._client.max_retries == 0
    default = create_provider("anthropic", _FAKE_ANTHROPIC_KEY)
    assert default._client.max_retries == 2 and default._client.timeout != 30


def test_groq_timeout_bounds_the_call_and_disables_sdk_retries() -> None:
    bounded = create_provider("groq", _FAKE_GROQ_KEY, timeout=30)
    assert bounded._client.timeout == 30 and bounded._client.max_retries == 0
    default = create_provider("groq", _FAKE_GROQ_KEY)
    assert default._client.max_retries == 1 and default._client.timeout != 30


def test_gemini_timeout_is_passed_in_milliseconds_with_a_single_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google import genai

    seen: list[dict] = []

    def fake_client(**kwargs: object) -> object:
        seen.append(kwargs)
        return object()

    monkeypatch.setattr(genai, "Client", fake_client)
    create_provider("gemini", _FAKE_GEMINI_KEY, timeout=30)
    create_provider("gemini", _FAKE_GEMINI_KEY)
    bounded, default = seen
    assert bounded["http_options"].timeout == 30_000
    assert bounded["http_options"].retry_options.attempts == 1
    assert "http_options" not in default  # the twin: the desktop default is untouched


# --- OpenRouter: Groq's OpenAI-compatible wire format at another address (web-transition 3.7) ---
# OpenRouterProvider subclasses GroqProvider and changes only where it points, what it calls
# itself in errors and its default model. These pin that, and the twins show Groq is unchanged.

_FAKE_OPENROUTER_KEY = "sk-or-test-not-a-real-key"


def test_create_provider_openrouter_returns_an_openrouter_provider() -> None:
    provider = create_provider("openrouter", _FAKE_OPENROUTER_KEY)
    assert isinstance(provider, OpenRouterProvider)
    assert isinstance(provider, GroqProvider)  # the wire translation is Groq's, reused
    assert isinstance(provider, BaseLLMProvider)


def test_openrouter_points_at_openrouter_not_groq() -> None:
    provider = create_provider("openrouter", _FAKE_OPENROUTER_KEY)
    assert str(provider._client.base_url).startswith("https://openrouter.ai/api/v1")
    assert "groq.com" not in str(provider._client.base_url)
    # the twin: Groq still points at Groq
    groq = create_provider("groq", _FAKE_GROQ_KEY)
    assert "groq.com" in str(groq._client.base_url)
    assert "openrouter" not in str(groq._client.base_url)


def test_openrouter_has_its_own_default_model_and_accepts_an_override() -> None:
    default = create_provider("openrouter", _FAKE_OPENROUTER_KEY)
    assert default._model == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert default._model != create_provider("groq", _FAKE_GROQ_KEY)._model
    chosen = create_provider("openrouter", _FAKE_OPENROUTER_KEY, "vendor/some-model")
    assert chosen._model == "vendor/some-model"


def test_openrouter_timeout_bounds_the_call_and_disables_sdk_retries() -> None:
    bounded = create_provider("openrouter", _FAKE_OPENROUTER_KEY, timeout=30)
    assert bounded._client.timeout == 30 and bounded._client.max_retries == 0
    default = create_provider("openrouter", _FAKE_OPENROUTER_KEY)
    assert default._client.max_retries == 1 and default._client.timeout != 30


@pytest.mark.parametrize(
    ("name", "label"), [("openrouter", "OpenRouter"), ("groq", "Groq")]
)
def test_a_failed_call_names_the_provider_that_failed(name: str, label: str) -> None:
    provider = create_provider(name, _FAKE_OPENROUTER_KEY)

    def fail(**kwargs: Any) -> Any:
        raise provider._openai.OpenAIError("boom")

    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail))
    )
    with pytest.raises(ServiceError, match=f"^{label} API call failed"):
        provider.send([], "system", [])


@pytest.mark.parametrize(
    ("name", "label"), [("openrouter", "OpenRouter"), ("groq", "Groq")]
)
def test_malformed_tool_arguments_name_the_provider_too(name: str, label: str) -> None:
    provider = create_provider(name, _FAKE_OPENROUTER_KEY)
    call = SimpleNamespace(
        id="c1", function=SimpleNamespace(name="clean", arguments="{not json")
    )
    reply = SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[call]))
        ],
        usage=None,
    )
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: reply))
    )
    with pytest.raises(
        ServiceError, match=f"^{label} returned malformed tool arguments"
    ):
        provider.send([], "system", [])


def test_the_valid_identifier_message_lists_openrouter() -> None:
    with pytest.raises(ServiceError) as excinfo:
        create_provider("not-a-real-provider", "k")
    assert "openrouter" in str(excinfo.value)


# --- token usage on every turn (web-transition 3.8: the assistant is metered per organization) ---
# Each provider reports usage in its own place; ``LLMTurn.usage`` is the one neutral answer. ``None``
# means "the provider reported nothing" (the caller decides what that costs), never a made-up zero.


def test_usage_totals_input_and_output() -> None:
    usage = LLMUsage(input_tokens=120, output_tokens=30)
    assert usage.total == 150
    assert LLMUsage(0, 0).total == 0


def test_an_llm_turn_without_usage_defaults_to_none() -> None:
    assert LLMTurn(text="x", tool_calls=[]).usage is None


def _anthropic_reply(usage: Any) -> Any:
    block = SimpleNamespace(type="text", text="hello")
    return SimpleNamespace(content=[block], usage=usage)


def test_anthropic_reports_input_and_output_tokens() -> None:
    provider = create_provider("anthropic", _FAKE_ANTHROPIC_KEY)
    reply = _anthropic_reply(SimpleNamespace(input_tokens=11, output_tokens=4))
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **k: reply)
    )
    turn, _raw = provider.send([], "system", [])
    assert turn.usage == LLMUsage(11, 4)
    assert turn.text == "hello"


def test_anthropic_without_usage_is_none() -> None:
    provider = create_provider("anthropic", _FAKE_ANTHROPIC_KEY)
    reply = _anthropic_reply(None)
    provider._client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **k: reply)
    )
    assert provider.send([], "system", [])[0].usage is None


def _gemini_reply(metadata: Any) -> Any:
    part = SimpleNamespace(text="hello", function_call=None)
    candidate = SimpleNamespace(content=SimpleNamespace(parts=[part]))
    return SimpleNamespace(candidates=[candidate], usage_metadata=metadata)


def test_gemini_counts_thinking_tokens_as_output_via_the_total() -> None:
    provider = create_provider("gemini", _FAKE_GEMINI_KEY)
    reply = _gemini_reply(
        SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, total_token_count=17
        )
    )
    provider._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **k: reply)
    )
    usage = provider.send([], "system", [])[0].usage
    assert usage == LLMUsage(10, 7)  # 17 total: the 2 thinking tokens are billed output


def test_gemini_without_a_total_uses_the_candidate_count() -> None:
    provider = create_provider("gemini", _FAKE_GEMINI_KEY)
    reply = _gemini_reply(
        SimpleNamespace(
            prompt_token_count=10, candidates_token_count=5, total_token_count=None
        )
    )
    provider._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **k: reply)
    )
    assert provider.send([], "system", [])[0].usage == LLMUsage(10, 5)


def test_gemini_without_metadata_is_none() -> None:
    provider = create_provider("gemini", _FAKE_GEMINI_KEY)
    reply = _gemini_reply(None)
    provider._client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **k: reply)
    )
    assert provider.send([], "system", [])[0].usage is None


def _openai_reply(usage: Any) -> Any:
    message = SimpleNamespace(content="hello", tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


@pytest.mark.parametrize("name", ["groq", "openrouter"])
def test_openai_compatible_providers_report_prompt_and_completion_tokens(
    name: str,
) -> None:
    provider = create_provider(name, _FAKE_OPENROUTER_KEY)
    reply = _openai_reply(SimpleNamespace(prompt_tokens=21, completion_tokens=9))
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: reply))
    )
    assert provider.send([], "system", [])[0].usage == LLMUsage(21, 9)


@pytest.mark.parametrize("name", ["groq", "openrouter"])
def test_openai_compatible_providers_without_usage_are_none(name: str) -> None:
    provider = create_provider(name, _FAKE_OPENROUTER_KEY)
    reply = _openai_reply(None)
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: reply))
    )
    assert provider.send([], "system", [])[0].usage is None


@pytest.mark.parametrize("bad", [None, -5, True, "7", 3.5])
def test_a_junk_count_is_treated_as_zero_not_trusted(bad: Any) -> None:
    provider = create_provider("groq", _FAKE_GROQ_KEY)
    reply = _openai_reply(SimpleNamespace(prompt_tokens=bad, completion_tokens=4))
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: reply))
    )
    assert provider.send([], "system", [])[0].usage == LLMUsage(0, 4)


def test_ollama_reports_its_evaluation_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    payload = {
        "message": {"content": "hello"},
        "prompt_eval_count": 8,
        "eval_count": 3,
    }
    fake = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(requests, "post", lambda *a, **k: fake)
    provider = OllamaProvider()
    assert provider.send([], "system", [])[0].usage == LLMUsage(8, 3)
    del payload["eval_count"], payload["prompt_eval_count"]
    assert (
        provider.send([], "system", [])[0].usage is None
    )  # the twin: nothing reported
