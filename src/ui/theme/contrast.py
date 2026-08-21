# File: src/ui/theme/contrast.py
"""WCAG 2.2 contrast math, used to *prove* the design tokens are accessible.

This module exists so that :mod:`src.ui.theme.tokens` is not a set of colors
somebody eyeballed. Every foreground/background pairing the application
actually renders is listed in
:data:`~src.ui.a11y.contrast_manifest.CONTRAST_REQUIREMENTS` and asserted
against these functions by a test, for every theme, so a token edit that
quietly breaks legibility fails the suite instead of shipping.

Pure arithmetic with no Qt import on purpose: contrast is a property of two
colors, not of a widget, and keeping it Qt-free means the test tier that
covers it needs no ``QApplication`` (see :mod:`tests.ui.theme.test_contrast`).

Formulae are taken directly from the WCAG 2.x definitions of *relative
luminance* and *contrast ratio*; the sRGB linearization constants below are
normative, not tuning knobs, so they are not configurable.
"""

from __future__ import annotations

from dataclasses import dataclass

# WCAG 2.2 Level AA thresholds. Named rather than inlined at call sites so a
# reader of a failing test sees *which* rule was violated, not a bare float.
AA_BODY_TEXT: float = 4.5  # 1.4.3 Contrast (Minimum) — text below 18.66px/24px
AA_LARGE_TEXT: float = 3.0  # 1.4.3 — >=18.66px bold or >=24px regular
AA_NON_TEXT: float = 3.0  # 1.4.11 Non-text Contrast — borders, icons, focus rings


def parse_hex(color: str) -> tuple[int, int, int]:
    """Return ``(r, g, b)`` 0-255 components of a ``#rrggbb`` string.

    Raises:
        ValueError: If ``color`` is not a 6-digit ``#rrggbb`` string. Short
            form (``#abc``) and named colors are deliberately rejected rather
            than supported: every token in :mod:`src.ui.theme.tokens` is
            authored as full 6-digit hex, so accepting other spellings would
            only create a second way to write the same value.
    """
    text = color.strip()
    if not text.startswith("#") or len(text) != 7:
        raise ValueError(f"Expected a '#rrggbb' color string, got {color!r}.")
    try:
        return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
    except ValueError as exc:  # non-hex digits
        raise ValueError(f"Expected a '#rrggbb' color string, got {color!r}.") from exc


def relative_luminance(color: str) -> float:
    """Return the WCAG relative luminance of ``color``, in ``0.0``–``1.0``.

    Each sRGB channel is normalized to 0-1, linearized (undoing the sRGB
    transfer function), then combined with the standard luminance weights.
    """

    def _linearize(channel_0_255: int) -> float:
        channel = channel_0_255 / 255.0
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (_linearize(component) for component in parse_hex(color))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio between two colors, from ``1.0`` to ``21.0``.

    Symmetric in its arguments — the ratio does not depend on which color is
    the text and which is behind it — so callers may pass them in either
    order without changing the result.
    """
    first = relative_luminance(foreground)
    second = relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def meets(foreground: str, background: str, minimum: float) -> bool:
    """Return whether ``foreground`` on ``background`` reaches ``minimum``."""
    return contrast_ratio(foreground, background) >= minimum


@dataclass(frozen=True)
class ContrastRequirement:
    """One pairing that every theme must satisfy.

    Attributes:
        foreground: Field name on :class:`~src.ui.theme.tokens.ThemeTokens`.
        background: Field name on :class:`~src.ui.theme.tokens.ThemeTokens`.
        minimum: Required ratio — one of :data:`AA_BODY_TEXT`,
            :data:`AA_LARGE_TEXT`, or :data:`AA_NON_TEXT`.
        rationale: Where this pairing appears on screen, so a test failure
            names a real surface instead of two token names.
    """

    foreground: str
    background: str
    minimum: float
    rationale: str
