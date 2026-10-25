# File: apps/api/uadas_api/web/stages.py
"""One router per ``PipelineStage``: the information architecture of the product, unchanged.

The routers are *generated from the core's enum* (``for stage in PipelineStage``), so the ten
stages of the desktop's pipeline are the ten tags and path segments of the web API and a stage added
to the core appears here without edits (``tests/test_web_stages.py`` fails if the committed schema
does not follow). Under ``/organizations/{org_id}/projects/{project_id}/stages/{stage}`` every stage has

* ``GET catalog`` -- what the stage can run, generated from the core registry
  (:mod:`uadas_api.stages.catalog`): name, description and the JSON-Schema of the parameters
  (so the web client builds the parameter form from it, as the desktop's dialog did);
* ``POST run`` -- only for a stage that has operations: validates ``operation`` and ``parameters``
  against that catalog, resolves the dataset through ``for_organization`` and the path's project,
  and **enqueues a ``run_operation`` job** (``202`` + job id). Nothing is computed in the request. The
  result is read from ``GET .../jobs/{job_id}/stage-result`` (the Phase 1.5 section model).

``upload`` (a multipart endpoint), ``report`` (its own resource) and ``reproduce`` (recipes and
lineage) expose a catalog with no operations and no ``run``: their routes are in ``datasets``,
``reports`` and ``pipeline``. ``explain`` has none because it needs an AI provider (3.7+). Expertise
hints per operation do not exist in the core (only per-stage weights in ``GuidanceService``), so the
catalog carries the orchestrator's stage rationale and nothing invented.

Runs are throttled per user and organization (``run`` scope) and need the editor role.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from django.core.exceptions import ValidationError
from django.http import HttpRequest
from ninja import Router, Schema, Status
from pydantic import Field, StringConstraints

from uadas_api import core_bridge
from uadas_api.accounts.models import Role
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.errors import IdempotencyConflictError, JobPermissionError
from uadas_api.jobs.services import create_job
from uadas_api.stages import catalog
from uadas_api.stages.catalog import OperationKind
from uadas_api.stages.run import new_dataset_id_for
from uadas_api.stages.serialize import EXPERTISE_NAMES, STAGE_NAMES
from uadas_api.web import throttle
from uadas_api.web.config import api_config
from uadas_api.web.errors import ApiError, responses
from uadas_api.web.scope import in_project, member, project_of, user_of
from uadas_api.workspaces.models import DatasetRecord
from uadas_core.services.analysis_orchestrator_service import PipelineStage

IdempotencyKey = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,64}$")]


class OperationOut(Schema):
    name: str
    description: str
    parameters: dict[str, Any]
    produces: Literal["dataset", "result", "figure"]


class CatalogOut(Schema):
    stage: STAGE_NAMES
    rationale: str
    operations: list[OperationOut]


class RunIn(Schema):
    operation: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    dataset_id: uuid.UUID
    parameters: dict[str, Any] = Field(default_factory=dict)
    expertise_level: EXPERTISE_NAMES = "analyst"
    idempotency_key: IdempotencyKey | None = None


class RunAcceptedOut(Schema):
    job_id: uuid.UUID
    status: str
    # The derived dataset's id (cleaning operations only): it exists once the job succeeds.
    dataset_id: uuid.UUID | None = None


def _catalog_out(stage: PipelineStage) -> CatalogOut:
    core_bridge.get_process_context()  # seeds the chart registry the build_chart enum reads
    return CatalogOut(
        stage=stage.value,
        rationale=catalog.stage_rationale(stage),
        operations=[
            OperationOut(
                name=op.name,
                description=op.description,
                parameters=op.parameters,
                produces=op.kind.value,
            )
            for op in catalog.operations(stage)
        ],
    )


def _stage_router(stage: PipelineStage) -> Router:
    router = Router(tags=[stage.value])
    base = f"/organizations/{{org_id}}/projects/{{project_id}}/stages/{stage.value}"

    @router.get(
        f"{base}/catalog",
        response=responses({200: CatalogOut}),
        summary=f"What the {stage.value} stage can run (viewer and above)",
        operation_id=f"stage_{stage.value}_catalog",
    )
    def catalog_view(
        request: HttpRequest, org_id: uuid.UUID, project_id: uuid.UUID
    ) -> CatalogOut:
        project_of(member(request, org_id, Role.VIEWER), project_id)
        return _catalog_out(stage)

    if catalog.STAGE_OPERATIONS[stage]:

        @router.post(
            f"{base}/run",
            response=responses({202: RunAcceptedOut}),
            summary=f"Run a {stage.value} operation as a job (editor and above)",
            operation_id=f"stage_{stage.value}_run",
        )
        def run_view(
            request: HttpRequest,
            org_id: uuid.UUID,
            project_id: uuid.UUID,
            payload: RunIn,
        ) -> Status[RunAcceptedOut]:
            membership = member(request, org_id, Role.EDITOR)
            project = project_of(membership, project_id)
            actor = user_of(membership)
            core_bridge.get_process_context()
            operation = catalog.find(stage, payload.operation)
            if operation is None:
                raise ApiError(422, "This stage has no such operation.")
            try:
                parameters = catalog.validate_parameters(
                    operation,
                    payload.parameters,
                    max_bytes=api_config().max_parameters_bytes,
                )
            except ValueError:
                raise ApiError(
                    422, "The parameters do not match this operation."
                ) from None
            dataset = in_project(DatasetRecord, project, payload.dataset_id)
            throttle.enforce("run", actor.pk, membership.organization_id)
            new_id = (
                new_dataset_id_for(project.organization_id, payload.idempotency_key)
                if operation.kind is OperationKind.DATASET
                else None
            )
            try:
                creation = create_job(
                    project=project,
                    actor=actor,
                    kind=JobKind.RUN_OPERATION.value,
                    params={
                        "stage": stage.value,
                        "operation": operation.name,
                        "dataset_id": str(dataset.pk),
                        "parameters": parameters,
                        "expertise_level": payload.expertise_level,
                        "new_dataset_id": new_id,
                    },
                    idempotency_key=payload.idempotency_key,
                )
            except JobPermissionError:
                raise ApiError(403, "Your role does not allow this.") from None
            except IdempotencyConflictError:
                raise ApiError(
                    409, "This idempotency key was used for a different request."
                ) from None
            except ValidationError:
                raise ApiError(422, "The request was not valid.") from None
            return Status(
                202,
                RunAcceptedOut(
                    job_id=creation.job.pk,
                    status=str(creation.job.status),
                    dataset_id=uuid.UUID(new_id) if new_id else None,
                ),
            )

    return router


STAGE_ROUTERS: dict[PipelineStage, Router] = {
    stage: _stage_router(stage) for stage in PipelineStage
}
