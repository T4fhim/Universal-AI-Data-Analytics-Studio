# File: apps/api/tests/test_database.py
"""The configured database really answers -- and in CI it really is PostgreSQL.

Why: until a model exists, nothing else in the suite opens a connection, so the CI
``api-test`` job's Postgres service container would be decoration. This test requests the
``db`` fixture (which creates the test database and runs the built-in migrations) and
asserts the engine matches ``DATABASE_URL``: with the CI value set, a green run is proof
the production engine was exercised, not an SQLite fallback.
"""

from __future__ import annotations

import os

import pytest
from django.db import connection

_VENDOR_BY_SCHEME = {"postgres": "postgresql", "postgresql": "postgresql"}


@pytest.mark.django_db
def test_database_round_trip_on_the_configured_engine() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)

    scheme = os.environ.get("DATABASE_URL", "").partition(":")[0]
    assert connection.vendor == _VENDOR_BY_SCHEME.get(scheme, "sqlite")
