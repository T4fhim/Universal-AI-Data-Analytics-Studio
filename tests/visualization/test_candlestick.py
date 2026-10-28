# File: tests/visualization/test_candlestick.py
"""``CandlestickChart`` draws price candles, with an optional volume pane (phase-4 step 7.4, Tier-1 V04).

Unlike the options added in steps 7.2 and 7.3 this is a new registry type: a candle needs four
price columns, which no existing chart takes. These tests pin the registration, the figure's
shape with and without volume, and the column checks.
"""

from __future__ import annotations

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.advanced_charts import CandlestickChart
from uadas_core.visualization.chart_registry import _register_builtins, get_chart


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "day": pd.date_range("2025-01-01", periods=4, freq="D"),
            "open": [10.0, 11.0, 12.5, 12.0],
            "high": [11.5, 12.8, 13.0, 12.6],
            "low": [9.5, 10.8, 11.9, 11.2],
            "close": [11.0, 12.5, 12.0, 11.4],
            "volume": [1200, 900, 1500, 700],
        }
    )


def _build(**kwargs):
    return CandlestickChart.build(
        _prices(),
        x_column="day",
        open_column="open",
        high_column="high",
        low_column="low",
        close_column="close",
        **kwargs,
    )


def test_it_is_registered_with_its_price_columns() -> None:
    _register_builtins()
    registration = get_chart("candlestick")
    assert registration.chart_class is CandlestickChart
    assert registration.required_fields == (
        "x_column",
        "open_column",
        "high_column",
        "low_column",
        "close_column",
    )
    assert registration.optional_fields == ("volume_column",)


def test_without_volume_it_is_one_candlestick_trace_with_the_four_prices() -> None:
    figure = _build()
    assert len(figure.data) == 1
    trace = figure.data[0]
    assert trace.type == "candlestick"
    assert list(trace.open) == [10.0, 11.0, 12.5, 12.0]
    assert list(trace.high) == [11.5, 12.8, 13.0, 12.6]
    assert list(trace.low) == [9.5, 10.8, 11.9, 11.2]
    assert list(trace.close) == [11.0, 12.5, 12.0, 11.4]
    assert len(trace.x) == 4


def test_the_range_slider_is_off() -> None:
    # Plotly turns a range slider on for every candlestick by default; it would cover the plot.
    assert _build().layout.xaxis.rangeslider.visible is False
    assert _build(volume_column="volume").layout.xaxis.rangeslider.visible is False


def test_volume_is_a_bar_pane_under_the_candles_on_the_same_x_axis() -> None:
    figure = _build(volume_column="volume")
    candles, volume = figure.data
    assert candles.type == "candlestick"
    assert volume.type == "bar"
    assert volume.name == "Volume"
    assert list(volume.y) == [1200, 900, 1500, 700]
    assert candles.yaxis in (None, "y") and volume.yaxis == "y2"
    # The candles' x axis follows the volume pane's (which carries the tick labels).
    assert figure.layout.xaxis.matches == "x2"
    assert figure.layout.xaxis.showticklabels is False
    # The candles get the larger pane: the first y axis spans more than the volume axis.
    price_span = figure.layout.yaxis.domain[1] - figure.layout.yaxis.domain[0]
    volume_span = figure.layout.yaxis2.domain[1] - figure.layout.yaxis2.domain[0]
    assert price_span > volume_span


def test_axis_titles_and_title() -> None:
    figure = _build(volume_column="volume")
    assert figure.layout.title.text == "close over day"
    assert figure.layout.yaxis2.title.text == "volume"
    assert _build(title="Acme").layout.title.text == "Acme"


def test_a_missing_price_is_passed_through_for_plotly_to_leave_a_gap() -> None:
    frame = _prices()
    frame.loc[1, "high"] = None
    figure = CandlestickChart.build(
        frame,
        x_column="day",
        open_column="open",
        high_column="high",
        low_column="low",
        close_column="close",
    )
    assert len(figure.data[0].x) == 4  # no row is dropped or filled


def test_the_dataframe_is_not_changed() -> None:
    frame = _prices()
    before = frame.copy()
    CandlestickChart.build(
        frame,
        x_column="day",
        open_column="open",
        high_column="high",
        low_column="low",
        close_column="close",
        volume_column="volume",
    )
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("column", ["open", "high", "low", "close"])
def test_a_text_price_column_is_refused(column: str) -> None:
    frame = _prices().astype({column: str})
    with pytest.raises(ServiceError, match=f"'{column}' must be numeric"):
        CandlestickChart.build(
            frame,
            x_column="day",
            open_column="open",
            high_column="high",
            low_column="low",
            close_column="close",
        )


def test_a_text_volume_column_is_refused() -> None:
    frame = _prices().astype({"volume": str})
    with pytest.raises(ServiceError, match="'volume' must be numeric"):
        CandlestickChart.build(
            frame,
            x_column="day",
            open_column="open",
            high_column="high",
            low_column="low",
            close_column="close",
            volume_column="volume",
        )


def test_a_missing_column_is_refused() -> None:
    with pytest.raises(ServiceError, match="nope"):
        CandlestickChart.build(
            _prices(),
            x_column="day",
            open_column="open",
            high_column="high",
            low_column="low",
            close_column="nope",
        )
