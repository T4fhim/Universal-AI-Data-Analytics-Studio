# File: apps/api/uadas_api/tenancy.py
"""Tenant ownership for every row the API stores, and the invariants that keep tenants apart.

Why this module exists (and is not an app): the product is multi-tenant, so a row must
never be readable, writable or *linkable* across organizations. Rather than hope each
model author remembers, every tenant-scoped model inherits :class:`TenantOwnedModel`,
which supplies a non-null ``organization`` foreign key and enforces these rules:

1. **Every foreign key from a tenant row to another tenant row points at the same
   organization.** The same applies to the plain-UUID references a model declares in
   ``soft_tenant_refs`` (``DatasetRecord.parent_dataset_id``): a reference may dangle --
   the core allows orphaned lineage -- but it may not point *into another tenant*.
2. **``organization`` is immutable once a row is saved**, as are any other fields a model
   lists in ``immutable_fields`` (``Membership.user`` / ``.organization``). Re-parenting a
   row would silently invalidate every row that references it. The check compares the
   value being written with the value the row was loaded with, and with a deferred load
   (``.only()``) it fetches the stored value instead of assuming it.
3. **``bulk_create(update_conflicts=True)`` is refused on every tenant model.** An upsert
   keyed on ``id`` would overwrite -- or re-parent -- another tenant's row.
4. **An object-store key lives under ``"<organization_id>/"``** (:func:`validate_storage_key`).

These are enforced in Python on ``save()``, ``bulk_create()``, ``bulk_update()`` and
``queryset.update()``, *and on* ``_base_manager``: every tenant model sets
``base_manager_name = "objects"``, because Django's related managers (``project.datasets
.add(row)``), ``refresh_from_db`` and the delete collector use ``_base_manager``, which
would otherwise be a plain ``Manager`` that skips every guard. Violations raise
:class:`TenantIsolationError` (or :class:`ImmutableFieldError`), ``ValidationError``
subclasses, so API layers can turn them into a 4xx without special casing.

What this does **not** cover -- stated plainly, because a false sense of isolation is
worse than none:

* **No database enforcement.** The rules are application-level. A *composite* foreign key
  ``(organization_id, project_id) -> (organization_id, id)``, which would make Postgres
  enforce them, is not expressible in Django's ORM or migrations, so none is declared.
  Raw SQL, ``QuerySet._raw_delete``, ``cursor.execute``, ``loaddata`` of a hand-written
  fixture, a psql session or another service writing to the same database all bypass it.
  Row-level security or a trigger is the way to close that gap; out of scope for 3.2.
* **JSON fields that carry ids are unvalidated** (``ChartSpec.spec``, ``Dashboard.layout``,
  ``PipelineNode.payload``, ``Recipe.definition``, ``Report.config``). A dataset id inside
  one can name another tenant's dataset. Every reader MUST resolve such ids through
  ``for_organization`` -- never ``Model.objects.get(pk=id_from_json)``.
* ``update()`` is checked only when the new value is a model instance or a primary key;
  an expression (``F(...)``, ``Subquery``) assigned to a tenant reference is refused.
* A check-then-write race exists between the lookup of the target row and the write. It
  cannot be exploited through this API because ``organization`` is immutable, but a
  concurrent raw-SQL re-parent would not be noticed.
* Two rows of one organization are not checked for agreeing on *project* (an edge whose
  endpoints sit in different projects passes): data integrity, not tenancy.
* Many-to-many fields are not supported on tenant models (a through table is a write path
  the guards cannot see); the isolation harness fails if one appears.

The cost: one ``SELECT`` per tenant reference per ``save()`` (none when the related object
is cached on the instance), one per reference per ``bulk_*`` batch, and one extra
``SELECT`` when an immutable field is written on a deferred load.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Collection, Iterable, Sequence
from contextvars import ContextVar
from typing import Any, ClassVar, Self, TypeVar

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

# A reference to an organization as callers naturally hold it: the row, or its key.
OrganizationRef = models.Model | uuid.UUID | str

_UUID = models.UUIDField()

# One path segment of a storage key: ASCII letters, digits, dot, underscore, hyphen.
_KEY_SEGMENT = re.compile(r"[A-Za-z0-9._-]+")


class TenantIsolationError(ValidationError):
    """A write would let one organization's rows reference or alter another's."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="tenant_isolation")


