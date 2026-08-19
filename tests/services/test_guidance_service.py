# File: tests/services/test_guidance_service.py
"""Tests for src.services.guidance_service.GuidanceService.

Covers milestone 26's three service-level acceptance criteria:

1. Every ``Suggestion.action_id`` this service can ever produce resolves in the real
   ``ActionRegistry`` -- a contract test that constructs every ``PipelineStage``, feeds
   ``propose_next_stage`` through every possible completed-stage combination it can reach,
   and asserts against the actually-registered ids (via ``src.ui.actions.builtin_actions``),
   not a hand-maintained duplicate list that could drift from the real registrations.
2. Guidance is fully populated and useful with **no AI key configured** -- exercised by
   never constructing an ``AssistantService``/provider anywhere in this file at all, and
   asserting a freshly imported dataset gets at least one real suggestion.
3. Changing ``ExpertiseLevel`` re-ranks, never filters -- the same candidate action-id
   multiset appears at every expertise level, just reordered.

No ``QApplication`` anywhere in this file -- this module never imports ``src.ui`` (see its
own docstring), and the contract test's "resolves in the real registry" check imports
``src.ui.actions.builtin_actions`` purely for its import-time registration side effect,
which itself requires no live Qt application (``ActionSpec`` construction is Qt-free -- see
that module's own docstring).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.core.expertise_level import ExpertiseLevel
from src.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.guidance_service import GuidanceService, SuggestionCategory
from src.services.workspace_service import Dataset, WorkspaceService


def _fresh_dataset() -> Dataset:
    """A freshly "imported" dataset -- exactly the milestone 26 criterion 2 scenario.

    Deliberately messy enough to exercise every one of GuidanceService's deterministic
    sources at once (a datetime+numeric pair for the chart recommender, missing values and
    an exact duplicate row for the data-quality scan) without needing a second, separately
    constructed fixture per source.
    """
    return Dataset(
        name="sales",
        dataframe=pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=10),
                "revenue": [
                    100.0,
                    200.0,
                    None,
                    150.0,
                    120.0,
                    130.0,
                    140.0,
                    None,
                    160.0,
                    170.0,
                ],
                "region": [
                    "east",
                    "west",
                    "east",
                    "west",
                    "east",
                    "west",
                    "east",
                    "west",
                    "east",
                    "west",
                ],
            }
        ).pipe(lambda df: pd.concat([df, df.iloc[[0]]], ignore_index=True)),
        source_format="csv",
    )


@pytest.fixture()
def workspace() -> WorkspaceService:
    return WorkspaceService()


@pytest.fixture()
def orchestrator(workspace: WorkspaceService) -> AnalysisOrchestratorService:
    return AnalysisOrchestratorService(workspace)


@pytest.fixture()
def guidance_service(orchestrator: AnalysisOrchestratorService) -> GuidanceService:
    return GuidanceService(orchestrator)


# -- Criterion 1: every action_id resolves in the real ActionRegistry -----------------------


def test_every_pipeline_stage_proposal_maps_to_a_registered_action_id() -> None:
    """Contract test: every stage propose_next_stage can ever return has a real registered action.

    Imports src.ui.actions.builtin_actions purely for its import-time registration side
    effect (matching how main_window.py itself relies on this same side effect -- see that
    module's own comment on the import), then asserts GuidanceService's own
    f"workbench.go_to_{stage.value}" formatting resolves for every stage
    AnalysisOrchestratorService.propose_next_stage can produce: every _AUTO_PROPOSED_STAGES
    member, plus its REPORT fallback.
    """
    import src.ui.actions.builtin_actions  # noqa: F401
    from src.ui.actions.action_registry import get_action

    possible_stages = (
        PipelineStage.UNDERSTAND,
        PipelineStage.CLEAN,
        PipelineStage.EXPLORE,
        PipelineStage.ANALYZE,
        PipelineStage.VISUALIZE,
        PipelineStage.PREDICT,
        PipelineStage.EXPLAIN,
        PipelineStage.REPORT,
    )
    for stage in possible_stages:
        action_id = f"workbench.go_to_{stage.value}"
        spec = get_action(action_id)  # raises ServiceError if unregistered
        assert spec.action_id == action_id


def test_every_suggestion_action_id_is_registered(
    workspace: WorkspaceService,
    orchestrator: AnalysisOrchestratorService,
    guidance_service: GuidanceService,
) -> None:
    """The full contract test: run get_suggestions across every completed-stage combination
    propose_next_stage can walk through, and every ExpertiseLevel, and assert every single
    Suggestion.action_id produced along the way resolves in the real ActionRegistry -- not
    just the pipeline-source ones test_every_pipeline_stage_proposal_maps_to_a_registered_
    action_id above already checked in isolation.
    """
    import src.ui.actions.builtin_actions  # noqa: F401
    from src.ui.actions.action_registry import get_action

    dataset = _fresh_dataset()
    workspace.add_dataset(dataset)

    # Walk propose_next_stage's own progression by recording a real stage run after each
    # call -- this is what actually varies which stage source 1 proposes next, exercising
    # every branch _pipeline_suggestion's f"workbench.go_to_{stage.value}" formatting can
    # produce, not just the first ("UNDERSTAND, nothing run yet") state.
    for _ in range(
        8
    ):  # one call per _AUTO_PROPOSED_STAGES member, plus one past the end
        for level in ExpertiseLevel:
            suggestions = guidance_service.get_suggestions(dataset, level)
            assert suggestions, "expected at least one suggestion for a real dataset"
            for suggestion in suggestions:
                get_action(suggestion.action_id)  # raises ServiceError if unregistered

        proposal = orchestrator.propose_next_stage(dataset.dataset_id)
        if proposal.stage in (
            PipelineStage.EXPLAIN,
            PipelineStage.REPORT,
            PipelineStage.REPRODUCE,
        ):
            # EXPLAIN requires a real Explanation to run_stage() (not a tool_name -- see
            # that method's own docstring), and REPORT/REPRODUCE are not run through
            # run_stage() at all. All three are already fully covered by
            # test_every_pipeline_stage_proposal_maps_to_a_registered_action_id above;
            # this loop's own job is exercising the tool-runnable stages in between.
            break
        orchestrator.run_stage(
            dataset.dataset_id, proposal.stage, tool_name="profile_dataset"
        )


# -- Criterion 2: fully populated and useful with no AI key configured ----------------------


def test_fresh_dataset_gets_at_least_one_suggestion_with_no_ai_configured(
    guidance_service: GuidanceService,
) -> None:
    """No AssistantService/provider is constructed anywhere in this test file -- guidance
    still produces real, useful suggestions purely from the four deterministic sources.
    """
    dataset = _fresh_dataset()
    suggestions = guidance_service.get_suggestions(dataset)

    assert len(suggestions) >= 1
    # All four... well, three source categories (re-ranking is not itself a source) should
    # each contribute something for a dataset deliberately built to trigger all three (see
    # _fresh_dataset's own docstring) -- not just "at least one," which a single lucky
    # suggestion could satisfy without the scan/recommender genuinely working.
    categories_seen = {s.category for s in suggestions}
    assert SuggestionCategory.PIPELINE in categories_seen
    assert SuggestionCategory.CHART in categories_seen
    assert SuggestionCategory.DATA_QUALITY in categories_seen

    for suggestion in suggestions:
        assert suggestion.rationale, (
            "every suggestion must explain itself (Explain Everything)"
        )
        assert suggestion.title


def test_no_active_dataset_returns_an_empty_list_not_an_error(
    guidance_service: GuidanceService,
) -> None:
    assert guidance_service.get_suggestions(None) == []


def test_data_quality_suggestions_reflect_real_duplicate_and_missing_value_findings(
    guidance_service: GuidanceService,
) -> None:
    dataset = _fresh_dataset()
    suggestions = guidance_service.get_suggestions(dataset)
    quality_suggestions = [
        s for s in suggestions if s.category is SuggestionCategory.DATA_QUALITY
    ]
    reasons = " ".join(s.rationale for s in quality_suggestions)
    assert "duplicate" in reasons.lower()
    assert "revenue" in reasons  # the column with >=5% missing values


# -- Criterion 3: ExpertiseLevel re-ranks, never filters -------------------------------------


def test_expertise_level_reranks_but_never_filters_the_candidate_set(
    guidance_service: GuidanceService,
) -> None:
    """The same candidate action-id multiset appears at every expertise level -- only order changes."""
    dataset = _fresh_dataset()

    result_by_level = {
        level: guidance_service.get_suggestions(dataset, level)
        for level in ExpertiseLevel
    }

    # Same *set of titles* (a stable per-suggestion identity within one get_suggestions call,
    # since nothing here produces two identical titles) at every level -- comparing titles
    # rather than action_id alone, since multiple DATA_QUALITY suggestions legitimately
    # share one action_id and a naive action_id-multiset comparison would still pass even if
    # a whole suggestion were dropped, as long as another with the same action_id remained.
    reference_titles = {s.title for s in result_by_level[ExpertiseLevel.BEGINNER]}
    for level, suggestions in result_by_level.items():
        assert {s.title for s in suggestions} == reference_titles, (
            f"expertise level {level!r} changed the candidate set instead of only its order"
        )

    # And the order genuinely does change: BEGINNER should rank the (VISUALIZE-stage) chart
    # suggestion at least as high as ENGINEER does, and ENGINEER should rank an
    # ANALYZE/PREDICT-stage suggestion earlier than BEGINNER does. This dataset has no
    # ANALYZE/PREDICT-stage suggestion of its own (propose_next_stage proposes UNDERSTAND
    # first for a freshly imported dataset), so the concrete, always-true assertion here is
    # the weaker but still real one: the two orderings are not identical.
    beginner_order = [s.action_id for s in result_by_level[ExpertiseLevel.BEGINNER]]
    engineer_order = [s.action_id for s in result_by_level[ExpertiseLevel.ENGINEER]]
    assert beginner_order != engineer_order


def test_beginner_ranks_visualize_stage_suggestions_above_predict_stage(
    workspace: WorkspaceService,
    orchestrator: AnalysisOrchestratorService,
    guidance_service: GuidanceService,
) -> None:
    """A concrete, plan-quoted re-ranking behavior: "BEGINNER... de-prioritises PREDICT."

    Advances the pipeline until PREDICT is genuinely one of the candidates (propose_next_stage
    only proposes it once every earlier stage has an entry), then compares its position
    across BEGINNER and ENGINEER.
    """
    dataset = _fresh_dataset()
    workspace.add_dataset(dataset)
    for stage in (
        PipelineStage.UNDERSTAND,
        PipelineStage.CLEAN,
        PipelineStage.EXPLORE,
        PipelineStage.ANALYZE,
        PipelineStage.VISUALIZE,
    ):
        orchestrator.run_stage(dataset.dataset_id, stage, tool_name="profile_dataset")

    proposal = orchestrator.propose_next_stage(dataset.dataset_id)
    assert proposal.stage is PipelineStage.PREDICT

    beginner = guidance_service.get_suggestions(dataset, ExpertiseLevel.BEGINNER)
    engineer = guidance_service.get_suggestions(dataset, ExpertiseLevel.ENGINEER)

    beginner_predict_rank = next(
        i for i, s in enumerate(beginner) if s.action_id == "workbench.go_to_predict"
    )
    engineer_predict_rank = next(
        i for i, s in enumerate(engineer) if s.action_id == "workbench.go_to_predict"
    )
    assert engineer_predict_rank < beginner_predict_rank
