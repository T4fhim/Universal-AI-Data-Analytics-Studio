# File: tests/assets/test_ui_behaviour_exports.py
"""Fidelity tests for the Phase 2.4b behaviour/layout/constants/copy exports.

Companion to :mod:`tests.assets.test_ui_contract_exports`. These cover the second batch mined
out of ``src/ui/`` before sub-step 2.5 deleted it: the default workspace layout, menu / toolbar
structure, named UI constants, file-picker filters, mapping tables, a full inventory of
user-facing copy, and the prose rules document.

Like its companion, nothing here imports ``src.ui``. What it does instead is cross-check each
export back into **surviving** live code -- the action registry, ``PipelineStage``, the chart
registry, the reader registry, the tool registry and the default config -- because a recorded
fact that disagrees with the live system is the failure mode that matters. A pinned count only
catches truncation; a cross-check catches an export that was wrong on the day it was written, or
that has drifted since.
"""

from __future__ import annotations

import json

import pytest

from uadas_core.core.constants import PROJECT_ROOT

CONTRACT_DIR = PROJECT_ROOT / "assets" / "ui-contract"

EXPECTED_COPY_COUNT = 345
EXPECTED_COPY_FILES = 41
EXPECTED_DATASET_FILTER_GROUPS = 17
EXPECTED_HANDLER_COUNT = 15


def _load(name: str) -> dict:
    path = CONTRACT_DIR / name
    assert (
        path.is_file()
    ), f"{name} is missing -- the Qt source it came from no longer exists"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def layout() -> dict:
    return _load("workspace-layout.json")


@pytest.fixture(scope="module")
def constants() -> dict:
    return _load("ui-constants.json")


@pytest.fixture(scope="module")
def filters() -> dict:
    return _load("file-picker-filters.json")


@pytest.fixture(scope="module")
def tables() -> dict:
    return _load("ui-mapping-tables.json")


@pytest.fixture(scope="module")
def copy() -> dict:
    return _load("ui-copy.json")


@pytest.fixture(scope="module")
def registered_action_ids() -> set[str]:
    # Importing the module registers the built-ins as a side effect.
    from uadas_core.actions import builtin_actions  # noqa: F401
    from uadas_core.actions.action_registry import list_actions

    return set(list_actions())


@pytest.fixture(scope="module")
def chart_registry():
    from uadas_core.visualization import chart_registry as registry

    # The repo's own tests/conftest.py seeds the registry the same way.
    registry._register_builtins()
    return registry


# -- provenance ------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "workspace-layout.json",
        "ui-constants.json",
        "file-picker-filters.json",
        "ui-mapping-tables.json",
        "ui-copy.json",
    ],
)
def test_every_export_carries_its_provenance(filename: str) -> None:
    payload = _load(filename)
    assert payload["$provenance"].strip(), f"{filename} has an empty $provenance"
    assert payload["generated_from"], f"{filename} does not name a source"


# -- workspace layout ------------------------------------------------------


def test_the_six_docks_are_all_recorded(layout: dict) -> None:
    ids = {d["id"] for d in layout["docks"]}
    assert ids == {
        "dataset_explorer",
        "console",
        "log",
        "chart",
        "data_table",
        "ai_assistant",
    }


def test_default_arrangement_matches_the_recorded_decisions(layout: dict) -> None:
    """The arrangement existed nowhere else, so each decision is pinned individually."""
    docks = {d["id"]: d for d in layout["docks"]}

    assert docks["dataset_explorer"]["area"] == "left"
    assert docks["console"]["tab_group"] == docks["log"]["tab_group"] == "bottom"
    assert docks["chart"]["tab_group"] == docks["data_table"]["tab_group"]
    assert docks["chart"]["tab_group"] is not None

    # The chart dock is the one that starts hidden; everything else starts visible.
    assert docks["chart"]["default_visible"] is False
    assert all(d["default_visible"] for k, d in docks.items() if k != "chart")

    # The assistant is stacked below the chart, deliberately NOT tabbed with it.
    assert docks["ai_assistant"]["split_below"] == "chart"
    assert docks["ai_assistant"]["tab_group"] is None


