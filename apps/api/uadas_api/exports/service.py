# File: apps/api/uadas_api/exports/service.py
"""The ``build_report`` job: a ``Report`` row in, a file in object storage and a ``ready`` row out.

Why a job: PDF / Word / Excel export is slow and library-heavy, so the API only records the
request (``Report`` row ``pending`` + a ``Job``) and a worker renders it. The report's *content*
is not recomputed: it is read from the provenance rows the stage jobs wrote (``PipelineNode``
payloads: stage, operation, parameters, headline, summary lines) for the report's dataset, and
handed to the core's own exporter classes, so the files are the ones the desktop produced.

The same rules as the other jobs: parameters are ids only and are re-resolved through
``for_organization`` plus the job's project in the worker; the file is written under a new key
(``<org>/exports/<report>/<token>.<ext>``) and the row flips to ``ready`` *in the transaction
that marks the job succeeded*; if anything fails the file is deleted (or queued) and a job that
ends failed or cancelled marks the report ``failed``.

Not in 3.6 (stated, not stubbed): figures inside a report (a node keeps no figure; the core's
exporters would need kaleido in the worker) and the AI "explain" narrative (no provider here).
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from uadas_api.accounts.models import User
from uadas_api.exports.choices import ReportStatus
from uadas_api.exports.models import Report
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.errors import JobError, JobErrorCode
from uadas_api.jobs.models import Job
from uadas_api.jobs.registry import Completion, JobContext, JobHandler
from uadas_api.jobs.services import JobCreation, create_job
from uadas_api.pipeline.models import PipelineNode
from uadas_api.stages import frames
from uadas_api.storage import keys
from uadas_api.storage.errors import InvalidKeyError
from uadas_api.storage.store import get_store
from uadas_api.workspaces.models import DatasetRecord, Project
from uadas_core.core.expertise_level import ExpertiseLevel
from uadas_core.reports.report_content import ReportContent, ReportSection
from uadas_core.services.analysis_orchestrator_service import PipelineStage

CONTENT_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "html": "text/html",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_CONFIG_FIELDS = frozenset({"dataset_id", "expertise_level", "included_stages"})
_STAGE_LABELS = {stage.value: stage.value.title() for stage in PipelineStage}


def exporters() -> dict[str, Any]:
    """format -> the core exporter class (imported lazily: they pull in reportlab, docx, openpyxl)."""
    from uadas_core.reports.excel_exporter import ExcelReportExporter
    from uadas_core.reports.html_exporter import HtmlReportExporter
    from uadas_core.reports.pdf_exporter import PdfReportExporter
    from uadas_core.reports.word_exporter import WordReportExporter

    return {
        "pdf": PdfReportExporter,
        "html": HtmlReportExporter,
        "docx": WordReportExporter,
        "xlsx": ExcelReportExporter,
    }


def _invalid(what: str) -> ValidationError:
    return ValidationError(f"invalid report parameter: {what}", code="invalid_report")


def clean_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Shape of a report's ``config`` (ids, a level, optional stage names); no database."""
    if set(config) != _CONFIG_FIELDS:
        raise _invalid("config fields")
    try:
        dataset_id = keys.uuid_text(config["dataset_id"], "dataset id")
        level = ExpertiseLevel(config["expertise_level"]).value
    except (InvalidKeyError, ValueError):
        raise _invalid("dataset or expertise level") from None
    stages = config["included_stages"]
    if stages is not None:
        if not isinstance(stages, list) or not all(
            isinstance(s, str) and s in _STAGE_LABELS for s in stages
        ):
            raise _invalid("included_stages")
        stages = sorted(set(stages))
    return {
        "dataset_id": dataset_id,
        "expertise_level": level,
        "included_stages": stages,
    }


