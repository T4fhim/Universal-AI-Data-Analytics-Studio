# File: uadas_core/provenance/dag.py
"""Reshape the orchestrator's *set* of per-dataset AnalysisLogs into a lineage DAG.

:class:`~uadas_core.services.analysis_orchestrator_service.AnalysisOrchestratorService`
keeps one :class:`~uadas_core.services.analysis_orchestrator_service.AnalysisLog`
*per dataset* (``_logs: dict[str, AnalysisLog]``). A cleaning stage records its
entry in the **parent** dataset's log with ``new_dataset_id`` in ``outputs``;
work on the derived dataset lands in that dataset's own log. The flat
per-dataset shape hides the cross-dataset lineage that Phase 5's transparency
features (F1 provenance graph, F3 time-travel/fork) need — this module rebuilds
it as an explicit graph without changing anything the orchestrator does.

Three elements (spec §1 + §R0.4 CHANGE 3):

* :class:`DatasetNode` — one per dataset id mentioned anywhere in the log set.
* :class:`TransformEdge` — one per log entry that produced a derived dataset
  (``"new_dataset_id" in entry.outputs``); ``from`` = the enclosing log's
  ``dataset_id`` (not recoverable from the entry alone), ``to`` = the new id.
* :class:`ArtifactNode` — one per non-producing entry (a profile, chart, test,
  forecast, explanation), hanging off its dataset node so it too is an
  inspectable, comment-able thing (F1, F9).

**The one predicate** for "this entry is a transform edge" is
``"new_dataset_id" in entry.outputs`` — never the ``stage``. An ANALYZE stage
that happened to drop duplicates is still an edge; an EXPLAIN stage never is.

:func:`_reject_dataset_id_cycles` is a deliberate sibling of
:func:`uadas_core.services.workspace_service._reject_parent_cycles` and
:func:`uadas_core.persistence.persistence_service._reject_parent_dataset_id_cycles`:
same per-start visited-set walk, same "dangling parent is a clean stop, a
revisited id is a :class:`~uadas_core.core.exceptions.ServiceError`" rule. The
three are kept separate rather than shared because each guards a different
data structure at a different boundary (a ``Dataset`` list on workspace
restore, a ``Dataset`` map on project load, a ``{child: parent}`` link map
built from *both* metadata and edges here) — cross-importing would couple
three layers to force one signature to fit all of them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from uadas_core.core.exceptions import ServiceError
from uadas_core.services.analysis_orchestrator_service import AnalysisLog


@dataclass(frozen=True)
class DatasetMeta:
    """The dataset-level facts a :class:`DatasetNode` carries.

    Everything except ``dataset_id`` is optional: when the caller has no
    :class:`DatasetMeta` for an id the DAG mentions (a derived dataset that
    was never re-opened, a hand-edited log), :func:`analysis_logs_to_dag`
    synthesizes one with ``partial=True`` rather than raising — a lineage
    view is still useful with a gap in it.
    """

    dataset_id: str
    name: str | None
    row_count: int | None
    column_count: int | None
    source_format: str | None
    parent_dataset_id: str | None
    partial: bool = False


@dataclass
class DatasetNode:
    """A dataset in the lineage graph — identity plus its :class:`DatasetMeta`."""

    dataset_id: str
    meta: DatasetMeta


@dataclass
class TransformEdge:
    """A log entry that produced one dataset from another (a CLEAN-type step).

    ``outputs`` is retained verbatim (spec §R0.4 CHANGE 4): the DAG is the
    "click a node, see the result as it was" substrate, so it keeps result
    payloads; only the :mod:`~uadas_core.provenance.recipe` layer drops them.
    """

    from_dataset_id: str
    to_dataset_id: str
    tool_name: str | None
    inputs: dict[str, Any]
    stage: str
    explanation: dict[str, Any] | None
    timestamp: str
    outputs: dict[str, Any]


@dataclass
class ArtifactNode:
    """A non-producing log entry — a profile, chart, statistical test, forecast, explanation.

    Identity is positional: ``(dataset_id, entry_index)`` into that dataset's
    :class:`~uadas_core.services.analysis_orchestrator_service.AnalysisLog`
    (spec §5). ``visualization_id`` is populated for VISUALIZE entries (the
    orchestrator already emits it in ``outputs``) and ``None`` otherwise.
    """

    dataset_id: str
    entry_index: int
    stage: str
    tool_name: str | None
    timestamp: str
    visualization_id: str | None


@dataclass
class Dag:
    """The reshaped lineage view: dataset nodes, transform edges, artifact nodes."""

    nodes: list[DatasetNode] = field(default_factory=list)
    edges: list[TransformEdge] = field(default_factory=list)
    artifacts: list[ArtifactNode] = field(default_factory=list)

    def roots(self) -> list[DatasetNode]:
        """Nodes with no in-graph parent — the lineage starting points.

        A node is a root when its ``meta.parent_dataset_id`` is ``None`` or
        points outside the graph, *and* no :class:`TransformEdge` targets it.
        The edge check is what makes a derived dataset whose metadata lost
        its ``parent_dataset_id`` still sort correctly as non-root.
        """
        node_ids = {n.dataset_id for n in self.nodes}
        edge_targets = {e.to_dataset_id for e in self.edges}
        return [
            n
            for n in self.nodes
            if n.dataset_id not in edge_targets
            and (
                n.meta.parent_dataset_id is None
                or n.meta.parent_dataset_id not in node_ids
            )
        ]


def _is_clean_entry(entry: Any) -> bool:
    """``True`` iff this entry produced a derived dataset — the one edge predicate.

    Keyed on ``"new_dataset_id" in entry.outputs``, never on ``entry.stage``:
    the orchestrator writes ``new_dataset_id`` into ``outputs`` for any stage
    whose tool returned a new :class:`~uadas_core.services.workspace_service.Dataset`,
    not only CLEAN (see ``_summarize_result``).
    """
    return "new_dataset_id" in entry.outputs


def _reject_dataset_id_cycles(links: Mapping[str, str | None]) -> None:
    """Raise :class:`ServiceError` if the ``{child: parent}`` links form a cycle.

    Loader-boundary check, mirroring
    :func:`uadas_core.services.workspace_service._reject_parent_cycles`: a
    per-start visited-set walk, a parent id absent from ``links`` is a
    *dangling* reference and a clean stop, only a *revisited* id is an error.
    See this module's docstring for why the three cycle-checkers are not
    shared.
    """
    for start in links:
        seen: set[str] = {start}
        path: list[str] = [start]
        current = links[start]
        while current is not None:
            path.append(current)
            if current in seen:
                raise ServiceError(f"parent_dataset_id cycle: {' -> '.join(path)}")
            seen.add(current)
            if current not in links:
                break  # dangling parent: allowed, stop this walk
            current = links[current]


def analysis_logs_to_dag(
    logs: Iterable[AnalysisLog], datasets: Mapping[str, DatasetMeta]
) -> Dag:
    """Reshape a *set* of per-dataset :class:`AnalysisLog`\\ s into a :class:`Dag`.

    :param logs: Every dataset's log — typically
        :meth:`~uadas_core.services.analysis_orchestrator_service.AnalysisOrchestratorService.get_all_logs`.
    :param datasets: Known :class:`DatasetMeta` by id; ids the logs mention
        but this map omits get a synthesized ``partial=True`` meta rather
        than raising.

    Reshape rules (spec §1):

    1. One :class:`DatasetNode` per id that is a log key or an edge
       ``to``/``from``.
    2. Per entry: :func:`_is_clean_entry` → :class:`TransformEdge`
       (``from`` = enclosing log id, ``to`` = ``outputs["new_dataset_id"]``,
       ``outputs`` kept verbatim); otherwise → :class:`ArtifactNode`
       ``(log.dataset_id, index, …)``.
    3. Build ``{child: parent}`` from *both* ``meta.parent_dataset_id`` and
       every edge's ``to → from`` (the edge wins on conflict — spec §
       "Edge wins over metadata"), then run :func:`_reject_dataset_id_cycles`.
    """
    logs = list(logs)

    edges: list[TransformEdge] = []
    artifacts: list[ArtifactNode] = []
    for log in logs:
        for index, entry in enumerate(log.entries):
            if _is_clean_entry(entry):
                edges.append(
                    TransformEdge(
                        from_dataset_id=log.dataset_id,
                        to_dataset_id=entry.outputs["new_dataset_id"],
                        tool_name=entry.tool_name,
                        inputs=dict(entry.inputs),
                        stage=entry.stage.value,
                        explanation=entry.explanation,
                        timestamp=entry.timestamp,
                        outputs=dict(entry.outputs),
                    )
                )
            else:
                artifacts.append(
                    ArtifactNode(
                        dataset_id=log.dataset_id,
                        entry_index=index,
                        stage=entry.stage.value,
                        tool_name=entry.tool_name,
                        timestamp=entry.timestamp,
                        visualization_id=entry.outputs.get("visualization_id"),
                    )
                )

    mentioned: list[str] = []
    for candidate in (
        [log.dataset_id for log in logs]
        + [edge.from_dataset_id for edge in edges]
        + [edge.to_dataset_id for edge in edges]
    ):
        if candidate not in mentioned:
            mentioned.append(candidate)

    nodes: list[DatasetNode] = []
    for dataset_id in mentioned:
        meta = datasets.get(dataset_id)
        if meta is None:
            meta = DatasetMeta(dataset_id, None, None, None, None, None, partial=True)
        nodes.append(DatasetNode(dataset_id=dataset_id, meta=meta))

    links: dict[str, str | None] = {
        n.dataset_id: n.meta.parent_dataset_id for n in nodes
    }
    for (
        edge
    ) in edges:  # edge is authoritative over a disagreeing meta.parent_dataset_id
        links[edge.to_dataset_id] = edge.from_dataset_id
    _reject_dataset_id_cycles(links)

    return Dag(nodes=nodes, edges=edges, artifacts=artifacts)
