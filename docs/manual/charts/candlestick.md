---
title: "Candlestick Chart"
anchors:
  - charts.candlestick
---

# Candlestick Chart

`uadas_core.visualization.advanced_charts.CandlestickChart`. **Required:** an x column (each
candle's period, typically a date) and four numeric columns: open, high, low and close.
**Optional:** a numeric volume column, which adds a bar pane titled "Volume" under the candles on
the same x axis (one zoom or pan moves both).

Each candle spans the period's low to high; its body runs from open to close. Direction is shown
by the body's fill as well as its colour: a hollow green body means the price rose (close above
open), a solid red body means it fell, so the two stay distinguishable without colour. The range
slider Plotly adds to candlesticks by default is switched off.

The chart draws the periods it is given and nothing else: a date axis with no rows for weekends
shows a gap there. Unlike the line chart it is not downsampled, so chart a window (a quarter, a
year) rather than a decade of minute bars; a saved chart rendered in the web app uses the first
5,000 rows of the dataset and says so.
