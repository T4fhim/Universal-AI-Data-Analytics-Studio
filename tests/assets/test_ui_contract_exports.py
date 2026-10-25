# File: tests/assets/test_ui_contract_exports.py
"""Fidelity tests for the Phase 2.4 UI-contract exports under ``assets/ui-contract/``.

These exist because sub-step 2.5 deletes ``src/ui/`` outright. Everything in
``assets/ui-contract/`` was mined out of those Qt modules first, and after the
deletion there is no source left to re-derive it from -- the JSON *is* the
surviving copy of that data. So these assertions are not "does the exporter
work"; they are a tripwire against the data silently rotting or being truncated
between here and Phase 4, when a React UI finally consumes it.

Deliberately written to survive 2.5: nothing here imports ``src.ui``. The one
cross-boundary check (help anchors) goes through
:mod:`uadas_core.help.manual_index`, which was lifted to ``uadas_core`` in 2.1
and stays, and against ``docs/manual/``, which stays too.
"""

from __future__ import annotations

import json

import pytest

from uadas_core.core.constants import PROJECT_ROOT
from uadas_core.help.manual_index import ManualIndex

CONTRACT_DIR = PROJECT_ROOT / "assets" / "ui-contract"

# Counts pinned at extraction time (commit 4bd0dc5, against the pre-2.5 tree).
# A change here means the export was regenerated or edited -- which is allowed,
# but it should be a deliberate edit with the number updated in the same commit,
# never a silent drift.
EXPECTED_RULE_COUNT = 8
EXPECTED_DESCRIPTOR_COUNT = 69
EXPECTED_STATE_COUNT = 4

EXPECTED_RULE_IDS = {
    "interactive-name",
    "input-buddy",
    "focus-reachable",
    "dialog-focus-trap",
    "duplicate-shortcut",
    "dock-title",
    "decorative-illustration",
    "tab-order",
}


def _load(name: str) -> dict:
    path = CONTRACT_DIR / name
    assert (
        path.is_file()
    ), f"{name} is missing -- the Qt source it came from no longer exists"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rules() -> dict:
    return _load("a11y-rules.json")


@pytest.fixture(scope="module")
def descriptors() -> dict:
    return _load("a11y-descriptors.json")


@pytest.fixture(scope="module")
def states() -> dict:
    return _load("empty-error-state-copy.json")


# -- provenance ------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "a11y-rules.json",
        "a11y-descriptors.json",
        "stage-status-prefixes.json",
        "empty-error-state-copy.json",
    ],
)
def test_every_export_carries_its_provenance(filename: str) -> None:
    """Each export says where it came from.

    Without this the files are anonymous blobs the moment ``src/ui/`` is gone,
    and the next person cannot tell generated data from hand-edited data.
    """
    payload = _load(filename)
    assert payload["$provenance"].strip(), f"{filename} has an empty $provenance"
    assert payload["generated_from"], f"{filename} does not name a source"


# -- a11y rules ------------------------------------------------------------


def test_a11y_rules_are_complete(rules: dict) -> None:
    ids = {r["rule_id"] for r in rules["rules"]}
    assert len(rules["rules"]) == EXPECTED_RULE_COUNT
    assert ids == EXPECTED_RULE_IDS


def test_a11y_rules_are_individually_usable(rules: dict) -> None:
    """A rule with no description cannot be reimplemented against the DOM."""
    for rule in rules["rules"]:
        assert rule["description"].strip(), f"{rule['rule_id']} has no description"
        assert rule[
            "check_function"
        ].strip(), f"{rule['rule_id']} lost its check-function name"


def test_a11y_severity_vocabulary_is_preserved(rules: dict) -> None:
    assert rules["severity_vocabulary"] == ["error", "warning"]


# -- a11y descriptors ------------------------------------------------------


def test_descriptor_count_matches_the_export_header(descriptors: dict) -> None:
    assert descriptors["count"] == len(descriptors["descriptors"])
    assert descriptors["count"] == EXPECTED_DESCRIPTOR_COUNT


def test_no_descriptor_is_silently_empty(descriptors: dict) -> None:
    """Every call site yielded either a literal name or a recorded expression.

    This is the assertion that would have caught the extractor dropping
    ``self.tr(...)``-wrapped copy on the floor: a record with neither a name nor
    a ``non_literal`` entry is a call site whose content was lost.
    """
    for item in descriptors["descriptors"]:
        has_literal = any(
            item.get(field)
            for field in ("name", "description", "status_tip", "tooltip", "help_anchor")
        )
        assert has_literal or item.get(
            "non_literal"
        ), f"{item['source']} carries no content"


def test_every_descriptor_is_traceable_to_its_origin(descriptors: dict) -> None:
    for item in descriptors["descriptors"]:
        assert ":" in item["source"], f"{item['source']} is not a file:line reference"
        assert item["source"].startswith("src/ui/")


