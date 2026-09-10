# File: tests/ui/help/test_manual_anti_rot.py
"""The anti-rot contract test: every real ``help_anchor`` in the codebase resolves.

Per the plan's own A8 section: "a test asserts every ``ActionSpec.help_anchor`` and every
``StagePage.help_anchor`` resolves in ``ManualIndex``. F1 can never land on a missing page."
This module extends that to the third real source of ``help_anchor`` values this codebase
has -- ``BaseResultRenderer.help_anchor()`` -- and, per this milestone's own "manual has zero
stub pages" acceptance criterion, additionally asserts every resolved page has real, substantial
content rather than a placeholder.

Deliberately enumerates every anchor from the real, live registries (``list_actions()``,
``list_registered_stages()``, ``list_renderers()``) rather than a hand-maintained literal list --
a hand-maintained list would silently stop catching a new anchor added later exactly the way this
test exists to prevent stub/missing pages in the first place. ``import src.ui.actions.
builtin_actions`` (for its import-time registration side effect) mirrors the same pattern
``src.ui.main_window`` itself relies on -- see that module's own comment on the identical import.
"""

from __future__ import annotations

import pytest

import uadas_core.actions.builtin_actions  # noqa: F401 -- import-time registration side effect
from src.ui.workbench.stage_registry import get_stage_page_class, list_registered_stages
from uadas_core.actions.action_registry import list_actions
from uadas_core.help.manual_index import ManualIndex
from uadas_core.results.result_renderer_registry import list_renderers

# A stub page would be short; every hand-authored page in docs/manual/ as of this milestone is
# comfortably longer than this. Not tuned to any single page's exact length -- this only needs
# to catch "practically nothing here" (an empty or one-line placeholder), which is what "zero
# stub pages" actually means as a checkable assertion.
_MIN_STUB_DETECTION_LENGTH = 150

_STUB_MARKERS = ("todo", "tbd", "placeholder", "coming soon", "not yet written")


def _every_action_help_anchor() -> set[str]:
    return {
        spec.help_anchor
        for spec in list_actions().values()
        if spec.help_anchor is not None
    }


def _every_stage_page_help_anchor() -> set[str]:
    anchors = set()
    for stage in list_registered_stages():
        page_class = get_stage_page_class(stage)
        assert page_class is not None  # list_registered_stages guarantees this
        anchors.add(page_class.help_anchor)
    return anchors


def _every_result_renderer_help_anchor() -> set[str]:
    return {renderer.help_anchor() for renderer in list_renderers().values()}


def _every_real_help_anchor() -> set[str]:
    return (
        _every_action_help_anchor()
        | _every_stage_page_help_anchor()
        | _every_result_renderer_help_anchor()
    )


def test_at_least_one_anchor_exists_in_each_real_source() -> None:
    """Guards against every other test in this module passing vacuously if a registry import
    silently returns nothing (e.g. builtin_actions failed to populate)."""
    assert len(_every_action_help_anchor()) > 10
    assert len(_every_stage_page_help_anchor()) == 9  # every stage but UPLOAD
    assert len(_every_result_renderer_help_anchor()) > 5


@pytest.mark.parametrize(
    "anchor", sorted(_every_action_help_anchor()), ids=lambda a: f"action:{a}"
)
def test_every_action_help_anchor_resolves(anchor: str) -> None:
    assert ManualIndex.anchor_exists(anchor), (
        f"ActionSpec.help_anchor {anchor!r} does not resolve to a real manual page -- "
        f"F1 from this action would land nowhere."
    )


@pytest.mark.parametrize(
    "anchor", sorted(_every_stage_page_help_anchor()), ids=lambda a: f"stage_page:{a}"
)
def test_every_stage_page_help_anchor_resolves(anchor: str) -> None:
    assert ManualIndex.anchor_exists(anchor), (
        f"StagePage.help_anchor {anchor!r} does not resolve to a real manual page -- "
        f"F1 from this stage page would land nowhere."
    )


@pytest.mark.parametrize(
    "anchor",
    sorted(_every_result_renderer_help_anchor()),
    ids=lambda a: f"renderer:{a}",
)
def test_every_result_renderer_help_anchor_resolves(anchor: str) -> None:
    assert ManualIndex.anchor_exists(anchor), (
        f"BaseResultRenderer.help_anchor() {anchor!r} does not resolve to a real manual "
        f"page -- F1 from this result card would land nowhere."
    )


@pytest.mark.parametrize(
    "anchor", sorted(_every_real_help_anchor()), ids=lambda a: f"content:{a}"
)
def test_every_real_help_anchor_has_substantial_non_stub_content(anchor: str) -> None:
    page = ManualIndex.resolve(anchor)
    body = page.body_markdown.strip()
    assert len(body) >= _MIN_STUB_DETECTION_LENGTH, (
        f"Manual page for {anchor!r} ({page.path}) is only {len(body)} character(s) -- "
        f"looks like a stub, not real content."
    )
    lowered = body.lower()
    for marker in _STUB_MARKERS:
        assert marker not in lowered, (
            f"Manual page for {anchor!r} ({page.path}) contains the stub marker "
            f"{marker!r} -- this milestone's acceptance criterion is zero stub pages."
        )


def test_the_manual_has_at_least_ninety_anchors() -> None:
    """Guards the module-level test below against passing vacuously (e.g. docs/manual/ being
    pointed at an empty tree) -- 90 is the real count as of this milestone (16 readers + 12
    charts + 12 statistical methods + 5 forecasters + 5 cleaning ops + 10 pipeline stages + AI
    overview + plugins overview + glossary + every application-wide-action/settings page, with
    several anchors sharing a handful of dual-purpose pages -- see ManualIndex's own docstring).
    """
    assert len(ManualIndex.all_anchors()) >= 90


@pytest.mark.parametrize(
    "anchor", sorted(ManualIndex.all_anchors()), ids=lambda a: f"all-content:{a}"
)
def test_every_page_in_the_whole_manual_has_substantial_non_stub_content(
    anchor: str,
) -> None:
    """The stronger, whole-manual version of the check above: covers every page reachable by
    *any* anchor, not only the 35 currently wired to a real ``help_anchor`` in the codebase --
    the manual's own "16 readers, 12 charts, 12 statistical methods, 5 forecasters, 5 cleaning
    ops" content requirement includes pages nothing in ``src/ui`` links to by ``help_anchor``
    yet (e.g. each individual reader's own reference page), which the narrower check above
    would never touch."""
    page = ManualIndex.resolve(anchor)
    body = page.body_markdown.strip()
    assert len(body) >= _MIN_STUB_DETECTION_LENGTH, (
        f"Manual page for {anchor!r} ({page.path}) is only {len(body)} character(s) -- "
        f"looks like a stub, not real content."
    )
    lowered = body.lower()
    for marker in _STUB_MARKERS:
        assert marker not in lowered, (
            f"Manual page for {anchor!r} ({page.path}) contains the stub marker "
            f"{marker!r} -- this milestone's acceptance criterion is zero stub pages."
        )
