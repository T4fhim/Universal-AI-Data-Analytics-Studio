# File: apps/api/uadas_api/pipeline/models.py
"""The provenance DAG and the portable Recipe, as rows.

Why two shapes of the same history (the Phase 1.7 split): the **DAG** keeps result
payloads, so it answers "show me this node as it was"; the **Recipe** is the same chain
with every function of the data removed (no outputs, no frames), so it can be replayed on
a fresh dataset and is the only thing the server needs to keep for the local-first story.
``PipelineNode`` / ``PipelineEdge`` are the DAG; ``Recipe`` is the exported, versioned
definition (``definition`` is the core ``Recipe.to_dict()`` payload).

Node and edge ``kind`` mirror the core's graph element classes (see ``choices.py``).
Deleting a node removes its edges (a dangling edge is meaningless), but deleting a
*dataset* only detaches the node (``dataset`` is ``SET_NULL``): lineage outlives the
dataset it describes, matching the core's non-cascading rule.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from uadas_api.pipeline.choices import EdgeKind, NodeKind
from uadas_api.tenancy import TenantOwnedModel
from uadas_api.workspaces.models import DatasetRecord, Project


class PipelineNode(TenantOwnedModel):
    """A node of a project's lineage graph: a dataset or an artifact derived from one."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="pipeline_nodes"
    )
    kind = models.CharField(max_length=16, choices=NodeKind.choices)
    label = models.CharField(max_length=255)
    dataset = models.ForeignKey(
        DatasetRecord,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pipeline_nodes",
    )
    payload: models.JSONField[Any] = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=NodeKind.values), name="ck_node_kind"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "project", "created_at"],
                name="ix_node_org_proj_ts",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}:{self.label}"


class PipelineEdge(TenantOwnedModel):
    """A directed edge between two nodes of the same project (``source`` -> ``target``)."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="pipeline_edges"
    )
    # No FK index of its own: uq_edge_src_tgt_kind leads with source and already serves it.
    source = models.ForeignKey(
        PipelineNode,
        on_delete=models.CASCADE,
        related_name="outgoing_edges",
        db_index=False,
    )
    target = models.ForeignKey(
        PipelineNode, on_delete=models.CASCADE, related_name="incoming_edges"
    )
    kind = models.CharField(max_length=16, choices=EdgeKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target", "kind"], name="uq_edge_src_tgt_kind"
            ),
            models.CheckConstraint(
                condition=~models.Q(source=models.F("target")),
                name="ck_edge_no_self_loop",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=EdgeKind.values), name="ck_edge_kind"
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "project"], name="ix_edge_org_proj"),
        ]

    def __str__(self) -> str:
        return f"{self.source_id} -[{self.kind}]-> {self.target_id}"


class Recipe(TenantOwnedModel):
    """A versioned, data-free, replayable export of an analysis chain."""

    # No FK index of its own: uq_recipe_project_name_ver leads with project.
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="recipes", db_index=False
    )
    name = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1)
    definition: models.JSONField[Any] = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["project", "name", "version"], name="uq_recipe_project_name_ver"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1), name="ck_recipe_version_pos"
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "project", "created_at"],
                name="ix_recipe_org_proj_ts",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"