def test_the_log_dock_is_titled_log_not_logging(layout: dict) -> None:
    """The class and module say 'Logging'; the user-visible title is 'Log'."""
    titles = {d["id"]: d["title"] for d in layout["docks"]}
    assert titles["log"] == "Log"
    assert titles["chart"] == "Charts"


def test_view_menu_order_lists_every_dock_title(layout: dict) -> None:
    titles = [d["title"] for d in layout["docks"]]
    assert sorted(layout["dock_view_menu_order"]) == sorted(titles)


def test_menu_order_is_recorded(layout: dict) -> None:
    assert [m["label"] for m in layout["menus"]] == [
        "&File",
        "&Edit",
        "&View",
        "&Analysis",
        "&Help",
    ]


def _menu_action_ids(layout: dict) -> set[str]:
    return {
        item
        for menu in layout["menus"]
        for item in menu["items"]
        if isinstance(item, str) and "." in item and not item.startswith("<")
    }


def test_every_menu_toolbar_and_handler_id_is_a_registered_action(
    layout: dict, registered_action_ids: set[str]
) -> None:
    """Cross-check into live code: the layout may not name an action that does not exist."""
    toolbar_ids = {i for i in layout["toolbar"]["items"] if i != "-"}
    handler_ids = set(layout["action_handlers"])
    menu_ids = _menu_action_ids(layout)

    assert menu_ids <= registered_action_ids, menu_ids - registered_action_ids
    assert toolbar_ids <= registered_action_ids, toolbar_ids - registered_action_ids
    assert handler_ids <= registered_action_ids, handler_ids - registered_action_ids


def test_every_menu_item_has_a_recorded_handler(layout: dict) -> None:
    handlers = set(layout["action_handlers"])
    assert len(handlers) == EXPECTED_HANDLER_COUNT
    missing = _menu_action_ids(layout) - handlers
    assert not missing, f"menu items with no recorded handler: {missing}"


def test_unbound_registry_actions_are_exactly_the_stage_navigation_ones(
    layout: dict, registered_action_ids: set[str]
) -> None:
    """The handler table's note explains the gap; this proves the explanation is complete.

    Every registered action is either in the 15-row table or is a ``workbench.go_to_*`` stage
    navigation action (bound by GuidanceController). Anything else would be an action whose
    handler was never recorded.
    """
    unbound = registered_action_ids - set(layout["action_handlers"])
    assert unbound, "expected the stage-navigation actions to be unbound here"
    assert all(a.startswith("workbench.go_to_") for a in unbound), unbound
    # Upload has no page, so it has no navigation action.
    assert "workbench.go_to_upload" not in unbound


def test_the_stale_dock_comment_is_flagged(layout: dict) -> None:
    """A source comment contradicted the code; the export must say which one is right."""
    joined = " ".join(layout["layout_rationale"])
    assert "stale comment" in joined
    assert "code is authoritative" in joined


def test_command_palette_contract_survives(layout: dict) -> None:
    palette = layout["command_palette"]
    assert palette["shortcut"] == "Ctrl+K"
    assert palette["min_width_px"] == 480
    assert palette["disabled_actions_shown"] is True
    assert "action_id" in palette["filter"]


# -- constants -------------------------------------------------------------


def test_data_table_constants_are_pinned(constants: dict) -> None:
    by_name = {c["name"]: c["value"] for c in constants["data_table"]}
    assert by_name == {
        "WORKER_FILTER_THRESHOLD_ROWS": 200_000,
        "COLUMN_WIDTH_SAMPLE_ROWS": 200,
        "MAX_COLUMN_WIDTH_PX": 400,
        "COLUMN_WIDTH_PADDING_PX": 24,
        "COLUMN_CHOOSER_THRESHOLD_COLUMNS": 1000,
        "ROW_HEIGHT_PX": 24,
    }


