# File: src/ai/llm_provider.py
"""Provider abstraction: translates each SDK's own message/tool-call shape into one common format.

Anthropic and Gemini structure tool calls and tool results differently
at the wire level — confirmed directly against both SDKs before
writing this file, not assumed:

* Anthropic: a response's ``content`` is a list of blocks; a
  ``tool_use`` block has ``.name``/``.input``/``.id``. A tool result is
  sent back as a ``user`` message containing
  ``{"type": "tool_result", "tool_use_id": ..., "content": ...}``.
* Gemini: a response's candidate has ``.content.parts``; a part with
  ``.function_call`` set has ``.function_call.name``/``.args``. A tool
  result is sent back via
  ``types.Part.from_function_response(name=..., response={...})``.

Rather than let :class:`~src.ai.assistant_service.AssistantService`
branch on which provider is active, every provider implementation here
translates to and from one shared, provider-neutral representation
(:class:`PendingToolCall`, :class:`LLMTurn`) so the tool-dispatch loop
— the part already built and tested in the Anthropic-only version —
does not need to change at all to support a second provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.core.exceptions import ServiceError


@dataclass
class PendingToolCall:
    """One tool call a model has requested, in provider-neutral form.

    Attributes:
        call_id: Provider-specific identifier for this call, needed
            when reporting the result back (Anthropic requires
            ``tool_use_id``; Gemini's ``from_function_response``
            matches by tool ``name`` instead and does not use this
            field — kept on every call regardless, so
            :class:`~src.ai.assistant_service.AssistantService`'s loop
            does not need a provider-specific branch to decide whether
            it exists).
        name: Tool name.
        arguments: Tool arguments, already parsed to a plain dict.
    """

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMTurn:
    """One model response, in provider-neutral form.

    Attributes:
        text: Any plain text the model produced this turn. Empty
            string if the model only requested tool calls with no
            accompanying text.
        tool_calls: Tool calls the model is requesting, if any. Empty
            list if the model produced a final answer with no further
            tool calls needed.
    """

    text: str
    tool_calls: list[PendingToolCall]


class BaseLLMProvider(ABC):
    """Shared interface both provider implementations satisfy.

    Unlike this project's other ``Base*`` classes (readers, cleaning
    operations, charts), a provider genuinely needs instance state —
    the underlying SDK client and the running conversation history —
    so this is not a classmethod-only stateless interface the way
    those are.
    """

    @abstractmethod
    def send(
        self,
        history: list[Any],
        system_prompt: str,
        tool_schemas: list[dict[str, Any]],
    ) -> tuple[LLMTurn, Any]:
        """Send the current conversation and return the model's turn.

        Args:
            history: The conversation so far, in this provider's own
                native message format — callers should treat this as
                opaque and only ever pass back what this same
                provider previously returned via the second element of
                this method's return value.
            system_prompt: System-level instructions.
            tool_schemas: Available tools, in this project's
                provider-neutral schema shape (name, description,
                JSON Schema parameters) — each provider translates
                this to its own required format internally.

        Returns:
            A ``(turn, raw_response)`` pair: the provider-neutral
            :class:`LLMTurn`, and the provider's own raw response
            object — the caller does not need to inspect the raw
            response directly, but must pass it to
            :meth:`append_assistant_turn` and (after executing any
            tool calls) :meth:`append_tool_results` to keep
            ``history`` correctly formed for this provider.

        Raises:
            ServiceError: If the underlying API call fails.
        """
        raise NotImplementedError

    @abstractmethod
    def append_user_message(self, history: list[Any], text: str) -> list[Any]:
        """Return ``history`` with a new user message appended, in this provider's format."""
        raise NotImplementedError

    @abstractmethod
    def append_assistant_turn(self, history: list[Any], raw_response: Any) -> list[Any]:
        """Return ``history`` with the model's last turn appended, in this provider's format."""
        raise NotImplementedError

    @abstractmethod
    def append_tool_results(
        self, history: list[Any], results: list[tuple[PendingToolCall, str]]
    ) -> list[Any]:
        """Return ``history`` with tool results appended, in this provider's format.

        Args:
            history: Conversation so far.
            results: ``(call, result_text)`` pairs — one per tool call
                that was executed this turn.
        """
        raise NotImplementedError


