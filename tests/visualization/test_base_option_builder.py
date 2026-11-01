# File: tests/visualization/test_base_option_builder.py
"""The ECharts option contract (chart intelligence CI.8a): plain JSON only, named formatters, a registry rule.

An option goes to the browser and into ``setOption``, built from a tenant's data, so what may appear in it is
closed: this file pins each refusal (a function, a numpy integer, NaN, an unknown formatter name, markup in a
tooltip template, a prototype key, the two measured ECharts traps), that an error names a path and a type but
**never a value**, the rule that ties the ``echarts`` renderer to an option builder, and that the formatter
names the core allows are exactly the ones the SPA implements (read from its source).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from uadas_core.analysis.fingerprint import SemanticRole
from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization import base_option_builder
from uadas_core.visualization.base_option_builder import (
    FORMATTER_NAMES,
    BaseOptionBuilder,
    OptionError,
    fmt,
    validate_option,
)
from uadas_core.visualization.categorical_charts import BarChart
from uadas_core.visualization.chart_fit import ChartFit, ChartIntent, Renderer, Slot
from uadas_core.visualization.chart_registry import (
    ChartRegistration,
    list_charts,
    option_builder_for,
    register_chart,
    unregister_chart,
)

ROOT = Path(__file__).resolve().parents[2]


def _plain() -> dict[str, Any]:
    return {
        "xAxis": {"type": "category", "data": ["a", "b", "c"]},
        "yAxis": {"type": "value", "axisLabel": {"formatter": fmt("compact")}},
        "series": [
            {"type": "bar", "data": [1, 2.5, 3]},
            {"type": "scatter", "large": True, "data": [[1, 2], [3, 4]]},
        ],
        "tooltip": {"formatter": "{b}: {c}", "valueFormatter": fmt("thousands")},
        # ``axisPointer.link`` is a list that links crosshairs (the candlestick + volume recipe), not a URL.
        "axisPointer": {"link": [{"xAxisIndex": "all"}]},
        "aria": {"enabled": True, "decal": {"show": False}},
        "empty": None,
        "flag": True,
    }


def test_a_plain_option_with_named_formatters_is_valid() -> None:
    validate_option(_plain())
    validate_option({"series": ((1, 2), (3, 4))})  # tuples are JSON arrays


@pytest.mark.parametrize(
    ("option", "fragment"),
    [
        ({"a": float("nan")}, "not finite"),
        ({"data": [1.0, float("inf")]}, "option.data[1]"),
        ({"a": np.int64(3)}, "int64"),
        ({"a": np.array([1, 2])}, "ndarray"),
        ({"a": lambda v: v}, "function"),
        ({"a": {1, 2}}, "set"),
        ({1: "x"}, "keys must be str"),
        ({"__proto__": {"x": 1}}, "JavaScript merge"),
        ({"constructor": {}}, "JavaScript merge"),
        ({"$eval": "1"}, "'$' key"),
        ({"a": {"$fmt": "pct1", "extra": 1}}, "only key"),
        ({"a": {"$fmt": "no_such_formatter"}}, "formatter names"),
        ({"a": {"$fmt": 3}}, "formatter names"),
        ({"tooltip": {"formatter": "<img src=x onerror=1>"}}, "markup"),
        ({"series": [{"type": "scatter", "data": [[1, 2]]}]}, "large: true"),
        ({"series": [{"type": "effectScatter", "large": False}]}, "large: true"),
        ({"aria": {"decal": {"show": True}}}, "default decal"),
        ({"aria": {"decal": {"show": 1}}}, "default decal"),
        # Sinks found by the security review: the browser would navigate to, or fetch, a URL the data chose.
        ({"title": {"link": "javascript:alert(1)"}}, "navigate to or fetch"),
        ({"title": {"sublink": "https://t.example"}}, "navigate to or fetch"),
        ({"title": {"target": "blank"}}, "navigate to or fetch"),
        (
            {"series": [{"data": [{"name": "x", "link": "https://t.example"}]}]},
            "navigate to or fetch",
        ),
        (
            {"graphic": [{"type": "image", "style": {"image": "http://t/p.png"}}]},
            "navigate to or fetch",
        ),
        (
            {"legend": {"data": [{"name": "a", "icon": "image://http://t/p.png"}]}},
            "fetch",
        ),
        ({"tooltip": {"extraCssText": "background:url(http://t/p.png)"}}, "fetch"),
        (
            {"series": [{"type": "line", "symbol": "image://http://t/p.png"}]},
            "image symbol",
        ),
        ({"series": [{"type": "line", "symbol": "IMAGE://x"}]}, "image symbol"),
        ({"markLine": {"symbol": ["none", "image://http://t/p.png"]}}, "image symbol"),
        # A function as the tooltip template would be set as HTML; valueFormatter is encoded by ECharts.
        ({"tooltip": {"formatter": {"$fmt": "compact"}}}, "rendered as HTML"),
        (
            {"series": [{"tooltip": {"formatter": {"$fmt": "pct1"}}}]},
            "rendered as HTML",
        ),
        ({"data": ["x" * 2001]}, "longer than"),
        ({"x" * 2001: 1}, "key longer than"),
        ({"data": [2**60]}, "2**53"),
        (
            {"series": [{"type": np.array([1, 2])}]},
            "ndarray",
        ),  # an OptionError, not numpy's ValueError
    ],
)
def test_an_option_that_is_not_plain_safe_json_is_refused_with_a_path(
    option: object, fragment: str
) -> None:
    with pytest.raises(OptionError) as caught:
        validate_option(option)
    assert fragment in str(caught.value)


def test_an_error_names_a_path_and_a_type_but_never_a_value() -> None:
    secret = "ACME-SECRET-7731"
    attempts: list[object] = [
        {"series": [{"data": [1, float("nan")], "name": secret}]},
        {"series": [{"name": secret, "data": [np.int64(1)]}]},
        {"tooltip": {"formatter": f"<b>{secret}</b>"}},
        {"label": {"$fmt": secret}},
        {secret: {"__proto__": 1}},
        {"series": [{"type": "scatter", "name": secret}]},
    ]
    for option in attempts:
        with pytest.raises(OptionError) as caught:
            validate_option(option)
        assert secret not in str(caught.value), option
    with pytest.raises(OptionError) as caught:
        validate_option({"series": [{"data": [1, float("nan")]}]})
    assert "option.series[0].data[1]" in str(caught.value)


def test_a_runaway_tree_is_refused_rather_than_walked_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deep: Any = {}
    cursor = deep
    for _ in range(base_option_builder.MAX_DEPTH + 2):
        cursor["n"] = {}
        cursor = cursor["n"]
    with pytest.raises(OptionError, match="deeper"):
        validate_option(deep)
    monkeypatch.setattr(base_option_builder, "MAX_NODES", 10)
    with pytest.raises(OptionError, match="nodes"):
        validate_option({"data": list(range(50))})


def test_fmt_builds_a_reference_and_refuses_an_unknown_name_without_echoing_it() -> (
    None
):
    assert fmt("pct1") == {"$fmt": "pct1"}
    with pytest.raises(OptionError) as caught:
        fmt("ACME-SECRET-7731")  # a builder that passed a column name by mistake
    assert "ACME-SECRET-7731" not in str(caught.value)


def test_a_valid_option_survives_a_json_round_trip_unchanged() -> None:
    option = _plain()
    assert json.loads(json.dumps(option, allow_nan=False)) == option


# ----------------------------------------------------------------------------- the registry rule


class _Builder(BaseOptionBuilder):
    @classmethod
    def build_option(cls, dataframe: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
        return {"series": [{"type": "bar", "data": [len(dataframe)]}]}


def _fit(*renderers: Renderer) -> ChartFit:
    return ChartFit(
        "echarts_probe",
        (ChartIntent.COMPARISON,),
        (Slot("category_column", (SemanticRole.DIMENSION,)),),
        renderers,
    )


def test_a_fit_listing_echarts_needs_an_option_builder_and_the_reverse() -> None:
    with pytest.raises(ServiceError, match="no option_builder"):
        register_chart(
            "echarts_probe",
            ChartRegistration(
                BarChart,
                ("category_column",),
                fit=_fit(Renderer.ECHARTS, Renderer.PLOTLY),
            ),
        )
    with pytest.raises(ServiceError, match="nothing could ever select"):
        register_chart(
            "echarts_probe",
            ChartRegistration(
                BarChart,
                ("category_column",),
                fit=_fit(Renderer.PLOTLY),
                option_builder=_Builder,
            ),
        )
    with pytest.raises(ServiceError, match="nothing could ever select"):
        register_chart(
            "echarts_probe",
            ChartRegistration(BarChart, ("category_column",), option_builder=_Builder),
        )
    assert "echarts_probe" not in list_charts()


def test_a_ported_chart_registers_and_its_builder_is_reachable() -> None:
    register_chart(
        "echarts_probe",
        ChartRegistration(
            BarChart,
            ("category_column",),
            fit=_fit(Renderer.ECHARTS, Renderer.PLOTLY),
            option_builder=_Builder,
        ),
    )
    try:
        builder = option_builder_for("echarts_probe")
        assert builder is _Builder
        option = builder.build_option(pd.DataFrame({"x": [1, 2, 3]}))
        validate_option(option)
        assert option["series"][0]["data"] == [3]
    finally:
        unregister_chart("echarts_probe")


def test_a_chart_without_a_port_has_no_builder_and_an_unknown_one_is_an_error() -> None:
    assert option_builder_for("bar") is None
    with pytest.raises(ServiceError):
        option_builder_for("not_a_chart")


def test_every_builtin_lists_echarts_exactly_when_it_has_an_option_builder() -> None:
    for name, registration in list_charts().items():
        assert registration.fit is not None
        listed = Renderer.ECHARTS in registration.fit.renderers
        assert listed == (registration.option_builder is not None), name


def test_an_option_builder_cannot_be_instantiated_without_build_option() -> None:
    class Incomplete(BaseOptionBuilder):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


# --------------------------------------------------------- the formatter names agree with the SPA


def test_the_formatter_names_are_exactly_the_ones_the_spa_implements() -> None:
    source = (ROOT / "apps/web/src/charts/formatters.ts").read_text(encoding="utf-8")
    block = re.search(
        r"export const FORMATTER_NAMES\s*=\s*\[(.*?)\]\s*as const", source, re.DOTALL
    )
    assert (
        block
    ), "apps/web/src/charts/formatters.ts must export FORMATTER_NAMES = [...] as const"
    names = set(re.findall(r"'([a-z0-9_]+)'", block.group(1)))
    assert names == set(FORMATTER_NAMES)
