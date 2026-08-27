# File: src/services/analysis_orchestrator_service.py
"""Guided Universal Data Scientist pipeline: stage-by-stage, human-checkpointed (milestone 9).

Encodes the ``UPLOAD -> UNDERSTAND -> CLEAN -> EXPLORE -> ANALYZE ->
VISUALIZE -> PREDICT -> EXPLAIN -> REPORT -> REPRODUCE`` workflow as an
explicit state machine over one dataset, per the confirmed decision
that Universal Data Scientist Mode ships as a **guided,
human-checkpointed pipeline, not a one-click autonomous run** (see
plans/defining-features-what-stateless-zebra.md). This service is glue,
not new statistics — every stage's actual work dispatches to a tool
already registered in :mod:`src.ai.tool_registry`, the same tools the
AI chat (:mod:`src.ai.assistant_service`) already calls, so a stage run
through the orchestrator and one run through a direct chat message
produce identical results and identical lineage.

The human-in-the-loop checkpoint itself (approve/skip/modify a
proposal before it runs) is a UI concern completed in milestone 10 —
this module's job is making that checkpoint *possible* by splitting
"what should happen next" (:meth:`AnalysisOrchestratorService.
propose_next_stage`) from "make it happen"
(:meth:`AnalysisOrchestratorService.run_stage`) as two separate calls,
rather than one opaque "run the whole pipeline" method a UI could not
interrupt between stages.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import plotly.graph_objects as go

from src.ai.tool_registry import get_tool_by_name
from src.analysis.explanation import Explanation
from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.services.workspace_service import Dataset, Visualization, WorkspaceService

_logger = get_logger(__name__)


class PipelineStage(str, Enum):
    """The ten stages of the Universal Data Scientist pipeline, in their fixed order."""

    UPLOAD = "upload"
    UNDERSTAND = "understand"
    CLEAN = "clean"
    EXPLORE = "explore"
    ANALYZE = "analyze"
    VISUALIZE = "visualize"
    PREDICT = "predict"
    EXPLAIN = "explain"
    REPORT = "report"
    REPRODUCE = "reproduce"


# The order propose_next_stage walks. UPLOAD is excluded — by the time
# any dataset_id exists for the orchestrator to reason about, a dataset
# has already been uploaded (see WorkspaceService, which is what
# populates dataset_id in the first place); this stage exists in the
# enum for completeness and UI display, not because the orchestrator
# itself ever proposes it. REPORT and REPRODUCE are excluded from
# auto-proposal for a different reason: both are explicit user actions
# (a "Generate Report" click, a "Reproduce" click — see milestone 13
# and :meth:`AnalysisOrchestratorService.reproduce` respectively), not
# stages the guided pipeline flows into automatically the way
# CLEAN -> EXPLORE -> ANALYZE do.
_AUTO_PROPOSED_STAGES: tuple[PipelineStage, ...] = (
    PipelineStage.UNDERSTAND,
    PipelineStage.CLEAN,
    PipelineStage.EXPLORE,
    PipelineStage.ANALYZE,
    PipelineStage.VISUALIZE,
    PipelineStage.PREDICT,
    PipelineStage.EXPLAIN,
)

_STAGE_RATIONALE: dict[PipelineStage, str] = {
    PipelineStage.UNDERSTAND: (
        "Profile the dataset first — row/column counts, missing values, "
        "and types — before deciding what cleaning or analysis makes sense."
    ),
    PipelineStage.CLEAN: (
        "Address data-quality issues found during UNDERSTAND (missing "
        "values, duplicates, ambiguous types) before analyzing, so results "
        "aren't skewed by fixable problems."
    ),
    PipelineStage.EXPLORE: (
        "Look at relationships between columns (crosstabs, grouped "
        "aggregates) before committing to a specific statistical test."
    ),
    PipelineStage.ANALYZE: (
        "Run a targeted statistical analysis (e.g. correlation) now that "
        "the data is understood and cleaned."
    ),
    PipelineStage.VISUALIZE: (
        "Build a chart of the analysis result — a visual is often clearer "
        "than a table of numbers for spotting what the analysis found."
    ),
    PipelineStage.PREDICT: (
        "If the dataset has a time dimension, forecast it — the "
        "orchestrator runs every applicable model and picks the best one "
        "by holdout accuracy (Automatic Model Competition)."
    ),
    PipelineStage.EXPLAIN: (
        "Every prior stage's result should be interpreted in plain "
        "language before reporting — this is the AI's role: interpret, "
        "not invent new numbers."
    ),
}


@dataclass
class StageProposal:
    """What :meth:`AnalysisOrchestratorService.propose_next_stage` recommends running next.

    Attributes:
        stage: The recommended next stage.
        rationale: Plain-language reason for the recommendation —
            deterministic, static text keyed by stage (see
            :data:`_STAGE_RATIONALE`) unless/until an AI layer is
            wired in to generate a dataset-specific rationale instead
            (the milestone plan's "asks the AI layer to propose what
            to run next" — the API shape here supports that without
            requiring it; see this module's own docstring).
    """

    stage: PipelineStage
    rationale: str


@dataclass
class AnalysisLogEntry:
    """One executed pipeline stage, recorded for Reproducible Analysis.

    Attributes:
        stage: Which pipeline stage this entry represents.
        tool_name: The :class:`~src.ai.tool_registry.ToolDefinition`
            name that was run, or ``None`` for an EXPLAIN entry (which
            records an :class:`~src.analysis.explanation.Explanation`
            directly rather than running a tool).
        inputs: The keyword arguments the tool was called with —
            exactly what :meth:`AnalysisOrchestratorService.reproduce`
            replays.
        outputs: A JSON-friendly summary of what the tool produced
            (see :meth:`AnalysisOrchestratorService.run_stage` for the
            exact shape per result type).
        explanation: The stage's :class:`~src.analysis.explanation.
            Explanation`, as a plain dict (``Explanation.to_dict()``),
            if one was supplied. ``None`` for stages run without an
            AI-generated interpretation attached.
        timestamp: ISO 8601 UTC timestamp of when this stage ran.
    """

    stage: PipelineStage
    tool_name: str | None
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    explanation: dict[str, Any] | None
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "tool_name": self.tool_name,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "explanation": self.explanation,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisLogEntry:
        return cls(
            stage=PipelineStage(data["stage"]),
            tool_name=data.get("tool_name"),
            inputs=dict(data.get("inputs", {})),
            outputs=dict(data.get("outputs", {})),
            explanation=data.get("explanation"),
            timestamp=data["timestamp"],
        )


@dataclass
class AnalysisLog:
    """Every stage run against one dataset, in order — the Reproducible Analysis record.

    Attributes:
        dataset_id: The :class:`~src.services.workspace_service.Dataset`
            this log belongs to. A log tracks one dataset's pipeline
            history; a derived dataset produced mid-pipeline (a
            cleaning stage's output) gets its own log entry recorded
            under whichever ``dataset_id`` was active for that
            :meth:`AnalysisOrchestratorService.run_stage` call, not
            retroactively merged into its parent's log — this mirrors
            how :class:`~src.services.workspace_service.Dataset`
            lineage itself works (a new dataset with
            ``parent_dataset_id`` set, not a mutation).
        entries: Every stage run, oldest first.
    """

    dataset_id: str
    entries: list[AnalysisLogEntry] = field(default_factory=list)

    def completed_stages(self) -> set[PipelineStage]:
        return {entry.stage for entry in self.entries}

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisLog:
        return cls(
            dataset_id=data["dataset_id"],
            entries=[AnalysisLogEntry.from_dict(e) for e in data.get("entries", [])],
        )


class AnalysisOrchestratorService:
    """Runs the guided pipeline's stages and tracks each dataset's :class:`AnalysisLog`.

    Args:
        workspace_service: Used to resolve datasets by ID and to
            register any new dataset/visualization a stage's tool
            produces — the same role it plays for
            :class:`~src.ai.assistant_service.AssistantService`.

    Session-scoped, in-memory state (one :class:`AnalysisLog` per
    dataset ID seen), matching :class:`WorkspaceService`'s own
    lifetime — register as a container singleton in
    :mod:`src.core.bootstrap` alongside it, per this repo's
    session-wide-service convention.
    """

    def __init__(self, workspace_service: WorkspaceService) -> None:
        self._workspace_service = workspace_service
        self._logs: dict[str, AnalysisLog] = {}

    def get_log(self, dataset_id: str) -> AnalysisLog:
        """Return ``dataset_id``'s log, creating an empty one if this is the first call for it."""
        return self._logs.setdefault(dataset_id, AnalysisLog(dataset_id=dataset_id))

    def load_log(self, log: AnalysisLog) -> None:
        """Install a log restored from a saved project.

        Used when a project is reopened (milestone 9's Reproducible
        Analysis persistence, wired via ``ProjectService`` — see that
        module's ``record_analysis_log``/``get_recorded_analysis_logs``)
        so a dataset's pipeline history survives a save/reload cycle
        rather than resetting every session.
        """
        self._logs[log.dataset_id] = log

    def propose_next_stage(self, dataset_id: str) -> StageProposal:
        """Recommend the next stage to run for ``dataset_id``, per its current log.

        Deterministic: proposes the first stage in
        :data:`_AUTO_PROPOSED_STAGES` order that has no log entry yet,
        with static rationale text. Once every auto-proposed stage has
        at least one entry, proposes REPORT (nothing further to
        automatically suggest — report generation and reproduction are
        explicit user actions, not proposals).

        This is a genuinely simple heuristic ("next unstarted stage"),
        not the fuller "what would actually be useful given what this
        specific dataset looks like" reasoning the milestone plan
        envisions the AI layer eventually providing — that requires
        wiring in a live :class:`~src.ai.assistant_service.
        AssistantService` call, which needs a configured provider (see
        milestone 7) to be meaningful and is therefore left as the
        integration point milestone 10's UI wires up, not invented
        here as an untestable stub.
        """
        log = self.get_log(dataset_id)
        completed = log.completed_stages()
        for stage in _AUTO_PROPOSED_STAGES:
            if stage not in completed:
                return StageProposal(stage=stage, rationale=_STAGE_RATIONALE[stage])
        return StageProposal(
            stage=PipelineStage.REPORT,
            rationale=(
                "Every pipeline stage has run at least once for this "
                "dataset. Ready to generate a report, or run any stage "
                "again with different parameters."
            ),
        )

    def run_stage(
        self,
        dataset_id: str,
        stage: PipelineStage,
        tool_name: str | None = None,
        tool_kwargs: dict[str, Any] | None = None,
        explanation: Explanation | None = None,
    ) -> AnalysisLogEntry:
        """Run one stage against ``dataset_id`` and append the result to its log.

        Args:
            dataset_id: Which dataset (already registered in
                ``WorkspaceService``) to run against.
            stage: Which pipeline stage this run represents. Only
                affects logging/labeling for most stages — the actual
                work is entirely determined by ``tool_name`` — except
                UNDERSTAND (always runs ``profile_dataset`` regardless
                of ``tool_name``) and EXPLAIN (never runs a tool at
                all; just records ``explanation``).
            tool_name: Which :mod:`src.ai.tool_registry` tool to run.
                Required for every stage except UNDERSTAND (defaults to
                ``"profile_dataset"``) and EXPLAIN (ignored).
            tool_kwargs: Keyword arguments for the tool.
            explanation: Required for an EXPLAIN-stage call; ignored
                otherwise.

        Returns:
            The :class:`AnalysisLogEntry` just appended.

        Raises:
            ServiceError: If ``dataset_id`` is not registered in
                ``WorkspaceService``, ``stage`` is REPORT/REPRODUCE
                (both are explicit actions elsewhere, not something
                this method runs — see :meth:`reproduce` for
                REPRODUCE), ``tool_name`` is missing where required, or
                the underlying tool call itself fails (propagated
                unchanged — this method does not swallow tool errors
                the way :meth:`~src.ai.assistant_service.
                AssistantService._execute_tool` does, since there is no
                model here to hand a recoverable error back to; the
                caller, whether UI or a script, must handle it).
        """
        # get_dataset() itself raises ServiceError with a clear message
        # if dataset_id is not currently loaded — no redundant None
        # check needed here, unlike src.ai.assistant_service's
        # WorkspaceService.get_active_dataset(), which does return
        # None for "nothing is active" (a different, valid state this
        # method's caller-supplied dataset_id can't be in).
        dataset = self._workspace_service.get_dataset(dataset_id)

        if stage in (PipelineStage.REPORT, PipelineStage.REPRODUCE):
            raise ServiceError(
                f"Stage {stage.value!r} is not run through run_stage() — "
                f"REPORT is milestone 13's ReportService, REPRODUCE is "
                f"this class's own reproduce() method."
            )

        tool_kwargs = dict(tool_kwargs or {})
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()

        if stage == PipelineStage.EXPLAIN:
            if explanation is None:
                raise ServiceError("run_stage(stage=EXPLAIN) requires an explanation.")
            entry = AnalysisLogEntry(
                stage=stage,
                tool_name=None,
                inputs={},
                outputs={},
                explanation=explanation.to_dict(),
                timestamp=timestamp,
            )
            self.get_log(dataset_id).entries.append(entry)
            return entry

        resolved_tool_name = tool_name or (
            "profile_dataset" if stage == PipelineStage.UNDERSTAND else None
        )
        if resolved_tool_name is None:
            raise ServiceError(f"run_stage(stage={stage.value!r}) requires tool_name.")

        try:
            tool = get_tool_by_name(resolved_tool_name)
        except KeyError as exc:
            raise ServiceError(str(exc)) from exc

        result = tool.handler(dataset, **tool_kwargs)
        outputs = self._summarize_result(
            dataset_id, resolved_tool_name, tool_kwargs, result
        )

        entry = AnalysisLogEntry(
            stage=stage,
            tool_name=resolved_tool_name,
            inputs=tool_kwargs,
            outputs=outputs,
            explanation=None,
            timestamp=timestamp,
        )
        self.get_log(dataset_id).entries.append(entry)
        _logger.info(
            "Orchestrator ran stage=%s tool=%s for dataset %s.",
            stage.value,
            resolved_tool_name,
            dataset_id,
        )
        return entry

    def _summarize_result(
        self, dataset_id: str, tool_name: str, tool_kwargs: dict[str, Any], result: Any
    ) -> dict[str, Any]:
        """Turn a tool's raw return value into the JSON-friendly ``outputs`` dict logged in an entry.

        Mirrors :meth:`~src.ai.assistant_service.AssistantService.
        _execute_tool`'s ``Dataset``/``go.Figure`` special-casing —
        both register the produced object into ``WorkspaceService``
        rather than leaving that to the caller, since a stage's whole
        point is to leave the workspace in the state a human clicking
        "approve" on this proposal would expect.
        """
        if isinstance(result, Dataset):
            self._workspace_service.add_dataset(result)
            return {
                "new_dataset_id": result.dataset_id,
                "derivation_description": result.derivation_description,
            }
        if isinstance(result, go.Figure):
            visualization = Visualization(
                name=tool_kwargs.get("title") or f"{tool_name} chart",
                dataset_id=dataset_id,
                figure=result,
                chart_type=str(tool_kwargs.get("chart_type", "")),
                chart_parameters=dict(tool_kwargs),
            )
            self._workspace_service.add_visualization(visualization)
            return {"visualization_id": visualization.visualization_id}
        if isinstance(result, dict):
            return result
        return {"result": result}

    def reproduce(self, dataset_id: str) -> list[AnalysisLogEntry]:
        """Replay every logged tool-call stage for ``dataset_id``, producing a fresh set of entries.

        The Reproducible Analysis feature: re-runs each entry's exact
        ``tool_name``/``inputs`` in original order. When a replayed
        CLEAN stage's tool produces a new derived dataset, subsequent
        replayed entries run against *that* new dataset — matching
        what actually happened the first time (a chain of derived
        datasets, not repeated mutation of one).

        EXPLAIN entries are skipped (nothing to re-run — they hold a
        recorded interpretation, not a tool call); the returned list
        contains only entries with an actual tool call replayed.

        Returns:
            The newly created entries (already appended to the log of
            whichever dataset each one ran against — not necessarily
            all under ``dataset_id`` itself, if the chain produced
            derived datasets along the way).

        Raises:
            ServiceError: If ``dataset_id`` has no log, or if any
                replayed stage's tool call fails (propagates
                unchanged, same as :meth:`run_stage`) — a reproduction
                that silently diverges partway through would defeat
                the point of the feature.
        """
        original_log = self._logs.get(dataset_id)
        if original_log is None:
            raise ServiceError(
                f"No analysis log recorded for dataset id: {dataset_id!r}"
            )

        replayed: list[AnalysisLogEntry] = []
        current_dataset_id = dataset_id
        # Snapshot with list(...) rather than iterating original_log.entries
        # directly: whenever a replayed stage stays on the same
        # dataset_id (e.g. re-running UNDERSTAND, which never produces a
        # new dataset), run_stage() below appends its new entry onto
        # this exact same list via self.get_log(dataset_id) — iterating
        # the live list would then also visit that just-appended entry
        # on the next step, replaying stages that were never part of
        # the original log at all.
        for original_entry in list(original_log.entries):
            if original_entry.tool_name is None:
                continue
            new_entry = self.run_stage(
                current_dataset_id,
                original_entry.stage,
                tool_name=original_entry.tool_name,
                tool_kwargs=original_entry.inputs,
            )
            if "new_dataset_id" in new_entry.outputs:
                current_dataset_id = new_entry.outputs["new_dataset_id"]
            replayed.append(new_entry)

        _logger.info(
            "Reproduced %d stage(s) from dataset %s's analysis log.",
            len(replayed),
            dataset_id,
        )
        return replayed
