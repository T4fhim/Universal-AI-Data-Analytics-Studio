# File: apps/api/tests/test_pipeline_models.py
"""Pipeline models: the lineage graph (``PipelineNode``/``PipelineEdge``) and ``Recipe``.

Why: pins the graph rules the DAG depends on -- an edge cannot loop onto its own node or
be duplicated, a deleted node takes its edges with it, but a deleted *dataset* only
detaches the nodes that described it (lineage outlives data, as in the core) -- and the
Recipe's per-project versioning.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from factories import factory_for, make_organization

from uadas_api.accounts.models import Organization
from uadas_api.pipeline.choices import EdgeKind, NodeKind
from uadas_api.pipeline.models import PipelineEdge, PipelineNode, Recipe
from uadas_api.workspaces.models import DatasetRecord, Project

pytestmark = pytest.mark.django_db


def _node(org: Organization, **kw: object) -> PipelineNode:
    return factory_for(PipelineNode).create(org, **kw)


def test_node_kinds_are_dataset_and_artifact() -> None:
    assert {k.value for k in NodeKind} == {"dataset", "artifact"}


def test_edge_kind_is_transform() -> None:
    assert {k.value for k in EdgeKind} == {"transform"}


def test_node_kind_is_a_closed_set_enforced_by_the_database() -> None:
    org = make_organization()
    node = factory_for(PipelineNode).build(org, kind="mystery")
    with pytest.raises(IntegrityError), transaction.atomic():
        node.save()


def test_edge_kind_is_a_closed_set_enforced_by_the_database() -> None:
    org = make_organization()
    edge = factory_for(PipelineEdge).build(org, kind="mystery")
    with pytest.raises(IntegrityError), transaction.atomic():
        edge.save()


def test_an_edge_connects_two_nodes_and_is_navigable_both_ways() -> None:
    org = make_organization()
    edge = factory_for(PipelineEdge).create(org)
    assert list(edge.source.outgoing_edges.all()) == [edge]
    assert list(edge.target.incoming_edges.all()) == [edge]


def test_an_edge_cannot_loop_onto_its_own_node() -> None:
    org = make_organization()
    node = _node(org)
    edge = factory_for(PipelineEdge).build(
        org, project=node.project, source=node, target=node
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        edge.save()


def test_the_same_edge_cannot_be_recorded_twice() -> None:
    org = make_organization()
    first = factory_for(PipelineEdge).create(org)
    duplicate = PipelineEdge(
        organization=org,
        project=first.project,
        source=first.source,
        target=first.target,
        kind=first.kind,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        duplicate.save()


def test_the_reverse_edge_is_a_different_edge() -> None:
    org = make_organization()
    forward = factory_for(PipelineEdge).create(org)
    backward = PipelineEdge(
        organization=org,
        project=forward.project,
        source=forward.target,
        target=forward.source,
        kind=forward.kind,
    )
    backward.save()  # a cycle is the loader's concern (core rejects it); not a DB rule
    assert PipelineEdge.objects.for_organization(org).count() == 2


def test_deleting_a_node_deletes_its_edges_but_not_the_other_endpoint() -> None:
    org = make_organization()
    edge = factory_for(PipelineEdge).create(org)
    other = edge.target
    edge.source.delete()
    assert not PipelineEdge.objects.filter(pk=edge.pk).exists()
    assert PipelineNode.objects.filter(pk=other.pk).exists()


def test_deleting_a_dataset_detaches_its_nodes_without_deleting_them() -> None:
    org = make_organization()
    dataset = factory_for(DatasetRecord).create(org)
    node = _node(org, project=dataset.project, dataset=dataset, payload={"rows": 3})
    dataset.delete()
    node.refresh_from_db()
    assert node.dataset is None
    assert node.payload == {"rows": 3}


def test_node_payload_defaults_to_an_empty_object() -> None:
    org = make_organization()
    node = PipelineNode.objects.create(
        organization=org,
        project=factory_for(Project).create(org),
        kind=NodeKind.ARTIFACT,
        label="profile",
    )
    assert node.payload == {}


def test_deleting_a_project_removes_its_graph_and_recipes() -> None:
    org = make_organization()
    edge = factory_for(PipelineEdge).create(org)
    factory_for(Recipe).create(org, project=edge.project)
    edge.project.delete()
    assert not PipelineNode.objects.for_organization(org).exists()
    assert not PipelineEdge.objects.for_organization(org).exists()
    assert not Recipe.objects.for_organization(org).exists()


# ---------------------------------------------------------------------- Recipe


def test_recipe_versions_are_unique_per_project_and_name() -> None:
    org = make_organization()
    first = factory_for(Recipe).create(org, name="monthly", version=1)
    factory_for(Recipe).create(org, project=first.project, name="monthly", version=2)
    factory_for(Recipe).create(org, project=first.project, name="other", version=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        factory_for(Recipe).create(
            org, project=first.project, name="monthly", version=1
        )


def test_the_same_recipe_name_and_version_can_exist_in_another_project() -> None:
    org = make_organization()
    first = factory_for(Recipe).create(org, name="monthly", version=1)
    factory_for(Recipe).create(org, name="monthly", version=1)  # a fresh project
    assert Recipe.objects.for_organization(org).count() == 2
    assert first.project_id is not None


def test_recipe_version_starts_at_one() -> None:
    org = make_organization()
    recipe = Recipe.objects.create(
        organization=org, project=factory_for(Project).create(org), name="r"
    )
    assert recipe.version == 1
    bad = factory_for(Recipe).build(org, version=0)
    with pytest.raises(IntegrityError), transaction.atomic():
        bad.save()


def test_recipe_definition_round_trips_the_exported_dag() -> None:
    org = make_organization()
    definition = {
        "version": "1.0",
        "name": "m",
        "steps": [{"id": "s1", "stage": "clean", "tool_name": "drop_duplicates"}],
    }
    recipe = factory_for(Recipe).create(org, definition=definition)
    assert Recipe.objects.get(pk=recipe.pk).definition == definition
