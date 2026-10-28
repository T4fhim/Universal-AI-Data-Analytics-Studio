# File: tests/visualization/gold_set.py
"""The chart-intelligence gold set: seeded datasets with the charts a sensible analyst would (and would not) show.

Step 8 (``plans/phase-4-chart-intelligence.md``, CI.0) measures every later change against this file, so the
recommender is tuned on data rather than by feel: CI.3 must clear the quality bar in section 4 of that plan
(a top-3 hit on at least 90 % of cases, no suggestion that cannot be built, no forbidden chart in the top five),
and CI.7 only ships the AI layer if it beats the rule-based baseline measured here.

Why generators and not committed data files: every case is rebuilt from a fixed seed, so the set is
byte-for-byte reproducible, carries no third-party licence and no tenant data, and the 1M-row case never has to
be stored (the large-file pre-commit check would reject it anyway). ``rows`` is a parameter for exactly that case.

Why an *acceptable set* per case rather than one right answer: several charts are legitimate for one dataset, and a
single expected chart would punish a correct recommendation. ``forbidden`` names charts that mislead or cannot be
read for that shape (a pie of 500 customers, a radar with 12 axes); ``avoid_columns`` names columns that must never
be bound to a suggestion (a sequential id is not a measure).

Not a test of :mod:`~uadas_core.visualization.chart_recommender` itself: ``test_gold_set.py`` checks the set's own
invariants, and :func:`evaluate` is the measuring instrument CI.3 and CI.7 call.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from uadas_core.visualization.chart_registry import get_chart

# Rows of a case's frame that the validity probe builds a figure from: enough to exercise a chart class, few
# enough that scoring 29 cases stays quick.
_BUILD_PROBE_ROWS = 2_000


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _daily(n: int, start: str = "2023-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="D")


# --------------------------------------------------------------------------- generators
# One function per case. Column names are what a user would plausibly upload: the recommender must not depend on
# a lucky name, but the reasons it prints read better with real ones.


def _daily_timeseries(n: int) -> pd.DataFrame:
    rng = _rng(1)
    season = 10 * np.sin(np.arange(n) * 2 * np.pi / 7)
    return pd.DataFrame(
        {
            "date": _daily(n),
            "sales": np.linspace(100, 160, n) + season + rng.normal(0, 3, n),
        }
    )


def _two_measures_over_time(n: int) -> pd.DataFrame:
    rng = _rng(2)
    revenue = np.linspace(200, 320, n) + rng.normal(0, 8, n)
    return pd.DataFrame(
        {
            "month": pd.date_range("2015-01-01", periods=n, freq="MS"),
            "revenue": revenue,
            "cost": revenue * 0.6 + rng.normal(0, 5, n),
        }
    )


def _irregular_timeseries(n: int) -> pd.DataFrame:
    rng = _rng(3)
    gaps = rng.integers(1, 9, n)
    stamps = pd.Timestamp("2022-03-01") + pd.to_timedelta(np.cumsum(gaps), unit="D")
    return pd.DataFrame({"visit_date": stamps, "temperature": 15 + rng.normal(0, 4, n)})


def _ohlc_prices(n: int) -> pd.DataFrame:
    rng = _rng(4)
    close = 50 + np.cumsum(rng.normal(0, 1, n))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.6, n))
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2022-01-03", periods=n),
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread,
            "close": close,
            "volume": rng.integers(10_000, 90_000, n),
        }
    )


def _seasonal_sales(n: int) -> pd.DataFrame:
    rng = _rng(5)
    return pd.DataFrame(
        {
            "date": pd.to_datetime("2022-01-01")
            + pd.to_timedelta(rng.integers(0, 730, n), unit="D"),
            "region": rng.choice(["north", "south", "east", "west"], n),
            "product": rng.choice(["a", "b", "c", "d", "e"], n),
            "units": rng.poisson(20, n),
        }
    )


def _region_sales(n: int) -> pd.DataFrame:
    rng = _rng(6)
    return pd.DataFrame(
        {
            "region": rng.choice(["north", "south", "east", "west", "central"], n),
            "sales": rng.gamma(3.0, 100.0, n),
        }
    )


def _customer_amounts(n: int) -> pd.DataFrame:
    rng = _rng(7)
    return pd.DataFrame(
        {
            "customer_id": [f"C{i:04d}" for i in rng.integers(0, 500, n)],
            "amount": rng.lognormal(4.0, 0.9, n),
        }
    )


def _numeric_id_trap(n: int) -> pd.DataFrame:
    rng = _rng(8)
    return pd.DataFrame(
        {
            "order_id": np.arange(1, n + 1),
            "amount": rng.gamma(2.0, 40.0, n),
            "quantity": rng.integers(1, 12, n),
        }
    )


def _correlated_pair(n: int) -> pd.DataFrame:
    rng = _rng(9)
    x = rng.normal(0, 1, n)
    return pd.DataFrame(
        {
            "height_cm": 170 + 8 * x,
            "weight_kg": 70 + 9 * (0.9 * x + 0.44 * rng.normal(0, 1, n)),
        }
    )


def _independent_pair(n: int) -> pd.DataFrame:
    rng = _rng(10)
    return pd.DataFrame({"x": rng.normal(0, 1, n), "y": rng.normal(0, 1, n)})


def _wide_numeric(n: int) -> pd.DataFrame:
    rng = _rng(11)
    base = rng.normal(0, 1, (n, 3))
    cols = {
        f"c{i:02d}": base[:, i % 3] * rng.uniform(0.5, 2) + rng.normal(0, 0.5, n)
        for i in range(12)
    }
    return pd.DataFrame(cols)


def _survey_likert(n: int) -> pd.DataFrame:
    rng = _rng(12)
    frame = {f"q{i}": rng.integers(1, 6, n) for i in range(1, 6)}
    frame["group"] = rng.choice(["a", "b", "c"], n)
    return pd.DataFrame(frame)


def _hierarchy_sales(n: int) -> pd.DataFrame:
    rng = _rng(13)
    tree = {
        "emea": ["uk", "de", "fr"],
        "apac": ["jp", "au", "sg"],
        "amer": ["us", "ca", "br"],
    }
    region = rng.choice(list(tree), n)
    return pd.DataFrame(
        {
            "region": region,
            "country": [rng.choice(tree[r]) for r in region],
            "product": rng.choice(["x", "y", "z"], n),
            "sales": rng.gamma(2.0, 50.0, n),
        }
    )


def _signed_increments(n: int) -> pd.DataFrame:
    steps = ["start", "price", "volume", "mix", "fx", "cost", "tax", "end"]
    delta = [100.0, 12.0, -7.0, 4.0, -3.0, -9.0, -5.0, 0.0]
    return pd.DataFrame({"step": steps[:n], "delta": delta[:n]})


def _funnel_stages(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stage": ["visit", "signup", "trial", "paid", "renewed"][:n],
            "users": [10_000, 4_200, 1_900, 700, 520][:n],
        }
    )


def _single_skewed_measure(n: int) -> pd.DataFrame:
    return pd.DataFrame({"amount": _rng(14).lognormal(3.0, 1.1, n)})


def _categorical_only(n: int) -> pd.DataFrame:
    rng = _rng(15)
    return pd.DataFrame(
        {
            "channel": rng.choice(["web", "store", "phone"], n),
            "segment": rng.choice(["smb", "mid", "ent"], n),
        }
    )


def _simpsons_pair(n: int) -> pd.DataFrame:
    """Within each group y falls as x rises; across groups the group means rise, so the pooled trend flips."""
    rng = _rng(16)
    group = rng.choice(["a", "b", "c"], n)
    offset = np.array([{"a": 0.0, "b": 4.0, "c": 8.0}[g] for g in group])
    within = rng.normal(0, 1, n)
    return pd.DataFrame(
        {
            "x": within + offset,
            "y": -0.8 * within + 2 * offset + rng.normal(0, 0.5, n),
            "group": group,
        }
    )


def _tiny_five_rows(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {"category": ["a", "b", "c", "d", "e"][:n], "value": [5, 9, 3, 7, 4][:n]}
    )


def _one_row(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {"units": [1200][:n], "revenue": [48_000.0][:n], "cost": [31_000.0][:n]}
    )


def _zero_rows(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series(dtype="datetime64[ns]"),
            "sales": pd.Series(dtype="float64"),
            "region": pd.Series(dtype="object"),
        }
    )


def _all_null_measure(n: int) -> pd.DataFrame:
    rng = _rng(17)
    return pd.DataFrame(
        {
            "empty_col": np.full(n, np.nan),
            "sales": rng.gamma(3.0, 90.0, n),
            "region": rng.choice(["n", "s", "e"], n),
        }
    )


def _constant_measure(n: int) -> pd.DataFrame:
    rng = _rng(18)
    return pd.DataFrame(
        {
            "flat": np.full(n, 7.0),
            "sales": rng.gamma(3.0, 90.0, n),
            "region": rng.choice(["n", "s", "e"], n),
        }
    )


def _ambiguous_mixed_column(n: int) -> pd.DataFrame:
    rng = _rng(19)
    return pd.DataFrame(
        {
            "code": rng.choice(["12", "7", "3", "N/A", "x9"], n),
            "sales": rng.gamma(3.0, 90.0, n),
            "region": rng.choice(["n", "s", "e"], n),
        }
    )


def _bubble_gapminder_like(n: int) -> pd.DataFrame:
    rng = _rng(20)
    gdp = rng.lognormal(9.0, 1.0, n)
    return pd.DataFrame(
        {
            "gdp_per_capita": gdp,
            "life_expectancy": 45 + 4.0 * np.log(gdp) + rng.normal(0, 2, n),
            "population": rng.lognormal(16.0, 1.2, n),
            "continent": rng.choice(["africa", "asia", "europe", "americas"], n),
        }
    )


def _budget_vs_actual(n: int) -> pd.DataFrame:
    rng = _rng(21)
    budget = rng.uniform(50, 150, n)
    return pd.DataFrame(
        {
            "department": [f"dept{i}" for i in range(n)],
            "budget": budget,
            "actual": budget * rng.uniform(0.8, 1.2, n),
        }
    )


def _composition_over_time(n: int) -> pd.DataFrame:
    rng = _rng(22)
    months = pd.date_range("2021-01-01", periods=max(n // 4, 1), freq="MS")
    return pd.DataFrame(
        {
            "month": np.repeat(months, 4)[:n],
            "segment": np.tile(["smb", "mid", "ent", "gov"], len(months))[:n],
            "revenue": rng.gamma(4.0, 50.0, n),
        }
    )


def _huge_timeseries(n: int) -> pd.DataFrame:
    rng = _rng(23)
    return pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-01", periods=n, freq="min"),
            "value": np.cumsum(rng.normal(0, 1, n)),
        }
    )


def _wide_200_columns(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        _rng(24).normal(0, 1, (n, 200)), columns=[f"c{i:03d}" for i in range(200)]
    )


# --------------------------------------------------------------------------- the cases


@dataclass(frozen=True)
class GoldCase:
    """One dataset and what the recommender may and may not do with it.

    Attributes:
        name: Stable id, used in reports.
        build: ``rows -> DataFrame``; deterministic for a given ``rows``.
        rows: The size the unit tests use. A benchmark passes its own (the 1M-row case).
        acceptable: Registry keys, at least one of which must be in the top three. Empty only with
            ``expects_empty``.
        forbidden: Registry keys that must not appear anywhere in the top five.
        avoid_columns: Columns that must never be bound to any suggestion.
        expects_empty: The right answer is no suggestion at all (a frame with nothing to draw).
    """

    name: str
    build: Callable[[int], pd.DataFrame]
    rows: int
    acceptable: frozenset[str]
    forbidden: frozenset[str] = frozenset()
    avoid_columns: frozenset[str] = frozenset()
    expects_empty: bool = False


def _case(
    name: str,
    build: Callable[[int], pd.DataFrame],
    rows: int,
    acceptable: str,
    forbidden: str = "",
    avoid: str = "",
    empty: bool = False,
) -> GoldCase:
    return GoldCase(
        name,
        build,
        rows,
        frozenset(acceptable.split()),
        frozenset(forbidden.split()),
        frozenset(avoid.split()),
        empty,
    )


_NONSENSE_FOR_TIME = "pie funnel treemap radar waterfall"

GOLD_CASES: tuple[GoldCase, ...] = (
    _case("daily_timeseries", _daily_timeseries, 365, "line", _NONSENSE_FOR_TIME),
    _case(
        "two_measures_over_time",
        _two_measures_over_time,
        120,
        "line scatter",
        "pie funnel treemap",
    ),
    _case(
        "irregular_timeseries", _irregular_timeseries, 200, "line", "pie funnel treemap"
    ),
    _case("ohlc_prices", _ohlc_prices, 250, "candlestick line", "pie funnel treemap"),
    _case(
        "seasonal_sales_region_product",
        _seasonal_sales,
        730,
        "line bar heatmap",
        "funnel radar waterfall",
    ),
    _case(
        "region_sales_low_cardinality",
        _region_sales,
        200,
        "bar pie",
        "line candlestick scatter",
    ),
    _case(
        "customer_amounts_high_cardinality",
        _customer_amounts,
        2000,
        "histogram box_plot bar",
        "pie treemap radar",
    ),
    _case(
        "numeric_id_trap",
        _numeric_id_trap,
        500,
        "histogram box_plot scatter",
        "pie funnel",
        avoid="order_id",
    ),
    _case(
        "correlated_pair",
        _correlated_pair,
        500,
        "scatter heatmap",
        "pie funnel treemap",
    ),
    _case(
        "independent_pair",
        _independent_pair,
        500,
        "scatter histogram box_plot heatmap",
        "pie funnel waterfall",
    ),
    _case(
        "wide_numeric_12",
        _wide_numeric,
        400,
        "heatmap scatter",
        "radar pie funnel waterfall",
    ),
    _case(
        "survey_likert",
        _survey_likert,
        300,
        "bar box_plot histogram heatmap radar",
        "line candlestick waterfall",
    ),
    _case(
        "hierarchy_sales",
        _hierarchy_sales,
        600,
        "treemap bar",
        "line candlestick scatter",
    ),
    _case(
        "signed_increments",
        _signed_increments,
        8,
        "waterfall bar",
        "pie treemap funnel",
    ),
    _case("funnel_stages", _funnel_stages, 5, "funnel bar", "scatter candlestick"),
    _case(
        "single_skewed_measure",
        _single_skewed_measure,
        1000,
        "histogram box_plot",
        "scatter pie line candlestick",
    ),
    _case(
        "categorical_only",
        _categorical_only,
        300,
        "bar pie heatmap",
        "line scatter histogram candlestick",
    ),
    _case("simpsons_pair", _simpsons_pair, 600, "scatter box_plot", "pie funnel"),
    _case(
        "tiny_five_rows",
        _tiny_five_rows,
        5,
        "bar pie kpi",
        "line candlestick scatter histogram",
    ),
    _case(
        "one_row",
        _one_row,
        1,
        "kpi",
        "line scatter histogram box_plot heatmap candlestick",
    ),
    _case("zero_rows", _zero_rows, 0, "", empty=True),
    _case(
        "all_null_measure",
        _all_null_measure,
        100,
        "bar histogram box_plot pie",
        avoid="empty_col",
    ),
    _case(
        "constant_measure",
        _constant_measure,
        100,
        "bar histogram box_plot pie",
        avoid="flat",
    ),
    _case(
        "ambiguous_mixed_column",
        _ambiguous_mixed_column,
        100,
        "bar histogram box_plot pie",
        avoid="code",
    ),
    _case(
        "bubble_gapminder_like",
        _bubble_gapminder_like,
        150,
        "bubble scatter",
        "pie funnel waterfall",
    ),
    _case(
        "budget_vs_actual",
        _budget_vs_actual,
        12,
        "bar waterfall",
        "candlestick funnel pie",
    ),
    _case(
        "composition_over_time",
        _composition_over_time,
        48,
        "bar line",
        "funnel radar candlestick",
    ),
    _case("huge_timeseries", _huge_timeseries, 20_000, "line", _NONSENSE_FOR_TIME),
    _case(
        "wide_200_columns",
        _wide_200_columns,
        50,
        "heatmap scatter histogram box_plot kpi",
        "radar pie funnel",
    ),
)


# --------------------------------------------------------------------------- measuring


@dataclass(frozen=True)
class CaseResult:
    """What one recommender did with one case."""

    name: str
    types: tuple[str, ...]
    top3_hit: bool
    forbidden_shown: tuple[str, ...]
    avoided_bound: tuple[str, ...]
    unbuildable: tuple[str, ...]
    empty_ok: bool | None
    error: str | None


# The positional contract of today's recommender, written out so the baseline can be built at all:
# ``ChartSuggestion.columns`` carries no field names, and the registry cannot supply them (``line`` takes
# ``y_column`` as required and ``x_column`` as optional; ``heatmap`` has no required field). This gap is CI.0
# finding 1 in ``plans/phase-4-ci0-findings.md``. CI.3's suggestions carry explicit ``params``, which
# :func:`_params_for` prefers, and this table is then deleted.
_LEGACY_COLUMN_FIELDS: dict[str, tuple[str, ...]] = {
    "line": ("x_column", "y_column"),
    "scatter": ("x_column", "y_column"),
    "bar": ("category_column", "value_column"),
    "pie": ("category_column",),
    "histogram": ("column",),
    "box_plot": ("value_column", "group_column"),
    "heatmap": (),
}


def _params_for(
    chart_type: str, columns: Sequence[str], explicit: dict[str, object] | None
) -> dict[str, object]:
    """The builder parameters for one suggestion: its own ``params`` if it has them, else the legacy mapping."""
    if explicit is not None:
        return dict(explicit)
    return dict(zip(_LEGACY_COLUMN_FIELDS[chart_type], columns, strict=False))


def evaluate(
    recommend: Callable[[pd.DataFrame, int], list],
    cases: Sequence[GoldCase] = GOLD_CASES,
    k: int = 5,
) -> list[CaseResult]:
    """Run ``recommend(frame, k)`` over ``cases`` and record the five things the quality bar needs.

    A recommender that raises is recorded as ``error`` and counts against it; it is never allowed to abort the run,
    because "does not crash on odd data" is itself a requirement.
    """
    results: list[CaseResult] = []
    for case in cases:
        frame = case.build(case.rows)
        try:
            suggestions = recommend(frame, k)
        except Exception as exc:  # noqa: BLE001 - recorded, see docstring
            results.append(
                CaseResult(case.name, (), False, (), (), (), None, type(exc).__name__)
            )
            continue
        types = tuple(s.chart_type for s in suggestions)
        bound = {c for s in suggestions for c in s.columns}
        unbuildable: list[str] = []
        probe = frame.head(_BUILD_PROBE_ROWS)
        for s in suggestions:
            try:
                params = _params_for(
                    s.chart_type, s.columns, getattr(s, "params", None)
                )
                get_chart(s.chart_type).chart_class.build(probe, **params)
            except Exception:  # noqa: BLE001 - any failure means not drawable
                unbuildable.append(s.chart_type)
        results.append(
            CaseResult(
                name=case.name,
                types=types,
                top3_hit=bool(case.acceptable & set(types[:3])),
                forbidden_shown=tuple(sorted(case.forbidden & set(types))),
                avoided_bound=tuple(sorted(case.avoid_columns & bound)),
                unbuildable=tuple(unbuildable),
                empty_ok=(not types) if case.expects_empty else None,
                error=None,
            )
        )
    return results


def summarise(
    results: Sequence[CaseResult], cases: Sequence[GoldCase] = GOLD_CASES
) -> dict[str, float | int]:
    """The numbers the plan's quality bar is stated in."""
    scored = [r for r, c in zip(results, cases, strict=True) if not c.expects_empty]
    return {
        "cases": len(results),
        "top3_hit_rate": round(sum(r.top3_hit for r in scored) / len(scored), 3),
        "crashes": sum(r.error is not None for r in results),
        "unbuildable_suggestions": sum(len(r.unbuildable) for r in results),
        "forbidden_shown": sum(len(r.forbidden_shown) for r in results),
        "avoided_columns_bound": sum(len(r.avoided_bound) for r in results),
        "empty_cases_wrong": sum(r.empty_ok is False for r in results),
        "cases_with_3_distinct_types": sum(len(set(r.types)) >= 3 for r in results),
    }
