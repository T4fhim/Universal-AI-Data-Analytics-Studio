# File: scripts/build_chart_gallery.py
"""Build the figures the web chart gallery draws, with the real core chart classes.

Why a generated file and not figures typed into the web app: the gallery (``/charts.html`` in
``apps/web``) exists to show every registered chart type before and after the Instrument skin,
and a hand-made figure would show a chart no user can actually get. These figures come out of
``uadas_core.visualization`` exactly as the API's ``charts_render`` returns them (plain Plotly
JSON, no styling), from a small seeded synthetic table, so the gallery cannot drift from what
the chart classes produce.

The set of charts is **the registry's**: ``main`` fails if a registered chart has no spec here
(or the reverse), the same "registry plus a separately hardcoded consumer" guard CLAUDE.md asks
for elsewhere. Run ``python scripts/build_chart_gallery.py`` after adding a chart type;
``--check`` (used by ``tests/assets/test_chart_gallery.py``) fails when the file is stale.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from uadas_core.visualization import chart_registry

OUT = ROOT / "apps" / "web" / "src" / "charts" / "gallery-figures.json"

REGIONS = ["North", "South", "East", "West"]
CHANNELS = ["Web", "Retail", "Partner"]
PRODUCTS = ["Atlas", "Beacon", "Cinder", "Delta", "Ember"]


def sample_tables() -> dict[str, pd.DataFrame]:
    """Small, seeded tables: no randomness may reach the committed file."""
    rng = np.random.default_rng(7)
    n = 160
    sales = pd.DataFrame(
        {
            "region": rng.choice(REGIONS, n),
            "channel": rng.choice(CHANNELS, n, p=[0.5, 0.3, 0.2]),
            "product": rng.choice(PRODUCTS, n),
            "ad_spend": rng.gamma(4.0, 120.0, n).round(2),
            "orders": rng.integers(5, 120, n),
        }
    )
    sales["revenue"] = (
        sales["ad_spend"] * rng.normal(3.2, 0.6, n) + sales["orders"] * 9
    ).round(2)
    sales["margin"] = rng.normal(0.28, 0.07, n).round(3)
    monthly = pd.DataFrame(
        {
            "month": pd.date_range("2025-01-01", periods=24, freq="MS"),
            "revenue": (1000 + np.arange(24) * 35 + rng.normal(0, 60, 24)).round(1),
        }
    )
    steps = pd.DataFrame(
        {
            "step": ["Start", "New", "Expansion", "Churn", "Refunds", "End"],
            "delta": [1000.0, 420.0, 260.0, -310.0, -90.0, 1280.0],
        }
    )
    funnel = pd.DataFrame(
        {
            "stage": ["Visits", "Sign-ups", "Trials", "Paid"],
            "count": [12000, 3400, 1250, 410],
        }
    )
    # Radar draws raw values on one shared axis, so its metrics share one 0-100 scale.
    teams = pd.DataFrame(
        {
            "region": REGIONS,
            "reach": [82, 64, 71, 58],
            "retention": [74, 81, 62, 69],
            "margin": [55, 63, 78, 60],
            "growth": [68, 49, 57, 85],
        }
    )
    # Drawn last so adding it leaves every table above byte-for-byte what it was.
    base = {"Web": (900, 30), "Retail": (520, 14), "Partner": (260, 9)}
    channel_months = pd.DataFrame(
        [
            {
                "month": month,
                "channel": channel,
                "revenue": round(start + i * slope + rng.normal(0, 40), 1),
            }
            for channel, (start, slope) in base.items()
            for i, month in enumerate(
                pd.date_range("2025-01-01", periods=12, freq="MS")
            )
        ]
    )
    # Drawn after channel_months for the same reason. Consecutive days, not business days, so the
    # date axis shows no weekend gaps: the core draws the dates it is given and nothing else.
    days = 40
    close = (100 + np.cumsum(rng.normal(0.3, 2.0, days))).round(2)
    open_ = (np.concatenate([[100.0], close[:-1]]) + rng.normal(0, 0.6, days)).round(2)
    prices = pd.DataFrame(
        {
            "day": pd.date_range("2025-01-02", periods=days, freq="D"),
            "open": open_,
            "high": (np.maximum(open_, close) + rng.uniform(0.3, 2.0, days)).round(2),
            "low": (np.minimum(open_, close) - rng.uniform(0.3, 2.0, days)).round(2),
            "close": close,
            "volume": rng.integers(8_000, 40_000, days),
        }
    )
    # And again last: two series whose scales differ by three orders of magnitude, the case a
    # second axis exists for.
    dual = pd.DataFrame(
        {
            "month": pd.date_range("2025-01-01", periods=24, freq="MS"),
            "revenue": (1000 + np.arange(24) * 35 + rng.normal(0, 60, 24)).round(1),
            "conversion": (2.2 + np.arange(24) * 0.03 + rng.normal(0, 0.15, 24)).round(
                2
            ),
        }
    )
    # And again last: a base year and the year compared against it, per region.
    rows = []
    for region, start in zip(REGIONS, (820, 640, 710, 560)):
        rows.append({"region": region, "year": "2024", "revenue": float(start)})
        rows.append(
            {
                "region": region,
                "year": "2025",
                "revenue": round(start * rng.uniform(0.85, 1.3), 1),
            }
        )
    pairs = pd.DataFrame(rows)
    # Last again: page visits per week and weekday (a calendar-shaped grid), and a small set of
    # models with a cost and a score (the score rises with the log of the cost, with scatter).
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    traffic = pd.DataFrame(
        [
            {
                "week": week,
                "weekday": weekday,
                "visits": int(rng.integers(20, 200)),
            }
            for week in range(1, 13)
            for weekday in weekdays
        ]
    )
    # In calendar order, not the alphabet's: an ordered category keeps its own order on an axis.
    traffic["weekday"] = pd.Categorical(traffic["weekday"], weekdays, ordered=True)
    model_cost = rng.uniform(0.2, 12.0, 14).round(2)
    models = pd.DataFrame(
        {
            "name": [f"M{i:02d}" for i in range(1, 15)],
            "cost": model_cost,
            "score": (40 + 6 * np.log(model_cost) + rng.normal(0, 3.0, 14)).round(1),
        }
    )
    return {
        "sales": sales,
        "monthly": monthly,
        "steps": steps,
        "funnel": funnel,
        "teams": teams,
        "channel_months": channel_months,
        "prices": prices,
        "dual": dual,
        "pairs": pairs,
        "traffic": traffic,
        "models": models,
    }


# chart name -> (table, keyword arguments). One entry per registered chart type.
SPECS: dict[str, tuple[str, dict[str, Any]]] = {
    "bar": ("sales", {"category_column": "region", "value_column": "revenue"}),
    "pie": ("sales", {"category_column": "channel", "value_column": "revenue"}),
    "line": ("monthly", {"y_column": "revenue", "x_column": "month"}),
    "scatter": (
        "sales",
        {"x_column": "ad_spend", "y_column": "revenue", "color_column": "region"},
    ),
    "histogram": ("sales", {"column": "revenue"}),
    "box_plot": ("sales", {"value_column": "revenue", "group_column": "region"}),
    "heatmap": ("sales", {}),
    "bubble": (
        "sales",
        {
            "x_column": "ad_spend",
            "y_column": "revenue",
            "size_column": "orders",
            "color_column": "region",
        },
    ),
    "treemap": (
        "sales",
        {"path_columns": ["region", "product"], "value_column": "revenue"},
    ),
    "radar": (
        "teams",
        {
            "category_column": "region",
            "value_columns": ["reach", "retention", "margin", "growth"],
        },
    ),
    "waterfall": ("steps", {"category_column": "step", "value_column": "delta"}),
    "funnel": ("funnel", {"stage_column": "stage", "value_column": "count"}),
    "candlestick": (
        "prices",
        {
            "x_column": "day",
            "open_column": "open",
            "high_column": "high",
            "low_column": "low",
            "close_column": "close",
            "volume_column": "volume",
        },
    ),
    "kpi": ("monthly", {"value_column": "revenue", "x_column": "month"}),
}

# An option of a registered chart that changes how it looks: gallery id -> (chart name, table,
# keyword arguments). Every registered chart still needs its base entry in SPECS above; a variant
# is one more figure from the same class, so the golden screenshot tests pin the option as well.
VARIANTS: dict[str, tuple[str, str, dict[str, Any]]] = {
    "candlestick_price_only": (
        "candlestick",
        "prices",
        {
            "x_column": "day",
            "open_column": "open",
            "high_column": "high",
            "low_column": "low",
            "close_column": "close",
        },
    ),
    "kpi_bars": (
        "kpi",
        "monthly",
        {"value_column": "revenue", "x_column": "month", "variant": "bars"},
    ),
    "kpi_dashes": (
        "kpi",
        "monthly",
        {"value_column": "revenue", "x_column": "month", "variant": "dashes"},
    ),
    "kpi_lollipop": (
        "kpi",
        "monthly",
        {"value_column": "revenue", "x_column": "month", "variant": "lollipop"},
    ),
    "heatmap_numbers": (
        "heatmap",
        "sales",
        {
            "row_column": "region",
            "column_column": "channel",
            "value_column": "revenue",
            "variant": "numbers",
        },
    ),
    "heatmap_grid": (
        "heatmap",
        "traffic",
        {
            "row_column": "weekday",
            "column_column": "week",
            "value_column": "visits",
            "variant": "grid",
        },
    ),
    "scatter_frontier": (
        "scatter",
        "models",
        {
            "x_column": "cost",
            "y_column": "score",
            "label_column": "name",
            "frontier": "upper_left",
            "pin": "M05",
        },
    ),
    "pie_grid": (
        "pie",
        "channel_months",
        {
            "category_column": "channel",
            "value_column": "revenue",
            "panel_column": "month",
        },
    ),
    "pie_donut": (
        "pie",
        "sales",
        {"category_column": "channel", "value_column": "revenue", "variant": "donut"},
    ),
    "bar_paired": (
        "bar",
        "pairs",
        {
            "category_column": "region",
            "series_column": "year",
            "value_column": "revenue",
            "variant": "paired",
        },
    ),
    "bar_grouped": (
        "bar",
        "sales",
        {
            "category_column": "region",
            "series_column": "channel",
            "value_column": "revenue",
            "variant": "grouped",
        },
    ),
    "line_dual_axis": (
        "line",
        "dual",
        {"y_column": "revenue", "y2_column": "conversion", "x_column": "month"},
    ),
    "line_area": (
        "line",
        "monthly",
        {"y_column": "revenue", "x_column": "month", "variant": "area"},
    ),
    "bar_stacked": (
        "bar",
        "channel_months",
        {
            "category_column": "month",
            "series_column": "channel",
            "value_column": "revenue",
        },
    ),
    "bar_stacked_incomplete": (
        "bar",
        "channel_months",
        {
            "category_column": "month",
            "series_column": "channel",
            "value_column": "revenue",
            "incomplete_from": "2025-12-01",
        },
    ),
}


def build_figures() -> dict[str, Any]:
    chart_registry._register_builtins()
    registered = set(chart_registry.list_charts())
    if registered != set(SPECS):
        raise SystemExit(
            "chart gallery out of sync with the registry: "
            f"missing {sorted(registered - set(SPECS))}, "
            f"unknown {sorted(set(SPECS) - registered)}"
        )
    if set(VARIANTS) & set(SPECS):
        raise SystemExit(
            f"variant ids reuse chart names: {sorted(set(VARIANTS) & set(SPECS))}"
        )
    tables = sample_tables()
    figures: dict[str, Any] = {}
    draws = {name: (name, *SPECS[name]) for name in SPECS} | VARIANTS
    for name in sorted(draws):
        chart_name, table, kwargs = draws[name]
        chart = chart_registry.get_chart(chart_name).chart_class
        figure = chart.build(tables[table].copy(), **kwargs)
        # to_json (not to_plotly_json) is what the API returns: arrays become typed-array JSON.
        figures[name] = json.loads(figure.to_json())
    return figures


def reference_stacked() -> go.Figure:
    """A multi-series stacked column: the reference the skin is tuned against, not a registry chart.

    It carries the idioms the OpenRouter rankings charts use (stacked columns that the page can
    switch to 100 %, a log axis, a trace named "Incomplete" for the latest, unfinished bucket),
    and is what the Tier-1 stacked chart will produce. The skin draws "Incomplete" hatched.
    """
    rng = np.random.default_rng(11)
    months = [f"2025-{month:02d}" for month in range(1, 13)]
    figure = go.Figure()
    for index, channel in enumerate(CHANNELS):
        start, slope = ((900, 30), (520, 14), (260, 9))[index]
        values = (start + np.arange(12) * slope + rng.normal(0, 40, 12)).round(0)
        figure.add_trace(go.Bar(name=channel, x=months, y=values))
    figure.add_trace(go.Bar(name="Incomplete", x=[months[-1]], y=[310.0]))
    figure.update_layout(
        barmode="stack",
        title="Revenue by channel and month (reference)",
        xaxis_title="month",
        yaxis_title="revenue",
    )
    return figure


def render() -> str:
    document = {
        "charts": build_figures(),
        "references": {"stacked": json.loads(reference_stacked().to_json())},
    }
    return json.dumps(document, indent=1, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--check", action="store_true", help="fail if the file is stale"
    )
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(
                f"{OUT.relative_to(ROOT)} is stale: run scripts/build_chart_gallery.py"
            )
            return 1
        print("chart gallery figures are current")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(
        f"wrote {OUT.relative_to(ROOT)} ({len(text) // 1024} KiB, {len(SPECS)} charts)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