def test_status_bar_and_guidance_constants_are_pinned(constants: dict) -> None:
    status = {c["name"]: c["value"] for c in constants["status_bar"]}
    assert status["DEFAULT_MESSAGE_TIMEOUT_MS"] == 5000
    assert constants["guidance"][0]["value"] == 5
    assert constants["dashboard_auto_layout"]["columns"] == 2


def test_every_constant_carries_a_rationale(constants: dict) -> None:
    """A bare number is half the fact: the *why* is what a rewrite cannot re-derive."""
    for section in ("data_table", "status_bar", "guidance", "settings_dialog_ranges"):
        for item in constants[section]:
            assert item["rationale"].strip(), f"{section}: {item.get('name')}"


def test_settings_ranges_are_coherent_and_agree_with_the_live_defaults(
    constants: dict,
) -> None:
    """Cross-check into live code: the recorded defaults must be the real config defaults.

    The bounds exist only in the export (config validation type-checks and does not
    range-check), but the defaults they sit around live in ``uadas_core.core.config``.
    """
    from uadas_core.core.config import _default_config_dict

    defaults = _default_config_dict()
    live = {
        "autosave interval": defaults["autosave"]["interval_minutes"],
        "base font size": defaults["accessibility"]["base_font_size"],
    }
    for entry in constants["settings_dialog_ranges"]:
        assert entry["min"] < entry["max"]
        assert entry["min"] <= entry["default"] <= entry["max"]
        assert entry["default"] == live[entry["field"]], entry["field"]


def test_qss_component_metrics_keep_the_wcag_target_size_floor(constants: dict) -> None:
    """The 24px minimum target size was a documented WCAG 2.5.8 decision, recorded in a stylesheet
    comment that is deleted along with the stylesheet -- so the number and its reason are pinned.
    """
    block = constants["qss_component_metrics"]
    assert block["min_target_size_px"] == 24
    assert "2.5.8" in block["min_target_size_rationale"]
    assert len(block["metrics"]) == 17
    two_line_rows = next(
        m for m in block["metrics"] if "guidanceSuggestionList" in m["selector"]
    )
    assert two_line_rows["min_height_px"] == 40
    assert "two lines" in two_line_rows["note"]


def test_the_spacing_scale_the_stylesheet_relied_on_survives_in_the_token_module(
    constants: dict,
) -> None:
    """Cross-check into live code: the export says spacing/radius/focus are tokenised elsewhere.

    ``space_1``..``space_5`` are derived (not dataclass fields) by ``ThemeTokens.space`` and
    exposed to the stylesheet through ``as_qss_mapping``, so assert behaviour: the scale exists,
    strictly increases, and is density-driven.
    """
    from dataclasses import fields

    from uadas_core.theme.tokens import DARK_TOKENS, Density, ThemeTokens

    assert "tokenised" in constants["qss_component_metrics"]["note"]
    names = {f.name for f in fields(ThemeTokens)}
    assert {"radius_sm", "radius_md", "focus_ring", "focus_ring_width"} <= names

    steps = [DARK_TOKENS.space(step) for step in range(1, 6)]
    assert steps == sorted(set(steps)), "the spacing scale must strictly increase"
    mapping = DARK_TOKENS.as_qss_mapping()
    assert all(f"space_{step}" in mapping for step in range(1, 6))

    # Density drives the scale: comfortable is looser than cozy, which is looser than compact.
    comfortable = DARK_TOKENS.with_density(Density.COMFORTABLE).space(3)
    cozy = DARK_TOKENS.with_density(Density.COZY).space(3)
    compact = DARK_TOKENS.with_density(Density.COMPACT).space(3)
    assert comfortable > cozy > compact


# -- file-picker filters ---------------------------------------------------


