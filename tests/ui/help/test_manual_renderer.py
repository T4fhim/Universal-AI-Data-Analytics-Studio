# File: tests/ui/help/test_manual_renderer.py
"""ManualRenderer compiles Markdown to the HTML QTextBrowser is handed -- covered against a
small temporary manual tree, the same isolation tests/ui/help/test_manual_index.py uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ui.help import manual_index as manual_index_module
from src.ui.help.manual_index import ManualIndex
from src.ui.help.manual_renderer import ManualRenderer
from uadas_core.core.exceptions import ServiceError


@pytest.fixture()
def temp_manual(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(manual_index_module, "MANUAL_ROOT", tmp_path)
    ManualIndex.clear_cache()
    yield tmp_path
    ManualIndex.clear_cache()


def test_renders_heading_and_paragraph_to_html(temp_manual: Path) -> None:
    (temp_manual / "a.md").write_text(
        '---\ntitle: "A Page"\nanchors: [a]\n---\n\n# A Page\n\nSome **bold** text.\n',
        encoding="utf-8",
    )
    rendered = ManualRenderer.render("a")
    assert rendered.title == "A Page"
    assert rendered.anchor == "a"
    assert "<h1>A Page</h1>" in rendered.html
    assert "<strong>bold</strong>" in rendered.html


def test_renders_a_table(temp_manual: Path) -> None:
    (temp_manual / "a.md").write_text(
        '---\ntitle: "A"\nanchors: [a]\n---\n\n| x | y |\n|---|---|\n| 1 | 2 |\n',
        encoding="utf-8",
    )
    rendered = ManualRenderer.render("a")
    assert "<table>" in rendered.html
    assert "<td>1</td>" in rendered.html


def test_unknown_anchor_propagates_service_error(temp_manual: Path) -> None:
    with pytest.raises(ServiceError):
        ManualRenderer.render("nope")
