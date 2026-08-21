# File: tests/ai/test_assistant_service.py
"""Tests for src.ai.assistant_service.AssistantService.

Grounded directly in AssistantService.send_message()/_execute_tool()
(read in full before writing any assertion here), not assumptions:

* A cleaning tool's return value (a Dataset) is registered via
  ``workspace_service.add_dataset()`` and never assigned back onto the
  dataset that was active when the turn started — the loop's local
  ``active_dataset`` variable is reassigned for *routing subsequent
  tool calls in the same turn*, but WorkspaceService's own active
  dataset (``get_active_dataset()``) is untouched by this whole path;
  nothing in send_message()/_execute_tool() ever calls
  ``set_active_dataset()``. Both halves of that rule are asserted
  below.
* ``_execute_tool()`` catches ``KeyError`` (unknown tool name) and
  both ``ApplicationError`` and bare ``Exception`` from a tool handler,
  turning each into a `(f"Error: ..."/"Unexpected error: ...", None)`
  result rather than letting the conversation loop raise — this is
  the "tool call fails, read the error and try a corrected call"
  behavior the system prompt itself documents.
* Multi-step tool chaining (profile, then correlate) is exactly the
  system prompt's own worked example ("profiling first to find which
  columns are numeric, then computing a correlation") — the
  conversation loop keeps calling provider.send() as long as
  turn.tool_calls is non-empty, so this is tested by scripting a
  three-turn FakeLLMProvider sequence: tool call, tool call, final
  text.
* Tool scope: every ToolDefinition.handler in tool_registry.py takes
  the *active* Dataset as a positional first argument the model never
  supplies (no schema in get_anthropic_tool_schemas() exposes a
  dataset_id/dataset selector field) — a tool call literally cannot
  address any dataset other than whichever one _execute_tool() was
  called with. This is asserted two ways: schema inspection (no
  input_schema anywhere accepts a dataset selector) and behavior (a
  second, non-active dataset sitting in the same workspace is provably
  untouched by a tool call executed while a different dataset is
  active).

SECRET HYGIENE: this file constructs AssistantService with only
obviously-fake placeholder API key strings (e.g.
"sk-test-not-a-real-key"). No fixture, mock response, or literal here
is a real credential of any kind. Note per this work item's own
instructions: .claude/hooks/protect-files.ps1 only blocks writes by
*filename* pattern (.env*, secrets.json, credentials.json, *.pem,
*.key) — it does not inspect file content for secret-shaped strings,
so this file's safety rests on careful authoring, not on that hook
catching a mistake.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.ai.assistant_service import AssistantService
from src.ai.llm_provider import LLMTurn, PendingToolCall
from src.ai.tool_registry import get_anthropic_tool_schemas
from src.core.exceptions import ServiceError
from src.services.workspace_service import Dataset, WorkspaceService
from tests.ai.conftest import make_provider

_FAKE_API_KEY = "sk-test-not-a-real-key"


# -- Rule 1: cleaning tool results become a NEW dataset, never a mutation --------


def test_cleaning_tool_result_is_added_as_new_dataset_not_a_mutation(
    workspace: WorkspaceService,
    active_dataset: Dataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_row_count = active_dataset.row_count
    original_dataframe_snapshot = active_dataset.dataframe.copy()

    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(call_id="1", name="drop_missing_values", arguments={})
            ],
        ),
        LLMTurn(
            text="Done — created a new dataset with missing rows removed.",
            tool_calls=[],
        ),
    ]
    make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Please drop rows with missing values.")

    # A second, real dataset now exists in the workspace.
    assert len(workspace.list_datasets()) == 2
    assert len(result.new_datasets) == 1
    new_dataset = result.new_datasets[0]
    assert new_dataset.dataset_id != active_dataset.dataset_id
    assert new_dataset.parent_dataset_id == active_dataset.dataset_id
    # Identity check via dataset_id, not `in`/`==`: Dataset is a plain
    # @dataclass whose generated __eq__ compares every field including
    # `dataframe`, and pandas DataFrame.__eq__ raises ValueError for
    # differently-shaped/labeled frames rather than returning a bool
    # — so `new_dataset in workspace.list_datasets()` blows up instead
    # of returning False/True the way it would for an ordinary object.
    assert new_dataset.dataset_id in {d.dataset_id for d in workspace.list_datasets()}

    # The originally-active dataset itself is untouched: same object,
    # same row count, same data (DropMissingValues.apply() never
    # mutates its input — see src/cleaning/missing_values.py).
    assert active_dataset.row_count == original_row_count
    pd.testing.assert_frame_equal(active_dataset.dataframe, original_dataframe_snapshot)

    # WorkspaceService's own active-dataset pointer is untouched by
    # this whole path — nothing in AssistantService calls
    # set_active_dataset(). The new dataset is registered but not made
    # active.
    assert workspace.get_active_dataset() is active_dataset
    assert workspace.get_active_dataset().dataset_id != new_dataset.dataset_id


def test_cleaning_tool_result_appears_in_turn_result_reply_text(
    workspace: WorkspaceService,
    active_dataset: Dataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(call_id="1", name="drop_missing_values", arguments={})
            ],
        ),
        LLMTurn(text="A new cleaned dataset was created.", tool_calls=[]),
    ]
    make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Clean the missing values.")

    assert result.reply_text == "A new cleaned dataset was created."


# -- Rule 2: tool-call error recovery -------------------------------------------


def test_unknown_tool_name_is_reported_back_as_recoverable_error_not_raised(
    workspace: WorkspaceService,
    active_dataset: Dataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_execute_tool() catches get_tool_by_name()'s KeyError and turns it into an "Error: ..." result."""
    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(call_id="1", name="not_a_real_tool", arguments={})
            ],
        ),
        LLMTurn(
            text="Sorry, I made a mistake and could not find that tool.", tool_calls=[]
        ),
    ]
    fake_provider = make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Do something.")

    # The conversation did not raise; it completed with the second
    # scripted turn's text, meaning the loop successfully recovered.
    assert result.reply_text == "Sorry, I made a mistake and could not find that tool."
    assert result.new_datasets == []
    assert fake_provider.send_call_count == 2

    # The error text that was actually reported back to the model is
    # inspectable via our own test double, not via AssistantService
    # internals: it must be exactly the documented "Error: ..." shape.
    reported = fake_provider.tool_result_calls[0]
    assert len(reported) == 1
    _, result_text = reported[0]
    assert result_text.startswith("Error: ")
    assert "not_a_real_tool" in result_text


