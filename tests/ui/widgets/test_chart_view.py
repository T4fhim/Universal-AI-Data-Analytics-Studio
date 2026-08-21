# File: tests/ui/widgets/test_chart_view.py
"""Tests for ChartView's layout-merging helpers and its real-widget lifecycle.

Split in two tiers, per the plan's R6 risk note (offscreen QWebEngineView
can hang or fail to initialize):

- ``_merge_layout``/``_flatten_layout`` are plain functions -- tested with
  zero Qt involvement.
- The ``@pytest.mark.webengine`` class below is the *one* guarded smoke
  test that constructs real ``ChartView`` instances (each one a real
  ``QWebEngineView``) and pumps the event loop to let the async page load
  complete. It is skippable via ``-m "not webengine"`` (or by setting
  ``SKIP_WEBENGINE_TESTS=1``) for an environment where offscreen WebEngine
  genuinely cannot initialize, without deleting the coverage outright.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import plotly.graph_objects as go
import pytest
from PySide6.QtWidgets import QApplication

from src.ui.theme.tokens import DARK_TOKENS, LIGHT_TOKENS
from src.ui.web import web_assets
from src.ui.widgets.chart_view import ChartView, _flatten_layout, _merge_layout

# -- Pure-function tier: no QApplication required --------------------------


def test_merge_layout_preserves_sibling_keys_in_nested_dicts() -> None:
    """The bug a naive `{**base, **override}` would introduce: overriding
    `title` wholesale would either drop the figure's own title text or the
    theme's font colour, since neither dict alone has both.
    """
    base = {"title": {"text": "Revenue by Region"}, "xaxis": {"gridcolor": "#000"}}
    override = {"title": {"font": {"color": "#fff"}}, "xaxis": {"gridcolor": "#333"}}

    merged = _merge_layout(base, override)

    assert merged["title"] == {"text": "Revenue by Region", "font": {"color": "#fff"}}
    assert merged["xaxis"] == {"gridcolor": "#333"}  # override wins on direct conflict


def test_merge_layout_adds_new_top_level_keys_from_override() -> None:
    merged = _merge_layout({"title": {"text": "x"}}, {"paper_bgcolor": "#111"})
    assert merged["paper_bgcolor"] == "#111"
    assert merged["title"] == {"text": "x"}


def test_flatten_layout_produces_dot_path_keys() -> None:
    flat = _flatten_layout({"xaxis": {"tickfont": {"color": "#fff"}}, "title": {}})
    assert flat == {"xaxis.tickfont.color": "#fff"}


def test_flatten_layout_leaves_top_level_scalars_unprefixed() -> None:
    flat = _flatten_layout({"paper_bgcolor": "#111", "font": {"size": 12}})
    assert flat == {"paper_bgcolor": "#111", "font.size": 12}


# -- Guarded real-widget tier -----------------------------------------------

_webengine = pytest.mark.webengine
_skip_webengine = pytest.mark.skipif(
    os.environ.get("SKIP_WEBENGINE_TESTS") == "1",
    reason=(
        "SKIP_WEBENGINE_TESTS=1 set; offscreen QWebEngineView unavailable "
        "here (see plan risk R6)"
    ),
)


def _make_figure() -> go.Figure:
    return go.Figure(
        data=[go.Bar(x=["a", "b"], y=[1, 2])], layout={"title": {"text": "Test"}}
    )


def _pump_until(app: QApplication, condition, timeout_seconds: float = 25.0) -> bool:
    """Pump the event loop until ``condition()`` is true, or ``timeout_seconds`` elapses.

    25s, not the original 8s -- see this class's own docstring/root-cause note below for
    the measured evidence behind that specific number.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if condition():
            return True
        app.processEvents()
        time.sleep(0.02)
    return condition()


