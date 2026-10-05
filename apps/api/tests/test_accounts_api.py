# File: apps/api/tests/test_accounts_api.py
"""The 3.3 endpoints: ``/api/me`` and the organization / membership routes.

Why: these are the first routes over tenant data, so they set the pattern every later
router copies -- session auth with CSRF, org id in the path, ``require_membership`` as the
gate, 404 for non-members and 403 for too-low roles. Each reject test has a positive twin
on the same fixtures (observation 0033): a route that refused everyone would otherwise
satisfy every "is refused" assertion.

Fixture ``world``: one organization with an owner, an admin, an editor and a viewer; a
second organization with its own owner; and an outsider who belongs to neither.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, get_args

import pytest
from apihelpers import Api
from factories import make_organization, make_user

from uadas_api.accounts import services
from uadas_api.accounts.api import RoleName
from uadas_api.accounts.models import AuditEvent, Membership, Organization, Role, User

pytestmark = pytest.mark.django_db


@dataclass
class World:
    org: Organization
    owner: Membership
    admin: Membership
    editor: Membership
    viewer: Membership
    other_org: Organization
    other_owner: Membership
    outsider: User

    def members_url(self, org: Organization | None = None) -> str:
        return f"/api/organizations/{(org or self.org).pk}/members"

    def member_url(
        self, membership: Membership, org: Organization | None = None
    ) -> str:
        return f"{self.members_url(org)}/{membership.pk}"


def _join(org: Organization, role: Role) -> Membership:
    return Membership.objects.create(user=make_user(), organization=org, role=role)


@pytest.fixture
def world() -> World:
    org, other = make_organization(), make_organization()
    return World(
        org=org,
        owner=_join(org, Role.OWNER),
        admin=_join(org, Role.ADMIN),
        editor=_join(org, Role.EDITOR),
        viewer=_join(org, Role.VIEWER),
        other_org=other,
        other_owner=_join(other, Role.OWNER),
        outsider=make_user(),
    )


def _events(org: Organization, action: str) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(organization=org, action=action))


# --- GET /api/me ----------------------------------------------------------------------


def test_me_requires_authentication() -> None:
    assert Api().get("/api/me").status_code == 401


def test_me_returns_the_user_and_only_their_memberships(world: World) -> None:
    extra = _join(world.other_org, Role.VIEWER)  # a different user, must not leak
    body = Api(world.admin.user).get("/api/me").json()
    assert body["user"] == {
        "id": str(world.admin.user_id),
        "email": world.admin.user.email,
        "display_name": "",
    }
    assert [m["id"] for m in body["memberships"]] == [str(world.admin.pk)]
    membership = body["memberships"][0]
    assert membership["role"] == "admin"
    assert membership["organization"] == {
        "id": str(world.org.pk),
        "name": world.org.name,
        "slug": world.org.slug,
    }
    assert str(extra.pk) not in str(body)


def test_me_lists_every_organization_of_a_multi_org_user(world: World) -> None:
    Membership.objects.create(
        user=world.admin.user, organization=world.other_org, role=Role.VIEWER
    )
    body = Api(world.admin.user).get("/api/me").json()
    roles = {m["organization"]["id"]: m["role"] for m in body["memberships"]}
    assert roles == {str(world.org.pk): "admin", str(world.other_org.pk): "viewer"}


def test_me_does_not_expose_secrets(world: World) -> None:
    text = Api(world.admin.user).get("/api/me").content.decode()
    assert "password" not in text
    assert "is_superuser" not in text


# --- GET /api/organizations ---------------------------------------------------------------


def test_organization_list_requires_authentication() -> None:
    assert Api().get("/api/organizations").status_code == 401


def test_organization_list_is_only_my_organizations(world: World) -> None:
    mine = Api(world.viewer.user).get("/api/organizations").json()
    assert [m["organization"]["id"] for m in mine] == [str(world.org.pk)]
    assert Api(world.outsider).get("/api/organizations").json() == []


# --- POST /api/organizations ---------------------------------------------------------------


def test_create_organization_makes_the_caller_its_owner_and_audits_it(
    world: World,
) -> None:
    response = Api(world.outsider).post(
        "/api/organizations", {"name": "  Acme Analytics  "}
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["role"] == "owner"
    assert body["organization"]["name"] == "Acme Analytics"
    org = Organization.objects.get(pk=body["organization"]["id"])
    membership = Membership.objects.get(organization=org)
    assert (membership.user_id, membership.role) == (world.outsider.pk, Role.OWNER)
    (event,) = _events(org, "organization.created")
    assert event.actor_id == world.outsider.pk
    assert event.target_type == "organization"
    assert event.target_id == str(org.pk)
    assert event.metadata == {"personal": False}


def test_create_organization_without_the_csrf_token_is_refused(world: World) -> None:
    before = Organization.objects.count()
    response = Api(world.outsider).post(
        "/api/organizations", {"name": "Acme"}, csrf=False
    )
    assert response.status_code == 403
    assert Organization.objects.count() == before


def test_create_organization_requires_authentication() -> None:
    assert Api().post("/api/organizations", {"name": "Acme"}).status_code == 401


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_create_organization_rejects_a_bad_name(world: World, name: str) -> None:
    assert (
        Api(world.outsider).post("/api/organizations", {"name": name}).status_code
        == 422
    )
    assert Api(world.outsider).post("/api/organizations", {}).status_code == 422


def test_organizations_with_the_same_name_get_distinct_slugs(world: World) -> None:
    api = Api(world.outsider)
    first = api.post("/api/organizations", {"name": "Same Name"}).json()
    second = api.post("/api/organizations", {"name": "Same Name"}).json()
    assert first["organization"]["slug"] != second["organization"]["slug"]
    assert first["organization"]["slug"].startswith("same-name")


def test_owned_organizations_are_capped_per_user(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "MAX_OWNED_ORGANIZATIONS", 2)
    api = Api(world.outsider)
    assert api.post("/api/organizations", {"name": "One"}).status_code == 201
    assert api.post("/api/organizations", {"name": "Two"}).status_code == 201
    refused = api.post("/api/organizations", {"name": "Three"})
    assert refused.status_code == 409
    assert Membership.objects.filter(user=world.outsider).count() == 2
    # Joining as a non-owner is not "owning", and other users are unaffected.
    assert (
        Api(world.viewer.user).post("/api/organizations", {"name": "Mine"}).status_code
        == 201
    )


# --- GET /api/organizations/{id}/members ---------------------------------------------------


@pytest.mark.parametrize("who", ["owner", "admin", "editor", "viewer"])
def test_every_member_can_list_members(world: World, who: str) -> None:
    caller: Membership = getattr(world, who)
    response = Api(caller.user).get(world.members_url())
    assert response.status_code == 200
    rows = response.json()
    assert {r["id"] for r in rows} == {
        str(m.pk) for m in (world.owner, world.admin, world.editor, world.viewer)
    }
    row = next(r for r in rows if r["id"] == str(world.editor.pk))
    assert row["user_id"] == str(world.editor.user_id)
    assert row["email"] == world.editor.user.email
    assert row["role"] == "editor"
    assert "password" not in response.content.decode()


def test_members_of_another_organization_are_not_included(world: World) -> None:
    rows = Api(world.owner.user).get(world.members_url()).json()
    assert str(world.other_owner.pk) not in {r["id"] for r in rows}


def test_non_member_gets_404_and_unauthenticated_gets_401(world: World) -> None:
    assert Api(world.outsider).get(world.members_url()).status_code == 404
    # Another tenant's owner is a stranger here, too.
    assert Api(world.other_owner.user).get(world.members_url()).status_code == 404
    assert Api().get(world.members_url()).status_code == 401


def test_the_404_for_a_real_org_equals_the_404_for_a_made_up_one(world: World) -> None:
    api = Api(world.outsider)
    real = api.get(world.members_url())
    made_up = api.get(f"/api/organizations/{uuid.uuid4()}/members")
    assert (real.status_code, real.content) == (made_up.status_code, made_up.content)


# --- PATCH /api/organizations/{id}/members/{membership_id} ---------------------------------


def _patch_role(world: World, caller: Membership, target: Membership, role: str) -> Any:
    return Api(caller.user).patch(world.member_url(target), {"role": role})


def test_admin_can_change_an_editors_role_and_it_is_audited(world: World) -> None:
    response = _patch_role(world, world.admin, world.editor, "viewer")
    assert response.status_code == 200, response.content
    assert response.json()["role"] == "viewer"
    world.editor.refresh_from_db()
    assert world.editor.role == Role.VIEWER
    (event,) = _events(world.org, "membership.role_changed")
    assert event.actor_id == world.admin.user_id
    assert event.target_type == "membership"
    assert event.target_id == str(world.editor.pk)
    assert event.metadata == {
        "from": "editor",
        "to": "viewer",
        "user_id": str(world.editor.user_id),
    }


@pytest.mark.parametrize("who", ["editor", "viewer"])
def test_below_admin_cannot_change_roles(world: World, who: str) -> None:
    caller: Membership = getattr(world, who)
    assert _patch_role(world, caller, world.viewer, "editor").status_code == 403
    world.viewer.refresh_from_db()
    assert world.viewer.role == Role.VIEWER
    assert not _events(world.org, "membership.role_changed")


def test_non_member_and_anonymous_cannot_change_roles(world: World) -> None:
    url = world.member_url(world.viewer)
    assert Api(world.outsider).patch(url, {"role": "admin"}).status_code == 404
    assert Api().patch(url, {"role": "admin"}).status_code == 401


def test_an_admin_cannot_grant_a_role_above_their_own(world: World) -> None:
    assert _patch_role(world, world.admin, world.editor, "owner").status_code == 403
    world.editor.refresh_from_db()
    assert world.editor.role == Role.EDITOR


def test_an_admin_may_grant_admin_and_an_owner_may_grant_owner(world: World) -> None:
    assert _patch_role(world, world.admin, world.editor, "admin").status_code == 200
    assert _patch_role(world, world.owner, world.viewer, "owner").status_code == 200
    world.viewer.refresh_from_db()
    assert world.viewer.role == Role.OWNER


def test_an_admin_cannot_touch_an_owner(world: World) -> None:
    assert _patch_role(world, world.admin, world.owner, "viewer").status_code == 403
    world.owner.refresh_from_db()
    assert world.owner.role == Role.OWNER


def test_an_owner_can_demote_another_owner_when_one_remains(world: World) -> None:
    second = _join(world.org, Role.OWNER)
    assert _patch_role(world, world.owner, second, "admin").status_code == 200
    second.refresh_from_db()
    assert second.role == Role.ADMIN


def test_the_last_owner_cannot_demote_themselves_but_can_with_a_co_owner(
    world: World,
) -> None:
    refused = _patch_role(world, world.owner, world.owner, "admin")
    assert refused.status_code == 409
    assert refused.json()["detail"]
    world.owner.refresh_from_db()
    assert world.owner.role == Role.OWNER
    _join(world.org, Role.OWNER)
    assert _patch_role(world, world.owner, world.owner, "admin").status_code == 200


def test_an_unknown_role_is_rejected(world: World) -> None:
    for role in ("superuser", "", "OWNER"):
        assert _patch_role(world, world.owner, world.viewer, role).status_code == 422
    world.viewer.refresh_from_db()
    assert world.viewer.role == Role.VIEWER


def test_a_membership_of_another_organization_is_404(world: World) -> None:
    url = world.member_url(world.other_owner)  # right org in the path, wrong membership
    assert Api(world.owner.user).patch(url, {"role": "viewer"}).status_code == 404
    world.other_owner.refresh_from_db()
    assert world.other_owner.role == Role.OWNER
    assert (
        Api(world.owner.user)
        .patch(f"{world.members_url()}/{uuid.uuid4()}", {"role": "viewer"})
        .status_code
        == 404
    )


def test_only_the_role_can_be_changed(world: World) -> None:
    body = {
        "role": "viewer",
        "user_id": str(world.outsider.pk),
        "organization_id": str(uuid.uuid4()),
    }
    assert (
        Api(world.owner.user).patch(world.member_url(world.editor), body).status_code
        == 200
    )
    world.editor.refresh_from_db()
    assert world.editor.user_id != world.outsider.pk
    assert world.editor.organization_id == world.org.pk


def test_changing_to_the_same_role_is_a_noop_without_an_audit_event(
    world: World,
) -> None:
    assert _patch_role(world, world.admin, world.editor, "editor").status_code == 200
    assert not _events(world.org, "membership.role_changed")


def test_patch_without_the_csrf_token_is_refused(world: World) -> None:
    api = Api(world.owner.user)
    assert (
        api.patch(
            world.member_url(world.viewer), {"role": "admin"}, csrf=False
        ).status_code
        == 403
    )
    world.viewer.refresh_from_db()
    assert world.viewer.role == Role.VIEWER
    assert (
        api.patch(world.member_url(world.viewer), {"role": "admin"}).status_code == 200
    )


# --- DELETE /api/organizations/{id}/members/{membership_id} --------------------------------


def test_admin_can_remove_a_member_and_it_is_audited(world: World) -> None:
    response = Api(world.admin.user).delete(world.member_url(world.viewer))
    assert response.status_code == 204
    assert not Membership.objects.filter(pk=world.viewer.pk).exists()
    (event,) = _events(world.org, "membership.removed")
    assert event.actor_id == world.admin.user_id
    assert event.target_id == str(world.viewer.pk)
    assert event.metadata == {
        "role": "viewer",
        "user_id": str(world.viewer.user_id),
        "self": False,
    }


def test_a_removed_member_loses_access(world: World) -> None:
    api = Api(world.viewer.user)
    assert api.get(world.members_url()).status_code == 200
    assert (
        Api(world.admin.user).delete(world.member_url(world.viewer)).status_code == 204
    )
    assert api.get(world.members_url()).status_code == 404


@pytest.mark.parametrize("who", ["owner", "admin", "editor", "viewer"])
def test_any_member_can_remove_themselves(world: World, who: str) -> None:
    if who == "owner":
        _join(world.org, Role.OWNER)  # a co-owner, so the owner may leave
    me: Membership = getattr(world, who)
    assert Api(me.user).delete(world.member_url(me)).status_code == 204
    assert not Membership.objects.filter(pk=me.pk).exists()
    (event,) = _events(world.org, "membership.removed")
    assert event.metadata["self"] is True


@pytest.mark.parametrize("who", ["editor", "viewer"])
def test_below_admin_cannot_remove_others(world: World, who: str) -> None:
    caller: Membership = getattr(world, who)
    target = world.admin
    assert Api(caller.user).delete(world.member_url(target)).status_code == 403
    assert Membership.objects.filter(pk=target.pk).exists()


def test_an_admin_cannot_remove_an_owner_but_an_owner_can_remove_a_co_owner(
    world: World,
) -> None:
    assert (
        Api(world.admin.user).delete(world.member_url(world.owner)).status_code == 403
    )
    assert Membership.objects.filter(pk=world.owner.pk).exists()
    co_owner = _join(world.org, Role.OWNER)
    assert Api(world.owner.user).delete(world.member_url(co_owner)).status_code == 204


def test_the_last_owner_cannot_leave(world: World) -> None:
    refused = Api(world.owner.user).delete(world.member_url(world.owner))
    assert refused.status_code == 409
    assert Membership.objects.filter(pk=world.owner.pk).exists()


def test_delete_for_non_member_anonymous_and_wrong_org_membership(world: World) -> None:
    assert Api(world.outsider).delete(world.member_url(world.viewer)).status_code == 404
    assert Api().delete(world.member_url(world.viewer)).status_code == 401
    assert (
        Api(world.owner.user).delete(world.member_url(world.other_owner)).status_code
        == 404
    )
    assert (
        Membership.objects.filter(
            pk__in=[world.viewer.pk, world.other_owner.pk]
        ).count()
        == 2
    )


def test_delete_without_the_csrf_token_is_refused(world: World) -> None:
    api = Api(world.owner.user)
    assert api.delete(world.member_url(world.viewer), csrf=False).status_code == 403
    assert Membership.objects.filter(pk=world.viewer.pk).exists()
    assert api.delete(world.member_url(world.viewer)).status_code == 204


# --- admins and their peers ----------------------------------------------------------------------


def test_an_admin_cannot_demote_or_remove_a_peer_admin(world: World) -> None:
    peer = _join(world.org, Role.ADMIN)
    assert _patch_role(world, world.admin, peer, "viewer").status_code == 403
    assert Api(world.admin.user).delete(world.member_url(peer)).status_code == 403
    peer.refresh_from_db()
    assert peer.role == Role.ADMIN
    assert not _events(world.org, "membership.role_changed")
    assert not _events(world.org, "membership.removed")


def test_an_admin_manages_editors_and_viewers_and_an_owner_manages_admins(
    world: World,
) -> None:
    assert _patch_role(world, world.admin, world.editor, "viewer").status_code == 200
    assert (
        Api(world.admin.user).delete(world.member_url(world.viewer)).status_code == 204
    )
    assert _patch_role(world, world.owner, world.admin, "editor").status_code == 200
    assert (
        Api(world.owner.user).delete(world.member_url(world.admin)).status_code == 204
    )


def test_an_admin_may_step_down_through_the_api(world: World) -> None:
    assert _patch_role(world, world.admin, world.admin, "viewer").status_code == 200
    world.admin.refresh_from_db()
    assert world.admin.role == Role.VIEWER


# --- memberships that vanish between authentication and the change ----------------------------


def test_an_actor_removed_mid_request_gets_404_not_403(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = services.change_member_role

    def removed_first(actor: Membership, target: Membership, role: Role) -> Membership:
        Membership.objects.filter(pk=actor.pk).delete()  # removed after the auth gate
        return real(actor, target, role)

    monkeypatch.setattr(services, "change_member_role", removed_first)
    assert _patch_role(world, world.admin, world.editor, "viewer").status_code == 404
    world.editor.refresh_from_db()
    assert world.editor.role == Role.EDITOR


def test_a_target_removed_mid_request_gets_404(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = services.remove_member

    def target_gone_first(actor: Membership, target: Membership) -> None:
        Membership.objects.filter(pk=target.pk).delete()
        real(actor, target)

    monkeypatch.setattr(services, "remove_member", target_gone_first)
    assert (
        Api(world.admin.user).delete(world.member_url(world.viewer)).status_code == 404
    )
    monkeypatch.undo()
    # Twin: with nothing racing, the same call succeeds.
    assert (
        Api(world.admin.user).delete(world.member_url(world.editor)).status_code == 204
    )


# --- schema ----------------------------------------------------------------------------------


def test_the_api_role_names_are_exactly_the_model_roles() -> None:
    # The Literal in the schema cannot be derived from the enum at type-check time, so it
    # is pinned here: a role added to the model without the schema would be unassignable.
    assert get_args(RoleName) == tuple(Role.values)
