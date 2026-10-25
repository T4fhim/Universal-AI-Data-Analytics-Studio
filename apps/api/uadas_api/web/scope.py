# File: apps/api/uadas_api/web/scope.py
"""Resolving the ids of a request inside the caller's organization and the path's project.

Why one module: the 3.2 obligation ("every reader resolves ids through ``for_organization``")
is only as strong as the weakest handler, so handlers never call ``Model.objects.get(pk=...)``.
They call :func:`member` first (401 / 404 / 403 through ``require_membership``), then
:func:`project_of` and :func:`in_project`, which query ``Model.objects.for_organization(org)`` and
narrow to the project of the *path*. A missing row, a row of another organization and a row of
another project of this organization are the same ``404 Not found.``: a caller can never tell
them apart, so ids cannot be probed.

``tests/test_web_idor.py`` walks every operation of the OpenAPI schema with an organization-B
member holding organization-A ids and fails if any answers with A's data; a handler that skips
these helpers would fail there, not in review.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.http import HttpRequest

from uadas_api.accounts.models import Membership, Role, User
from uadas_api.accounts.security import require_membership
from uadas_api.tenancy import TenantOwnedModel
from uadas_api.web.errors import not_found
from uadas_api.workspaces.models import Project


def member(
    request: HttpRequest, org_id: uuid.UUID, min_role: Role = Role.VIEWER
) -> Membership:
    """The caller's membership in ``org_id`` with at least ``min_role`` (401 / 404 / 403 else)."""
    return require_membership(request, org_id, min_role)


def user_of(membership: Membership) -> User:
    """The signed-in user of a membership returned by :func:`member`."""
    return membership.user


def project_of(membership: Membership, project_id: uuid.UUID) -> Project:
    """The project ``project_id`` of the caller's organization, or ``404``."""
    project = (
        Project.objects.for_organization(membership.organization_id)
        .filter(pk=project_id)
        .first()
    )
    if project is None:
        raise not_found()
    return project


def in_project[M: TenantOwnedModel](
    model: type[M], project: Project, pk: uuid.UUID, **extra: Any
) -> M:
    """The ``model`` row ``pk`` that belongs to ``project`` (and so to its organization), or ``404``.

    ``model`` must have a ``project`` foreign key. ``extra`` adds filters (for example
    ``kind=...``); they narrow, never widen.
    """
    row = (
        model.objects.for_organization(project.organization_id)
        .filter(pk=pk, project=project, **extra)
        .first()
    )
    if row is None:
        raise not_found()
    return row


def scoped[M: TenantOwnedModel](model: type[M], project: Project) -> Any:
    """The queryset of ``model`` rows of ``project`` (organization-scoped first)."""
    return model.objects.for_organization(project.organization_id).filter(
        project=project
    )
