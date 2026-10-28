# File: apps/api/tests/test_web_resources.py
"""The 3.6 resource routes: projects, datasets (paged preview, summary, delete), charts, dashboards,
reports and jobs -- roles, scoping, limits and the error envelope.

Every refusal has a positive twin on the same fixtures (observation 0033): a route that refused
everyone would satisfy every "is refused" assertion. Roles are the 3.3 matrix (viewer reads, editor
writes, admin manages); a non-member and a foreign id are both ``404``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pytest
from web_support import SAMPLE, World, error_code, make_world, store_dataset

from uadas_api.exports.models import Report
from uadas_api.jobs.execution import execute_job
from uadas_api.jobs.models import Job
from uadas_api.storage.models import OrphanedObject
from uadas_api.workspaces.models import ChartSpec, Dashboard, DatasetRecord, Project

pytestmark = pytest.mark.django_db


@pytest.fixture
def world() -> World:
    return make_world()


# ------------------------------------------------------------------------- projects


def test_projects_are_listed_created_renamed_and_deleted_by_role(world: World) -> None:
    base = f"/api/organizations/{world.org.pk}/projects"
    listed = world.api("viewer").get(base)
    assert listed.status_code == 200
    body = listed.json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert [p["name"] for p in body["items"]] == ["Main"]

    assert world.api("viewer").post(base, {"name": "X"}).status_code == 403
    created = world.api("editor").post(base, {"name": "Second"})
    assert created.status_code == 201
    new_id = created.json()["id"]

    assert world.api("editor").post(base, {"name": "Second"}).status_code == 409
    assert error_code(world.api("editor").post(base, {"name": "Second"})) == "conflict"
    assert world.api("editor").post(base, {"name": "  "}).status_code == 422

    renamed = world.api("editor").patch(f"{base}/{new_id}", {"name": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"

    assert (
        world.api("editor").delete(f"{base}/{new_id}").status_code == 403
    )  # admin only
    assert world.api("admin").delete(f"{base}/{new_id}").status_code == 204
    assert world.api("viewer").get(f"{base}/{new_id}").status_code == 404


def test_a_project_with_datasets_cannot_be_deleted(world: World) -> None:
    url = f"/api/organizations/{world.org.pk}/projects/{world.project.pk}"
    refused = world.api("admin").delete(url)
    assert refused.status_code == 409 and error_code(refused) == "conflict"
    assert Project.objects.filter(pk=world.project.pk).exists()


def test_the_envelope_for_non_members_csrf_and_bad_ids(world: World) -> None:
    url = f"/api/organizations/{world.org.pk}/projects"
    assert world.api("outsider").get(url).status_code == 404
    assert error_code(world.api("outsider").get(url)) == "not_found"
    assert world.api("editor").post(url, {"name": "n"}, csrf=False).status_code == 403
    bad = world.api("viewer").get(f"{url}/not-a-uuid")
    assert bad.status_code == 422 and error_code(bad) == "invalid_request"
    detail = bad.json()["error"]["details"][0]
    assert set(detail) == {"loc", "type"}  # never the offending value


def test_list_endpoints_cap_the_page_size(world: World) -> None:
    url = f"/api/organizations/{world.org.pk}/projects"
    assert world.api("viewer").get(f"{url}?limit=200").status_code == 200
    assert world.api("viewer").get(f"{url}?limit=201").status_code == 422
    assert world.api("viewer").get(f"{url}?limit=0").status_code == 422
    assert world.api("viewer").get(f"{url}?offset=-1").status_code == 422


# ------------------------------------------------------------------------- datasets


def test_datasets_list_detail_and_foreign_project_ids(world: World) -> None:
    base = world.base()
    listed = world.api("viewer").get(f"{base}/datasets").json()
    assert [d["id"] for d in listed["items"]] == [str(world.dataset.pk)]
    detail = world.api("viewer").get(f"{base}/datasets/{world.dataset.pk}")
    assert detail.status_code == 200 and detail.json()["row_count"] == 10

    second = Project.objects.create(organization=world.org, name="Second")
    # The dataset exists in this organization but not in the *path's* project: 404.
    wrong = world.api("viewer").get(
        f"{world.base(project=second)}/datasets/{world.dataset.pk}"
    )
    assert wrong.status_code == 404


def test_deleting_a_dataset_queues_its_stored_objects(world: World) -> None:
    url = f"{world.base()}/datasets/{world.dataset.pk}"
    assert world.api("viewer").delete(url).status_code == 403
    assert DatasetRecord.objects.filter(pk=world.dataset.pk).exists()
    assert world.api("editor").delete(url).status_code == 204
    assert not DatasetRecord.objects.filter(pk=world.dataset.pk).exists()
    queued = OrphanedObject.objects.filter(organization=world.org, is_prefix=True)
    assert [o.storage_key for o in queued] == [
        f"{world.org.pk}/datasets/{world.dataset.pk}"
    ]


def _preview(world: World, dataset: DatasetRecord, query: str = "") -> Any:
    return world.api("viewer").get(
        f"{world.base()}/datasets/{dataset.pk}/preview{query}"
    )


def test_preview_formats_cells_with_the_core_formatters(world: World) -> None:
    body = _preview(world, world.dataset, "?limit=3").json()
    assert [c["name"] for c in body["columns"]] == ["id", "group", "value", "label"]
    assert body["total_rows"] == 10 and body["limit"] == 3 and body["offset"] == 0
    assert body["rows"][0] == ["1", "a", "1.5", "row 1"]
    assert body["rows"][1][2] == "—"  # a missing cell is the core's em dash


def test_preview_pages_and_sorts_across_row_groups(world: World) -> None:
    frame = pd.DataFrame(
        {"n": list(range(30)), "s": [f"v{(i * 7) % 30:02d}" for i in range(30)]}
    )
    frame.loc[3, "n"] = None
    dataset = store_dataset(world.org, world.project, frame, row_group_size=7)
    page = _preview(world, dataset, "?offset=5&limit=4").json()
    assert [r[0] for r in page["rows"]] == ["5", "6", "7", "8"]  # crosses a group edge
    tail = _preview(world, dataset, "?offset=28&limit=10").json()
    assert [r[0] for r in tail["rows"]] == ["28", "29"]
    assert _preview(world, dataset, "?offset=500").json()["rows"] == []

    asc = _preview(world, dataset, "?sort=s&limit=3").json()
    assert [r[1] for r in asc["rows"]] == ["v00", "v01", "v02"]
    desc = _preview(world, dataset, "?sort=s&descending=true&limit=2").json()
    assert [r[1] for r in desc["rows"]] == ["v29", "v28"]
    assert desc["sort"] == "s" and desc["descending"] is True
    # nulls last in either direction
    by_n = _preview(world, dataset, "?sort=n&descending=true&limit=30").json()
    assert by_n["rows"][-1][0] == "—"


def test_preview_validates_the_sort_column_and_caps_the_page(world: World) -> None:
    assert _preview(world, world.dataset, "?sort=value").status_code == 200
    unknown = _preview(world, world.dataset, "?sort=nope")
    assert unknown.status_code == 422 and error_code(unknown) == "invalid_request"
    assert _preview(world, world.dataset, "?sort=value;drop").status_code == 422
    assert _preview(world, world.dataset, "?limit=200").status_code == 200
    assert _preview(world, world.dataset, "?limit=201").status_code == 422


def test_preview_and_summary_are_throttled_per_user_and_organization(
    world: World, settings: Any
) -> None:
    """Each call copies and hashes the whole Parquet object, so both share a bounded ``preview`` budget."""
    settings.UADAS_API = {"throttles": {"preview": "3/60"}}
    viewer = world.api("viewer")
    assert _preview(world, world.dataset).status_code == 200
    assert (
        viewer.get(f"{world.base()}/datasets/{world.dataset.pk}/summary").status_code
        == 200
    )
    assert _preview(world, world.dataset).status_code == 200
    limited = _preview(world, world.dataset)
    assert limited.status_code == 429 and error_code(limited) == "rate_limited"
    summary = viewer.get(f"{world.base()}/datasets/{world.dataset.pk}/summary")
    assert summary.status_code == 429  # one shared budget
    assert (
        world.api("admin")
        .get(f"{world.base()}/datasets/{world.dataset.pk}/summary")
        .status_code
        == 200
    )  # another user's budget
    assert (
        world.api("viewer").get(f"{world.base()}/datasets").status_code == 200
    )  # lists are not metered


def test_summary_reads_the_footer_statistics(world: World) -> None:
    body = (
        world.api("viewer")
        .get(f"{world.base()}/datasets/{world.dataset.pk}/summary")
        .json()
    )
    assert body["row_count"] == 10 and body["column_count"] == 4
    value = next(c for c in body["columns"] if c["name"] == "value")
    assert value["null_count"] == 1 and value["min"] == "1.5" and value["max"] == "10.0"


# --------------------------------------------------------------------------- charts


def _chart(world: World, **over: Any) -> dict[str, Any]:
    body = {
        "chart_type": "scatter",
        "title": "Value by id",
        "dataset_id": str(world.dataset.pk),
        "spec": {"x_column": "id", "y_column": "value"},
    }
    return {**body, **over}


def test_charts_are_validated_against_the_registry_and_the_project(
    world: World,
) -> None:
    url = f"{world.base()}/charts"
    assert world.api("viewer").post(url, _chart(world)).status_code == 403
    created = world.api("editor").post(url, _chart(world))
    assert created.status_code == 201 and created.json()["dataset_id"] == str(
        world.dataset.pk
    )

    for bad in (
        _chart(world, chart_type="nope"),
        _chart(world, spec={"x_column": "id"}),  # y_column is required
        _chart(world, spec={"x_column": "id", "y_column": "value", "evil": "x"}),
        _chart(world, spec={"x_column": ["id"], "y_column": "value"}),  # wrong shape
    ):
        refused = world.api("editor").post(url, bad)
        assert refused.status_code == 422, bad

    second = Project.objects.create(organization=world.org, name="Second")
    foreign = store_dataset(world.org, second, SAMPLE)
    assert (
        world.api("editor")
        .post(url, _chart(world, dataset_id=str(foreign.pk)))
        .status_code
        == 404
    )  # a dataset of another project, same organization


def test_a_stacked_bar_spec_may_carry_its_literal_field(world: World) -> None:
    """``incomplete_from`` is a value, not a column, so it is allowed through ``literal_fields``."""
    url = f"{world.base()}/charts"
    spec = {
        "category_column": "id",
        "series_column": "value",
        "incomplete_from": "3",
    }
    created = world.api("editor").post(url, _chart(world, chart_type="bar", spec=spec))
    assert created.status_code == 201
    assert created.json()["spec"]["incomplete_from"] == "3"
    refused = world.api("editor").post(
        url, _chart(world, chart_type="bar", spec={**spec, "evil": "x"})
    )
    assert refused.status_code == 422


def test_patches_write_only_the_fields_they_change(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PATCH that wrote every column would clobber a concurrent PATCH of another field."""
    saved: list[tuple[str, Any]] = []
    for model in (ChartSpec, Dashboard):
        original = model.save

        def spy(self: Any, *args: Any, _o: Any = original, **kwargs: Any) -> None:
            saved.append((type(self).__name__, kwargs.get("update_fields")))
            _o(self, *args, **kwargs)

        monkeypatch.setattr(model, "save", spy)
    charts = f"{world.base()}/charts"
    chart_id = world.api("editor").post(charts, _chart(world)).json()["id"]
    boards = f"{world.base()}/dashboards"
    board_id = world.api("editor").post(boards, {"name": "B", "tiles": []}).json()["id"]
    saved.clear()

    assert (
        world.api("editor").patch(f"{charts}/{chart_id}", {"title": "New"}).status_code
        == 200
    )
    assert (
        world.api("editor")
        .patch(f"{boards}/{board_id}", {"name": "Renamed"})
        .status_code
        == 200
    )
    assert saved == [("ChartSpec", ["title"]), ("Dashboard", ["name"])]
    both = world.api("editor").patch(
        f"{charts}/{chart_id}",
        {"title": "T2", "spec": {"x_column": "id", "y_column": "value"}},
    )
    assert both.status_code == 200 and saved[-1] == (
        "ChartSpec",
        ["title", "spec"],
    )  # the twin
    assert world.api("viewer").get(f"{charts}/{chart_id}").json()["title"] == "T2"


