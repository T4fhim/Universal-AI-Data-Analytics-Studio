# File: apps/api/tests/test_tenancy_mechanics.py
"""The corners of ``uadas_api.tenancy`` the generic harness does not reach.

Why: the harness runs the same cross-organization checks against every tenant model;
this file covers behaviour of the machinery itself that no single model exposes -- a row
with no organization, an unverifiable expression assigned to a tenant FK, the promise that
the error message does not reveal another tenant's ids, ``update_fields`` scoping, and the
shape of the manager/queryset API. Written against ``Project``/``DatasetRecord``, which
between them have a tenant FK, a scalar unique and a storage key.
"""

from __future__ import annotations

import uuid

import pytest
from django.db import models, transaction
from django.db.models import F
from factories import factory_for, make_organization

from uadas_api.tenancy import (
    TenantIsolationError,
    TenantManager,
    TenantQuerySet,
    iter_tenant_models,
    tenant_fk_fields,
)
from uadas_api.workspaces.models import DatasetRecord, Project

pytestmark = pytest.mark.django_db


def test_a_tenant_row_without_an_organization_is_refused() -> None:
    with pytest.raises(TenantIsolationError, match="needs an organization"):
        Project(name="orphan").save()


def test_organization_can_be_chosen_freely_until_the_first_save() -> None:
    org_a, org_b = make_organization(), make_organization()
    project = factory_for(Project).build(org_a)
    project.organization = org_b  # still a draft: nothing references it yet
    project.save()
    assert Project.objects.get(pk=project.pk).organization_id == org_b.pk


def test_the_organization_of_a_just_saved_instance_is_locked_too() -> None:
    org_a, org_b = make_organization(), make_organization()
    project = factory_for(Project).create(org_a)
    project.organization = org_b
    with pytest.raises(TenantIsolationError, match="immutable"):
        project.save()


def test_a_saved_row_can_still_change_its_ordinary_fields() -> None:
    project = factory_for(Project).create(make_organization())
    project.name = "renamed"
    project.save()
    assert Project.objects.get(pk=project.pk).name == "renamed"


def test_the_error_does_not_reveal_the_other_tenants_ids() -> None:
    org_a, org_b = make_organization(), make_organization()
    foreign = factory_for(Project).create(org_b)
    with pytest.raises(TenantIsolationError) as excinfo:
        factory_for(DatasetRecord).create(org_a, project=foreign)
    message = " ".join(excinfo.value.messages)
    assert str(foreign.pk) not in message
    assert str(org_b.pk) not in message
    assert "workspaces.DatasetRecord.project" in message


def test_assigning_an_expression_to_a_tenant_fk_is_refused_because_it_cannot_be_checked() -> (
    None
):
    org = make_organization()
    record = factory_for(DatasetRecord).create(org)
    with pytest.raises(TenantIsolationError, match="expression"):
        DatasetRecord.objects.filter(pk=record.pk).update(project=F("project"))


def test_update_of_ordinary_fields_is_unaffected() -> None:
    org = make_organization()
    record = factory_for(DatasetRecord).create(org)
    assert DatasetRecord.objects.filter(pk=record.pk).update(name="x", row_count=9) == 1
    record.refresh_from_db()
    assert (record.name, record.row_count) == ("x", 9)


def test_update_setting_a_tenant_fk_to_null_is_allowed_where_the_column_is_nullable() -> (
    None
):
    org = make_organization()
    from uadas_api.workspaces.models import ChartSpec

    dataset = factory_for(DatasetRecord).create(org)
    chart = factory_for(ChartSpec).create(org, project=dataset.project, dataset=dataset)
    assert ChartSpec.objects.filter(pk=chart.pk).update(dataset=None) == 1


def test_update_checks_every_row_it_would_touch() -> None:
    org_a, org_b = make_organization(), make_organization()
    mine = factory_for(DatasetRecord).create(org_a)
    theirs = factory_for(DatasetRecord).create(org_b)
    target = factory_for(Project).create(org_a)
    # one of the two matched rows is another tenant's: the whole update is refused
    with pytest.raises(TenantIsolationError):
        DatasetRecord.objects.filter(pk__in=[mine.pk, theirs.pk]).update(project=target)
    mine.refresh_from_db()
    assert mine.project_id != target.pk


