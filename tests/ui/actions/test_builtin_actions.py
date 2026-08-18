# File: tests/ui/actions/test_builtin_actions.py
"""Tests against the real, as-shipped action set.

Unlike test_action_registry.py, this file deliberately does NOT isolate
the registry -- it imports builtin_actions.py and checks its actual
registrations, since the whole point is verifying what ships, not a
synthetic fixture.
"""

from __future__ import annotations

import src.ui.actions.builtin_actions  # noqa: F401 -- import-time registration
from src.ui.actions.action_registry import Requirement, list_actions
from src.ui.theme.icon_provider import IconProvider
from src.ui.theme.tokens import DARK_TOKENS


def test_every_icon_name_exists_on_disk() -> None:
    """Backs IconProvider.available_icons()'s own docstring promise: a typo
    in an ActionSpec.icon_name must surface here, not as a silently blank
    toolbar button.
    """
    provider = IconProvider(DARK_TOKENS)
    available = set(provider.available_icons())

    missing = {
        f"{spec.action_id} -> {spec.icon_name!r}"
        for spec in list_actions().values()
        if spec.icon_name is not None and spec.icon_name not in available
    }
    assert (
        not missing
    ), f"ActionSpec.icon_name references a missing icon file: {missing}"


def test_every_action_has_a_non_empty_label() -> None:
    empty = [aid for aid, spec in list_actions().items() if not spec.label.strip()]
    assert empty == []


def test_edit_undo_and_redo_are_registered_with_real_predicates() -> None:
    """Milestone 17 removed the dead Undo/Redo QActions entirely rather than keeping them
    permanently disabled -- see builtin_actions.py's module docstring. Milestone 23 re-adds
    them with real semantics: gated by CommandStack.can_undo/can_redo via a predicate, since
    Requirement has no boolean member for "can undo" (see ActionContext.can_undo's own
    docstring).
    """
    from dataclasses import dataclass

    @dataclass
    class _Stub:
        can_undo: bool
        can_redo: bool

    undo_spec = list_actions()["edit.undo"]
    redo_spec = list_actions()["edit.redo"]
    assert undo_spec.predicate is not None
    assert redo_spec.predicate is not None
    assert undo_spec.predicate(_Stub(can_undo=True, can_redo=False)) is True
    assert undo_spec.predicate(_Stub(can_undo=False, can_redo=False)) is False
    assert redo_spec.predicate(_Stub(can_undo=False, can_redo=True)) is True
    assert redo_spec.predicate(_Stub(can_undo=False, can_redo=False)) is False


def test_save_actions_require_project_open() -> None:
    assert Requirement.PROJECT_OPEN in list_actions()["project.save"].requires
    assert Requirement.PROJECT_OPEN in list_actions()["project.save_as"].requires


def test_visualize_and_generate_report_require_active_dataset() -> None:
    """Matches the real pre-milestone-17 handler bodies, not an assumption
    -- _on_create_visualization and _on_generate_report both check
    workspace_service.get_active_dataset(), never project_service.
    """
    assert Requirement.ACTIVE_DATASET in list_actions()["analysis.visualize"].requires
    assert (
        Requirement.ACTIVE_DATASET
        in list_actions()["analysis.generate_report"].requires
    )


def test_dashboard_predicate_requires_at_least_two_visualizations() -> None:
    """_on_create_dashboard's real precondition (len(visualizations) < 2 ->
    blocked) needs a count, which the boolean Requirement enum cannot
    express -- exercised via a minimal stand-in with just the one field
    this predicate reads.
    """
    from dataclasses import dataclass

    @dataclass
    class _Stub:
        visualization_count: int

    predicate = list_actions()["analysis.dashboard"].predicate
    assert predicate is not None
    assert predicate(_Stub(0)) is False
    assert predicate(_Stub(1)) is False
    assert predicate(_Stub(2)) is True
    assert predicate(_Stub(5)) is True


def test_exit_is_not_palette_visible() -> None:
    assert list_actions()["project.exit"].palette_visible is False


def test_project_new_is_palette_visible() -> None:
    assert list_actions()["project.new"].palette_visible is True