def test_chart_render_builds_the_figure_from_a_bounded_sample(
    world: World, settings: Any
) -> None:
    url = f"{world.base()}/charts"
    chart_id = world.api("editor").post(url, _chart(world)).json()["id"]
    rendered = world.api("viewer").post(f"{url}/{chart_id}/render")
    assert rendered.status_code == 200
    body = rendered.json()
    assert (
        body["rows_used"] == 10
        and body["rows_total"] == 10
        and body["sampled"] is False
    )
    assert (
        body["figure"]["data"]
        and body["figure"]["layout"]["title"]["text"] == "Value by id"
    )

    settings.UADAS_API = {"render_max_rows": 4}
    sampled = world.api("viewer").post(f"{url}/{chart_id}/render").json()
    assert sampled["rows_used"] == 4 and sampled["sampled"] is True

    unbound = world.api("editor").post(url, _chart(world, dataset_id=None)).json()["id"]
    refused = world.api("viewer").post(f"{url}/{unbound}/render")
    assert refused.status_code == 409 and error_code(refused) == "conflict"


def test_chart_render_is_throttled_per_user_and_organization(
    world: World, settings: Any
) -> None:
    settings.UADAS_API = {"throttles": {"render": "2/60"}}
    url = f"{world.base()}/charts"
    chart_id = world.api("editor").post(url, _chart(world)).json()["id"]
    render = f"{url}/{chart_id}/render"
    assert world.api("viewer").post(render).status_code == 200
    assert world.api("viewer").post(render).status_code == 200
    limited = world.api("viewer").post(render)
    assert limited.status_code == 429 and error_code(limited) == "rate_limited"
    assert world.api("admin").post(render).status_code == 200  # another user's budget