class ImmutableFieldError(ValidationError):
    """A write would change a field that is fixed once its row is saved."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="immutable_field")


def _same_id(left: Any, right: Any) -> bool:
    """Compare two primary keys that may be a ``UUID`` or its string form."""
    return bool(_UUID.to_python(left) == _UUID.to_python(right))


def _org_pk(organization: OrganizationRef) -> Any:
    return organization.pk if isinstance(organization, models.Model) else organization


def tenant_fk_fields(model: type[models.Model]) -> list[Any]:
    """Return ``model``'s concrete foreign keys that point at another tenant-owned model.

    ``organization`` itself is excluded (it points at ``Organization``, not a tenant
    model). The result drives both the write-time check and the test harness (which
    cross-checks it against an independent enumeration).
    """
    return [
        field
        for field in model._meta.concrete_fields
        if isinstance(field, models.ForeignKey)
        and isinstance(field.related_model, type)
        and issubclass(field.related_model, TenantOwnedModel)
    ]


def iter_tenant_models() -> list[type[TenantOwnedModel]]:
    """Return every concrete :class:`TenantOwnedModel` in the loaded apps.

    Used by the isolation test harness: discovery, not a hand-kept list, so a new tenant
    model is covered the moment it exists.
    """
    return [m for m in apps.get_models() if issubclass(m, TenantOwnedModel)]


def _target_organizations(target: type[models.Model], ids: set[Any]) -> dict[Any, Any]:
    """Map each existing target primary key to its organization id (one query)."""
    return dict(
        target._base_manager.filter(pk__in=ids).values_list("pk", "organization_id")
    )


def _cross_tenant(model: type[models.Model], field_name: str) -> TenantIsolationError:
    # Deliberately names no ids: the message may reach a caller who must not learn that
    # the foreign row exists.
    return TenantIsolationError(
        f"{model._meta.label}.{field_name} must reference a row of the same organization"
    )


def _immutable_error(model: type[models.Model], attname: str) -> ValidationError:
    name = model._meta.get_field(attname).name
    message = f"{model._meta.label}.{name} is immutable once a row is saved"
    if attname == "organization_id" and issubclass(model, TenantOwnedModel):
        return TenantIsolationError(message)
    return ImmutableFieldError(message)


def assert_same_tenant(
    model: type[TenantOwnedModel],
    objs: Sequence[TenantOwnedModel],
    names: Collection[str] | None = None,
) -> None:
    """Raise :class:`TenantIsolationError` if any tenant reference of ``objs`` crosses organizations.

    Covers foreign keys and ``soft_tenant_refs``. ``names`` restricts the check to those
    fields (``update_fields`` / ``bulk_update``); ``None`` checks them all. A reference
    that was never loaded (a deferred field) is not being written and is skipped. A target
    row that does not exist is skipped here: for a foreign key the database's own
    constraint reports it, and for a soft reference a dangling id is legal.
    """
    for obj in objs:
        if "organization_id" in obj.__dict__ and obj.organization_id is None:
            raise TenantIsolationError(
                f"{model._meta.label}: a tenant-owned row needs an organization"
            )
    for field in tenant_fk_fields(model):
        if names is not None and field.name not in names and field.attname not in names:
            continue
        unresolved: list[tuple[TenantOwnedModel, Any]] = []
        for obj in objs:
            target_id = obj.__dict__.get(field.attname)
            if target_id is None:
                continue
            cached = field.get_cached_value(obj, None)
            if cached is not None and _same_id(cached.pk, target_id):
                if not _same_id(cached.organization_id, obj.organization_id):
                    raise _cross_tenant(model, field.name)
                continue
            unresolved.append((obj, target_id))
        if not unresolved:
            continue
        found = _target_organizations(
            field.related_model, {_UUID.to_python(t) for _, t in unresolved}
        )
        for obj, target_id in unresolved:
            org_id = found.get(_UUID.to_python(target_id))
            if org_id is not None and not _same_id(org_id, obj.organization_id):
                raise _cross_tenant(model, field.name)
    for name, label in model.soft_tenant_refs.items():
        if names is not None and name not in names:
            continue
        pending = [(o, o.__dict__[name]) for o in objs if o.__dict__.get(name)]
        if not pending:
            continue
        found = _target_organizations(
            apps.get_model(label), {_UUID.to_python(v) for _, v in pending}
        )
        for obj, value in pending:
            org_id = found.get(_UUID.to_python(value))
            if org_id is not None and not _same_id(org_id, obj.organization_id):
                raise _cross_tenant(model, name)


def assert_unchanged(model: type[models.Model], objs: Sequence[models.Model]) -> None:
    """Raise if any saved row in ``objs`` now holds a different value in an immutable field.

    Always checks the in-memory values, whatever is being written: a foreign-key check
    compares against the row's *in-memory* organization, so an organization changed in
    memory must be caught even when the write itself only names another field.

    A field that was never loaded cannot have been changed (skipped). One that was
    assigned on a deferred load has no recorded original, so the stored value is fetched
    (one query for the whole batch) and compared.
    """
    attnames: tuple[str, ...] = getattr(model, "immutable_fields", ())
    if not attnames:
        return
    unknown: list[models.Model] = []
    for obj in objs:
        if obj._state.adding:
            continue
        originals: dict[str, Any] = getattr(obj, "_original_immutable", {})
        for att in attnames:
            current = obj.__dict__.get(att)
            if current is None:
                continue
            original = originals.get(att)
            if original is None:
                unknown.append(obj)
                break
            if not _same_id(original, current):
                raise _immutable_error(model, att)
    if not unknown:
        return
    rows = {
        row[0]: row[1:]
        for row in model._base_manager.filter(
            pk__in=[o.pk for o in unknown]
        ).values_list("pk", *attnames)
    }
    for obj in unknown:
        stored = rows.get(obj.pk)
        if stored is None:
            continue
        for att, stored_value in zip(attnames, stored, strict=True):
            current = obj.__dict__.get(att)
            if (
                current is not None
                and stored_value is not None
                and not _same_id(stored_value, current)
            ):
                raise _immutable_error(model, att)


def validate_storage_key(
    organization_id: Any, key: str, *, allow_blank: bool = False
) -> None:
    """Require an object-store key to live under ``"<organization_id>/"`` and be plain.

    Why: storage keys are the only thing separating tenants' files in a shared bucket, so
    the prefix is enforced rather than conventional. After the prefix, every ``/``-separated
    segment must be non-empty, match ``[A-Za-z0-9._-]+`` (so no percent-encoding, spaces,
    control characters, backslashes or Unicode lookalikes), not be ``.`` or ``..``, and not
    end with ``.`` (some filesystems and stores strip trailing dots, turning ``a.`` into
    ``a`` and ``..`` into a traversal). A bare prefix with nothing after it is refused.
    Treat a key as an opaque object name: never join it into a filesystem path without the
    storage backend's own sanitising.

    Raises :class:`~django.core.exceptions.ValidationError` keyed on ``storage_key`` so it
    surfaces from both ``full_clean()`` and ``save()``.
    """
    if key == "":
        if allow_blank:
            return
        raise ValidationError({"storage_key": "This field is required."})
    prefix = f"{_UUID.to_python(organization_id)}/"
    rest = key[len(prefix) :]
    segments = rest.split("/")
    if (
        not key.startswith(prefix)
        or not rest
        or any(
            _KEY_SEGMENT.fullmatch(s) is None or s in {".", ".."} or s.endswith(".")
            for s in segments
        )
    ):
        raise ValidationError(
            {
                "storage_key": (
                    f"Must start with {prefix!r}, followed by non-empty segments of "
                    "letters, digits, '.', '_' and '-' (no '.', '..' or trailing dots)."
                )
            }
        )


_T = TypeVar("_T", bound=models.Model)
_M = TypeVar("_M", bound="TenantOwnedModel")

# Django implements ``bulk_update`` by calling ``queryset.update()`` with ``Case``/``When``
# expressions, which :meth:`TenantQuerySet.update` must refuse (it cannot verify an
# expression). ``bulk_update`` has *already* verified every object it was given, so it
# raises this flag around the delegation; the inner ``update()`` then stands aside. A
# ContextVar rather than an instance attribute because Django clones the queryset before
# calling ``update()``, and so that concurrent async tasks cannot see each other's flag.
_BULK_UPDATE_VALIDATED: ContextVar[bool] = ContextVar(
    "uadas_tenant_bulk_update_validated", default=False
)


def _reject_immutable_names(model: type[models.Model], names: Iterable[str]) -> None:
    immutable: tuple[str, ...] = getattr(model, "immutable_fields", ())
    for name in names:
        attname = getattr(model._meta.get_field(name), "attname", None)
        if attname in immutable:
            raise _immutable_error(model, attname)


class ImmutableFieldsQuerySet(models.QuerySet[_T]):
    """A queryset that refuses to write a model's ``immutable_fields``."""

    def update(self, **kwargs: Any) -> int:
        _reject_immutable_names(self.model, kwargs)
        return super().update(**kwargs)

    def bulk_update(
        self,
        objs: Iterable[_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        batch, names = list(objs), list(fields)
        _reject_immutable_names(self.model, names)
        assert_unchanged(self.model, batch)
        return super().bulk_update(batch, names, batch_size)


class ImmutableFieldsManager(models.Manager[_T]):
    """Manager whose querysets are :class:`ImmutableFieldsQuerySet`."""

    def get_queryset(self) -> ImmutableFieldsQuerySet[_T]:
        return ImmutableFieldsQuerySet(self.model, using=self._db)


class ImmutableFieldsModel(models.Model):
    """Abstract base: fields named in ``immutable_fields`` cannot change once saved.

    ``immutable_fields`` lists *attnames* (``"user_id"``). The value each had when the row
    was constructed (which is when it is loaded: ``from_db`` builds through ``__init__``)
    or last saved is remembered; ``save()`` and the querysets compare against it.
    Recorded in ``__init__`` rather than by overriding ``from_db`` because ``from_db``'s
    signature changed in Django 6.1 (``fetch_mode``) and 6.0 is supported too.
    """

    immutable_fields: ClassVar[tuple[str, ...]] = ()

    objects: ImmutableFieldsManager[Any] = ImmutableFieldsManager()

    class Meta:
        abstract = True
        # Related managers, refresh_from_db and the delete collector use _base_manager;
        # make it this manager so the guards apply there too.
        base_manager_name = "objects"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._remember_immutable()

    def _remember_immutable(self) -> None:
        # A deferred field is absent from __dict__ and records None (no comparison).
        self._original_immutable: dict[str, Any] = {
            att: self.__dict__.get(att) for att in self.immutable_fields
        }

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        assert_unchanged(type(self), [self])
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )
        self._remember_immutable()


class TenantQuerySet(ImmutableFieldsQuerySet[_M]):
    """A queryset that scopes by organization and refuses cross-tenant writes."""

    def for_organization(self, organization: OrganizationRef) -> Self:
        """Restrict to one organization's rows. The only sanctioned way to list tenant data."""
        return self.filter(organization_id=_org_pk(organization))

    def bulk_create(
        self,
        objs: Iterable[_M],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_M]:
        if update_conflicts:
            raise TenantIsolationError(
                f"{self.model._meta.label}: bulk_create(update_conflicts=True) is not "
                "allowed on tenant models; an upsert keyed on id can overwrite or "
                "re-parent another organization's row"
            )
        batch = list(objs)
        assert_same_tenant(self.model, batch)
        for obj in batch:
            obj.check_tenant_invariants()  # bulk_create bypasses save()
        return super().bulk_create(
            batch,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )

    def bulk_update(
        self,
        objs: Iterable[_M],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        batch, names = list(objs), list(fields)
        # Immutable fields first, so a re-parented row reports *that*, not whatever the
        # other checks make of its changed organization. (ImmutableFieldsQuerySet repeats
        # the check when delegating; it is free unless an immutable field was assigned on
        # a deferred load, where it costs one extra query.)
        _reject_immutable_names(self.model, names)
        assert_unchanged(self.model, batch)
        assert_same_tenant(self.model, batch, names=set(names))
        for obj in batch:
            obj.check_tenant_invariants()  # bulk_update bypasses save()
        token = _BULK_UPDATE_VALIDATED.set(True)
        try:
            return super().bulk_update(batch, names, batch_size)
        finally:
            _BULK_UPDATE_VALIDATED.reset(token)

    def update(self, **kwargs: Any) -> int:
        """``QuerySet.update`` that cannot move rows between tenants.

        ``organization`` (and any other immutable field) may not be assigned. A tenant
        reference -- foreign key or ``soft_tenant_refs`` -- may only be assigned a row (or
        key) of the organization of *every* row being updated; anything else, including
        an unverifiable expression, raises. A storage key must keep its organization
        prefix.
        """
        if _BULK_UPDATE_VALIDATED.get():
            return super().update(**kwargs)  # bulk_update's own, already-verified call
        fk_targets = {f.name: f.related_model for f in tenant_fk_fields(self.model)}
        for key, value in kwargs.items():
            field = self.model._meta.get_field(key)
            if field.name == self.model.storage_key_field:
                self._check_storage_key_update(value)
                continue
            if value is None:
                continue
            if field.name in fk_targets:
                self._check_reference_update(field.name, fk_targets[field.name], value)
            elif field.name in self.model.soft_tenant_refs:
                target = apps.get_model(self.model.soft_tenant_refs[field.name])
                self._check_reference_update(field.name, target, value)
        return super().update(**kwargs)

    def _check_reference_update(
        self, name: str, target: type[models.Model], value: Any
    ) -> None:
        if hasattr(value, "resolve_expression"):
            raise TenantIsolationError(
                f"{self.model._meta.label}.{name}: cannot verify the organization of "
                "an expression; assign a row or its primary key"
            )
        pk = _UUID.to_python(value.pk if isinstance(value, models.Model) else value)
        target_org = _target_organizations(target, {pk}).get(pk)
        if target_org is not None and self.exclude(organization_id=target_org).exists():
            raise _cross_tenant(self.model, name)

    def _check_storage_key_update(self, value: Any) -> None:
        """Validate a storage key assigned by ``update()`` against every affected organization."""
        if hasattr(value, "resolve_expression"):
            raise TenantIsolationError(
                f"{self.model._meta.label}.{self.model.storage_key_field}: cannot verify "
                "an expression; assign the key itself"
            )
        for organization_id in self.values_list(
            "organization_id", flat=True
        ).distinct():
            validate_storage_key(
                organization_id, value, allow_blank=self.model.storage_key_may_be_blank
            )


class TenantManager(ImmutableFieldsManager[_M]):
    """Manager whose querysets are :class:`TenantQuerySet`."""

    def get_queryset(self) -> TenantQuerySet[_M]:
        return TenantQuerySet(self.model, using=self._db)

    def for_organization(self, organization: OrganizationRef) -> TenantQuerySet[_M]:
        return self.get_queryset().for_organization(organization)


class TenantOwnedModel(ImmutableFieldsModel):
    """Abstract base for every model whose rows belong to exactly one organization.

    Provides a UUID primary key (ids are non-enumerable), the non-null ``organization``
    foreign key -- ``PROTECT`` so an organization that still owns data cannot be deleted
    out from under it, ``related_name="+"`` so the organization does not grow a reverse
    accessor per table -- and the write-time rules described in the module docstring.

    The ``organization`` foreign key is declared ``db_index=False``: every query is
    organization-scoped, so each tenant model is expected to have an explicit index or
    unique constraint *leading with* ``organization`` instead (it serves the same lookups
    and more), and a duplicate index only slows writes. The isolation harness fails on a
    model with neither. A model with no such composite index can restore Django's own by
    redeclaring ``organization`` with ``db_index=True``.

    Concrete models declare ``class Meta(TenantOwnedModel.Meta)`` so ``base_manager_name``
    is inherited (a bare ``class Meta:`` silently drops it; the harness catches that).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="+",
        db_index=False,
    )

    objects: TenantManager[Any] = TenantManager()

    immutable_fields: ClassVar[tuple[str, ...]] = ("organization_id",)

    # Plain-UUID (non-FK) references to another tenant row: field name -> "app.Model".
    # They may dangle but may not point into another organization.
    soft_tenant_refs: ClassVar[dict[str, str]] = {}

    # Name of the field holding an object-store key, or None. When set, that field must
    # satisfy :func:`validate_storage_key` on every write path (save, bulk_create,
    # bulk_update, update, full_clean). ``storage_key_may_be_blank`` allows "no object yet".
    storage_key_field: ClassVar[str | None] = None
    storage_key_may_be_blank: ClassVar[bool] = False

    class Meta(ImmutableFieldsModel.Meta):
        abstract = True

    def check_tenant_invariants(self) -> None:
        """Per-row rules that depend on the organization; override to add more (call super)."""
        if self.storage_key_field is not None:
            validate_storage_key(
                self.organization_id,
                getattr(self, self.storage_key_field),
                allow_blank=self.storage_key_may_be_blank,
            )

    def clean(self) -> None:
        super().clean()
        self.check_tenant_invariants()

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        names = None if update_fields is None else set(update_fields)
        # Immutable fields first (see TenantQuerySet.bulk_update); ImmutableFieldsModel.save,
        # called below, repeats the check at no cost in the ordinary case.
        assert_unchanged(type(self), [self])
        assert_same_tenant(type(self), [self], names=names)
        self.check_tenant_invariants()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )
