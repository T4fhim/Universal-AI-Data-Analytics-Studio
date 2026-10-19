# File: apps/api/uadas_api/web/assistant.py
"""``POST .../assistant/messages``: one assistant turn as a Server-Sent Events stream (3.7).

Roles and gates, in order: signed in and CSRF-checked (the default auth), an **editor** of the
organization (a viewer cannot spend the organization's provider quota), a configured provider (else
``503``), the per-user/organization throttle (``assistant``, 60/hour) and the concurrent-stream cap
(2 per user, 10 per organization; ``429``). Only then is the provider called.

The stream's events (all JSON, none carry a dataset's rows): ``message`` (a part of the reply
text), ``tool_call`` (a **proposed** call: name and arguments -- nothing is executed here, see
:mod:`uadas_api.ai.assistant`), ``done`` and ``error`` (a closed code and a fixed sentence, never the
provider's text). While the provider thinks the stream sends ``: keep-alive`` comments, so a proxy
does not time it out; if the client leaves, the provider call is abandoned and the cap lease
released. Because a provider call blocks, it runs in a worker thread with a hard time limit.

The client reads this stream with ``fetch`` (a ``POST`` cannot be an ``EventSource``); the frames are
the standard SSE ones. There is no resume: a turn is one request, and the client retries it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from asgiref.sync import sync_to_async
from django.http import HttpRequest
from django.http.response import HttpResponseBase
from ninja import Router, Schema
from pydantic import Field

from uadas_api.accounts.models import Role
from uadas_api.ai import assistant
from uadas_api.web import throttle
from uadas_api.web.config import ApiConfig, api_config
from uadas_api.web.errors import ApiError, responses
from uadas_api.web.scope import member
from uadas_api.web.sse import (
    SseEventTooLarge,
    SseResponse,
    encode_comment,
    encode_event,
    sse_openapi,
)
from uadas_api.web.streams import StreamLease, acquire, release_connections

router = Router(tags=["assistant"])

_DEFAULTS = ApiConfig()


class HistoryItem(Schema):
    """One earlier turn the client keeps (the server keeps none)."""

    role: Literal["user", "assistant"]
    text: str = Field(max_length=_DEFAULTS.assistant_max_message_chars)


class AssistantMessageIn(Schema):
    message: str = Field(min_length=1, max_length=_DEFAULTS.assistant_max_message_chars)
    history: list[HistoryItem] = Field(
        default_factory=list, max_length=_DEFAULTS.assistant_max_history
    )


_EVENTS: dict[str, Any] = {
    "message": {
        "type": "object",
        "description": "A part of the assistant's reply text (a whole turn, split only when long).",
        "required": ["index", "text"],
        "properties": {"index": {"type": "integer"}, "text": {"type": "string"}},
    },
    "tool_call": {
        "type": "object",
        "description": "A PROPOSED tool call. Nothing was run; run it through the stage endpoints.",
        "required": ["call_id", "name", "arguments", "proposed"],
        "properties": {
            "call_id": {"type": "string"},
            "name": {"type": "string"},
            "arguments": {"type": "object"},
            "proposed": {"const": True},
        },
    },
    "done": {
        "type": "object",
        "description": "The turn finished.",
        "required": ["tool_calls", "dropped"],
        "properties": {
            "tool_calls": {"type": "integer"},
            "dropped": {"type": "integer"},
        },
    },
    "error": {
        "type": "object",
        "description": "The turn failed; the stream ends.",
        "required": ["code", "message"],
        "properties": {
            "code": {
                "type": "string",
                "enum": ["provider_error", "provider_timeout", "event_too_large"],
            },
            "message": {"type": "string"},
        },
    },
}
_OPENAPI = sse_openapi(
    _EVENTS,
    description=(
        "text/event-stream of one assistant turn: `message` parts, `tool_call` proposals, then "
        "`done` (or `error`). Proposals are never executed by this endpoint."
    ),
)

_MESSAGES = {
    "provider_error": "The assistant could not complete this request.",
    "provider_timeout": "The assistant took too long to answer.",
    "event_too_large": "The assistant's answer was too large to stream.",
}


def _open(
    request: HttpRequest, org_id: uuid.UUID, payload: AssistantMessageIn
) -> tuple[str, StreamLease]:
    """Gate the request (database, config, throttle, cap), then close the connection."""
    config = api_config()
    try:
        membership = member(request, org_id, Role.EDITOR)
        history = [(item.role, item.text) for item in payload.history]
        if (
            not payload.message.strip()
            or sum(len(text) for _role, text in history)
            > config.assistant_max_history_chars
        ):
            raise ApiError(422, "The request was not valid.")
        if not assistant.is_configured():
            raise ApiError(503, "The assistant is not configured.")
        throttle.enforce("assistant", membership.user_id, membership.organization_id)
        lease = acquire(
            "assistant",
            membership.user_id,
            membership.organization_id,
            user_cap=config.assistant_user_cap,
            org_cap=config.assistant_org_cap,
            max_seconds=config.assistant_turn_seconds,
        )
        return assistant.build_user_content(payload.message, history), lease
    finally:
        release_connections()


def _run(content: str) -> assistant.Proposal:
    return assistant.propose(assistant.make_provider(), content)


def _error(code: assistant.AssistantErrorCode) -> bytes:
    return encode_event(
        {"code": code, "message": _MESSAGES[code]}, event="error", max_bytes=1024
    )


async def _turn(
    content: str, lease: StreamLease, config: ApiConfig
) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(asyncio.to_thread(_run, content))
    try:
        yield encode_comment(
            "open"
        )  # headers and first byte now, not after the provider answers
        deadline = loop.time() + config.assistant_turn_seconds
        while not task.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                yield _error("provider_timeout")
                return
            await asyncio.wait(
                {task}, timeout=min(config.sse_heartbeat_seconds, remaining)
            )
            if not task.done():
                yield encode_comment()
        try:
            proposal = task.result()
        except Exception as error:  # noqa: BLE001
            # every provider failure, whatever its type, becomes a closed code (text never leaves)
            yield _error(assistant.classify(error))
            return
        limit = config.assistant_max_event_bytes
        text = proposal.text
        parts = [
            text[i : i + assistant.MESSAGE_PART_CHARS]
            for i in range(0, len(text), assistant.MESSAGE_PART_CHARS)
        ]
        dropped = proposal.dropped
        try:
            for index, part in enumerate(parts):
                yield encode_event(
                    {"index": index, "text": part}, event="message", max_bytes=limit
                )
            sent = 0
            for call in proposal.calls:
                try:
                    frame = encode_event(
                        {
                            "call_id": call.call_id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "proposed": True,
                        },
                        event="tool_call",
                        max_bytes=config.max_parameters_bytes,
                    )
                except (SseEventTooLarge, TypeError, ValueError):
                    dropped += (
                        1  # an oversized or non-JSON proposal is dropped, not truncated
                    )
                    continue
                sent += 1
                yield frame
        except SseEventTooLarge:
            yield _error("event_too_large")
            return
        yield encode_event(
            {"tool_calls": sent, "dropped": dropped}, event="done", max_bytes=1024
        )
    finally:
        task.cancel()  # a client that left (or a timeout) abandons the provider call's result
        lease.release()


@router.post(
    "/organizations/{org_id}/assistant/messages",
    response=responses({200: None}),
    summary="Ask the assistant; the answer streams as Server-Sent Events (editor and above)",
    operation_id="assistant_messages",
    openapi_extra=_OPENAPI,
)
async def assistant_messages(
    request: HttpRequest, org_id: uuid.UUID, payload: AssistantMessageIn
) -> HttpResponseBase:
    content, lease = await sync_to_async(_open)(request, org_id, payload)
    return SseResponse(_turn(content, lease, api_config()), on_close=lease.release)
