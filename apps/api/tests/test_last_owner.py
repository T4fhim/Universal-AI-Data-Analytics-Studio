# File: apps/api/tests/test_last_owner.py
"""Last-owner protection (Phase 3.3; deferred from 3.2).

Why: an organization with no owner can never be administered again -- nobody may change
roles, and the last person who could is gone. The rule "keep at least one owner" is
therefore enforced where the data is written, not only in the endpoints, on every path
that can remove or demote an owner: ``Membership.save()``, ``Membership.delete()``,
queryset ``update()`` / ``delete()`` / ``bulk_update()`` (so also related managers), and
deleting a *user*, whose memberships are cascaded by Django's collector, which bypasses all
of the former.

Every refusal below is paired with the legitimate twin (the same operation with a second
owner present), so a guard that refuses *everything* cannot pass these tests.
"""

from __future__ import annotations

import pytest
from django.db.models import F, Value
from factories import make_organization, make_user

from uadas_api.accounts.models import (
    AuditEvent,
    LastOwnerError,
    Membership,
    Organization,
    Role,
    User,
)

pytestmark = pytest.mark.django_db


def _member(
    org: Organization, user: User | None = None, role: str = Role.VIEWER
) -> Membership:
    return Membership.objects.create(
        user=user or make_user(), organization=org, role=role
    )


def _owners(org: Organization) -> int:
    return Membership.objects.filter(organization=org, role=Role.OWNER).count()


# --- Membership.save() --------------------------------------------------------------


def test_demoting_the_only_owner_is_refused() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    owner.role = Role.ADMIN
    with pytest.raises(LastOwnerError):
        owner.save()
    owner.refresh_from_db()
    assert owner.role == Role.OWNER


def test_demoting_an_owner_is_allowed_when_another_owner_exists() -> None:
    org = make_organization()
    first = _member(org, role=Role.OWNER)
    _member(org, role=Role.OWNER)
    first.role = Role.ADMIN
    first.save()
    first.refresh_from_db()
    assert first.role == Role.ADMIN
    assert _owners(org) == 1


def test_demotion_through_update_fields_is_guarded_too() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    owner.role = Role.VIEWER
    with pytest.raises(LastOwnerError):
        owner.save(update_fields=["role"])


def test_saving_an_only_owner_without_changing_the_role_is_fine() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    owner.save()
    assert _owners(org) == 1


def test_promoting_and_demoting_non_owners_is_unaffected() -> None:
    org = make_organization()
    _member(org, role=Role.OWNER)
    member = _member(org, role=Role.VIEWER)
    for role in (Role.EDITOR, Role.ADMIN, Role.OWNER, Role.OWNER, Role.VIEWER):
        member.role = role
        member.save()
    assert _owners(org) == 1


def test_the_guard_reads_the_stored_role_not_the_in_memory_one() -> None:
    org = make_organization()
    member = _member(org, role=Role.VIEWER)
    stale = Membership.objects.get(pk=member.pk)  # loaded while a viewer
    # Meanwhile the row becomes the organization's only owner (no guard on promotion).
    Membership.objects.filter(pk=member.pk).update(role=Role.OWNER)
    stale.role = Role.EDITOR  # the stale copy thinks this is viewer -> editor: harmless
    with pytest.raises(LastOwnerError):
        stale.save()
    assert Membership.objects.get(pk=member.pk).role == Role.OWNER


# --- Membership.delete() --------------------------------------------------------------


def test_deleting_the_only_owner_is_refused() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    with pytest.raises(LastOwnerError):
        owner.delete()
    assert Membership.objects.filter(pk=owner.pk).exists()


def test_deleting_an_owner_is_allowed_when_another_owner_exists() -> None:
    org = make_organization()
    first = _member(org, role=Role.OWNER)
    second = _member(org, role=Role.OWNER)
    first.delete()
    assert not Membership.objects.filter(pk=first.pk).exists()
    assert Membership.objects.filter(pk=second.pk).exists()


