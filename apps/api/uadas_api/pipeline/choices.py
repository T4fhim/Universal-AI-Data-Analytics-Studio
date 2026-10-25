# File: apps/api/uadas_api/pipeline/choices.py
"""Node and edge kinds of the provenance DAG, pinned to the core by a parity test.

Why these values: ``uadas_core.provenance.dag`` models the lineage graph as three
dataclasses -- ``DatasetNode`` (a dataset), ``ArtifactNode`` (a profile, chart, test,
forecast or explanation hanging off a dataset) and ``TransformEdge`` (a step that
produced one dataset from another). The core has no ``kind`` enum, so the kind of a node
or edge *is* which class it is; here that becomes an explicit column
(``dataset`` / ``artifact`` / ``transform``) so the graph can live in two tables.

Not imported from ``uadas_core`` (models must not import the core at runtime). The
parity test (``tests/test_choices_parity.py``) derives the kinds from the core's classes
and fails if a new ``*Node`` or ``*Edge`` appears there that this module does not know.
"""

from __future__ import annotations

from django.db import models


class NodeKind(models.TextChoices):
    """What a :class:`~uadas_api.pipeline.models.PipelineNode` represents."""

    DATASET = "dataset", "Dataset"
    ARTIFACT = "artifact", "Artifact"


class EdgeKind(models.TextChoices):
    """What a :class:`~uadas_api.pipeline.models.PipelineEdge` represents."""

    TRANSFORM = "transform", "Transform"
