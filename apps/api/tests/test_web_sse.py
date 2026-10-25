# File: apps/api/tests/test_web_sse.py
"""SSE framing (3.7): one physical line per field, no way to forge a frame, bounded size.

Why: an event frame is delimited by newlines, so a name, id or payload that could carry one lets a
tenant's text end the frame and fabricate the next (a fake ``job`` event, a fake ``done``). Every
rejection below has a twin that shows the same call with a clean value is accepted, so the guard is
the validation and not a function that refuses everything.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from uadas_api.web.sse import (
    SseEventTooLarge,
    SseResponse,
    encode_comment,
    encode_event,
    encode_retry,
)

CAP = 4096


def _frame(**kwargs: Any) -> bytes:
    kwargs.setdefault("max_bytes", CAP)
    return encode_event(**kwargs)


def test_a_frame_is_event_id_data_and_a_blank_line() -> None:
    frame = _frame(data={"a": 1}, event="job", event_id=7)
    assert frame == b'event: job\nid: 7\ndata: {"a":1}\n\n'
    assert (
        _frame(data=[], event="done") == b"event: done\ndata: []\n\n"
    )  # id is optional


@pytest.mark.parametrize(
    "name", ["job\nevent: done", "job\r", "", "9job", "a b", "x" * 65, "job:", "jöb"]
)
def test_an_unsafe_event_name_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="event name"):
        _frame(data={}, event=name)
    _frame(data={}, event="job.progress_2-x")  # the twin: a clean name passes


@pytest.mark.parametrize(
    "identifier", ["1\ndata: forged", "a b", "", "x" * 65, "1\r\n"]
)
def test_an_unsafe_event_id_is_refused(identifier: str) -> None:
    with pytest.raises(ValueError, match="event id"):
        _frame(data={}, event="job", event_id=identifier)
    _frame(data={}, event="job", event_id="12:34.a_b-c")  # the twin


@pytest.mark.parametrize(
    "text",
    [
        "line one\nevent: done\ndata: {}",
        "carriage\rreturn",
        "crlf\r\nid: 99",
        "separator and more",
        "\x00\x1b[31m",
    ],
)
def test_a_payload_cannot_inject_a_frame_and_round_trips(text: str) -> None:
    frame = _frame(data={"message": text}, event="job")
    lines = frame.decode("utf-8").split("\n")
    # exactly: event line, data line, and the blank terminator -- nothing a payload wrote is a line
    assert lines[0] == "event: job" and lines[1].startswith("data: ")
    assert lines[2:] == ["", ""]
    assert frame.count(b"\n") == 3 and b"\r" not in frame
    assert json.loads(lines[1][len("data: ") :]) == {"message": text}


def test_non_json_payloads_are_refused() -> None:
    with pytest.raises(TypeError):
        _frame(data={"x": object()}, event="job")
    with pytest.raises(ValueError):
        _frame(data={"x": float("nan")}, event="job")
    _frame(data={"x": 1.5}, event="job")  # the twin


def test_an_event_over_the_cap_is_refused_and_one_at_the_cap_is_not() -> None:
    with pytest.raises(SseEventTooLarge):
        encode_event({"t": "x" * 200}, event="job", max_bytes=100)
    small = encode_event({"t": "x"}, event="job", max_bytes=100)
    assert len(small) <= 100
    exact = encode_event({"t": "x" * 50}, event="job", max_bytes=len(small) + 49)
    assert len(exact) == len(small) + 49


def test_retry_and_comment_frames() -> None:
    assert encode_retry(3000) == b"retry: 3000\n\n"
    assert encode_comment() == b": keep-alive\n\n"
    for bad in ("x\ndata: {}", "x\r", "é"):
        with pytest.raises(ValueError):
            encode_comment(bad)
    assert encode_comment("open") == b": open\n\n"  # the twin


def test_cors_allows_the_reconnect_header_and_keeps_the_defaults() -> None:
    from corsheaders.defaults import default_headers
    from django.conf import settings

    allowed = {h.lower() for h in settings.CORS_ALLOW_HEADERS}
    assert (
        "last-event-id" in allowed
    )  # a cross-origin EventSource reconnect is preflighted with it
    assert {
        h.lower() for h in default_headers
    } <= allowed  # x-csrftoken etc. still allowed


@pytest.mark.django_db  # closing any Django response sends request_finished (connection hygiene)
def test_the_response_is_an_uncached_unbuffered_event_stream_that_runs_its_close_hook() -> (
    None
):
    closed: list[int] = []

    async def chunks() -> Any:
        yield b": x\n\n"

    response = SseResponse(chunks(), on_close=lambda: closed.append(1))
    assert response["Content-Type"] == "text/event-stream; charset=utf-8"
    assert response["Cache-Control"] == "no-cache, no-transform, private"
    assert response["X-Accel-Buffering"] == "no"
    assert not closed
    response.close()  # runs whether or not the body was ever iterated
    assert closed == [1]
