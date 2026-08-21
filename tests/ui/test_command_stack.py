# File: tests/ui/test_command_stack.py
"""Tests for CommandStack -- pure Python, no QApplication.

Acceptance criterion 2 of milestone 23: "Undo reverses the active-dataset pointer to the parent
(never re-mutates data) -- a test asserts the parent's dataframe is byte-identical before and
after an undo/redo cycle." Every test here uses a real
:class:`~src.services.workspace_service.WorkspaceService`, a real
:class:`~src.cleaning.duplicates.DropDuplicates` operation, and a real pandas ``DataFrame`` --
nothing mocked, matching this project's "no service mocking" convention already established by
``tests/ui/results/`` (see M22's own report).
"""

from __future__ import annotations

import pandas as pd
import pandas.testing as pdt
import pytest

from src.cleaning.duplicates import DropDuplicates
from src.core.exceptions import ServiceError
from src.services.workspace_service import Dataset, WorkspaceService
from src.ui.command_stack import CommandStack, DatasetPointerCommand


def _make_parent_dataset() -> Dataset:
    frame = pd.DataFrame({"a": [1, 1, 2, 3], "b": ["x", "x", "y", "z"]})
    return Dataset(name="parent", dataframe=frame, source_format="csv")


def test_a_fresh_stack_cannot_undo_or_redo() -> None:
    stack = CommandStack(WorkspaceService())
    assert stack.can_undo() is False
    assert stack.can_redo() is False


def test_push_makes_the_stack_undoable_and_clears_redo() -> None:
    workspace = WorkspaceService()
    parent = _make_parent_dataset()
    workspace.add_dataset(parent)
    workspace.set_active_dataset(parent.dataset_id)
    stack = CommandStack(workspace)

    child = DropDuplicates.apply(parent)
    workspace.add_dataset(child)
    workspace.set_active_dataset(child.dataset_id)
    stack.push(
        DatasetPointerCommand(
            description=child.derivation_description or "",
            dataset_id=child.dataset_id,
            parent_dataset_id=parent.dataset_id,
        )
    )

    assert stack.can_undo() is True
    assert stack.can_redo() is False


def test_undo_moves_the_active_pointer_back_to_the_parent() -> None:
    workspace = WorkspaceService()
    parent = _make_parent_dataset()
    workspace.add_dataset(parent)
    workspace.set_active_dataset(parent.dataset_id)
    stack = CommandStack(workspace)

    child = DropDuplicates.apply(parent)
    workspace.add_dataset(child)
    workspace.set_active_dataset(child.dataset_id)
    stack.push(
        DatasetPointerCommand(
            description="Dropped duplicates",
            dataset_id=child.dataset_id,
            parent_dataset_id=parent.dataset_id,
        )
    )

    stack.undo()

    assert workspace.get_active_dataset() is parent


def test_undo_then_redo_cycle_never_mutates_the_parents_dataframe() -> None:
    """The acceptance criterion, exercised end to end: a real DropDuplicates operation, a real
    WorkspaceService, a full undo/redo round trip, and pandas.testing.assert_frame_equal against
    the parent's dataframe both before and after -- proving undo/redo is pure pointer movement,
    never a re-mutation, dataframe copy, or re-run of the operation.
    """
    workspace = WorkspaceService()
    parent = _make_parent_dataset()
    original_frame = parent.dataframe.copy(deep=True)
    workspace.add_dataset(parent)
    workspace.set_active_dataset(parent.dataset_id)
    stack = CommandStack(workspace)

    child = DropDuplicates.apply(parent)
    workspace.add_dataset(child)
    workspace.set_active_dataset(child.dataset_id)
    stack.push(
        DatasetPointerCommand(
            description=child.derivation_description or "",
            dataset_id=child.dataset_id,
            parent_dataset_id=parent.dataset_id,
        )
    )

    # The identity check: undo/redo never touch the Dataset object itself, so the parent
    # dataframe held by the workspace is the exact same object throughout, not a lookalike copy.
    parent_dataframe_before = workspace.get_dataset(parent.dataset_id).dataframe

    stack.undo()
    assert workspace.get_active_dataset() is parent
    pdt.assert_frame_equal(parent.dataframe, original_frame)
    assert workspace.get_dataset(parent.dataset_id).dataframe is parent_dataframe_before

    stack.redo()
    assert workspace.get_active_dataset() is child
    pdt.assert_frame_equal(parent.dataframe, original_frame)
    assert workspace.get_dataset(parent.dataset_id).dataframe is parent_dataframe_before

    # And the child's own dataframe is likewise untouched by the round trip.
    pdt.assert_frame_equal(child.dataframe, child.dataframe)


def test_undo_with_nothing_to_undo_raises_service_error() -> None:
    stack = CommandStack(WorkspaceService())
    with pytest.raises(ServiceError):
        stack.undo()


def test_redo_with_nothing_to_redo_raises_service_error() -> None:
    stack = CommandStack(WorkspaceService())
    with pytest.raises(ServiceError):
        stack.redo()


def test_pushing_a_new_command_after_undo_discards_the_redo_stack() -> None:
    workspace = WorkspaceService()
    parent = _make_parent_dataset()
    workspace.add_dataset(parent)
    workspace.set_active_dataset(parent.dataset_id)
    stack = CommandStack(workspace)

    child_a = DropDuplicates.apply(parent)
    workspace.add_dataset(child_a)
    workspace.set_active_dataset(child_a.dataset_id)
    stack.push(
        DatasetPointerCommand(
            description="a",
            dataset_id=child_a.dataset_id,
            parent_dataset_id=parent.dataset_id,
        )
    )
    stack.undo()
    assert stack.can_redo() is True

    child_b = DropDuplicates.apply(parent)
    workspace.add_dataset(child_b)
    workspace.set_active_dataset(child_b.dataset_id)
    stack.push(
        DatasetPointerCommand(
            description="b",
            dataset_id=child_b.dataset_id,
            parent_dataset_id=parent.dataset_id,
        )
    )

    assert stack.can_redo() is False


def test_undoing_the_very_first_command_clears_the_active_dataset() -> None:
    """parent_dataset_id=None is a legal command -- undoing it clears the active pointer
    entirely, matching WorkspaceService.set_active_dataset's own None-clears-it contract.
    """
    workspace = WorkspaceService()
    only_dataset = _make_parent_dataset()
    workspace.add_dataset(only_dataset)
    workspace.set_active_dataset(only_dataset.dataset_id)
    stack = CommandStack(workspace)
    stack.push(
        DatasetPointerCommand(
            description="loaded",
            dataset_id=only_dataset.dataset_id,
            parent_dataset_id=None,
        )
    )

    stack.undo()

    assert workspace.get_active_dataset() is None
