# File: tests/ai/test_llm_provider.py
"""Tests for src.ai.llm_provider.create_provider().

create_provider()'s own docstring (read in full before writing this
file) documents exactly three accepted identifier strings — "anthropic",
"gemini", "groq" — and states it raises ServiceError for anything else.
Each provider's __init__ only constructs its underlying SDK client
object (``anthropic.Anthropic(...)``, ``genai.Client(...)``,
``openai.OpenAI(...)``) and stores config; none of the three SDKs used
here make a network call at client-construction time (confirmed by
reading each __init__ in src/ai/llm_provider.py: every one just stores
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

import pytest

from src.ai.llm_provider import (
    AnthropicProvider,
    BaseLLMProvider,
    GeminiProvider,
    GroqProvider,
    create_provider,
)
from src.core.exceptions import ServiceError

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
