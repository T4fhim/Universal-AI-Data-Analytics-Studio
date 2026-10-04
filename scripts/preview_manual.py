# File: scripts/preview_manual.py
"""Renders one manual page through the real ManualRenderer, for authoring without an app rebuild.

Non-shipping infrastructure -- a tool a human or an agent runs after editing a page under
``docs/manual/``. It goes through the *real* rendering path (:class:`~uadas_core.help.
manual_index.ManualIndex` for frontmatter/anchor resolution, :class:`~uadas_core.help.
manual_renderer.ManualRenderer` for the Markdown-to-HTML compile) rather than a hand-rolled
stand-in, and prints the resolved title and compiled HTML to stdout. That is enough to confirm
a frontmatter block parses and a page's Markdown compiles after every edit.

There used to be a second mode that saved a PNG of the Qt manual dialog. The dialog was part of
the desktop shell removed in Phase 2.5, so only the text mode remains; a visual preview belongs
to whatever renders the manual in the web UI.

Usage::

    python scripts/preview_manual.py --list
    python scripts/preview_manual.py --anchor pipeline.understand
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uadas_core.help.manual_index import ManualIndex
from uadas_core.help.manual_renderer import ManualRenderer


def _print_text_preview(anchor: str) -> None:
    page = ManualRenderer.render(anchor)
    print(f"Anchor:  {page.anchor}")
    print(f"Title:   {page.title}")
    print("-" * 60)
    print(page.html)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--anchor", default="index", help="Manual anchor to render (default: index)."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List every currently resolvable anchor and exit.",
    )
    args = parser.parse_args(argv)

    if args.list:
        for anchor in sorted(ManualIndex.all_anchors()):
            print(anchor)
        return 0

    _print_text_preview(args.anchor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
