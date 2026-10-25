# File: apps/api/uadas_api/web/pipeline.py
"""The provenance DAG (nodes, edges) and Recipes, read-only: the ``reproduce`` stage's resources.

Nodes and edges are written by the stage jobs (:mod:`uadas_api.stages.run`) in the transaction that
marks a job succeeded; this API only reads them, so a client cannot forge lineage. A node's
``dataset_id`` is the foreign key, returned only if that dataset belongs to the path's project, and
its ``payload`` is a whitelist of the keys the jobs write (the column is free JSON; nothing else
leaves the server). A recipe's ``definition`` is the core's ``Recipe.to_dict()`` document, stored
and returned verbatim and **never dereferenced** here, so ids inside it are not followed.

Creating a recipe from the DAG is not built yet (listed in ``plans/phase-3-6-api.md``).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from django.http import HttpRequest
from ninja import Query, Router, Schema

from uadas_api.accounts.models import Role
from uadas_api.pipeline.models import PipelineEdge, PipelineNode, Recipe
from uadas_api.web.errors import responses
from uadas_api.web.pagination import Page, PageParams, paginate
from uadas_api.web.scope import in_project, member, project_of, scoped
from uadas_api.workspaces.models import DatasetRecord, Project

router = Router(tags=["reproduce"])
_BASE = "/organizations/{org_id}/projects/{project_id}"
_PAYLOAD_KEYS = ("stage", "operation", "parameters", "job_id", "headline", "summary")


class PipelineNodeOut(Schema):
    id: uuid.UUID
    kind: str
    label: str
    dataset_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime.datetime


class PipelineEdgeOut(Schema):
    id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    kind: str
    created_at: datetime.datetime


class RecipeSummaryOut(Schema):
    id: uuid.UUID
    name: str
    version: int
    created_at: datetime.datetime


class RecipeOut(RecipeSummaryOut):
    definition: dict[str, Any]


def _nodes_out(project: Project, nodes: list[PipelineNode]) -> list[PipelineNodeOut]:
    wanted = {n.dataset_id for n in nodes if n.dataset_id}
    valid = set(
        DatasetRecord.objects.for_organization(project.organization_id)
        .filter(project=project, pk__in=wanted)
        .values_list("pk", flat=True)
    )
    out: list[PipelineNodeOut] = []
    for node in nodes:
        raw = node.payload if isinstance(node.payload, dict) else {}
        out.append(
            PipelineNodeOut(
                id=node.pk,
                kind=node.kind,
                label=node.label,
                dataset_id=node.dataset_id if node.dataset_id in valid else None,
                payload={k: raw[k] for k in _PAYLOAD_KEYS if k in raw},
                created_at=node.created_at,
            )
        )
    return out


@router.get(
    f"{_BASE}/pipeline/nodes",
    response=responses({200: Page[PipelineNodeOut]}),
    summary="Lineage nodes of a project (viewer and above)",
    operation_id="pipeline_nodes",
)
def pipeline_nodes(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[PageParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(PipelineNode, project).order_by("created_at", "pk")
    rows = list(queryset[params.offset : params.offset + params.limit])
    return {
        "items": _nodes_out(project, rows),
        "total": queryset.count(),
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    f"{_BASE}/pipeline/edges",
    response=responses({200: Page[PipelineEdgeOut]}),
    summary="Lineage edges of a project (viewer and above)",
    operation_id="pipeline_edges",
)
def pipeline_edges(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[PageParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(PipelineEdge, project).order_by("created_at", "pk")
    return paginate(
        queryset,
        params,
        lambda e: PipelineEdgeOut(
            id=e.pk,
            source_id=e.source_id,
            target_id=e.target_id,
            kind=e.kind,
            created_at=e.created_at,
        ),
    )


@router.get(
    f"{_BASE}/recipes",
    response=responses({200: Page[RecipeSummaryOut]}),
    summary="Recipes of a project (viewer and above)",
    operation_id="recipes_list",
)
def recipes_list(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[PageParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(Recipe, project).order_by("name", "-version", "pk")
    return paginate(
        queryset,
        params,
        lambda r: RecipeSummaryOut(
            id=r.pk, name=r.name, version=r.version, created_at=r.created_at
        ),
    )


@router.get(
    f"{_BASE}/recipes/{{recipe_id}}",
    response=responses({200: RecipeOut}),
    summary="One recipe with its definition (viewer and above)",
    operation_id="recipes_get",
)
def recipes_get(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, recipe_id: uuid.UUID
) -> RecipeOut:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    recipe = in_project(Recipe, project, recipe_id)
    definition = recipe.definition if isinstance(recipe.definition, dict) else {}
    return RecipeOut(
        id=recipe.pk,
        name=recipe.name,
        version=recipe.version,
        created_at=recipe.created_at,
        definition=definition,
    )
