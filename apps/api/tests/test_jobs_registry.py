# File: apps/api/tests/test_jobs_registry.py
"""Parity between the closed sets: job kinds <-> handlers, sandbox codes <-> job codes.

Why: the same discipline as ``test_choices_parity.py``. A job kind without a handler is a job
that can be created and never run; a handler for a kind that does not exist is dead code; a
sandbox error code missing from the job's code set would be stored as something the API cannot
name. Each is a hand-kept pairing, so each is pinned here and fails the build when it drifts.
"""

from __future__ import annotations

import pytest

from uadas_api.accounts.permissions import Capability
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.errors import (
    MESSAGES,
    RETRYABLE,
    JobError,
    JobErrorCode,
    classify,
    message_for,
)
from uadas_api.jobs.registry import (
    JobHandler,
    get_handler,
    override_handler,
    registered_kinds,
)
from uadas_api.sandbox.errors import MESSAGES as SANDBOX_MESSAGES
from uadas_api.sandbox.errors import RETRYABLE as SANDBOX_RETRYABLE
from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.storage.errors import (
    ObjectExistsError,
    ObjectNotFoundError,
    ObjectTooLargeError,
    StorageUnavailableError,
)

# ------------------------------------------------------------------ kinds <-> handlers


def test_every_job_kind_has_a_handler_and_every_handler_has_a_kind() -> None:
    assert registered_kinds() == {kind.value for kind in JobKind}


@pytest.mark.parametrize("kind", [k.value for k in JobKind])
def test_each_handler_is_a_complete_job_handler(kind: str) -> None:
    handler = get_handler(kind)
    assert isinstance(handler, JobHandler)
    assert callable(handler.validate_params) and callable(handler.run)
    assert isinstance(handler.capability, Capability)


def test_an_unknown_kind_has_no_handler() -> None:
    with pytest.raises(KeyError):
        get_handler("rm_rf")


def test_overriding_a_handler_is_scoped_and_only_for_known_kinds() -> None:
    kind = JobKind.INGEST_DATASET.value
    original = get_handler(kind)
    fake = JobHandler(validate_params=lambda org, p: dict(p), run=lambda ctx: None)  # type: ignore[arg-type,return-value]
    with override_handler(kind, fake):
        assert get_handler(kind) is fake
    assert get_handler(kind) is original
    with pytest.raises(KeyError), override_handler("rm_rf", fake):
        pass


# --------------------------------------------------------------- the code vocabulary


def test_every_sandbox_code_is_a_job_code_with_the_same_sentence() -> None:
    for code in SandboxErrorCode:
        assert code.value in {c.value for c in JobErrorCode}, code
        assert MESSAGES[code.value] == SANDBOX_MESSAGES[code]


def test_every_job_code_has_a_sentence_and_no_sentence_is_orphaned() -> None:
    assert {c.value for c in JobErrorCode} == set(MESSAGES)
    assert all(text and text == text.strip() for text in MESSAGES.values())


def test_the_retryable_codes_are_exactly_the_ones_that_say_nothing_about_the_job() -> (
    None
):
    assert {"sandbox_unavailable", "storage_unavailable"} == RETRYABLE
    assert {c.value for c in SANDBOX_RETRYABLE} <= RETRYABLE


def test_a_code_outside_the_set_gets_the_generic_sentence() -> None:
    assert message_for("whatever-the-input-said") == message_for("internal_error")


def test_error_codes_fit_the_column() -> None:
    assert max(len(c.value) for c in JobErrorCode) <= 32
    assert max(len(text) for text in MESSAGES.values()) <= 200


# --------------------------------------------------------------------- classification


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (JobError(JobErrorCode.PARSE_ERROR), "parse_error", False),
        (JobError(JobErrorCode.STORAGE_UNAVAILABLE), "storage_unavailable", True),
        (SandboxError(SandboxErrorCode.TIMEOUT), "timeout", False),
        (
            SandboxError(SandboxErrorCode.SANDBOX_UNAVAILABLE),
            "sandbox_unavailable",
            True,
        ),
        (StorageUnavailableError("x"), "storage_unavailable", True),
        (ObjectNotFoundError("x"), "not_found", False),
        (ObjectTooLargeError("x"), "input_too_large", False),
        (ObjectExistsError("x"), "conflict", False),
        (RuntimeError("anything"), "internal_error", False),
        (KeyError("anything"), "internal_error", False),
    ],
)
def test_classification_by_type(
    error: BaseException, code: str, retryable: bool
) -> None:
    classified = classify(error)
    assert (classified.code.value, classified.retryable) == (code, retryable)


def test_classification_never_reads_the_exceptions_text() -> None:
    class Weird(Exception):
        def __str__(self) -> str:  # pragma: no cover - must never be called
            raise AssertionError("the message was read")

    assert classify(Weird("C:/secret/path")).code is JobErrorCode.INTERNAL_ERROR


def test_celerys_soft_time_limit_is_a_timeout_matched_by_name() -> None:
    class SoftTimeLimitExceeded(Exception):
        pass

    classified = classify(SoftTimeLimitExceeded())
    assert (classified.code, classified.retryable) == (JobErrorCode.TIMEOUT, False)