@_webengine
@_skip_webengine
class TestChartViewRealWidget:
    """Root-caused, with measured evidence, during the M27 remediation pass.

    This class's tests were a confirmed intermittent flake in full-suite runs
    (never in isolation, nor in a small isolated subset that included its
    heaviest neighboring test) -- ``test_figure_renders_and_host_becomes_ready``
    occasionally timed out waiting for ``ChartView._rendered`` at the original
    8s ``_pump_until`` budget. Two candidate causes were ruled out with real
    evidence before landing on the actual one:

    - **Not** a leaked ``QWebEngineView`` from the immediately preceding test
      in this class: a settle-the-event-loop step added to ``teardown_method``
      (pumping briefly after every test, so a next test never starts while a
      prior one's ``deleteLater()``-scheduled page teardown is still in
      flight) did not eliminate the flake across two subsequent full-suite
      runs -- both still failed at this exact class.
    - **Not** localized to this file's own immediate neighbors: running just
      ``tests/ui/widgets/data_table/test_pandas_table_model.py`` (whose own
      1M-row construction/timing-budget test runs immediately before this
      file in full-suite collection order) together with this file passed
      cleanly in 14.55s, 26/26 -- the same tests that fail in a 1172-test
      full run do not fail in a small subset that includes their heaviest
      neighbor.

    What actually reproduced it, with numbers: instrumenting ``_pump_until``
    with a much larger (60s) ceiling and timing how long each real load
    actually took, under genuine full-suite conditions (a ~9-minute, 1172-
    test run with cumulative widget/thread/native-library state built up
    across everything that ran before this class), showed real completion
    times of 14.02s, 6.48s, and 6.88s -- consistently well past the original
    8s budget on the slowest of the three, never remotely close to hanging.
    This is genuine cumulative full-suite resource pressure (memory, CPU,
    and OS-level Chromium-process-launch contention built up over roughly a
    thousand preceding tests, not something specific to this file's own
    immediate neighbors), which is also why an isolated or small-subset run
    never reproduces it. 25s (roughly 2x the worst measured 14.02s) is the
    justified budget this class now uses -- generous enough to absorb that
    measured full-suite variance without masking a genuine hang the way an
    unbounded or very large timeout would.

    The teardown_method settle-step from the (disproven) leaked-widget theory
    is kept below regardless -- pumping the event loop briefly after each
    test so a prior test's scheduled page teardown gets a chance to run is
    still a reasonable hygiene practice on its own merits, it simply was not
    sufficient by itself to be *the* fix.

    A related, separate flake was also observed in this same investigation:
    ``tests/ui/workbench/test_predict_page.py::
    test_comparison_run_reports_progress_to_a_real_status_bar`` (a genuine
    ``QThreadPool`` worker fitting all 5 forecasters twice each) missed even
    its own considerably more generous 30s ``wait_for_signal`` budget in two
    of three full-suite runs during this investigation -- the same
    "cumulative full-suite resource pressure" mechanism, in a different file,
    unrelated to ``QWebEngineView`` specifically. Left unfixed here: out of
    this class's scope, flagged for whoever next touches that test/file.
    """

    def setup_method(self) -> None:
        web_assets.reset_staged_assets_for_tests()

    def teardown_method(self) -> None:
        web_assets.reset_staged_assets_for_tests()
        # See this class's own docstring for why this alone does not fix the
        # flake (kept anyway: still a reasonable settle point on its own).
        app = QApplication.instance()
        if app is not None:
            deadline = time.time() + 1.0
            while time.time() < deadline:
                app.processEvents()
                time.sleep(0.01)

    def test_opening_ten_charts_leaves_staged_asset_count_flat(
        self, qapp: QApplication
    ) -> None:
        """The milestone-16 acceptance criterion: disk usage stays flat
        regardless of how many chart tabs get opened in one session.
        """
        figure = _make_figure()
        views = [ChartView() for _ in range(10)]
        for view in views:
            view.display_figure(figure, DARK_TOKENS)

        staged_dir = Path(web_assets.staged_chart_host_url().toLocalFile()).parent
        assert len(list(staged_dir.iterdir())) == 3  # host, bridge js, plotly.min.js

        for view in views:
            view.close()

    def test_figure_renders_and_host_becomes_ready(self, qapp: QApplication) -> None:
        view = ChartView()
        view.display_figure(_make_figure(), DARK_TOKENS)

        assert _pump_until(qapp, lambda: view._rendered)
        assert view._host_ready is True
        view.close()

    def test_apply_theme_does_not_raise_after_render(self, qapp: QApplication) -> None:
        view = ChartView()
        view.display_figure(_make_figure(), DARK_TOKENS)
        assert _pump_until(qapp, lambda: view._rendered)

        view.apply_theme(LIGHT_TOKENS)  # must not raise
        qapp.processEvents()
        view.close()

    def test_apply_theme_before_any_render_only_stores_tokens(
        self, qapp: QApplication
    ) -> None:
        view = ChartView()
        view.apply_theme(LIGHT_TOKENS)  # no figure yet -- must not raise
        assert view._tokens is LIGHT_TOKENS
        view.close()

    def test_close_event_deletes_page_without_crashing(
        self, qapp: QApplication
    ) -> None:
        """Regression guard for the confirmed Windows QWebEngineView
        shutdown crash the pyside6-development skill and plan risk R2
        both name -- page().deleteLater() must run from closeEvent.
        """
        view = ChartView()
        view.display_figure(_make_figure(), DARK_TOKENS)
        _pump_until(qapp, lambda: view._rendered)

        view.close()
        qapp.processEvents()  # let the deleteLater() actually process
