# File: src/services/guidance_service.py
"""Answers "what should I do next?" -- milestone 26's ``GuidanceService``.

Merges four **deterministic** sources into one ranked list of :class:`Suggestion`, each
carrying a real :class:`~src.ui.actions.action_registry.ActionSpec` id as a plain string:

1. :meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.
   propose_next_stage` -- one PIPELINE suggestion, mapped onto a
   ``"workbench.go_to_<stage>"`` action id (see
   :mod:`src.ui.actions.builtin_actions`'s ``_STAGE_NAV_ACTIONS`` -- registered for every
   stage :func:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.
   propose_next_stage` can ever return, so this mapping can never miss).
2. :func:`~src.visualization.chart_recommender.recommend_charts` -- CHART suggestions,
   all pointing at the existing ``"analysis.visualize"`` action (there is no per-chart-type
   action registered, and none is needed: "create a chart" is the one real, always-correct
   next step for any chart suggestion regardless of which type it names).
3. A data-quality scan built on :func:`~src.analysis.dataset_profile.profile_dataset` --
   duplicate rows, missing values, and mixed-type ("ambiguous") columns, all pointing at
   ``"workbench.go_to_clean"``. Deliberately reuses ``profile_dataset`` rather than
   re-deriving null-fraction/duplicate/mixed-type detection independently: it is already the
   one place in this codebase that computation lives (see that module's own docstring), and
   :meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.run_stage`
   already runs it for the UNDERSTAND stage -- reusing it here means a "3 duplicate rows"
   suggestion and an UNDERSTAND-stage profile summary can never disagree with each other.
4. Re-ranking (not filtering) by :class:`~src.core.expertise_level.ExpertiseLevel` --
   :func:`get_suggestions`'s final sort step, not a fifth source of new candidates.

**Never imports anything from ``src.ui``.** ``Suggestion.action_id`` is a plain string a UI
layer resolves against :func:`~src.ui.actions.action_registry.get_action` -- this is what lets
``tests/services/test_guidance_service.py`` exercise this whole module with zero ``QApplication``,
and what keeps this service on the correct side of this repo's "ui/ imports downward only" rule
(nothing outside ``src/ui`` may import ``src.ui`` -- see ``tests/ui/test_import_layering.py``).

AI-generated suggestions are explicitly out of scope for this module: the plan names them as
"additive and optional," and the one hard acceptance criterion this milestone must meet is that
guidance is **fully populated and useful with no AI key configured at all** -- so the four
sources above are the whole of :func:`get_suggestions`, not a fallback path taken only when no
provider is configured.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.analysis.dataset_profile import profile_dataset
from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.workspace_service import Dataset
from src.visualization.chart_recommender import recommend_charts
from src.visualization.chart_registry import display_name_for

_logger = get_logger(__name__)

# A column at or above this missing-value percentage is worth a dedicated
# suggestion of its own; below it, a handful of missing cells is normal,
# unremarkable data and not worth surfacing as "do something about this."
_MISSING_VALUE_SUGGESTION_THRESHOLD_PERCENT = 5.0

# The action every CHART-category suggestion points at. There is
# deliberately no per-chart-type action registered (see this module's own
# docstring) -- "create a chart" is the one real next step regardless of
# which chart_recommender.ChartSuggestion produced the rationale.
_VISUALIZE_ACTION_ID = "analysis.visualize"

# The action every DATA_QUALITY-category suggestion points at -- there is
# no per-cleaning-operation action registered either (CleanPage dispatches
# through src.cleaning.operation_registry directly, not through
# ActionRegistry -- see that page's own docstring), so every data-quality
# finding routes a user to the Clean stage page itself, where the specific
# operation can actually be run.
_CLEAN_ACTION_ID = "workbench.go_to_clean"


class SuggestionCategory(str, Enum):
    """Which of :mod:`GuidanceService`'s deterministic sources produced a :class:`Suggestion`.

    Subclasses ``str`` for the same round-trip-friendly reason
    :class:`~src.core.expertise_level.ExpertiseLevel` does -- comparable/serializable with no
    manual ``.value`` conversion, useful for a caller (or a test) filtering suggestions by
    source without importing this enum's identity, only its value.
    """

    PIPELINE = "pipeline"
    CHART = "chart"
    DATA_QUALITY = "data_quality"


@dataclass(frozen=True)
class Suggestion:
    """One recommended next action, from one of :class:`GuidanceService`'s deterministic sources.

    Attributes:
        action_id: A string id resolvable via
            :func:`~src.ui.actions.action_registry.get_action` -- **never** a live
            ``QAction`` or handler reference (see this module's own docstring on why
            ``src.ui`` is never imported here). The one hard invariant
            ``tests/services/test_guidance_service.py``'s contract test enforces: every
            ``action_id`` this service can ever produce resolves in the real registry.
        title: Short, human-readable label for what the action does (e.g. "Go to Clean
            stage").
        rationale: Why this suggestion is here -- always populated, matching this project's
            "Explain Everything" principle (the same reasoning
            :class:`~src.visualization.chart_recommender.ChartSuggestion.reason` already
            follows).
        category: Which deterministic source produced this suggestion.
        stage: The :class:`~src.services.analysis_orchestrator_service.PipelineStage` this
            suggestion is most associated with -- what :func:`_expertise_weight` re-ranks
            against. Not necessarily the stage the suggestion's ``action_id`` navigates to
            for every category (a CHART suggestion's action opens a dialog, not a stage
            page), but always the stage a user would reasonably associate the suggestion
            with.
        base_score: This suggestion's ranking within its own source, before expertise
            re-ranking -- higher sorts first. Not a calibrated probability, purely an
            ordering device (matching ``ChartSuggestion.score``'s own docstring).
    """

    action_id: str
    title: str
    rationale: str
    category: SuggestionCategory
    stage: PipelineStage
    base_score: float


# Per-ExpertiseLevel multipliers applied to a suggestion's base_score, keyed by the
# suggestion's own `stage`. A multiplier, not a filter or a floor of zero -- the acceptance
# criterion this exists for is "changing ExpertiseLevel visibly re-ranks suggestions, does
# not filter them" (the same candidate set must appear at every level, just reordered), so
# every multiplier here stays strictly positive. Missing entries default to 1.0 (neutral --
# see _expertise_weight).
#
# BEGINNER/STUDENT bias toward UNDERSTAND/VISUALIZE and de-prioritise PREDICT, per the plan's
# A6. RESEARCHER/ENGINEER surface ANALYZE/PREDICT earlier. ANALYST sits at the plan's implied
# "no particular bias" baseline. DECISION_MAKER biases toward REPORT/EXPLAIN -- the two stages
# that produce a decision-ready conclusion rather than raw methodology -- which the plan does
# not spell out explicitly but follows directly from EXPERTISE_LEVEL_GUIDANCE's own
# DECISION_MAKER text ("Lead with the business-relevant conclusion...").
_EXPERTISE_STAGE_WEIGHT: dict[ExpertiseLevel, dict[PipelineStage, float]] = {
    ExpertiseLevel.BEGINNER: {
        PipelineStage.UNDERSTAND: 1.4,
        PipelineStage.VISUALIZE: 1.4,
        PipelineStage.PREDICT: 0.5,
        PipelineStage.ANALYZE: 0.7,
    },
    ExpertiseLevel.STUDENT: {
        PipelineStage.UNDERSTAND: 1.3,
        PipelineStage.VISUALIZE: 1.3,
        PipelineStage.PREDICT: 0.6,
        PipelineStage.ANALYZE: 0.8,
    },
    ExpertiseLevel.ANALYST: {},
    ExpertiseLevel.RESEARCHER: {
        PipelineStage.ANALYZE: 1.4,
        PipelineStage.PREDICT: 1.4,
        PipelineStage.UNDERSTAND: 0.8,
    },
    ExpertiseLevel.ENGINEER: {
        PipelineStage.ANALYZE: 1.4,
        PipelineStage.PREDICT: 1.4,
        PipelineStage.CLEAN: 1.2,
        PipelineStage.UNDERSTAND: 0.8,
    },
    ExpertiseLevel.DECISION_MAKER: {
        PipelineStage.REPORT: 1.4,
        PipelineStage.EXPLAIN: 1.3,
        PipelineStage.ANALYZE: 0.7,
    },
}


def _expertise_weight(stage: PipelineStage, expertise_level: ExpertiseLevel) -> float:
    """Return the re-ranking multiplier for ``stage`` at ``expertise_level``.

    ``1.0`` (neutral -- no re-ranking effect) for any (level, stage) pair not named in
    :data:`_EXPERTISE_STAGE_WEIGHT`, so adding a new stage or level never requires touching
    every existing entry.
    """
    return _EXPERTISE_STAGE_WEIGHT.get(expertise_level, {}).get(stage, 1.0)


class GuidanceService:
    """Produces ranked, deterministic "what should I do next" suggestions for a dataset.

    Args:
        orchestrator_service: Queried for :meth:`~src.services.
            analysis_orchestrator_service.AnalysisOrchestratorService.propose_next_stage`
            (source 1) -- the same session-scoped instance
            :mod:`src.core.bootstrap` already registers, so this service's PIPELINE
            suggestion always reflects the same pipeline state the workbench's own
            :class:`~src.ui.workbench.stage_rail.StageRail` displays.

    Stateless beyond that one collaborator reference -- registered as a container singleton
    in :mod:`src.core.bootstrap`, alongside ``AnalysisOrchestratorService``, per this repo's
    "new services register in bootstrap.py" convention, even though nothing here would break
    if a caller constructed a second instance (there is no session state of this service's
    own to fork).
    """

    def __init__(self, orchestrator_service: AnalysisOrchestratorService) -> None:
        self._orchestrator_service = orchestrator_service

    def get_suggestions(
        self,
        dataset: Dataset | None,
        expertise_level: ExpertiseLevel = ExpertiseLevel.BEGINNER,
        max_suggestions: int | None = None,
    ) -> list[Suggestion]:
        """Return every deterministic suggestion for ``dataset``, ranked for ``expertise_level``.

        Args:
            dataset: The active dataset to suggest next steps for. ``None`` (no active
                dataset -- the workbench is showing its welcome page) returns an empty list
                rather than raising: "nothing to suggest yet" is a normal, expected state at
                the start of a session, not an error.
            expertise_level: Re-ranks (never filters) the candidate set -- see this module's
                own docstring, point 4. Defaults to ``ExpertiseLevel.BEGINNER``, matching
                :data:`~src.core.config._default_config_dict`'s own ``ai.expertise_level``
                default, so a caller that has not yet read a real expertise level from
                settings gets the same default the rest of the application does.
            max_suggestions: Truncates the ranked list to at most this many entries if
                given. ``None`` (the default) returns every candidate, unranked-set-size
                unchanged -- this is what
                ``tests/services/test_guidance_service.py``'s "same candidate set at every
                expertise level" contract test relies on: truncating by default would let a
                large candidate set silently drop different members at different expertise
                levels (a level-dependent multiplier pushing a suggestion below the cutoff),
                which would look exactly like filtering even though the underlying ranking
                function never removes anything itself.

        Returns:
            Suggestions sorted best-first for ``expertise_level``. Ties (equal weighted
            score) preserve each source's own relative order -- Python's ``sort`` is stable,
            and source order (pipeline, then chart, then data-quality) is itself a
            reasonable default tie-break with no expertise opinion attached.
        """
        if dataset is None:
            return []

        candidates: list[Suggestion] = []
        candidates.append(self._pipeline_suggestion(dataset))
        candidates.extend(self._chart_suggestions(dataset))
        candidates.extend(self._data_quality_suggestions(dataset))

        candidates.sort(
            key=lambda s: s.base_score * _expertise_weight(s.stage, expertise_level),
            reverse=True,
        )

        if max_suggestions is not None:
            candidates = candidates[:max_suggestions]

        _logger.debug(
            "GuidanceService produced %d suggestion(s) for dataset '%s' at expertise level %s.",
            len(candidates),
            dataset.name,
            expertise_level.value,
        )
        return candidates

    # -- Source 1: the guided pipeline's own proposal ------------------------------------

    def _pipeline_suggestion(self, dataset: Dataset) -> Suggestion:
        """Wrap :meth:`AnalysisOrchestratorService.propose_next_stage` as one PIPELINE suggestion.

        Always produces exactly one suggestion -- ``propose_next_stage`` itself never
        returns ``None`` (its own fallback, once every auto-proposed stage has run at least
        once, is a REPORT proposal -- see that method's own docstring), so this is the one
        source guaranteed to contribute a real, resolvable suggestion for *any* dataset with
        no active dataset check needed beyond the one already done in :meth:`get_suggestions`.
        """
        proposal = self._orchestrator_service.propose_next_stage(dataset.dataset_id)
        stage = proposal.stage
        return Suggestion(
            action_id=f"workbench.go_to_{stage.value}",
            title=f"Go to {stage.value.title()} stage",
            rationale=proposal.rationale,
            category=SuggestionCategory.PIPELINE,
            stage=stage,
            # Highest of the three sources' base scores by default: the
            # orchestrator's own "what's next in the guided pipeline"
            # recommendation is this application's flagship guidance
            # feature (see the plan's Context section) and should win
            # ties against a same-scored chart or data-quality finding
            # before any expertise re-ranking is even applied.
            base_score=10.0,
        )

    # -- Source 2: Smart Visualization Selection ------------------------------------------

    def _chart_suggestions(self, dataset: Dataset) -> list[Suggestion]:
        """Wrap :func:`~src.visualization.chart_recommender.recommend_charts` as CHART suggestions.

        Every result's ``action_id`` is the existing ``"analysis.visualize"`` action -- see
        this module's own docstring on why no per-chart-type action exists or is needed.
        """
        chart_suggestions = recommend_charts(dataset.dataframe)
        return [
            Suggestion(
                action_id=_VISUALIZE_ACTION_ID,
                title=f"Create a {display_name_for(cs.chart_type)} chart",
                rationale=cs.reason,
                category=SuggestionCategory.CHART,
                stage=PipelineStage.VISUALIZE,
                # chart_recommender's own scores are already a 0-10 ranking
                # device (see ChartSuggestion.score's docstring) on the same
                # scale _pipeline_suggestion's base_score uses -- reused
                # directly rather than re-normalized, so a genuinely
                # strong chart match (a datetime+numeric pair, scored 10.0)
                # can outrank a weak pipeline proposal on its own terms.
                base_score=cs.score,
            )
            for cs in chart_suggestions
        ]

    # -- Source 3: a data-quality scan, built on the existing dataset profiler -----------

    def _data_quality_suggestions(self, dataset: Dataset) -> list[Suggestion]:
        """Turn a fresh :func:`~src.analysis.dataset_profile.profile_dataset` run into
        DATA_QUALITY suggestions -- duplicate rows, columns with meaningfully missing data,
        and mixed-type ("ambiguous") columns, each routed to ``"workbench.go_to_clean"``.

        Deliberately re-profiles ``dataset`` on every call rather than accepting an
        already-computed :class:`~src.analysis.dataset_profile.DatasetProfile` as a
        parameter: ``profile_dataset`` is a cheap, pure function of the dataframe (no I/O),
        and taking a pre-computed profile instead would let a caller pass a stale one from
        before a cleaning operation ran, silently suggesting a fix for a problem the
        dataset no longer has.
        """
        profile = profile_dataset(dataset)
        suggestions: list[Suggestion] = []

        if profile.duplicate_row_count > 0:
            fraction = (
                profile.duplicate_row_count / profile.row_count
                if profile.row_count > 0
                else 0.0
            )
            suggestions.append(
                Suggestion(
                    action_id=_CLEAN_ACTION_ID,
                    title="Remove duplicate rows",
                    rationale=(
                        f"{profile.duplicate_row_count} of {profile.row_count} row(s) "
                        f"are exact duplicates of an earlier row."
                    ),
                    category=SuggestionCategory.DATA_QUALITY,
                    stage=PipelineStage.CLEAN,
                    # Scaled by how much of the dataset is affected -- a
                    # dataset that is 40% duplicate rows is a more urgent
                    # finding than one that is 1% duplicate rows, even
                    # though both are non-zero.
                    base_score=3.0 + 5.0 * fraction,
                )
            )

        for column_profile in profile.column_profiles:
            if (
                column_profile.missing_percentage
                >= _MISSING_VALUE_SUGGESTION_THRESHOLD_PERCENT
            ):
                suggestions.append(
                    Suggestion(
                        action_id=_CLEAN_ACTION_ID,
                        title=f"Handle missing values in '{column_profile.name}'",
                        rationale=(
                            f"'{column_profile.name}' is missing "
                            f"{column_profile.missing_percentage}% of its values "
                            f"({column_profile.missing_count} of {profile.row_count} row(s))."
                        ),
                        category=SuggestionCategory.DATA_QUALITY,
                        stage=PipelineStage.CLEAN,
                        base_score=2.0
                        + (column_profile.missing_percentage / 100.0) * 6.0,
                    )
                )

        if profile.ambiguous_type_columns:
            suggestions.append(
                Suggestion(
                    action_id=_CLEAN_ACTION_ID,
                    title="Resolve mixed-type columns",
                    rationale=(
                        f"{len(profile.ambiguous_type_columns)} column(s) mix numeric and "
                        f"non-numeric values under a text type: "
                        f"{', '.join(profile.ambiguous_type_columns)}."
                    ),
                    category=SuggestionCategory.DATA_QUALITY,
                    stage=PipelineStage.CLEAN,
                    base_score=4.0,
                )
            )

        return suggestions
