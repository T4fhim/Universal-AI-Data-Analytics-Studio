# File: apps/api/tests/test_storage_ci_guard.py
"""CI must not quietly lose the real-store tests (3.4).

Why: about a hundred storage tests run against a real MinIO only when ``STORAGE_INTEGRATION=1``
and the ``STORAGE_*`` variables are present; without them they *skip*, and a skipped test is
a green build. A renamed variable or a dropped workflow step would therefore remove the
strongest evidence for the atomicity and isolation claims with nobody noticing. Two layers:
this test fails when GitHub Actions' ``CI=true`` is set but the integration environment is
not, and ``ci.yml`` additionally fails the job if more tests skip than the known few.
"""

from __future__ import annotations

import os

import pytest
from storage_support import integration_enabled, integration_required_but_missing

COMPLETE = {
    "STORAGE_INTEGRATION": "1",
    "STORAGE_ENDPOINT_URL": "http://localhost:9000",
    "STORAGE_BUCKET": "b",
    "STORAGE_ACCESS_KEY_ID": "k",
    "STORAGE_SECRET_ACCESS_KEY": "s",
}


def test_ci_with_the_integration_environment_is_fine() -> None:
    assert integration_enabled(COMPLETE)
    assert not integration_required_but_missing({"CI": "true", **COMPLETE})


@pytest.mark.parametrize(
    "lost", ["STORAGE_INTEGRATION", "STORAGE_ENDPOINT_URL", "STORAGE_ACCESS_KEY_ID"]
)
def test_ci_that_lost_part_of_the_integration_environment_is_flagged(lost: str) -> None:
    env = {"CI": "true", **{k: v for k, v in COMPLETE.items() if k != lost}}
    assert integration_required_but_missing(env)


def test_a_developer_machine_without_the_environment_is_not_flagged() -> None:
    assert not integration_required_but_missing({})
    assert not integration_required_but_missing({"CI": "false"})


def test_this_run_has_the_integration_environment_when_it_is_a_ci_run() -> None:
    assert not integration_required_but_missing(os.environ), (
        "CI=true but the real-store tests would skip: STORAGE_INTEGRATION and the STORAGE_* "
        "variables must be set on the pytest step of the api-test job"
    )
