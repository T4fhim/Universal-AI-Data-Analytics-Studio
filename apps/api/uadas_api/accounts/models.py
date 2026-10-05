# File: apps/api/uadas_api/accounts/models.py
"""Identity and tenancy primitives: ``User``, ``Organization``, ``Membership``, ``AuditEvent``.

Why these four live together: they are the only models that are about *who* and *which
tenant* rather than about analytics data, and the three non-audit ones are exactly the
models the tenant-isolation harness allowlists as not tenant-owned (they ARE the
tenancy). :class:`AuditEvent` is tenant-owned (it records what happened inside an
organization) and append-only.

Design points a later step must not undo:

* **UUID primary keys everywhere** -- ids appear in URLs and storage keys, so they must
  not be guessable or enumerable.
* **Email is the login name and is unique ignoring case.** The constraint is a
  functional ``UNIQUE (lower(email))``; ``unique=True`` on the column alone would be
  case-sensitive and let ``Ada@x.com`` and ``ada@x.com`` coexist (it is kept too, only
  because Django's ``auth.E003`` check demands it). ``get_by_natural_key`` looks up
  case-insensitively so ``authenticate()`` agrees with the constraint.
* ``AUTH_USER_MODEL`` points here (settings/base.py), set in the same change as the first
  migration because Django cannot swap the user model after migrations reference
  ``auth.User``.
* **The audit log is append-only in Python**, not in the database: ``save()`` on an
  existing row, ``delete()``, ``queryset.update()``/``delete()``/``bulk_update()`` raise
  :class:`AuditLogImmutableError`. Raw SQL, ``QuerySet._raw_delete`` and database
  administrators are not stopped by this; a Postgres trigger or revoked ``UPDATE``/
  ``DELETE`` privilege would be the enforcement that survives them (not in 3.2). The lock covers
  ``_base_manager`` too (``base_manager_name = "objects"``), which Django's related
  managers and delete collector use. The one sanctioned change is detaching ``actor`` when
  a user is deleted, done by the custom ``on_delete`` :func:`detach_actor` (not
  ``QuerySet.update``), so the event outlives the person who caused it. Because ``organization`` is ``PROTECT`` and events cannot be
  deleted, an organization with any audit history can never be deleted: deliberate.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Value
from django.db.models.base import ModelBase
from django.db.models.functions import Lower
from django.db.models.lookups import Exact
from django.utils import timezone

from uadas_api.tenancy import (
    ImmutableFieldsManager,
    ImmutableFieldsModel,
    ImmutableFieldsQuerySet,
    TenantManager,
    TenantOwnedModel,
    TenantQuerySet,
)


def normalise_email(email: str | None) -> str:
    """NFKC-normalise, trim, and lowercase the domain of an email address.

    NFKC folds canonically equivalent spellings (``e`` + combining acute vs ``é``) and
    compatibility forms (fullwidth letters) to one string, so they cannot coexist as
    distinct accounts; Django's own ``normalize_username`` does the same for the login
    name. The local part's case is preserved here and compared case-insensitively by the
    ``Lower`` constraint and :meth:`UserManager.by_email`.
    """
    return BaseUserManager.normalize_email(
        unicodedata.normalize("NFKC", (email or "").strip())
    )


def _assert_users_are_not_sole_owners(user_ids: Collection[uuid.UUID]) -> None:
    """Raise :class:`LastOwnerError` if deleting these users would orphan an organization.

    Deleting a user cascades to their memberships through Django's delete collector, which
    calls neither ``Membership.delete()`` nor the membership queryset, so the guard has to
    sit on the user as well. Must run inside :func:`_locked_organizations`.
    """
    owners = Membership.objects.filter(user_id__in=list(user_ids), role=Role.OWNER)
    _assert_owners_remain(
        _group_by_organization(owners.values_list("pk", "organization_id"))
    )


class UserQuerySet(models.QuerySet["User"]):
    """User queryset whose ``delete()`` cannot orphan an organization (see above)."""

    def delete(self) -> tuple[int, dict[str, int]]:
        ids = list(self.values_list("pk", flat=True))
        organizations = Membership.objects.filter(
            user_id__in=ids, role=Role.OWNER
        ).values_list("organization_id", flat=True)
        with _locked_organizations(organizations):
            _assert_users_are_not_sole_owners(ids)
            return super().delete()


class UserManager(BaseUserManager["User"]):
    """Creates users keyed on email; lookups by login name ignore case."""

    use_in_migrations = True

    def get_queryset(self) -> UserQuerySet:
        return UserQuerySet(self.model, using=self._db)

    def _create(self, email: str, password: str | None, **extra: Any) -> User:
        email = normalise_email(email)
        if not email:
            raise ValueError("A user must have an email address.")
        user = self.model(email=email, **extra)
        user.set_password(password)  # None -> an unusable password, never an empty one
        # Validate before writing: a malformed address or a case/Unicode twin of an
        # existing one becomes a ValidationError here, not a stored row or a bare
        # IntegrityError. The unique constraint remains the backstop for a race.
        user.full_clean()
        user.save(using=self._db)
        return user

    def create_user(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        for flag in ("is_staff", "is_superuser"):
            if extra_fields[flag] is not True:
                raise ValueError(f"A superuser must have {flag}=True.")
        return self._create(email, password, **extra_fields)

    def by_email(self, email: str | None) -> models.QuerySet[User]:
        """Users whose normalised email equals ``email`` ignoring case.

        Filters on ``LOWER(email) = LOWER(%s)`` -- the very expression of the
        ``uq_user_email_ci`` constraint, so Postgres can use that index and the lookup can
        never disagree with the constraint about what counts as the same address (both
        sides use the *database's* ``lower``, not Python's). ``email__iexact`` is
        deliberately avoided: on Postgres it compiles to ``UPPER(email) = UPPER(%s)``,
        which matches no index and folds some characters differently.
        """
        return self.filter(Exact(Lower("email"), Lower(Value(normalise_email(email)))))

    def get_by_natural_key(self, username: str | None) -> User:
        return self.by_email(username).get()


class User(AbstractBaseUser, PermissionsMixin):
    """A person who can sign in; belongs to organizations through :class:`Membership`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # unique=True is required by Django's auth.E003 check (it does not recognise a
    # functional constraint as making USERNAME_FIELD unique) and is the exact-case
    # guarantee; the case-insensitive rule is the Lower() constraint in Meta below. The
    # redundant exact-case index is the price of not silencing a system check.
    email = models.EmailField(max_length=254, unique=True)
    display_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects: UserManager = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("email"), name="uq_user_email_ci"),
        ]

    def __str__(self) -> str:
        return self.email

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Any = None,
    ) -> None:
        # Normalise on every path, not only through the manager, so an address assigned
        # directly (user.email = ...) cannot reintroduce a Unicode twin.
        if update_fields is None or "email" in update_fields:
            self.email = normalise_email(self.email)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Delete the user -- unless they are the only owner of some organization.

        Their memberships (and so their ownership) are removed with them, which would
        leave that organization ownerless; transfer ownership or retire the organization
        first. Organization offboarding is deferred, so for now a sole owner cannot be
        deleted at all. Their ``AuditEvent`` rows are detached, not deleted.
        """
        organizations = Membership.objects.filter(
            user_id=self.pk, role=Role.OWNER
        ).values_list("organization_id", flat=True)
        with _locked_organizations(organizations):
            _assert_users_are_not_sole_owners([self.pk])
            return super().delete(using=using, keep_parents=keep_parents)


class Organization(models.Model):
    """The tenant. Everything else a customer owns hangs off one of these."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=63, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    """A member's role within one organization (per-tenant, not global)."""

    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    EDITOR = "editor", "Editor"
    VIEWER = "viewer", "Viewer"


