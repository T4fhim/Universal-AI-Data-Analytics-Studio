# File: uadas_core/provenance/recipe.py
"""The portable Recipe: the lineage DAG with every function of the data removed.

:mod:`~uadas_core.provenance.dag` keeps result payloads (``outputs``) verbatim
so the DAG can answer "show me the result as it was". A **Recipe** is the
opposite trade-off: structure + operations + parameters only, no ``outputs``
and no DataFrames, so it replays on a *fresh* dataset with a compatible schema
(spec §2). This is the substrate Phase 5's replayable-recipe feature (F2) and
local-first privacy story (F10, "the server stores the Recipe, never the
data") build on.

:func:`analysis_logs_to_recipe` flattens the root→derived chain of
:class:`~uadas_core.services.analysis_orchestrator_service.AnalysisLog`\\ s
(via :func:`_creation_order`) into one :class:`RecipeStep` per entry, then
:func:`recipe_to_analysis_logs` (added in Task 6) rebuilds an equivalent log
chain on replay, re-minting the dataset ids the ``outputs`` used to carry.

``RecipeStep.timestamp`` is provenance-of-origin — *when the original step
ran* — not a replay clock; nothing in replay reads it.

Scope for 1.7 (spec §5): **linear chains only** — :func:`_creation_order` raises
if the log set is a forest (>1 root), fans out (a log with >1 dataset-producing
entry, e.g. a clean stage re-run with different params), or is disconnected /
cyclic (fewer logs reachable from the root than exist). Deterministic tools
only, no partial replay, and ``source_dataset.schema`` is left ``{}`` (it needs
a live DataFrame — Phase 3). Recipe *disk* persistence is also Phase 3; 1.7
ships the in-memory converters plus ``to_dict`` / ``from_dict``.

Note: which dataset each entry *ran against* is **not** preserved through a
Recipe round-trip — :func:`recipe_to_analysis_logs` normalizes the chain,
re-partitioning entries into per-dataset logs at each producing step. The C-2
contract (spec §3.3) compares the flattened creation-order entry *sequence*,
not the log grouping.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from uadas_core.core.exceptions import ServiceError
from uadas_core.provenance.dag import DatasetMeta
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisLog,
    AnalysisLogEntry,
    PipelineStage,
)

_STEP_LABELS: dict[tuple[str, str | None], str] = {
    ("understand", "profile_dataset"): "Profile the dataset",
    ("clean", "drop_missing_values"): "Remove rows with missing values",
    ("clean", "drop_duplicates"): "Remove duplicate rows",
    ("explore", "aggregate"): "Aggregate the data",
    ("analyze", "profile_dataset"): "Re-profile the derived dataset",
    ("visualize", "build_chart"): "Build a chart",
    ("explain", None): "Record an explanation",
}


def _label_for(stage: str, tool_name: str | None) -> str:
    """A short human label for a step — static lookup, else ``"<stage>: <tool>"``."""
    return _STEP_LABELS.get((stage, tool_name), f"{stage}: {tool_name}")


@dataclass
class RecipeStep:
    """One operation in a :class:`Recipe` — a log entry minus its ``outputs``.

    ``id`` is positional (``"s1"``, ``"s2"``, …) and stable across a
    re-export of the same chain (spec §5 / §R0.4 CHANGE 6), so Phase 5
    comments (F9) and re-pointing a recipe at next month's file (F2) can
    anchor to it. There is deliberately **no ``outputs`` field**.
    """

    id: str
    label: str
    stage: str
    tool_name: str | None
    inputs: dict[str, Any]
    produces_dataset: bool
    explanation: dict[str, Any] | None
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "stage": self.stage,
            "tool_name": self.tool_name,
            "inputs": dict(self.inputs),
            "produces_dataset": self.produces_dataset,
            "explanation": self.explanation,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecipeStep:
        """Rebuild a step, validating the timestamp the same way :class:`AnalysisLogEntry` does.

        ``recipe_to_analysis_logs`` constructs :class:`AnalysisLogEntry` objects
        *directly* from these steps (not via ``AnalysisLogEntry.from_dict``), so
        a malformed ``timestamp`` in a Recipe payload would otherwise ride
        straight into the rebuilt log chain — the exact silent path the 1.7
        timestamp validation exists to close. ``produces_dataset`` is a required
        key (``to_dict`` always writes it); a missing one would silently collapse
        a derived-dataset boundary on replay.
        """
        timestamp = data["timestamp"]
        try:
            datetime.datetime.fromisoformat(timestamp)
        except (TypeError, ValueError) as exc:
            raise ServiceError(
                f"RecipeStep.timestamp is not an ISO-8601 string: {timestamp!r}"
            ) from exc
        return cls(
            id=data["id"],
            label=data.get("label", ""),
            stage=data["stage"],
            tool_name=data.get("tool_name"),
            inputs=dict(data.get("inputs", {})),
            produces_dataset=bool(data["produces_dataset"]),
            explanation=data.get("explanation"),
            timestamp=timestamp,
        )


@dataclass
class Recipe:
    """A replayable, data-free description of one analysis chain (spec §2)."""

    version: str = "1.0"
    name: str = ""
    description: str = ""
    source_dataset: dict[str, Any] = field(default_factory=dict)
    steps: list[RecipeStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "source_dataset": dict(self.source_dataset),
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recipe:
        return cls(
            version=data.get("version", "1.0"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            source_dataset=dict(data.get("source_dataset", {})),
            steps=[RecipeStep.from_dict(s) for s in data.get("steps", [])],
        )


def _creation_order(logs: list[AnalysisLog]) -> list[AnalysisLog]:
    """Root-first linear chain of logs, following each producing entry's ``new_dataset_id``.

    The root is the one log whose ``dataset_id`` is never another entry's
    ``new_dataset_id``. A ``new_dataset_id`` with no matching log (the derived
    dataset was never worked on) is a clean stop, mirroring the DAG's
    dangling-reference tolerance.

    1.7 handles **linear chains only** (spec §5); every non-linear shape raises
    :class:`ServiceError`:

    * ``!= 1`` root → an empty set or a forest.
    * any log with ``> 1`` dataset-producing entry → a fan-out (a clean stage
      re-run with different params branches the lineage). The single-root check
      misses this — the log is still the sole root.
    * ``len(ordered) != len(logs)`` after the walk → a disconnected log
      (unreachable from the root) or a cycle among log ids (the walk stops early
      on the visited-set guard).
    """
    produced = {
        e.outputs["new_dataset_id"]
        for log in logs
        for e in log.entries
        if "new_dataset_id" in e.outputs
    }
    roots = [log for log in logs if log.dataset_id not in produced]
    if len(roots) != 1:
        raise ServiceError(
            f"analysis_logs_to_recipe expects a single root log, found {len(roots)} "
            "(recipe branching is out of scope for Phase 1.7)"
        )
    fan_out = [
        log.dataset_id
        for log in logs
        if sum("new_dataset_id" in e.outputs for e in log.entries) > 1
    ]
    if fan_out:
        raise ServiceError(
            f"log(s) {fan_out} each produced more than one dataset — recipe "
            "branching is out of scope for Phase 1.7 (linear chains only)"
        )
    by_id = {log.dataset_id: log for log in logs}
    ordered: list[AnalysisLog] = []
    current: AnalysisLog | None = roots[0]
    seen: set[str] = set()
    while current is not None and current.dataset_id not in seen:
        seen.add(current.dataset_id)
        ordered.append(current)
        nxt: AnalysisLog | None = None
        for e in current.entries:
            if "new_dataset_id" in e.outputs:
                nxt = by_id.get(e.outputs["new_dataset_id"])
        current = nxt
    if len(ordered) != len(logs):
        raise ServiceError(
            f"analysis log set is not a single linear chain "
            f"({len(ordered)} of {len(logs)} logs reachable from the root) — "
            "a disconnected or cyclic log set is out of scope for Phase 1.7"
        )
    return ordered


def analysis_logs_to_recipe(
    logs: list[AnalysisLog],
    datasets: Mapping[str, DatasetMeta] | None = None,
    *,
    name: str = "",
    description: str = "",
) -> Recipe:
    """Flatten a root→derived :class:`AnalysisLog` chain into a :class:`Recipe`.

    One :class:`RecipeStep` per log entry, in creation order;
    ``produces_dataset`` is ``"new_dataset_id" in entry.outputs`` (the same
    single predicate the DAG uses).

    :param datasets: Optional :class:`DatasetMeta` by id. When it holds the
        root's id, ``source_dataset`` carries that dataset's real shape;
        otherwise ``source_dataset`` is ``partial`` with ``None`` fields — the
        converter has no DataFrame of its own to measure. ``schema`` is always
        ``{}`` (it needs a live DataFrame — Phase 3).
    """
    ordered = _creation_order(list(logs))
    root_meta = (datasets or {}).get(ordered[0].dataset_id)
    source_dataset: dict[str, Any] = {
        "name": root_meta.name if root_meta else None,
        "row_count": root_meta.row_count if root_meta else None,
        "column_count": root_meta.column_count if root_meta else None,
        "source_format": root_meta.source_format if root_meta else None,
        "partial": root_meta.partial if root_meta else True,
        "schema": {},
    }

    steps: list[RecipeStep] = []
    for log in ordered:
        for entry in log.entries:
            steps.append(
                RecipeStep(
                    id=f"s{len(steps) + 1}",
                    label=_label_for(entry.stage.value, entry.tool_name),
                    stage=entry.stage.value,
                    tool_name=entry.tool_name,
                    inputs=dict(entry.inputs),
                    produces_dataset="new_dataset_id" in entry.outputs,
                    explanation=entry.explanation,
                    timestamp=entry.timestamp,
                )
            )

    return Recipe(
        name=name, description=description, source_dataset=source_dataset, steps=steps
    )


def recipe_to_analysis_logs(
    data: dict[str, Any], *, new_root_dataset_id: str
) -> list[AnalysisLog]:
    """Replay a :meth:`Recipe.to_dict` payload into an equivalent AnalysisLog chain.

    Walk ``steps`` in order against a fresh root log for
    ``new_root_dataset_id``. A ``produces_dataset`` step's entry lands in the
    *current* log with ``outputs = {"new_dataset_id": <fresh uuid4>}`` and
    opens a new derived log; every other step's entry gets ``outputs = {}``.
    ``outputs`` is intentionally re-minted rather than carried: it is a
    function of the data the Recipe deliberately dropped, and
    :meth:`~uadas_core.services.analysis_orchestrator_service.AnalysisOrchestratorService.reproduce`
    regenerates the real values when the chain is actually re-executed. An
    empty ``steps`` list yields a single empty log for the root id.
    """
    recipe = Recipe.from_dict(data)
    root = AnalysisLog(dataset_id=new_root_dataset_id)
    logs: list[AnalysisLog] = [root]
    current = root
    for step in recipe.steps:
        try:
            stage = PipelineStage(step.stage)
        except ValueError as exc:
            raise ServiceError(
                f"Recipe step {step.id!r} has an unknown pipeline stage: {step.stage!r}"
            ) from exc
        outputs: dict[str, Any] = {}
        minted: str | None = None
        if step.produces_dataset:
            minted = str(uuid.uuid4())
            outputs = {"new_dataset_id": minted}
        current.entries.append(
            AnalysisLogEntry(
                stage=stage,
                tool_name=step.tool_name,
                inputs=dict(step.inputs),
                outputs=outputs,
                explanation=step.explanation,
                timestamp=step.timestamp,
            )
        )
        if minted is not None:
            current = AnalysisLog(dataset_id=minted)
            logs.append(current)
    return logs
