# File: apps/api/tests/test_audit_event.py
"""``AuditEvent`` is append-only: it can be created, never changed or removed.

Why: an audit trail that can be edited is not evidence. Django has several ways to change
a row -- ``save()`` on an existing instance, ``delete()``, ``queryset.update()``,
``queryset.delete()``, ``bulk_update()`` -- and each is closed here. The one mutation
Django itself performs on an audit row is ``on_delete=SET_NULL`` on ``actor`` when a user
is deleted; that goes through the collector, not ``QuerySet.update``, and is asserted
below as the single permitted exception (the event outlives the person). What these
tests cannot prove, and the docstring on the model says, is that raw SQL or a database
admin can still rewrite the table.
"""

from __future__ import annotations

import pytest
from django.db.models import ProtectedError
from factories import factory_for, make_organization, make_user

from uadas_api.accounts.models import (
    AuditEvent,
    AuditEventManager,
    AuditLogImmutableError,
)
from uadas_api.tenancy import TenantIsolationError

pytestmark = pytest.mark.django_db


def _event(**kwargs: object) -> AuditEvent:
    org = make_organization()
    return factory_for(AuditEvent).create(org, **kwargs)


def test_an_event_can_be_created_and_read_back() -> None:
    org, actor = make_organization(), make_user()
    event = AuditEvent.objects.create(
        organization=org,
        actor=actor,
        action="dataset.upload",
        target_type="dataset",
        target_id="abc",
        metadata={"rows": 12},
    )
    loaded = AuditEvent.objects.get(pk=event.pk)
    assert loaded.action == "dataset.upload"
    assert loaded.metadata == {"rows": 12}
    assert loaded.actor == actor
    assert loaded.created_at is not None


def test_saving_an_existing_event_raises() -> None:
    event = _event()
    event.action = "tampered"
    with pytest.raises(AuditLogImmutableError):
        event.save()
    assert AuditEvent.objects.get(pk=event.pk).action == "test.action"


def test_saving_a_reloaded_event_raises() -> None:
    event = AuditEvent.objects.get(pk=_event().pk)
    with pytest.raises(AuditLogImmutableError):
        event.save()


def test_deleting_an_event_raises() -> None:
    event = _event()
    with pytest.raises(AuditLogImmutableError):
        event.delete()
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_queryset_update_raises() -> None:
    event = _event()
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.filter(pk=event.pk).update(action="tampered")
    assert AuditEvent.objects.get(pk=event.pk).action == "test.action"


def test_queryset_delete_raises() -> None:
    event = _event()
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.filter(pk=event.pk).delete()
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.all().delete()
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_bulk_update_raises() -> None:
    event = _event()
    event.action = "tampered"
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.bulk_update([event], ["action"])
    assert AuditEvent.objects.get(pk=event.pk).action == "test.action"


def test_bulk_create_still_appends() -> None:
    org = make_organization()
    events = [
        AuditEvent(organization=org, action=f"a{i}", target_type="t", target_id=str(i))
        for i in range(3)
    ]
    AuditEvent.objects.bulk_create(events)
    assert AuditEvent.objects.for_organization(org).count() == 3


def test_an_organization_with_audit_events_cannot_be_deleted() -> None:
    org = make_organization()
    factory_for(AuditEvent).create(org)
    with pytest.raises(ProtectedError):
        org.delete()
    assert AuditEvent.objects.for_organization(org).count() == 1


def test_deleting_the_actor_keeps_the_event_with_a_null_actor() -> None:
    org, actor = make_organization(), make_user()
    event = factory_for(AuditEvent).create(org, actor=actor)
    actor.delete()
    event.refresh_from_db()
    assert event.actor is None
    assert event.action == "test.action"


def test_the_base_manager_is_locked_too() -> None:
    """Django's related-manager and refresh paths use ``_base_manager``, not ``objects``."""
    event = _event()
    assert isinstance(AuditEvent._base_manager, AuditEventManager)
    with pytest.raises(AuditLogImmutableError):
        AuditEvent._base_manager.filter(pk=event.pk).update(action="tampered")
    with pytest.raises(AuditLogImmutableError):
        AuditEvent._base_manager.filter(pk=event.pk).delete()
    with pytest.raises(AuditLogImmutableError):
        AuditEvent._base_manager.all().delete()
    assert AuditEvent.objects.get(pk=event.pk).action == "test.action"


def test_blanking_the_actor_by_queryset_update_is_tampering_and_is_refused() -> None:
    org, actor = make_organization(), make_user()
    event = factory_for(AuditEvent).create(org, actor=actor)
    with pytest.raises(AuditLogImmutableError):
        AuditEvent.objects.filter(pk=event.pk).update(actor=None)
    assert AuditEvent.objects.get(pk=event.pk).actor == actor


def test_deleting_a_user_detaches_every_one_of_their_events() -> None:
    """The one sanctioned change, made by the delete collector, not by ``update()``."""
    org, actor, bystander = make_organization(), make_user(), make_user()
    mine = [factory_for(AuditEvent).create(org, actor=actor) for _ in range(3)]
    theirs = factory_for(AuditEvent).create(org, actor=bystander)
    actor.delete()
    assert (
        not AuditEvent.objects.filter(pk__in=[e.pk for e in mine])
        .exclude(actor=None)
        .exists()
    )
    assert AuditEvent.objects.get(pk=theirs.pk).actor == bystander
    assert AuditEvent.objects.for_organization(org).count() == 4


def test_bulk_create_upsert_cannot_rewrite_an_existing_event() -> None:
    org = make_organization()
    event = factory_for(AuditEvent).create(org)
    replay = AuditEvent(id=event.pk, organization=org, action="forged", target_type="x")
    with pytest.raises(TenantIsolationError):
        AuditEvent.objects.bulk_create(
            [replay],
            update_conflicts=True,
            unique_fields=["id"],
            update_fields=["action"],
        )
    assert AuditEvent.objects.get(pk=event.pk).action == "test.action"


def test_metadata_defaults_to_an_empty_object_and_target_id_is_text() -> None:
    org = make_organization()
    event = AuditEvent.objects.create(
        organization=org, action="project.open", target_type="project"
    )
    assert event.metadata == {}
    assert event.target_id == ""
