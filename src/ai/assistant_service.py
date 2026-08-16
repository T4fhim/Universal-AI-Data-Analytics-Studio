# File: src/ai/assistant_service.py
"""Runs a conversation with an LLM (Anthropic or Gemini), dispatching tool calls against the active dataset.

Delegates every provider-specific detail to :mod:`src.ai.llm_provider`
so this class's own logic is identical regardless of which provider is
active.

The one rule enforced here, not in the tool registry: a tool that
returns a new :class:`~src.services.workspace_service.Dataset` (every
cleaning tool) is added to
:class:`~src.services.workspace_service.WorkspaceService` as a new
dataset — it never silently replaces the active dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.ai.llm_provider import PendingToolCall
from src.ai.provider_rotation import (
    ProviderRotationService,
    ResolvedProviderProfile,
    _looks_like_rate_limit,
)
from src.ai.tool_registry import get_anthropic_tool_schemas, get_tool_by_name
from src.core.exceptions import ApplicationError, ServiceError
from src.core.expertise_level import EXPERTISE_LEVEL_GUIDANCE, ExpertiseLevel
from src.core.logger import get_logger
from src.services.workspace_service import Dataset, WorkspaceService

_logger = get_logger(__name__)

# Scoped to "answer thoroughly about the active dataset using the
# available tools," not "answer any question about anything." Within
# that scope, explicitly instructed not to dodge or give up on a
# legitimate multi-step data question. Kept provider/expertise-neutral
# — :func:`_build_system_prompt` appends the expertise-specific
# register/depth guidance (milestone 8) rather than this constant
# branching on it, so the base scope-and-honesty instructions stay in
# one place regardless of which expertise level is active.
_BASE_SYSTEM_PROMPT = (
    "You are a data analysis assistant embedded in a desktop analytics "
    "application. You have tools to clean, profile, and statistically "
    "analyze the user's currently active dataset — nothing else; you "
    "do not have general web or knowledge-base access, and should say "
    "so plainly if asked something outside that scope, rather than "
    "guessing.\n\n"
    "Within that scope, be thorough, not evasive: if a question about "
    "the dataset requires several tool calls chained together (for "
    "instance, profiling first to find which columns are numeric, then "
    "computing a correlation), do that rather than answering only the "
    "easiest part of the question. If a tool call fails, read the "
    "error and try a corrected call rather than giving up after one "
    "attempt. When a cleaning tool succeeds, tell the user a new "
    "dataset was created — never claim you modified their original "
    "data, since you did not and cannot. Be concise in your final "
    "answer; summarize the meaningful finding rather than dumping raw "
    "numbers."
)


def _build_system_prompt(expertise_level: ExpertiseLevel) -> str:
    """Append expertise-level guidance (milestone 8) to the base system prompt.

    A plain function, not a method, since it has no dependency on
    ``AssistantService`` instance state — kept next to
    ``_BASE_SYSTEM_PROMPT`` at module scope for the same reason
    ``_provider_list_item`` in ``settings_dialog.py`` is module-level:
    it's a pure formatting step, not assistant behavior.
    """
    guidance = EXPERTISE_LEVEL_GUIDANCE[ExpertiseLevel(expertise_level)]
    return f"{_BASE_SYSTEM_PROMPT}\n\n{guidance}"


@dataclass
class AssistantTurnResult:
    """Result of one call to :meth:`AssistantService.send_message`.

    Attributes:
        reply_text: The assistant's natural-language reply.
        new_datasets: Any new datasets created by tool calls during
            this turn (already added to ``WorkspaceService``).
    """

    reply_text: str
    new_datasets: list[Dataset] = field(default_factory=list)


class AssistantService:
    """Runs conversations with an LLM, executing tool calls against the active dataset.

    Args:
        provider_name: ``"anthropic"`` or ``"gemini"``.
        api_key: The selected provider's API key.
        workspace_service: Used to resolve the active dataset for tool
            calls and to register any new dataset a cleaning tool
            produces.
    """

    def __init__(
        self, provider_name: str, api_key: str, workspace_service: WorkspaceService
    ) -> None:
        # Wrapped in a single-profile ProviderRotationService rather than
        # calling create_provider() directly — this constructor's
        # signature is unchanged (existing tests and any future simple
        # call site keep working exactly as before), but every send()
        # now goes through the same rotation-aware path that
        # from_config_profiles() below uses for real, multi-profile
        # configuration. A single-profile rotation service simply never
        # has anywhere to advance() to, so this is a no-op for callers
        # that don't need rotation.
        self._rotation = ProviderRotationService(
            [
                ResolvedProviderProfile(
                    name=provider_name, provider_type=provider_name, api_key=api_key
                )
            ]
        )
        self._rotation_enabled = False
        self._workspace_service = workspace_service
        self._history: list[Any] = []
        self._expertise_level: ExpertiseLevel = ExpertiseLevel.BEGINNER

    @classmethod
    def from_provider_profiles(
        cls,
        config_profiles: list[dict[str, Any]],
        rotation_enabled: bool,
        workspace_service: WorkspaceService,
        expertise_level: str = ExpertiseLevel.BEGINNER,
    ) -> AssistantService:
        """Construct from the ``ai.providers`` config list (milestone 7's real wiring path).

        Args:
            config_profiles: The ``ai.providers`` list as stored in
                config (see :func:`src.core.config._default_config_dict`)
                — each a ``{name, provider_type, api_key_env_var,
                model}`` dict. Must be non-empty.
            rotation_enabled: Mirrors ``ai.rotation_enabled``. When
                ``False``, only the first profile is ever used —
                :meth:`send_message` will not rotate on failure even if
                more profiles are configured, matching the config
                toggle's documented meaning.
            workspace_service: Same role as in :meth:`__init__`.
            expertise_level: Mirrors ``ai.expertise_level`` (milestone
                8) — a plain string (the config's own storage type; see
                :class:`~src.core.expertise_level.ExpertiseLevel`'s
                docstring for why it round-trips without conversion).

        Raises:
            ServiceError: If ``config_profiles`` is empty — mirrors
                :class:`~src.ai.provider_rotation.ProviderRotationService`'s
                own guard, surfaced here since this is the path real
                (non-test) callers use.
        """
        if not config_profiles:
            raise ServiceError(
                "No AI provider is configured. Add at least one provider "
                "profile in Settings before using the assistant."
            )
        instance = cls.__new__(cls)
        instance._rotation = ProviderRotationService.from_config_profiles(
            config_profiles
        )
        instance._rotation_enabled = rotation_enabled
        instance._workspace_service = workspace_service
        instance._history = []
        instance._expertise_level = ExpertiseLevel(expertise_level)
        return instance

    def set_expertise_level(self, expertise_level: str) -> None:
        """Update the expertise level guiding the AI's system prompt for future turns.

        Takes effect from the *next* :meth:`send_message` call onward
        — does not retroactively change how earlier turns in
        ``self._history`` already read, since a provider's history
        entries are opaque, already-sent conversation state (see
        :class:`~src.ai.llm_provider.BaseLLMProvider`'s own docstring),
        not something this method can safely rewrite after the fact.
        Exposed as a live setter (rather than requiring a fresh
        ``AssistantService`` per change) so the milestone-10 expertise
        selector can update an already-running conversation.
        """
        self._expertise_level = ExpertiseLevel(expertise_level)

    @property
    def active_provider_name(self) -> str:
        """The currently active provider profile's user-facing name.

        Exposed so the UI (the AI chat panel, milestone 10) can show
        which provider/key is answering right now — the milestone
        plan's own requirement that rotation "surface which provider is
        active to the UI rather than failing the turn" silently.
        """
        return self._rotation.active_profile.name

    def reset_conversation(self) -> None:
        """Clear conversation history, starting fresh."""
        self._history = []
        _logger.info("Assistant conversation reset.")

    def send_message(self, user_message: str) -> AssistantTurnResult:
        """Send ``user_message``, run any tool calls the model requests, return the final reply.

        Raises:
            ServiceError: If no dataset is active, or the underlying
                API call fails.
        """
        active_dataset = self._workspace_service.get_active_dataset()
        if active_dataset is None:
            raise ServiceError(
                "No active dataset. Open or select a dataset before "
                "using the assistant."
            )

        provider = self._rotation.current_provider()
        self._history = provider.append_user_message(self._history, user_message)
        new_datasets: list[Dataset] = []
        tool_schemas = get_anthropic_tool_schemas()

        while True:
            turn, raw_response = self._send_with_rotation(tool_schemas, user_message)
            provider = self._rotation.current_provider()
            self._history = provider.append_assistant_turn(self._history, raw_response)

            if not turn.tool_calls:
                return AssistantTurnResult(
                    reply_text=turn.text, new_datasets=new_datasets
                )

            results: list[tuple[PendingToolCall, str]] = []
            for call in turn.tool_calls:
                result_text, produced_dataset = self._execute_tool(
                    call.name, call.arguments, active_dataset
                )
                if produced_dataset is not None:
                    new_datasets.append(produced_dataset)
                    active_dataset = produced_dataset
                results.append((call, result_text))

            self._history = provider.append_tool_results(self._history, results)

    def _send_with_rotation(
        self, tool_schemas: list[dict[str, Any]], original_user_message: str
    ) -> tuple[Any, Any]:
        """Call the active provider's ``send()``, rotating to the next profile on a rate-limit failure.

        Args:
            tool_schemas: Passed through to ``send()`` unchanged.
            original_user_message: Used only if rotation must reset
                history (see below) — re-seeds the conversation with
                just this message rather than leaving ``self._history``
                empty, so the new provider still has something to
                respond to.

        Returns:
            The same ``(LLMTurn, raw_response)`` pair ``send()``
            returns.

        Raises:
            ServiceError: The original failure, if rotation is
                disabled, the failure doesn't look like a rate limit,
                or no further profiles are configured to rotate to —
                in every one of those cases this fails the turn exactly
                as the pre-milestone-7 code did, per the plan's own
                framing of rotation as additive, not a behavior change
                for the non-rotating case.
        """
        provider = self._rotation.current_provider()
        try:
            return provider.send(
                self._history, _build_system_prompt(self._expertise_level), tool_schemas
            )
        except ServiceError as exc:
            if not self._rotation_enabled or not _looks_like_rate_limit(exc):
                raise
            previous_provider_type = self._rotation.active_profile.provider_type
            if not self._rotation.advance():
                raise  # no more configured profiles left to try

            if self._rotation.active_profile.provider_type != previous_provider_type:
                # Conversation history so far is shaped in the previous
                # provider's own wire format (see llm_provider.py's
                # module docstring on how differently each provider
                # represents a turn) — safe to keep reusing only when
                # rotating between profiles of the *same* provider_type
                # (the headline case: several Groq keys). Rotating to a
                # genuinely different provider type mid-conversation
                # would hand that provider objects/shapes it cannot
                # parse, so history is deliberately reset to just the
                # user's original message rather than risk a confusing
                # second failure.
                _logger.warning(
                    "Rotated across provider types (%s -> %s); resetting "
                    "conversation history to the current message only.",
                    previous_provider_type,
                    self._rotation.active_profile.provider_type,
                )
                self._history = []
                new_provider = self._rotation.current_provider()
                self._history = new_provider.append_user_message(
                    self._history, original_user_message
                )

            _logger.warning(
                "Provider %r rate-limited; retrying once with %r.",
                previous_provider_type,
                self._rotation.active_profile.name,
            )
            provider = self._rotation.current_provider()
            return provider.send(
                self._history, _build_system_prompt(self._expertise_level), tool_schemas
            )

    def _execute_tool(
        self, tool_name: str, tool_input: dict[str, Any], active_dataset: Dataset
    ) -> tuple[str, Dataset | None]:
        """Run one tool call, returning (result text for the model, new Dataset if any).

        Errors are caught and reported back to the model as the tool
        result rather than raised, so a mistaken tool call becomes a
        correctable conversational turn instead of crashing the whole
        conversation.
        """
        try:
            tool = get_tool_by_name(tool_name)
        except KeyError as exc:
            return f"Error: {exc}", None

        try:
            clean_input = {k: v for k, v in tool_input.items() if k}
            result = tool.handler(active_dataset, **clean_input)
        except ApplicationError as exc:
            _logger.warning("Tool '%s' failed: %s", tool_name, exc)
            return f"Error: {exc}", None
        except Exception as exc:
            _logger.error("Tool '%s' raised an unexpected error: %s", tool_name, exc)
            return f"Unexpected error: {exc}", None

        if isinstance(result, Dataset):
            self._workspace_service.add_dataset(result)
            _logger.info(
                "Assistant tool '%s' produced new dataset: %s (%s)",
                tool_name,
                result.name,
                result.dataset_id,
            )
            return (
                f"Success. Created new dataset '{result.name}' "
                f"({result.row_count} rows, {result.column_count} cols). "
                f"{result.derivation_description}",
                result,
            )

        return json.dumps(result, default=str), None
