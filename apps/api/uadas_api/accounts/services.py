# File: apps/api/uadas_api/accounts/services.py
"""Account use-cases: provisioning, organizations and members, and the audit trail.

Why a service layer: the same rules must hold whether a change arrives through the HTTP
API, an allauth signup hook or (later) a management command, and "create the organization
*and* its owner *and* the audit row, or none of them" is a transaction boundary, not an
endpoint detail. Views stay thin: they authenticate, call ``require_membership`` and map the
exceptions below to status codes (:class:`MemberPolicyError` -> 403, ``LastOwnerError`` and
:class:`OrganizationLimitError` -> 409).

What is audited (``AuditEvent``: organization, actor, ``action``, ``target_type``,
``target_id``, ``metadata``): signup, organization creation, role change, member removal
(here) and login / logout (``accounts/signals.py``). Metadata carries ids and role names
only -- never a password, token, session key or free text; the actor's email is not copied
(``actor`` already points at the user while the user exists).
"""

from __future__ import annotations

import re
import secrets
import uuid
from collections.abc import Iterator
from typing import Any

from django.db import IntegrityError, transaction
from django.utils.text import slugify

from uadas_api.accounts.models import (
    AuditEvent,
    Membership,
    Organization,
    Role,
    User,
)
from uadas_api.accounts.permissions import Capability, can, role_rank

# A user may own at most this many organizations: an unauthenticated-to-owner path (sign up,
# then POST /api/organizations in a loop) must not be a free way to mint unbounded rows.
MAX_OWNED_ORGANIZATIONS = 20

_SLUG_BASE_LENGTH = 40
_SLUG_ATTEMPTS = 6
_NAME_MAX = 200


class MemberPolicyError(Exception):
    """The caller's role does not allow this change to a membership (HTTP 403)."""


class MembershipNotFoundError(Exception):
    """The acting or target membership no longer exists (HTTP 404)."""


class OrganizationLimitError(Exception):
    """The user already owns the maximum number of organizations (HTTP 409)."""


# --- audit --------------------------------------------------------------------------------


def record_audit(
    organization: Organization,
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str = "",
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    """Append one :class:`AuditEvent` to ``organization``'s log."""
    return AuditEvent.objects.create(
        organization=organization,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        metadata=metadata or {},
    )


def record_user_event(user: User, action: str) -> AuditEvent | None:
    """Audit something a *user* did that has no organization of its own (login, logout).

    Audit rows belong to an organization, so the event is filed under the user's oldest
    membership -- for a normal account, the personal organization created at signup. A user
    with no membership has nowhere to record it and yields ``None``.
    """
    organization_id = (
        Membership.objects.filter(user=user)
        .order_by("created_at", "pk")
        .values_list("organization_id", flat=True)
        .first()
    )
    if organization_id is None:
        return None
    return AuditEvent.objects.create(
        organization_id=organization_id,
        actor=user,
        action=action,
        target_type="user",
        target_id=str(user.pk),
        metadata={},
    )


# --- organizations ---------------------------------------------------------------------------


def _slug_base(name: str) -> str:
    # Dots, underscores and plus signs separate words in an email's local part; Django's
    # slugify would delete them and glue the words together.
    return (
        slugify(re.sub(r"[._+\s]+", "-", name))[:_SLUG_BASE_LENGTH].strip("-")
        or "workspace"
    )


def _candidate_slugs(name: str) -> Iterator[str]:
    base = _slug_base(name)
    yield base
    for _ in range(_SLUG_ATTEMPTS - 1):
        yield f"{base}-{secrets.token_hex(3)}"


def create_organization(
    name: str, owner: User, *, personal: bool = False
) -> Organization:
    """Create an organization with ``owner`` as its owner, and audit it -- atomically.

    The slug comes from the name and is made unique with a random suffix on collision; the
    insert is retried if a concurrent request wins the same slug (the unique constraint is
    the arbiter, the pre-check is only an optimisation). Raises
    :class:`OrganizationLimitError` for a non-personal organization when the user already
    owns :data:`MAX_OWNED_ORGANIZATIONS`.
    """
    name = " ".join(name.split())[:_NAME_MAX] or "Workspace"
    with transaction.atomic():
        if not personal:
            # Count under a row lock on the creating user: two parallel requests from one
            # account would otherwise both count "below the cap" and both insert.
            list(
                User.objects.select_for_update()
                .filter(pk=owner.pk)
                .values_list("pk", flat=True)
            )
            owned = Membership.objects.filter(user=owner, role=Role.OWNER).count()
            if owned >= MAX_OWNED_ORGANIZATIONS:
                raise OrganizationLimitError(
                    f"You can own at most {MAX_OWNED_ORGANIZATIONS} organizations."
                )
        organization: Organization | None = None
        for slug in _candidate_slugs(name):
            if Organization.objects.filter(slug=slug).exists():
                continue
            try:
                with transaction.atomic():
                    organization = Organization.objects.create(name=name, slug=slug)
            except IntegrityError:
                continue
            break
        if organization is None:
            raise RuntimeError("could not allocate a unique organization slug")
        Membership.objects.create(
            user=owner, organization=organization, role=Role.OWNER
        )
        record_audit(
            organization,
            actor=owner,
            action="organization.created",
            target_type="organization",
            target_id=organization.pk,
            metadata={"personal": personal},
        )
    return organization


def provision_personal_organization(user: User) -> Organization | None:
    """Give a freshly signed-up ``user`` a personal organization they own; audit the signup.

    Called from the allauth adapters inside the signup transaction, so a user can never
    exist without an organization (nor an organization without its owner). Idempotent: a
    user who already belongs to any organization is left alone and ``None`` is returned
    (the social-signup-with-form path reaches this twice).
    """
    if Membership.objects.filter(user=user).exists():
        return None
    local_part = (user.email or "").partition("@")[0].strip()
    with transaction.atomic():
        organization = create_organization(
            local_part or "Personal", user, personal=True
        )
        record_audit(
            organization,
            actor=user,
            action="user.signed_up",
            target_type="user",
            target_id=user.pk,
        )
    return organization


# --- members -----------------------------------------------------------------------------------


def _lock_and_refresh(actor: Membership, target: Membership) -> None:
    """Lock the organization and re-read both roles, inside the caller's transaction.

    The endpoint loaded ``actor`` and ``target`` before any lock, so their roles may be
    stale: an admin must not demote someone promoted to owner a moment ago, nor act after
    being demoted or removed. Also refuses memberships of two different organizations, so
    no caller of the service can cross tenants. Raises :class:`MembershipNotFoundError`
    if either membership no longer exists (a just-removed actor is a non-member, and a
    vanished target is simply not there: both are "not found", never "forbidden").
    """
    if actor.organization_id != target.organization_id:
        raise MemberPolicyError(
            "Both memberships must belong to the same organization."
        )
    list(
        Organization.objects.select_for_update()
        .filter(pk=target.organization_id)
        .values_list("pk", flat=True)
    )
    try:
        actor.refresh_from_db(fields=["role"])
        target.refresh_from_db(fields=["role"])
    except Membership.DoesNotExist:
        raise MembershipNotFoundError("That membership no longer exists.") from None


def _assert_may_manage(actor: Membership, target: Membership, *, is_self: bool) -> None:
    """Who may change or remove whom (after the rows were re-read).

    The actor needs ``manage_members`` (admin or owner). An owner may manage anyone (the
    last-owner rule still applies). Anyone else may manage only members *strictly below*
    their own role: an admin manages editors and viewers, never a peer admin or an owner --
    otherwise one compromised or disgruntled admin could strip every other admin. Acting on
    yourself is allowed here (stepping down, leaving); granting above your own role is
    refused separately.
    """
    if is_self:
        return
    if not can(actor.role, Capability.MANAGE_MEMBERS):
        raise MemberPolicyError("Managing members requires the admin role.")
    if actor.role == Role.OWNER:
        return
    if target.role == Role.OWNER:
        raise MemberPolicyError("Only an owner can change or remove an owner.")
    if role_rank(target.role) >= role_rank(actor.role):
        raise MemberPolicyError("You can only manage members below your own role.")


def change_member_role(
    actor: Membership, target: Membership, new_role: Role
) -> Membership:
    """Set ``target``'s role to ``new_role`` on behalf of ``actor`` (a member of the same organization).

    Rules: the actor needs ``manage_members`` (admin or owner); nobody may grant a role above
    their own (an admin cannot create owners); an owner may change anyone, anyone else only
    members strictly below their own role (:func:`_assert_may_manage`), so an admin cannot
    touch a peer admin; stepping down yourself is allowed. The last-owner rule is enforced by ``Membership.save`` and surfaces as ``LastOwnerError``.
    Setting the role a member already has is a no-op and records nothing.
    """
    with transaction.atomic():
        _lock_and_refresh(actor, target)  # decide on the rows as they are *now*
        if not can(actor.role, Capability.MANAGE_MEMBERS):
            raise MemberPolicyError("Changing roles requires the admin role.")
        if role_rank(new_role) > role_rank(actor.role):
            raise MemberPolicyError("You cannot grant a role above your own.")
        _assert_may_manage(actor, target, is_self=actor.pk == target.pk)
        if target.role == new_role:
            return target
        previous = target.role
        target.role = new_role
        target.save(update_fields=["role"])
        record_audit(
            target.organization,
            actor=actor.user,
            action="membership.role_changed",
            target_type="membership",
            target_id=target.pk,
            metadata={"from": previous, "to": new_role, "user_id": str(target.user_id)},
        )
    return target


def remove_member(actor: Membership, target: Membership) -> None:
    """Remove ``target`` from the organization on behalf of ``actor``.

    A member may always remove themselves; removing someone else needs ``manage_members``
    and a role strictly above the target's (an owner may remove anyone). The last owner
    cannot be removed (``LastOwnerError``).
    """
    is_self = actor.pk == target.pk
    with transaction.atomic():
        _lock_and_refresh(actor, target)  # decide on the rows as they are *now*
        _assert_may_manage(actor, target, is_self=is_self)
        role, user_id, membership_id = target.role, target.user_id, target.pk
        target.delete()
        record_audit(
            actor.organization,
            actor=actor.user,
            action="membership.removed",
            target_type="membership",
            target_id=membership_id,
            metadata={"role": role, "user_id": str(user_id), "self": is_self},
        )