class LastOwnerError(ValidationError):
    """A change would leave an organization with no owner."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or "An organization must keep at least one owner.",
            code="last_owner",
        )


# Django implements ``bulk_update`` by calling ``queryset.update()`` with ``Case``/``When``
# expressions, which :meth:`MembershipQuerySet.update` must refuse (it cannot verify an
# expression). ``bulk_update`` has already checked every object it was given, so it raises
# this flag around the delegation. A ContextVar for the same reasons as the one in
# ``uadas_api.tenancy`` (the queryset is cloned; concurrent async tasks must not share it).
_BULK_ROLE_VALIDATED: ContextVar[bool] = ContextVar(
    "uadas_membership_bulk_role_validated", default=False
)


@contextmanager
def _locked_organizations(organization_ids: Iterable[uuid.UUID]) -> Iterator[None]:
    """Hold a transaction that has the given organizations' rows locked.

    Two admins demoting the two owners at the same moment must not both conclude "the
    other owner remains": the check and the write run under a row lock on the
    organization, in a fixed (sorted) order so two such transactions cannot deadlock.
    SQLite has no row locks (it serialises writers anyway), where Django omits the clause.
    """
    with transaction.atomic():
        ids = sorted(set(organization_ids))
        if ids:
            list(
                Organization.objects.select_for_update()
                .filter(pk__in=ids)
                .order_by("pk")
                .values_list("pk", flat=True)
            )
        yield


def _assert_owners_remain(leaving: Mapping[uuid.UUID, Collection[uuid.UUID]]) -> None:
    """Raise :class:`LastOwnerError` unless every organization keeps an owner.

    ``leaving`` maps an organization id to the ids of the *owner memberships* about to be
    demoted or removed. Call it inside :func:`_locked_organizations`.
    """
    for organization_id, membership_ids in leaving.items():
        remaining = (
            Membership.objects.filter(organization_id=organization_id, role=Role.OWNER)
            .exclude(pk__in=list(membership_ids))
            .exists()
        )
        if not remaining:
            raise LastOwnerError()


def _group_by_organization(
    rows: Iterable[tuple[uuid.UUID, uuid.UUID]],
) -> dict[uuid.UUID, set[uuid.UUID]]:
    grouped: dict[uuid.UUID, set[uuid.UUID]] = {}
    for membership_id, organization_id in rows:
        grouped.setdefault(organization_id, set()).add(membership_id)
    return grouped


class MembershipQuerySet(ImmutableFieldsQuerySet["Membership"]):
    """Membership queryset that refuses to leave an organization without an owner.

    Guards ``update(role=...)``, ``delete()`` and ``bulk_update(..., ["role"])`` -- and so
    related-manager calls too, since ``Membership`` uses this manager as its base manager.
    Not covered (like every Python-level guard here): ``_raw_delete``, raw SQL, and the
    cascade from deleting an *organization* (which removes its owners with it on purpose).
    """

    @contextmanager
    def _owner_check(self) -> Iterator[None]:
        """Lock the organizations this queryset touches and refuse if it would orphan one."""
        with _locked_organizations(self.values_list("organization_id", flat=True)):
            owners = self.filter(role=Role.OWNER).values_list("pk", "organization_id")
            _assert_owners_remain(_group_by_organization(owners))
            yield

    def update(self, **kwargs: Any) -> int:
        if _BULK_ROLE_VALIDATED.get() or "role" not in kwargs:
            return super().update(**kwargs)
        role = kwargs["role"]
        if hasattr(role, "resolve_expression"):
            raise LastOwnerError(
                "Membership.role: cannot verify an expression; assign a role."
            )
        if role == Role.OWNER:
            return super().update(**kwargs)  # an owner stays an owner
        with self._owner_check():
            return super().update(**kwargs)

    def delete(self) -> tuple[int, dict[str, int]]:
        with self._owner_check():
            return super().delete()

    def bulk_update(
        self,
        objs: Iterable[Membership],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        batch, names = list(objs), list(fields)
        if "role" not in names:
            return super().bulk_update(batch, names, batch_size)
        with _locked_organizations(o.organization_id for o in batch):
            stored = dict(
                Membership.objects.filter(pk__in=[o.pk for o in batch]).values_list(
                    "pk", "role"
                )
            )
            demoted = [
                o
                for o in batch
                if stored.get(o.pk) == Role.OWNER and o.role != Role.OWNER
            ]
            _assert_owners_remain(
                _group_by_organization((o.pk, o.organization_id) for o in demoted)
            )
            token = _BULK_ROLE_VALIDATED.set(True)
            try:
                return super().bulk_update(batch, names, batch_size)
            finally:
                _BULK_ROLE_VALIDATED.reset(token)


class MembershipManager(ImmutableFieldsManager["Membership"]):
    def get_queryset(self) -> MembershipQuerySet:
        return MembershipQuerySet(self.model, using=self._db)


class Membership(ImmutableFieldsModel):
    """A user's role in an organization. One row per (user, organization).

    ``user`` and ``organization`` are fixed once saved (only ``role`` changes): moving a
    membership between people or organizations is a different fact, so it is a delete and
    a create, and cannot happen by accident through ``update()``, ``bulk_update()`` or a
    related manager's ``add()``.

    **Last-owner protection** (3.3): an organization always keeps at least one ``owner``.
    ``save()`` with a changed role, ``delete()``, and the queryset ``update()`` /
    ``delete()`` / ``bulk_update()`` raise :class:`LastOwnerError` rather than demote or
    remove the final owner; deleting a *user* is guarded the same way (see
    :class:`UserQuerySet`). The check reads the **stored** role, not the in-memory one (a
    stale copy must not hide a demotion), and runs under a row lock on the organization
    so two concurrent demotions cannot both succeed.
    """

    immutable_fields = ("user_id", "organization_id")

    objects: MembershipManager = MembershipManager()

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(ImmutableFieldsModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization"], name="uq_membership_user_org"
            ),
            # `choices` is advisory in Django; this makes the role set a database fact.
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values), name="ck_membership_role"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} as {self.role} in {self.organization_id}"

    def _stored_role(self) -> str | None:
        return (
            Membership.objects.filter(pk=self.pk).values_list("role", flat=True).first()
        )

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        names = None if update_fields is None else set(update_fields)
        writes_role = names is None or "role" in names
        if self._state.adding or not writes_role or self.role == Role.OWNER:
            super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=using,
                update_fields=update_fields,
            )
            return
        with _locked_organizations([self.organization_id]):
            if self._stored_role() == Role.OWNER:
                _assert_owners_remain({self.organization_id: [self.pk]})
            super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=using,
                update_fields=update_fields,
            )

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        with _locked_organizations([self.organization_id]):
            if self._stored_role() == Role.OWNER:
                _assert_owners_remain({self.organization_id: [self.pk]})
            return super().delete(using=using, keep_parents=keep_parents)


class AuditLogImmutableError(RuntimeError):
    """An attempt to change or remove an :class:`AuditEvent`."""


class AuditEventQuerySet(TenantQuerySet["AuditEvent"]):
    """Tenant queryset with every mutating path closed."""

    def update(self, **kwargs: Any) -> int:
        raise AuditLogImmutableError("audit events cannot be updated")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise AuditLogImmutableError("audit events cannot be deleted")

    def bulk_update(self, *args: Any, **kwargs: Any) -> int:
        raise AuditLogImmutableError("audit events cannot be updated")

    def _raw_delete(self, using: str | None) -> int:
        raise AuditLogImmutableError("audit events cannot be deleted")


class AuditEventManager(TenantManager["AuditEvent"]):
    def get_queryset(self) -> AuditEventQuerySet:
        return AuditEventQuerySet(self.model, using=self._db)


def detach_actor(collector: Any, field: Any, sub_objs: Any, using: str) -> None:
    """``on_delete`` for ``AuditEvent.actor``: what ``SET_NULL`` does, minus ``update()``.

    ``models.SET_NULL`` hands the delete collector a lazy queryset, which the collector
    applies with ``QuerySet.update()`` -- the one call this model's queryset refuses.
    Evaluating the queryset first makes the collector write the NULLs with a plain
    ``UPDATE`` instead (its handling of already-fetched objects), so the audit log stays
    locked against every ``update()`` -- including ``update(actor=None)``, which would
    erase who did something -- while deleting a user still detaches their events.
    Referenced by name from the migration, so keep it importable at this path.
    """
    list(sub_objs)
    collector.add_field_update(field, None, sub_objs)


class AuditEvent(TenantOwnedModel):
    """One thing that happened in an organization. Append-only (see module docstring)."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=detach_actor,
        related_name="+",
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100)
    # Text, not a typed FK: the target may be any model, or already deleted.
    target_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects: AuditEventManager = AuditEventManager()

    class Meta(TenantOwnedModel.Meta):
        indexes = [
            models.Index(
                fields=["organization", "created_at"], name="ix_audit_org_created"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action} on {self.target_type}:{self.target_id}"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Any = None,
    ) -> None:
        if not self._state.adding:
            raise AuditLogImmutableError("audit events cannot be modified once saved")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise AuditLogImmutableError("audit events cannot be deleted")
