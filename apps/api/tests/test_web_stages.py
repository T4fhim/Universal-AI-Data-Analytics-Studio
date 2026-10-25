# File: apps/api/tests/test_web_stages.py
"""The per-stage routers: catalog parity with the core registry, validated runs, and the job pipeline.

Three layers of evidence. (1) *Parity*: the stage mapping, the catalog, the raw-result table and the
OpenAPI Literals are pinned to the live core in both directions, so a tool or stage added to the core
fails here instead of surfacing as a missing route. (2) *Validation*: a run is refused (``422`` /
``403`` / ``404`` / ``409``) before any job exists, each with a positive twin. (3) *End to end*:
a cleaning run produces a **derived** dataset (``parent_dataset_id`` + ``derivation_description``,
the source untouched) and provenance rows; analysis, exploration, forecasting and charting runs
return the Phase 1.5 result sections; a core failure ends in the closed code ``operation_failed``
with no dataset and no stored frame left behind.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, get_args

import pandas as pd  # type: ignore[import-untyped]
import pytest
from web_support import World, error_code, make_world, store_dataset

from uadas_api.exports.choices import ReportFormat
from uadas_api.jobs.errors import JobErrorCode
from uadas_api.jobs.execution import execute_job
from uadas_api.jobs.models import Job
from uadas_api.pipeline.models import PipelineEdge, PipelineNode
from uadas_api.stages import catalog
from uadas_api.stages.catalog import STAGE_OPERATIONS, OperationKind
from uadas_api.stages.execute import RAW_RUNNERS
from uadas_api.stages.serialize import EXPERTISE_NAMES, STAGE_NAMES
from uadas_api.storage.store import get_store
from uadas_api.web.errors import ErrorCode, ErrorCodeName
from uadas_api.web.reports import ReportFormatName
from uadas_api.web.stages import STAGE_ROUTERS
from uadas_api.workspaces.models import DatasetRecord, Project
from uadas_core.ai.tool_registry import TOOLS
from uadas_core.core.expertise_level import ExpertiseLevel
from uadas_core.services.analysis_orchestrator_service import PipelineStage

pytestmark = pytest.mark.django_db

N = 24
FRAME = pd.DataFrame(
    {
        "g": ["a", "b", "c"] * (N // 3),
        "h": ["x", "y"] * (N // 2),
        "x": [float(i) + (i % 5) * 0.37 for i in range(N)],
        "y": [float(i) * 2 + (i % 7) * 0.5 for i in range(N)],
        "t": pd.date_range("2024-01-01", periods=N, freq="D"),
        "missing": [None if i % 4 == 0 else float(i) for i in range(N)],
    }
)


@pytest.fixture
def world() -> World:
    return make_world(FRAME)


def _run(
    world: World, stage: str, operation: str, parameters: dict[str, Any], **extra: Any
) -> Any:
    body = {
        "operation": operation,
        "dataset_id": str(world.dataset.pk),
        "parameters": parameters,
        **extra,
    }
    return world.api("editor").post(f"{world.base()}/stages/{stage}/run", body)


def _finish(world: World, accepted: Any) -> dict[str, Any]:
    """Run the accepted job in-process and return its (polled) job resource."""
    assert accepted.status_code == 202, accepted.content
    job_id = accepted.json()["job_id"]
    execute_job(job_id)
    return world.api("viewer").get(f"{world.base()}/jobs/{job_id}").json()


def _result(world: World, job: dict[str, Any]) -> dict[str, Any]:
    response = world.api("viewer").get(f"{world.base()}/jobs/{job['id']}/stage-result")
    assert response.status_code == 200, response.content
    return response.json()


# ---------------------------------------------------------------------- parity pins


def test_there_is_one_router_per_pipeline_stage_and_its_tag_is_the_stage() -> None:
    assert set(STAGE_ROUTERS) == set(PipelineStage)
    assert len(PipelineStage) == 10
    for stage, router in STAGE_ROUTERS.items():
        assert router.tags == [stage.value]


def test_every_registered_tool_belongs_to_exactly_one_stage_and_every_name_is_a_tool() -> (
    None
):
    registered = {tool.name for tool in TOOLS}
    mapped = [name for names in STAGE_OPERATIONS.values() for name in names]
    assert sorted(mapped) == sorted(
        set(mapped)
    ), "an operation is listed under two stages"
    assert set(mapped) == registered
    assert set(STAGE_OPERATIONS) == set(PipelineStage)


def test_raw_runners_cover_exactly_the_result_operations() -> None:
    result_ops = {
        op.name
        for stage in PipelineStage
        for op in catalog.operations(stage)
        if op.kind is OperationKind.RESULT
    }
    assert set(RAW_RUNNERS) == result_ops


def test_the_openapi_literals_follow_the_core_and_the_error_codes() -> None:
    assert set(get_args(STAGE_NAMES)) == {s.value for s in PipelineStage}
    assert set(get_args(EXPERTISE_NAMES)) == {e.value for e in ExpertiseLevel}
    assert set(get_args(ReportFormatName)) == set(ReportFormat.values)
    assert set(get_args(ErrorCodeName)) == {c.value for c in ErrorCode}


def test_raw_runners_agree_with_the_tool_handlers() -> None:
    from uadas_api import core_bridge
    from uadas_core.ai.tool_registry import get_tool_by_name
    from uadas_core.models import Dataset

    core_bridge.get_process_context()
    dataset = Dataset(name="d", dataframe=FRAME.copy(), source_format="csv")
    profile = RAW_RUNNERS["profile_dataset"](dataset)
    handler = get_tool_by_name("profile_dataset").handler(dataset)
    assert profile.row_count == handler["row_count"] == N
    ttest = RAW_RUNNERS["independent_t_test"](dataset, "x", "h", "x", "y")
    via_tool = get_tool_by_name("independent_t_test").handler(
        dataset, "x", "h", "x", "y"
    )
    assert ttest.p_value == pytest.approx(via_tool["p_value"])


# ------------------------------------------------------------------------ catalogs


def test_catalogs_come_from_the_live_registry(world: World) -> None:
    base = f"{world.base()}/stages"
    analyze = world.api("viewer").get(f"{base}/analyze/catalog").json()
    assert analyze["stage"] == "analyze" and analyze["rationale"]
    names = [o["name"] for o in analyze["operations"]]
    assert names == list(STAGE_OPERATIONS[PipelineStage.ANALYZE])
    ttest = next(o for o in analyze["operations"] if o["name"] == "independent_t_test")
    assert ttest["parameters"]["additionalProperties"] is False
    assert (
        "value_column" in ttest["parameters"]["required"]
        and ttest["produces"] == "result"
    )

    clean = world.api("viewer").get(f"{base}/clean/catalog").json()
    assert {o["produces"] for o in clean["operations"]} == {"dataset"}
    chart = world.api("viewer").get(f"{base}/visualize/catalog").json()["operations"][0]
    enum = chart["parameters"]["properties"]["chart_type"]["enum"]
    assert "bar" in enum and enum == sorted(
        enum
    )  # the live chart registry, not the import-time []

    for empty in ("upload", "explain", "report", "reproduce"):
        assert (
            world.api("viewer").get(f"{base}/{empty}/catalog").json()["operations"]
            == []
        )
        assert world.api("editor").post(f"{base}/{empty}/run", {}).status_code == 404

    assert world.api("outsider").get(f"{base}/analyze/catalog").status_code == 404


# ----------------------------------------------------------------------- validation


def test_a_run_is_validated_before_any_job_exists(world: World) -> None:
    ok = {"column": "x"}
    assert (
        world.api("viewer")
        .post(
            f"{world.base()}/stages/analyze/run",
            {
                "operation": "check_normality",
                "dataset_id": str(world.dataset.pk),
                "parameters": ok,
            },
        )
        .status_code
        == 403
    )
    for stage, operation, parameters in (
        ("analyze", "drop_missing_values", {}),  # a clean operation asked of analyze
        ("analyze", "nope", {}),
        ("analyze", "check_normality", {}),  # required `column` missing
        ("analyze", "check_normality", {"column": "x", "evil": 1}),  # unknown parameter
        ("analyze", "check_normality", {"column": 5}),  # wrong type
        (
            "analyze",
            "check_normality",
            {"column": "x", "method": "nope"},
        ),  # not in the enum
    ):
        refused = _run(world, stage, operation, parameters)
        assert refused.status_code == 422, (operation, parameters)
        assert error_code(refused) == "invalid_request"
    assert not Job.objects.exists()
    # resource bounds on what one run may ask for (a worker would allocate 10**9 future dates)
    bound = {"date_column": "t", "value_column": "x"}
    for periods in (0, 1001, 10**9):
        assert (
            _run(
                world,
                "predict",
                "forecast_linear_regression",
                {**bound, "periods": periods},
            ).status_code
            == 422
        )
    assert (
        _run(
            world, "predict", "forecast_linear_regression", {**bound, "periods": 1000}
        ).status_code
        == 202
    )
    assert _run(world, "analyze", "check_normality", ok).status_code == 202  # the twin


def test_a_run_resolves_the_dataset_inside_the_organization_and_project(
    world: World,
) -> None:
    second = Project.objects.create(organization=world.org, name="Second")
    foreign_project = store_dataset(world.org, second, FRAME)
    other_org = store_dataset(world.other_org, world.other_project, FRAME)
    for dataset in (foreign_project, other_org, uuid.uuid4()):
        pk = getattr(dataset, "pk", dataset)
        refused = world.api("editor").post(
            f"{world.base()}/stages/analyze/run",
            {
                "operation": "check_normality",
                "dataset_id": str(pk),
                "parameters": {"column": "x"},
            },
        )
        assert refused.status_code == 404
    assert not Job.objects.exists()


def test_idempotency_keys_return_the_same_job_and_refuse_a_different_request(
    world: World,
) -> None:
    first = _run(
        world, "analyze", "check_normality", {"column": "x"}, idempotency_key="k1"
    )
    again = _run(
        world, "analyze", "check_normality", {"column": "x"}, idempotency_key="k1"
    )
    assert first.json()["job_id"] == again.json()["job_id"]
    clash = _run(
        world, "analyze", "check_normality", {"column": "y"}, idempotency_key="k1"
    )
    assert clash.status_code == 409 and error_code(clash) == "conflict"
    assert Job.objects.count() == 1


def test_a_stage_job_is_throttled(world: World, settings: Any) -> None:
    settings.UADAS_API = {"throttles": {"run": "1/60"}}
    assert _run(world, "analyze", "check_normality", {"column": "x"}).status_code == 202
    assert _run(world, "analyze", "check_normality", {"column": "x"}).status_code == 429


# ------------------------------------------------------------------------ end to end


def test_a_cleaning_run_derives_a_new_dataset_and_records_lineage(world: World) -> None:
    accepted = _run(world, "clean", "drop_missing_values", {"columns": ["missing"]})
    new_id = accepted.json()["dataset_id"]
    assert (
        new_id and not DatasetRecord.objects.filter(pk=new_id).exists()
    )  # not before the job
    job = _finish(world, accepted)
    assert job["status"] == "succeeded" and job["dataset_id"] == new_id

    derived = DatasetRecord.objects.get(pk=new_id)
    assert (
        derived.parent_dataset_id == world.dataset.pk
    )  # lineage, never an in-place edit
    assert derived.derivation_description
    assert derived.row_count == 18 and derived.project_id == world.project.pk
    world.dataset.refresh_from_db()
    assert world.dataset.row_count == N  # the source is untouched
    preview = (
        world.api("viewer")
        .get(f"{world.base()}/datasets/{new_id}/preview?limit=1")
        .json()
    )
    assert preview["total_rows"] == 18

    result = _result(world, job)
    assert result["kind"] == "dataset" and result["dataset_id"] == new_id
    assert result["parent_dataset_id"] == str(world.dataset.pk)
    assert result["sections"][0]["type"] == "key_value"

    nodes = list(PipelineNode.objects.filter(project=world.project))
    assert {n.kind for n in nodes} == {"dataset"} and len(nodes) == 2
    (edge,) = PipelineEdge.objects.filter(project=world.project)
    assert edge.kind == "transform" and edge.target.dataset_id == derived.pk
    listed = world.api("viewer").get(f"{world.base()}/pipeline/nodes").json()
    assert listed["total"] == 2
    assert (
        world.api("viewer").get(f"{world.base()}/pipeline/edges").json()["total"] == 1
    )


def test_a_failed_run_leaves_no_dataset_no_frame_and_a_closed_error_code(
    world: World,
) -> None:
    objects_before = {
        o.key for o in get_store(world.org).list_prefix(f"{world.org.pk}/")
    }
    accepted = _run(
        world, "clean", "drop_missing_values", {"columns": ["no_such_column"]}
    )
    job = _finish(world, accepted)
    assert (
        job["status"] == "failed"
        and job["error_code"] == JobErrorCode.OPERATION_FAILED.value
    )
    assert job["error_message"] == "The operation could not be applied to this dataset."
    assert "no_such_column" not in str(job)  # the core's text is never kept
    assert DatasetRecord.objects.filter(project=world.project).count() == 1
    assert not PipelineNode.objects.exists()
    assert {
        o.key for o in get_store(world.org).list_prefix(f"{world.org.pk}/")
    } == objects_before
    assert (
        world.api("viewer")
        .get(f"{world.base()}/jobs/{job['id']}/stage-result")
        .status_code
        == 409
    )


@pytest.mark.parametrize(
    ("stage", "operation", "parameters", "types"),
    [
        ("understand", "profile_dataset", {}, {"key_value", "table"}),
        ("explore", "aggregate", {"group_by": ["g"], "agg_column": "x"}, {"table"}),
        (
            "explore",
            "cross_tabulate",
            {"row_column": "g", "column_column": "h"},
            {"table"},
        ),
        ("analyze", "compute_correlation", {}, {"table"}),
        (
            "analyze",
            "independent_t_test",
            {"value_column": "x", "group_column": "h", "group_a": "x", "group_b": "y"},
            {"metric", "assumptions"},
        ),
        ("analyze", "check_normality", {"column": "x"}, {"metric", "assumptions"}),
        (
            "predict",
            "forecast_linear_regression",
            {"date_column": "t", "value_column": "x", "periods": 3},
            {"table"},
        ),
        (
            "visualize",
            "build_chart",
            {"chart_type": "scatter", "x_column": "x", "y_column": "y"},
            {"figure"},
        ),
    ],
)
def test_result_operations_return_the_section_model(
    world: World,
    stage: str,
    operation: str,
    parameters: dict[str, Any],
    types: set[str],
) -> None:
    job = _finish(
        world, _run(world, stage, operation, parameters, expertise_level="beginner")
    )
    assert job["status"] == "succeeded", job
    result = _result(world, job)
    assert result["stage"] == stage and result["operation"] == operation
    assert (
        result["title"]
        and result["headline"]
        and result["expertise_level"] == "beginner"
    )
    found = {s["type"] for s in result["sections"]}
    assert types <= found, found
    assert result["dataset_id"] is None
    if "figure" in types:
        figure = next(s for s in result["sections"] if s["type"] == "figure")["figure"]
        assert figure["data"]
    nodes = PipelineNode.objects.filter(project=world.project, kind="artifact")
    assert nodes.count() == 1 and nodes[0].payload["operation"] == operation
    assert (
        DatasetRecord.objects.filter(project=world.project).count() == 1
    )  # no dataset made


def test_a_cancelled_run_is_never_executed(world: World) -> None:
    accepted = _run(world, "analyze", "check_normality", {"column": "x"})
    job_id = accepted.json()["job_id"]
    assert (
        world.api("editor").post(f"{world.base()}/jobs/{job_id}/cancel").status_code
        == 200
    )
    execute_job(job_id)
    assert Job.objects.get(pk=job_id).status == "cancelled"
    assert not PipelineNode.objects.exists()


def test_the_stage_result_only_returns_ids_that_resolve_inside_the_project(
    world: World,
) -> None:
    from uadas_api.web.jobs import jobs_out

    foreign = store_dataset(world.other_org, world.other_project, FRAME)
    job = Job(
        organization=world.org,
        project=world.project,
        kind="ingest_dataset",
        idempotency_key="k",
        status="succeeded",
        created_at=datetime.now(UTC),  # unsaved, so auto_now_add has not run
        result={"dataset_id": str(foreign.pk)},
    )
    assert (
        jobs_out(world.project, [job])[0].dataset_id is None
    )  # B's id is never echoed
    job.result = {"dataset_id": str(world.dataset.pk)}
    assert jobs_out(world.project, [job])[0].dataset_id == world.dataset.pk  # the twin
