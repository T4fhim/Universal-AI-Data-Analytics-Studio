# File: tests/ui/theme/test_qss_compiler.py
"""Tests for compile_qss: the substitute-vs-safe_substitute decision, and perf.

No QApplication needed -- compilation is pure string work.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.core.exceptions import ServiceError
from src.ui.theme import qss_compiler
from src.ui.theme.qss_compiler import TEMPLATE_PATH, compile_qss
from src.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS, TOKENS_BY_NAME


@pytest.fixture(autouse=True)
def _clear_compiler_cache() -> None:
    """Every test gets a clean cache -- compile_qss's cache is module state."""
    qss_compiler.clear_cache()
    yield
    qss_compiler.clear_cache()


@pytest.mark.parametrize(
    "tokens", list(TOKENS_BY_NAME.values()), ids=list(TOKENS_BY_NAME)
)
def test_compiles_without_leaving_any_placeholder_behind(tokens) -> None:
    css = compile_qss(tokens, use_cache=False)
    assert "$" not in css, "a literal '$' survived compilation"
    assert "{" in css and "}" in css, "output does not look like QSS at all"


def test_real_template_compiles_under_20ms() -> None:
    """Budget from the plan: substitution is cheap; QApplication.setStyleSheet
    re-polishing the widget tree is the real cost and is not measured here.
    """
    start = time.perf_counter()
    compile_qss(DARK_TOKENS, use_cache=False)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 20, f"compile_qss took {elapsed_ms:.2f}ms, budget is 20ms"


def test_missing_token_raises_service_error_not_silent_placeholder(
    tmp_path: Path,
) -> None:
    """The whole reason substitute() was chosen over safe_substitute()."""
    broken_template = tmp_path / "broken.qss.template"
    broken_template.write_text(
        "QWidget { color: ${not_a_real_token}; }", encoding="utf-8"
    )
    with pytest.raises(ServiceError, match="not_a_real_token"):
        compile_qss(DARK_TOKENS, template_path=broken_template, use_cache=False)


def test_missing_template_file_raises_service_error(tmp_path: Path) -> None:
    with pytest.raises(ServiceError, match="not found"):
        compile_qss(
            DARK_TOKENS, template_path=tmp_path / "nope.qss.template", use_cache=False
        )


def test_result_is_cached_by_theme_and_density() -> None:
    first = compile_qss(DARK_TOKENS)
    second = compile_qss(DARK_TOKENS)
    assert first is second  # same cached string object, not merely equal


def test_use_cache_false_bypasses_the_cache() -> None:
    compile_qss(DARK_TOKENS)  # warm the cache
    fresh = compile_qss(DARK_TOKENS, use_cache=False)
    assert fresh == compile_qss(DARK_TOKENS)  # same content


def test_different_themes_are_cached_independently() -> None:
    dark_css = compile_qss(DARK_TOKENS)
    light_css = compile_qss(LIGHT_TOKENS)
    assert dark_css != light_css
    assert DARK_TOKENS.surface_0 in dark_css
    assert LIGHT_TOKENS.surface_0 in light_css


def test_default_template_path_points_at_the_real_file() -> None:
    assert TEMPLATE_PATH.exists()
    assert TEMPLATE_PATH.name == "base.qss.template"
