# File: apps/api/uadas_api/sandbox/child.py
"""The sandbox child: the only module in ``uadas_api`` that may import ``uadas_core.readers``.

Run as ``python -I -m uadas_api.sandbox.child`` by :mod:`uadas_api.sandbox.runner`, with a
minimal environment and an empty working directory. It reads one JSON request from stdin,
puts the guards on itself *first* (hardening and its own alarm, rlimits, a network namespace,
then the in-process socket shim), only then imports the readers, parses the named input file,
writes ``out.parquet`` and replies with one JSON line.

Why its shape is what it is:

* **Guards before readers.** The import of ``uadas_core.readers`` (which pulls in pandas,
  lxml, openpyxl, PyMuPDF, OpenCV ...) happens *inside* :func:`_parse`, after
  :func:`~uadas_api.sandbox.guards.apply_resource_limits`,
  :func:`~uadas_api.sandbox.guards.isolate_network` and
  :func:`~uadas_api.sandbox.guards.install_network_block`. Everything that can run attacker-
  influenced code therefore runs under the limits.
* **stdout is the protocol, nothing else.** Native libraries and ``print`` calls write to
  fd 1; the real stdout is duplicated first and fd 1 is pointed at stderr, which the parent
  discards. The reply goes to the saved descriptor only.
* **Only codes cross the boundary.** Whatever goes wrong is classified into the closed
  :class:`~uadas_api.sandbox.errors.SandboxErrorCode` set; no exception text, no path, no
  traceback is ever written to the reply (a crafted file can put anything in a message).
  A forbidden operation that a reader *swallowed* still fails the parse
  (:func:`~uadas_api.sandbox.guards.violation_kind`): fail closed.
* **Exit with ``os._exit``.** Interpreter teardown with native libraries loaded is slow and
  can hang or crash; the reply has been flushed by then.
* **No Django.** Importing this module imports only the standard library and the stdlib-only
  sandbox modules; the child never sees settings, the database or a secret *in its own
  environment*. (Whether it can read the worker's is a question of uid, not of environment
  variables: see :mod:`uadas_api.sandbox.isolation`.)

The table is flattened to one Parquet file. Multi-table sources (several worksheets, an
SQLite file with several tables) are refused with ``multiple_tables`` rather than guessed at:
choosing a table is an API decision (3.6), not the sandbox's.
"""

from __future__ import annotations

import errno
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from uadas_api.sandbox import guards
from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.protocol import (
    ProtocolError,
    Success,
    decode_request,
    encode_failure,
    encode_success,
)

_RESOURCE_ERRNOS = {errno.EMFILE, errno.ENFILE, errno.EAGAIN, errno.ENOMEM}
_MAX_CHAIN = 12


def _chain(error: BaseException) -> Iterator[BaseException]:
    """``error`` and its causes / contexts (readers wrap what they catch)."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen and len(seen) < _MAX_CHAIN:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify(error: BaseException) -> SandboxErrorCode:
    """Map any exception to one closed code. The text of ``error`` is never consulted."""
    if guards.violation_kind() is not None:
        return SandboxErrorCode.BLOCKED_OPERATION
    for link in _chain(error):
        if isinstance(link, SandboxError):
            return link.code
        if isinstance(link, MemoryError):
            return SandboxErrorCode.MEMORY_LIMIT
        if isinstance(link, OSError):
            if link.errno == errno.EFBIG:
                return SandboxErrorCode.OUTPUT_TOO_LARGE
            if link.errno in _RESOURCE_ERRNOS:
                return SandboxErrorCode.RESOURCE_LIMIT
        # Pillow's decompression-bomb guard, matched by name so Pillow is never imported here.
        if any(
            base.__name__ == "DecompressionBombError" for base in type(link).__mro__
        ):
            return SandboxErrorCode.DECOMPRESSION_BOMB
    return SandboxErrorCode.PARSE_ERROR


def _parse(
    input_name: str,
    output_name: str,
    limits: dict[str, int],
    enforcement: dict[str, bool],
) -> Success:
    """Read ``input_name`` with the matching core reader and write the frame to ``output_name``."""
    base = Path.cwd()
    input_path = base / input_name
    output_path = base / output_name
    if input_path.is_symlink() or not input_path.is_file():
        raise SandboxError(SandboxErrorCode.UNSUPPORTED_TYPE)

    # The only line that loads the readers (and through them every parsing library): it must
    # stay below the guards.
    from uadas_core.readers.reader_registry import get_reader_for_path

    reader = get_reader_for_path(input_path)
    if len(reader.list_tables(input_path)) > 1:
        raise SandboxError(SandboxErrorCode.MULTIPLE_TABLES)
    dataset = reader.read(input_path)
    frame: Any = dataset.dataframe
    rows, columns = (int(n) for n in frame.shape)
    if rows > limits["max_rows"]:
        raise SandboxError(SandboxErrorCode.TOO_MANY_ROWS)
    if columns > limits["max_columns"]:
        raise SandboxError(SandboxErrorCode.TOO_MANY_COLUMNS)
    # Parquet needs string column names; a shallow copy so the reader's frame is untouched.
    frame = frame.copy(deep=False)
    frame.columns = [str(name) for name in frame.columns]
    summary = tuple((str(name), str(dtype)) for name, dtype in frame.dtypes.items())
    frame.to_parquet(output_path, index=False)
    return Success(
        source_format=str(dataset.source_format),
        row_count=rows,
        column_count=columns,
        columns=summary,
        warning_count=len(dataset.read_warnings or []),
        enforcement=enforcement,
    )


def main() -> int:
    """Child entry point. Always replies (a code, never text); returns 0 once it has."""
    reply = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)  # stray prints and native writes go to stderr, which the parent drops
    sys.stdout = sys.stderr

    enforcement: dict[str, bool] = {}
    try:
        request = decode_request(sys.stdin.buffer.read(16 * 1024 + 1))
    except ProtocolError:
        reply.write(encode_failure(SandboxErrorCode.PROTOCOL_ERROR))
        reply.flush()
        return 0

    try:
        # Hardening first (it arms the kill-with-parent signal and the own alarm), then the
        # rlimits (they count this user's tasks, which a user namespace would make unreadable),
        # then the network namespace, then the in-process shim, and only then any reader.
        hardened = guards.harden_process(
            parent_pid=request.limits.get("parent_pid"),
            alarm_seconds=request.limits.get("wall_alarm_seconds", 0),
        )
        enforcement = guards.apply_resource_limits(request.limits)
        enforcement["hardened"] = hardened
        enforcement["network_isolated"] = (
            bool(request.limits.get("isolate_network", 1)) and guards.isolate_network()
        )
        guards.install_network_block()
        enforcement["network_guard"] = True
        result = _parse(
            request.input_name, request.output_name, request.limits, enforcement
        )
        if guards.violation_kind() is not None:
            # A reader swallowed a blocked operation and carried on: not a parse to trust.
            raise SandboxError(SandboxErrorCode.BLOCKED_OPERATION)
        payload = encode_success(result)
    # Every failure -- even MemoryError or SystemExit -- becomes one closed code.
    except BaseException as error:  # noqa: BLE001
        payload = encode_failure(classify(error), enforcement)
    reply.write(payload + b"\n")
    reply.flush()
    return 0


if __name__ == "__main__":
    code = main()
    sys.stderr.flush()
    # os._exit: skip interpreter teardown (native libraries can hang or crash in it).
    os._exit(code)
