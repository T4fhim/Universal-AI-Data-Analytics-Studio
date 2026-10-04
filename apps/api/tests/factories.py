# File: apps/api/tests/factories.py
"""The per-model factory registry the tenant-isolation harness is driven by.

Why this exists: ``test_tenant_isolation.py`` discovers every concrete
:class:`~uadas_api.tenancy.TenantOwnedModel` and runs the same isolation checks against
each. To do that generically it must be able to *build a row of any model inside a given
organization*, including the parent rows that model needs (a dataset needs a project, an
edge needs two nodes...). Each model therefore registers one factory here, and the
harness fails -- by design, with a message pointing at this file -- if a tenant model has
none. A new model cannot silently skip isolation testing by simply not being listed.

Contract of a factory: ``build(organization, **overrides)`` returns an **unsaved**
instance whose defaults are valid and unique; ``overrides`` replace any field (the
harness uses this to point a foreign key at another tenant's row, or to repeat the values
of a unique constraint). Parents that are *not* overridden are created (saved) in the
same organization. :meth:`ModelFactory.create` is ``build`` plus ``save``.
"""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from uadas_api.accounts.models import AuditEvent, Organization, User
from uadas_api.exports.models import Report
from uadas_api.pipeline.models import PipelineEdge, PipelineNode, Recipe
from uadas_api.tenancy import TenantOwnedModel
from uadas_api.workspaces.models import ChartSpec, Dashboard, DatasetRecord, Project

_counter = itertools.count(1)


def make_organization(slug: str | None = None) -> Organization:
    """Create and return an :class:`Organization` with a unique slug."""
    n = next(_counter)
    slug = slug or f"org-{n}"
    return Organization.objects.create(name=f"Org {slug}", slug=slug)


def make_user(email: str | None = None) -> User:
    """Create and return a :class:`User` with a unique email."""
    email = email or f"user{next(_counter)}@example.com"
    return User.objects.create_user(email=email, password="pw-for-tests")  # nosec B106


@dataclass(frozen=True)
class ModelFactory:
    """A registered factory: how to build (unsaved) and create (saved) one tenant row."""

    model: type[TenantOwnedModel]
    build: Callable[..., TenantOwnedModel]

    def create(self, organization: Organization, **overrides: Any) -> Any:
        """Build then save a row in ``organization``; returns the saved instance."""
        obj = self.build(organization, **overrides)
        obj.save()
        return obj


_REGISTRY: dict[type[TenantOwnedModel], ModelFactory] = {}


def register(
    model: type[TenantOwnedModel],
) -> Callable[[Callable[..., TenantOwnedModel]], Callable[..., TenantOwnedModel]]:
    """Register ``build`` as ``model``'s factory (decorator)."""

    def decorator(
        build: Callable[..., TenantOwnedModel],
    ) -> Callable[..., TenantOwnedModel]:
        _REGISTRY[model] = ModelFactory(model=model, build=build)
        return build

    return decorator


def factory_for(model: type[TenantOwnedModel]) -> ModelFactory:
    """Return ``model``'s factory, or fail loudly if it has none."""
    try:
        return _REGISTRY[model]
    except KeyError:
        raise LookupError(
            f"no factory registered for tenant model {model._meta.label}: add a "
            "@register(...) factory in apps/api/tests/factories.py so the tenant-"
            "isolation harness can exercise it"
        ) from None


def registered_models() -> set[type[TenantOwnedModel]]:
    """Every model that currently has a factory."""
    return set(_REGISTRY)


def _parent(
    model: type[TenantOwnedModel],
    organization: Organization,
    overrides: dict[str, Any],
    key: str,
) -> Any:
    """Pop ``key`` from ``overrides`` if given, else create a ``model`` row in ``organization``."""
    if key in overrides:
        return overrides.pop(key)
    return factory_for(model).create(organization)


@register(AuditEvent)
def _audit_event(organization: Organization, **kw: Any) -> AuditEvent:
    kw.setdefault("action", "test.action")
    kw.setdefault("target_type", "project")
    kw.setdefault("target_id", str(uuid.uuid4()))
    return AuditEvent(organization=organization, **kw)


@register(Project)
def _project(organization: Organization, **kw: Any) -> Project:
    kw.setdefault("name", f"project-{next(_counter)}")
    return Project(organization=organization, **kw)


@register(DatasetRecord)
def _dataset(organization: Organization, **kw: Any) -> DatasetRecord:
    project = _parent(Project, organization, kw, "project")
    kw.setdefault("name", f"dataset-{next(_counter)}")
    kw.setdefault("source_format", "csv")
    kw.setdefault("storage_key", f"{organization.pk}/datasets/{uuid.uuid4()}.parquet")
    kw.setdefault("row_count", 3)
    kw.setdefault("column_count", 2)
    return DatasetRecord(organization=organization, project=project, **kw)


@register(ChartSpec)
def _chart_spec(organization: Organization, **kw: Any) -> ChartSpec:
    project = _parent(Project, organization, kw, "project")
    kw.setdefault("chart_type", "bar")
    kw.setdefault("title", f"chart-{next(_counter)}")
    kw.setdefault("spec", {"category_column": "a", "value_column": "b"})
    return ChartSpec(organization=organization, project=project, **kw)


@register(Dashboard)
def _dashboard(organization: Organization, **kw: Any) -> Dashboard:
    project = _parent(Project, organization, kw, "project")
    kw.setdefault("name", f"dashboard-{next(_counter)}")
    kw.setdefault("layout", {"tiles": []})
    return Dashboard(organization=organization, project=project, **kw)


@register(PipelineNode)
def _pipeline_node(organization: Organization, **kw: Any) -> PipelineNode:
    project = _parent(Project, organization, kw, "project")
    kw.setdefault("kind", "dataset")
    kw.setdefault("label", f"node-{next(_counter)}")
    return PipelineNode(organization=organization, project=project, **kw)


@register(PipelineEdge)
def _pipeline_edge(organization: Organization, **kw: Any) -> PipelineEdge:
    # Endpoints default to nodes in a project of this organization, even when the
    # harness overrides the edge's own ``project`` with a foreign one -- the edge is
    # then the only wrong row, so the check under test is the one that fires.
    endpoint_project = (
        factory_for(Project).create(organization)
        if "project" in kw
        else _parent(Project, organization, kw, "project")
    )
    project = kw.pop("project") if "project" in kw else endpoint_project
    source = (
        kw.pop("source")
        if "source" in kw
        else factory_for(PipelineNode).create(organization, project=endpoint_project)
    )
    target = (
        kw.pop("target")
        if "target" in kw
        else factory_for(PipelineNode).create(organization, project=endpoint_project)
    )
    kw.setdefault("kind", "transform")
    return PipelineEdge(
        organization=organization, project=project, source=source, target=target, **kw
    )


@register(Recipe)
def _recipe(organization: Organization, **kw: Any) -> Recipe:
    project = _parent(Project, organization, kw, "project")
    kw.setdefault("name", f"recipe-{next(_counter)}")
    kw.setdefault("version", 1)
    kw.setdefault("definition", {"version": "1.0", "steps": []})
    return Recipe(organization=organization, project=project, **kw)


@register(Report)
def _report(organization: Organization, **kw: Any) -> Report:
    project = _parent(Project, organization, kw, "project")
    kw.setdefault("title", f"report-{next(_counter)}")
    kw.setdefault("format", "pdf")
    kw.setdefault("status", "pending")
    kw.setdefault("config", {})
    return Report(organization=organization, project=project, **kw)
