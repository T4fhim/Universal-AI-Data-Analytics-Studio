# File: apps/api/uadas_api/sandbox/errors.py
"""The closed set of sandbox failures, each with one fixed, safe sentence.

Why a closed enum and fixed messages: what goes wrong inside a parser is attacker-controlled
text (a crafted file can put anything in an exception message: a path, another tenant's
data, a prompt-injection) and is useless to the end user. So the child reports only a
*code*, the parent accepts only codes from this set (anything else becomes ``protocol_error``),
and the sentence shown to a user is looked up here -- never built from an exception. A
:class:`SandboxError` has no free-text constructor argument for the same reason.

Standard library only: the child imports this module.
"""

from __future__ import annotations

from enum import StrEnum


class SandboxErrorCode(StrEnum):
    """Why a file could not be turned into a table. Stable: stored on job rows."""

    UNSUPPORTED_TYPE = "unsupported_type"
    INPUT_TOO_LARGE = "input_too_large"
    DECOMPRESSION_BOMB = "decompression_bomb"
    TIMEOUT = "timeout"
    MEMORY_LIMIT = "memory_limit"
    CPU_LIMIT = "cpu_limit"
    OUTPUT_TOO_LARGE = "output_too_large"
    TOO_MANY_ROWS = "too_many_rows"
    TOO_MANY_COLUMNS = "too_many_columns"
    MULTIPLE_TABLES = "multiple_tables"
    PARSE_ERROR = "parse_error"
    BLOCKED_OPERATION = "blocked_operation"
    RESOURCE_LIMIT = "resource_limit"
    SANDBOX_CRASHED = "sandbox_crashed"
    PROTOCOL_ERROR = "protocol_error"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"


MESSAGES: dict[SandboxErrorCode, str] = {
    SandboxErrorCode.UNSUPPORTED_TYPE: (
        "This file type is not supported, or the file does not match its extension."
    ),
    SandboxErrorCode.INPUT_TOO_LARGE: "The file is larger than the allowed upload size.",
    SandboxErrorCode.DECOMPRESSION_BOMB: (
        "The file expands to far more data than it is allowed to contain."
    ),
    SandboxErrorCode.TIMEOUT: "Reading the file took too long and was stopped.",
    SandboxErrorCode.MEMORY_LIMIT: "Reading the file needed more memory than is allowed.",
    SandboxErrorCode.CPU_LIMIT: "Reading the file used more processing time than is allowed.",
    SandboxErrorCode.OUTPUT_TOO_LARGE: "The table in this file is larger than is allowed.",
    SandboxErrorCode.TOO_MANY_ROWS: "The table in this file has more rows than is allowed.",
    SandboxErrorCode.TOO_MANY_COLUMNS: (
        "The table in this file has more columns than is allowed."
    ),
    SandboxErrorCode.MULTIPLE_TABLES: (
        "The file contains more than one table; choosing one is not supported yet."
    ),
    SandboxErrorCode.PARSE_ERROR: "The file could not be read as a table.",
    SandboxErrorCode.BLOCKED_OPERATION: (
        "The file tried to do something that is not allowed while reading it."
    ),
    SandboxErrorCode.RESOURCE_LIMIT: "Reading the file exceeded a resource limit.",
    SandboxErrorCode.SANDBOX_CRASHED: "The file could not be read safely.",
    SandboxErrorCode.PROTOCOL_ERROR: "The file could not be read safely.",
    SandboxErrorCode.SANDBOX_UNAVAILABLE: (
        "File reading is temporarily unavailable; please try again."
    ),
}

# Failures that say nothing about the file: the same file may well succeed later.
RETRYABLE: frozenset[SandboxErrorCode] = frozenset(
    {SandboxErrorCode.SANDBOX_UNAVAILABLE}
)


def parse_code(value: object) -> SandboxErrorCode:
    """Return ``value`` as a code, or ``protocol_error`` if it is not one of the closed set."""
    if isinstance(value, str):
        try:
            return SandboxErrorCode(value)
        except ValueError:
            pass
    return SandboxErrorCode.PROTOCOL_ERROR


class SandboxError(Exception):
    """A file was refused or could not be parsed. Carries a code, never free text."""

    def __init__(self, code: SandboxErrorCode) -> None:
        super().__init__(MESSAGES[code])
        self.code = code

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE
