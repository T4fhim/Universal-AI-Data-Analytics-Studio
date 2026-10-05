# File: apps/api/uadas_api/accounts/permissions.py
"""Per-organization roles: their order, and what each tier may do.

Why this module exists: every router from 3.6 onward has to answer "may this member do
this?", and answering it with ad-hoc role comparisons scattered over the codebase is how
authorization drifts. The order of the four roles is therefore defined **once**, here, and
every check goes through :func:`role_at_least` / :func:`can`. A role is per-organization
(:class:`~uadas_api.accounts.models.Membership`), never global.

Capability matrix (a role holds every capability of the tiers below it):

========================  ======  ======  =====  =====
capability                viewer  editor  admin  owner
========================  ======  ======  =====  =====
``read``                  yes     yes     yes    yes
``write_data``            -       yes     yes    yes
``manage_members``        -       -       yes    yes
``delete_organization``   -       -       -      yes
``transfer_ownership``    -       -       -      yes
========================  ======  ======  =====  =====

``read`` is every read of the organization's data; ``write_data`` is creating, changing and
deleting projects, datasets, charts and the rest of the tenant data; ``manage_members``
is changing roles and removing members (with the extra limits in
:mod:`uadas_api.accounts.services`: nobody may grant a role above their own, and only an
owner may change or remove an owner). ``delete_organization`` and ``transfer_ownership``
belong to owners only; the endpoints for them do not exist yet (offboarding is deferred),
but the tier is fixed now so they cannot be added at a weaker one.
"""

from __future__ import annotations

from enum import StrEnum

from uadas_api.accounts.models import Role


class Capability(StrEnum):
    """Something a member may be allowed to do inside one organization."""

    READ = "read"
    WRITE_DATA = "write_data"
    MANAGE_MEMBERS = "manage_members"
    DELETE_ORGANIZATION = "delete_organization"
    TRANSFER_OWNERSHIP = "transfer_ownership"


# Lowest to highest. The one definition of the order; nothing else may hard-code it.
ROLE_ORDER: tuple[Role, ...] = (Role.VIEWER, Role.EDITOR, Role.ADMIN, Role.OWNER)

# The lowest role that holds each capability.
CAPABILITIES: dict[Capability, Role] = {
    Capability.READ: Role.VIEWER,
    Capability.WRITE_DATA: Role.EDITOR,
    Capability.MANAGE_MEMBERS: Role.ADMIN,
    Capability.DELETE_ORGANIZATION: Role.OWNER,
    Capability.TRANSFER_OWNERSHIP: Role.OWNER,
}


def role_rank(role: str) -> int:
    """Position of ``role`` in :data:`ROLE_ORDER` (higher = more powerful)."""
    try:
        return ROLE_ORDER.index(Role(role))
    except ValueError:
        raise ValueError(f"unknown role: {role!r}") from None


def role_at_least(role: str, minimum: str) -> bool:
    """``True`` if ``role`` is ``minimum`` or higher. An unknown role satisfies nothing."""
    try:
        return role_rank(role) >= role_rank(minimum)
    except ValueError:
        return False


def can(role: str, capability: Capability) -> bool:
    """``True`` if ``role`` holds ``capability``."""
    return role_at_least(role, CAPABILITIES[capability])
