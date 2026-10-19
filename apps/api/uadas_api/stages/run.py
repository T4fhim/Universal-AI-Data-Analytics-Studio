# File: apps/api/uadas_api/stages/run.py
"""The ``run_operation`` job: one catalog operation on one stored dataset, in a worker.

The pipeline, and the rule it keeps (**a failure at any step leaves no ``DatasetRecord``, no
provenance row and no stored frame**):

1. *Re-validate* the parameters the API stored (shape, stage, operation in that stage's catalog,
   parameters against the operation's schema). The worker trusts nothing it did not just check.
2. *Resolve the dataset* through ``DatasetRecord.objects.for_organization(org)`` **and** the job's
   project, then load its frame from the tenant's object store (verified SHA-256, row cap).
3. *Run* the core operation (:mod:`uadas_api.stages.execute`): the same tool the AI chat calls, so
   validation, lineage and results are identical. A core failure (``ServiceError``, bad data) is the
   closed code ``operation_failed``; its text is never stored.
4. *Describe* the outcome as the result-section model (:mod:`uadas_api.stages.serialize`) and put it
   on the job's ``result`` (bounded: ``ApiConfig.stage_max_result_bytes``).
5. A *cleaning* operation returns a derived dataset. It is written to a new, never-reused key
   (``<org>/datasets/<new id>/frames/j<attempt>-<job>.parquet``) and the ``DatasetRecord`` --
   ``parent_dataset_id`` = the source and ``derivation_description`` from the core, the
   non-mutating rule -- is created **in the transaction that marks the job succeeded**, together
   with the provenance node and edge. Every other operation records one artifact node and edge.

Heavy computation lives here and only here: a web request never runs a statistic. The derived
dataset's id is chosen when the job is *created* (``new_dataset_id``) so a job that dies without
a chance to clean up can still be cleaned (:func:`abandon_run` queues that directory), exactly like
the ingest job's dataset id.
"""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from uadas_api import core_bridge
from uadas_api.jobs.errors import JobError, JobErrorCode
from uadas_api.jobs.models import Job
from uadas_api.jobs.registry import Completion, JobContext, JobHandler
from uadas_api.pipeline.models import PipelineEdge, PipelineNode
from uadas_api.sandbox.limits import SandboxLimits
from uadas_api.stages import catalog, frames
from uadas_api.stages.execute import execute
from uadas_api.stages.serialize import sections_to_dicts, summary_lines
from uadas_api.storage import keys, lifecycle
from uadas_api.storage.errors import InvalidKeyError
from uadas_api.storage.store import StoredObject, TenantObjectStore, get_store
from uadas_api.web.config import api_config
from uadas_api.workspaces.models import DatasetRecord, Project
from uadas_core.core.exceptions import ServiceError
from uadas_core.core.expertise_level import ExpertiseLevel
from uadas_core.models import Dataset
from uadas_core.services.analysis_orchestrator_service import PipelineStage

_logger = logging.getLogger(__name__)

FRAME_CONTENT_TYPE = "application/vnd.apache.parquet"
_PARAM_FIELDS = frozenset(
    {
        "stage",
        "operation",
        "dataset_id",
        "parameters",
        "expertise_level",
        "new_dataset_id",
    }
)


def _invalid(what: str) -> ValidationError:
    # Never echoes the value: it may be attacker-controlled text.
    return ValidationError(f"invalid run parameter: {what}", code="invalid_run")


