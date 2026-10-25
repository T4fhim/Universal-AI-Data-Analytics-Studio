# File: apps/api/tests/asgi_support.py
"""A minimal ASGI client that sees a response *as it is sent* (3.7's streaming tests).

Why not ``httpx.ASGITransport`` or Django's test ``Client``: both collect the whole body before
returning, so a stream that was secretly buffered until it ended would look identical to a correct
one. This client calls the real ASGI application directly with the ASGI message protocol, keeps every
``http.response.body`` message as it arrives (a queue), and delivers ``http.disconnect`` on demand --
exactly what a server does when a browser closes its ``EventSource`` -- so a test can prove that
events arrive incrementally and that leaving releases every resource.

Sign-in is a cookie copied from :class:`apihelpers.Api` (a real session; CSRF stays enforced: a POST
sends the ``csrftoken`` cookie and the ``X-CSRFToken`` header, like the SPA).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from apihelpers import Api
from django.core.handlers.asgi import ASGIHandler

TIMEOUT = 10.0


def application() -> ASGIHandler:
    """The project's real ASGI entry point (``uadas_api.asgi``)."""
    from uadas_api.asgi import application as app

    return app


class Conn:
    """One in-flight request: ``await Conn.open(...)``, then read chunks, then disconnect or finish."""

    def __init__(self) -> None:
        self.status = 0
        self.headers: dict[str, str] = {}
        self._incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self.finished = False

    @classmethod
    async def open(
        cls,
        method: str,
        path: str,
        *,
        api: Api | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        wait_head: bool = True,
    ) -> Conn:
        conn = cls()
        raw = json.dumps(body).encode() if body is not None else b""
        sent: list[tuple[bytes, bytes]] = [(b"host", b"testserver")]
        if api is not None:
            jar = api.client.cookies
            cookie = "; ".join(f"{name}={jar[name].value}" for name in jar)
            sent.append((b"cookie", cookie.encode()))
            if method != "GET":
                sent.append((b"x-csrftoken", api.token.encode()))
        if body is not None:
            sent += [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw)).encode()),
            ]
        for name, value in (headers or {}).items():
            sent.append((name.lower().encode(), value.encode()))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": sent,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
        }
        conn._incoming.put_nowait(
            {"type": "http.request", "body": raw, "more_body": False}
        )
        conn._task = asyncio.ensure_future(
            application()(scope, conn._incoming.get, conn._outgoing.put)  # type: ignore[arg-type]
        )
        if not wait_head:  # the caller will disconnect before the response head exists
            return conn
        start = await conn._next()
        assert start["type"] == "http.response.start", start
        conn.status = start["status"]
        conn.headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        return conn

    async def _next(self, timeout: float = TIMEOUT) -> dict[str, Any]:
        task = self._task
        assert task is not None
        getter = asyncio.ensure_future(self._outgoing.get())
        done, _ = await asyncio.wait(
            {getter, task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if getter in done:
            return getter.result()
        getter.cancel()
        if task in done:
            task.result()  # surface an exception of the app
            raise AssertionError("the application ended without a response")
        raise AssertionError("timed out waiting for the application")

    async def chunk(self, timeout: float = TIMEOUT) -> bytes | None:
        """The next body chunk, or ``None`` once the response is complete."""
        if self.finished:
            return None
        message = await self._next(timeout)
        assert message["type"] == "http.response.body", message
        if not message.get("more_body", False):
            self.finished = True
            # A plain response is one final message with its whole body; a stream's last is empty.
            return bytes(message.get("body", b"")) or None
        return bytes(message.get("body", b""))

    async def until(self, marker: bytes, timeout: float = TIMEOUT) -> list[bytes]:
        """Read chunks up to and including the first one containing ``marker``."""
        got: list[bytes] = []
        while True:
            piece = await self.chunk(timeout)
            assert piece is not None, f"the stream ended before {marker!r}; got {got!r}"
            got.append(piece)
            if marker in piece:
                return got

    async def body(self) -> bytes:
        """Everything up to the end of a response that ends by itself."""
        parts: list[bytes] = []
        while (piece := await self.chunk()) is not None:
            parts.append(piece)
        return b"".join(parts)

    async def disconnect(self) -> None:
        """What the server sees when the browser closes the connection; waits for the app to wind down."""
        self._incoming.put_nowait({"type": "http.disconnect"})
        await self.wait_done()

    async def wait_done(self, timeout: float = TIMEOUT) -> None:
        assert self._task is not None
        await asyncio.wait({self._task}, timeout=timeout)
        assert self._task.done(), "the application did not finish"
        self._task.result()


def sse_events(chunks: list[bytes] | bytes) -> list[dict[str, Any]]:
    """Parse frames into ``{event, id, data}`` dicts (comments and retry hints are skipped)."""
    text = (b"".join(chunks) if isinstance(chunks, list) else chunks).decode()
    out: list[dict[str, Any]] = []
    for block in text.split("\n\n"):
        fields = dict(
            line.split(": ", 1)
            for line in block.split("\n")
            if ": " in line and not line.startswith(":")
        )
        if "event" in fields:
            out.append(
                {
                    "event": fields["event"],
                    "id": fields.get("id"),
                    "data": json.loads(fields["data"]),
                }
            )
    return out