class AnthropicProvider(BaseLLMProvider):
    """Wraps the Anthropic SDK, translating to/from the shared LLMTurn format."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = 4096
        self._anthropic = anthropic

    def send(
        self,
        history: list[Any],
        system_prompt: str,
        tool_schemas: list[dict[str, Any]],
    ) -> tuple[LLMTurn, Any]:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system_prompt,
                tools=tool_schemas,
                messages=history,
            )
        except self._anthropic.APIError as exc:
            raise ServiceError(f"Anthropic API call failed: {exc}") from exc

        text = "".join(b.text for b in response.content if b.type == "text")
        tool_calls = [
            PendingToolCall(call_id=b.id, name=b.name, arguments=b.input)
            for b in response.content
            if b.type == "tool_use"
        ]
        return LLMTurn(text=text, tool_calls=tool_calls), response

    def append_user_message(self, history: list[Any], text: str) -> list[Any]:
        return history + [{"role": "user", "content": text}]

    def append_assistant_turn(self, history: list[Any], raw_response: Any) -> list[Any]:
        return history + [{"role": "assistant", "content": raw_response.content}]

    def append_tool_results(
        self, history: list[Any], results: list[tuple[PendingToolCall, str]]
    ) -> list[Any]:
        tool_result_blocks = [
            {"type": "tool_result", "tool_use_id": call.call_id, "content": result_text}
            for call, result_text in results
        ]
        return history + [{"role": "user", "content": tool_result_blocks}]


class GeminiProvider(BaseLLMProvider):
    """Wraps the Google Gen AI SDK, translating to/from the shared LLMTurn format.

    Confirmed directly against the installed SDK (``google-genai``,
    not the deprecated ``google-generativeai``) before writing this
    class: ``tools``/``system_instruction`` are fields on
    ``GenerateContentConfig``, not direct keyword arguments to
    ``generate_content``; a response part carries a call in
    ``.function_call`` (with ``.name``/``.args``); a tool result is
    sent back via ``types.Part.from_function_response``.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._genai = genai
        from google.genai import types

        self._types = types

    def _build_tool_config(self, tool_schemas: list[dict[str, Any]]):
        function_declarations = [
            self._types.FunctionDeclaration(
                name=schema["name"],
                description=schema["description"],
                parameters_json_schema=schema["input_schema"],
            )
            for schema in tool_schemas
        ]
        return [self._types.Tool(function_declarations=function_declarations)]

    def send(
        self,
        history: list[Any],
        system_prompt: str,
        tool_schemas: list[dict[str, Any]],
    ) -> tuple[LLMTurn, Any]:
        config = self._types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=self._build_tool_config(tool_schemas) if tool_schemas else None,
        )
        try:
            response = self._client.models.generate_content(
                model=self._model, contents=history, config=config
            )
        except Exception as exc:
            raise ServiceError(f"Gemini API call failed: {exc}") from exc

        if not response.candidates:
            raise ServiceError(
                "Gemini returned no candidates — the request may have "
                "been blocked by safety filters."
            )

        parts = response.candidates[0].content.parts or []
        text = "".join(p.text for p in parts if p.text)
        tool_calls = [
            PendingToolCall(
                call_id=p.function_call.id or p.function_call.name,
                name=p.function_call.name,
                arguments=dict(p.function_call.args or {}),
            )
            for p in parts
            if p.function_call is not None
        ]
        return LLMTurn(text=text, tool_calls=tool_calls), response

    def append_user_message(self, history: list[Any], text: str) -> list[Any]:
        return history + [
            self._types.Content(role="user", parts=[self._types.Part(text=text)])
        ]

    def append_assistant_turn(self, history: list[Any], raw_response: Any) -> list[Any]:
        return history + [raw_response.candidates[0].content]

    def append_tool_results(
        self, history: list[Any], results: list[tuple[PendingToolCall, str]]
    ) -> list[Any]:
        response_parts = [
            self._types.Part.from_function_response(
                name=call.name, response={"result": result_text}
            )
            for call, result_text in results
        ]
        return history + [self._types.Content(role="user", parts=response_parts)]


