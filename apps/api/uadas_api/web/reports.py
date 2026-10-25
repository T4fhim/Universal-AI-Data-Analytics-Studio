# File: apps/api/uadas_api/web/reports.py
"""Reports (the ``report`` stage): request one (-> a job), list, read, download link, delete.

Creating a report is ``202``: a ``pending`` ``Report`` row and a ``build_report`` job are made
together and a worker renders the file (:mod:`uadas_api.exports.service`). The download is **not
streamed through this process**: ``GET .../download`` returns a presigned object-store URL from
the tenant's own ``TenantObjectStore`` handle (key re-validated against the organization) that is
valid for ``DOWNLOAD_URL_SECONDS`` (60) -- a client asks right before it downloads. A report that is
not ``ready`` is ``409``. The dataset a report is about is named in ``config`` (JSON), so it is only
returned after it resolves, through ``for_organization``, to a dataset of this project.

Roles: viewer lists, reads and downloads; editor requests and deletes.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from django.db import transaction
from django.http import HttpRequest
from ninja import Query, Router, Schema, Status
from pydantic import Field, field_validator

from uadas_api.accounts.models import Role
from uadas_api.exports.choices import ReportStatus
from uadas_api.exports.models import Report
from uadas_api.exports.service import request_report
from uadas_api.jobs.errors import IdempotencyConflictError, JobPermissionError
from uadas_api.stages.serialize import EXPERTISE_NAMES, STAGE_NAMES
from uadas_api.storage.errors import StorageError
from uadas_api.storage.store import get_store
from uadas_api.web import throttle
from uadas_api.web.errors import ApiError, responses
from uadas_api.web.idempotency import IdempotencyKeyHeader
from uadas_api.web.pagination import Page, PageParams
from uadas_api.web.scope import in_project, member, project_of, scoped, user_of
from uadas_api.workspaces.models import DatasetRecord, Project

router = Router(tags=["report"])
_BASE = "/organizations/{org_id}/projects/{project_id}/reports"
DOWNLOAD_URL_SECONDS = 60
FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")  # mirrors the core exporter's rule

ReportFormatName = Literal[
    "pdf", "html", "docx", "xlsx"
]  # pinned to ReportFormat by a test


class ReportIn(Schema):
    title: str = Field(min_length=1, max_length=255)
    format: ReportFormatName
    dataset_id: uuid.UUID
    expertise_level: EXPERTISE_NAMES = "analyst"
    included_stages: list[STAGE_NAMES] | None = Field(default=None, max_length=10)

    @field_validator("title")
    @classmethod
    def _title_is_not_a_formula(cls, value: str) -> str:
        # A title is written into Excel / Word cells: one a spreadsheet reads as a formula
        # (``=HYPERLINK(...)``) is refused here as well as neutralised by the core's exporter.
        if value.startswith(FORMULA_TRIGGERS):
            raise ValueError(
                "a report title may not start with = + - @ or a control character"
            )
        return value


class ReportOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    format: str
    status: str
    dataset_id: uuid.UUID | None
    created_at: datetime.datetime


class ReportAcceptedOut(Schema):
    report: ReportOut
    job_id: uuid.UUID


class DownloadOut(Schema):
    url: str
    expires_in_seconds: int
    filename: str


def _reports_out(project: Project, reports: list[Report]) -> list[ReportOut]:
    named: dict[uuid.UUID, uuid.UUID] = {}
    for report in reports:
        config = report.config if isinstance(report.config, dict) else {}
        try:
            named[report.pk] = uuid.UUID(str(config.get("dataset_id")))
        except ValueError:
            continue
    found = set(
        DatasetRecord.objects.for_organization(project.organization_id)
        .filter(project=project, pk__in=set(named.values()))
        .values_list("pk", flat=True)
    )
    return [
        ReportOut(
            id=r.pk,
            project_id=r.project_id,
            title=r.title,
            format=r.format,
            status=r.status,
            dataset_id=named[r.pk] if named.get(r.pk) in found else None,
            created_at=r.created_at,
        )
        for r in reports
    ]


@router.get(
    _BASE,
    response=responses({200: Page[ReportOut]}),
    summary="Reports of a project, newest first (viewer and above)",
    operation_id="reports_list",
)
def reports_list(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[PageParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(Report, project).order_by("-created_at", "-pk")
    rows = list(queryset[params.offset : params.offset + params.limit])
    return {
        "items": _reports_out(project, rows),
        "total": queryset.count(),
        "limit": params.limit,
        "offset": params.offset,
    }


@router.post(
    _BASE,
    response=responses({202: ReportAcceptedOut}),
    summary="Request a report; a job builds the file (editor and above)",
    operation_id="reports_create",
)
def reports_create(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: ReportIn,
    idempotency_key: IdempotencyKeyHeader = None,
) -> Status[ReportAcceptedOut]:
    membership = member(request, org_id, Role.EDITOR)
    project = project_of(membership, project_id)
    actor = user_of(membership)
    dataset = in_project(DatasetRecord, project, payload.dataset_id)
    throttle.enforce("report", actor.pk, membership.organization_id)
    try:
        report, creation = request_report(
            project=project,
            actor=actor,
            title=payload.title,
            report_format=payload.format,
            dataset=dataset,
            expertise_level=payload.expertise_level,
            included_stages=(
                list(payload.included_stages)
                if payload.included_stages is not None
                else None
            ),
            idempotency_key=idempotency_key,
        )
    except JobPermissionError:
        raise ApiError(403, "Your role does not allow this.") from None
    except IdempotencyConflictError:
        raise ApiError(
            409, "This report request conflicts with an earlier one."
        ) from None
    return Status(
        202,
        ReportAcceptedOut(
            report=_reports_out(project, [report])[0], job_id=creation.job.pk
        ),
    )


@router.get(
    f"{_BASE}/{{report_id}}",
    response=responses({200: ReportOut}),
    summary="One report (viewer and above)",
    operation_id="reports_get",
)
def reports_get(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, report_id: uuid.UUID
) -> ReportOut:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    return _reports_out(project, [in_project(Report, project, report_id)])[0]


@router.get(
    f"{_BASE}/{{report_id}}/download",
    response=responses({200: DownloadOut}),
    summary="A short-lived signed download URL for a ready report (viewer and above)",
    operation_id="reports_download",
)
def reports_download(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, report_id: uuid.UUID
) -> DownloadOut:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    report = in_project(Report, project, report_id)
    if report.status != ReportStatus.READY or not report.storage_key:
        raise ApiError(409, "This report is not ready.")
    filename = f"{report.title}.{report.format}"
    try:
        url = get_store(report.organization_id).presigned_get(
            report.storage_key,
            expires_in=DOWNLOAD_URL_SECONDS,
            download_filename=filename,
        )
    except (StorageError, ValueError):
        raise ApiError(503, "Storage is temporarily unavailable.") from None
    return DownloadOut(
        url=url, expires_in_seconds=DOWNLOAD_URL_SECONDS, filename=filename
    )


@router.delete(
    f"{_BASE}/{{report_id}}",
    response=responses({204: None}),
    summary="Delete a report and queue its file for removal (editor and above)",
    operation_id="reports_delete",
)
def reports_delete(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, report_id: uuid.UUID
) -> Status[None]:
    project = project_of(member(request, org_id, Role.EDITOR), project_id)
    report = in_project(Report, project, report_id)
    with transaction.atomic():
        report.delete()
    return Status(204, None)