# ----------------------------------------------------------------------- dashboards


def test_dashboards_resolve_tiles_inside_the_project(world: World) -> None:
    charts = f"{world.base()}/charts"
    chart_id = world.api("editor").post(charts, _chart(world)).json()["id"]
    url = f"{world.base()}/dashboards"
    tile = {"chart_id": chart_id, "row": 0, "column": 0}
    created = world.api("editor").post(url, {"name": "Board", "tiles": [tile]})
    assert created.status_code == 201
    assert created.json()["tiles"][0]["chart_exists"] is True
    board_id = created.json()["id"]

    assert (
        world.api("viewer").post(url, {"name": "B2", "tiles": [tile]}).status_code
        == 403
    )
    ghost = {**tile, "chart_id": "00000000-0000-4000-8000-000000000000"}
    assert (
        world.api("editor").post(url, {"name": "B3", "tiles": [ghost]}).status_code
        == 422
    )
    other_chart = (
        world.api("other")
        .post(
            f"{world.other_base}/charts",
            {"chart_type": "histogram", "spec": {"column": "x"}},
        )
        .json()["id"]
    )
    foreign = {**tile, "chart_id": other_chart}
    assert (
        world.api("editor").post(url, {"name": "B4", "tiles": [foreign]}).status_code
        == 422
    )

    assert world.api("editor").delete(f"{charts}/{chart_id}").status_code == 204
    after = world.api("viewer").get(f"{url}/{board_id}").json()
    assert (
        after["tiles"][0]["chart_exists"] is False
    )  # an orphaned tile is normal state


