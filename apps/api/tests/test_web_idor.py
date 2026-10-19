# File: apps/api/tests/test_web_idor.py
"""A cross-tenant IDOR walk over **every operation in the OpenAPI schema** (discovery, not a list).

The attacker is an owner of organization B. The victim is organization A, which holds one of
everything (project, dataset, chart, dashboard, job, report, recipe, lineage). For each operation
discovered in ``api.get_openapi_schema()`` the walk checks three attacks, and fails if a new route
cannot be classified, so **a route cannot skip it**:

1. *Foreign organization in the path* -- B's user names A's organization: always ``404``, identical
   to a missing organization, and no byte of A's data in the body.
2. *Own organization, foreign resource ids* -- B's organization and project, A's dataset / chart /
   job / report / ... ids: ``404`` (never 2xx) for every operation that names a resource, and no
   A marker in the body of any answer.
3. *Foreign ids inside a request body* (``dataset_id``, a dashboard tile's ``chart_id``, a stage
   run's dataset ...) with B's own path: refused with ``404`` / ``422``, nothing created, and -- the
   positive twin -- the same body with B's *own* ids succeeds, so the refusal is the ownership
   check and not a malformed request.

At the end A's rows and A's stored objects are byte-for-byte what they were.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from factories import factory_for
from web_support import World, make_world, store_dataset

from uadas_api.api import api
from uadas_api.exports.models import Report
from uadas_api.jobs.models import Job
from uadas_api.pipeline.models import PipelineEdge, Recipe
from uadas_api.stages.catalog import STAGE_OPERATIONS
from uadas_api.storage.store import get_store
from uadas_api.tenancy import iter_tenant_models
from uadas_api.workspaces.models import ChartSpec, Dashboard, DatasetRecord, Project
from uadas_core.services.analysis_orchestrator_service import PipelineStage

pytestmark = pytest.mark.django_db

# Operations that take no organization in the path: nothing of A's can be named.
ORG_AGNOSTIC = {"health", "me", "organizations_list", "organizations_create"}
# Path parameters the walk knows how to fill. A new name fails the test until it is added.
RESOURCE_PARAMS = {
    "dataset_id",
    "chart_id",
    "dashboard_id",
    "job_id",
    "report_id",
    "recipe_id",
    "membership_id",
}
CONTAINER_PARAMS = {"org_id", "project_id"}

# A valid run body per stage (one operation, valid parameters), so a run is refused for ownership,
# never for being malformed.
STAGE_RUN: dict[str, tuple[str, dict[str, Any]]] = {
    "understand": ("profile_dataset", {}),
    "clean": ("drop_missing_values", {}),
    "explore": ("aggregate", {"group_by": ["g"], "agg_column": "x"}),
    "analyze": ("compute_correlation", {}),
    "visualize": ("build_chart", {"chart_type": "bar", "category_column": "g"}),
    "predict": (
        "forecast_linear_regression",
        {"date_column": "g", "value_column": "x", "periods": 2},
    ),
}


def _tile(chart: Any) -> dict[str, Any]:
    return {"chart_id": str(chart), "row": 0, "column": 0}


BODIES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "organizations_create": lambda i: {"name": "walk-org"},
    "member_update_role": lambda i: {"role": "viewer"},
    "projects_create": lambda i: {"name": f"walk-{uuid.uuid4().hex[:8]}"},
    "projects_rename": lambda i: {"name": f"walk-{uuid.uuid4().hex[:8]}"},
    "charts_create": lambda i: {
        "chart_type": "histogram",
        "dataset_id": str(i["dataset_id"]),
        "spec": {"column": "x"},
    },
    "charts_update": lambda i: {"title": "t", "dataset_id": str(i["dataset_id"])},
    "dashboards_create": lambda i: {
        "name": f"walk-{uuid.uuid4().hex[:8]}",
        "tiles": [_tile(i["chart_id"])],
    },
    "dashboards_update": lambda i: {"tiles": [_tile(i["chart_id"])]},
    "assistant_messages": lambda i: {"message": "walk"},  # 3.7 (SSE; no ids to forge)
    "reports_create": lambda i: {
        "title": "walk",
        "format": "html",
        "dataset_id": str(i["dataset_id"]),
    },
    **{
        f"stage_{stage}_run": (
            lambda i, stage=stage: {  # type: ignore[misc]
                "operation": STAGE_RUN[stage][0],
                "dataset_id": str(i["dataset_id"]),
                "parameters": STAGE_RUN[stage][1],
            }
        )
        for stage in STAGE_RUN
    },
}
MULTIPART = {"datasets_upload"}


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    schema = api.get_openapi_schema()
    return [
        (method.upper(), path, op)
        for path, item in schema["paths"].items()
        for method, op in item.items()
    ]


def _params(path: str) -> list[str]:
    return [p[1:-1] for p in path.split("/") if p.startswith("{")]


@pytest.fixture
def worlds() -> tuple[World, dict[str, Any], dict[str, Any]]:
    world = make_world()
    org, project = world.org, world.project
    # Names unique to A, so "A's data appeared in a response" is a substring check, not a guess.
    Project.objects.filter(pk=project.pk).update(name="A-SECRET-PROJECT")
    DatasetRecord.objects.filter(pk=world.dataset.pk).update(
        name="A-SECRET-DATASET.csv"
    )
    project.name, world.dataset.name = "A-SECRET-PROJECT", "A-SECRET-DATASET.csv"
    chart = ChartSpec.objects.create(
        organization=org,
        project=project,
        dataset=world.dataset,
        chart_type="histogram",
        title="A-SECRET-CHART",
        spec={"column": "id"},
    )
    board = Dashboard.objects.create(
        organization=org,
        project=project,
        name="A-SECRET-BOARD",
        layout={"tiles": [{"chart_id": str(chart.pk), "row": 0, "column": 0}]},
    )
    job = factory_for(Job).create(org, project=project)
    report = Report.objects.create(
        organization=org,
        project=project,
        title="A-SECRET-REPORT",
        format="html",
        config={"dataset_id": str(world.dataset.pk)},
    )
    recipe = factory_for(Recipe).create(org, project=project, name="A-SECRET-RECIPE")
    factory_for(PipelineEdge).create(org, project=project)  # two nodes and an edge of A
    a_ids: dict[str, Any] = {
        "org_id": org.pk,
        "project_id": project.pk,
        "dataset_id": world.dataset.pk,
        "chart_id": chart.pk,
        "dashboard_id": board.pk,
        "job_id": job.pk,
        "report_id": report.pk,
        "recipe_id": recipe.pk,
        "membership_id": world.viewer.pk,
    }
    other, other_project = world.other_org, world.other_project
    b_dataset = store_dataset(other, other_project, _frame())
    b_chart = ChartSpec.objects.create(
        organization=other,
        project=other_project,
        dataset=b_dataset,
        chart_type="histogram",
        title="B-own",
        spec={"column": "id"},
    )
    b_board = Dashboard.objects.create(
        organization=other, project=other_project, name="B-own"
    )
    b_job = factory_for(Job).create(other, project=other_project)
    b_report = Report.objects.create(
        organization=other,
        project=other_project,
        title="B-own",
        format="html",
        config={"dataset_id": str(b_dataset.pk)},
    )
    b_recipe = factory_for(Recipe).create(other, project=other_project, name="B-own")
    b_ids: dict[str, Any] = {
        "org_id": other.pk,
        "project_id": other_project.pk,
        "dataset_id": b_dataset.pk,
        "chart_id": b_chart.pk,
        "dashboard_id": b_board.pk,
        "job_id": b_job.pk,
        "report_id": b_report.pk,
        "recipe_id": b_recipe.pk,
        "membership_id": world.other_owner.pk,
    }
    return world, a_ids, b_ids


def _frame() -> Any:
    import pandas as pd  # type: ignore[import-untyped]

    return pd.DataFrame(
        {
            "g": ["a", "b"] * 6,
            "x": [float(i) for i in range(12)],
            "id": list(range(12)),
        }
    )


def _markers(world: World, a_ids: dict[str, Any]) -> list[str]:
    found = {str(v) for v in a_ids.values()}
    found |= {
        m.user.email for m in (world.owner, world.admin, world.editor, world.viewer)
    }
    found |= {"A-SECRET-CHART", "A-SECRET-BOARD", "A-SECRET-REPORT", "A-SECRET-RECIPE"}
    found |= {world.org.slug, world.project.name, world.dataset.name}
    return sorted(found)


def _snapshot(world: World) -> tuple[dict[str, int], set[str]]:
    counts = {
        model._meta.label: model.objects.for_organization(world.org).count()
        for model in iter_tenant_models()
    }
    keys = {o.key for o in get_store(world.org).list_prefix(f"{world.org.pk}/")}
    return counts, keys


def _call(client: Any, method: str, path: str, body: dict[str, Any] | None) -> Any:
    return client.request(method, path, body)


def _fill(path: str, ids: dict[str, Any]) -> str:
    out = path
    for name in _params(path):
        out = out.replace("{" + name + "}", str(ids[name]))
    return out


def _no_leak(response: Any, markers: list[str], where: str) -> None:
    text = response.content.decode("utf-8", errors="replace")
    for marker in markers:
        assert marker not in text, f"{where}: response leaked {marker!r}"


# ------------------------------------------------------------------------ discovery


def test_the_walk_classifies_every_operation_and_every_parameter() -> None:
    operations = _operations()
    assert len(operations) >= 58  # discovery found the whole schema (guards the guard)
    seen_bodies: set[str] = set()
    for method, path, op in operations:
        names = _params(path)
        operation_id = op["operationId"]
        if "org_id" not in names:
            assert operation_id in ORG_AGNOSTIC, (
                f"{method} {path} names no organization: either it is org-agnostic "
                "(add it to ORG_AGNOSTIC deliberately) or it is a tenancy bug"
            )
        unknown = set(names) - RESOURCE_PARAMS - CONTAINER_PARAMS
        assert not unknown, f"{operation_id}: the IDOR walk cannot fill {unknown}"
        if "requestBody" in op:
            assert (
                operation_id in BODIES or operation_id in MULTIPART
            ), f"{operation_id} has a request body: add a builder to BODIES in {__file__}"
            seen_bodies.add(operation_id)
    # Every builder is for a real operation (a renamed route cannot leave a dead entry).
    assert set(BODIES) <= seen_bodies
    stages_with_run = {s.value for s in PipelineStage if STAGE_OPERATIONS[s]}
    assert set(STAGE_RUN) == stages_with_run


def test_the_leak_detector_would_notice_a_leak() -> None:
    class Leaky:
        content = b'{"items": [{"name": "A-SECRET-CHART"}]}'

    with pytest.raises(AssertionError, match="leaked"):
        _no_leak(Leaky(), ["A-SECRET-CHART"], "self-test")
    _no_leak(Leaky(), ["B-own"], "self-test")  # the twin: no marker, no failure


# ------------------------------------------------------------------------ the walk


def test_foreign_organization_and_foreign_ids_never_reach_organization_a_data(
    worlds: tuple[World, dict[str, Any], dict[str, Any]],
) -> None:
    world, a_ids, b_ids = worlds
    attacker = world.api("other")
    markers = _markers(world, a_ids)
    before = _snapshot(world)
    walked = 0
    for method, path, op in _operations():
        operation_id = op["operationId"]
        names = _params(path)
        body = BODIES[operation_id](a_ids) if operation_id in BODIES else None

        if operation_id in ORG_AGNOSTIC:
            response = _call(attacker, method, path, body)
            _no_leak(response, markers, f"{operation_id} (agnostic)")
            walked += 1
            continue

        # 1. foreign organization in the path (all of A's ids)
        if operation_id in MULTIPART:
            response = attacker.client.post(
                _fill(path, a_ids),
                {
                    "file": SimpleUploadedFile(
                        "x.csv", b"a,b\n1,2\n", content_type="text/csv"
                    )
                },
                headers={"X-CSRFToken": attacker.token},
            )
        else:
            response = _call(attacker, method, _fill(path, a_ids), body)
        assert response.status_code == 404, f"{operation_id}: {response.status_code}"
        assert response.json()["error"]["code"] == "not_found"
        _no_leak(response, markers, f"{operation_id} (foreign org)")

        # 2. own organization and project, foreign resource ids
        mixed = {**a_ids, "org_id": b_ids["org_id"], "project_id": b_ids["project_id"]}
        if operation_id in MULTIPART:
            response = attacker.client.post(
                _fill(path, mixed),
                {
                    "file": SimpleUploadedFile(
                        "x.csv", b"a,b\n1,2\n", content_type="text/csv"
                    )
                },
                headers={"X-CSRFToken": attacker.token},
            )
        else:
            response = _call(attacker, method, _fill(path, mixed), body)
        names_a_resource = bool(set(names) & RESOURCE_PARAMS)
        if names_a_resource:
            assert (
                response.status_code == 404
            ), f"{operation_id}: {response.status_code}"
        _no_leak(response, markers, f"{operation_id} (own org, foreign ids)")

        # 2b. own organization in the path but A's *project* (and A's resource ids, in the path,
        # the body and the query string): the project scope alone must make every such operation a
        # 404 -- including list routes that name no resource. (Found by review: a project lookup
        # that forgot ``for_organization`` passed attack 2 because B's own project was used there.)
        if "project_id" in names:
            foreign_project = {**a_ids, "org_id": b_ids["org_id"]}
            url = (
                _fill(path, foreign_project)
                + "?"
                + urlencode({k: str(v) for k, v in a_ids.items() if k not in names})
            )
            if operation_id in MULTIPART:
                response = attacker.client.post(
                    url,
                    {
                        "file": SimpleUploadedFile(
                            "x.csv", b"a,b\n1,2\n", content_type="text/csv"
                        )
                    },
                    headers={"X-CSRFToken": attacker.token},
                )
            else:
                response = _call(attacker, method, url, body)
            assert (
                response.status_code == 404
            ), f"{operation_id} (own org, A's project): {response.status_code}"
            _no_leak(response, markers, f"{operation_id} (own org, A's project)")
        walked += 1
    assert walked == len(_operations())
    assert (
        _snapshot(world) == before
    )  # A's rows and A's objects are exactly as they were


def test_foreign_ids_inside_request_bodies_are_refused_and_the_twin_is_accepted(
    worlds: tuple[World, dict[str, Any], dict[str, Any]],
) -> None:
    world, a_ids, b_ids = worlds
    attacker = world.api("other")
    markers = _markers(world, a_ids)
    before = _snapshot(world)
    twins = 0
    for method, path, op in _operations():
        operation_id = op["operationId"]
        if operation_id not in BODIES or operation_id in ORG_AGNOSTIC:
            continue
        own_body, foreign_body = BODIES[operation_id](b_ids), BODIES[operation_id](
            a_ids
        )
        if own_body == foreign_body or (
            "dataset_id" not in json.dumps(own_body)
            and ("chart_id" not in json.dumps(own_body))
        ):
            continue  # the body carries no id: nothing to forge
        url = _fill(path, b_ids)  # B's own path (own org, project, resources)
        refused = _call(attacker, method, url, foreign_body)
        assert refused.status_code in {
            404,
            422,
        }, f"{operation_id}: {refused.status_code}"
        _no_leak(refused, markers, f"{operation_id} (foreign body ids)")
        accepted = _call(attacker, method, url, own_body)
        assert accepted.status_code in {200, 201, 202}, (
            f"{operation_id}: the twin with B's own ids was refused ({accepted.status_code}); "
            "the refusal above would be vacuous"
        )
        twins += 1
    assert twins >= 10  # charts x2, dashboards x2, reports, six stage runs
    assert _snapshot(world) == before
    assert not DatasetRecord.objects.filter(
        organization=world.other_org, pk=a_ids["dataset_id"]
    ).exists()
