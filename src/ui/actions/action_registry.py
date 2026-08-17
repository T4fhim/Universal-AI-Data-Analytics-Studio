# File: src/ui/actions/action_registry.py
"""Qt-free, import-time-populated registry of every application action.

Mirrors :mod:`src.visualization.chart_registry`'s exact shape (a frozen
dataclass registration, a module-level ``_REGISTRY`` dict,
``register_action`` raising :class:`~src.core.exceptions.ServiceError` on a
duplicate id, plus ``get_action``/``list_actions``/``unregister_action``),
per this overhaul's cross-cutting rule 3.

**Deliberately holds no handler and no ``QIcon``.** ``chart_registry``
works as pure data resolvable at import time because a
:class:`~src.visualization.base_chart.BaseChart` subclass needs no
``QApplication`` to exist. An action's handler is a bound method of a
``MainWindow`` that is not constructed until well after this module is
imported, and constructing a ``QIcon`` before ``QApplication`` exists is
undefined behavior in Qt. Putting either here would force per-window
mutable state onto what should stay pure, testable-without-Qt data --
:class:`~src.ui.actions.action_binder.ActionBinder` is where the handler
and the icon actually get attached, once a window exists to attach them to.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

if TYPE_CHECKING:
    from src.services.analysis_orchestrator_service import PipelineStage
    from src.ui.actions.action_context import ActionContext

_logger = get_logger(__name__)


class ActionCategory(Enum):
    """Which menu/palette group an action belongs to."""

    PROJECT = "project"
    DATASET = "dataset"
    ANALYSIS = "analysis"
    VIEW = "view"
    EDIT = "edit"
    HELP = "help"


class Requirement(Enum):
    """Named preconditions :meth:`~src.ui.actions.action_binder.ActionBinder.
    refresh_enablement` checks generically against an
    :class:`~src.ui.actions.action_context.ActionContext`, so the common
    "needs an open project" / "needs an active dataset" cases don't each
    need their own one-line predicate lambda repeated across every action
    that shares the same precondition. Anything more specific (e.g. "needs
    at least two visualizations") uses :attr:`ActionSpec.predicate` instead.
    """

    PROJECT_OPEN = auto()
    ACTIVE_DATASET = auto()


@dataclass(frozen=True)
class ActionSpec:
    """One registered application action.

    Attributes:
        action_id: A stable, dotted identifier -- ``"dataset.open"``,
            ``"project.save"``. Used as the registry key, the command
            palette's search target, and (via ``requires``) what
            :class:`~src.ui.actions.action_context.ActionContext` gets
            checked against.
        label: Display text, with a ``&`` mnemonic where one applies --
            passed straight to ``QAction(label, parent)``.
        category: Which menu/palette group this belongs to.
        icon_name: A filename stem under ``resources/icons/`` (see
            :class:`~src.ui.theme.icon_provider.IconProvider`), or ``None``
            for an action with no natural icon. A test asserts every
            non-``None`` value here actually exists on disk.
        shortcut: A ``QKeySequence``-parseable string (``"Ctrl+S"``), or
            ``None``.
        status_tip: Shown in the status bar on hover, or ``None``.
        help_anchor: The manual section F1 should open for this action
            (milestone 29's anti-rot test asserts every non-``None`` value
            here resolves in ``ManualIndex`` once that exists) -- set now
            even though nothing reads it yet, so later widgets do not need
            their ``ActionSpec`` touched again just to add this.
        requires: Preconditions checked generically -- the action is
            disabled unless *all* are satisfied.
        predicate: An additional, action-specific enablement check beyond
            what ``requires`` can express (e.g. "at least two
            visualizations exist," which needs a count, not a boolean).
            Evaluated only if every ``requires`` entry is already satisfied.
        checkable: Whether the resulting ``QAction`` is a toggle.
        palette_visible: Whether the command palette lists this action.
            ``False`` for things a fuzzy-search mis-click makes
            disproportionately risky (quitting the application).
        stage: Which :class:`~src.services.analysis_orchestrator_service.
            PipelineStage` this action belongs to, if any -- read by
            milestone 26's ``GuidanceService`` to map a suggestion onto a
            concrete action id. ``None`` for actions with no stage
            affinity (settings, about, theme toggle).
    """

    action_id: str
    label: str
    category: ActionCategory
    icon_name: str | None = None
    shortcut: str | None = None
    status_tip: str | None = None
    help_anchor: str | None = None
    requires: frozenset[Requirement] = frozenset()
    predicate: Callable[[ActionContext], bool] | None = None
    checkable: bool = False
    palette_visible: bool = True
    stage: PipelineStage | None = None


_REGISTRY: dict[str, ActionSpec] = {}


def register_action(spec: ActionSpec) -> None:
    """Register ``spec`` under its own ``action_id``.

    Raises:
        ServiceError: If ``spec.action_id`` is already registered -- this
            project has no "last registration wins" convention anywhere
            else (compare :func:`~src.visualization.chart_registry.
            register_chart`), so a colliding id surfaces immediately
            rather than silently shadowing whichever action registered
            first.
    """
    if spec.action_id in _REGISTRY:
        raise ServiceError(
            f"An action with id '{spec.action_id}' is already registered "
            f"({_REGISTRY[spec.action_id].label!r}). Choose a different id."
        )
    _REGISTRY[spec.action_id] = spec
    _logger.debug("Registered action '%s' -> %s", spec.action_id, spec.label)


def get_action(action_id: str) -> ActionSpec:
    """Look up a registered action by id.

    Raises:
        ServiceError: If no action named ``action_id`` is registered.
    """
    if action_id not in _REGISTRY:
        raise ServiceError(
            f"Unknown action id: {action_id!r}. Registered ids: "
            f"{', '.join(sorted(_REGISTRY))}."
        )
    return _REGISTRY[action_id]


def unregister_action(action_id: str) -> None:
    """Remove a previously registered action. Silently a no-op if absent."""
    _REGISTRY.pop(action_id, None)


def list_actions() -> dict[str, ActionSpec]:
    """Return every registered action, keyed by id."""
    return dict(_REGISTRY)