def test_tool_call_with_invalid_arguments_is_reported_as_error_and_produces_no_dataset(
    workspace: WorkspaceService,
    active_dataset: Dataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ServiceError raised by the underlying operation (an ApplicationError) is caught, not raised."""
    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(
                    call_id="1",
                    name="drop_missing_values",
                    arguments={"columns": ["not_a_real_column"]},
                )
            ],
        ),
        LLMTurn(
            text="That column does not exist; let me try differently.", tool_calls=[]
        ),
    ]
    fake_provider = make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Drop missing values in 'not_a_real_column'.")

    assert result.reply_text == "That column does not exist; let me try differently."
    assert result.new_datasets == []
    # No second dataset was created — the failed tool call did not
    # touch WorkspaceService at all.
    assert len(workspace.list_datasets()) == 1

    _, result_text = fake_provider.tool_result_calls[0][0]
    assert result_text.startswith("Error: ")
    assert "not_a_real_column" in result_text


def test_tool_call_with_unexpected_keyword_argument_is_caught_as_unexpected_error(
    workspace: WorkspaceService,
    active_dataset: Dataset,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-ApplicationError raised by a handler (e.g. a bad kwarg -> TypeError) hits the second except clause."""
    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(
                    call_id="1",
                    name="profile_dataset",
                    # profile_dataset's handler takes only `dataset` — an
                    # extra kwarg the model hallucinated raises a plain
                    # TypeError, not an ApplicationError.
                    arguments={"unexpected_argument": "surprise"},
                )
            ],
        ),
        LLMTurn(text="Let me retry without that argument.", tool_calls=[]),
    ]
    fake_provider = make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Profile the dataset.")

    assert result.reply_text == "Let me retry without that argument."
    _, result_text = fake_provider.tool_result_calls[0][0]
    assert result_text.startswith("Unexpected error: ")


# -- Multi-step tool chaining (system prompt's own profile-then-correlate example) --


