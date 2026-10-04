# File: apps/api/tests/test_tenant_isolation.py
"""Discovery-based tenant-isolation harness (written before the second tenant model).

Why: tenant isolation is the property that must never regress, and a hand-maintained list
of "models to test" is exactly the kind of registry-plus-hardcoded-consumer pair that
silently drifts (CLAUDE.md, "Multi-file touchpoints"). So nothing here names a model. It
walks ``django.apps`` for every concrete :class:`~uadas_api.tenancy.TenantOwnedModel` and
runs the same checks against each, building rows through the factory registry in
``factories.py`` -- and :func:`test_every_tenant_model_has_a_factory` fails if a new
tenant model has no factory, so it cannot dodge the checks by not being listed.

The checks, per discovered model:

* ``organization`` exists, is non-null, indexed, and ``on_delete=PROTECT``;
* ``for_organization(a)`` never returns organization b's rows;
* a foreign key to another tenant model is rejected when it crosses organizations, on
  ``save()``, ``bulk_create()``, ``bulk_update()`` and ``queryset.update()``;
* uniqueness is per organization (same values in two organizations is fine, twice in one
  is not) and no field is *globally* unique;
* an organization that owns a row cannot be deleted.

Plus a completeness test: every model in the ``uadas_api`` apps is tenant-owned or on an
explicit, reviewed allowlist, so a new model cannot be tenant-less by accident.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.apps import apps
from django.db import IntegrityError, models, transaction
from factories import factory_for, make_organization, registered_models

from uadas_api.accounts.models import (
    AuditLogImmutableError,
    Membership,
    Organization,
    User,
)
from uadas_api.tenancy import (
    TenantIsolationError,
    TenantManager,
    TenantOwnedModel,
    iter_tenant_models,
    tenant_fk_fields,
)

TENANT_MODELS = iter_tenant_models()
MODEL_IDS = [m._meta.label for m in TENANT_MODELS]

# Models in the uadas_api apps that are deliberately NOT tenant-owned. Each entry is a
# reviewed decision: the user and organization ARE the tenancy primitives, and a
# membership is the link between them. Adding to this set is a design decision.
NON_TENANT_ALLOWLIST: frozenset[type[models.Model]] = frozenset(
    {User, Organization, Membership}
)

FK_CASES = [(m, f.name) for m in TENANT_MODELS for f in tenant_fk_fields(m)]
FK_IDS = [f"{m._meta.label}.{name}" for m, name in FK_CASES]

UNIQUE_CASES = [
    (m, c)
    for m in TENANT_MODELS
    for c in m._meta.constraints
    if isinstance(c, models.UniqueConstraint) and c.fields
]
UNIQUE_IDS = [f"{m._meta.label}.{c.name}" for m, c in UNIQUE_CASES]

# Plain-UUID references to another tenant row (not foreign keys; see DatasetRecord).
SOFT_CASES = [(m, name) for m in TENANT_MODELS for name in m.soft_tenant_refs]
SOFT_IDS = [f"{m._meta.label}.{name}" for m, name in SOFT_CASES]


def _leading_fields(model: type[models.Model]) -> set[str]:
    """Names of the first column of every explicit index and unique constraint."""
    leading = {i.fields[0].lstrip("-") for i in model._meta.indexes if i.fields}
    leading |= {
        c.fields[0]
        for c in model._meta.constraints
        if isinstance(c, models.UniqueConstraint) and c.fields
    }
    return leading


def _ids(queryset: models.QuerySet[Any]) -> set[Any]:
    return set(queryset.values_list("pk", flat=True))


# ---------------------------------------------------------------- completeness


def test_discovery_finds_tenant_models() -> None:
    assert TENANT_MODELS, "discovery found no TenantOwnedModel subclass"
    assert all(not m._meta.abstract for m in TENANT_MODELS)


def test_every_tenant_model_has_a_factory() -> None:
    missing = [m._meta.label for m in TENANT_MODELS if m not in registered_models()]
    assert not missing, (
        f"tenant models without a factory in tests/factories.py: {missing}. "
        "Register one so the isolation harness covers them."
    )


def test_no_factory_is_registered_for_a_model_that_is_not_tenant_owned() -> None:
    stale = [m._meta.label for m in registered_models() if m not in TENANT_MODELS]
    assert not stale, f"factories for non-tenant models: {stale}"


def test_every_api_model_is_tenant_owned_or_allowlisted() -> None:
    offenders = [
        m._meta.label
        for m in apps.get_models()
        if m._meta.app_label in {c.label for c in _api_app_configs()}
        and not issubclass(m, TenantOwnedModel)
        and m not in NON_TENANT_ALLOWLIST
    ]
    assert not offenders, (
        f"models that are neither TenantOwnedModel nor allowlisted: {offenders}. "
        "Every table in this API belongs to a tenant unless a reviewer says otherwise."
    )


def test_allowlist_names_only_live_models_in_the_api_apps() -> None:
    api_labels = {c.label for c in _api_app_configs()}
    for model in NON_TENANT_ALLOWLIST:
        assert model._meta.app_label in api_labels
        assert not issubclass(
            model, TenantOwnedModel
        ), f"{model._meta.label} is tenant-owned; remove it from the allowlist"


def _api_app_configs() -> list[Any]:
    return [c for c in apps.get_app_configs() if c.name.startswith("uadas_api.")]


# ------------------------------------------------------ structure of each model


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_organization_fk_is_non_null_indexed_and_protected(
    model: type[TenantOwnedModel],
) -> None:
    field = model._meta.get_field("organization")
    assert isinstance(field, models.ForeignKey)
    assert field.remote_field.model is Organization
    assert field.null is False
    assert field.remote_field.on_delete is models.PROTECT
    assert field.remote_field.related_name == "+"
    assert field.remote_field.hidden


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_default_manager_is_the_tenant_manager(model: type[TenantOwnedModel]) -> None:
    assert isinstance(model._default_manager, TenantManager)
    assert isinstance(model.objects, TenantManager)


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_primary_key_is_a_uuid(model: type[TenantOwnedModel]) -> None:
    assert isinstance(model._meta.pk, models.UUIDField)


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_no_field_is_globally_unique(model: type[TenantOwnedModel]) -> None:
    """``unique=True`` on a tenant model would make a value unique *across* tenants."""
    globally_unique = [
        f.name for f in model._meta.concrete_fields if f.unique and not f.primary_key
    ]
    assert (
        not globally_unique
    ), f"{model._meta.label} has global uniques: {globally_unique}"


@pytest.mark.parametrize(("model", "constraint"), UNIQUE_CASES, ids=UNIQUE_IDS)
def test_unique_constraints_are_scoped_to_a_tenant(
    model: type[TenantOwnedModel], constraint: models.UniqueConstraint
) -> None:
    tenant_scoped = {"organization"} | {f.name for f in tenant_fk_fields(model)}
    assert tenant_scoped & set(constraint.fields), (
        f"{constraint.name} on {model._meta.label} names no tenant-scoped field, so "
        "its values would be unique across all organizations"
    )


# --------------------------------------------------------------------- behaviour


@pytest.mark.django_db
@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_for_organization_never_returns_another_tenants_rows(
    model: type[TenantOwnedModel],
) -> None:
    factory = factory_for(model)
    org_a, org_b = make_organization(), make_organization()
    mine = [factory.create(org_a), factory.create(org_a)]
    theirs = [factory.create(org_b)]

    seen_a = _ids(model.objects.for_organization(org_a))
    seen_b = _ids(model.objects.for_organization(org_b))

    assert {o.pk for o in mine} <= seen_a
    assert not seen_a & {o.pk for o in theirs}
    assert {o.pk for o in theirs} <= seen_b
    assert not seen_b & {o.pk for o in mine}
    # by primary key as well as by instance
    assert _ids(model.objects.for_organization(org_a.pk)) == seen_a


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_cross_tenant_fk_is_rejected_on_save(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    related = model._meta.get_field(field_name).related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    org_a, org_b = make_organization(), make_organization()
    foreign = factory_for(related).create(org_b)
    obj = factory_for(model).build(org_a, **{field_name: foreign})
    with pytest.raises(TenantIsolationError):
        obj.save()
    assert not model.objects.filter(pk=obj.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_cross_tenant_fk_is_rejected_on_bulk_create(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    related = model._meta.get_field(field_name).related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    org_a, org_b = make_organization(), make_organization()
    foreign = factory_for(related).create(org_b)
    good = factory_for(model).build(org_a)
    bad = factory_for(model).build(org_a, **{field_name: foreign})
    with pytest.raises(TenantIsolationError):
        model.objects.bulk_create([good, bad])
    # the whole batch is refused: nothing was written
    assert not model.objects.filter(pk__in=[good.pk, bad.pk]).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_cross_tenant_fk_is_rejected_on_queryset_update(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    related = model._meta.get_field(field_name).related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    org_a, org_b = make_organization(), make_organization()
    row = factory_for(model).create(org_a)
    foreign = factory_for(related).create(org_b)
    original = getattr(row, f"{field_name}_id")

    for value in (foreign, foreign.pk):
        with pytest.raises(TenantIsolationError):
            model.objects.filter(pk=row.pk).update(**{field_name: value})
    row.refresh_from_db()
    assert getattr(row, f"{field_name}_id") == original

    # a same-organization target is still allowed
    sibling = factory_for(related).create(org_a)
    assert model.objects.filter(pk=row.pk).update(**{field_name: sibling}) == 1


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_cross_tenant_fk_is_rejected_on_bulk_update(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    related = model._meta.get_field(field_name).related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    org_a, org_b = make_organization(), make_organization()
    row = factory_for(model).create(org_a)
    foreign = factory_for(related).create(org_b)
    setattr(row, field_name, foreign)
    with pytest.raises(TenantIsolationError):
        model.objects.bulk_update([row], [field_name])


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_same_tenant_fk_is_accepted_on_every_write_path(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    """The guard must not be a false positive: legitimate same-organization writes pass."""
    related = model._meta.get_field(field_name).related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    org = make_organization()
    factory, parents = factory_for(model), factory_for(related)

    row = factory.create(org)
    via_save = parents.create(org)
    setattr(row, field_name, via_save)
    row.save()
    assert getattr(model.objects.get(pk=row.pk), f"{field_name}_id") == via_save.pk

    via_bulk_update = parents.create(org)
    setattr(row, field_name, via_bulk_update)
    model.objects.bulk_update([row], [field_name])
    assert (
        getattr(model.objects.get(pk=row.pk), f"{field_name}_id") == via_bulk_update.pk
    )

    via_update = parents.create(org)
    assert model.objects.filter(pk=row.pk).update(**{field_name: via_update}) == 1
    assert getattr(model.objects.get(pk=row.pk), f"{field_name}_id") == via_update.pk

    created = factory.build(org, **{field_name: parents.create(org)})
    model.objects.bulk_create([created])
    assert model.objects.filter(pk=created.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "constraint"), UNIQUE_CASES, ids=UNIQUE_IDS)
def test_uniqueness_is_per_organization(
    model: type[TenantOwnedModel], constraint: models.UniqueConstraint
) -> None:
    factory = factory_for(model)
    org_a, org_b = make_organization(), make_organization()
    first = factory.create(org_a)

    fields = [f for f in constraint.fields if f != "organization"]
    scalars = {
        n: getattr(first, n) for n in fields if not model._meta.get_field(n).is_relation
    }
    # the same scalar values in another organization are fine ...
    factory.create(org_b, **scalars)
    # ... and a true duplicate inside one organization is not
    duplicate = {n: getattr(first, n) for n in fields}
    with pytest.raises(IntegrityError), transaction.atomic():
        factory.create(org_a, **duplicate)


@pytest.mark.django_db
@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_an_organization_that_owns_rows_cannot_be_deleted(
    model: type[TenantOwnedModel],
) -> None:
    from django.db.models import ProtectedError

    org = make_organization()
    factory_for(model).create(org)
    with pytest.raises(ProtectedError):
        org.delete()
    assert Organization.objects.filter(pk=org.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_organization_of_a_saved_row_cannot_be_changed(
    model: type[TenantOwnedModel],
) -> None:
    org_a, org_b = make_organization(), make_organization()
    row = factory_for(model).create(org_a)

    # An append-only model (the audit log) refuses *any* change, which is stricter and
    # equally correct; every other model must refuse specifically on tenancy grounds.
    refused = (TenantIsolationError, AuditLogImmutableError)

    row.organization = org_b
    with pytest.raises(refused):
        row.save()

    loaded = model.objects.get(pk=row.pk)
    loaded.organization = org_b
    with pytest.raises(refused):
        loaded.save()

    for key in ("organization", "organization_id"):
        value = org_b if key == "organization" else org_b.pk
        with pytest.raises(refused):
            model.objects.filter(pk=row.pk).update(**{key: value})
    assert model.objects.get(pk=row.pk).organization_id == org_a.pk


# ----------------------------------------------- review hardening (discovery-based)

# An append-only model (the audit log) refuses *any* change, which is stricter and
# equally correct; every other model must refuse specifically on tenancy grounds.
REFUSED = (TenantIsolationError, AuditLogImmutableError)


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_organization_is_covered_by_exactly_one_index(
    model: type[TenantOwnedModel],
) -> None:
    field = model._meta.get_field("organization")
    own_index = bool(field.db_index)  # type: ignore[attr-defined]
    composite = "organization" in _leading_fields(model)
    assert (
        own_index or composite
    ), f"{model._meta.label}: organization has no index at all"
    assert not (
        own_index and composite
    ), f"{model._meta.label}: the organization FK index duplicates a composite index"


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_no_foreign_key_index_duplicates_a_composite_or_unique_index(
    model: type[TenantOwnedModel],
) -> None:
    leading = _leading_fields(model)
    redundant = [
        f.name
        for f in model._meta.concrete_fields
        if isinstance(f, models.ForeignKey)
        and f.db_index  # type: ignore[attr-defined]
        and f.name in leading
    ]
    assert not redundant, f"{model._meta.label}: redundant FK indexes on {redundant}"


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_tenant_models_have_no_many_to_many_fields(
    model: type[TenantOwnedModel],
) -> None:
    # A through table is a model-less write path that would bypass every guard here.
    assert not model._meta.many_to_many


def test_fk_discovery_agrees_with_an_independent_enumeration() -> None:
    """The harness and the guard both use ``tenant_fk_fields``; cross-check it.

    ``_meta.get_fields()`` enumerates relations by a different route, so a bug in
    ``tenant_fk_fields`` (a field kind it misses) cannot hide from both at once.
    """
    independent = {
        (m._meta.label, f.name)
        for m in TENANT_MODELS
        for f in m._meta.get_fields()
        if f.is_relation
        and f.concrete
        and (f.many_to_one or f.one_to_one)
        and isinstance(f.related_model, type)
        and issubclass(f.related_model, TenantOwnedModel)
    }
    guarded = {
        (m._meta.label, f.name) for m in TENANT_MODELS for f in tenant_fk_fields(m)
    }
    assert independent == guarded
    assert independent == {(m._meta.label, name) for m, name in FK_CASES}
    assert independent, "the cross-check found no tenant foreign keys at all"


@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_base_manager_is_the_tenant_manager(model: type[TenantOwnedModel]) -> None:
    """Django's own related-manager and refresh paths use ``_base_manager``.

    If it were a plain ``Manager`` they would bypass every guard on the queryset.
    """
    assert model._meta.base_manager_name == "objects"
    assert isinstance(model._base_manager, TenantManager)
    assert isinstance(model._base_manager.all(), type(model.objects.all()))


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_related_manager_add_cannot_reparent_another_tenants_row(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    field = model._meta.get_field(field_name)
    related = field.related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    accessor = field.remote_field.get_accessor_name()  # type: ignore[union-attr]
    assert accessor and not accessor.endswith("+")
    org_a, org_b = make_organization(), make_organization()
    parent_a = factory_for(related).create(org_a)
    child_b = factory_for(model).create(org_b)
    original = getattr(child_b, f"{field_name}_id")

    with pytest.raises(TenantIsolationError):
        getattr(parent_a, accessor).add(child_b)

    child_b.refresh_from_db()
    assert getattr(child_b, f"{field_name}_id") == original


@pytest.mark.django_db
@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_bulk_create_upsert_is_refused(model: type[TenantOwnedModel]) -> None:
    """``update_conflicts`` would overwrite (or re-parent) another tenant's row by id."""
    org_a, org_b = make_organization(), make_organization()
    victim = factory_for(model).create(org_b)
    attacker = factory_for(model).build(org_a, id=victim.pk)
    writable = next(
        f.name
        for f in model._meta.concrete_fields
        if not f.primary_key and f.name != "organization"
    )
    with pytest.raises(TenantIsolationError):
        model.objects.bulk_create(
            [attacker],
            update_conflicts=True,
            unique_fields=["id"],
            update_fields=[writable],
        )
    with pytest.raises(TenantIsolationError):  # the positional spelling
        model.objects.bulk_create([attacker], None, False, True, [writable], ["id"])
    assert model.objects.get(pk=victim.pk).organization_id == org_b.pk

    # ignore_conflicts only skips the clashing row; it can overwrite nothing
    model.objects.bulk_create([attacker], ignore_conflicts=True)
    assert model.objects.get(pk=victim.pk).organization_id == org_b.pk


