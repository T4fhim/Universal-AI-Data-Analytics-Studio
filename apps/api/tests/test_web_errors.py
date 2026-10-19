# File: apps/api/tests/test_web_errors.py
"""The error envelope and the request-size caps.

What is pinned: every refusal is ``{"error": {"code", "message", "details"}}`` with a code from the
closed set; a ``422`` names *where* a field is invalid and pydantic's error *type*, never the value
the client sent; an oversized JSON body is ``413`` before any handler runs; an unauthenticated or
foreign request gets the same body shape as any other. Each refusal has its positive twin.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from apihelpers import Api
from web_support import World, error_code, make_world

from uadas_api.web.errors import (
    CODE_FOR_STATUS,
    ERROR_RESPONSES,
    ApiError,
    ErrorCode,
    error_body,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def world() -> World:
    return make_world()


def test_every_status_of_the_envelope_maps_to_a_code_of_the_closed_set() -> None:
    assert set(CODE_FOR_STATUS.values()) <= set(ErrorCode)
    assert set(ERROR_RESPONSES) == set(CODE_FOR_STATUS)
    for status in CODE_FOR_STATUS:
        body = error_body(status, "A sentence.")
        assert set(body["error"]) == {"code", "message", "details"}
    with pytest.raises(ValueError):
        ApiError(500, "no such envelope status")
    with pytest.raises(KeyError):
        error_body(418, "teapot")


def test_each_refusal_status_uses_the_envelope(world: World) -> None:
    projects = f"/api/organizations/{world.org.pk}/projects"
    cases: list[tuple[Any, int, str]] = [
        (Api().get(projects), 401, "unauthenticated"),
        (world.api("viewer").post(projects, {"name": "x"}), 403, "forbidden"),
        (
            world.api("editor").post(projects, {"name": "x"}, csrf=False),
            403,
            "forbidden",
        ),
        (world.api("outsider").get(projects), 404, "not_found"),
        (world.api("editor").post(projects, {"name": "Main"}), 409, "conflict"),
        (world.api("editor").post(projects, {"name": ""}), 422, "invalid_request"),
    ]
    for response, status, code in cases:
        assert response.status_code == status
        assert error_code(response) == code
        assert response["Content-Type"].startswith("application/json")
    assert (
        world.api("editor").post(projects, {"name": "fresh"}).status_code == 201
    )  # twin


def test_a_422_never_echoes_the_value_the_client_sent(world: World) -> None:
    secret = "s3cr3t-value-that-must-not-come-back"
    response = world.api("editor").post(
        f"/api/organizations/{world.org.pk}/projects", {"name": {"nested": secret}}
    )
    assert response.status_code == 422
    assert secret not in response.content.decode()
    for detail in response.json()["error"]["details"]:
        assert set(detail) == {"loc", "type"}


def test_an_unknown_organization_and_a_foreign_one_answer_identically(
    world: World,
) -> None:
    missing = world.api("outsider").get(
        "/api/organizations/00000000-0000-4000-8000-000000000000/projects"
    )
    foreign = world.api("outsider").get(f"/api/organizations/{world.org.pk}/projects")
    assert missing.status_code == foreign.status_code == 404
    assert missing.json() == foreign.json()


def test_an_oversized_json_body_is_refused_before_the_handler(world: World) -> None:
    projects = f"/api/organizations/{world.org.pk}/projects"
    client = world.api("editor")
    big = json.dumps({"name": "x" * (1024 * 1024 + 10)})
    refused = client.client.generic(
        "POST",
        projects,
        big,
        content_type="application/json",
        headers={"X-CSRFToken": client.token},
    )
    assert refused.status_code == 413 and error_code(refused) == "payload_too_large"
    assert (
        client.post(projects, {"name": "x" * 150}).status_code == 201
    )  # the twin: a normal body