def test_multi_step_tool_chaining_profile_then_correlate(
    workspace: WorkspaceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = Dataset(
        name="numeric_data",
        dataframe=pd.DataFrame({"x": [1, 2, 3, 4], "y": [10, 20, 30, 40]}),
        source_format="csv",
    )
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)

    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(call_id="1", name="profile_dataset", arguments={})
            ],
        ),
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(
                    call_id="2",
                    name="compute_correlation",
                    arguments={"method": "pearson"},
                )
            ],
        ),
        LLMTurn(text="x and y are perfectly correlated.", tool_calls=[]),
    ]
    fake_provider = make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Which numeric columns correlate?")

    assert fake_provider.send_call_count == 3
    assert result.reply_text == "x and y are perfectly correlated."
    # Neither tool in this chain produces a Dataset (both are
    # analysis, not cleaning, tools) — no new dataset should appear.
    assert result.new_datasets == []
    assert len(workspace.list_datasets()) == 1

    # Two distinct tool results were reported back, one per step of
    # the chain, each against a *result* dict (JSON-serialized), never
    # an "Error:"/"Unexpected error:" string.
    assert len(fake_provider.tool_result_calls) == 2
    _, profile_result_text = fake_provider.tool_result_calls[0][0]
    _, correlation_result_text = fake_provider.tool_result_calls[1][0]
    assert not profile_result_text.startswith("Error")
    assert not correlation_result_text.startswith("Error")


def test_second_cleaning_tool_in_a_chain_operates_on_the_dataset_the_first_produced(
    workspace: WorkspaceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirms _execute_tool()'s `active_dataset = produced_dataset` reassignment: chained cleaning ops compose."""
    dataset = Dataset(
        name="dupes_and_case",
        dataframe=pd.DataFrame({"label": ["A", "A", " b ", "c"]}),
        source_format="csv",
    )
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)

    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(call_id="1", name="drop_duplicates", arguments={})
            ],
        ),
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(
                    call_id="2",
                    name="normalize_text",
                    arguments={"columns": ["label"], "trim_whitespace": True},
                )
            ],
        ),
        LLMTurn(text="Cleaned up duplicates and whitespace.", tool_calls=[]),
    ]
    make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Drop duplicates then trim whitespace.")

    assert len(result.new_datasets) == 2
    dedup_dataset, normalized_dataset = result.new_datasets
    # The second tool's output is derived from the FIRST tool's
    # output, not from the originally-active dataset — proving the
    # loop's local active_dataset variable was reassigned in between.
    assert normalized_dataset.parent_dataset_id == dedup_dataset.dataset_id
    assert dedup_dataset.parent_dataset_id == dataset.dataset_id
    assert len(workspace.list_datasets()) == 3


# -- Rule 4: tool scope never exceeds the active dataset ------------------------


def test_no_tool_schema_exposes_a_dataset_selector() -> None:
    """No tool the model can call accepts a dataset_id/dataset-name argument — every handler is scoped by call site only."""
    for schema in get_anthropic_tool_schemas():
        properties = schema["input_schema"].get("properties", {})
        assert "dataset_id" not in properties
        assert "dataset" not in properties


def test_tool_call_cannot_reach_a_non_active_dataset_in_the_same_workspace(
    workspace: WorkspaceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    active = Dataset(
        name="active_one", dataframe=pd.DataFrame({"n": [1, None]}), source_format="csv"
    )
    other = Dataset(
        name="other_untouched",
        dataframe=pd.DataFrame({"n": [None, None]}),
        source_format="csv",
    )
    workspace.add_dataset(active)
    workspace.add_dataset(other)
    workspace.set_active_dataset(active.dataset_id)
    other_snapshot = other.dataframe.copy()

    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(call_id="1", name="drop_missing_values", arguments={})
            ],
        ),
        LLMTurn(text="Done.", tool_calls=[]),
    ]
    make_provider(monkeypatch, turns)

    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)
    result = service.send_message("Drop missing values.")

    # The only new dataset produced is derived from the active
    # dataset — "other" was never a valid target because nothing in
    # the tool call vocabulary can name it.
    assert result.new_datasets[0].parent_dataset_id == active.dataset_id
    # "other" is provably untouched: same object, same data, and no
    # dataset in the workspace claims it as a parent.
    pd.testing.assert_frame_equal(other.dataframe, other_snapshot)
    assert all(
        d.parent_dataset_id != other.dataset_id for d in workspace.list_datasets()
    )


# -- No active dataset -----------------------------------------------------------


def test_send_message_raises_service_error_when_no_active_dataset(
    workspace: WorkspaceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_provider(monkeypatch, turns=[])  # send() must never be reached
    service = AssistantService("anthropic", _FAKE_API_KEY, workspace)

    with pytest.raises(ServiceError, match="No active dataset"):
        service.send_message("Anything.")
