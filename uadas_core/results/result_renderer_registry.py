# File: uadas_core/results/result_renderer_registry.py
"""The registry that resolves an analysis-result object to its renderer (milestone 22).

Mirrors :mod:`uadas_core.visualization.chart_registry` exactly, per this overhaul's cross-cutting rule
3 ("new registries mirror chart_registry.py exactly"): a module-level ``_REGISTRY`` dict,
``register_renderer`` raising :class:`~uadas_core.core.exceptions.ServiceError` on a duplicate key,
plus ``get_renderer``/``list_renderers``/``unregister_renderer``. The one shape difference from
``chart_registry`` is the key type: a chart is looked up by a machine name a caller already
knows (``"box_plot"``); a result renderer is looked up by the *type* of a result a caller did
not choose and cannot be expected to know how to name -- the AI layer, the orchestrator, and a
stage page all just have "some result object" and need "whatever renders this," not a lookup
table of type-name strings to keep in sync with the analysis package's own dataclasses.

Resolution order, per the plan's A5 section ("dispatch registry ... resolved by exact type,
then MRO walk, then a generic fallback"):

1. Exact ``type(result)`` match.
2. Walk ``type(result).__mro__[1:]`` (every ancestor, nearest first) for a registered type --
   lets a future result subclass inherit its base class's renderer without an explicit
   registration, the same way Python's own method resolution works.
3. :class:`~uadas_core.results.renderers.generic.GenericResultRenderer` -- never raises. A plain
   ``pandas.DataFrame`` (``aggregate``/``cross_tabulate``'s return type -- neither has a
   dedicated result dataclass, unlike every other :mod:`uadas_core.analysis` function) and any future
   analysis function's result both fall through to this, which is *why* :meth:`get_renderer`
   returns a renderer rather than raising ``ServiceError`` the way :func:`~uadas_core.visualization.
   chart_registry.get_chart` does for an unknown name -- an unrenderable result would otherwise
   crash a stage page instead of degrading to a generic (if less polished) display.
"""

from __future__ import annotations

# Imported only for their types (registration keys), not called directly here -- keeping the
# import list explicit rather than a wildcard so a reader can see, at a glance, exactly which
# result dataclasses this milestone shipped a renderer for.
from uadas_core.analysis.anova import AnovaResult
from uadas_core.analysis.chi_square import ChiSquareResult
from uadas_core.analysis.clustering import ClusteringResult
from uadas_core.analysis.correlation import CorrelationResult
from uadas_core.analysis.dataset_profile import DatasetProfile
from uadas_core.analysis.normality import NormalityResult
from uadas_core.analysis.pca import PcaResult
from uadas_core.analysis.regression import RegressionResult
from uadas_core.analysis.t_test import TTestResult
from uadas_core.core.exceptions import ServiceError
from uadas_core.core.logger import get_logger
from uadas_core.forecasting.exponential_smoothing import ForecastResult
from uadas_core.forecasting.model_comparison import ModelComparisonResult
from uadas_core.results.base_result_renderer import BaseResultRenderer
from uadas_core.results.renderers.correlation import CorrelationResultRenderer
from uadas_core.results.renderers.forecasting import (
    ForecastResultRenderer,
    ModelComparisonResultRenderer,
)
from uadas_core.results.renderers.generic import GenericResultRenderer
from uadas_core.results.renderers.multivariate import (
    ClusteringResultRenderer,
    PcaResultRenderer,
)
from uadas_core.results.renderers.profiling import DatasetProfileRenderer
from uadas_core.results.renderers.regression import RegressionResultRenderer
from uadas_core.results.renderers.statistical_tests import (
    AnovaResultRenderer,
    ChiSquareResultRenderer,
    NormalityResultRenderer,
    TTestResultRenderer,
)

_logger = get_logger(__name__)

_REGISTRY: dict[type, type[BaseResultRenderer]] = {}

# Web-transition 1.3: the built-ins are populated by
# :func:`uadas_core.core.bootstrap.bootstrap` rather than as a side effect of
# importing this module, so importing it has no global-state effect (see
# plans/phase-1-3-startup-graph.md §9). This flag makes :func:`_register_builtins`
# a no-op after its first successful call: ``bootstrap()`` runs several times per
# pytest session and ``tests/conftest.py`` also seeds the built-in registries, at
# module import (before test collection). Mirrors
# :data:`uadas_core.core.logger._configured`.
_builtins_registered: bool = False


