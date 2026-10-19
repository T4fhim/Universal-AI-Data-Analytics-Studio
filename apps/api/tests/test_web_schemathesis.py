# File: apps/api/tests/test_web_schemathesis.py
"""Schemathesis against the committed OpenAPI schema, in process (no network, no server).

This is the Schemathesis item of 3.8, kept small and deterministic:

* **fuzz** -- the read (``GET``) operations are called with generated path / query parameters
  (positive and negative) through the real Django WSGI application, with a logged-in session, and every
  response must be a documented status, content type and body (``not_a_server_error``,
  ``status_code_conformance``, ``content_type_conformance``, ``response_schema_conformance``).
  Hypothesis is derandomized and its database off, so a failure reproduces and the run cannot flake.
* **smoke** -- every ``GET`` operation is then called *with real ids* (a project that holds a dataset,
  a chart, a dashboard, a job, a report ...) and must answer ``200`` with a body that conforms to its
  schema: the conformance of the success shapes, which random ids never reach.

Write operations are covered by the resource, stage, upload and IDOR tests, which know their bodies.
The WSGI application is built from the same settings as the rest of the suite and the schema is the
committed ``openapi.json`` (so this also fails if that file stops describing the running API).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import schemathesis
from django.core.signals import request_finished, request_started
from django.core.wsgi import get_wsgi_application
from django.db import close_old_connections
from factories import factory_for
from hypothesis import HealthCheck, settings
from web_support import World, make_world

from uadas_api.exports.models import Report
from uadas_api.jobs.models import Job
from uadas_api.pipeline.models import PipelineEdge, Recipe
from uadas_api.web import openapi as export
from uadas_api.workspaces.models import ChartSpec, Dashboard

schema = schemathesis.openapi.from_dict(
    json.loads(export.COMMITTED_PATH.read_text(encoding="utf-8"))
)
schema.app = get_wsgi_application()

pytestmark = pytest.mark.django_db

_SESSION: dict[str, str] = {}


@schema.auth(
    refresh_interval=None
)  # never cached: the session changes with every test's database
class SessionCookieAuth:
    """Give every generated case the logged-in session cookie (and let Schemathesis break it).

    Declaring the provider (rather than passing a cookie to ``call``) lets Schemathesis's
    ``ignored_auth`` and ``negative_data_rejection`` checks send a missing or invalid session and
    prove the API answers ``401`` -- the authentication guard exercised from the outside.
    """

    def get(self, case: Any, ctx: Any) -> str:
        # At collection time (Schemathesis pre-generates its coverage cases) no test database
        # exists yet, so those cases carry an invalid session and must be answered 401.
        return _SESSION.get("sessionid", "collection-time-placeholder")

    def set(self, case: Any, data: str, ctx: Any) -> None:
        case.cookies = {**(case.cookies or {}), "sessionid": data}


@pytest.fixture(autouse=True)
def _keep_the_test_connection(world: World) -> Iterator[None]:
    """Do what Django's test ``Client`` does: a raw WSGI call must not close the test's connection.

    ``request_started`` runs ``close_old_connections``; inside the test's transaction (autocommit
    off) PostgreSQL's connection would be judged unusable and closed, taking the test data with it.
    It depends on ``world`` so it runs *after* the world is built: the test ``Client`` used to build
    it reconnects these signal handlers after each of its own requests.
    """
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)
    yield
    request_started.connect(close_old_connections)
    request_finished.connect(close_old_connections)


@pytest.fixture
def world() -> World:
    built = make_world()
    ChartSpec.objects.create(
        organization=built.org,
        project=built.project,
        dataset=built.dataset,
        chart_type="histogram",
        title="c",
        spec={"column": "id"},
    )
    Dashboard.objects.create(organization=built.org, project=built.project, name="d")
    Report.objects.create(
        organization=built.org,
        project=built.project,
        title="r",
        format="html",
        config={"dataset_id": str(built.dataset.pk)},
    )
    factory_for(Job).create(built.org, project=built.project)
    factory_for(Recipe).create(built.org, project=built.project)
    factory_for(PipelineEdge).create(built.org, project=built.project)
    _SESSION["sessionid"] = built.api("viewer").client.cookies["sessionid"].value
    return built


@schema.include(method="GET").parametrize()
@settings(
    max_examples=12,
    deadline=None,
    derandomize=True,
    database=None,
    suppress_health_check=list(HealthCheck),
)
def test_read_operations_conform_to_the_schema_under_generated_input(
    case: Any, world: World
) -> None:
    case.call_and_validate()


def _real_ids(world: World) -> dict[str, str]:
    ids = {
        "org_id": world.org.pk,
        "project_id": world.project.pk,
        "dataset_id": world.dataset.pk,
        "chart_id": ChartSpec.objects.get(project=world.project).pk,
        "dashboard_id": Dashboard.objects.get(project=world.project).pk,
        "job_id": Job.objects.get(project=world.project).pk,
        "report_id": Report.objects.get(project=world.project).pk,
        "recipe_id": Recipe.objects.get(project=world.project).pk,
        "membership_id": world.viewer.pk,
    }
    return {name: str(value) for name, value in ids.items()}


def test_every_read_operation_answers_200_with_a_conforming_body_for_real_ids(
    world: World,
) -> None:
    ids = _real_ids(world)
    checked: list[str] = []
    for result in schema.get_all_operations():
        operation = result.ok()  # type: ignore[union-attr]
        if operation.method.upper() != "GET":
            continue
        names = [p for p in operation.path.split("/") if p.startswith("{")]
        parameters = {name[1:-1]: ids[name[1:-1]] for name in names}
        case = operation.Case(
            path_parameters=parameters, cookies={"sessionid": _SESSION["sessionid"]}
        )
        response = case.call()
        # The fixture's job is an ingest job (no stage result: 404) and its report is pending
        # (no file yet: 409); every other read of existing data is a 200.
        expected = {"stage-result": 404, "download": 409}.get(
            operation.path.rsplit("/", 1)[-1], 200
        )
        assert response.status_code == expected, (operation.label, response.status_code)
        case.validate_response(response)
        checked.append(operation.label)
    assert len(checked) >= 28  # the whole read surface was visited (guards the guard)
