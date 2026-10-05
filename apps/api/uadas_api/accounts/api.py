# File: apps/api/uadas_api/accounts/api.py
"""Account routes: ``/api/me`` and the organization / membership endpoints.

Why this is the template for later routers: it shows the three habits every tenant route
shares. (1) Authentication is the API-wide default (``session_auth``, CSRF included; see
``accounts/security.py``) so nothing here declares it. (2) The organization is in the path
and the first line of each handler is ``require_membership(request, org_id, <min role>)``,
which answers 401/404/403 uniformly. (3) Domain rules live in ``accounts/services.py``; this
module only maps their exceptions to status codes (403 policy, 409 conflict) and shapes the
JSON. Sign-in itself is allauth's, mounted at ``/api/auth/`` (see ``urls.py``).

Invitations by email are not built yet: members can be re-roled and removed, not added.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, Literal

from django.http import HttpRequest
from ninja import Router, Schema, Status
from ninja.errors import HttpError
from pydantic import StringConstraints

from uadas_api.accounts import services
from uadas_api.accounts.models import (
    LastOwnerError,
    Membership,
    Role,
    User,
)
from uadas_api.accounts.security import require_membership

router = Router(tags=["accounts"])

RoleName = Literal["owner", "admin", "editor", "viewer"]  # pinned to Role by a test


class UserOut(Schema):
    id: uuid.UUID
    email: str
    display_name: str


class OrganizationOut(Schema):
    id: uuid.UUID
    name: str
    slug: str


class MembershipOut(Schema):
    """The caller's role in one organization."""

    id: uuid.UUID
    organization: OrganizationOut
    role: RoleName


class MeOut(Schema):
    user: UserOut
    memberships: list[MembershipOut]


class OrganizationIn(Schema):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class MemberOut(Schema):
    """One member of an organization, as another member sees them."""

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    display_name: str
    role: RoleName
    joined_at: datetime.datetime


class MemberRoleIn(Schema):
    role: RoleName


def _caller(request: HttpRequest) -> User:
    user = request.user
    if not isinstance(user, User):  # unreachable behind session_auth; keeps mypy honest
        raise HttpError(401, "Authentication required.")
    return user


def _membership_out(membership: Membership) -> MembershipOut:
    org = membership.organization
    return MembershipOut(
        id=membership.pk,
        organization=OrganizationOut(id=org.pk, name=org.name, slug=org.slug),
        role=membership.role,  # type: ignore[arg-type]
    )


def _member_out(membership: Membership) -> MemberOut:
    return MemberOut(
        id=membership.pk,
        user_id=membership.user_id,
        email=membership.user.email,
        display_name=membership.user.display_name,
        role=membership.role,  # type: ignore[arg-type]
        joined_at=membership.created_at,
    )


@router.get(
    "/me",
    response=MeOut,
    summary="The signed-in user and their organizations",
    operation_id="me",
)
def me(request: HttpRequest) -> MeOut:
    user = _caller(request)
    memberships = (
        Membership.objects.select_related("organization")
        .filter(user=user)
        .order_by("created_at", "pk")
    )
    return MeOut(
        user=UserOut(id=user.pk, email=user.email, display_name=user.display_name),
        memberships=[_membership_out(m) for m in memberships],
    )


@router.get(
    "/organizations",
    response=list[MembershipOut],
    summary="Organizations I belong to",
    operation_id="organizations_list",
)
def organizations_list(request: HttpRequest) -> list[MembershipOut]:
    memberships = (
        Membership.objects.select_related("organization")
        .filter(user=_caller(request))
        .order_by("created_at", "pk")
    )
    return [_membership_out(m) for m in memberships]


@router.post(
    "/organizations",
    response={201: MembershipOut},
    summary="Create an organization (the caller becomes its owner)",
    operation_id="organizations_create",
)
def organizations_create(
    request: HttpRequest, payload: OrganizationIn
) -> Status[MembershipOut]:
    user = _caller(request)
    try:
        organization = services.create_organization(payload.name, user)
    except services.OrganizationLimitError as error:
        raise HttpError(409, str(error)) from None
    membership = Membership.objects.select_related("organization").get(
        user=user, organization=organization
    )
    return Status(201, _membership_out(membership))


@router.get(
    "/organizations/{org_id}/members",
    response=list[MemberOut],
    summary="Members of an organization (viewer and above)",
    operation_id="members_list",
)
def members_list(request: HttpRequest, org_id: uuid.UUID) -> list[MemberOut]:
    require_membership(request, org_id, Role.VIEWER)
    members = (
        Membership.objects.select_related("user")
        .filter(organization_id=org_id)
        .order_by("created_at", "pk")
    )
    return [_member_out(m) for m in members]


def _target(org_id: uuid.UUID, membership_id: uuid.UUID) -> Membership:
    """The membership named in the path, *within* the organization named in the path."""
    target = (
        Membership.objects.select_related("organization", "user")
        .filter(organization_id=org_id, pk=membership_id)
        .first()
    )
    if target is None:
        raise HttpError(404, "Not found.")
    return target


@router.patch(
    "/organizations/{org_id}/members/{membership_id}",
    response=MemberOut,
    summary="Change a member's role (admin and above)",
    operation_id="member_update_role",
)
def member_update_role(
    request: HttpRequest,
    org_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MemberRoleIn,
) -> MemberOut:
    # Admin and above; the service repeats the check and adds the finer rules (grant
    # ceiling, owners only touched by owners), so the rules hold for any caller of it.
    actor = require_membership(request, org_id, Role.ADMIN)
    target = _target(org_id, membership_id)
    try:
        changed = services.change_member_role(actor, target, Role(payload.role))
    except services.MembershipNotFoundError:
        raise HttpError(404, "Not found.") from None
    except services.MemberPolicyError as error:
        raise HttpError(403, str(error)) from None
    except LastOwnerError as error:
        raise HttpError(409, error.messages[0]) from None
    return _member_out(changed)


@router.delete(
    "/organizations/{org_id}/members/{membership_id}",
    response={204: None},
    summary="Remove a member (admin and above), or leave (any member)",
    operation_id="member_remove",
)
def member_remove(
    request: HttpRequest, org_id: uuid.UUID, membership_id: uuid.UUID
) -> Status[None]:
    actor = require_membership(request, org_id, Role.VIEWER)
    target = _target(org_id, membership_id)
    try:
        services.remove_member(actor, target)
    except services.MembershipNotFoundError:
        raise HttpError(404, "Not found.") from None
    except services.MemberPolicyError as error:
        raise HttpError(403, str(error)) from None
    except LastOwnerError as error:
        raise HttpError(409, error.messages[0]) from None
    return Status(204, None)
