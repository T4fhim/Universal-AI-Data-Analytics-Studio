# File: apps/api/tests/test_member_services.py
"""Member-management rules at the service layer: stale rows and cross-tenant callers.

Why: the endpoint loads the acting and target memberships *before* the service runs, so
their roles can be stale by the time the decision is made (an admin acting after being
demoted; a target promoted to owner a moment ago). The service therefore locks the
organization and re-reads both roles inside its transaction, and refuses memberships of two
different organizations so no caller can cross tenants. Each refusal has a fresh-row twin
that succeeds.
"""

from __future__ import annotations

import pytest
from factories import make_organization, make_user

from uadas_api.accounts import services
from uadas_api.accounts.models import Membership, Organization, Role

pytestmark = pytest.mark.django_db


def _join(org: Organization, role: Role) -> Membership:
    return Membership.objects.create(user=make_user(), organization=org, role=role)


def test_an_actor_demoted_after_loading_cannot_act() -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    admin, victim = _join(org, Role.ADMIN), _join(org, Role.EDITOR)
    stale_admin = Membership.objects.get(pk=admin.pk)  # loaded while still an admin
    Membership.objects.filter(pk=admin.pk).update(role=Role.VIEWER)  # demoted since
    with pytest.raises(services.MemberPolicyError):
        services.change_member_role(stale_admin, victim, Role.VIEWER)
    with pytest.raises(services.MemberPolicyError):
        services.remove_member(stale_admin, victim)
    assert Membership.objects.get(pk=victim.pk).role == Role.EDITOR


def test_an_actor_who_is_still_an_admin_can_act() -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    admin, victim = _join(org, Role.ADMIN), _join(org, Role.EDITOR)
    fresh_admin = Membership.objects.get(pk=admin.pk)
    services.change_member_role(fresh_admin, victim, Role.VIEWER)
    assert Membership.objects.get(pk=victim.pk).role == Role.VIEWER


def test_a_target_promoted_to_owner_after_loading_is_protected() -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    admin, target = _join(org, Role.ADMIN), _join(org, Role.EDITOR)
    stale_target = Membership.objects.get(pk=target.pk)  # loaded as an editor
    Membership.objects.filter(pk=target.pk).update(role=Role.OWNER)  # promoted since
    with pytest.raises(services.MemberPolicyError):
        services.change_member_role(admin, stale_target, Role.VIEWER)
    with pytest.raises(services.MemberPolicyError):
        services.remove_member(admin, stale_target)
    assert Membership.objects.get(pk=target.pk).role == Role.OWNER


def test_a_target_who_is_still_an_editor_can_be_demoted_by_an_admin() -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    admin, target = _join(org, Role.ADMIN), _join(org, Role.EDITOR)
    services.change_member_role(
        admin, Membership.objects.get(pk=target.pk), Role.VIEWER
    )
    assert Membership.objects.get(pk=target.pk).role == Role.VIEWER


# --- admins do not manage their peers ----------------------------------------------------------


def test_an_admin_cannot_demote_or_remove_a_peer_admin() -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    admin, peer = _join(org, Role.ADMIN), _join(org, Role.ADMIN)
    with pytest.raises(services.MemberPolicyError, match="below your own"):
        services.change_member_role(admin, peer, Role.VIEWER)
    with pytest.raises(services.MemberPolicyError, match="below your own"):
        services.remove_member(admin, peer)
    assert Membership.objects.get(pk=peer.pk).role == Role.ADMIN


@pytest.mark.parametrize("below", [Role.EDITOR, Role.VIEWER])
def test_an_admin_manages_members_below_them(below: Role) -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    admin, member = _join(org, Role.ADMIN), _join(org, below)
    services.change_member_role(
        admin, member, Role.EDITOR if below == Role.VIEWER else Role.VIEWER
    )
    services.remove_member(admin, member)
    assert not Membership.objects.filter(pk=member.pk).exists()


def test_an_owner_manages_admins_and_other_owners() -> None:
    org = make_organization()
    owner = _join(org, Role.OWNER)
    admin, co_owner = _join(org, Role.ADMIN), _join(org, Role.OWNER)
    services.change_member_role(owner, admin, Role.EDITOR)
    services.remove_member(owner, co_owner)
    assert Membership.objects.get(pk=admin.pk).role == Role.EDITOR
    assert not Membership.objects.filter(pk=co_owner.pk).exists()


def test_an_admin_may_step_down_or_leave_themselves() -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    first, second = _join(org, Role.ADMIN), _join(org, Role.ADMIN)
    services.change_member_role(first, first, Role.VIEWER)  # self-demotion is fine
    services.remove_member(second, second)  # leaving is always fine
    assert Membership.objects.get(pk=first.pk).role == Role.VIEWER
    assert not Membership.objects.filter(pk=second.pk).exists()


# --- memberships that vanish under the caller -------------------------------------------------------


def test_a_vanished_target_is_not_found_not_a_crash() -> None:
    org = make_organization()
    owner, target = _join(org, Role.OWNER), _join(org, Role.EDITOR)
    ghost = Membership.objects.get(pk=target.pk)
    target.delete()
    with pytest.raises(services.MembershipNotFoundError):
        services.change_member_role(owner, ghost, Role.VIEWER)
    with pytest.raises(services.MembershipNotFoundError):
        services.remove_member(owner, ghost)


def test_a_vanished_actor_is_not_found_and_changes_nothing() -> None:
    org = make_organization()
    _join(org, Role.OWNER)
    admin, victim = _join(org, Role.ADMIN), _join(org, Role.EDITOR)
    ghost = Membership.objects.get(pk=admin.pk)
    admin.delete()  # removed after the endpoint authenticated them
    with pytest.raises(services.MembershipNotFoundError):
        services.change_member_role(ghost, victim, Role.VIEWER)
    assert Membership.objects.get(pk=victim.pk).role == Role.EDITOR


def test_memberships_of_two_organizations_are_refused() -> None:
    org_a, org_b = make_organization(), make_organization()
    owner_a, owner_b = _join(org_a, Role.OWNER), _join(org_b, Role.OWNER)
    viewer_b = _join(org_b, Role.VIEWER)
    with pytest.raises(services.MemberPolicyError, match="same organization"):
        services.change_member_role(owner_a, viewer_b, Role.ADMIN)
    with pytest.raises(services.MemberPolicyError, match="same organization"):
        services.remove_member(owner_a, viewer_b)
    assert Membership.objects.filter(pk=viewer_b.pk, role=Role.VIEWER).exists()
    # Same organization: fine.
    services.change_member_role(owner_b, viewer_b, Role.ADMIN)
    assert Membership.objects.get(pk=viewer_b.pk).role == Role.ADMIN