def test_deleting_a_non_owner_never_needs_an_owner_check() -> None:
    org = make_organization()
    _member(org, role=Role.OWNER)
    viewer = _member(org)
    viewer.delete()
    assert _owners(org) == 1


# --- queryset paths -------------------------------------------------------------------


def test_queryset_update_cannot_demote_the_only_owner() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    with pytest.raises(LastOwnerError):
        Membership.objects.filter(pk=owner.pk).update(role=Role.VIEWER)
    owner.refresh_from_db()
    assert owner.role == Role.OWNER


def test_queryset_update_may_demote_one_of_two_owners_but_not_both_at_once() -> None:
    org = make_organization()
    a = _member(org, role=Role.OWNER)
    b = _member(org, role=Role.OWNER)
    assert Membership.objects.filter(pk=a.pk).update(role=Role.ADMIN) == 1
    with pytest.raises(LastOwnerError):
        Membership.objects.filter(organization=org).update(role=Role.VIEWER)
    b.refresh_from_db()
    assert b.role == Role.OWNER
    both = _member(org, role=Role.OWNER)
    # Two owners (b, both) demoted in one statement leaves none.
    with pytest.raises(LastOwnerError):
        Membership.objects.filter(pk__in=[b.pk, both.pk]).update(role=Role.EDITOR)
    assert _owners(org) == 2


def test_queryset_update_of_other_fields_or_to_owner_is_unaffected() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    viewer = _member(org)
    assert Membership.objects.filter(pk=viewer.pk).update(role=Role.OWNER) == 1
    assert Membership.objects.filter(pk=owner.pk).update(role=Role.OWNER) == 1
    assert _owners(org) == 2


def test_queryset_update_with_an_expression_for_the_role_is_refused() -> None:
    org = make_organization()
    _member(org, role=Role.OWNER)
    # An expression cannot be checked against "is the new role owner?", so it is refused
    # rather than trusted -- the same stance as TenantQuerySet.update.
    with pytest.raises(LastOwnerError, match="expression"):
        Membership.objects.filter(organization=org).update(role=F("role"))
    with pytest.raises(LastOwnerError, match="expression"):
        Membership.objects.filter(organization=org).update(role=Value("viewer"))


def test_queryset_delete_cannot_remove_the_only_owner() -> None:
    org = make_organization()
    _member(org, role=Role.OWNER)
    _member(org)
    with pytest.raises(LastOwnerError):
        Membership.objects.filter(organization=org).delete()
    assert Membership.objects.filter(organization=org).count() == 2


def test_queryset_delete_of_non_owners_and_of_one_of_two_owners_works() -> None:
    org = make_organization()
    a = _member(org, role=Role.OWNER)
    _member(org, role=Role.OWNER)
    _member(org)
    assert (
        Membership.objects.filter(organization=org, role=Role.VIEWER).delete()[0] == 1
    )
    assert Membership.objects.filter(pk=a.pk).delete()[0] == 1
    assert _owners(org) == 1


def test_the_related_manager_is_guarded_as_well() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    with pytest.raises(LastOwnerError):
        owner.user.memberships.all().delete()
    with pytest.raises(LastOwnerError):
        org.memberships.filter(role=Role.OWNER).update(role=Role.VIEWER)


def test_bulk_update_cannot_demote_the_only_owner() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    owner.role = Role.VIEWER
    with pytest.raises(LastOwnerError):
        Membership.objects.bulk_update([owner], ["role"])
    owner.refresh_from_db()
    assert owner.role == Role.OWNER


def test_bulk_update_may_demote_an_owner_when_another_remains() -> None:
    org = make_organization()
    a = _member(org, role=Role.OWNER)
    _member(org, role=Role.OWNER)
    a.role = Role.EDITOR
    assert Membership.objects.bulk_update([a], ["role"]) == 1
    a.refresh_from_db()
    assert a.role == Role.EDITOR


def test_organizations_are_counted_independently() -> None:
    org_a, org_b = make_organization(), make_organization()
    user = make_user()
    mine = _member(org_a, user, Role.OWNER)
    _member(org_b, user, Role.OWNER)  # owning *another* org does not help org_a
    with pytest.raises(LastOwnerError):
        mine.delete()


