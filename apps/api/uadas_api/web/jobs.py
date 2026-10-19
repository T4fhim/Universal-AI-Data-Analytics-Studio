# File: apps/api/uadas_api/web/jobs.py
"""Jobs: list, detail (status + progress for polling), cancel, and a stage run's result.

Every job route lives under its project (``/organizations/{org_id}/projects/{project_id}/jobs``)
and resolves the job through ``for_organization`` *and* that project. Viewers may read, editors
may cancel (the service re-checks the capability).

``dataset_id`` / ``report_id`` on a job are what a finished job produced, taken from the job's own
``result`` -- an id read out of a JSON field, so (the 3.2 obligation) it is only returned after it
resolves, through ``for_organization``, to a row of this project; otherwise it is ``None``.

The stage result (the Phase 1.5 section model) is large, so it is not part of the polled job
resource: ``GET .../jobs/{job_id}/stage-result`` returns it once the job has succeeded.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from django.db.models.fields.json import KeyTextTransform
from django.http import HttpRequest
from ninja import Query, Router, Schema

from uadas_api.accounts.models import Role
from uadas_api.exports.models import Report
from uadas_api.jobs import services
from uadas_api.jobs.choices import JobKind, JobStatus
from uadas_api.jobs.errors import JobPermissionError
from uadas_api.jobs.models import Job
from uadas_api.stages.serialize import StageResultOut
from uadas_api.web.errors import ApiError, not_found, responses
from uadas_api.web.pagination import Page, PageParams
from uadas_api.web.scope import in_project, member, project_of, scoped
from uadas_api.workspaces.models import DatasetRecord, Project

router = Router(tags=["jobs"])
_BASE = "/organizations/{org_id}/projects/{project_id}/jobs"


class JobOut(Schema):
    id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    status: str
    progress: int
    message: str
    error_code: str
    error_message: str
    cancel_requested: bool
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    dataset_id: uuid.UUID | None = None
    report_id: uuid.UUID | None = None


class JobListParams(PageParams):
    status: str | None = None


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def for_listing(queryset: Any) -> Any:
    """``queryset`` without the ``result`` column (up to 4 MiB of JSON per row), keeping only the
    two ids the list shows, extracted by the database (``out_dataset`` / ``out_report``).
    """
    return queryset.defer("result").annotate(
        out_dataset=KeyTextTransform("dataset_id", "result"),
        out_report=KeyTextTransform("report_id", "result"),
    )


def _named(job: Job) -> tuple[Any, Any]:
    """The raw dataset and report ids a job's result names (annotated by :func:`for_listing`, else read)."""
    if "out_dataset" in job.__dict__:
        return job.__dict__["out_dataset"], job.__dict__["out_report"]
    result = job.result if isinstance(job.result, dict) else {}
    return result.get("dataset_id"), result.get("report_id")


def _outputs(
    project: Project, jobs: list[Job]
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """The dataset and report ids named by ``jobs``' results that really are this project's."""
    named = [_named(job) for job in jobs]
    datasets = {i for d, _ in named if (i := _uuid_or_none(d))}
    reports = {i for _, r in named if (i := _uuid_or_none(r))}
    org = project.organization_id
    found_datasets = set(
        DatasetRecord.objects.for_organization(org)
        .filter(project=project, pk__in=datasets)
        .values_list("pk", flat=True)
    )
    found_reports = set(
        Report.objects.for_organization(org)
        .filter(project=project, pk__in=reports)
        .values_list("pk", flat=True)
    )
    return found_datasets, found_reports


def jobs_out(project: Project, jobs: list[Job]) -> list[JobOut]:
    datasets, reports = _outputs(project, jobs)
    out: list[JobOut] = []
    for job in jobs:
        raw_dataset, raw_report = _named(job)
        dataset_id = _uuid_or_none(raw_dataset)
        report_id = _uuid_or_none(raw_report)
        out.append(
            JobOut(
                id=job.pk,
                project_id=job.project_id,
                kind=job.kind,
                status=job.status,
                progress=job.progress,
                message=job.message,
                error_code=job.error_code,
                error_message=job.error_message,
                cancel_requested=job.cancel_requested,
                created_at=job.created_at,
                started_at=job.started_at,
                finished_at=job.finished_at,
                dataset_id=dataset_id if dataset_id in datasets else None,
                report_id=report_id if report_id in reports else None,
            )
        )
    return out


def job_out(project: Project, job: Job) -> JobOut:
    return jobs_out(project, [job])[0]


@router.get(
    _BASE,
    response=responses({200: Page[JobOut]}),
    summary="Jobs of a project, newest first (viewer and above)",
    operation_id="jobs_list",
)
def jobs_list(
    request: HttpRequest,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    params: Query[JobListParams],
) -> dict[str, Any]:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    queryset = scoped(Job, project).order_by("-created_at", "-pk")
    if params.status is not None:
        if params.status not in JobStatus.values:
            raise ApiError(422, "Unknown job status.")
        queryset = queryset.filter(status=params.status)
    total = queryset.count()
    rows = list(for_listing(queryset)[params.offset : params.offset + params.limit])
    return {
        "items": jobs_out(project, rows),
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
    }


@router.get(
    f"{_BASE}/{{job_id}}",
    response=responses({200: JobOut}),
    summary="One job: status, progress, error code (viewer and above)",
    operation_id="jobs_get",
)
def jobs_get(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, job_id: uuid.UUID
) -> JobOut:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    return job_out(project, in_project(Job, project, job_id))


@router.post(
    f"{_BASE}/{{job_id}}/cancel",
    response=responses({200: JobOut}),
    summary="Cancel a queued job now, or ask a running one to stop (editor and above)",
    operation_id="jobs_cancel",
)
def jobs_cancel(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, job_id: uuid.UUID
) -> JobOut:
    membership = member(request, org_id, Role.EDITOR)
    project = project_of(membership, project_id)
    job = in_project(Job, project, job_id)
    try:
        outcome = services.request_cancel(
            organization=membership.organization,
            job_id=job.pk,
            actor=membership.user,
        )
    except JobPermissionError:
        raise ApiError(403, "Your role does not allow this.") from None
    if outcome is services.CancelOutcome.NOT_FOUND:
        raise not_found()
    if outcome is services.CancelOutcome.ALREADY_FINISHED:
        raise ApiError(409, "This job has already finished.")
    return job_out(project, in_project(Job, project, job_id))


@router.get(
    f"{_BASE}/{{job_id}}/stage-result",
    response=responses({200: StageResultOut}),
    summary="The result sections of a finished stage run (viewer and above)",
    operation_id="jobs_stage_result",
)
def jobs_stage_result(
    request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID, job_id: uuid.UUID
) -> Any:
    project = project_of(member(request, org_id, Role.VIEWER), project_id)
    job = in_project(Job, project, job_id, kind=JobKind.RUN_OPERATION.value)
    if job.status != JobStatus.SUCCEEDED or not isinstance(job.result, dict):
        raise ApiError(409, "This job has no result yet.")
    result = dict(job.result)
    # Ids read out of a JSON field are returned only if they resolve inside this project (3.2).
    named = {
        key: _uuid_or_none(result.get(key))
        for key in ("dataset_id", "parent_dataset_id")
    }
    found = set(
        DatasetRecord.objects.for_organization(project.organization_id)
        .filter(project=project, pk__in=[i for i in named.values() if i])
        .values_list("pk", flat=True)
    )
    for key, value in named.items():
        result[key] = str(value) if value in found else None
    return result
