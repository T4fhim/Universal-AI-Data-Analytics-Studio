# File: apps/api/uadas_api/web/datasets.py
"""Datasets: list, detail, delete, paged preview, column summary, and the upload endpoint.

Roles: viewer reads, editor uploads and deletes (a dataset is data; its objects are removed by the
3.4 outbox when the row is deleted, in the delete's own transaction).

**Upload** (the ``upload`` stage) is one multipart request, streamed to a temporary file under the
size cap (:mod:`uadas_api.web.uploads`), admitted by extension and by the file's own signature
(:mod:`uadas_api.sandbox.admission`), stored as an immutable original under a tenant key, and handed
to an ``ingest_dataset`` job. The answer is ``202`` with the job id; the dataset exists only when the
job succeeds. No reader runs in this process. Chosen over presigned-then-complete because the
server sees every byte it admits (cap and signature are enforced here, not trusted from a client
that talks to the bucket directly), at the cost of the upload passing through the API process; a
presigned flow is the later optimisation if that proves a bottleneck.

**Preview** returns one page: ``limit`` (capped), ``offset``, optional ``sort`` (validated against the
frame's own columns) and ``descending``; cells are the core's display strings
(``uadas_core.data_table.column_formatters``, a missing cell is ``—``). See
:mod:`uadas_api.stages.frames` for how a page is read without loading the frame.
"""

from __future__ import annotations

import datetime
import re
import uuid
from pathlib import Path
from typing import Annotated, Any, BinaryIO, cast

from django.db import transaction
from django.http import HttpRequest
from ninja import File, Query, Router, Schema, Status, UploadedFile
from pyarrow import ArrowException
from pydantic import Field

from uadas_api.accounts.models import Role
from uadas_api.ingest.service import request_ingest
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.errors import IdempotencyConflictError, JobPermissionError
from uadas_api.jobs.models import Job
from uadas_api.sandbox.admission import check_content, check_extension
from uadas_api.sandbox.errors import SandboxError, SandboxErrorCode
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.stages import frames
from uadas_api.storage import keys
from uadas_api.storage.errors import (
    ObjectNotFoundError,
    ObjectTooLargeError,
    StorageError,
)
from uadas_api.storage.store import TenantObjectStore, get_store
from uadas_api.web import throttle
from uadas_api.web.config import api_config
from uadas_api.web.errors import ApiError, not_found, responses
from uadas_api.web.idempotency import IdempotencyKeyHeader
from uadas_api.web.pagination import Page, PageParams, paginate
from uadas_api.web.scope import in_project, member, project_of, scoped, user_of
from uadas_api.workspaces.models import DatasetRecord, Project
from uadas_core.data_table.column_formatters import format_value

router = Router(tags=["datasets"])
# The upload route is a separate router so ``api._wire_routers`` can mount it *before* ``router``:
# ``.../datasets/upload`` must be matched before ``.../datasets/{dataset_id}`` (Django takes the
# first URL pattern that matches, and "upload" would otherwise be read as a dataset id -> 405).
upload_router = Router(tags=["upload"])

_MEDIA_TYPE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}"
)
_GENERIC_TYPE = "application/octet-stream"
_BASE = "/organizations/{org_id}/projects/{project_id}/datasets"


class DatasetOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    source_format: str
    parent_dataset_id: uuid.UUID | None
    derivation_description: str
    row_count: int
    column_count: int
    sha256: str
    created_at: datetime.datetime


class ColumnOut(Schema):
    name: str
    dtype: str


class PreviewOut(Schema):
    columns: list[ColumnOut]
    rows: list[list[str]]
    total_rows: int
    offset: int
    limit: int
    sort: str | None
    descending: bool


class PreviewParams(Schema):
    offset: Annotated[int, Field(ge=0, le=api_config().max_offset)] = 0
    limit: Annotated[int, Field(ge=1, le=api_config().preview_max_rows)] = 50
    sort: Annotated[str | None, Field(max_length=255)] = None
    descending: bool = False


class ColumnSummaryOut(Schema):
    name: str
    dtype: str
    null_count: int | None
    min: str | None
    max: str | None


class SummaryOut(Schema):
    row_count: int
    column_count: int
    columns: list[ColumnSummaryOut]


class UploadAcceptedOut(Schema):
    job_id: uuid.UUID
    dataset_id: uuid.UUID
    status: str


def dataset_out(record: DatasetRecord) -> DatasetOut:
    return DatasetOut(
        id=record.pk,
        project_id=record.project_id,
        name=record.name,
        source_format=record.source_format,
        parent_dataset_id=record.parent_dataset_id,
        derivation_description=record.derivation_description,
        row_count=record.row_count,
        column_count=record.column_count,
        sha256=record.sha256,
        created_at=record.created_at,
    )