def test_the_dashboards_list_resolves_every_tile_in_one_query(
    world: World, django_assert_max_num_queries: Any
) -> None:
    """The list must not be an N+1: tile chart ids are resolved for the whole page at once."""
    charts = f"{world.base()}/charts"
    chart_id = world.api("editor").post(charts, _chart(world)).json()["id"]
    url = f"{world.base()}/dashboards"
    tile = {"chart_id": chart_id, "row": 0, "column": 0}
    for n in range(12):
        assert (
            world.api("editor")
            .post(url, {"name": f"B{n}", "tiles": [tile]})
            .status_code
            == 201
        )
    client = world.api("viewer")
    client.get(url)  # warm the session / CSRF cookie so only the list itself is counted
    with django_assert_max_num_queries(
        9
    ):  # session, user, membership, project, count, page, charts
        listed = client.get(url).json()
    assert listed["total"] == 12
    assert all(d["tiles"][0]["chart_exists"] for d in listed["items"])


# ------------------------------------------------------------------ reports and jobs


def _request_report(world: World, fmt: str = "html") -> Any:
    return world.api("editor").post(
        f"{world.base()}/reports",
        {"title": "Quarterly", "format": fmt, "dataset_id": str(world.dataset.pk)},
    )


def test_a_report_is_requested_built_by_its_job_and_downloaded(world: World) -> None:
    assert (
        world.api("viewer")
        .post(
            f"{world.base()}/reports",
            {"title": "T", "format": "html", "dataset_id": str(world.dataset.pk)},
        )
        .status_code
        == 403
    )
    accepted = _request_report(world)
    assert accepted.status_code == 202
    report_id, job_id = accepted.json()["report"]["id"], accepted.json()["job_id"]
    assert accepted.json()["report"]["status"] == "pending"
    download = f"{world.base()}/reports/{report_id}/download"
    assert world.api("viewer").get(download).status_code == 409  # not ready yet

    execute_job(job_id)
    report = Report.objects.get(pk=report_id)
    assert report.status == "ready" and report.storage_key.startswith(
        f"{world.org.pk}/exports/"
    )
    ready = world.api("viewer").get(download)
    assert ready.status_code == 200
    assert (
        ready.json()["expires_in_seconds"] == 60
        and ready.json()["filename"] == "Quarterly.html"
    )
    assert (
        world.api("viewer").get(f"{world.base()}/jobs/{job_id}").json()["report_id"]
        == report_id
    )

    assert (
        world.api("editor").delete(f"{world.base()}/reports/{report_id}").status_code
        == 204
    )
    assert OrphanedObject.objects.filter(storage_key=report.storage_key).exists()


