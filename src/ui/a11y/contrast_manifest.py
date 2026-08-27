# File: src/ui/a11y/contrast_manifest.py
"""Every foreground/background pairing the UI renders, with its WCAG floor.

This is the list that makes :mod:`src.ui.theme.tokens` trustworthy. Each
entry names two token fields and the ratio they must reach;
``tests/ui/theme/test_contrast.py`` asserts all of them against every theme,
so editing a colour cannot quietly break legibility.

Two deliberate exclusions, both grounded in what WCAG actually requires
rather than in what was convenient:

- **``text_disabled`` is absent.** WCAG 1.4.3 exempts text that is part of an
  inactive user interface component. Requiring 4.5:1 from disabled text would
  force it to look enabled, destroying the only visual signal that a control
  is unavailable.
- **``border`` is absent, while ``focus_ring`` is present.** 1.4.11 covers
  visual information required to *identify* a component or its state. A
  divider between two panels identifies nothing -- the panels are already
  distinguished by their surface fills -- whereas a focus ring is the sole
  indicator of where the keyboard is, so it is held to the full 3:1 against
  every surface it can appear on.
"""

from __future__ import annotations

from src.ui.theme.contrast import (
    AA_BODY_TEXT,
    AA_NON_TEXT,
    ContrastRequirement,
)

_SURFACES = ("surface_0", "surface_1", "surface_2")

CONTRAST_REQUIREMENTS: tuple[ContrastRequirement, ...] = (
    # -- Body text on every surface it can land on --------------------------
    *(
        ContrastRequirement(
            "text_primary", surface, AA_BODY_TEXT, f"Body text on {surface}"
        )
        for surface in _SURFACES
    ),
    *(
        ContrastRequirement(
            "text_secondary",
            surface,
            AA_BODY_TEXT,
            f"Secondary text (hints, status bar, tick labels) on {surface}",
        )
        for surface in _SURFACES[:2]
    ),
    # -- Text on accent fills ------------------------------------------------
    ContrastRequirement(
        "text_on_accent", "accent", AA_BODY_TEXT, "Primary button label"
    ),
    ContrastRequirement(
        "text_on_accent", "accent_hover", AA_BODY_TEXT, "Primary button, hovered"
    ),
    ContrastRequirement(
        "text_on_accent", "accent_pressed", AA_BODY_TEXT, "Primary button, pressed"
    ),
    ContrastRequirement(
        "text_on_accent", "accent", AA_BODY_TEXT, "Selected menu and list item"
    ),
    # -- Focus indicator: 2.4.11, on every surface it can appear over --------
    *(
        ContrastRequirement(
            "focus_ring",
            surface,
            AA_NON_TEXT,
            f"Keyboard focus ring over {surface}",
        )
        for surface in _SURFACES
    ),
    # -- Semantic state text -------------------------------------------------
    *(
        ContrastRequirement(
            role, surface, AA_BODY_TEXT, f"{role.capitalize()} message on {surface}"
        )
        for role in ("success", "warning", "danger", "info")
        for surface in _SURFACES[:2]
    ),
)


def chart_color_requirements(surface: str = "surface_1") -> str:
    """Return the surface chart series are drawn on.

    Series colours are checked separately from
    :data:`CONTRAST_REQUIREMENTS` because their count varies per theme, so
    they cannot be a fixed tuple of field-name pairs. See
    ``test_chart_colors_are_distinguishable`` for the assertion itself.
    """
    return surface