def validate_params(organization_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """The registry's creation-time check: one ``report_id`` that is this organization's."""
    if set(params) != {"report_id"}:
        raise _invalid("fields")
    try:
        report_id = keys.uuid_text(params["report_id"], "report id")
    except InvalidKeyError:
        raise _invalid("report id") from None
    if (
        not Report.objects.for_organization(organization_id)
        .filter(pk=report_id)
        .exists()
    ):
        raise _invalid("report")
    return {"report_id": report_id}


def request_report(
    *,
    project: Project,
    actor: User,
    title: str,
    report_format: str,
    dataset: DatasetRecord,
    expertise_level: str,
    included_stages: list[str] | None,
    idempotency_key: str | None = None,
) -> tuple[Report, JobCreation]:
    """Create the ``pending`` Report and its job together (one transaction); returns both."""
    config = clean_config(
        {
            "dataset_id": str(dataset.pk),
            "expertise_level": expertise_level,
            "included_stages": included_stages,
        }
    )
    with transaction.atomic():
        report = Report.objects.create(
            organization_id=project.organization_id,
            project=project,
            title=title,
            format=report_format,
            status=ReportStatus.PENDING,
            config=config,
        )
        creation = create_job(
            project=project,
            actor=actor,
            kind=JobKind.BUILD_REPORT.value,
            params={"report_id": str(report.pk)},
            idempotency_key=idempotency_key or f"report-{report.pk}",
        )
    return report, creation


def _sections(
    org: str, project: Project, record: DatasetRecord, stages: list[str] | None
) -> list[ReportSection]:
    nodes = (
        PipelineNode.objects.for_organization(org)
        .filter(project=project, dataset=record)
        .order_by("created_at", "pk")
    )
    sections: list[ReportSection] = []
    for node in nodes:
        payload = node.payload if isinstance(node.payload, dict) else {}
        stage = payload.get("stage")
        if not isinstance(stage, str) or stage not in _STAGE_LABELS:
            continue  # a bare dataset node: nothing was run
        if stages is not None and stage not in stages:
            continue
        summary = payload.get("summary")
        lines = [str(x) for x in summary] if isinstance(summary, list) else []
        headline = payload.get("headline")
        if isinstance(headline, str) and headline:
            lines.insert(0, headline)
        sections.append(
            ReportSection(
                stage_label=_STAGE_LABELS[stage],
                tool_name=str(payload.get("operation") or "") or None,
                timestamp=node.created_at.isoformat(),
                summary_lines=lines,
            )
        )
    return sections


def build_report(ctx: JobContext) -> Completion:
    """The worker body of a ``build_report`` job. See the module docstring."""
    org = keys.organization_id(ctx.organization.pk)
    try:
        params = validate_params(org, ctx.params)
    except ValidationError:
        raise JobError(JobErrorCode.INVALID_REQUEST) from None
    report = (
        Report.objects.for_organization(org)
        .filter(pk=params["report_id"], project=ctx.project)
        .first()
    )
    if report is None:
        raise JobError(JobErrorCode.NOT_FOUND)
    if report.status != ReportStatus.PENDING or report.format not in CONTENT_TYPES:
        raise JobError(JobErrorCode.CONFLICT)
    try:
        config = clean_config(report.config)
    except ValidationError:
        raise JobError(JobErrorCode.INVALID_REQUEST) from None
    record = (
        DatasetRecord.objects.for_organization(org)
        .filter(pk=config["dataset_id"], project=ctx.project)
        .first()
    )
    if record is None:
        raise JobError(JobErrorCode.NOT_FOUND)

    store = get_store(org)
    ctx.report(15, "Reading the dataset", force=True)
    with frames.open_frame(store, record) as handle:
        names = frames.column_names(frames.parquet_file(handle))
    content = ReportContent(
        title=report.title,
        dataset_name=record.name,
        dataset_summary={
            "Rows": record.row_count,
            "Columns": record.column_count,
            "Source format": record.source_format,
            "Column names": ", ".join(names),
        },
        expertise_level=ExpertiseLevel(config["expertise_level"]),
        sections=_sections(org, ctx.project, record, config["included_stages"]),
    )
    ctx.check_cancelled()
    ctx.report(40, "Building the file", force=True)
    extension = report.format
    key = keys.export_key(org, report.pk, extension)
    with tempfile.TemporaryDirectory(prefix="uadas-report-") as scratch:
        path = exporters()[report.format].export(
            content, Path(scratch) / f"report.{extension}"
        )
        ctx.check_cancelled()
        ctx.report(80, "Saving the file", force=True)
        with Path(path).open("rb") as handle:
            stored = store.put(
                key,
                handle,
                content_type=CONTENT_TYPES[report.format],
                allowed_content_types=(CONTENT_TYPES[report.format],),
            )
    report_id = report.pk

    def commit() -> None:
        row = Report.objects.for_organization(org).get(pk=report_id)
        row.status = ReportStatus.READY
        row.storage_key = key
        row.save()

    def cleanup() -> None:
        from uadas_api.ingest.service import retire_frame

        retire_frame(org, store, key)

    return Completion(
        result={
            "report_id": str(report_id),
            "storage_key": key,
            "size_bytes": stored.size,
        },
        commit=commit,
        cleanup=cleanup,
    )


def abandon_report(job: Job) -> None:
    """A job ended failed or cancelled for good: its report will never be ready."""
    try:
        params = validate_params(job.organization_id, job.params)
    except ValidationError:
        return
    Report.objects.for_organization(job.organization_id).filter(
        pk=params["report_id"], status=ReportStatus.PENDING
    ).update(status=ReportStatus.FAILED)


HANDLER = JobHandler(
    validate_params=validate_params, run=build_report, on_abandon=abandon_report
)
