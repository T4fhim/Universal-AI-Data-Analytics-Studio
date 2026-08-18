# File: src/ui/workbench/stage_registry.py
"""The registry of which :class:`StagePage` renders each pipeline stage.

Mirrors :mod:`src.visualization.chart_registry`'s shape exactly, per this overhaul's
cross-cutting rule 3 ("new registries mirror chart_registry.py exactly"): a frozen
dataclass registration, a module-level ``_REGISTRY`` dict, ``register_stage_page`` raising
:class:`~src.core.exceptions.ServiceError` on a duplicate stage, plus ``get_stage_page_class``/
``list_registered_stages``/``unregister_stage_page``.

Only stages with an actually-built page register here. :class:`~src.services.
analysis_orchestrator_service.PipelineStage` has ten members; milestone 20 ships pages for
UNDERSTAND, REPORT, and REPRODUCE only (CLEAN/EXPLORE/ANALYZE/VISUALIZE/PREDICT/EXPLAIN are
milestones 23-26's own scope, and UPLOAD has no page at all -- it is represented by the
welcome page, which is not itself a stage page since "no dataset yet" has no
:class:`~src.services.analysis_orchestrator_service.PipelineStage` value that fits it).
:class:`~src.ui.workbench.workbench.Workbench` asks this registry which stages have real
content and simply does not switch its stack to a stage with none -- see
:meth:`~src.ui.workbench.workbench.Workbench._on_stage_selected`.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.workbench.stage_page import StagePage

_logger = get_logger(__name__)


@dataclass(frozen=True)
class StagePageRegistration:
    """One registered stage page.

    Attributes:
        stage: The :class:`~src.services.analysis_orchestrator_service.PipelineStage`
            this page renders.
        page_class: The :class:`~src.ui.workbench.stage_page.StagePage` subclass.
    """

    stage: PipelineStage
    page_class: type[StagePage]


_REGISTRY: dict[PipelineStage, StagePageRegistration] = {}


def register_stage_page(stage: PipelineStage, page_class: type[StagePage]) -> None:
    """Register ``page_class`` as the workbench page for ``stage``.

    Raises:
        ServiceError: If ``stage`` is already registered (matching
            :func:`~src.visualization.chart_registry.register_chart`'s own "no
            last-registration-wins" convention), or if ``page_class.stage`` does
            not equal ``stage`` -- a page class registered under the wrong stage
            would silently mislabel itself (e.g. its guidance card would never
            receive :class:`~src.services.analysis_orchestrator_service.StageProposal`
            updates, since :class:`~src.ui.workbench.workbench.Workbench` matches
            proposals against ``page_class.stage``, not the registry key).
    """
    if stage in _REGISTRY:
        raise ServiceError(
            f"A stage page for {stage.value!r} is already registered "
            f"({_REGISTRY[stage].page_class.__name__}). Choose a different stage "
            f"or unregister the existing one first."
        )
    if page_class.stage != stage:
        raise ServiceError(
            f"{page_class.__name__}.stage is {page_class.stage!r}, which does "
            f"not match the registration stage {stage!r}."
        )
    _REGISTRY[stage] = StagePageRegistration(stage=stage, page_class=page_class)
    _logger.debug(
        "Registered stage page for %s -> %s.", stage.value, page_class.__name__
    )


def get_stage_page_class(stage: PipelineStage) -> type[StagePage] | None:
    """Return the registered page class for ``stage``, or ``None`` if none is registered.

    Returns ``None`` rather than raising -- unlike
    :func:`~src.visualization.chart_registry.get_chart`, an unregistered stage is an
    expected, ordinary state here (most of the ten stages have no page yet), not a caller
    error to report loudly.
    """
    registration = _REGISTRY.get(stage)
    return registration.page_class if registration is not None else None


def list_registered_stages() -> tuple[PipelineStage, ...]:
    """Return every stage with a registered page, in :class:`PipelineStage` declaration order."""
    return tuple(stage for stage in PipelineStage if stage in _REGISTRY)


def unregister_stage_page(stage: PipelineStage) -> None:
    """Remove a previously registered stage page. Silently does nothing if unregistered."""
    _REGISTRY.pop(stage, None)


def _register_builtins() -> None:
    """Populate the registry with every stage page built as of milestone 22.

    Imported here, at the bottom of this module, rather than at module top --
    :mod:`~src.ui.workbench.pages.understand_page` and its siblings import
    :class:`StagePage` from this package's sibling module, not from here, so there is no
    real import cycle either way; the local import is kept purely to match
    :func:`~src.visualization.chart_registry._register_builtins`'s own "populate at the
    bottom, after every name this function needs already exists" shape.

    Milestone 22 adds EXPLORE/ANALYZE/EXPLAIN -- see
    :mod:`~src.ui.workbench.pages.analyze_page`'s own docstring for why these pages call
    :mod:`src.analysis` directly rather than through the orchestrator's ``run_stage``, and for
    the real integration gap this leaves (``main_window.py`` does not yet wire their
    ``set_dataset``/``run_*`` methods to a live dataset-changed signal the way
    :class:`~src.ui.controllers.pipeline_controller.PipelineController` does for UNDERSTAND).
    """
    from src.ui.workbench.pages.analyze_page import AnalyzePage
    from src.ui.workbench.pages.explain_page import ExplainPage
    from src.ui.workbench.pages.explore_page import ExplorePage
    from src.ui.workbench.pages.report_page import ReportPage
    from src.ui.workbench.pages.reproduce_page import ReproducePage
    from src.ui.workbench.pages.understand_page import UnderstandPage

    register_stage_page(PipelineStage.UNDERSTAND, UnderstandPage)
    register_stage_page(PipelineStage.EXPLORE, ExplorePage)
    register_stage_page(PipelineStage.ANALYZE, AnalyzePage)
    register_stage_page(PipelineStage.EXPLAIN, ExplainPage)
    register_stage_page(PipelineStage.REPORT, ReportPage)
    register_stage_page(PipelineStage.REPRODUCE, ReproducePage)


_register_builtins()
