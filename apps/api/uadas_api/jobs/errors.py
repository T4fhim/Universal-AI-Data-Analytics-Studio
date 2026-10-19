# File: apps/api/uadas_api/jobs/errors.py
"""A job's failure vocabulary: closed codes, fixed sentences, and the classifier.

Why: what is stored on a failed job and shown to the user must be safe to show and must not
leak. An exception raised while handling a tenant's file can carry a path, a fragment of the
data, a connection string, another tenant's name. So a job never stores ``str(exception)``: the
failure is mapped to one of :class:`JobErrorCode` -- a closed set -- and the sentence shown is
looked up in :data:`MESSAGES`. The classifier (:func:`classify`) reads only the *type* of the
exception, never its text, and unknown types become ``internal_error`` with a generic
sentence; the server log records the class and the traceback frames (no message) so an
operator can still find the line.

``RETRYABLE`` marks codes that say nothing about the job itself (the store or the sandbox was
momentarily unavailable): only those are retried, with backoff, and only up to
``JOBS_MAX_ATTEMPTS``. Everything else fails at once -- retrying a file that cannot be parsed
helps nobody.

The sandbox's codes are mirrored here (``tests/test_jobs_errors.py`` fails if they drift) so the
column stays one closed set.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from django.core.exceptions import ValidationError
from django.db import OperationalError

from uadas_api.sandbox.errors import MESSAGES as SANDBOX_MESSAGES
from uadas_api.sandbox.errors import SandboxError
from uadas_api.storage.errors import (
    DisallowedContentTypeError,
    InvalidKeyError,
    ObjectExistsError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectTooLargeError,
    StorageNotConfiguredError,
    StorageUnavailableError,
)


class JobErrorCode(StrEnum):
    """Why a job failed. Stable: stored on job rows and (later) returned by the API."""

    # --- from the sandbox / admission (mirrors SandboxErrorCode) ---
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
    # --- from the job machinery ---
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    INVALID_REQUEST = "invalid_request"
    # 3.6: the core refused or could not complete a stage operation on this dataset's columns or
    # values (a missing column, too few rows, a singular matrix ...). The core's text is never kept.
    OPERATION_FAILED = "operation_failed"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    STORAGE_ERROR = "storage_error"
    TOO_MANY_ATTEMPTS = "too_many_attempts"
    WORKER_LOST = "worker_lost"
    INTERNAL_ERROR = "internal_error"


MESSAGES: dict[str, str] = {
    **{code.value: text for code, text in SANDBOX_MESSAGES.items()},
    JobErrorCode.FORBIDDEN: "You are no longer allowed to do this.",
    JobErrorCode.NOT_FOUND: "Something this job needs no longer exists.",
    JobErrorCode.CONFLICT: "This conflicts with something that already exists.",
    JobErrorCode.INVALID_REQUEST: "The request for this job was not valid.",
    JobErrorCode.OPERATION_FAILED: "The operation could not be applied to this dataset.",
    JobErrorCode.STORAGE_UNAVAILABLE: "Storage is temporarily unavailable; please try again.",
    JobErrorCode.STORAGE_ERROR: "The stored file could not be used.",
    JobErrorCode.TOO_MANY_ATTEMPTS: "The job did not finish after several attempts.",
    JobErrorCode.WORKER_LOST: "The job was interrupted and could not be completed.",
    JobErrorCode.INTERNAL_ERROR: "Something went wrong; the problem has been logged.",
}

RETRYABLE: frozenset[str] = frozenset(
    {JobErrorCode.SANDBOX_UNAVAILABLE.value, JobErrorCode.STORAGE_UNAVAILABLE.value}
)

MAX_MESSAGE_CHARS = 200


def message_for(code: str) -> str:
    """The sentence for ``code`` (a code outside the set gets the generic internal one)."""
    return MESSAGES.get(code, MESSAGES[JobErrorCode.INTERNAL_ERROR])


class JobError(Exception):
    """A handler's own failure: carries a code, never free text. ``retryable`` follows the code."""

    def __init__(self, code: JobErrorCode, *, retryable: bool | None = None) -> None:
        super().__init__(MESSAGES[code])
        self.code = code
        self.retryable = code.value in RETRYABLE if retryable is None else retryable


class JobCancelledError(Exception):
    """The handler honoured a cancellation request at a checkpoint."""


class JobLostError(Exception):
    """The job is no longer ours: another worker took it over, the sweeper failed it, ..."""


class JobTransitionError(ValidationError):
    """A write would make an illegal state change, or touch a terminal (immutable) job."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="job_transition")


class IdempotencyConflictError(ValidationError):
    """An idempotency key was reused for a different request."""

    def __init__(self) -> None:
        super().__init__(
            "This idempotency key was already used for a different request.",
            code="idempotency_conflict",
        )


class JobPermissionError(Exception):
    """The caller may not create or cancel jobs in this organization."""


@dataclass(frozen=True)
class Classified:
    """What an exception means for a job."""

    code: JobErrorCode
    retryable: bool


def classify(error: BaseException) -> Classified:
    """Map ``error`` to a code from its *type* only (its text is never read)."""
    if isinstance(error, JobError):
        return Classified(error.code, error.retryable)
    if isinstance(error, SandboxError):
        return Classified(JobErrorCode(error.code.value), error.retryable)
    if isinstance(error, StorageUnavailableError | StorageNotConfiguredError):
        return Classified(JobErrorCode.STORAGE_UNAVAILABLE, True)
    if isinstance(error, ObjectNotFoundError):
        return Classified(JobErrorCode.NOT_FOUND, False)
    if isinstance(error, ObjectTooLargeError):
        return Classified(JobErrorCode.INPUT_TOO_LARGE, False)
    if isinstance(error, ObjectExistsError):
        return Classified(JobErrorCode.CONFLICT, False)
    if isinstance(
        error, ObjectIntegrityError | InvalidKeyError | DisallowedContentTypeError
    ):
        return Classified(JobErrorCode.STORAGE_ERROR, False)
    if isinstance(error, OperationalError):
        return Classified(JobErrorCode.INTERNAL_ERROR, True)  # the database blinked
    # Celery's soft time limit, matched by name so this module never imports Celery.
    if type(error).__name__ == "SoftTimeLimitExceeded":
        return Classified(JobErrorCode.TIMEOUT, False)
    return Classified(JobErrorCode.INTERNAL_ERROR, False)