def test_update_to_a_nonexistent_target_is_left_to_the_database() -> None:
    org = make_organization()
    record = factory_for(DatasetRecord).create(org)
    # The tenancy check has nothing to compare against, so it steps aside; the database's
    # own FK constraint is the authority on a dangling reference. SQLite and Postgres
    # defer that check to commit, so the dangling row is rolled back explicitly.
    with transaction.atomic():
        DatasetRecord.objects.filter(pk=record.pk).update(project=uuid.uuid4())
        transaction.set_rollback(True)


def test_update_fields_limits_the_foreign_key_check_to_the_fields_being_saved() -> None:
    org_a, org_b = make_organization(), make_organization()
    record = factory_for(DatasetRecord).create(org_a)
    record.project = factory_for(Project).create(org_b)  # wrong, but not being saved
    record.name = "only-the-name"
    record.save(update_fields=["name"])
    fresh = DatasetRecord.objects.get(pk=record.pk)
    assert fresh.name == "only-the-name"
    assert (
        fresh.project.organization_id == org_a.pk
    )  # the bad assignment never persisted


def test_bulk_create_checks_a_whole_batch_in_few_queries(
    django_assert_max_num_queries: object,
) -> None:
    org = make_organization()
    project = factory_for(Project).create(org)
    rows = [factory_for(DatasetRecord).build(org, project=project) for _ in range(25)]
    # The FK target is cached on each instance, so verification costs no per-row query.
    # savepoint + insert(s) + release; the point is that 25 rows do not cost 25 lookups.
    with django_assert_max_num_queries(6):  # type: ignore[operator]
        DatasetRecord.objects.bulk_create(rows)


def test_for_organization_accepts_a_row_a_uuid_or_its_string() -> None:
    org = make_organization()
    row = factory_for(Project).create(org)
    other = factory_for(Project).create(make_organization())
    for ref in (org, org.pk, str(org.pk)):
        assert list(Project.objects.for_organization(ref)) == [row]
    assert other not in Project.objects.for_organization(org)


def test_for_organization_chains_with_ordinary_queryset_methods() -> None:
    org = make_organization()
    factory_for(Project).create(org, name="a")
    factory_for(Project).create(org, name="b")
    qs = Project.objects.for_organization(org)
    assert isinstance(qs, TenantQuerySet)
    assert isinstance(qs.filter(name="a"), TenantQuerySet)
    assert qs.filter(name="a").for_organization(org).count() == 1
    plain = Project.objects.filter(name="a")  # typed as a plain QuerySet by the stubs
    assert plain.for_organization(org).count() == 1  # type: ignore[attr-defined]
    # scoping to a *different* organization after the fact leaves nothing
    assert qs.for_organization(make_organization()).count() == 0


def test_the_manager_exposes_the_queryset_type() -> None:
    assert isinstance(Project.objects, TenantManager)
    assert isinstance(Project.objects.all(), TenantQuerySet)


def test_tenant_fk_fields_lists_only_foreign_keys_to_tenant_models() -> None:
    assert {f.name for f in tenant_fk_fields(DatasetRecord)} == {"project"}
    assert (
        tenant_fk_fields(Project) == []
    )  # organization and created_by are not tenant FKs
    assert all(
        isinstance(f, models.ForeignKey) for f in tenant_fk_fields(DatasetRecord)
    )


def test_discovery_includes_every_workspace_pipeline_and_export_model() -> None:
    labels = {m._meta.label for m in iter_tenant_models()}
    assert {
        "accounts.AuditEvent",
        "workspaces.Project",
        "workspaces.DatasetRecord",
        "workspaces.ChartSpec",
        "workspaces.Dashboard",
        "pipeline.PipelineNode",
        "pipeline.PipelineEdge",
        "pipeline.Recipe",
        "exports.Report",
    } == labels
