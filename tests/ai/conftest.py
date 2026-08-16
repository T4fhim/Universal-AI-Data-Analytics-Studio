# File: tests/ai/conftest.py
"""Shared fixtures/test doubles for tests under tests/ai/.

This package sits alongside tests/core, tests/readers, tests/cleaning,
and tests/services under the shared tests/conftest.py (config_path,
log_dir, reset_logging_state fixtures) — it adds no new top-level
pytest configuration of its own, only the AI-specific fixtures below.

FakeLLMProvider below is the seam this whole test package leans on:
:class:`~src.ai.llm_provider.BaseLLMProvider` is the documented,
already-abstract extension point AssistantService talks to (see
src/ai/assistant_service.py's own docstring: "Delegates every
provider-specific detail to src.ai.llm_provider so this class's own
logic is identical regardless of which provider is active"). Swapping
in a hand-written subclass of that same abstract base — rather than
patching individual methods on a real AnthropicProvider/GeminiProvider/
GroqProvider instance — means these tests exercise AssistantService
exactly as it is actually used, through its one real integration
point, with no real network call and no real API key ever constructed.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from src.ai.llm_provider import BaseLLMProvider, LLMTurn, PendingToolCall
from src.services.workspace_service import Dataset, WorkspaceService


class FakeLLMProvider(BaseLLMProvider):
    """A scripted BaseLLMProvider: returns a fixed sequence of LLMTurns, one per call to send().

    Records every history mutation it is asked to perform so tests can
    assert on what AssistantService actually sent back to the
    "provider" after executing a tool call (its documented contract:
    append_tool_results()'s ``results`` argument), without reaching
    into AssistantService's own private state.
    """

    def __init__(self, turns: list[LLMTurn]) -> None:
        self._turns = list(turns)
        self.send_call_count = 0
        self.tool_result_calls: list[list[tuple[PendingToolCall, str]]] = []

    def send(
        self,
        history: list[Any],
        system_prompt: str,
        tool_schemas: list[dict[str, Any]],
    ) -> tuple[LLMTurn, Any]:
        if self.send_call_count >= len(self._turns):
            raise AssertionError(
                "FakeLLMProvider.send() called more times than the "
                "scripted turn sequence provides — test double is "
                "under-specified for this conversation."
            )
        turn = self._turns[self.send_call_count]
        self.send_call_count += 1
        # The "raw response" is opaque to AssistantService by contract
        # (see BaseLLMProvider.send()'s docstring) — reusing the same
        # LLMTurn object as the raw response is legitimate here since
        # this fake's own append_assistant_turn() below only stores
        # whatever it is given, never inspects provider-specific shape.
        return turn, turn

    def append_user_message(self, history: list[Any], text: str) -> list[Any]:
        return history + [("user", text)]

    def append_assistant_turn(self, history: list[Any], raw_response: Any) -> list[Any]:
        return history + [("assistant", raw_response)]

    def append_tool_results(
        self, history: list[Any], results: list[tuple[PendingToolCall, str]]
    ) -> list[Any]:
        self.tool_result_calls.append(results)
        return history + [("tool_results", results)]


@pytest.fixture()
def workspace() -> WorkspaceService:
    """A fresh, empty WorkspaceService — real, not mocked."""
    return WorkspaceService()


@pytest.fixture()
def active_dataset(workspace: WorkspaceService) -> Dataset:
    """A dataset with some missing values, registered and made active in ``workspace``.

    Real WorkspaceService state, not a mock — Work Item 5 requires
    asserting against actual WorkspaceService mutations, not mocked
    ones.
    """
    dataset = Dataset(
        name="sales",
        dataframe=pd.DataFrame(
            {
                "region": ["east", "west", None, "east"],
                "revenue": [100, 200, 150, None],
            }
        ),
        source_format="csv",
    )
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    return dataset


def make_provider(
    monkeypatch: pytest.MonkeyPatch, turns: list[LLMTurn]
) -> FakeLLMProvider:
    """Patch src.ai.provider_rotation.create_provider to hand back a scripted FakeLLMProvider.

    Patched at ``src.ai.provider_rotation`` (milestone 7), not
    ``src.ai.assistant_service`` — since that milestone,
    ``AssistantService`` no longer calls ``create_provider`` directly;
    it goes through ``ProviderRotationService.current_provider()``,
    which is where the real ``create_provider(provider_name, api_key,
    model=None)`` call site now lives. Patching there keeps this fixture
    exercising the real construction path unchanged, only swapping what
    it resolves to — the same seam BaseLLMProvider always provided, just
    one module further down the call chain than before rotation existed.
    """
    import src.ai.provider_rotation as provider_rotation_module

    fake = FakeLLMProvider(turns)
    monkeypatch.setattr(
        provider_rotation_module,
        "create_provider",
        lambda provider_name, api_key, model=None: fake,
    )
    return fake
