# File: uadas_core/provenance/__init__.py
"""Lineage DAG + portable Recipe over the orchestrator's per-dataset AnalysisLogs.

Web-transition 1.7. A read-only *view* beside
:class:`~uadas_core.services.analysis_orchestrator_service.AnalysisOrchestratorService`:
:func:`~uadas_core.provenance.dag.analysis_logs_to_dag` reshapes the *set* of
per-dataset logs into dataset-node / transform-edge / artifact-node form, and
:mod:`~uadas_core.provenance.recipe` strips it to a data-free Recipe that replays
on a fresh dataset. Nothing here mutates orchestrator state or imports Qt.

Dependency direction is one-way: ``provenance`` reads
``uadas_core.services`` / ``uadas_core.analysis`` / ``uadas_core.core``; the
services layer must never import ``provenance`` back (enforced socially, not by
import-linter, which only guards the Qt boundary).
"""

from __future__ import annotations

from uadas_core.provenance.dag import (
    ArtifactNode,
    Dag,
    DatasetMeta,
    DatasetNode,
    TransformEdge,
    analysis_logs_to_dag,
)
from uadas_core.provenance.recipe import (
    Recipe,
    RecipeStep,
    analysis_logs_to_recipe,
    recipe_to_analysis_logs,
)

__all__ = [
    "ArtifactNode",
    "Dag",
    "DatasetMeta",
    "DatasetNode",
    "Recipe",
    "RecipeStep",
    "TransformEdge",
    "analysis_logs_to_dag",
    "analysis_logs_to_recipe",
    "recipe_to_analysis_logs",
]