def test_a_report_title_that_a_spreadsheet_would_read_as_a_formula_is_refused(
    world: World,
) -> None:
    url = f"{world.base()}/reports"
    for title in (
        '=HYPERLINK("http://evil.example")',
        "+1+1",
        "-2+3",
        "@SUM(1)",
        "\t=1",
    ):
        refused = world.api("editor").post(
            url, {"title": title, "format": "xlsx", "dataset_id": str(world.dataset.pk)}
        )
        assert refused.status_code == 422, title
    assert not Report.objects.filter(project=world.project).exists()
    ok = world.api("editor").post(
        url,
        {"title": "Q3 = good", "format": "xlsx", "dataset_id": str(world.dataset.pk)},
    )
    assert ok.status_code == 202  # the twin: an inner "=" is fine


def test_a_report_of_a_dataset_outside_the_project_is_refused(world: World) -> None:
    second = Project.objects.create(organization=world.org, name="Second")
    foreign = store_dataset(world.org, second, SAMPLE)
    refused = world.api("editor").post(
        f"{world.base()}/reports",
        {"title": "T", "format": "html", "dataset_id": str(foreign.pk)},
    )
    assert refused.status_code == 404
    assert not Report.objects.filter(project=world.project).exists()


def test_the_jobs_list_never_loads_the_result_column(
    world: World, django_assert_max_num_queries: Any
) -> None:
    """A stage result is up to 4 MiB of JSON on the job row; a page of 200 jobs must not read it."""
    import re

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    job_ids = [_request_report(world).json()["job_id"] for _ in range(3)]
    Job.objects.filter(pk=job_ids[0]).update(result={"blob": "x" * 200_000})
    execute_job(
        job_ids[1]
    )  # a finished job: its result names the report (the list must still show it)
    with CaptureQueriesContext(connection) as queries:
        listed = world.api("viewer").get(f"{world.base()}/jobs").json()
    selects = [
        q["sql"]
        for q in queries
        if '"exports_report"' not in q["sql"] and 'FROM "jobs_job"' in q["sql"]
    ]
    assert selects, "the list ran no query on the jobs table?"
    for sql in selects:
        # the JSON key extractions that feed ``report_id`` / ``dataset_id`` are fine; the column itself is not
        # (a bare select-list column is followed by another column, an expression or FROM; a JSON
        # key extraction has the column followed by a quoted path or ``->>``)
        assert not re.search(r'"jobs_job"\."result"(?=,\s*["(]|\s+FROM)', sql), sql
    assert len(listed["items"]) == 3
    finished = next(j for j in listed["items"] if j["id"] == job_ids[1])
    assert finished["status"] == "succeeded" and finished["report_id"] is not None
    twin = world.api("viewer").get(f"{world.base()}/jobs/{job_ids[1]}").json()
    assert twin["report_id"] == finished["report_id"]  # the single-job read agrees


def test_jobs_are_listed_read_and_cancelled_inside_their_project(world: World) -> None:
    job_id = _request_report(world).json()["job_id"]
    base = f"{world.base()}/jobs"
    listed = world.api("viewer").get(base).json()
    assert [j["id"] for j in listed["items"]] == [job_id]
    one = world.api("viewer").get(f"{base}/{job_id}").json()
    assert (
        one["status"] == "queued"
        and one["progress"] == 0
        and one["kind"] == "build_report"
    )
    assert world.api("viewer").get(f"{base}?status=nope").status_code == 422
    assert world.api("viewer").get(f"{base}?status=queued").json()["total"] == 1
    assert world.api("viewer").get(f"{base}?status=failed").json()["total"] == 0

    assert world.api("viewer").post(f"{base}/{job_id}/cancel").status_code == 403
    cancelled = world.api("editor").post(f"{base}/{job_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    again = world.api("editor").post(f"{base}/{job_id}/cancel")
    assert again.status_code == 409
    assert Job.objects.get(pk=job_id).status == "cancelled"
    assert (
        Report.objects.get(project=world.project).status == "failed"
    )  # abandon hook ran

    other = world.api("other").get(f"{world.other_base}/jobs/{job_id}")
    assert other.status_code == 404  # a job of organization A, asked for in B's project
    # a stage result is only for run_operation jobs that succeeded
    assert world.api("viewer").get(f"{base}/{job_id}/stage-result").status_code == 404
