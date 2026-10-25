# File: apps/api/uadas_api/web/sse.py
"""Server-Sent Events framing and the streaming response, shared by every stream of the API (3.7).

Why hand-rolled and not Ninja's built-in ``SSE`` stream format: that format emits bare ``data:``
frames, with no ``event:`` name, no ``id:`` (so no ``Last-Event-ID`` resume) and no ``retry:``,
which are exactly what the job-progress stream needs. This module is the one place a frame is
built, so the rules that keep a stream safe live in one place:

* **Newline-injection safety.** A frame is delimited by newlines, so any value that reaches a
  frame line could end it and forge the next one. Event names and ids are validated against a
  small closed alphabet (``ValueError`` otherwise); the payload is **JSON only**, encoded with
  ``ensure_ascii`` (every control character, ``U+2028`` and ``U+2029`` included, becomes a
  ``\\uXXXX`` escape), so it is one physical line by construction -- and a final check refuses
  the frame if a raw CR or LF is somehow still there.
* **A size cap per event** (:class:`SseEventTooLarge`): a stream cannot be made to push an
  unbounded blob to a client or a proxy buffer.
* **Never a data row.** The helpers cannot know what a payload means; the callers (job progress,
  assistant) build payloads from closed fields only. See ``plans/phase-3-7-streaming.md``.

:class:`SseResponse` also carries an ``on_close`` hook that Django runs when the response is
closed, **whether or not the body generator ever started**. A client that vanishes before the
first chunk is pulled leaves an async generator that never ran (so its ``finally`` never will);
the stream-cap lease is released here as well, idempotently.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from django.http import StreamingHttpResponse

MEDIA_TYPE = "text/event-stream"

EVENT_NAME = re.compile(r"\A[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
EVENT_ID = re.compile(r"\A[A-Za-z0-9._:-]{1,64}\Z")
_COMMENT = re.compile(r"\A[A-Za-z0-9 ._:-]{0,64}\Z")


class SseEventTooLarge(ValueError):
    """An event's encoded size exceeds the cap; nothing was framed."""


def encode_event(
    data: Any, *, event: str, event_id: str | int | None = None, max_bytes: int
) -> bytes:
    """One frame: ``event:``, optional ``id:``, one ``data:`` line of compact JSON, blank line."""
    if not EVENT_NAME.fullmatch(event):
        raise ValueError("invalid SSE event name")
    lines = [f"event: {event}"]
    if event_id is not None:
        identifier = str(event_id)
        if not EVENT_ID.fullmatch(identifier):
            raise ValueError("invalid SSE event id")
        lines.append(f"id: {identifier}")
    payload = json.dumps(
        data, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )
    if (
        "\n" in payload or "\r" in payload
    ):  # unreachable with ensure_ascii; the belt to its braces
        raise ValueError("SSE data must be a single line")
    lines.append(f"data: {payload}")
    frame = ("\n".join(lines) + "\n\n").encode("utf-8")
    if len(frame) > max_bytes:
        raise SseEventTooLarge
    return frame


def encode_retry(milliseconds: int) -> bytes:
    """The ``retry:`` hint: how long the browser waits before it reconnects."""
    return f"retry: {int(milliseconds)}\n\n".encode("ascii")


def encode_comment(text: str = "keep-alive") -> bytes:
    """A comment frame (ignored by clients; keeps idle proxies from closing the connection)."""
    if not _COMMENT.fullmatch(text):
        raise ValueError("invalid SSE comment")
    return f": {text}\n\n".encode("ascii")


class SseResponse(StreamingHttpResponse):
    """A ``text/event-stream`` response that is never cached or buffered by a proxy."""

    def __init__(
        self, chunks: AsyncIterator[bytes], *, on_close: Callable[[], None]
    ) -> None:
        super().__init__(chunks, content_type=f"{MEDIA_TYPE}; charset=utf-8")
        self["Cache-Control"] = "no-cache, no-transform, private"
        self["X-Accel-Buffering"] = "no"  # nginx: do not buffer this response
        self._on_close = on_close

    def close(self) -> None:
        try:
            self._on_close()
        finally:
            super().close()


def sse_openapi(events: dict[str, Any], *, description: str) -> dict[str, Any]:
    """The ``openapi_extra`` of a stream operation: a ``text/event-stream`` 200 and its events.

    OpenAPI 3.1 has no way to type an event stream, so the 200 documents the media type with a
    string schema and lists each event name with the JSON Schema of its ``data`` in
    ``x-sse-events`` (``tests/test_web_openapi.py`` requires every one to be typed).
    """
    return {
        "responses": {
            200: {
                "description": description,
                "content": {
                    MEDIA_TYPE: {
                        # One parsed SSE event (the shape Schemathesis and Ninja's own SSE use);
                        # `data` is the JSON text, typed per event in `x-sse-events` below.
                        "schema": {
                            "type": "object",
                            "properties": {
                                "event": {"type": "string", "enum": sorted(events)},
                                "id": {"type": "string"},
                                "data": {"type": "string"},
                            },
                        }
                    }
                },
                "x-sse-events": events,
            }
        }
    }
