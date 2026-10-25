# File: apps/api/uadas_api/web/charts.py
"""Saved charts (``ChartSpec``): CRUD, and a bounded synchronous ``render``.

A chart is *a description*, never data: a registry chart name and its column parameters
(``spec``), optionally bound to a dataset. Both are validated against the core's live chart
registry when saved, so a spec that could never build is a ``422`` at save time, and the bound
dataset is resolved through ``for_organization`` *and* the path's project.

**Render is a bounded synchronous call, not a job** (the choice the plan asked us to state): it
streams at most ``ApiConfig.render_max_rows`` rows (5,000 by default -- below the core's
plotly-resampler threshold, so the figure is a plain ``go.Figure``) of only the columns the spec
names, builds the figure with the *unchanged* core chart class and returns ``figure.to_json()``
capped at ``render_max_figure_bytes``. That keeps a dashboard tile one round trip. A full-data chart
is the ``visualize`` stage's ``build_chart`` operation, which *is* a job. Render is throttled per
user and organization (``render`` scope).

Roles: viewer renders and reads; editor creates, edits and deletes.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Annotated, Any

from django.db import transaction
from django.http import HttpRequest
from ninja import Query, Router, Schema, Status
from pyarrow import ArrowException
from pydantic import Field, StringConstraints

from uadas_api import core_bridge
from uadas_api.accounts.models import Role
from uadas_api.stages import frames
from uadas_api.storage.errors import ObjectNotFoundError, StorageError
from uadas_api.storage.store import get_store
from uadas_api.web import throttle
from uadas_api.web.config import api_config
from uadas_api.web.errors import ApiError, not_found, responses
from uadas_api.web.pagination import Page, PageParams
from uadas_api.web.scope import in_project, member, project_of, scoped, user_of
from uadas_api.workspaces.models import ChartSpec, DatasetRecord, Project
from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.chart_registry import get_chart, list_charts

router = Router(tags=["charts"])
_BASE = "/organizations/{org_id}/projects/{project_id}/charts"

ChartTypeName = Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,32}$")]
ColumnName = Annotated[str, StringConstraints(min_length=1, max_length=255)]
SpecValue = ColumnName | Annotated[list[ColumnName], Field(max_length=20)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


class ChartIn(Schema):
    chart_type: ChartTypeName
    title: Title = ""
    dataset_id: uuid.UUID | None = None
    spec: dict[str, SpecValue] = Field(default_factory=dict)


class ChartPatch(Schema):
    title: Title | None = None
    dataset_id: uuid.UUID | None = None
    spec: dict[str, SpecValue] | None = None


class ChartOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID | None
    chart_type: str
    title: str
    spec: dict[str, Any]
    created_at: datetime.datetime


class ChartRenderOut(Schema):
    figure: dict[str, Any]
    rows_used: int
    rows_total: int
    sampled: bool


def _check_spec(chart_type: str, spec: dict[str, Any]) -> None:
    """The spec names only the registry's fields for ``chart_type`` and all the required ones."""
    core_bridge.get_process_context()  # seeds the chart registry
    if chart_type not in list_charts():
        raise ApiError(422, "Unknown chart type.")
    registration = get_chart(chart_type)
    allowed = set(registration.required_fields) | set(registration.optional_fields)
    if not set(spec) <= allowed:
        raise ApiError(422, "The chart parameters include an unknown field.")
    if not set(registration.required_fields) <= set(spec):
        raise ApiError(422, "The chart parameters are missing a required field.")
    for name, value in spec.items():
        if (name in registration.list_fields) != isinstance(value, list):
            raise ApiError(422, "A chart parameter has the wrong shape.")


def _dataset_in(project: Project, dataset_id: uuid.UUID | None) -> DatasetRecord | None:
    if dataset_id is None:
        return None
    return in_project(DatasetRecord, project, dataset_id)


def chart_out(project: Project, chart: ChartSpec, valid: set[uuid.UUID]) -> ChartOut:
    spec = chart.spec if isinstance(chart.spec, dict) else {}
    return ChartOut(
        id=chart.pk,
        project_id=chart.project_id,
        dataset_id=chart.dataset_id if chart.dataset_id in valid else None,
        chart_type=chart.chart_type,
        title=chart.title,
        spec={k: v for k, v in spec.items() if isinstance(v, str | list)},
        created_at=chart.created_at,
    )


def _valid_datasets(project: Project, charts: list[ChartSpec]) -> set[uuid.UUID]:
    wanted = {c.dataset_id for c in charts if c.dataset_id}
    return set(
        DatasetRecord.objects.for_organization(project.organization_id)
        .filter(project=project, pk__in=wanted)
        .values_list("pk", flat=True)
    )


def _one(project: Project, chart: ChartSpec) -> ChartOut:
    return chart_out(project, chart, _valid_datasets(project, [chart]))