def _clean(organization_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """Shape and meaning of ``params`` (no database): raises ``ValidationError`` for anything off."""
    if set(params) != _PARAM_FIELDS:
        raise _invalid("fields")
    try:
        stage = PipelineStage(params["stage"])
        level = ExpertiseLevel(params["expertise_level"])
    except ValueError:
        raise _invalid("stage or expertise level") from None
    name = params["operation"]
    operation = catalog.find(stage, name) if isinstance(name, str) else None
    if operation is None:
        raise _invalid("operation")
    try:
        dataset_id = keys.uuid_text(params["dataset_id"], "dataset id")
        parameters = catalog.validate_parameters(
            operation, params["parameters"], max_bytes=api_config().max_parameters_bytes
        )
        new_id = params["new_dataset_id"]
        if operation.kind is catalog.OperationKind.DATASET:
            new_id = keys.uuid_text(new_id, "new dataset id")
        elif new_id is not None:
            raise _invalid("new_dataset_id")
    except (InvalidKeyError, ValueError):
        raise _invalid("identifier or parameters") from None
    return {
        "stage": stage.value,
        "operation": operation.name,
        "dataset_id": dataset_id,
        "parameters": parameters,
        "expertise_level": level.value,
        "new_dataset_id": new_id,
    }


def validate_params(organization_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    """The registry's creation-time check: ``_clean`` plus 'the dataset belongs to the organization'."""
    cleaned = _clean(organization_id, params)
    if (
        not DatasetRecord.objects.for_organization(organization_id)
        .filter(pk=cleaned["dataset_id"])
        .exists()
    ):
        raise _invalid("dataset")
    return cleaned


# ------------------------------------------------------------------- provenance


def _dataset_node(project: Project, record: DatasetRecord) -> PipelineNode:
    scope = PipelineNode.objects.for_organization(project.organization_id)
    node = scope.filter(project=project, kind="dataset", dataset=record).first()
    if node is None:
        node = PipelineNode.objects.create(
            organization_id=project.organization_id,
            project=project,
            kind="dataset",
            label=record.name[:255],
            dataset=record,
        )
    return node


def _link(project: Project, source: PipelineNode, target: PipelineNode) -> None:
    PipelineEdge.objects.create(
        organization_id=project.organization_id,
        project=project,
        source=source,
        target=target,
        kind="transform",
    )


def _record_provenance(
    project: Project,
    source: DatasetRecord,
    derived: DatasetRecord | None,
    payload: dict[str, Any],
    label: str,
) -> None:
    source_node = _dataset_node(project, source)
    if derived is not None:
        node = PipelineNode.objects.create(
            organization_id=project.organization_id,
            project=project,
            kind="dataset",
            label=derived.name[:255],
            dataset=derived,
            payload=payload,
        )
    else:
        node = PipelineNode.objects.create(
            organization_id=project.organization_id,
            project=project,
            kind="artifact",
            label=label[:255],
            dataset=source,
            payload=payload,
        )
    _link(project, source_node, node)


# ------------------------------------------------------------------- the handler


def _write_derived(
    store: TenantObjectStore, key: str, dataset: Dataset, limits: SandboxLimits
) -> StoredObject:
    with tempfile.TemporaryDirectory(prefix="uadas-run-") as scratch:
        path = Path(scratch) / "frame.parquet"
        dataset.dataframe.to_parquet(path, index=False)
        with path.open("rb") as handle:
            return store.put(
                key,
                handle,
                content_type=FRAME_CONTENT_TYPE,
                allowed_content_types=(FRAME_CONTENT_TYPE,),
                max_bytes=limits.max_output_bytes,
            )


def _retire(organization_id: str, store: TenantObjectStore, key: str) -> None:
    from uadas_api.ingest.service import retire_frame

    retire_frame(organization_id, store, key)


def run_operation(ctx: JobContext) -> Completion:
    """The worker body of a ``run_operation`` job. See the module docstring."""
    cfg = api_config()
    org = keys.organization_id(ctx.organization.pk)
    try:
        params = _clean(org, ctx.params)
    except ValidationError:
        raise JobError(JobErrorCode.INVALID_REQUEST) from None
    stage = PipelineStage(params["stage"])
    operation = catalog.find(stage, params["operation"])
    if operation is None:
        raise JobError(JobErrorCode.INVALID_REQUEST)
    record = (
        DatasetRecord.objects.for_organization(org)
        .filter(pk=params["dataset_id"], project=ctx.project)
        .first()
    )
    if record is None:
        raise JobError(JobErrorCode.NOT_FOUND)
    core_bridge.get_process_context()  # seeds the chart / operation / renderer registries
    store = get_store(org)
    ctx.report(10, "Loading the dataset", force=True)
    frame = frames.load_dataframe(store, record, cfg.stage_max_rows)
    source = Dataset(
        name=record.name,
        dataframe=frame,
        source_format=record.source_format,
        dataset_id=str(record.pk),
        parent_dataset_id=(
            str(record.parent_dataset_id) if record.parent_dataset_id else None
        ),
    )
    ctx.check_cancelled()
    ctx.report(35, "Running the operation", force=True)
    try:
        executed = execute(
            operation,
            source,
            params["parameters"],
            ExpertiseLevel(params["expertise_level"]),
        )
    except (ServiceError, ValueError, KeyError, ArithmeticError) as error:
        # The class only: the core's text can quote a column value of the tenant's data.
        _logger.warning("a stage operation failed (%s)", type(error).__name__)
        raise JobError(JobErrorCode.OPERATION_FAILED) from None
    ctx.check_cancelled()
    ctx.report(75, "Saving the result", force=True)

    derived = executed.derived
    new_id: str | None = params["new_dataset_id"]
    result: dict[str, Any] = {
        "stage": stage.value,
        "operation": operation.name,
        "kind": operation.kind.value,
        "title": executed.title,
        "headline": executed.headline,
        "expertise_level": params["expertise_level"],
        "sections": sections_to_dicts(executed.sections),
        "dataset_id": new_id if derived is not None else None,
        "parent_dataset_id": str(record.pk) if derived is not None else None,
    }
    if len(json.dumps(result)) > cfg.stage_max_result_bytes:
        raise JobError(JobErrorCode.OUTPUT_TOO_LARGE)

    frame_key: str | None = None
    stored: StoredObject | None = None
    if derived is not None and new_id is not None:
        derived.dataset_id = new_id
        frame_key = keys.dataset_frame_key(
            org, new_id, f"j{ctx.job.attempts:03d}-{ctx.job.pk.hex}"
        )
        stored = _write_derived(
            store, frame_key, derived, SandboxLimits.from_settings()
        )
    try:
        ctx.check_cancelled()
    except BaseException:
        if frame_key is not None:
            _retire(org, store, frame_key)
        raise

    project = ctx.project
    job_id = str(ctx.job.pk)
    payload = {
        "stage": stage.value,
        "operation": operation.name,
        "parameters": params["parameters"],
        "job_id": job_id,
        "headline": executed.headline,
        # What a report prints for this step: bounded (a node payload is not a result store).
        "summary": [line[:300] for line in summary_lines(result["sections"])[:40]],
    }

    def commit() -> None:  # inside the transaction that marks the job succeeded
        created: DatasetRecord | None = None
        if derived is not None and stored is not None and frame_key is not None:
            try:
                created = DatasetRecord.objects.create(
                    id=new_id,
                    organization_id=org,
                    project=project,
                    name=derived.name[:255],
                    source_format=record.source_format,
                    parent_dataset_id=record.pk,
                    derivation_description=derived.derivation_description or "",
                    storage_key=frame_key,
                    sha256=stored.sha256 or "",
                    row_count=derived.row_count,
                    column_count=derived.column_count,
                )
            except IntegrityError:
                raise JobError(JobErrorCode.CONFLICT) from None
        _record_provenance(project, record, created, payload, executed.title)

    cleanup = None
    if frame_key is not None:
        key_to_retire = frame_key
        cleanup = lambda: _retire(org, store, key_to_retire)

    return Completion(
        result=result,
        commit=commit,
        cleanup=cleanup,
        max_result_bytes=cfg.stage_max_result_bytes,
    )


def abandon_run(job: Job) -> None:
    """A job ended failed or cancelled for good: queue the derived dataset's directory, if one was planned."""
    org = str(job.organization_id)
    try:
        params = _clean(org, job.params)
    except ValidationError:
        return
    new_id = params["new_dataset_id"]
    if new_id is None:
        return
    if DatasetRecord.objects.for_organization(org).filter(pk=new_id).exists():
        return
    prefix = f"{org}/datasets/{new_id}"
    with transaction.atomic():
        lifecycle.queue_deletions(org, [(prefix, True)], reason="run_failed")


def new_dataset_id_for(organization_id: uuid.UUID, idempotency_key: str | None) -> str:
    """The derived dataset's id: fresh, or derived from the idempotency key so a retry matches."""
    if idempotency_key is None:
        return str(uuid.uuid4())
    return str(uuid.uuid5(organization_id, f"run:{idempotency_key}"))


HANDLER = JobHandler(
    validate_params=validate_params, run=run_operation, on_abandon=abandon_run
)
