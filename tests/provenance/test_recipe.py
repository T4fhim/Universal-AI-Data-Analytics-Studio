# File: tests/provenance/test_recipe.py
"""`analysis_logs_to_recipe` — the DAG stripped to a data-free, replayable Recipe.

Pins spec §2 / §R0.4 CHANGE 4 + CHANGE 6: one positional-id step per log
entry, no ``outputs`` anywhere (a function of the data — ``reproduce()``
regenerates it), CLEAN-type steps flagged ``produces_dataset``, and a
``to_dict`` / ``from_dict`` JSON round-trip. `test_recipe.py` also carries
the Task 6 C-2 acceptance gate (`recipe_to_analysis_logs`).
"""

from __future__ import annotations

from uadas_core.provenance.recipe import Recipe, RecipeStep, analysis_logs_to_recipe


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