def test_dataset_filter_groups(filters: dict) -> None:
    groups = filters["dataset_open"]["groups"]
    assert len(groups) == EXPECTED_DATASET_FILTER_GROUPS
    assert groups[0]["label"] == "All Supported Datasets"
    for group in groups:
        assert group["patterns"], group["label"]
        assert all(p.startswith("*.") for p in group["patterns"]), group["label"]


def test_dataset_filter_covers_exactly_the_extensions_the_readers_accept(
    filters: dict,
) -> None:
    """The one place the UI and the registry were hand-synchronised, and could drift.

    ``CLAUDE.md`` warns that the file filter does not derive from the reader registry. At
    extraction time the two sets were identical (29 extensions, no extras either way); this
    test turns that into a standing guarantee for whatever upload control Phase 4 builds.
    """
    from uadas_core.readers.reader_registry import _BUILTIN_READERS

    from_readers = {
        ext.lower()
        for reader in _BUILTIN_READERS
        for ext in reader.SUPPORTED_EXTENSIONS
    }
    from_filter = {
        pattern.lower().removeprefix("*")
        for group in filters["dataset_open"]["groups"]
        for pattern in group["patterns"]
    }
    assert from_filter == from_readers


def test_report_formats_are_four_in_this_order(filters: dict) -> None:
    formats = filters["report_export"]["formats"]
    assert [f["key"] for f in formats] == ["pdf", "html", "docx", "xlsx"]
    assert all(f["extension"] == f["key"] for f in formats)


# -- mapping tables --------------------------------------------------------


def test_recommendation_order_is_pinned_and_keeps_its_warning(tables: dict) -> None:
    block = tables["recommendation_field_order"]
    order = block["value"]
    assert order["line"] == ["x_column", "y_column"]
    assert "heatmap" not in order
    assert "SILENTLY SWAPS" in block["CORRECTNESS_CRITICAL"]


def test_recommendation_order_names_real_fields_of_real_charts(
    tables: dict, chart_registry
) -> None:
    """Cross-check into live code, and a direct proof of the Line trap the note describes.

    Every chart in the table is registered and every field it names is a real field on that
    chart. For ``line`` the recommender's order is ``[x, y]`` while the chart's *required*
    field is ``y`` alone (``x`` optional), which is exactly why a positional zip against
    ``required_fields`` would swap them.
    """
    order = tables["recommendation_field_order"]["value"]
    for chart, fields in order.items():
        registration = chart_registry.get_chart(chart)
        known = set(registration.required_fields) | set(registration.optional_fields)
        assert set(fields) <= known, f"{chart}: {set(fields) - known}"

    line = chart_registry.get_chart("line")
    assert line.required_fields == ("y_column",)
    assert tuple(order["line"]) != tuple(line.required_fields)

    # Heatmap is genuinely column-less, which is why it is absent from the table.
    assert chart_registry.get_chart("heatmap").required_fields == ()


def test_report_section_labels_are_eight_of_ten_stages(tables: dict) -> None:
    from uadas_core.services.analysis_orchestrator_service import PipelineStage

    labels = tables["report_section_labels"]["value"]
    stages = {s.name for s in PipelineStage}
    assert set(labels) <= stages, set(labels) - stages
    assert stages - set(labels) == {"REPORT", "REPRODUCE"}
    assert len(labels) == 8


def test_explanation_fields_are_real_explanation_fields(tables: dict) -> None:
    from dataclasses import fields

    from uadas_core.analysis.explanation import Explanation

    recorded = [f["field"] for f in tables["explanation_fields"]["value"]]
    assert len(recorded) == 7
    live = {f.name for f in fields(Explanation)}
    assert set(recorded) <= live, set(recorded) - live


