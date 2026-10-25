# File: apps/api/tests/test_web_schemathesis_stateful.py
"""Stateful Schemathesis: a write sequence through the committed OpenAPI schema, per organization.

``test_web_schemathesis.py`` fuzzes the read (``GET``) operations with a viewer session. This is
its stateful sibling (3.8): an *authenticated, organization-scoped* sequence of writes --
``projects_create`` -> ``projects_get`` -> ``projects_rename`` -> ``projects_get`` ->
``projects_delete`` -> ``projects_get`` -- in which every response is validated against the schema
(documented status, content type, body shape), and the same sequence replayed with a **second
organization's** session, where every call must be ``404`` and organization A's project must come
out untouched (the tenant-isolation property, proved from the outside through the schema).

Why a hand-written sequence and not ``schema.as_state_machine()``: Schemathesis chains operations
through OpenAPI ``links``, and the committed ``openapi.json`` has none (Django Ninja does not emit
them), so the state machine would be a bag of unrelated calls with random ids, which the read fuzz
already covers. Injecting links in the test would exercise a schema that is not the one we ship, and
would run a unittest-style ``TestCase`` outside pytest-django's per-test transaction. The sequence
is driven by the schema's ``operationId``s instead (a renamed or removed operation fails the
lookup), builds ``Case`` objects so every call goes through the same WSGI application and the same
``validate_response`` as the fuzz, and draws only the project *names* from Hypothesis.

Why it cannot flake: Hypothesis is derandomized with its example database off and a hard example
cap (:data:`MAX_EXAMPLES` sequences of :data:`STEPS` requests), the names come from a fixed
alphabet with no control characters (so no value depends on the database engine), there are no
sleeps and no network (the WSGI application is called in process), and every sequence deletes what
it created so examples cannot collide on the unique project name.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from typing import Any

import pytest
import schemathesis
from django.core.signals import request_finished, request_started
from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from schemathesis.core.failures import FailureGroup
from web_support import World, make_world

from uadas_api.web import openapi as export
from uadas_api.workspaces.models import Project

SCHEMA_DICT = json.loads(export.COMMITTED_PATH.read_text(encoding="utf-8"))

pytestmark = pytest.mark.django_db

MAX_EXAMPLES = 5  # Hypothesis sequences per test
STEPS = 6  # requests in one sequence: create, get, rename, get, delete, get
SESSION_COOKIES = ("sessionid", "csrftoken")

# Letters, digits and a few separators: valid for ``ProjectName`` (1..200 characters after
# stripping), free of control characters and surrogates, and never all whitespace.
NAMES = st.text(
    st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters=" -_."),
    min_size=1,
    max_size=60,
).filter(
    lambda s: s.strip().lower() not in {"", "main", "other"}
)  # the world's own projects
# Fixed edge cases the generator would only rarely hit: padded (stripped by the API), the 200-char
# maximum, and non-ASCII.
EDGE_NAMES = ("  padded  ", "x" * 200, "Überblick – 数据")

hypothesis_settings = settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)


def _schema(document: dict[str, Any]) -> Any:
    loaded = schemathesis.openapi.from_dict(document)
    loaded.app = get_wsgi_application()
    return loaded


schema = _schema(SCHEMA_DICT)


@pytest.fixture(autouse=True)
def _keep_the_test_connection(world: World) -> Iterator[None]:
    """Do what Django's test ``Client`` does: a raw WSGI call must not close the test's connection.

    Same reason as in ``test_web_schemathesis.py``: ``request_started`` runs
    ``close_old_connections``, which inside the test's transaction would drop the test data. It
    depends on ``world`` so it runs after the world is built -- and that includes the two logged-in
    sessions, because ``World.api`` builds its Django test ``Client`` lazily and every request of a
    test ``Client`` *reconnects* these handlers when it finishes. A session first built inside the
    test body would re-arm ``close_old_connections`` and the next raw WSGI call would close the
    PostgreSQL connection mid-transaction ("the connection is closed"; SQLite hides it).
    """
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)
    yield
    request_started.connect(close_old_connections)
    request_finished.connect(close_old_connections)


@pytest.fixture
def world() -> World:
    built = make_world()
    for who in (
        "admin",
        "other",
    ):  # log both sessions in *before* the handlers are disconnected
        built.api(who)
    return built


class Caller:
    """One browser session (cookie + CSRF token) calling operations of a schema by ``operationId``.

    ``calls`` counts every request, so a test can assert the sequence's hard cap.
    """

    def __init__(self, world: World, who: str, loaded: Any = None) -> None:
        client = world.api(who).client
        self.cookies = {name: client.cookies[name].value for name in SESSION_COOKIES}
        self.schema = schema if loaded is None else loaded
        self.calls = 0

    def call(
        self,
        operation_id: str,
        *,
        path: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> Any:
        """Send ``operation_id`` and return the response *after* schema-validating it."""
        operation = self.schema.find_operation_by_id(operation_id)
        extra: dict[str, Any] = {}
        if body is not None:
            extra = {"body": body, "media_type": "application/json"}
        case = operation.Case(
            path_parameters=path,
            cookies=self.cookies,
            # Session auth enforces CSRF on unsafe methods: send the token as the SPA does.
            headers={"X-CSRFToken": self.cookies["csrftoken"]},
            **extra,
        )
        self.calls += 1
        response = case.call()
        case.validate_response(response)
        return response


def _project_path(org_id: object, project_id: object) -> dict[str, str]:
    return {"org_id": str(org_id), "project_id": str(project_id)}


def _sequence(
    caller: Caller, org_id: object, first: str, second: str, project_id: object = None
) -> list[Any]:
    """create -> get -> rename -> get -> delete -> get; returns the six responses.

    With ``project_id`` given (a project of *another* organization, for the replay) it is the
    target of every call after the create; otherwise the id the create returned is used.
    """
    created = caller.call(
        "projects_create", path={"org_id": str(org_id)}, body={"name": first}
    )
    if project_id is None:
        project_id = created.json()["id"] if created.status_code == 201 else "none"
    path = _project_path(org_id, project_id)
    return [
        created,
        caller.call("projects_get", path=path),
        caller.call("projects_rename", path=path, body={"name": second}),
        caller.call("projects_get", path=path),
        caller.call("projects_delete", path=path),
        caller.call("projects_get", path=path),
    ]


def _own_organization_sequence(world: World, first: str, second: str) -> None:
    caller = Caller(world, "admin")
    created, read, renamed, reread, deleted, gone = _sequence(
        caller, world.org.pk, first, second
    )
    assert [r.status_code for r in (created, read, renamed, reread, deleted, gone)] == [
        201,
        200,
        200,
        200,
        204,
        404,
    ]
    assert caller.calls == STEPS
    # the writes took effect, observed through the schema-validated reads in between
    assert read.json()["name"] == first.strip()
    assert reread.json()["name"] == second.strip()
    assert read.json()["id"] == reread.json()["id"] == created.json()["id"]


@hypothesis_settings
@given(first=NAMES, second=NAMES)
def test_create_get_rename_delete_follows_the_schema_in_the_callers_own_organization(
    world: World, first: str, second: str
) -> None:
    _own_organization_sequence(world, first, second)


@pytest.mark.parametrize("name", EDGE_NAMES, ids=["padded", "max-length", "unicode"])
def test_the_sequence_holds_for_the_edge_case_names(world: World, name: str) -> None:
    _own_organization_sequence(world, name, name[::-1].strip() or "r")


def _assert_project_untouched(world: World) -> None:
    project = Project.objects.get(pk=world.project.pk)
    assert project.name == "Main"
    assert project.organization_id == world.org.pk
    assert Project.objects.filter(organization=world.org).count() == 1


@hypothesis_settings
@given(first=NAMES, second=NAMES)
def test_the_same_sequence_with_another_organizations_session_is_404_on_every_call(
    world: World, first: str, second: str
) -> None:
    caller = Caller(world, "other")  # the owner of organization B
    # Organization A's URL space, A's real project: B must not even learn that it exists.
    responses = _sequence(caller, world.org.pk, first, second, world.project.pk)
    assert [r.status_code for r in responses] == [404] * STEPS
    assert caller.calls == STEPS
    _assert_project_untouched(world)
    assert not Project.objects.filter(
        name=first.strip()
    ).exists()  # the create wrote nothing


def test_another_organizations_session_cannot_reach_a_foreign_project_through_its_own_org(
    world: World,
) -> None:
    # B's own organization id with A's project id: the project lookup is tenant-scoped.
    caller = Caller(world, "other")
    path = _project_path(world.other_org.pk, world.project.pk)
    for operation_id, body in (
        ("projects_get", None),
        ("projects_rename", {"name": "taken over"}),
        ("projects_delete", None),
    ):
        assert caller.call(operation_id, path=path, body=body).status_code == 404
    _assert_project_untouched(world)


def test_the_isolation_checks_have_a_positive_twin_in_the_owning_organization(
    world: World,
) -> None:
    # The exact URLs the replay above gets 404 for are 200 / 200 / 204 for the project's owner
    # organization: the 404s are isolation, not a broken route or a missing project.
    caller = Caller(world, "admin")
    path = _project_path(world.org.pk, world.project.pk)
    assert caller.call("projects_get", path=path).status_code == 200
    renamed = caller.call("projects_rename", path=path, body={"name": "Renamed"})
    assert renamed.status_code == 200
    assert Project.objects.get(pk=world.project.pk).name == "Renamed"
    # Main still owns a dataset (PROTECT), so the *documented* answer to a delete is 409, not 204.
    assert caller.call("projects_delete", path=path).status_code == 409


def test_the_response_validation_can_fail_when_the_schema_does_not_document_a_status(
    world: World,
) -> None:
    # Positive twin of ``validate_response``: the same cross-organization 404 is rejected against a
    # schema that does not document it, so "every response conforms" cannot be vacuously true.
    narrowed = copy.deepcopy(SCHEMA_DICT)
    operation = narrowed["paths"]["/api/organizations/{org_id}/projects/{project_id}"][
        "get"
    ]
    del operation["responses"]["404"]
    caller = Caller(world, "other", _schema(narrowed))
    with pytest.raises(FailureGroup, match="Undocumented status code"):
        caller.call("projects_get", path=_project_path(world.org.pk, world.project.pk))


def test_every_operation_the_sequence_uses_exists_in_the_committed_schema() -> None:
    ids = ("projects_create", "projects_get", "projects_rename", "projects_delete")
    methods = {schema.find_operation_by_id(i).method.upper() for i in ids}
    assert methods == {"POST", "GET", "PATCH", "DELETE"}
    with pytest.raises(LookupError):
        schema.find_operation_by_id("projects_no_such_operation")