def test_help_anchors_resolve_against_the_real_manual(descriptors: dict) -> None:
    """The one check that crosses from the export back into live code.

    ``docs/manual/`` and ``uadas_core.help.manual_index`` both outlive 2.5, so a
    help anchor recorded here can still be proven to point at a real page.
    """
    anchors = {d["help_anchor"] for d in descriptors["descriptors"] if d["help_anchor"]}
    assert (
        anchors
    ), "no help anchors were captured -- the extractor likely missed the kwarg"
    for anchor in sorted(anchors):
        assert ManualIndex.anchor_exists(
            anchor
        ), f"help anchor {anchor!r} resolves to no page"


# -- stage status prefixes -------------------------------------------------


def test_stage_status_prefixes_keep_their_exact_glyphs() -> None:
    """The trailing space is part of the encoding, so compare exactly."""
    prefixes = _load("stage-status-prefixes.json")["status_prefixes"]
    assert prefixes == {"complete": "✓ ", "proposed": "→ ", "pending": "· "}


# -- first-run tour --------------------------------------------------------


def test_first_run_tour_copy_survived_intact() -> None:
    text = (CONTRACT_DIR / "first-run-tour.md").read_text(encoding="utf-8")
    assert text.startswith("# Welcome to ")
    # The three things the tour actually promises the user.
    assert "stage rail" in text
    assert "F1" in text
    assert "optional" in text.lower()


# -- empty / error state copy ----------------------------------------------


def test_state_copy_count(states: dict) -> None:
    assert states["count"] == len(states["states"]) == EXPECTED_STATE_COUNT


def test_state_components_are_known(states: dict) -> None:
    assert {s["component"] for s in states["states"]} == {"EmptyState", "ErrorState"}


def test_every_state_kept_its_heading(states: dict) -> None:
    """Either a literal heading, or the expression that computed one.

    ``stage_page.py`` builds its heading from the stage name at runtime, so a
    literal is genuinely absent there -- but the expression must still be on
    record, otherwise the copy is simply gone.
    """
    for state in states["states"]:
        assert state["heading"] or (state.get("non_literal") or {}).get(
            "heading"
        ), f"{state['source']} lost its heading"


def test_illustration_ids_point_at_real_svgs(states: dict) -> None:
    """An illustration id that names no file would be a dead reference in Phase 4."""
    illustrations = PROJECT_ROOT / "resources" / "icons" / "illustrations"
    for state in states["states"]:
        name = state.get("illustration")
        if not name:
            continue
        assert (illustrations / f"{name}.svg").is_file(), f"{name}.svg is missing"


# -- a11y helper patterns beyond describe() --------------------------------


@pytest.fixture(scope="module")
def patterns() -> dict:
    return _load("a11y-interaction-patterns.json")


def test_the_three_non_describe_helpers_are_all_recorded(patterns: dict) -> None:
    """``describe()`` was one of four helpers in ``accessible.py``.

    The other three encode behaviour a React port has to reproduce deliberately;
    none of it falls out of putting ``aria-label`` on things. Added after the
    2.4 accessibility review found the live-region pattern was about to be lost
    at 2.5 with no surviving record.
    """
    assert {p["pattern"] for p in patterns["patterns"]} == {
        "live-region",
        "field-label-association",
        "explicit-tab-order",
    }


def test_live_region_pattern_keeps_its_reasoning(patterns: dict) -> None:
    """The *why* is the part that cannot be recovered once the Qt file is gone.

    Qt set the accessible description rather than the name on purpose: the name
    identifies the control, so announcing through it would rename the widget on
    every message. A web port that reaches for ``aria-label`` repeats the bug
    the original authors deliberately avoided.
    """
    live = next(p for p in patterns["patterns"] if p["pattern"] == "live-region")
    assert live["call_sites"], "the live-region call site was lost"
    assert "aria-live" in live["web_equivalent"]
    assert (
        "name" in live["qt_implementation"]
    ), "the name-vs-description reasoning was dropped"
    assert live["wcag"].startswith("4.1.3")


def test_every_pattern_either_has_call_sites_or_says_why_not(patterns: dict) -> None:
    """An empty call-site list must be a recorded fact, not an extraction miss."""
    for pattern in patterns["patterns"]:
        assert pattern["call_sites"] or pattern.get(
            "status"
        ), f"{pattern['pattern']} has no call sites and no explanation"


def test_descriptor_mapping_warns_about_containers(descriptors: dict) -> None:
    """``name`` -> ``aria-label`` is wrong for containers and the note must say so.

    Labelling a container overrides its contents for a screen reader, which is a
    worse outcome than the Qt original.
    """
    assert "CAVEAT" in descriptors["note"]
    assert "container" in descriptors["note"].lower()