class GroqProvider(BaseLLMProvider):
    """Wraps Groq's OpenAI-compatible chat completions API.

    Groq's API is OpenAI-compatible (confirmed directly against its
    documented curl example before writing this class:
    ``https://api.groq.com/openai/v1/chat/completions``), so this uses
    the ``openai`` SDK pointed at Groq's base URL rather than a
    Groq-specific SDK — no separate dependency needed beyond
    ``openai``, which is a thin, widely-used HTTP client for this
    exact API shape.

    OpenAI's tool-calling shape is the third distinct format this
    project's provider abstraction translates, alongside Anthropic's
    ``tool_use`` content blocks and Gemini's ``function_call`` parts:
    a request's ``tools`` is a list of
    ``{"type": "function", "function": {name, description,
    parameters}}``; a response's tool calls appear on
    ``message.tool_calls``, each with ``.id``/``.function.name``/
    ``.function.arguments`` (arguments arrive as a JSON *string*, not
    a parsed dict — unlike both other providers, which hand back
    already-parsed structures). A tool result is sent back as a
    message with ``role="tool"``, ``tool_call_id=...``,
    ``content=...``.
    """

    def __init__(self, api_key: str, model: str = "openai/gpt-oss-120b") -> None:
        import openai

        self._client = openai.OpenAI(
            api_key=api_key, base_url="https://api.groq.com/openai/v1", max_retries=1
        )
        self._model = model
        self._openai = openai

    def _build_tool_schemas(
        self, tool_schemas: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema["description"],
                    "parameters": schema["input_schema"],
                },
            }
            for schema in tool_schemas
        ]

    def send(
        self,
        history: list[Any],
        system_prompt: str,
        tool_schemas: list[dict[str, Any]],
    ) -> tuple[LLMTurn, Any]:
        messages = [{"role": "system", "content": system_prompt}] + history
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=self._build_tool_schemas(tool_schemas) if tool_schemas else None,
            )
        except self._openai.OpenAIError as exc:
            raise ServiceError(f"Groq API call failed: {exc}") from exc

        message = response.choices[0].message
        text = message.content or ""

        tool_calls = []
        if message.tool_calls:
            import json

            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError as exc:
                    raise ServiceError(
                        f"Groq returned malformed tool arguments for "
                        f"'{tc.function.name}': {exc}"
                    ) from exc
                tool_calls.append(
                    PendingToolCall(
                        call_id=tc.id, name=tc.function.name, arguments=arguments
                    )
                )

        return LLMTurn(text=text, tool_calls=tool_calls), response

    def append_user_message(self, history: list[Any], text: str) -> list[Any]:
        return history + [{"role": "user", "content": text}]

    def append_assistant_turn(self, history: list[Any], raw_response: Any) -> list[Any]:
        message = raw_response.choices[0].message
        entry: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        return history + [entry]

    def append_tool_results(
        self, history: list[Any], results: list[tuple[PendingToolCall, str]]
    ) -> list[Any]:
        tool_messages = [
            {"role": "tool", "tool_call_id": call.call_id, "content": result_text}
            for call, result_text in results
        ]
        return history + tool_messages


