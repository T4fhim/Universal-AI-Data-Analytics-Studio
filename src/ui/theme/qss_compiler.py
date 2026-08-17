# File: src/ui/theme/qss_compiler.py
"""Turns a :class:`~src.ui.theme.tokens.ThemeTokens` into a finished stylesheet.

Qt Style Sheets have no variable mechanism, so the token layer has to be
resolved before Qt ever sees the text. This module is that resolution step:
it reads ``resources/styles/base.qss.template`` once, substitutes a token
mapping into it, and hands the result to
:meth:`~src.ui.theme_manager.ThemeManager.apply_theme`.

``string.Template`` is used rather than ``str.format`` or f-strings because
QSS is full of braces — every rule body is ``{ ... }`` — and ``str.format``
would require doubling every one of them, turning the template into
something nobody can read or edit safely. ``$``-prefixed placeholders do not
collide with any QSS syntax.

:meth:`string.Template.substitute` is used rather than ``safe_substitute``
**deliberately**: a mistyped or removed token must raise ``KeyError`` at
compile time. ``safe_substitute`` would leave the literal text ``${accnt}``
in the stylesheet, where Qt silently discards the malformed declaration and
the only symptom is one widget quietly rendering with the wrong colour --
the exact class of bug this token layer exists to prevent.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from src.core.constants import PROJECT_ROOT
from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.ui.theme.tokens import ThemeTokens

_logger = get_logger(__name__)

TEMPLATE_PATH: Path = PROJECT_ROOT / "resources" / "styles" / "base.qss.template"

# Compiled stylesheets, keyed by (theme name, density). Theme switching is a
# user-initiated action that happens at most a handful of times per session,
# so this cache is a convenience rather than a necessity -- the dominant cost
# of a theme change is Qt re-polishing every widget, not this substitution,
# which measures in the hundreds of microseconds.
_COMPILED_CACHE: dict[tuple[str, str], str] = {}

# The template text itself, read once per process. Kept separate from
# _COMPILED_CACHE so clear_cache() can drop compiled output without forcing a
# re-read of a file that cannot change while the application is running.
_TEMPLATE_TEXT: str | None = None


def _read_template(template_path: Path) -> str:
    """Return the template text, reading from disk at most once per process."""
    global _TEMPLATE_TEXT
    if _TEMPLATE_TEXT is not None:
        return _TEMPLATE_TEXT
    if not template_path.exists():
        raise ServiceError(f"QSS template not found: {template_path}")
    try:
        _TEMPLATE_TEXT = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ServiceError(
            f"Failed to read QSS template {template_path}: {exc}"
        ) from exc
    return _TEMPLATE_TEXT


def compile_qss(
    tokens: ThemeTokens, template_path: Path = TEMPLATE_PATH, use_cache: bool = True
) -> str:
    """Return the finished stylesheet for ``tokens``.

    Args:
        tokens: The theme to render.
        template_path: Overridable primarily so tests can compile a small
            fixture template instead of the real 500-line one.
        use_cache: Set ``False`` in tests that mutate token values between
            calls, where a cache hit would mask the change.

    Raises:
        ServiceError: If the template is missing, unreadable, or references a
            placeholder that ``tokens`` does not define. The last case is
            re-raised from ``KeyError`` with the offending name, because
            ``string.Template``'s own message is just the bare key with no
            indication of which file it came from.
    """
    cache_key = (tokens.name, tokens.density.value)
    if use_cache and cache_key in _COMPILED_CACHE:
        return _COMPILED_CACHE[cache_key]

    template_text = _read_template(template_path)
    try:
        stylesheet = Template(template_text).substitute(tokens.as_qss_mapping())
    except KeyError as exc:
        raise ServiceError(
            f"QSS template {template_path.name} references an unknown token "
            f"{exc.args[0]!r}. Add it to ThemeTokens.as_qss_mapping() or fix "
            f"the placeholder."
        ) from exc
    except ValueError as exc:  # a stray, unescaped '$' in the template
        raise ServiceError(
            f"QSS template {template_path.name} contains a malformed "
            f"placeholder: {exc}. A literal dollar sign must be written '$$'."
        ) from exc

    if use_cache:
        _COMPILED_CACHE[cache_key] = stylesheet
    _logger.debug(
        "Compiled QSS for theme '%s' (density %s): %d characters.",
        tokens.name,
        tokens.density.value,
        len(stylesheet),
    )
    return stylesheet


def clear_cache() -> None:
    """Drop cached stylesheets and the cached template text.

    Exists for tests, which edit token values between cases and would
    otherwise see a stale compile.
    """
    global _TEMPLATE_TEXT
    _COMPILED_CACHE.clear()
    _TEMPLATE_TEXT = None
