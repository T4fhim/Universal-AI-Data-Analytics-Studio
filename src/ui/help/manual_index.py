# File: src/ui/help/manual_index.py
"""Builds and resolves the anchor -> manual-page index from ``docs/manual/*.md`` frontmatter.

``ManualIndex`` mirrors this project's ``Base*``/registry extension-point shape (see CLAUDE.md's
"``Base*`` extension-point pattern" and, more directly, :mod:`~uadas_core.visualization.chart_registry`'s
module-level registry) even though there is exactly one implementation of "a manual page" today
-- a plugin-provided manual page is out of scope for this milestone (see
:mod:`~uadas_core.plugins.plugin_manifest`'s own ``SUPPORTED_CATEGORIES`` for the project's existing,
deliberate line on what is and isn't plugin-extensible yet). Keeping the same "stateless,
classmethod-only, look things up through the class" shape means a future plugin-provided page
would not need this module's call sites to change shape, only to feed a second source directory
into :meth:`ManualIndex._build`.

Each manual page under ``docs/manual/`` is plain Markdown with a small YAML frontmatter block::

    ---
    title: "New Project"
    anchors:
      - project/new
    ---

    # New Project
    ...

``anchors`` is a list, not a single value, because one page legitimately answers more than one
F1 anchor -- for example ``docs/manual/results/t_test.md`` answers both ``results.t_test`` (the
t-test result card's own F1 anchor) and ``statistics.t_test`` (the general statistics-reference
anchor), so the manual's "12 statistical methods" content requirement and its "every
``ActionSpec``/``StagePage``/result-renderer ``help_anchor`` resolves" contract test are both
satisfied by one real page, not two copies of the same content that could drift apart.

A page with no ``anchors`` at all (there are none as of this milestone, but the format allows
it) is a pure cross-referenced page nothing links to by anchor directly -- skipped when building
the index, not an error, since "not F1-reachable" is a valid thing for a reference page to be.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from uadas_core.core.constants import PROJECT_ROOT
from uadas_core.core.exceptions import ServiceError
from uadas_core.core.logger import get_logger

_logger = get_logger(__name__)

#: Root of the authored manual content -- anchored to the project root (see CLAUDE.md's "Path
#: resolution" rule), not ``Path.cwd()``, so the manual resolves correctly regardless of the
#: working directory the application happens to be launched from.
MANUAL_ROOT: Path = PROJECT_ROOT / "docs" / "manual"

# Matches a leading YAML frontmatter block delimited by "---" lines. DOTALL so "." spans
# newlines inside the frontmatter and body; re.match anchors the whole pattern at position 0,
# so a page missing frontmatter entirely (no leading "---") simply fails to match rather than
# matching some later, unrelated "---" further down in the body (a Markdown horizontal rule).
_FRONTMATTER_PATTERN = re.compile(
    r"\A---\n(?P<frontmatter>.*?)\n---\n?(?P<body>.*)", re.DOTALL
)


@dataclass(frozen=True)
class ManualPage:
    """One manual page, as read from disk and resolved for a specific anchor.

    Attributes:
        anchor: The specific anchor this lookup resolved -- one of possibly several a page
            answers (see this module's own docstring).
        title: Page heading, from the frontmatter's ``title`` field.
        path: Source file -- surfaced for error messages and for
            ``scripts/preview_manual.py``, which prints it so an author knows exactly which file
            to edit.
        body_markdown: The raw Markdown body, frontmatter stripped. Kept separate from any
            compiled HTML so a test can assert on real prose content directly (e.g. "this page
            is not a stub") without needing a Qt/``markdown_it`` round trip -- see
            :class:`~src.ui.help.manual_renderer.ManualRenderer` for the HTML compilation step.
    """

    anchor: str
    title: str
    path: Path
    body_markdown: str


def _split_frontmatter(path: Path) -> tuple[dict, str]:
    """Return ``(frontmatter_dict, body_markdown)`` for one manual page file.

    Raises:
        ServiceError: If ``path`` has no leading YAML frontmatter block, or the block is not a
            YAML mapping -- both indicate an authoring mistake in the manual itself (every page
            is hand-authored, checked into version control, and expected to follow this format
            exactly), not a condition a reader of the manual should ever be able to trigger.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_PATTERN.match(text)
    if not match:
        raise ServiceError(
            f"Manual page {path} is missing its required leading YAML frontmatter "
            f"block (a '---'-delimited section with at least a 'title' key)."
        )
    frontmatter = yaml.safe_load(match.group("frontmatter")) or {}
    if not isinstance(frontmatter, dict):
        raise ServiceError(
            f"Manual page {path}'s frontmatter block must be a YAML mapping, got "
            f"{type(frontmatter).__name__}."
        )
    return frontmatter, match.group("body")


class ManualIndex:
    """Stateless, classmethod-only anchor resolver over ``docs/manual/*.md``.

    The scanned index is cached at the class level after the first call (see
    :meth:`_build`/:meth:`clear_cache`) -- scanning and YAML-parsing ~80 small files on every
    single F1 press would be wasteful for a tree that essentially never changes at runtime
    (the manual ships with the application; nothing in the running UI writes to
    ``docs/manual/``). :meth:`clear_cache` exists for the one case that *does* need a fresh
    scan: ``scripts/preview_manual.py``, an authoring tool that edits a page and re-renders it
    without restarting a process, and tests that point :data:`MANUAL_ROOT`-shaped fixtures at a
    temporary tree.
    """

    _cache: dict[str, ManualPage] | None = None

    @classmethod
    def _build(cls) -> dict[str, ManualPage]:
        index: dict[str, ManualPage] = {}
        for md_path in sorted(MANUAL_ROOT.rglob("*.md")):
            frontmatter, body = _split_frontmatter(md_path)
            anchors = frontmatter.get("anchors") or []
            title = frontmatter.get("title") or md_path.stem
            for anchor in anchors:
                if anchor in index:
                    raise ServiceError(
                        f"Manual anchor {anchor!r} is claimed by both "
                        f"{index[anchor].path} and {md_path} -- each anchor must "
                        f"resolve to exactly one page."
                    )
                index[str(anchor)] = ManualPage(
                    anchor=str(anchor),
                    title=str(title),
                    path=md_path,
                    body_markdown=body,
                )
        _logger.debug(
            "ManualIndex built: %d anchor(s) across docs/manual/.", len(index)
        )
        return index

    @classmethod
    def _index(cls) -> dict[str, ManualPage]:
        if cls._cache is None:
            cls._cache = cls._build()
        return cls._cache

    @classmethod
    def resolve(cls, anchor: str) -> ManualPage:
        """Return the :class:`ManualPage` for ``anchor``.

        Raises:
            ServiceError: If ``anchor`` is not claimed by any page under
                :data:`MANUAL_ROOT` -- this is the exact failure
                ``tests/ui/help/test_manual_anti_rot.py``'s contract test asserts never happens
                for any real ``help_anchor`` value in the codebase.
        """
        index = cls._index()
        if anchor not in index:
            raise ServiceError(
                f"No manual page found for anchor {anchor!r}. Known anchors: "
                f"{', '.join(sorted(index)) or '(none)'}."
            )
        return index[anchor]

    @classmethod
    def anchor_exists(cls, anchor: str) -> bool:
        """Return whether ``anchor`` resolves to a real page, without raising."""
        return anchor in cls._index()

    @classmethod
    def all_anchors(cls) -> frozenset[str]:
        """Return every anchor currently resolvable -- used by ``scripts/preview_manual.py``
        to list valid ``--anchor`` choices."""
        return frozenset(cls._index())

    @classmethod
    def resolve_path(cls, path: Path) -> str | None:
        """Return an anchor that resolves to the page at ``path``, or ``None``.

        Used by :class:`~src.ui.dialogs.manual_dialog.ManualDialog` to follow a clicked
        cross-reference link (manual pages link to each other by relative file path, e.g.
        ``[Clean](../pipeline/clean.md)`` -- see this module's own docstring for why pages are
        authored against real, browsable file paths rather than a second, parallel anchor-only
        link syntax). If ``path`` answers more than one anchor (see this module's own docstring
        on why one page may), any one of them is returned -- they all resolve to the identical
        page, so which specific anchor string is used to get there does not change what is shown.
        """
        for anchor, page in cls._index().items():
            if page.path == path:
                return anchor
        return None

    @classmethod
    def clear_cache(cls) -> None:
        """Force the next :meth:`resolve`/:meth:`anchor_exists` call to re-scan disk.

        See this class's own docstring for the two real callers: ``scripts/preview_manual.py``
        (re-render after an edit, in the same process) and tests that need a fresh scan against
        a temporary manual tree.
        """
        cls._cache = None
