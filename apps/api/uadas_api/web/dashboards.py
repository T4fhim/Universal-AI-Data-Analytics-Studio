# File: apps/api/uadas_api/web/dashboards.py
"""Dashboards: CRUD over a grid of tiles that reference saved charts.

``Dashboard.layout`` is free JSON in the database and carries chart ids, so (the 3.2 obligation)
it is never trusted: the API accepts a *typed* tile list, requires every tile's ``chart_id`` to
resolve through ``for_organization`` to a chart of **this project** before storing it, and on read
re-resolves each tile (a tile whose chart was deleted is returned with ``chart_exists = false``,
the core's non-cascading rule: an orphaned reference is normal, not corruption). Only the five
tile fields are ever stored or returned.

Roles: viewer reads; editor creates, edits and deletes.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Query, Router, Schema, Status
from pydantic import Field, StringConstraints

from uadas_api.accounts.models import Role
from uadas_api.web.errors import ApiError, responses
from uadas_api.web.pagination import Page, PageParams
from uadas_api.web.scope import in_project, member, project_of, scoped
from uadas_api.workspaces.models import ChartSpec, Dashboard, Project

router = Router(tags=["dashboards"])
_BASE = "/organizations/{org_id}/projects/{project_id}/dashboards"
MAX_TILES = 100

DashboardName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class TileIn(Schema):
    chart_id: uuid.UUID
    row: Annotated[int, Field(ge=0, le=1000)]
    column: Annotated[int, Field(ge=0, le=100)]
    row_span: Annotated[int, Field(ge=1, le=12)] = 1
    col_span: Annotated[int, Field(ge=1, le=12)] = 1


class TileOut(TileIn):
    chart_exists: bool


class DashboardIn(Schema):
    name: DashboardName
    tiles: Annotated[list[TileIn], Field(max_length=MAX_TILES)] = Field(
        default_factory=list
    )


class DashboardPatch(Schema):
    name: DashboardName | None = None
    tiles: Annotated[list[TileIn], Field(max_length=MAX_TILES)] | None = None


class DashboardOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    tiles: list[TileOut]
    created_at: datetime.datetime


def _layout(tiles: list[TileIn]) -> dict[str, Any]:
    return {
        "tiles": [
            {
                "chart_id": str(t.chart_id),
                "row": t.row,
                "column": t.column,
                "row_span": t.row_span,
                "col_span": t.col_span,
            }
            for t in tiles
        ]
    }


def _require_charts(project: Project, tiles: list[TileIn]) -> None:
    wanted = {t.chart_id for t in tiles}
    found = set(
        scoped(ChartSpec, project).filter(pk__in=wanted).values_list("pk", flat=True)
    )
    if wanted != found:
        raise ApiError(422, "A tile names a chart that is not in this project.")


def _parsed_tiles(dashboard: Dashboard) -> list[TileIn]:
    layout = dashboard.layout if isinstance(dashboard.layout, dict) else {}
    raw = layout.get("tiles")
    items = [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []
    parsed: list[TileIn] = []
    for item in items[:MAX_TILES]:
        try:
            parsed.append(TileIn(**item))
        except (
            ValueError
        ):  # includes pydantic's ValidationError: a malformed stored tile is dropped
            continue
    return parsed


def dashboards_out(project: Project, dashboards: list[Dashboard]) -> list[DashboardOut]:
    """Serialize a page of dashboards, resolving every tile's chart id in **one** query.

    The ids come from a free JSON column, so each is checked through ``for_organization`` and the
    project (the 3.2 obligation); doing it once per page keeps a list from being an N+1.
    """
    parsed = {d.pk: _parsed_tiles(d) for d in dashboards}
    wanted = {t.chart_id for tiles in parsed.values() for t in tiles}
    found = (
        set(
            scoped(ChartSpec, project)
            .filter(pk__in=wanted)
            .values_list("pk", flat=True)
        )
        if wanted
        else set()
    )
    return [
        DashboardOut(
            id=d.pk,
            project_id=d.project_id,
            name=d.name,
            tiles=[
                TileOut(**t.model_dump(), chart_exists=t.chart_id in found)
                for t in parsed[d.pk]
            ],
            created_at=d.created_at,
        )
        for d in dashboards
    ]


def dashboard_out(project: Project, dashboard: Dashboard) -> DashboardOut:
    return dashboards_out(project, [dashboard])[0]


@router.get(
    _BASE,
    response=responses({200: Page[DashboardOut]}),
    summary="Dashboards of a project (viewer and above)",
    operation_id="dashboards_list",
)
def dashboards_list(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[PageParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(Dashboard, project).order_by("created_at", "pk")
    rows = list(queryset[params.offset : params.offset + params.limit])
    return {
        "items": dashboards_out(project, rows),
        "total": queryset.count(),
        "limit": params.limit,
        "offset": params.offset,
    }


@router.post(
    _BASE,
    response=responses({201: DashboardOut}),
    summary="Create a dashboard (editor and above)",
    operation_id="dashboards_create",
)
def dashboards_create(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, payload: DashboardIn
) -> Status[DashboardOut]:
    project = project_of(member(request, org_id, Role.EDITOR), project_id)
    _require_charts(project, payload.tiles)
    with transaction.atomic():
        dashboard = Dashboard.objects.create(
            organization_id=project.organization_id,
            project=project,
            name=payload.name,
            layout=_layout(payload.tiles),
        )
    return Status(201, dashboard_out(project, dashboard))


@router.get(
    f"{_BASE}/{{dashboard_id}}",
    response=responses({200: DashboardOut}),
    summary="One dashboard (viewer and above)",
    operation_id="dashboards_get",
)
def dashboards_get(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dashboard_id: uuid.UUID,
) -> DashboardOut:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    return dashboard_out(project, in_project(Dashboard, project, dashboard_id))


@router.patch(
    f"{_BASE}/{{dashboard_id}}",
    response=responses({200: DashboardOut}),
    summary="Rename a dashboard or replace its tiles (editor and above)",
    operation_id="dashboards_update",
)
def dashboards_update(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dashboard_id: uuid.UUID,
    payload: DashboardPatch,
) -> DashboardOut:
    project = project_of(member(request, org_id, Role.EDITOR), project_id)
    dashboard = in_project(Dashboard, project, dashboard_id)
    changed: list[str] = (
        []
    )  # only the patched columns are written (no clobbering of a concurrent PATCH)
    if payload.name is not None:
        dashboard.name = payload.name
        changed.append("name")
    if payload.tiles is not None:
        _require_charts(project, payload.tiles)
        dashboard.layout = _layout(payload.tiles)
        changed.append("layout")
    try:
        if changed:
            with transaction.atomic():
                dashboard.save(update_fields=changed)
    except IntegrityError:
        raise ApiError(409, "This dashboard could not be saved.") from None
    return dashboard_out(project, dashboard)


@router.delete(
    f"{_BASE}/{{dashboard_id}}",
    response=responses({204: None}),
    summary="Delete a dashboard (editor and above)",
    operation_id="dashboards_delete",
)
def dashboards_delete(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dashboard_id: uuid.UUID,
) -> Status[None]:
    project = project_of(member(request, org_id, Role.EDITOR), project_id)
    in_project(Dashboard, project, dashboard_id).delete()
    return Status(204, None)
