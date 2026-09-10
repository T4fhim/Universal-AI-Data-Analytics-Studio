# File: tests/ui/help/test_manual_index.py
"""Unit coverage for ManualIndex's frontmatter parsing and anchor resolution.

Points :data:`~uadas_core.help.manual_index.MANUAL_ROOT` at a small, hand-built temporary tree via
monkeypatch rather than exercising the real docs/manual/ content here -- the real tree's own
correctness (every real anchor resolves, zero stub pages) is
tests/ui/help/test_manual_anti_rot.py's job; this module is about ManualIndex's own parsing and
lookup logic in isolation, with cases (a duplicate anchor, a missing frontmatter block) the real
manual is never expected to actually have.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.help import manual_index as manual_index_module
from uadas_core.help.manual_index import ManualIndex


@pytest.fixture()
def temp_manual(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(manual_index_module, "MANUAL_ROOT", tmp_path)
    ManualIndex.clear_cache()
    yield tmp_path
    ManualIndex.clear_cache()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_resolves_a_well_formed_page(temp_manual: Path) -> None:
    _write(
        temp_manual / "a.md",
        '---\ntitle: "A Page"\nanchors:\n  - a/page\n---\n\nSome real body text here.\n',
    )
    page = ManualIndex.resolve("a/page")
    assert page.title == "A Page"
    assert "Some real body text" in page.body_markdown


def test_a_page_can_answer_more_than_one_anchor(temp_manual: Path) -> None:
    _write(
        temp_manual / "dual.md",
        '---\ntitle: "Dual"\nanchors:\n  - results.x\n  - statistics.x\n---\n\nBody.\n',
    )
    assert (
        ManualIndex.resolve("results.x").path
        == ManualIndex.resolve("statistics.x").path
    )


def test_a_page_with_no_anchors_is_simply_unreachable_by_anchor(
    temp_manual: Path,
) -> None:
    _write(temp_manual / "orphan.md", '---\ntitle: "Orphan"\n---\n\nBody.\n')
    assert ManualIndex.all_anchors() == frozenset()


def test_unknown_anchor_raises_service_error(temp_manual: Path) -> None:
    _write(temp_manual / "a.md", '---\ntitle: "A"\nanchors: [a]\n---\n\nBody.\n')
    with pytest.raises(ServiceError):
        ManualIndex.resolve("does-not-exist")


def test_anchor_exists_does_not_raise(temp_manual: Path) -> None:
    _write(temp_manual / "a.md", '---\ntitle: "A"\nanchors: [a]\n---\n\nBody.\n')
    assert ManualIndex.anchor_exists("a") is True
    assert ManualIndex.anchor_exists("nope") is False


def test_duplicate_anchor_across_two_files_raises(temp_manual: Path) -> None:
    _write(
        temp_manual / "one.md", '---\ntitle: "One"\nanchors: [shared]\n---\n\nBody.\n'
    )
    _write(
        temp_manual / "two.md", '---\ntitle: "Two"\nanchors: [shared]\n---\n\nBody.\n'
    )
    with pytest.raises(ServiceError):
        ManualIndex.resolve("shared")


def test_missing_frontmatter_raises_service_error(temp_manual: Path) -> None:
    _write(temp_manual / "bad.md", "# Just a heading, no frontmatter\n")
    with pytest.raises(ServiceError):
        ManualIndex.resolve("anything")


def test_resolve_path_finds_an_anchor_for_a_known_file(temp_manual: Path) -> None:
    path = temp_manual / "a.md"
    _write(path, '---\ntitle: "A"\nanchors: [a]\n---\n\nBody.\n')
    assert ManualIndex.resolve_path(path) == "a"


def test_resolve_path_returns_none_for_an_unknown_file(temp_manual: Path) -> None:
    assert ManualIndex.resolve_path(temp_manual / "nope.md") is None


def test_clear_cache_forces_a_rescan(temp_manual: Path) -> None:
    _write(temp_manual / "a.md", '---\ntitle: "A"\nanchors: [a]\n---\n\nBody.\n')
    assert ManualIndex.anchor_exists("a") is True
    assert ManualIndex.anchor_exists("b") is False

    _write(temp_manual / "b.md", '---\ntitle: "B"\nanchors: [b]\n---\n\nBody.\n')
    assert ManualIndex.anchor_exists("b") is False  # still cached from before

    ManualIndex.clear_cache()
    assert ManualIndex.anchor_exists("b") is True
