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

Scope for 1.7 (spec §5): linear chains only (a forest raises), deterministic
tools only, no partial replay, and ``source_dataset.schema`` is left ``{}``
(it needs a live DataFrame — Phase 3). Recipe *disk* persistence is also
Phase 3; 1.7 ships the in-memory converters plus ``to_dict`` / ``from_dict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from uadas_core.core.exceptions import ServiceError
from uadas_core.provenance.dag import analysis_logs_to_dag
from uadas_core.services.analysis_orchestrator_service import AnalysisLog

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
        return cls(
            id=data["id"],
            label=data.get("label", ""),
            stage=data["stage"],
            tool_name=data.get("tool_name"),
            inputs=dict(data.get("inputs", {})),
            produces_dataset=bool(data.get("produces_dataset", False)),
            explanation=data.get("explanation"),
            timestamp=data["timestamp"],
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
    """Root-first linear chain of logs, following each CLEAN's ``new_dataset_id``.

    The root is the one log whose ``dataset_id`` is never another entry's
    ``new_dataset_id``. More than one root → a forest, which is out of scope
    for 1.7 (spec §5) → :class:`ServiceError`. A ``new_dataset_id`` with no
    matching log (the derived dataset was never worked on) is a clean stop,
    mirroring the DAG's dangling-reference tolerance.
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
    return ordered


def analysis_logs_to_recipe(
    logs: list[AnalysisLog], *, name: str = "", description: str = ""
) -> Recipe:
    """Flatten a root→derived :class:`AnalysisLog` chain into a :class:`Recipe`.

    One :class:`RecipeStep` per log entry, in creation order;
    ``produces_dataset`` is ``"new_dataset_id" in entry.outputs`` (the same
    single predicate the DAG uses). ``source_dataset`` carries the root
    dataset's shape from the DAG's root node — ``schema`` stays ``{}`` (it
    needs a live DataFrame, out of scope for 1.7).
    """
    ordered = _creation_order(list(logs))
    # Build the DAG purely to reuse its root-node resolution — Recipe *is*
    # "the DAG minus data", so the source-dataset facts come from the same
    # place. datasets={} → the root meta is ``partial`` (all None) until a
    # live dataset is available; that is honest, not a gap to paper over.
    dag = analysis_logs_to_dag(ordered, {})
    root_meta = dag.roots()[0].meta
    source_dataset: dict[str, Any] = {
        "name": root_meta.name,
        "row_count": root_meta.row_count,
        "column_count": root_meta.column_count,
        "source_format": root_meta.source_format,
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
