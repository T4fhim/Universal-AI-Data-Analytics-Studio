# File: tests/ui/theme/test_tokens.py
"""Tests for ThemeTokens: mapping shape, density scaling, and immutability.

The WCAG correctness of the actual colour values is covered by
:mod:`tests.ui.theme.test_contrast`; this file covers the dataclass's own
mechanics.
"""

from __future__ import annotations

import pytest

from src.core.constants import AVAILABLE_THEMES
from src.core.expertise_level import ExpertiseLevel
from src.ui.theme.tokens import (
    DARK_TOKENS,
    DENSITY_BY_EXPERTISE_LEVEL,
    LIGHT_TOKENS,
    TOKENS_BY_NAME,
    Density,
)


def test_available_themes_matches_tokens() -> None:
    """The two theme lists must never drift apart.

    ``AVAILABLE_THEMES`` lives in src/core/constants.py because config
    validation (in core/) needs it and core/ may not import from ui/ --
    see that constant's own comment. This test is the tripwire that catches
    the two lists disagreeing.
    """
    assert set(AVAILABLE_THEMES) == set(TOKENS_BY_NAME)


@pytest.mark.parametrize(
    "tokens", list(TOKENS_BY_NAME.values()), ids=list(TOKENS_BY_NAME)
)
def test_as_qss_mapping_has_no_empty_values(tokens) -> None:
    mapping = tokens.as_qss_mapping()
    for key, value in mapping.items():
        assert value, f"{tokens.name}.{key} resolved to an empty value"


def test_as_qss_mapping_flattens_stage_hues_by_index() -> None:
    mapping = DARK_TOKENS.as_qss_mapping()
    for index, hue in enumerate(DARK_TOKENS.stage_hues):
        assert mapping[f"stage_hue_{index}"] == hue


def test_as_qss_mapping_flattens_chart_colors_by_index() -> None:
    mapping = LIGHT_TOKENS.as_qss_mapping()
    for index, color in enumerate(LIGHT_TOKENS.chart_categorical):
        assert mapping[f"chart_color_{index}"] == color


def test_space_scales_with_density() -> None:
    comfortable = DARK_TOKENS.with_density(Density.COMFORTABLE)
    compact = DARK_TOKENS.with_density(Density.COMPACT)
    assert comfortable.space(2) > DARK_TOKENS.with_density(Density.COZY).space(2)
    assert compact.space(2) < DARK_TOKENS.with_density(Density.COZY).space(2)


def test_space_is_monotonic_in_step() -> None:
    values = [DARK_TOKENS.space(step) for step in range(1, 6)]
    assert values == sorted(values)
    assert len(set(values)) == 5


@pytest.mark.parametrize("step", [0, 6, -1])
def test_space_rejects_out_of_range_step(step: int) -> None:
    with pytest.raises(ValueError):
        DARK_TOKENS.space(step)


def test_with_density_returns_a_new_instance_and_does_not_mutate() -> None:
    """ThemeTokens is frozen and shared -- with_density must copy, not mutate.

    The same DARK_TOKENS instance is handed to the QSS compiler, the icon
    provider, and the Plotly theme; a mutation here would silently affect all
    three.
    """
    original_density = DARK_TOKENS.density
    scaled = DARK_TOKENS.with_density(Density.COMPACT)
    assert scaled is not DARK_TOKENS
    assert DARK_TOKENS.density is original_density
    assert scaled.density is Density.COMPACT


def test_tokens_are_frozen() -> None:
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError is a TypeError
        DARK_TOKENS.accent = "#000000"  # type: ignore[misc]


def test_density_by_expertise_level_covers_every_expertise_level() -> None:
    """Milestone 26: every ExpertiseLevel maps to a real Density -- no gap that would fall
    through to a caller's own default and silently never change density for that level.
    """
    assert set(DENSITY_BY_EXPERTISE_LEVEL) == set(ExpertiseLevel)
    for density in DENSITY_BY_EXPERTISE_LEVEL.values():
        assert isinstance(density, Density)


def test_beginner_and_engineer_map_to_different_densities() -> None:
    """The concrete claim the plan makes: a beginner gets a less dense layout than an engineer."""
    assert (
        DENSITY_BY_EXPERTISE_LEVEL[ExpertiseLevel.BEGINNER]
        != DENSITY_BY_EXPERTISE_LEVEL[ExpertiseLevel.ENGINEER]
    )


def test_dark_and_light_use_the_same_accent_for_brand_continuity() -> None:
    """Not a hard requirement -- documents a deliberate current choice.

    If a future theme pass diverges the accent hue between themes, update
    this test rather than treating its failure as a regression.
    """
    assert DARK_TOKENS.accent == LIGHT_TOKENS.accent