def test_forecaster_menu_lists_real_tools_with_the_comparison_first(
    tables: dict,
) -> None:
    from uadas_core.ai.tool_registry import TOOLS

    menu = tables["forecaster_menu"]
    tool_names = {t.name for t in TOOLS}
    assert menu["automatic_model_competition_tool"] in tool_names
    assert menu["order"][0] == "Automatic Model Competition"
    # Each remaining label must be derivable from a real forecast_* tool.
    derived = {
        name.replace("forecast_", "").replace("_", " ").title()
        for name in tool_names
        if name.startswith("forecast_")
    }
    assert set(menu["order"][1:]) <= derived, set(menu["order"][1:]) - derived
    assert "Arima" in menu["order"], "the label rule yields 'Arima', not 'ARIMA'"


# -- copy inventory --------------------------------------------------------


def test_copy_inventory_size_is_pinned(copy: dict) -> None:
    assert copy["count"] == EXPECTED_COPY_COUNT
    assert copy["files"] == EXPECTED_COPY_FILES
    assert sum(len(v) for v in copy["by_file"].values()) == copy["count"]


def test_copy_inventory_has_no_empty_entries(copy: dict) -> None:
    for source, entries in copy["by_file"].items():
        assert source.startswith("src/ui/"), source
        assert "/a11y/" not in source, "a11y copy lives in the a11y-*.json exports"
        for entry in entries:
            assert entry["text"].strip(), f"{source}:{entry['line']}"


def test_copy_inventory_keeps_the_strings_independent_sweeps_flagged(
    copy: dict,
) -> None:
    """A recall check: copy that independent reviewers named as load-bearing must be present."""
    everything = "\n".join(
        entry["text"] for entries in copy["by_file"].values() for entry in entries
    )
    for needle in (
        "Missing Required Fields",
        "Show tour again next time",
        "Unexpected Error",
        "Close Dataset",
        "Pick Columns",
        "Configure Chart",
        "Sections to include",
        "(New profile)",
        "Select Columns",
        "No Active Dataset",
        "Loaded dataset:",
        "never the password",
        "Pre-flight validation failed",
        "No AI provider configured",
        "Type to search actions",
    ):
        assert needle in everything, f"copy inventory lost {needle!r}"


# -- behaviour rules document ----------------------------------------------


@pytest.fixture(scope="module")
def rules_text() -> str:
    path = CONTRACT_DIR / "ui-behaviour-rules.md"
    assert path.is_file(), "ui-behaviour-rules.md is missing"
    return path.read_text(encoding="utf-8")


def test_rules_document_keeps_all_seven_sections(rules_text: str) -> None:
    for heading in (
        "## 1. Data table",
        "## 2. Async and orchestration",
        "## 3. Navigation and stage pages",
        "## 4. Dialogs and forms",
        "## 5. Product rules",
        "## 6. Chart bridge",
        "## 7. Where else the rest lives",
    ):
        assert heading in rules_text, f"lost section {heading!r}"


def test_rules_document_keeps_its_load_bearing_rejections(rules_text: str) -> None:
    """The reasoning about why the simple alternative is wrong is the irreplaceable part."""
    for phrase in (
        "Missing values always sort last, in both directions",
        "QSortFilterProxyModel",
        "Never open a modal from an asynchronous completion callback",
        "fourth zone",
        "Absence over an inert placeholder",
        "order *is* the failover order",
        "Undo is a pointer move, not a replay",
    ):
        assert phrase in rules_text, f"rules document lost {phrase!r}"


def test_rules_document_points_only_at_files_that_exist() -> None:
    """Section 7's table names surviving locations; each must still exist."""
    for relative in (
        "uadas_core/services/analysis_orchestrator_service.py",
        "uadas_core/actions/builtin_actions.py",
        "uadas_core/theme/tokens.py",
        "uadas_core/help",
        "uadas_core/core/config.py",
        "uadas_core/services/project_service.py",
        "uadas_core/jobs/job_runner.py",
        "uadas_core/command_stack.py",
        "plans/ui-overhaul-pioneering-adaptive-workbench.md",
        "resources/web/chart_host.html",
        "resources/web/chart_bridge.js",
        "docs/manual/pipeline",
    ):
        assert (PROJECT_ROOT / relative).exists(), f"{relative} no longer exists"
