# File: scripts/preview_manual.py
"""Renders one manual page through the real ManualRenderer, for authoring without a full
app rebuild.

Non-shipping infrastructure, alongside ``scripts/screenshot_app_state.py`` -- a verification/
authoring tool a human or an agent runs after editing a page under ``docs/manual/``, never
imported by ``src/``.

Two modes, both going through the *real* rendering path (:class:`~src.ui.help.manual_index.
ManualIndex` for frontmatter/anchor resolution, :class:`~src.ui.help.manual_renderer.
ManualRenderer` for the Markdown-to-HTML compile) rather than a hand-rolled Markdown-to-text
stand-in:

* **Text mode (default, no Qt at all)** -- prints the resolved title and compiled HTML straight
  to stdout. Fast, and enough to confirm a frontmatter block parses and a page's Markdown
  compiles without errors after every edit.
* **Screenshot mode (``--output``)** -- constructs the real :class:`~src.ui.dialogs.
  manual_dialog.ManualDialog` (the exact widget F1 opens in the running application, not a
  simplified stand-in) inside an offscreen ``QApplication`` and saves a PNG of it, the same
  "boot the real path, grab a frame" approach ``screenshot_app_state.py`` uses for the whole
  window -- see that script's own docstring for why offscreen rendering is required in a
  headless CI or agent sandbox.

Usage::

    python scripts/preview_manual.py --list
    python scripts/preview_manual.py --anchor pipeline.understand
    python scripts/preview_manual.py --anchor results.t_test --output out.png
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Must precede any PySide6 import -- see screenshot_app_state.py's own docstring for why
# setdefault() (not assignment) and why this must happen this early.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ui.help.manual_index import ManualIndex
from src.ui.help.manual_renderer import ManualRenderer


class PreviewManualError(Exception):
    """Raised for a failure specific to this script, distinct from a real ``ServiceError``
    an anchor lookup or render might legitimately raise (which is allowed to propagate as-is
    -- this script's own job is orchestration, not re-wrapping every possible failure)."""


def _print_text_preview(anchor: str) -> None:
    page = ManualRenderer.render(anchor)
    print(f"Anchor:  {page.anchor}")
    print(f"Title:   {page.title}")
    print("-" * 60)
    print(page.html)


def _save_screenshot(anchor: str, output_path: Path) -> None:
    from PySide6.QtWidgets import QApplication

    from src.ui.dialogs.manual_dialog import ManualDialog

    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        raise PreviewManualError(
            "QT_QPA_PLATFORM must be 'offscreen' to run this script headlessly "
            f"(currently {os.environ.get('QT_QPA_PLATFORM')!r})."
        )

    app = QApplication.instance() or QApplication(sys.argv[:1])
    dialog = ManualDialog()
    dialog.show_anchor(anchor)
    dialog.resize(700, 600)
    dialog.show()
    app.processEvents()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = dialog.grab()
    if not pixmap.save(str(output_path), "PNG"):
        raise PreviewManualError(f"QPixmap.save() reported failure for {output_path}")
    print(f"Saved manual preview screenshot to {output_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--anchor", default="index", help="Manual anchor to render (default: index)."
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Save a screenshot PNG to this path."
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

    if args.output is not None:
        _save_screenshot(args.anchor, args.output)
    else:
        _print_text_preview(args.anchor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
