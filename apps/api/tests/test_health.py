# File: apps/api/tests/test_health.py
"""``GET /api/health`` -- the one endpoint Phase 3.1 ships.

Why: it is a liveness probe for the container orchestrator, so it must answer without
touching the database (a DB outage must not get the API pod killed and restarted in a
loop). None of these tests request the ``db`` fixture, and pytest-django blocks all
database access unless a test does -- so a passing test is the proof that the endpoint
is DB-free.
"""

from __future__ import annotations

from django.test import Client

from uadas_api.api import api, build_api


def test_health_returns_ok(client: Client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Content-Type"].startswith("application/json")


def test_health_is_get_only(client: Client) -> None:
    assert client.post("/api/health").status_code == 405


def test_health_is_in_the_openapi_contract() -> None:
    # Generated in-process: the HTTP route is dev-only (see below), the contract is not.
    schema = api.get_openapi_schema()
    assert "get" in schema["paths"]["/api/health"]


def test_schema_and_docs_are_not_served_outside_debug(client: Client) -> None:
    # The test settings run with DEBUG off. An unauthenticated schema in production
    # hands an attacker the full endpoint map, so the route is removed, not guarded.
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_schema_and_docs_are_served_in_debug() -> None:
    dev_api = build_api(debug=True)
    assert dev_api.docs_url == "/docs"
    assert dev_api.openapi_url == "/openapi.json"
    prod_api = build_api(debug=False)
    assert prod_api.docs_url is None
    assert prod_api.openapi_url is None
