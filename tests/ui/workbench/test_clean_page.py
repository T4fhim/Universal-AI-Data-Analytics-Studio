# File: tests/ui/workbench/test_clean_page.py
"""Tests for CleanPage -- milestone 23's primary acceptance criterion, end to end.

"All 5 operation_registry cleaning operations are reachable from the Clean page -- first
non-AI path to any cleaning operation." Every test here calls the real
:mod:`~src.cleaning.operation_registry` operation classes against a real pandas ``DataFrame`` --
nothing mocked, matching :mod:`tests.ui.workbench.test_analyze_page`'s own "no src.ai import on
this path" proof for its own acceptance criterion.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication

from src.cleaning.operation_registry import list_operations
from src.services.workspace_service import Dataset
from src.ui.workbench.pages.clean_page import CleanPage


def _make_dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "value": [1, 1, 2, None],
            "label": ["  A ", "  A ", "B", "C"],
        }
    )
    return Dataset(name="clean-demo", dataframe=frame, source_format="csv")


def test_every_registered_operation_is_offered_in_the_tool_combo(
    qapp: QApplication,
) -> None:
    page = CleanPage()
    combo_names = {
        page._tool_combo.itemData(i) for i in range(page._tool_combo.count())
    }
    assert combo_names == set(list_operations())
    assert len(combo_names) == 5


def test_set_dataset_loads_the_before_table(qapp: QApplication) -> None:
    page = CleanPage()
    dataset = _make_dataset()

    page.set_dataset(dataset)

    assert page.before_table.dataset_id == dataset.dataset_id
    assert page.before_table.model is not None
    assert page.before_table.model.rowCount() == 4


def test_apply_drop_missing_values_produces_a_correctly_linked_derived_dataset(
    qapp: QApplication,
) -> None:
    """Acceptance criterion 1, exercised end to end: a real Dataset, a real operation, and a
    real before/after DataTableView split showing real cell values.
    """
    page = CleanPage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    derived = page.apply_operation(dataset, "drop_missing_values", {})

    assert derived is not None
    assert derived.parent_dataset_id == dataset.dataset_id
    assert derived.derivation_description is not None
    assert derived.row_count == 3  # the one row with a missing "value" was dropped

    # The before table still shows the untouched parent's real data.
    assert page.before_table.model.rowCount() == 4
    assert page.before_table.model.dataframe is dataset.dataframe

    # The after table shows the derived dataset's real data -- one fewer row.
    assert page.after_table.dataset_id == derived.dataset_id
    assert page.after_table.model.rowCount() == 3
    pd_frame = page.after_table.model.dataframe
    assert pd_frame["value"].isna().sum() == 0


def test_apply_operation_emits_operation_applied_with_the_derived_dataset(
    qapp: QApplication,
) -> None:
    page = CleanPage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    received: list = []
    page.operation_applied.connect(received.append)

    derived = page.apply_operation(dataset, "drop_duplicates", {})

    assert received == [derived]


def test_all_five_operations_are_runnable_end_to_end(qapp: QApplication) -> None:
    """Drives every one of the 5 operation_registry operations through apply_operation, the
    same method the Run button calls -- the literal acceptance-criterion claim.
    """
    page = CleanPage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    results = {
        "drop_missing_values": page.apply_operation(dataset, "drop_missing_values", {}),
        "fill_missing_values": page.apply_operation(
            dataset, "fill_missing_values", {"fill_value": 0}
        ),
        "drop_duplicates": page.apply_operation(dataset, "drop_duplicates", {}),
        "normalize_text": page.apply_operation(
            dataset, "normalize_text", {"columns": ["label"], "case": "upper"}
        ),
        "convert_type": page.apply_operation(
            dataset, "convert_type", {"column": "label", "target_type": "string"}
        ),
    }

    for name, derived in results.items():
        assert derived is not None, f"{name} did not produce a derived dataset"
        assert derived.parent_dataset_id == dataset.dataset_id


def test_apply_operation_with_unknown_tool_name_returns_none_and_sets_result_text(
    qapp: QApplication,
) -> None:
    page = CleanPage()
    dataset = _make_dataset()

    result = page.apply_operation(dataset, "not_a_real_operation", {})

    assert result is None
    assert "Unknown cleaning operation" in page._result_label.text()


def test_apply_operation_reports_a_service_error_without_crashing(
    qapp: QApplication, block_modals
) -> None:
    # Milestone 27: a failed cleaning operation is shown via the page's own in-page ErrorState
    # now, not a QMessageBox.critical -- see StagePage.show_error's own docstring.
    page = CleanPage()
    dataset = _make_dataset()

    # convert_type with a nonexistent column raises a real ServiceError.
    result = page.apply_operation(
        dataset, "convert_type", {"column": "not_a_column", "target_type": "numeric"}
    )

    assert result is None
    assert not block_modals
    assert page._error_state.isHidden() is False
    assert page._error_state._heading_label.text() == "Cleaning Operation Failed"


def test_run_with_no_active_dataset_shows_an_informative_message(
    qapp: QApplication, block_modals
) -> None:
    page = CleanPage()
    page._on_run_clicked()

    assert any(call.kind == "information" for call in block_modals)


def test_show_lineage_forwards_to_the_lineage_view(qapp: QApplication) -> None:
    page = CleanPage()
    dataset = _make_dataset()
    derived = page.apply_operation(dataset, "drop_duplicates", {})
    assert derived is not None

    page.show_lineage([dataset], derived, [])

    assert page.lineage_view.topLevelItemCount() == 1