# --- deleting a user (Django's collector bypasses the Membership guards) -------------


def test_deleting_the_only_owner_user_is_refused_and_changes_nothing() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    with pytest.raises(LastOwnerError):
        owner.user.delete()
    assert User.objects.filter(pk=owner.user_id).exists()
    assert Membership.objects.filter(pk=owner.pk).exists()


def test_the_queryset_delete_of_users_is_guarded_too() -> None:
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    with pytest.raises(LastOwnerError):
        User.objects.filter(pk=owner.user_id).delete()
    assert User.objects.filter(pk=owner.user_id).exists()


def test_deleting_an_owner_user_is_allowed_when_another_owner_remains() -> None:
    org = make_organization()
    leaving = _member(org, role=Role.OWNER)
    staying = _member(org, role=Role.OWNER)
    leaving.user.delete()
    assert not User.objects.filter(pk=leaving.user_id).exists()
    assert not Membership.objects.filter(pk=leaving.pk).exists()
    assert Membership.objects.filter(pk=staying.pk).exists()


def test_deleting_two_co_owners_in_one_statement_is_refused() -> None:
    org = make_organization()
    a = _member(org, role=Role.OWNER)
    b = _member(org, role=Role.OWNER)
    with pytest.raises(LastOwnerError):
        User.objects.filter(pk__in=[a.user_id, b.user_id]).delete()
    assert User.objects.filter(pk__in=[a.user_id, b.user_id]).count() == 2


def test_deleting_a_non_owner_user_is_unaffected() -> None:
    org = make_organization()
    _member(org, role=Role.OWNER)
    viewer = _member(org)
    viewer.user.delete()
    assert _owners(org) == 1


def test_a_deleted_co_owner_keeps_their_audit_events_with_the_actor_detached() -> None:
    org = make_organization()
    leaving = _member(org, role=Role.OWNER)
    _member(org, role=Role.OWNER)
    event = AuditEvent.objects.create(
        organization=org, actor=leaving.user, action="x.y", target_type="t"
    )
    leaving.user.delete()
    event.refresh_from_db()
    assert event.actor is None
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_deleting_an_organization_still_cascades_its_memberships() -> None:
    # Offboarding an organization removes its owners with it; that is not "leaving an
    # organization ownerless". (An organization with audit history cannot be deleted at
    # all -- PROTECT -- so this is the path for one that never recorded an event.)
    org = make_organization()
    owner = _member(org, role=Role.OWNER)
    org.delete()
    assert not Membership.objects.filter(pk=owner.pk).exists()
    assert User.objects.filter(pk=owner.user_id).exists()


@pytest.mark.django_db(transaction=True)
def test_two_owners_demoted_at_the_same_moment_cannot_both_succeed() -> None:
    """The row lock is what makes "the other owner remains" true when the check runs.

    Two admins each demote a *different* owner of a two-owner organization at once. Without
    the organization lock both transactions see the other owner still in place and both
    commit, leaving none; with it they serialise, so exactly one is refused. Needs real row
    locks, i.e. Postgres (SQLite serialises writers anyway, so the race cannot occur there).
    """
    import threading
    from uuid import UUID

    from django.db import connection, connections

    if connection.vendor != "postgresql":
        pytest.skip("row locks are a PostgreSQL behaviour; CI's api-test job runs this")
    org = make_organization()
    first, second = _member(org, role=Role.OWNER), _member(org, role=Role.OWNER)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def demote(membership_id: UUID) -> None:
        try:
            member = Membership.objects.get(pk=membership_id)
            member.role = Role.ADMIN
            barrier.wait(timeout=10)
            try:
                member.save()
                outcomes.append("demoted")
            except LastOwnerError:
                outcomes.append("refused")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=demote, args=(m.pk,)) for m in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(outcomes) == ["demoted", "refused"]
    assert _owners(org) == 1