@router.get(
    _BASE,
    response=responses({200: Page[ChartOut]}),
    summary="Saved charts of a project (viewer and above)",
    operation_id="charts_list",
)
def charts_list(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[PageParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(ChartSpec, project).order_by("created_at", "pk")
    rows = list(queryset[params.offset : params.offset + params.limit])
    valid = _valid_datasets(project, rows)
    return {
        "items": [chart_out(project, c, valid) for c in rows],
        "total": queryset.count(),
        "limit": params.limit,
        "offset": params.offset,
    }


@router.post(
    _BASE,
    response=responses({201: ChartOut}),
    summary="Save a chart (editor and above)",
    operation_id="charts_create",
)
def charts_create(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, payload: ChartIn
) -> Status[ChartOut]:
    membership = member(request, org_id, Role.EDITOR)
    project = project_of(membership, project_id)
    _check_spec(payload.chart_type, payload.spec)
    dataset = _dataset_in(project, payload.dataset_id)
    with transaction.atomic():
        chart = ChartSpec.objects.create(
            organization_id=project.organization_id,
            project=project,
            dataset=dataset,
            chart_type=payload.chart_type,
            title=payload.title,
            spec=payload.spec,
        )
    return Status(201, _one(project, chart))


@router.get(
    f"{_BASE}/{{chart_id}}",
    response=responses({200: ChartOut}),
    summary="One saved chart (viewer and above)",
    operation_id="charts_get",
)
def charts_get(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, chart_id: uuid.UUID
) -> ChartOut:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    return _one(project, in_project(ChartSpec, project, chart_id))


@router.patch(
    f"{_BASE}/{{chart_id}}",
    response=responses({200: ChartOut}),
    summary="Change a saved chart's title, dataset or parameters (editor and above)",
    operation_id="charts_update",
)
def charts_update(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    chart_id: uuid.UUID,
    payload: ChartPatch,
) -> ChartOut:
    project = project_of(member(request, org_id, Role.EDITOR), project_id)
    chart = in_project(ChartSpec, project, chart_id)
    sent = payload.model_fields_set
    changed: list[str] = (
        []
    )  # only these columns are written: a concurrent PATCH of another
    if "title" in sent and payload.title is not None:  # field must not be clobbered
        chart.title = payload.title
        changed.append("title")
    if "dataset_id" in sent:
        chart.dataset = _dataset_in(project, payload.dataset_id)
        changed.append("dataset")
    if "spec" in sent and payload.spec is not None:
        _check_spec(chart.chart_type, payload.spec)
        chart.spec = payload.spec
        changed.append("spec")
    if changed:
        with transaction.atomic():
            chart.save(update_fields=changed)
    return _one(project, chart)


@router.delete(
    f"{_BASE}/{{chart_id}}",
    response=responses({204: None}),
    summary="Delete a saved chart (editor and above)",
    operation_id="charts_delete",
)
def charts_delete(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, chart_id: uuid.UUID
) -> Status[None]:
    project = project_of(member(request, org_id, Role.EDITOR), project_id)
    in_project(ChartSpec, project, chart_id).delete()
    return Status(204, None)


def _referenced_columns(spec: dict[str, Any]) -> list[str]:
    columns: list[str] = []
    for value in spec.values():
        columns.extend(value if isinstance(value, list) else [value])
    return [c for c in columns if isinstance(c, str)]


@router.post(
    f"{_BASE}/{{chart_id}}/render",
    response=responses({200: ChartRenderOut}),
    summary="Build the figure from a bounded sample of the dataset (viewer and above)",
    operation_id="charts_render",
)
def charts_render(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, chart_id: uuid.UUID
) -> ChartRenderOut:
    membership = member(request, org_id, Role.VIEWER)
    project = project_of(membership, project_id)
    chart = in_project(ChartSpec, project, chart_id)
    throttle.enforce("render", user_of(membership).pk, membership.organization_id)
    record = _dataset_in(project, chart.dataset_id)
    if record is None:
        raise ApiError(409, "This chart has no dataset to draw.")
    cfg = api_config()
    spec = chart.spec if isinstance(chart.spec, dict) else {}
    core_bridge.get_process_context()
    try:
        registration = get_chart(chart.chart_type)
    except ServiceError:
        raise ApiError(422, "This chart type is no longer available.") from None
    try:
        with frames.open_frame(get_store(record.organization_id), record) as handle:
            pf = frames.parquet_file(handle)
            columns = _referenced_columns(spec) or frames.column_names(pf)
            sample = frames.read_sample(pf, columns, cfg.render_max_rows)
    except ObjectNotFoundError:
        raise not_found() from None
    except (StorageError, ArrowException, OSError):
        raise ApiError(503, "The dataset could not be read.") from None
    try:
        figure = registration.chart_class.build(sample, **spec)
        if chart.title:
            figure.update_layout(title=chart.title)
        encoded = figure.to_json()
    except (ServiceError, ValueError, KeyError, TypeError):
        raise ApiError(422, "The chart could not be built from this dataset.") from None
    if len(encoded) > cfg.render_max_figure_bytes:
        raise ApiError(422, "The chart is too large to render.")
    return ChartRenderOut(
        figure=json.loads(encoded),
        rows_used=len(sample),
        rows_total=record.row_count,
        sampled=len(sample) < record.row_count,
    )
