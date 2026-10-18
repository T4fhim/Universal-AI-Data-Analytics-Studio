# File: apps/api/uadas_api/ingest/service.py
"""The ``ingest_dataset`` job: stored original in, ``DatasetRecord`` + Parquet frame out.

The pipeline, and the one rule it keeps (**a failure at any step leaves no ``DatasetRecord`` and
cleans up or queues for deletion whatever was staged**):

1. *Admission by name*: the declared file name's extension must be one the readers accept
   (:func:`~uadas_api.sandbox.admission.check_extension`). No storage call yet.
2. *Fetch*: ``HEAD`` the stored original (size cap before any byte moves), then download it into
   the sandbox workspace's private temp directory, verified against its recorded SHA-256.
3. *Admission by content*: the file's own bytes must agree with its extension
   (:func:`~uadas_api.sandbox.admission.check_content`) -- signature, zip / gzip budgets, size.
   Still no reader has run.
4. *Parse, in the sandbox child* (:class:`~uadas_api.sandbox.runner.SandboxWorkspace`): this
   process never imports a reader. The child returns a Parquet file the parent has already
   verified (size, magic, SHA-256) plus counts.
5. *Store the frame* under a **new, never-reused key** (``<org>/datasets/<id>/frames/
   j<attempt>-<job>.parquet``), create-only, so a retry cannot overwrite what an earlier attempt
   left and the 3.4 rule "never write to a key something references" holds.
6. *Commit*: the ``DatasetRecord`` (storage key, counts, source format, SHA-256) is created **in
   the same database transaction** that marks the job ``succeeded``
   (:func:`uadas_api.jobs.execution._commit`). Either both exist or neither does.

What cleans up what:

* the frame, if anything fails after it was uploaded (cancel, lost claim, a rival dataset with the
  same id, a failing commit): deleted at once, or -- if the store refuses -- queued in the 3.4
  outbox (``OrphanedObject``);
* the frames of *earlier attempts* (a worker that died after uploading one): queued at commit;
* the whole dataset directory -- the original upload included -- when the job ends failed or
  cancelled **for good** and no dataset with that id exists (:func:`abandon_ingest`). If a dataset
  *does* exist (a duplicate request lost the race) nothing is deleted.

Idempotency: the job's idempotency key defaults to ``ingest-<dataset_id>``, so asking twice for one
dataset is one job; a redelivered task for a finished job is a no-op (``execution``); a second,
different job for a dataset that already exists fails ``conflict`` without touching it.

Plugins stay off: nothing here loads one, and the child process (which does import the reader
registry) runs with no plugin loader at all.
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from uadas_api.accounts.models import User
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.errors import JobError, JobErrorCode
from uadas_api.jobs.models import Job
from uadas_api.jobs.registry import Completion, JobContext, JobHandler
from uadas_api.jobs.services import JobCreation, create_job
from uadas_api.sandbox.admission import check_content, check_extension
from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.sandbox.runner import SandboxResult, SandboxWorkspace
from uadas_api.storage import keys, lifecycle
from uadas_api.storage.errors import InvalidKeyError, StorageError
from uadas_api.storage.store import StoredObject, TenantObjectStore, get_store
from uadas_api.workspaces.choices import SourceFormat
from uadas_api.workspaces.models import DatasetRecord, Project

_logger = logging.getLogger(__name__)

FRAME_CONTENT_TYPE = "application/vnd.apache.parquet"
MAX_FILENAME_CHARS = 255
_PARAM_FIELDS = frozenset({"dataset_id", "original_key", "filename", "content_type"})
_MEDIA_TYPE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}"
)


# ------------------------------------------------------------------ parameters


def _invalid(what: str) -> ValidationError:
    # Never echoes the value: it may be attacker-controlled text.
    return ValidationError(f"invalid ingest parameter: {what}", code="invalid_ingest")


def _clean_filename(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_FILENAME_CHARS:
        raise _invalid("filename")
    if any(unicodedata.category(ch) in {"Cc", "Cf", "Cs", "Co", "Cn"} for ch in value):
        raise _invalid("filename")
    return value


def _structural_params(
    organization_id: Any, params: Mapping[str, Any]
) -> dict[str, str]:
    """Check the shape of ``params`` and that every id and key belongs to ``organization_id``.

    Everything except the extension (that is :func:`check_extension`'s, so that a wrong extension
    at *run time* is reported as ``unsupported_type`` rather than a malformed request).
    """
    if set(params) != _PARAM_FIELDS:
        raise _invalid("fields")
    try:
        org = keys.organization_id(organization_id)
        dataset_id = keys.uuid_text(params["dataset_id"], "dataset id")
        original_key = params["original_key"]
        if not isinstance(original_key, str):
            raise _invalid("original_key")
        keys.check_key(org, original_key)
    except InvalidKeyError:
        raise _invalid("identifier") from None
    prefix = f"{org}/datasets/{dataset_id}/original/"
    if not original_key.startswith(prefix) or len(original_key) == len(prefix):
        raise _invalid("original_key")
    content_type = params["content_type"]
    if not isinstance(content_type, str):
        raise _invalid("content_type")
    bare = content_type.split(";", 1)[0].strip().lower()
    if _MEDIA_TYPE.fullmatch(bare) is None:
        raise _invalid("content_type")
    return {
        "dataset_id": dataset_id,
        "original_key": original_key,
        "filename": _clean_filename(params["filename"]),
        "content_type": bare,
    }


def validate_params(organization_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """The job registry's creation-time check: shape, ownership of every key, a listed extension.

    ``content_type`` is validated for shape and stored, but it is advisory: the client sets it, so
    only the extension and the file's own bytes decide what the file is.
    """
    cleaned = _structural_params(organization_id, params)
    try:
        check_extension(cleaned["filename"])
    except SandboxError:
        raise _invalid("filename extension") from None
    return dict(cleaned)


def request_ingest(
    *,
    project: Project,
    actor: User,
    dataset_id: uuid.UUID | str,
    original_key: str,
    filename: str,
    content_type: str,
    idempotency_key: str | None = None,
) -> JobCreation:
    """Create (or return) the ingest job for an already-stored original upload.

    ``original_key`` is the key under which the upload endpoint (3.6) stored the original, inside
    the dataset's own ``original/`` directory; ``filename`` and ``content_type`` are what the
    client declared. Raises what :func:`uadas_api.jobs.services.create_job` raises.
    """
    return create_job(
        project=project,
        actor=actor,
        kind=JobKind.INGEST_DATASET.value,
        params={
            "dataset_id": str(dataset_id),
            "original_key": original_key,
            "filename": filename,
            "content_type": content_type,
        },
        idempotency_key=idempotency_key
        or f"ingest-{keys.uuid_text(dataset_id, 'dataset id')}",
    )


# ------------------------------------------------------------------- the handler


def _attempt_token(job_id: uuid.UUID, attempt: int) -> str:
    """The frame-key token of one attempt: new per attempt, derivable for cleanup."""
    return f"j{attempt:03d}-{job_id.hex}"


def _display_name(filename: str) -> str:
    last = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    return (last or "dataset")[:MAX_FILENAME_CHARS]


def _retire_frame(organization_id: str, store: TenantObjectStore, key: str) -> None:
    """Delete a frame this job staged, or queue the deletion in the outbox; never raise."""
    try:
        store.delete(key)
        return
    except StorageError as error:
        _logger.warning(
            "could not delete a staged frame (%s); queueing it", type(error).__name__
        )
    try:
        with transaction.atomic():
            lifecycle.queue_deletions(organization_id, [(key, False)], reason="ingest")
    # Cleanup must not mask the job's real outcome, so nothing escapes from here.
    except Exception as error:  # noqa: BLE001
        _logger.error(
            "could not queue a staged frame for deletion (%s)", type(error).__name__
        )


def _put_frame(
    store: TenantObjectStore, key: str, result: SandboxResult, limits: SandboxLimits
) -> StoredObject:
    with result.open_output() as handle:
        return store.put(
            key,
            handle,
            content_type=FRAME_CONTENT_TYPE,
            allowed_content_types=(FRAME_CONTENT_TYPE,),
            max_bytes=limits.max_output_bytes,
            metadata={"source-format": result.source_format},
        )


def ingest_dataset(ctx: JobContext) -> Completion:
    """The worker body of an ``ingest_dataset`` job. See the module docstring."""
    org = keys.organization_id(ctx.organization.pk)
    try:
        params = _structural_params(org, ctx.params)
    except ValidationError:
        raise JobError(JobErrorCode.INVALID_REQUEST) from None
    dataset_id, original_key = params["dataset_id"], params["original_key"]
    if DatasetRecord.objects.for_organization(org).filter(pk=dataset_id).exists():
        raise JobError(JobErrorCode.CONFLICT)
    extension = check_extension(params["filename"])  # (1) admission by name; no I/O yet

    limits = SandboxLimits.from_settings()
    store = get_store(org)
    frame_key = keys.dataset_frame_key(
        org, dataset_id, _attempt_token(ctx.job.pk, ctx.job.attempts)
    )
    ctx.report(5, "Checking the file", force=True)

    with SandboxWorkspace(limits) as workspace:
        info = store.head(original_key)  # (2) fetch: size first
        if info is None:
            raise JobError(JobErrorCode.NOT_FOUND)
        if info.size > limits.max_input_bytes:
            raise SandboxError(SandboxErrorCode.INPUT_TOO_LARGE)
        input_path = workspace.input_path(extension)
        store.download_to(original_key, input_path, max_bytes=limits.max_input_bytes)
        check_content(input_path, extension, limits)  # (3) admission by content
        ctx.check_cancelled()
        ctx.report(25, "Reading the file", force=True)
        result = workspace.parse(extension)  # (4) the sandbox child
        if result.source_format not in SourceFormat.values:
            raise JobError(JobErrorCode.INTERNAL_ERROR)
        ctx.check_cancelled()
        ctx.report(75, "Saving the table", force=True)
        stored = _put_frame(store, frame_key, result, limits)  # (5) a new key

    try:
        if stored.sha256 != result.sha256:
            raise JobError(
                JobErrorCode.INTERNAL_ERROR
            )  # the bytes stored are not the bytes parsed
        ctx.check_cancelled()
    except BaseException:
        _retire_frame(org, store, frame_key)
        raise

    attempt = ctx.job.attempts
    project = ctx.project

    def commit() -> (
        None
    ):  # (6) runs inside the transaction that marks the job succeeded
        try:
            DatasetRecord.objects.create(
                id=dataset_id,
                organization_id=org,
                project=project,
                name=_display_name(params["filename"]),
                source_format=result.source_format,
                storage_key=frame_key,
                sha256=result.sha256,
                row_count=result.row_count,
                column_count=result.column_count,
            )
        except IntegrityError:
            raise JobError(JobErrorCode.CONFLICT) from None
        if attempt > 1:  # frames an earlier, crashed attempt may have left behind
            earlier = [
                (
                    keys.dataset_frame_key(
                        org, dataset_id, _attempt_token(ctx.job.pk, n)
                    ),
                    False,
                )
                for n in range(1, attempt)
            ]
            lifecycle.queue_deletions(org, earlier, reason="ingest_retry")

    return Completion(
        result={
            "dataset_id": dataset_id,
            "storage_key": frame_key,
            "sha256": result.sha256,
            "row_count": result.row_count,
            "column_count": result.column_count,
            "source_format": result.source_format,
            "size_bytes": result.size,
        },
        commit=commit,
        cleanup=lambda: _retire_frame(org, store, frame_key),
    )


def abandon_ingest(job: Job) -> None:
    """A job ended failed or cancelled for good: queue the dataset's stored objects for deletion.

    Only if no ``DatasetRecord`` has that id -- when one exists (a duplicate request that lost) its
    objects belong to it and are never touched. Queued, not deleted: the outbox pays the debt after
    its grace period and never deletes what a saved workspace references.
    """
    org = str(job.organization_id)
    try:
        params = _structural_params(org, job.params)
    except ValidationError:
        return  # malformed parameters name nothing this job can own
    if (
        DatasetRecord.objects.for_organization(org)
        .filter(pk=params["dataset_id"])
        .exists()
    ):
        return
    prefix = f"{org}/datasets/{params['dataset_id']}"
    with transaction.atomic():
        lifecycle.queue_deletions(org, [(prefix, True)], reason="ingest_failed")


HANDLER = JobHandler(
    validate_params=validate_params,
    run=ingest_dataset,
    on_abandon=abandon_ingest,
)
