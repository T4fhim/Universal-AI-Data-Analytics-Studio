# File: tests/ui/web/test_web_assets.py
"""Tests for the chart web-asset staging singleton.

Deliberately does not construct a QWebEngineView (see R6 in the plan --
offscreen QWebEngineView can hang or fail to initialize) -- everything here
is staging/filesystem behaviour, testable as plain functions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.exceptions import ServiceError
from src.ui.web import web_assets


@pytest.fixture(autouse=True)
def _reset_staging() -> None:
    """Force a fresh temp dir per test -- the module singleton otherwise
    persists across the whole test session by design (see the module
    docstring), which would let one test's staging silently satisfy
    another's assertions.
    """
    web_assets.reset_staged_assets_for_tests()
    yield
    web_assets.reset_staged_assets_for_tests()


def test_staged_chart_host_url_points_at_a_real_file() -> None:
    url = web_assets.staged_chart_host_url()
    path = Path(url.toLocalFile())
    assert path.is_file()
    assert path.name == "chart_host.html"


def test_staging_copies_all_three_assets_once() -> None:
    url = web_assets.staged_chart_host_url()
    staged_dir = Path(url.toLocalFile()).parent
    assert sorted(p.name for p in staged_dir.iterdir()) == [
        "chart_bridge.js",
        "chart_host.html",
        "plotly.min.js",
    ]


def test_staging_is_idempotent_across_repeated_calls() -> None:
    """Ten calls (proxying "ten ChartViews opened in one session") must
    resolve to the same staged file, not create ten copies -- this is the
    module-level singleton behind the milestone's "disk usage stays flat"
    acceptance criterion.
    """
    urls = [web_assets.staged_chart_host_url() for _ in range(10)]
    assert len({url.toLocalFile() for url in urls}) == 1


def test_missing_source_asset_raises_service_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A broken install (a missing resources/web/ file) must fail loudly,
    not silently fall back to writing a new per-call temp file -- that
    fallback would quietly reintroduce the exact leak this module exists to
    prevent.
    """
    monkeypatch.setattr(web_assets, "_SOURCE_WEB_ROOT", tmp_path)
    with pytest.raises(ServiceError, match="Missing chart web asset"):
        web_assets.staged_chart_host_url()
