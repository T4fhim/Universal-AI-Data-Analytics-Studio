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

from tests.provenance.conftest import _creation_order
from uadas_core.provenance.recipe import (
    Recipe,
    RecipeStep,
    analysis_logs_to_recipe,
    recipe_to_analysis_logs,
)


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