def register_renderer(
    result_type: type, renderer_class: type[BaseResultRenderer]
) -> None:
    """Register ``renderer_class`` as the renderer for ``result_type``.

    Args:
        result_type: The exact result dataclass this renderer knows how to render.
        renderer_class: A :class:`~uadas_core.results.base_result_renderer.BaseResultRenderer`
            subclass.

    Raises:
        ServiceError: If ``result_type`` is already registered -- the same "no last-
            registration-wins" convention :func:`~uadas_core.visualization.chart_registry.
            register_chart` uses, for the same reason: a silent second registration would mean
            whichever module happened to import last determines what a result type renders as,
            with no error to say so.
    """
    if result_type in _REGISTRY:
        raise ServiceError(
            f"A renderer for {result_type.__name__!r} is already registered "
            f"({_REGISTRY[result_type].__name__}). Choose a different result type or "
            f"unregister the existing one first."
        )
    _REGISTRY[result_type] = renderer_class
    _logger.debug(
        "Registered result renderer for %s -> %s.",
        result_type.__name__,
        renderer_class.__name__,
    )


def get_renderer(result_type: type) -> type[BaseResultRenderer]:
    """Resolve ``result_type`` to its renderer: exact match, then MRO walk, then generic fallback.

    Never raises -- see this module's own docstring for why an unrenderable result degrades to
    :class:`~uadas_core.results.renderers.generic.GenericResultRenderer` instead of erroring.
    """
    exact = _REGISTRY.get(result_type)
    if exact is not None:
        return exact
    for ancestor in result_type.__mro__[1:]:
        found = _REGISTRY.get(ancestor)
        if found is not None:
            return found
    return GenericResultRenderer


def list_renderers() -> dict[type, type[BaseResultRenderer]]:
    """Return every registered ``result_type -> renderer_class`` mapping."""
    return dict(_REGISTRY)


def unregister_renderer(result_type: type) -> None:
    """Remove a previously registered renderer. Silently does nothing if ``result_type`` was
    never registered -- matches :func:`~uadas_core.visualization.chart_registry.unregister_chart`'s own
    "caller may not know what it actually managed to register" rationale."""
    _REGISTRY.pop(result_type, None)


def _register_builtins() -> None:
    """Populate the registry with every built-in result renderer.

    Called from :func:`uadas_core.core.bootstrap.bootstrap` (web-transition 1.3
    moved this off module import so importing this module has no global-state
    side effect). Idempotent via the module-level ``_builtins_registered`` guard,
    so the repeated ``bootstrap()`` calls in the test suite and the module-level
    registry seeding in ``tests/conftest.py`` are both safe. Same shape as
    :func:`~uadas_core.visualization.chart_registry._register_builtins`.
    Covers all 12 :mod:`uadas_core.analysis` functions' result types except
    ``aggregate``/``cross_tabulate`` (both return a plain ``pandas.DataFrame``,
    which needs no dedicated renderer --
    :class:`~uadas_core.results.renderers.generic.GenericResultRenderer` already
    renders a ``DataFrame`` as a
    :class:`~uadas_core.results.base_result_renderer.TableSection`, and it is the
    registry's own fallback, so no explicit registration entry is needed for it).
    """
    global _builtins_registered
    if _builtins_registered:
        return
    register_renderer(DatasetProfile, DatasetProfileRenderer)
    register_renderer(CorrelationResult, CorrelationResultRenderer)
    register_renderer(TTestResult, TTestResultRenderer)
    register_renderer(AnovaResult, AnovaResultRenderer)
    register_renderer(ChiSquareResult, ChiSquareResultRenderer)
    register_renderer(NormalityResult, NormalityResultRenderer)
    register_renderer(RegressionResult, RegressionResultRenderer)
    register_renderer(PcaResult, PcaResultRenderer)
    register_renderer(ClusteringResult, ClusteringResultRenderer)
    # Milestone 25: the PREDICT stage's two result types.
    register_renderer(ForecastResult, ForecastResultRenderer)
    register_renderer(ModelComparisonResult, ModelComparisonResultRenderer)
    _builtins_registered = True
