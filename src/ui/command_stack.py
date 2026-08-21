# File: src/ui/command_stack.py
"""Real Undo/Redo, built strictly on top of the never-mutate-in-place cleaning contract.

Milestone 17's ``builtin_actions.py``/``menu_bar.py`` removed the ``edit.undo``/``edit.redo``
``QAction``s outright rather than leave them wired to nothing -- this is where milestone 23 gives
them real semantics, per those modules' own docstrings ("Milestone 23 is where real undo/redo
semantics land").

**What this stack actually undoes.** Per :mod:`~src.cleaning.base_operation`, a cleaning operation
*never* mutates a :class:`~src.services.workspace_service.Dataset` in place -- it always returns a
new, derived ``Dataset`` whose ``parent_dataset_id`` points back at the source. That means "undo a
cleaning operation" does not require replaying, inverting, or storing any copy of a dataframe at
all: the derived dataset and its parent both already exist, side by side, in
:class:`~src.services.workspace_service.WorkspaceService`'s dataset dict, for as long as neither is
explicitly closed. Undo is therefore nothing more than moving
:meth:`~src.services.workspace_service.WorkspaceService.set_active_dataset` back to the parent's
id; redo moves it forward to the child's id again. Neither direction ever touches a
``Dataset.dataframe`` -- there is no dataframe-copying, no re-running the operation, and no way for
either direction to silently produce a value different from what was already computed once. This
is the architectural point of the never-mutate-in-place rule (see ``BaseOperation``'s own
docstring: "mutating in place would... make undo impossible without a separate undo stack" and
"[a fresh, immutable result] sidesteps both problems by construction rather than by discipline") --
:class:`CommandStack` is that sidestep made concrete.

**Why this lives in ``src/ui/`` rather than ``src/services/``.** Every other session-wide service
(``WorkspaceService``, ``ProjectService``, ...) is registered in
:func:`~src.core.bootstrap.bootstrap` and resolved from the shared
:class:`~src.core.dependency_container.DependencyContainer`, per this overhaul's cross-cutting rule
2. ``bootstrap.py`` lives under ``src/core/``, and ``src/ui/`` is the *only* package allowed to
import ``src.ui`` at all (``tests/ui/test_import_layering.py`` enforces this both ways) -- so a
"service" registered there could never itself live under ``src/ui/`` without breaking that
one-way dependency direction. This is not actually a session-wide *service* in the same sense
those are, though: it holds no data of its own beyond two id stacks, and its only job is
translating "the user pressed Ctrl+Z" into a call the already-registered ``WorkspaceService``
answers. That is exactly the shape :class:`~src.ui.ui_state_bus.UiStateBus` and
:class:`~src.ui.worker_runner.WorkerRunner` already have -- both are UI-session infrastructure
constructed directly in ``main_window.py``, not container services -- so :class:`CommandStack`
follows that precedent rather than inventing a third construction pattern for what is, at bottom,
the same kind of object.

**Qt-free by construction.** Nothing here imports PySide6. A :class:`CommandStack` is exercised
end to end -- push, undo, redo, the "never re-mutates" guarantee -- against a real
:class:`~src.services.workspace_service.WorkspaceService` with zero ``QApplication``, matching how
:mod:`~src.ui.results.result_renderer_registry`'s own tests need no ``qapp`` fixture either (see
that package's own test suite).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.services.workspace_service import WorkspaceService

_logger = get_logger(__name__)


@dataclass(frozen=True)
class DatasetPointerCommand:
    """One undoable "the active dataset pointer moved" event.

    Deliberately holds only two ids, never a ``Dataset`` or a dataframe -- undo/redo replay this
    command by calling :meth:`~src.services.workspace_service.WorkspaceService.set_active_dataset`
    with one id or the other, never by touching any dataset's data (see this module's own
    docstring for why that is sufficient).

    Attributes:
        description: Human-readable summary of what this command did -- typically the derived
            dataset's own :attr:`~src.services.workspace_service.Dataset.derivation_description`,
            shown in a future status-bar/tooltip ("Undo: Dropped missing values in 'email'").
        dataset_id: The dataset that became active when this command was originally applied --
            what :meth:`CommandStack.redo` restores the active pointer to.
        parent_dataset_id: The dataset that was active immediately before -- what
            :meth:`CommandStack.undo` restores the active pointer to. ``None`` is a legal value
            (the very first dataset loaded into an empty workspace has no "previous active
            dataset" to undo back to), and undoing such a command clears the active dataset
            entirely, matching :meth:`~src.services.workspace_service.WorkspaceService.
            set_active_dataset`'s own ``None``-clears-it contract.
    """

    description: str
    dataset_id: str
    parent_dataset_id: str | None


class CommandStack:
    """A linear undo/redo stack over :class:`~src.services.workspace_service.WorkspaceService`'s
    active-dataset pointer.

    Args:
        workspace_service: Where :meth:`undo`/:meth:`redo` actually move the active-dataset
            pointer. Held directly (not injected per-call) since every command this stack ever
            pushes acts on the same, single workspace for the lifetime of one running session --
            the same one-service-per-session shape ``WorkspaceService`` itself already has.

    A plain list-based stack, not a tree -- pushing a new command after an undo discards
    whatever was in the redo stack (see :meth:`push`), matching the conventional
    editor-undo-stack behavior (and, more concretely here: a dataset derived from an
    old-branch "future" a subsequent undo already walked away from would need its own,
    independent lineage bookkeeping this milestone does not build).
    """

    def __init__(self, workspace_service: WorkspaceService) -> None:
        self._workspace_service = workspace_service
        self._undo_stack: list[DatasetPointerCommand] = []
        self._redo_stack: list[DatasetPointerCommand] = []

    def push(self, command: DatasetPointerCommand) -> None:
        """Record ``command`` as the most recent action, and discard any redo history.

        Called once, immediately after a cleaning operation's resulting dataset has already
        been added to the workspace and made active (see
        :meth:`~src.ui.controllers.pipeline_controller.PipelineController.
        register_clean_operation`) -- this method itself never adds a dataset or changes the
        active pointer; it only remembers that the change already made is now undoable.
        """
        self._undo_stack.append(command)
        self._redo_stack.clear()
        _logger.debug(
            "Pushed undoable command: %s (dataset=%s, parent=%s)",
            command.description,
            command.dataset_id,
            command.parent_dataset_id,
        )

    def can_undo(self) -> bool:
        """Whether :meth:`undo` has anything to do -- what
        :attr:`~src.ui.actions.action_context.ActionContext.can_undo` reads."""
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        """Whether :meth:`redo` has anything to do -- what
        :attr:`~src.ui.actions.action_context.ActionContext.can_redo` reads."""
        return bool(self._redo_stack)

    def undo(self) -> DatasetPointerCommand:
        """Move the active-dataset pointer back to the most recent command's parent.

        Never touches any :class:`~src.services.workspace_service.Dataset` object or its
        dataframe -- see this module's own docstring for why that is the entire point.

        Returns:
            The command that was undone, so a caller can report what happened (e.g. "Undid:
            Dropped missing values in 'email'").

        Raises:
            ServiceError: If there is nothing to undo -- matching
                :class:`~src.services.workspace_service.WorkspaceService`'s own convention of
                raising rather than silently no-op'ing on an invalid caller request (a bound
                ``edit.undo`` ``QAction`` is disabled whenever ``can_undo()`` is ``False``, per
                its ``ActionSpec.predicate`` -- reaching this branch at all means a caller
                bypassed that enablement check, which is itself worth surfacing loudly rather
                than swallowing).
        """
        if not self._undo_stack:
            raise ServiceError("Nothing to undo.")
        command = self._undo_stack.pop()
        self._workspace_service.set_active_dataset(command.parent_dataset_id)
        self._redo_stack.append(command)
        _logger.info(
            "Undid: %s (active dataset -> %s)",
            command.description,
            command.parent_dataset_id,
        )
        return command

    def redo(self) -> DatasetPointerCommand:
        """Move the active-dataset pointer forward to the most recently undone command's dataset.

        Never touches any :class:`~src.services.workspace_service.Dataset` object or its
        dataframe -- see :meth:`undo`'s own docstring; the identical guarantee applies in
        this direction.

        Raises:
            ServiceError: If there is nothing to redo -- see :meth:`undo`'s own docstring for
                the identical reasoning.
        """
        if not self._redo_stack:
            raise ServiceError("Nothing to redo.")
        command = self._redo_stack.pop()
        self._workspace_service.set_active_dataset(command.dataset_id)
        self._undo_stack.append(command)
        _logger.info(
            "Redid: %s (active dataset -> %s)", command.description, command.dataset_id
        )
        return command
