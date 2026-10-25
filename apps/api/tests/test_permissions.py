# File: apps/api/tests/test_permissions.py
"""The role order and capability matrix (Phase 3.3).

Why: the order ``viewer < editor < admin < owner`` is the single fact every later router
leans on, so it is defined once (``accounts/permissions.py``) and pinned here. These are
pure-function tests (no database): they fail if a role is added without being ranked,
if the order is shuffled, or if a capability silently moves to a different tier.
"""

from __future__ import annotations

import pytest

from uadas_api.accounts.models import Role
from uadas_api.accounts.permissions import (
    CAPABILITIES,
    ROLE_ORDER,
    Capability,
    can,
    role_at_least,
    role_rank,
)


def test_role_order_is_viewer_editor_admin_owner() -> None:
    assert ROLE_ORDER == (Role.VIEWER, Role.EDITOR, Role.ADMIN, Role.OWNER)


def test_every_role_is_ranked_exactly_once() -> None:
    assert sorted(ROLE_ORDER) == sorted(Role.values)
    assert len(set(ROLE_ORDER)) == len(ROLE_ORDER)


def test_ranks_increase_along_the_order() -> None:
    ranks = [role_rank(r) for r in ROLE_ORDER]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


@pytest.mark.parametrize("higher", range(len(ROLE_ORDER)))
@pytest.mark.parametrize("lower", range(len(ROLE_ORDER)))
def test_role_at_least_follows_the_order(higher: int, lower: int) -> None:
    assert role_at_least(ROLE_ORDER[higher], ROLE_ORDER[lower]) is (higher >= lower)


def test_an_unknown_role_has_no_rank_and_satisfies_nothing() -> None:
    with pytest.raises(ValueError, match="unknown role"):
        role_rank("superuser")
    assert role_at_least("superuser", Role.VIEWER) is False


# (capability, lowest role that holds it) -- the documented matrix, spelled out so a
# change to it is a visible diff in this file and not only in permissions.py.
MATRIX = [
    (Capability.READ, Role.VIEWER),
    (Capability.WRITE_DATA, Role.EDITOR),
    (Capability.MANAGE_MEMBERS, Role.ADMIN),
    (Capability.DELETE_ORGANIZATION, Role.OWNER),
    (Capability.TRANSFER_OWNERSHIP, Role.OWNER),
]


def test_the_matrix_covers_every_capability() -> None:
    assert set(CAPABILITIES) == set(Capability)
    assert {c for c, _ in MATRIX} == set(Capability)


@pytest.mark.parametrize(("capability", "lowest"), MATRIX)
def test_capability_is_granted_from_its_lowest_role_upward_and_not_below(
    capability: Capability, lowest: Role
) -> None:
    assert CAPABILITIES[capability] == lowest
    for role in ROLE_ORDER:
        expected = role_rank(role) >= role_rank(lowest)
        assert can(role, capability) is expected, (role, capability)
