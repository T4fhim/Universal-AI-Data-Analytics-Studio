# File: src/ui/theme/tokens.py
"""The single source of truth for every color, space, and radius the UI uses.

Qt Style Sheets have no variable mechanism — there is no QSS equivalent of a
CSS custom property — so a "design token" layer cannot live in the stylesheet
itself. It lives here instead, in Python, and
:func:`~src.ui.theme.qss_compiler.compile_qss` substitutes these values into
``resources/styles/base.qss.template`` at theme-apply time.

Before this module, ``resources/styles/dark.qss`` and ``light.qss`` each held
twelve hand-maintained literal hex values with no shared naming, and
``dark.qss``'s own header comment flagged that as future work. Both files are
now deleted: one template plus the token sets below is the only definition,
so the two themes cannot drift out of step.

Fields are named for **what a color means**, not what it looks like
(``surface_1``, ``danger``), because the light and dark values for the same
role are frequently inverted — a literal name like ``dark_grey`` would be a
lie in one theme.

Every pairing these tokens produce on screen is asserted against WCAG 2.2
Level AA by :mod:`tests.ui.theme.test_contrast`, and the values below were
chosen by running that check rather than by eye. Two findings from that pass
are baked into the shape of this dataclass:

- ``accent`` and ``focus_ring`` are **separate tokens**. The original single
  ``#3a5fc4`` accent could not be both a fill that white text reads against
  (needs 4.5:1) and a focus indicator visible on a dark ground (needs 3:1) —
  it scored 5.81 and 2.83 respectively, so the dark theme's focus ring was
  failing 1.4.11. Splitting the role is the fix.
- ``chart_categorical`` is **per-theme**, not a module constant. The standard
  Okabe–Ito colourblind-safe palette is designed for white grounds; on the
  dark surface its blue scores 2.87. Each theme carries a ramp that keeps
  Okabe–Ito's hue *separation* (the property that makes it colourblind-safe)
  while meeting 3:1 against its own background.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class Density(str, Enum):
    """How tightly the UI packs content.

    Subclasses ``str`` for the same reason
    :class:`~src.core.expertise_level.ExpertiseLevel` does — it round-trips
    through ``config.yaml`` as a plain string with no conversion at the
    config boundary.

    Milestone 25 maps :class:`~src.core.expertise_level.ExpertiseLevel` onto
    these so a beginner gets large targets and generous spacing while an
    engineer gets compact rows. The enum ships now, in milestone 15, because
    the spacing scale has to be derived from *something* and hard-coding one
    density would mean re-deriving every spacing value later.
    """

    COMFORTABLE = "comfortable"
    COZY = "cozy"
    COMPACT = "compact"

    @property
    def scale(self) -> float:
        """Multiplier applied to the base spacing scale."""
        return {"comfortable": 1.25, "cozy": 1.0, "compact": 0.75}[self.value]


@dataclass(frozen=True)
class ThemeTokens:
    """One complete theme.

    Attributes are grouped below by role. See this module's own docstring for
    why ``accent``/``focus_ring`` and the per-theme ``chart_categorical``
    exist as separate concepts rather than single shared values.
    """

    name: str

    # -- Surfaces, back to front ------------------------------------------
    surface_0: str  # window / canvas ground
    surface_1: str  # panels, inputs, menus, list backgrounds
    surface_2: str  # raised or hovered elements

    # -- Text --------------------------------------------------------------
    text_primary: str
    text_secondary: str
    text_disabled: str  # exempt from 1.4.3 (inactive components), see manifest
    text_on_accent: str

    # -- Accent (fills that carry text_on_accent) --------------------------
    accent: str
    accent_hover: str
    accent_pressed: str

    # -- Lines -------------------------------------------------------------
    border: str  # decorative separation between surfaces
    border_strong: str  # scrollbar handles, emphasised dividers
    focus_ring: str  # keyboard focus indicator — must clear 3:1 everywhere

    # -- Semantic state ----------------------------------------------------
    success: str
    warning: str
    danger: str
    info: str

    # -- Data visualisation -------------------------------------------------
    stage_hues: tuple[str, ...]
    chart_categorical: tuple[str, ...]

    # -- Geometry and type ---------------------------------------------------
    density: Density = Density.COZY
    focus_ring_width: int = 2  # 2.4.11 wants a 2px-equivalent perimeter
    radius_sm: int = 4
    radius_md: int = 6
    font_family: str = '"Segoe UI", "Inter", "Helvetica Neue", sans-serif'
    font_size_sm: int = 12
    font_size_md: int = 13
    font_size_lg: int = 16

    def with_density(self, density: Density) -> ThemeTokens:
        """Return a copy at a different :class:`Density`.

        A new instance rather than a mutation, because ``ThemeTokens`` is
        frozen and shared — the same dark token set is handed to the QSS
        compiler, the icon provider, and the Plotly theme, and any one of
        them mutating it would silently change the others.
        """
        return replace(self, density=density)

    def space(self, step: int) -> int:
        """Return spacing step ``step`` (1-5) in pixels, scaled by density.

        A 4px base grid. Exposed as a method rather than five separate
        ``space_1``..``space_5`` fields so that density scaling happens in
        exactly one place instead of being reapplied at every use site.
        """
        if not 1 <= step <= 5:
            raise ValueError(f"Spacing step must be 1-5, got {step}.")
        return max(1, round(4 * step * self.density.scale))

    def as_qss_mapping(self) -> dict[str, str]:
        """Return the flat ``name -> value`` mapping the QSS template substitutes.

        Tuples are flattened into indexed keys (``stage_hue_0``,
        ``chart_color_0``, ...) because ``string.Template`` substitutes flat
        scalars only. Numeric values become ``"12px"`` strings here rather
        than in the template, so the template never has to concatenate a unit
        onto a placeholder — ``${space_2}px`` would silently produce
        ``8pxpx`` if a value ever already carried its unit.
        """
        mapping: dict[str, str] = {
            "font_family": self.font_family,
            "font_size_sm": f"{self.font_size_sm}px",
            "font_size_md": f"{self.font_size_md}px",
            "font_size_lg": f"{self.font_size_lg}px",
            "focus_ring_width": f"{self.focus_ring_width}px",
            "radius_sm": f"{self.radius_sm}px",
            "radius_md": f"{self.radius_md}px",
        }
        for field_name in (
            "surface_0", "surface_1", "surface_2",
            "text_primary", "text_secondary", "text_disabled", "text_on_accent",
            "accent", "accent_hover", "accent_pressed",
            "border", "border_strong", "focus_ring",
            "success", "warning", "danger", "info",
        ):
            mapping[field_name] = getattr(self, field_name)
        for step in range(1, 6):
            mapping[f"space_{step}"] = f"{self.space(step)}px"
        for index, hue in enumerate(self.stage_hues):
            mapping[f"stage_hue_{index}"] = hue
        for index, color in enumerate(self.chart_categorical):
            mapping[f"chart_color_{index}"] = color
        return mapping


# Hue per :class:`~src.services.analysis_orchestrator_service.PipelineStage`,
# in that enum's declaration order (UPLOAD, UNDERSTAND, CLEAN, EXPLORE,
# ANALYZE, VISUALIZE, PREDICT, EXPLAIN, REPORT, REPRODUCE). Indexed by
# position rather than keyed by the enum so this module stays free of any
# import from src.services — tokens are consumed by the QSS compiler, which
# must remain loadable with nothing else in the application constructed.
_DARK_STAGE_HUES = (
    "#7AA2F7", "#56B4E9", "#00BE8C", "#A6D75B", "#E69F00",
    "#F07030", "#E86A9A", "#CC79A7", "#9B8CF0", "#B0B0B0",
)
_LIGHT_STAGE_HUES = (
    "#2B5FCC", "#1B7FB5", "#00795C", "#4A7A00", "#B07500",
    "#C0450A", "#C0326B", "#A6417F", "#6A4FC0", "#5F5F5F",
)

# Okabe-Ito hue order, retinted per theme so each entry clears 3:1 against
# that theme's chart background. Hue *separation* is what makes Okabe-Ito
# safe for colour-vision deficiency, and lightening or darkening preserves
# hue, so both ramps keep that property.
_DARK_CHART_COLORS = (
    "#E69F00", "#56B4E9", "#00BE8C", "#F0E442",
    "#4DA3E0", "#F07030", "#CC79A7", "#B0B0B0",
)
_LIGHT_CHART_COLORS = (
    "#B07500", "#1B7FB5", "#00795C", "#7A6E00",
    "#0059A8", "#C0450A", "#A6417F", "#5F5F5F",
)

DARK_TOKENS = ThemeTokens(
    name="dark",
    surface_0="#1e1f24",
    surface_1="#26272e",
    surface_2="#3a3b44",
    text_primary="#e6e6e8",
    text_secondary="#a0a1a8",
    text_disabled="#6a6b72",
    text_on_accent="#ffffff",
    accent="#3a5fc4",
    accent_hover="#4a6fd4",
    accent_pressed="#2a4fb4",
    border="#35363e",
    border_strong="#4a4b54",
    focus_ring="#6b8ce8",
    success="#4ec9a0",
    warning="#e0a458",
    danger="#f27b7b",
    info="#6b8ce8",
    stage_hues=_DARK_STAGE_HUES,
    chart_categorical=_DARK_CHART_COLORS,
)

LIGHT_TOKENS = ThemeTokens(
    name="light",
    surface_0="#f5f5f7",
    surface_1="#ffffff",
    surface_2="#e4e4e8",
    text_primary="#1e1f24",
    text_secondary="#5a5b62",
    text_disabled="#a0a1a8",
    text_on_accent="#ffffff",
    accent="#3a5fc4",
    accent_hover="#2a4fb4",
    accent_pressed="#1a3fa4",
    border="#d8d8dc",
    border_strong="#c0c0c6",
    focus_ring="#2a4fb4",
    success="#0f7a5a",
    warning="#8a5a00",
    danger="#c0392b",
    info="#2a4fb4",
    stage_hues=_LIGHT_STAGE_HUES,
    chart_categorical=_LIGHT_CHART_COLORS,
)

# A genuine third theme, not a tinted dark: pure-black ground, pure-white
# text, and a thicker focus ring. Offered because WCAG 2.2 AA is a floor, not
# a target — users who need more than 4.5:1 (low vision, glare, failing
# displays) are not served by nudging the dark theme's greys.
HIGH_CONTRAST_TOKENS = ThemeTokens(
    name="high_contrast",
    surface_0="#000000",
    surface_1="#000000",
    surface_2="#1a1a1a",
    text_primary="#ffffff",
    text_secondary="#ffffff",
    text_disabled="#8f8f8f",
    text_on_accent="#000000",
    accent="#ffd400",
    accent_hover="#ffe456",
    accent_pressed="#e0ba00",
    border="#ffffff",
    border_strong="#ffffff",
    focus_ring="#ffd400",
    success="#4dff9f",
    warning="#ffd400",
    danger="#ff6b6b",
    info="#7ac9ff",
    stage_hues=("#ffffff",) * 10,
    chart_categorical=(
        "#ffffff", "#ffd400", "#7ac9ff", "#4dff9f",
        "#ff6b6b", "#d7a3ff", "#ffb066", "#b0b0b0",
    ),
    focus_ring_width=3,
)

TOKENS_BY_NAME: dict[str, ThemeTokens] = {
    tokens.name: tokens
    for tokens in (DARK_TOKENS, LIGHT_TOKENS, HIGH_CONTRAST_TOKENS)
}