@pytest.mark.django_db
@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_saving_a_new_instance_with_another_tenants_id_cannot_overwrite_it(
    model: type[TenantOwnedModel],
) -> None:
    org_a, org_b = make_organization(), make_organization()
    victim = factory_for(model).create(org_b)
    attacker = factory_for(model).build(org_a, id=victim.pk)
    with pytest.raises((IntegrityError, *REFUSED)), transaction.atomic():
        attacker.save()
    assert model.objects.get(pk=victim.pk).organization_id == org_b.pk


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_bulk_update_cannot_change_organization_and_a_link_together(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    """Moving the row's own organization *and* its FK to match defeats a naive FK check."""
    related = model._meta.get_field(field_name).related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    org_a, org_b = make_organization(), make_organization()
    row = factory_for(model).create(org_a)
    foreign = factory_for(related).create(org_b)

    row.organization_id = org_b.pk
    setattr(row, field_name, foreign)
    with pytest.raises(REFUSED):
        model.objects.bulk_update([row], [field_name])
    with pytest.raises(REFUSED):
        row.save()
    assert model.objects.get(pk=row.pk).organization_id == org_a.pk


@pytest.mark.django_db
@pytest.mark.parametrize("model", TENANT_MODELS, ids=MODEL_IDS)
def test_organization_cannot_change_on_a_deferred_load(
    model: type[TenantOwnedModel],
) -> None:
    """``.only()`` leaves ``organization_id`` unloaded, so there is nothing to compare to."""
    org_a, org_b = make_organization(), make_organization()
    row = factory_for(model).create(org_a)

    loaded = model.objects.only("id").get(pk=row.pk)
    assert "organization_id" not in loaded.__dict__
    loaded.organization_id = org_b.pk
    with pytest.raises(REFUSED):
        loaded.save()
    assert model.objects.get(pk=row.pk).organization_id == org_a.pk


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "field_name"), FK_CASES, ids=FK_IDS)
def test_bulk_update_checks_organization_on_a_deferred_load(
    model: type[TenantOwnedModel], field_name: str
) -> None:
    related = model._meta.get_field(field_name).related_model
    assert isinstance(related, type) and issubclass(related, TenantOwnedModel)
    org_a, org_b = make_organization(), make_organization()
    row = factory_for(model).create(org_a)
    foreign = factory_for(related).create(org_b)

    loaded = model.objects.only("id", field_name).get(pk=row.pk)
    loaded.organization_id = org_b.pk
    setattr(loaded, field_name, foreign)
    with pytest.raises(REFUSED):
        model.objects.bulk_update([loaded], [field_name])
    assert model.objects.get(pk=row.pk).organization_id == org_a.pk


# Plain-UUID references to another tenant row (DatasetRecord.parent_dataset_id).


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "name"), SOFT_CASES, ids=SOFT_IDS)
def test_a_plain_uuid_reference_may_not_point_into_another_tenant(
    model: type[TenantOwnedModel], name: str
) -> None:
    target = apps.get_model(model.soft_tenant_refs[name])
    assert issubclass(target, TenantOwnedModel)
    org_a, org_b = make_organization(), make_organization()
    foreign = factory_for(target).create(org_b)

    bad = factory_for(model).build(org_a, **{name: foreign.pk})
    with pytest.raises(TenantIsolationError):
        bad.save()
    with pytest.raises(TenantIsolationError):
        model.objects.bulk_create([bad])

    row = factory_for(model).create(org_a)
    for value in (foreign.pk, str(foreign.pk)):
        with pytest.raises(TenantIsolationError):
            model.objects.filter(pk=row.pk).update(**{name: value})
    setattr(row, name, foreign.pk)
    with pytest.raises(TenantIsolationError):
        model.objects.bulk_update([row], [name])
    with pytest.raises(TenantIsolationError):
        row.save()
    assert getattr(model.objects.get(pk=row.pk), name) != foreign.pk


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "name"), SOFT_CASES, ids=SOFT_IDS)
def test_a_plain_uuid_reference_may_be_dangling_or_same_tenant(
    model: type[TenantOwnedModel], name: str
) -> None:
    """Orphaned lineage is normal (the core's non-cascade rule); only cross-tenant is wrong."""
    target = apps.get_model(model.soft_tenant_refs[name])
    org = make_organization()
    sibling = factory_for(target).create(org)

    factory_for(model).create(org, **{name: uuid.uuid4()})  # parent never existed
    same_tenant = factory_for(model).create(org, **{name: sibling.pk})
    assert getattr(model.objects.get(pk=same_tenant.pk), name) == sibling.pk
    model.objects.bulk_create([factory_for(model).build(org, **{name: sibling.pk})])
    assert model.objects.filter(pk=same_tenant.pk).update(**{name: uuid.uuid4()}) == 1


