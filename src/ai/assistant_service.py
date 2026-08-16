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

from src.ai.llm_provider import BaseLLMProvider, PendingToolCall, create_provider
from src.ai.tool_registry import get_anthropic_tool_schemas, get_tool_by_name
from src.core.exceptions import ApplicationError, ServiceError
from src.core.logger import get_logger
from src.services.workspace_service import Dataset, WorkspaceService

_logger = get_logger(__name__)

# Scoped to "answer thoroughly about the active dataset using the
# available tools," not "answer any question about anything." Within
# that scope, explicitly instructed not to dodge or give up on a
# legitimate multi-step data question.
_SYSTEM_PROMPT = (
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
        self._provider: BaseLLMProvider = create_provider(provider_name, api_key)
        self._workspace_service = workspace_service
        self._history: list[Any] = []

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

        self._history = self._provider.append_user_message(self._history, user_message)
        new_datasets: list[Dataset] = []
        tool_schemas = get_anthropic_tool_schemas()

        while True:
            turn, raw_response = self._provider.send(
                self._history, _SYSTEM_PROMPT, tool_schemas
            )
            self._history = self._provider.append_assistant_turn(
                self._history, raw_response
            )

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

            self._history = self._provider.append_tool_results(self._history, results)

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
