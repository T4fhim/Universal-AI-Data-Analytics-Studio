# File: apps/api/uadas_api/jobs/models.py
"""``Job``: one unit of background work, as a tenant-owned database row.

Why a row and not just a Celery task: the broker is a courier, and couriers lose parcels
(Redis flushed, a message redelivered twice, a worker killed mid-task). The *truth* about a job
-- who asked, what for, how far it got, whether it finished, why it failed -- must survive all
of that and must be readable by the API. So the row carries it, the task message carries only
the row's id, and every worker action is a conditional update of this row.

It is also the **cross-process progress sink**. ``django.tasks`` / Celery progress callbacks are
in-process; a worker is another process. The worker therefore writes ``progress`` / ``message`` /
``heartbeat_at`` here (throttled, see :mod:`uadas_api.jobs.progress`) and the API -- and 3.7's
SSE stream -- reads them. Nothing in those columns may hold data from the user's file or a
secret: messages are fixed strings chosen by the handler, errors are a closed code plus a fixed
sentence (:mod:`uadas_api.jobs.errors`).

The state machine (:mod:`uadas_api.jobs.choices`) is enforced on every write path, not by
convention:

* ``save()`` -- :meth:`Job._check_transition` (what this instance remembers) *and*
  :meth:`Job._check_against_the_database` (what is stored, under a row lock, in the same
  transaction as the write): a new job starts ``queued``; an existing one may only follow the
  table; a terminal job refuses every save, whatever the field, even from an instance that was
  loaded before the job finished.
* ``queryset.update()`` -- ``status`` may be written only inside :func:`allow_status_write` (the
  services' conditional updates use it); terminal rows are excluded from every ``update()``, so
  a ``succeeded`` row cannot be edited by a stray queryset either.
* The database -- check constraints pin the value sets, ``progress`` in 0..100, "terminal if and
  only if it has a finish time", "failed if and only if it has an error code".

What this does **not** do: a raw SQL ``UPDATE`` or ``QuerySet._raw_delete`` bypasses all of the
Python-level guards (the same limit as ``tenancy``); the check constraints are the floor that
remains. Transition *legality* is not a database constraint (it would need a trigger).

``project`` cascades (a job owns no stored object; ``Project`` deletion is already blocked while
datasets exist), ``created_by`` is ``SET_NULL`` (a deleted user's jobs keep their history).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from django.conf import settings
from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models.base import ModelBase

from uadas_api.jobs.choices import (
    TERMINAL_STATUSES,
    JobKind,
    JobStatus,
    can_transition,
)
from uadas_api.jobs.errors import JobTransitionError
from uadas_api.tenancy import TenantManager, TenantOwnedModel, TenantQuerySet
from uadas_api.workspaces.models import Project

_TERMINAL_LIST: list[str] = sorted(TERMINAL_STATUSES)

# True only inside `allow_status_write()`. A ContextVar (not a module global) so two threads or
# async tasks cannot open each other's door.
_STATUS_WRITE: ContextVar[bool] = ContextVar("uadas_job_status_write", default=False)

validate_idempotency_key = RegexValidator(
    r"\A[A-Za-z0-9._:-]{1,64}\Z",
    "An idempotency key is 1-64 letters, digits, '.', '_', ':' or '-'.",
)


@contextmanager
def allow_status_write() -> Iterator[None]:
    """Open the one door through which ``queryset.update()`` may write ``Job.status``.

    Only :mod:`uadas_api.jobs.services` (conditional, state-machine-filtered updates) and the
    tests that need to put a row in a given state use it.
    """
    token = _STATUS_WRITE.set(True)
    try:
        yield
    finally:
        _STATUS_WRITE.reset(token)


def _require_door(fields: Collection[str]) -> None:
    if "status" in fields and not _STATUS_WRITE.get():
        raise JobTransitionError(
            "Job.status may only be changed through uadas_api.jobs.services (which "
            "applies the state machine as a conditional update)."
        )


class JobQuerySet(TenantQuerySet["Job"]):
    """A tenant queryset that also enforces the job state machine on bulk writes."""

    def update(self, **kwargs: Any) -> int:
        _require_door(kwargs)
        # A terminal job is immutable: no update, of any field, can reach it.
        return super(JobQuerySet, self.exclude(status__in=TERMINAL_STATUSES)).update(
            **kwargs
        )

    def bulk_update(
        self,
        objs: Iterable[Job],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        names = list(fields)
        _require_door(names)
        return super().bulk_update(objs, names, batch_size)

    def bulk_create(self, objs: Iterable[Job], *args: Any, **kwargs: Any) -> list[Job]:
        batch = list(objs)
        for job in batch:
            if job.status != JobStatus.QUEUED:
                raise JobTransitionError("A new job must start queued.")
        return super().bulk_create(batch, *args, **kwargs)


class JobManager(TenantManager["Job"]):
    """Manager whose querysets are :class:`JobQuerySet`."""

    def get_queryset(self) -> JobQuerySet:
        return JobQuerySet(self.model, using=self._db)


class Job(TenantOwnedModel):
    """One background job. See the module docstring for the contract."""

    objects: JobManager = JobManager()

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="jobs")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    kind = models.CharField(max_length=32, choices=JobKind.choices)
    # What the job is to do: ids, storage keys and a display name -- never data from a file.
    # Validated per kind (the handler's ``validate_params``) before the row exists.
    params: models.JSONField[Any] = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(
        max_length=64, validators=[validate_idempotency_key]
    )

    status = models.CharField(
        max_length=16, choices=JobStatus.choices, default=JobStatus.QUEUED
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    progress = models.PositiveSmallIntegerField(
        default=0, validators=[MaxValueValidator(100)]
    )
    message = models.CharField(max_length=200, blank=True)
    # Ids and keys only (what the job produced), never rows of data.
    result: models.JSONField[Any] = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=32, blank=True)
    error_message = models.CharField(max_length=200, blank=True)

    cancel_requested = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # When the message was last handed to the broker (the sweeper re-sends a lost one).
    enqueued_at = models.DateTimeField(null=True, blank=True)
    # A retry backing off: the job must not run (or be re-sent by the lost-message sweeper)
    # before this instant. ``None`` = no constraint.
    not_before = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind", "idempotency_key"],
                name="uq_job_org_kind_key",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=JobKind.values), name="ck_job_kind"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=JobStatus.values), name="ck_job_status"
            ),
            models.CheckConstraint(
                condition=models.Q(progress__gte=0, progress__lte=100),
                name="ck_job_progress",
            ),
            models.CheckConstraint(
                # A sorted *list*, not the frozenset: the migration serializes it, and a set's
                # iteration order would make the generated file differ from run to run.
                condition=(
                    models.Q(status__in=_TERMINAL_LIST, finished_at__isnull=False)
                    | (
                        ~models.Q(status__in=_TERMINAL_LIST)
                        & models.Q(finished_at__isnull=True)
                    )
                ),
                name="ck_job_finished_iff_terminal",
            ),
            models.CheckConstraint(
                condition=(models.Q(status=JobStatus.FAILED) & ~models.Q(error_code=""))
                | (~models.Q(status=JobStatus.FAILED) & models.Q(error_code="")),
                name="ck_job_error_iff_failed",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "project", "created_at"],
                name="ix_job_org_proj_ts",
            ),
            # The sweeper looks across organizations for stale running jobs and for queued
            # jobs whose message may have been lost.
            models.Index(fields=["status", "heartbeat_at"], name="ix_job_status_beat"),
            models.Index(fields=["status", "enqueued_at"], name="ix_job_status_enq"),
        ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._remember_status()

    def _remember_status(self) -> None:
        # A deferred field is absent from __dict__ and recorded as None (fetched on demand).
        self._original_status: str | None = self.__dict__.get("status")

    def __str__(self) -> str:
        # No params: a display string reaches logs and admin pages.
        return f"{self.kind} {self.pk} [{self.status}]"

    # --- the state machine on the ORM path ---------------------------------------

    def _check_transition(self) -> None:
        if self._state.adding:
            if self.status != JobStatus.QUEUED:
                raise JobTransitionError("A new job must start queued.")
            return
        if "status" not in self.__dict__:
            return  # deferred and untouched: not being written
        original = self._original_status
        if original is None:  # status was deferred and then assigned: ask the database
            original = (
                Job._base_manager.filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
        if original is None:
            return  # the row is gone; the save will report that itself
        if original in TERMINAL_STATUSES:
            raise JobTransitionError("A finished job is immutable.")
        if self.status != original and not can_transition(original, self.status):
            raise JobTransitionError(
                f"A job cannot move from {original} to {self.status}."
            )

    def _check_against_the_database(self, using: str | None) -> None:
        """Re-check the transition against the *stored* status, under a row lock.

        The in-memory check trusts what this instance remembers, which can be hours old: another
        worker may have finished the job since, and a ``save()`` of every field would then write
        the stale ``status`` back over a terminal row. So at write time the row is locked
        (``SELECT ... FOR UPDATE`` where the database has row locks) and the move is judged against
        what is really there. Must run inside the same transaction as the write.
        """
        stored = (
            Job._base_manager.using(using)
            .select_for_update()
            .filter(pk=self.pk)
            .values_list("status", flat=True)
            .first()
        )
        if stored is None:
            return  # the row is gone; the save will report that itself
        if stored in TERMINAL_STATUSES:
            raise JobTransitionError("A finished job is immutable.")
        if (
            "status" in self.__dict__
            and self.status != stored
            and not can_transition(stored, self.status)
        ):
            raise JobTransitionError(
                f"A job cannot move from {stored} to {self.status}."
            )

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        self._check_transition()  # cheap, and fails fast without a query for the plain cases
        with transaction.atomic(using=using):
            if not self._state.adding:
                self._check_against_the_database(using)
            super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=using,
                update_fields=update_fields,
            )
        self._remember_status()


def new_idempotency_key() -> str:
    """A fresh key for a caller that does not supply one (every call is then its own request)."""
    return uuid.uuid4().hex
