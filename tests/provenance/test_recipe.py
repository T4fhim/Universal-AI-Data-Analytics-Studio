# File: tests/provenance/test_recipe.py
"""`analysis_logs_to_recipe` — the DAG stripped to a data-free, replayable Recipe.

Pins spec §2 / §R0.4 CHANGE 4 + CHANGE 6: one positional-id step per log
entry, no ``outputs`` anywhere (a function of the data — ``reproduce()``
regenerates it), CLEAN-type steps flagged ``produces_dataset``, and a
``to_dict`` / ``from_dict`` JSON round-trip. `test_recipe.py` also carries
the Task 6 C-2 acceptance gate (`recipe_to_analysis_logs`).
"""

from __future__ import annotations

import json

import pytest

from tests.provenance.conftest import _creation_order, _e
from uadas_core.core.exceptions import ServiceError
from uadas_core.provenance.recipe import (
    Recipe,
    RecipeStep,
    analysis_logs_to_recipe,
    recipe_to_analysis_logs,
)
from uadas_core.services.analysis_orchestrator_service import AnalysisLog


def test_step_count_equals_total_entries(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    assert len(r.steps) == sum(len(log.entries) for log in analysis_log_set)


def test_ids_are_positional_and_outputs_absent(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    assert [s.id for s in r.steps] == [f"s{i + 1}" for i in range(len(r.steps))]
    assert all("outputs" not in d for d in r.to_dict()["steps"])
    assert not any(
        f.name == "outputs" for f in RecipeStep.__dataclass_fields__.values()
    )


def test_recipe_dict_round_trips(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    assert Recipe.from_dict(r.to_dict()).to_dict() == r.to_dict()


def test_clean_steps_marked_produces_dataset(analysis_log_set):
    r = analysis_logs_to_recipe(analysis_log_set)
    n = sum(
        1
        for log in analysis_log_set
        for e in log.entries
        if "new_dataset_id" in e.outputs
    )
    assert sum(1 for s in r.steps if s.produces_dataset) == n


def test_every_analysis_log_fixture_round_trips_through_recipe(analysis_log_set):
    # The C-2 acceptance gate: every AnalysisLog shape the suite builds must
    # survive analysis_logs_to_recipe -> recipe_to_analysis_logs. outputs
    # (incl. new_dataset_id) are re-derived on replay and deliberately not
    # compared; everything else must match, in creation order.
    recipe = analysis_logs_to_recipe(analysis_log_set)
    logs2 = recipe_to_analysis_logs(recipe.to_dict(), new_root_dataset_id="new-root")

    e1 = [e for log in _creation_order(analysis_log_set) for e in log.entries]
    e2 = [e for log in _creation_order(logs2) for e in log.entries]
    assert len(e1) == len(e2)  # never rely on zip() to catch a length mismatch
    for a, b in zip(e1, e2):
        assert b.stage == a.stage
        assert b.tool_name == a.tool_name
        assert b.inputs == a.inputs
        assert b.explanation == a.explanation  # plain dict, round-trips via JSON
        assert b.timestamp == a.timestamp
    assert json.dumps([log.to_dict() for log in logs2])  # outputs JSON-serializable


# --- non-linear log sets are out of 1.7 scope: _creation_order must raise, not ---
# --- silently drop a branch (end-of-range review B1 / silent-failure-hunter). ---


def _clean(i: int, new_id: str) -> object:
    return _e(
        "clean",
        "drop_missing_values",
        outputs={"new_dataset_id": new_id, "derivation_description": "x"},
        i=i,
    )


def test_fan_out_in_one_log_raises_not_drops_a_branch():
    # root produced BOTH "a" and "b" — a clean stage re-run with different params.
    # One root, so the >1-root guard misses it; the branch must still be refused.
    root = AnalysisLog("root", [_clean(20, "a"), _clean(21, "b")])
    a = AnalysisLog("a", [_e("analyze", "profile_dataset", i=25)])
    b = AnalysisLog("b", [_e("analyze", "profile_dataset", i=26)])
    with pytest.raises(ServiceError, match="more than one dataset"):
        analysis_logs_to_recipe([root, a, b])


def test_forest_of_two_roots_raises():
    with pytest.raises(ServiceError, match="single root log"):
        analysis_logs_to_recipe(
            [
                AnalysisLog("r1", [_e("understand", "profile_dataset", i=1)]),
                AnalysisLog("r2", [_e("understand", "profile_dataset", i=2)]),
            ]
        )


def test_a_stray_unreachable_log_raises():
    # root -> "a"; "orphan" is produced by nothing, so it is a second root and
    # the set is refused (a stray log must never be silently omitted from the
    # Recipe). Whichever guard fires, the contract is: ServiceError, not a
    # partial Recipe.
    root = AnalysisLog("root", [_clean(20, "a")])
    a = AnalysisLog("a", [_e("analyze", "profile_dataset", i=25)])
    orphan = AnalysisLog("orphan", [_e("understand", "profile_dataset", i=1)])
    with pytest.raises(ServiceError):
        analysis_logs_to_recipe([root, a, orphan])


def test_recipe_step_from_dict_rejects_a_non_iso_timestamp():
    good = RecipeStep(
        "s1",
        "Profile",
        "understand",
        "profile_dataset",
        {},
        False,
        None,
        "2026-09-07T14:32:15Z",
    ).to_dict()
    bad = {**good, "timestamp": "whenever"}
    with pytest.raises(ServiceError, match="ISO-8601"):
        RecipeStep.from_dict(bad)


def test_recipe_step_from_dict_requires_produces_dataset():
    good = RecipeStep(
        "s1",
        "Profile",
        "understand",
        "profile_dataset",
        {},
        False,
        None,
        "2026-09-07T14:32:15Z",
    ).to_dict()
    del good["produces_dataset"]
    with pytest.raises(KeyError):
        RecipeStep.from_dict(good)


def test_recipe_step_from_dict_rejects_an_unknown_stage():
    # type-design review: from_dict validated timestamp but not stage, deferring
    # the failure to replay -- now caught at parse time, uniform with
    # AnalysisLogEntry.from_dict.
    good = RecipeStep(
        "s1",
        "Profile",
        "understand",
        "profile_dataset",
        {},
        False,
        None,
        "2026-09-07T14:32:15Z",
    ).to_dict()
    with pytest.raises(ServiceError, match="stage"):
        RecipeStep.from_dict({**good, "stage": "not-a-stage"})


def test_recipe_to_analysis_logs_rejects_an_unknown_stage():
    # An unknown stage in a recipe payload -> ServiceError, never a bare crash.
    # Since the type-design fix it is rejected at Recipe.from_dict parse time
    # (RecipeStep.from_dict) rather than at replay -- fail-fast, still a
    # ServiceError about the stage.
    step = RecipeStep(
        "s1", "x", "not-a-stage", None, {}, False, None, "2026-09-07T14:32:15Z"
    )
    recipe = Recipe(steps=[step])
    with pytest.raises(ServiceError, match="stage"):
        recipe_to_analysis_logs(recipe.to_dict(), new_root_dataset_id="new-root")


def test_source_dataset_is_populated_when_datasets_is_supplied():
    from uadas_core.provenance.dag import DatasetMeta

    root = AnalysisLog("root", [_e("understand", "profile_dataset", i=15)])
    meta = DatasetMeta("root", "sales", 5, 2, "csv", parent_dataset_id=None)
    recipe = analysis_logs_to_recipe([root], {"root": meta})
    assert recipe.source_dataset["name"] == "sales"
    assert recipe.source_dataset["row_count"] == 5
    assert recipe.source_dataset["partial"] is False


def test_source_dataset_is_partial_when_datasets_is_omitted():
    root = AnalysisLog("root", [_e("understand", "profile_dataset", i=15)])
    recipe = analysis_logs_to_recipe([root])
    assert recipe.source_dataset["name"] is None
    assert recipe.source_dataset["partial"] is True