@router.get(
    f"{_BASE}",
    response=responses({200: Page[DatasetOut]}),
    summary="Datasets of a project (viewer and above)",
    operation_id="datasets_list",
)
def datasets_list(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[PageParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(DatasetRecord, project).order_by("created_at", "pk")
    return paginate(queryset, params, dataset_out)


@router.get(
    f"{_BASE}/{{dataset_id}}",
    response=responses({200: DatasetOut}),
    summary="One dataset (viewer and above)",
    operation_id="datasets_get",
)
def datasets_get(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
) -> DatasetOut:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    return dataset_out(in_project(DatasetRecord, project, dataset_id))


@router.delete(
    f"{_BASE}/{{dataset_id}}",
    response=responses({204: None}),
    summary="Delete a dataset and queue its stored objects for removal (editor and above)",
    operation_id="datasets_delete",
)
def datasets_delete(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
) -> Status[None]:
    project = project_of(member(request, org_id, Role.EDITOR), project_id)
    record = in_project(DatasetRecord, project, dataset_id)
    # The post_delete receiver (uadas_api.storage.signals) queues the dataset's whole directory in
    # *this* transaction and the purge runs after commit: the original and every frame go.
    with transaction.atomic():
        record.delete()
    return Status(204, None)


def _metered_dataset(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
) -> DatasetRecord:
    """The dataset (viewer and above), after counting one ``preview``-scope read for the caller.

    A preview page and a summary each make the store copy and hash the whole Parquet object, so
    both draw on one bounded per-user, per-organization budget; the dataset is resolved first so a
    foreign id is a 404 that costs nothing.
    """
    membership = member(request, org_id, Role.VIEWER)
    project = project_of(membership, project_id)
    record = in_project(DatasetRecord, project, dataset_id)
    throttle.enforce("preview", membership.user_id, membership.organization_id)
    return record


def _open(store: TenantObjectStore, record: DatasetRecord) -> Any:
    try:
        return frames.open_frame(store, record)
    except ObjectNotFoundError:
        raise not_found() from None
    except StorageError:
        raise ApiError(503, "Storage is temporarily unavailable.") from None


@router.get(
    f"{_BASE}/{{dataset_id}}/preview",
    response=responses({200: PreviewOut}),
    summary="One page of rows, optionally sorted (viewer and above)",
    operation_id="datasets_preview",
)
def datasets_preview(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    params: Query[PreviewParams],
) -> PreviewOut:
    record = _metered_dataset(request, org_id, project_id, dataset_id)
    cfg = api_config()
    limit = min(params.limit, cfg.preview_max_rows)
    if params.sort is not None and record.row_count > cfg.preview_max_sort_rows:
        raise ApiError(422, "This dataset is too large to sort in the preview.")
    handle = _open(get_store(record.organization_id), record)
    try:
        with handle:
            pf = frames.parquet_file(handle)
            names = frames.column_names(pf)
            if params.sort is not None and params.sort not in names:
                raise ApiError(422, "Unknown sort column.")
            page = frames.read_page(
                pf,
                offset=params.offset,
                limit=limit,
                sort=params.sort,
                descending=params.descending,
            )
            types = frames.column_types(pf)
            total = int(pf.metadata.num_rows)
    except (ArrowException, OSError):
        raise ApiError(503, "The stored dataset could not be read.") from None
    rows = [
        [format_value(value) for value in row] for row in page.itertuples(index=False)
    ]
    return PreviewOut(
        columns=[ColumnOut(name=n, dtype=t) for n, t in types],
        rows=rows,
        total_rows=total,
        offset=params.offset,
        limit=limit,
        sort=params.sort,
        descending=params.descending,
    )


@router.get(
    f"{_BASE}/{{dataset_id}}/summary",
    response=responses({200: SummaryOut}),
    summary="Column types, null counts and ranges from the file footer (viewer and above)",
    operation_id="datasets_summary",
)
def datasets_summary(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
) -> SummaryOut:
    record = _metered_dataset(request, org_id, project_id, dataset_id)
    handle = _open(get_store(record.organization_id), record)
    try:
        with handle:
            pf = frames.parquet_file(handle)
            summaries = frames.column_summaries(pf)
            total = int(pf.metadata.num_rows)
    except (ArrowException, OSError):
        raise ApiError(503, "The stored dataset could not be read.") from None
    return SummaryOut(
        row_count=total,
        column_count=len(summaries),
        columns=[ColumnSummaryOut(**item) for item in summaries],
    )


# ----------------------------------------------------------------------- upload


def _media_type(declared: str | None) -> str:
    bare = (declared or "").split(";", 1)[0].strip().lower()
    return bare if _MEDIA_TYPE.fullmatch(bare) else _GENERIC_TYPE


def _admission_error(error: SandboxError) -> ApiError:
    if error.code in {
        SandboxErrorCode.INPUT_TOO_LARGE,
        SandboxErrorCode.DECOMPRESSION_BOMB,
    }:
        return ApiError(413, "This file is too large.")
    return ApiError(415, "This file type is not supported.")


def _retire(organization_id: uuid.UUID, store: TenantObjectStore, key: str) -> None:
    from uadas_api.ingest.service import retire_frame

    retire_frame(str(organization_id), store, key)


@upload_router.post(
    f"{_BASE}/upload",
    response=responses({202: UploadAcceptedOut}),
    summary="Upload a file; an ingest job turns it into a dataset (editor and above)",
    operation_id="datasets_upload",
)
def datasets_upload(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    file: File[UploadedFile],
    idempotency_key: IdempotencyKeyHeader = None,
) -> Status[UploadAcceptedOut]:
    membership = member(request, org_id, Role.EDITOR)
    project = project_of(membership, project_id)
    actor = user_of(membership)
    # The upload throttle is counted by the upload handler *before* the body is parsed
    # (uadas_api/web/uploads.py), so a refused or throttled request never costs a temp file.
    return _accept_upload(project, actor, file, idempotency_key)


def _replayed_upload(
    project: Project, dataset_id: uuid.UUID, filename: str
) -> Status[UploadAcceptedOut] | None:
    """The answer for a retried upload (same ``Idempotency-Key``), or ``None`` if it is new."""
    existing = (
        Job.objects.for_organization(project.organization_id)
        .filter(
            kind=JobKind.INGEST_DATASET.value, idempotency_key=f"ingest-{dataset_id}"
        )
        .first()
    )
    if existing is None:
        return None
    if existing.project_id != project.pk or existing.params.get("filename") != filename:
        raise ApiError(409, "This idempotency key was used for a different request.")
    return Status(
        202,
        UploadAcceptedOut(
            job_id=existing.pk, dataset_id=dataset_id, status=str(existing.status)
        ),
    )


def _accept_upload(
    project: Project,
    actor: Any,
    upload: UploadedFile,
    idempotency_key: str | None = None,
) -> Status[UploadAcceptedOut]:
    name = (upload.name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or not upload.size:
        raise ApiError(422, "The file is empty or has no name.")
    limits = SandboxLimits.from_settings()
    try:
        extension = check_extension(name)
        path = getattr(upload, "temporary_file_path", None)
        if (
            path is None
        ):  # not reachable with the capped handler; fail closed rather than skip
            raise ApiError(422, "The upload could not be inspected.")
        check_content(Path(path()), extension, limits)
    except SandboxError as error:
        raise _admission_error(error) from None

    org = keys.organization_id(project.organization_id)
    # With a client key the dataset id is derived from it (per organization), so a retry names the
    # same dataset and the ingest job's own key (``ingest-<dataset id>``) dedups it.
    dataset_id = (
        uuid.uuid4()
        if idempotency_key is None
        else uuid.uuid5(project.organization_id, f"upload:{idempotency_key}")
    )
    if idempotency_key is not None:
        replay = _replayed_upload(project, dataset_id, name)
        if replay is not None:
            return replay
    original_key = keys.dataset_original_key(org, dataset_id)
    # The declared type is advisory (it goes to the job as such); the *stored* original is always
    # opaque bytes, so a client cannot make the bucket serve its upload as text/html.
    declared_type = _media_type(upload.content_type)
    content_type = _GENERIC_TYPE
    store = get_store(org)
    if upload.file is None:  # not reachable for a parsed multipart file; fail closed
        raise ApiError(422, "The upload could not be read.")
    stream = cast(BinaryIO, upload.file)  # a temporary file opened "wb+" by Django
    stream.seek(0)
    try:
        store.put(
            original_key,
            stream,
            content_type=content_type,
            allowed_content_types=(content_type,),
            max_bytes=limits.max_input_bytes,
            original_filename=name,
        )
    except ObjectTooLargeError:
        raise ApiError(413, "This file is too large.") from None
    except StorageError:
        raise ApiError(503, "Storage is temporarily unavailable.") from None
    try:
        creation = request_ingest(
            project=project,
            actor=actor,
            dataset_id=dataset_id,
            original_key=original_key,
            filename=name,
            content_type=declared_type,
        )
    except JobPermissionError:
        _retire(project.organization_id, store, original_key)
        raise ApiError(403, "Your role does not allow this.") from None
    except IdempotencyConflictError:
        _retire(project.organization_id, store, original_key)
        raise ApiError(409, "This upload conflicts with an earlier one.") from None
    except Exception:
        _retire(project.organization_id, store, original_key)
        raise
    return Status(
        202,
        UploadAcceptedOut(
            job_id=creation.job.pk,
            dataset_id=dataset_id,
            status=str(creation.job.status),
        ),
    )
