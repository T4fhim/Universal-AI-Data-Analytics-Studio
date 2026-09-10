# File: uadas_core/help/manual_renderer.py
"""Compiles a resolved :class:`~uadas_core.help.manual_index.ManualPage`'s Markdown into HTML.

Uses ``markdown_it`` (already a project dependency -- see ``requirements.txt``'s own comment
naming this exact milestone as the reason it is listed explicitly rather than relying on it
arriving transitively via ``rich``), compiled with the ``QTextBrowser``-safe subset in mind:
``QTextBrowser`` (this project's chosen display widget -- see :mod:`~src.ui.dialogs.manual_dialog`'s
own docstring for why it, not ``QWebEngineView``, was chosen) supports a real but bounded HTML
subset. ``markdown_it``'s ``"commonmark"`` preset -- headings, paragraphs, lists, links, code
spans/blocks, emphasis, tables (via the ``tables`` plugin) -- stays comfortably inside that
subset without needing any HTML sanitization step: every manual page is authored, checked-in
content, not user input, so there is no untrusted-HTML risk to guard against here the way there
would be for, say, rendering an AI-generated message.
"""

from __future__ import annotations

from dataclasses import dataclass

from markdown_it import MarkdownIt

from uadas_core.help.manual_index import ManualIndex

# "commonmark" plus the "table" plugin -- CommonMark alone has no table syntax, and several
# manual pages (see docs/manual/data/open-dataset.md, visualize/create-chart.md) use Markdown
# tables for the readers/charts reference lists.
_markdown = MarkdownIt("commonmark").enable("table")


@dataclass(frozen=True)
class RenderedManualPage:
    """A manual page, compiled to HTML and ready to display.

    Attributes:
        anchor: The anchor this page was resolved for.
        title: Page heading.
        html: Compiled HTML body -- what :class:`~src.ui.dialogs.manual_dialog.ManualDialog`
            hands to ``QTextBrowser.setHtml``.
    """

    anchor: str
    title: str
    html: str


class ManualRenderer:
    """Stateless, classmethod-only -- see :class:`~uadas_core.help.manual_index.ManualIndex`'s own
    docstring for why this project's ``Base*``-shaped convention is followed here even though
    there is exactly one rendering strategy today."""

    @classmethod
    def render(cls, anchor: str) -> RenderedManualPage:
        """Resolve ``anchor`` via :class:`~uadas_core.help.manual_index.ManualIndex` and compile it.

        Raises:
            ServiceError: Propagated from :meth:`~uadas_core.help.manual_index.ManualIndex.resolve`
                if ``anchor`` does not resolve to a real page.
        """
        page = ManualIndex.resolve(anchor)
        html = _markdown.render(page.body_markdown)
        return RenderedManualPage(anchor=page.anchor, title=page.title, html=html)
