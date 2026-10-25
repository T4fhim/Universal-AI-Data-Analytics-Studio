# File: apps/api/uadas_api/web/projects.py
"""Projects: ``/api/organizations/{org_id}/projects`` -- list, create, read, rename, delete.

Roles follow the 3.3 matrix: viewer reads, editor creates and renames, **admin** deletes (removing
a whole workspace is management, not data entry). A project that still owns datasets or reports
cannot be deleted (``PROTECT``, so their stored objects are never orphaned by a project delete):
the answer is ``409`` and the client deletes those first.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.http import HttpRequest
from ninja import Query, Router, Schema, Status
from pydantic import StringConstraints

from uadas_api.accounts.models import Role
from uadas_api.web.errors import ApiError, responses
from uadas_api.web.pagination import Page, PageParams, paginate
from uadas_api.web.scope import member, project_of, user_of
from uadas_api.workspaces.models import Project

router = Router(tags=["projects"])

ProjectName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class ProjectIn(Schema):
    name: ProjectName


class ProjectOut(Schema):
    id: uuid.UUID
    name: str
    created_at: datetime.datetime


def project_out(project: Project) -> ProjectOut:
    return ProjectOut(id=project.pk, name=project.name, created_at=project.created_at)


@router.get(
    "/organizations/{org_id}/projects",
    response=responses({200: Page[ProjectOut]}),
    summary="Projects of an organization (viewer and above)",
    operation_id="projects_list",
)
def projects_list(
    request: HttpRequest, org_id: uuid.UUID, params: Query[PageParams]
) -> dict[str, object]:
    membership = member(request, org_id, Role.VIEWER)
    queryset = Project.objects.for_organization(membership.organization_id).order_by(
        "created_at", "pk"
    )
    return paginate(queryset, params, project_out)


@router.post(
    "/organizations/{org_id}/projects",
    response=responses({201: ProjectOut}),
    summary="Create a project (editor and above)",
    operation_id="projects_create",
)
def projects_create(
    request: HttpRequest, org_id: uuid.UUID, payload: ProjectIn
) -> Status[ProjectOut]:
    membership = member(request, org_id, Role.EDITOR)
    try:
        with transaction.atomic():
            project = Project.objects.create(
                organization_id=membership.organization_id,
                name=payload.name,
                created_by=user_of(membership),
            )
    except IntegrityError:
        raise ApiError(409, "A project with this name already exists.") from None
    return Status(201, project_out(project))


@router.get(
    "/organizations/{org_id}/projects/{project_id}",
    response=responses({200: ProjectOut}),
    summary="One project (viewer and above)",
    operation_id="projects_get",
)
def projects_get(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectOut:
    membership = member(request, org_id, Role.VIEWER)
    return project_out(project_of(membership, project_id))


@router.patch(
    "/organizations/{org_id}/projects/{project_id}",
    response=responses({200: ProjectOut}),
    summary="Rename a project (editor and above)",
    operation_id="projects_rename",
)
def projects_rename(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: ProjectIn,
) -> ProjectOut:
    membership = member(request, org_id, Role.EDITOR)
    project = project_of(membership, project_id)
    project.name = payload.name
    try:
        with transaction.atomic():
            project.save(update_fields=["name"])
    except IntegrityError:
        raise ApiError(409, "A project with this name already exists.") from None
    return project_out(project)


@router.delete(
    "/organizations/{org_id}/projects/{project_id}",
    response=responses({204: None}),
    summary="Delete an empty project (admin and above)",
    operation_id="projects_delete",
)
def projects_delete(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID
) -> Status[None]:
    membership = member(request, org_id, Role.ADMIN)
    project = project_of(membership, project_id)
    try:
        with transaction.atomic():
            project.delete()
    except ProtectedError:
        raise ApiError(
            409, "Delete the project's datasets and reports first."
        ) from None
    return Status(204, None)