class OllamaProvider(BaseLLMProvider):
    """Wraps a local Ollama server's OpenAI-adjacent ``/api/chat`` endpoint.

    Delivers "Local-First AI" (milestone 7): no API key, no outbound
    network call beyond ``localhost`` — the model runs entirely on the
    user's machine via a locally running ``ollama serve``. Uses
    ``requests`` directly (already a declared project dependency)
    rather than pulling in a dedicated Ollama SDK, since the raw HTTP
    surface is small and stable
    (https://github.com/ollama/ollama/blob/main/docs/api.md).

    Confirmed against Ollama's documented ``/api/chat`` shape before
    writing this class: a request takes ``model``/``messages``/
    ``tools``/``stream``; ``tools`` uses the same
    ``{"type": "function", "function": {name, description,
    parameters}}`` shape OpenAI (and this project's ``GroqProvider``)
    already use, so :meth:`_build_tool_schemas` is intentionally
    identical in shape to ``GroqProvider``'s. The one confirmed
    difference: a response's ``message.tool_calls[].function.arguments``
    arrives as an already-parsed object, not a JSON string the way
    Groq's does — handled by accepting either shape rather than
    assuming one, since this varies across Ollama server versions.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama3.1",
        base_url: str = "http://localhost:11434",
    ) -> None:
        # api_key accepted (and ignored) only so create_provider() can
        # construct every provider through one uniform call signature
        # without a provider-specific branch — Ollama itself needs no
        # credential since it only ever talks to localhost.
        del api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def _build_tool_schemas(
        self, tool_schemas: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": schema["name"],
                    "description": schema["description"],
                    "parameters": schema["input_schema"],
                },
            }
            for schema in tool_schemas
        ]

    def send(
        self,
        history: list[Any],
        system_prompt: str,
        tool_schemas: list[dict[str, Any]],
    ) -> tuple[LLMTurn, Any]:
        import requests

        messages = [{"role": "system", "content": system_prompt}] + history
        try:
            response = requests.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "tools": (
                        self._build_tool_schemas(tool_schemas) if tool_schemas else None
                    ),
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ServiceError(
                f"Ollama request failed (is 'ollama serve' running at "
                f"{self._base_url}?): {exc}"
            ) from exc

        payload = response.json()
        message = payload.get("message", {})
        text = message.get("content") or ""

        tool_calls = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            function = tc.get("function", {})
            raw_arguments = function.get("arguments", {})
            if isinstance(raw_arguments, str):
                import json

                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise ServiceError(
                        f"Ollama returned malformed tool arguments for "
                        f"'{function.get('name')}': {exc}"
                    ) from exc
            else:
                arguments = dict(raw_arguments or {})
            # Ollama's /api/chat does not assign tool_calls an id the
            # way Anthropic/Groq do — synthesize a stable one from
            # position within this turn, since PendingToolCall.call_id
            # must be non-empty for append_tool_results below to pair
            # results back up correctly.
            tool_calls.append(
                PendingToolCall(
                    call_id=tc.get("id") or f"ollama-call-{i}",
                    name=function.get("name", ""),
                    arguments=arguments,
                )
            )

        return LLMTurn(text=text, tool_calls=tool_calls), payload

    def append_user_message(self, history: list[Any], text: str) -> list[Any]:
        return history + [{"role": "user", "content": text}]

    def append_assistant_turn(self, history: list[Any], raw_response: Any) -> list[Any]:
        message = raw_response.get("message", {})
        entry: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content") or "",
        }
        if message.get("tool_calls"):
            entry["tool_calls"] = message["tool_calls"]
        return history + [entry]

    def append_tool_results(
        self, history: list[Any], results: list[tuple[PendingToolCall, str]]
    ) -> list[Any]:
        tool_messages = [
            {"role": "tool", "content": result_text} for _call, result_text in results
        ]
        return history + tool_messages


def create_provider(
    provider_name: str, api_key: str, model: str | None = None
) -> BaseLLMProvider:
    """Construct a provider by name.

    Args:
        provider_name: ``"anthropic"``, ``"gemini"``, ``"groq"``, or
            ``"ollama"``.
        api_key: The provider's API key. Ignored for ``"ollama"``,
            which needs none.
        model: Optional model override, passed through to the
            provider's constructor. ``None`` uses that provider
            class's own default (see each class's ``__init__``).

    Raises:
        ServiceError: If ``provider_name`` is not recognized.
    """
    kwargs: dict[str, Any] = {"api_key": api_key}
    if model is not None:
        kwargs["model"] = model

    if provider_name == "anthropic":
        return AnthropicProvider(**kwargs)
    if provider_name == "gemini":
        return GeminiProvider(**kwargs)
    if provider_name == "groq":
        return GroqProvider(**kwargs)
    if provider_name == "ollama":
        return OllamaProvider(**kwargs)
    raise ServiceError(
        f"Unknown provider: {provider_name!r}. Must be 'anthropic', 'gemini', "
        f"'groq', or 'ollama'."
    )
