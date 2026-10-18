# File: apps/api/uadas_api/sandbox/protocol.py
"""The parent <-> child wire format: one JSON object each way, strictly validated.

Why a hand-rolled, tiny protocol instead of pickle / multiprocessing connections: the child is
the component that handles hostile input, so *nothing it sends back may be trusted to be what
it says*. The parent therefore never deserialises anything richer than JSON, caps the size of
the reply before decoding, and re-validates every field -- types, ranges, string length, the
closed set of error codes -- so a compromised child can at worst report a wrong row count or
a wrong failure, never feed the parent an object, an exception, or a path.

Request (parent -> child, on stdin, then closed)::

    {"v": 1, "input": "input.csv", "output": "out.parquet", "limits": {...}}

Both names are plain file names inside the child's working directory (never a path), chosen by
the parent; the user's own file name never reaches the child. Response (child -> parent, one
JSON line on the child's real stdout)::

    {"ok": true,  "source_format": "csv", "row_count": 3, "column_count": 2,
     "columns": [["a", "int64"], ...], "warning_count": 0, "enforcement": {...}}
    {"ok": false, "code": "parse_error"}

Standard library only (the child imports this module).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from uadas_api.sandbox.errors import SandboxErrorCode, parse_code

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 16 * 1024
MAX_REPORTED_COLUMNS = 2_000
MAX_NAME_CHARS = 128
MAX_DTYPE_CHARS = 48

OUTPUT_NAME = "out.parquet"
# Keys of the child's report of which limits it actually managed to apply.
ENFORCEMENT_KEYS: tuple[str, ...] = (
    "core",
    "memory",
    "cpu",
    "fsize",
    "nofile",
    "nproc",
    # The in-process socket shim is installed. Reported, but NOT enforcement: Python code can
    # reach the raw socket class around it (see ``guards.install_network_block``).
    "network_guard",
    # The child unshared a network namespace and verified that only loopback is left.
    "network_isolated",
    # Non-dumpable, killed with its parent (PR_SET_PDEATHSIG), own wall-clock alarm armed.
    "hardened",
)

_FILE_NAME = re.compile(r"[a-z0-9_]{1,32}\.[a-z0-9]{1,8}")
_SOURCE_FORMAT = re.compile(r"[a-z0-9_]{1,32}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


class ProtocolError(ValueError):
    """A message did not match the protocol (either direction)."""


@dataclass(frozen=True)
class Request:
    """What the child was asked to do."""

    input_name: str
    output_name: str
    limits: dict[str, int]


@dataclass(frozen=True)
class Success:
    """A parsed table: counts and a column summary. The data itself is in the output file."""

    source_format: str
    row_count: int
    column_count: int
    columns: tuple[tuple[str, str], ...] = ()
    warning_count: int = 0
    enforcement: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Failure:
    """The child could not produce a table; ``code`` is from the closed set."""

    code: SandboxErrorCode
    enforcement: dict[str, bool] = field(default_factory=dict)


def encode_request(input_name: str, output_name: str, limits: dict[str, int]) -> bytes:
    """Serialise a request. Raises :class:`ProtocolError` for a name that is not a plain file name."""
    for name in (input_name, output_name):
        if _FILE_NAME.fullmatch(name) is None:
            raise ProtocolError("file names must be plain lower-case names")
    body = {
        "v": PROTOCOL_VERSION,
        "input": input_name,
        "output": output_name,
        "limits": limits,
    }
    return json.dumps(body, separators=(",", ":")).encode()


def decode_request(raw: bytes) -> Request:
    """Parse and validate a request (child side)."""
    if len(raw) > MAX_REQUEST_BYTES:
        raise ProtocolError("request too large")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("request is not JSON") from None
    if not isinstance(data, dict) or data.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    input_name, output_name, limits = (
        data.get("input"),
        data.get("output"),
        data.get("limits"),
    )
    if not (isinstance(input_name, str) and isinstance(output_name, str)):
        raise ProtocolError("names must be strings")
    for name in (input_name, output_name):
        if _FILE_NAME.fullmatch(name) is None:
            raise ProtocolError("file names must be plain lower-case names")
    if input_name == output_name:
        raise ProtocolError("input and output must differ")
    if not isinstance(limits, dict) or not all(
        isinstance(k, str) and type(v) is int and v >= 0 for k, v in limits.items()
    ):
        raise ProtocolError("limits must map names to non-negative integers")
    return Request(input_name=input_name, output_name=output_name, limits=dict(limits))


def _clean(text: object, limit: int) -> str:
    if not isinstance(text, str):
        raise ProtocolError("expected a string")
    return _CONTROL.sub("?", text)[:limit]


def _count(value: object, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ProtocolError("count out of range")
    return value


def _enforcement(value: object) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProtocolError("enforcement must be an object")
    return {k: value.get(k) is True for k in ENFORCEMENT_KEYS}


def encode_success(result: Success) -> bytes:
    """Serialise a success (child side)."""
    body: dict[str, Any] = {
        "ok": True,
        "source_format": result.source_format,
        "row_count": result.row_count,
        "column_count": result.column_count,
        "columns": [list(c) for c in result.columns[:MAX_REPORTED_COLUMNS]],
        "warning_count": result.warning_count,
        "enforcement": result.enforcement,
    }
    return json.dumps(body, separators=(",", ":")).encode()


def encode_failure(
    code: SandboxErrorCode, enforcement: dict[str, bool] | None = None
) -> bytes:
    """Serialise a failure (child side)."""
    body = {"ok": False, "code": code.value, "enforcement": enforcement or {}}
    return json.dumps(body, separators=(",", ":")).encode()


def decode_response(
    raw: bytes, *, max_rows: int, max_columns: int
) -> Success | Failure:
    """Parse and strictly validate the child's reply (parent side).

    Raises :class:`ProtocolError` for anything that is not exactly the documented shape; the
    caller turns that into ``protocol_error``. ``max_rows`` / ``max_columns`` bound the
    counts the child may claim.
    """
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("reply is not JSON") from None
    if not isinstance(data, dict):
        raise ProtocolError("reply is not an object")
    enforcement = _enforcement(data.get("enforcement"))
    if data.get("ok") is False:
        return Failure(code=parse_code(data.get("code")), enforcement=enforcement)
    if data.get("ok") is not True:
        raise ProtocolError("reply has no verdict")
    source_format = data.get("source_format")
    if (
        not isinstance(source_format, str)
        or _SOURCE_FORMAT.fullmatch(source_format) is None
    ):
        raise ProtocolError("bad source format")
    columns_raw = data.get("columns")
    if not isinstance(columns_raw, list) or len(columns_raw) > MAX_REPORTED_COLUMNS:
        raise ProtocolError("bad column summary")
    columns: list[tuple[str, str]] = []
    for item in columns_raw:
        if not (isinstance(item, list) and len(item) == 2):
            raise ProtocolError("bad column entry")
        columns.append(
            (_clean(item[0], MAX_NAME_CHARS), _clean(item[1], MAX_DTYPE_CHARS))
        )
    return Success(
        source_format=source_format,
        row_count=_count(data.get("row_count"), max_rows),
        column_count=_count(data.get("column_count"), max_columns),
        columns=tuple(columns),
        warning_count=_count(data.get("warning_count", 0), 10_000_000),
        enforcement=enforcement,
    )
