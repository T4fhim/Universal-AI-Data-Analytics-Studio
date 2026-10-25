# File: apps/api/tests/test_jobs_ci_guard.py
"""CI must not quietly lose the real-worker test (3.5).

Why: ``test_jobs_integration.py`` is the only test that puts a real Redis, a real ``celery
worker`` process, PostgreSQL and MinIO together, and it skips unless ``JOBS_INTEGRATION=1`` and
the services' variables are exported. A renamed variable or a dropped ``ci.yml`` step would turn
those tests into skips -- a green build with the strongest evidence gone. Same two layers as
``test_storage_ci_guard.py``: this test fails when ``CI=true`` is set but the environment is
incomplete, and ``ci.yml`` caps the number of skipped tests.
"""

from __future__ import annotations

import os

import pytest
from jobs_support import (
    database_url,
    integration_enabled,
    integration_required_but_missing,
)

COMPLETE = {
    "JOBS_INTEGRATION": "1",
    "CELERY_BROKER_URL": "redis://localhost:6379/5",
    "DATABASE_URL": "postgres://uadas:uadas@localhost:5432/uadas",
    "STORAGE_INTEGRATION": "1",
    "STORAGE_ENDPOINT_URL": "http://localhost:9000",
    "STORAGE_BUCKET": "b",
    "STORAGE_ACCESS_KEY_ID": "k",
    "STORAGE_SECRET_ACCESS_KEY": "s",
}


def test_a_complete_environment_enables_the_integration_tests() -> None:
    assert integration_enabled(COMPLETE)
    assert not integration_required_but_missing({"CI": "true", **COMPLETE})


def test_redis_url_alone_is_enough_for_the_broker() -> None:
    env = {k: v for k, v in COMPLETE.items() if k != "CELERY_BROKER_URL"}
    assert not integration_enabled(env)
    assert integration_enabled({**env, "REDIS_URL": "redis://localhost:6379/5"})


@pytest.mark.parametrize(
    "lost",
    [
        "JOBS_INTEGRATION",
        "CELERY_BROKER_URL",
        "DATABASE_URL",
        "STORAGE_INTEGRATION",
        "STORAGE_BUCKET",
    ],
)
def test_ci_that_lost_part_of_the_environment_is_flagged(lost: str) -> None:
    env = {"CI": "true", **{k: v for k, v in COMPLETE.items() if k != lost}}
    assert integration_required_but_missing(env)


def test_sqlite_is_not_a_database_the_worker_can_share() -> None:
    env = {**COMPLETE, "DATABASE_URL": "sqlite:///db.sqlite3"}
    assert not integration_enabled(env)


def test_a_developer_machine_without_the_environment_is_not_flagged() -> None:
    assert not integration_required_but_missing({})
    assert not integration_required_but_missing({"CI": "false"})


def test_the_database_url_names_the_test_database() -> None:
    url = database_url(
        {"USER": "u", "PASSWORD": "p", "HOST": "", "PORT": "", "NAME": "test_uadas"}
    )
    assert url == "postgres://u:p@localhost:5432/test_uadas"


def test_this_run_has_the_integration_environment_when_it_is_a_ci_run() -> None:
    assert not integration_required_but_missing(os.environ), (
        "CI=true but the real-worker tests would skip: JOBS_INTEGRATION=1, CELERY_BROKER_URL "
        "(or REDIS_URL), a postgres DATABASE_URL and the STORAGE_* variables must be set on the "
        "pytest step of the api-test job"
    )