# ------------------------------------------------ storage keys (where a model has one)

STORAGE_KEY_MODELS = [m for m in TENANT_MODELS if m.storage_key_field is not None]
STORAGE_KEY_IDS = [m._meta.label for m in STORAGE_KEY_MODELS]


def _bad_keys(other_org_id: Any) -> list[str]:
    return [
        "no-prefix/file.parquet",
        f"{other_org_id}/file.parquet",  # another tenant's prefix
        "file.parquet",
        "/absolute.parquet",
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("model", STORAGE_KEY_MODELS, ids=STORAGE_KEY_IDS)
def test_storage_key_prefix_is_enforced_on_every_write_path(
    model: type[TenantOwnedModel],
) -> None:
    from django.core.exceptions import ValidationError

    org_a, org_b = make_organization(), make_organization()
    field = model.storage_key_field
    assert field is not None
    good_key = f"{org_a.pk}/objects/{uuid.uuid4()}"
    good = factory_for(model).create(org_a, **{field: good_key})
    assert getattr(model.objects.get(pk=good.pk), field) == good_key

    for bad in _bad_keys(org_b.pk):
        row = factory_for(model).build(org_a, **{field: bad})
        with pytest.raises(ValidationError):
            row.save()
        with pytest.raises(ValidationError) as excinfo:
            row.full_clean()
        assert field in excinfo.value.error_dict  # reported against the field itself
        with pytest.raises(ValidationError):
            model.objects.bulk_create([row])

        changed = model.objects.get(pk=good.pk)
        setattr(changed, field, bad)
        with pytest.raises(ValidationError):
            changed.save()
        with pytest.raises(ValidationError):
            model.objects.bulk_update([changed], [field])
        with pytest.raises(ValidationError):
            model.objects.filter(pk=good.pk).update(**{field: bad})

    # the failed attempts changed nothing
    assert getattr(model.objects.get(pk=good.pk), field) == good_key
