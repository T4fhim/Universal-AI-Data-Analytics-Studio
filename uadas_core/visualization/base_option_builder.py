# File: uadas_core/visualization/base_option_builder.py
"""The second output contract of a chart: an ECharts option as plain JSON (chart intelligence, CI.8a).

``plans/phase-4-chart-intelligence.md`` sections 3.7 and 9.4. ECharts is the core renderer, ported one chart
at a time (CI.8 waves); Plotly stays the second renderer and the fallback. A chart that has been ported has
two builders over the same shaped data: :class:`~uadas_core.visualization.base_chart.BaseChart` (a Plotly
figure) and a :class:`BaseOptionBuilder` (an ECharts option). They are **siblings**, not one class with two
methods, so a plugin that only knows ``BaseChart`` is not forced to grow an option builder, and the registry
records which charts have one (``ChartRegistration.option_builder``) and refuses a fit that lists the
``echarts`` renderer without one. Python keeps owning data shaping: the frontend and the LLM never compute a
number a user will read, and both builders of a chart call one shared shaping step so they cannot disagree on
a value (the equivalence test of each port wave checks it).

Why the option must be *plain JSON*. It is sent to the browser and handed to ``setOption``; a Python dict
cannot carry a JS function, and a tenant's data must never become executable code or markup. So:

* only ``dict`` (string keys), ``list``, ``str``, ``int``, ``bool``, ``None`` and finite ``float`` appear (a
  numpy ``int64`` is refused here, with its path, instead of failing later inside ``json.dumps``);
* anything that needs a function is a **named formatter**: ``{"$fmt": "pct1"}``. The set of names is closed
  (:data:`FORMATTER_NAMES`) and the SPA owns the implementations (``apps/web/src/charts/formatters.ts``; a test
  keeps the two in step) and swaps each reference for its function before ``setOption``;
* a ``formatter`` *string* may not contain ``<``: an ECharts tooltip renders HTML, so a template with a tag
  would let a column name or cell value inject markup;
* keys that make the browser navigate or fetch are refused (found by the security review of ECharts 6.1): a
  *string* ``link`` / ``sublink`` / ``target`` / ``subtarget`` (ECharts opens it with ``window.open``, which runs a
  ``javascript:`` URL in the app's origin), any ``image`` / ``icon`` / ``src`` / ``url`` / ``extraCssText``, and a
  ``symbol`` of ``image://...`` (the browser would fetch a URL the data chose). ``axisPointer.link`` is a *list*
  that links crosshairs and stays allowed. This is a denylist of known sinks, not an allowlist of ECharts' whole
  vocabulary: an ECharts feature that takes a URL is a new entry here, and the client mirrors the list;
* strings are bounded (:data:`MAX_STRING_LENGTH`) and integers stay within what JavaScript holds exactly
  (:data:`MAX_INT`), so one cell cannot make a payload of megabytes;
* measured traps of CI.0 section 6 are refused rather than rediscovered: a scatter must set ``large: true``
  (plain ECharts is unusable from 100k points), and ``aria.decal.show`` must not be true (it gives every
  series without an explicit decal a default one, so a plain series came out 43 % hatched).

Error messages carry a path (``series[0].data[3]``) and a type name, **never a value**: the value is tenant data
and one server log is shared by every tenant.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

# The name of the one reserved key: ``{"$fmt": "<name>"}`` stands for a formatter function.
FMT_KEY = "$fmt"

# The formatters the SPA implements. Closed on purpose: a name outside it cannot be revived on the client, so
# it is refused here. Adding one means adding it to ``apps/web/src/charts/formatters.ts`` in the same change
# (``tests/visualization/test_base_option_builder.py`` fails until the two agree).
FORMATTER_NAMES: frozenset[str] = frozenset({"pct1", "compact", "thousands", "fixed2"})

# Keys that mean something special to a JavaScript object merge (``setOption`` merges into existing objects).
_FORBIDDEN_KEYS = frozenset({"__proto__", "constructor", "prototype"})

# A runaway builder must not be able to hand the client an unbounded tree.
MAX_DEPTH = 16
MAX_NODES = 1_000_000
# A label, a name or a template is short; anything past this is a bug or an attack, and it would go to the browser.
MAX_STRING_LENGTH = 2_000
# JavaScript holds integers exactly only up to 2**53, and ``json.dumps`` fails past 4,300 digits.
MAX_INT = 2**53

# ECharts keys whose *string* value navigates: ``title.link`` is opened with ``window.open(link, '_self')``,
# which runs a ``javascript:`` URL. (``axisPointer.link`` is a list of objects and is not a URL.)
_NAVIGATION_KEYS = frozenset({"link", "sublink", "target", "subtarget"})
# Keys whose value, of any shape, names a URL to fetch or CSS to apply (a tracking pixel, a remote pattern, an
# overlay): ``symbol: "image://..."``, ``graphic`` images, pattern fills, ``tooltip.extraCssText``.
_FETCH_KEYS = frozenset({"image", "icon", "src", "url", "extraCssText"})


# The keys an error path may show. ECharts' option vocabulary is fixed, but a builder that keyed a dict by a
# column name would put tenant text in a path, and one server log is shared by every tenant, so any other key
# is shown as ``<key>``. Grow this list with the port waves; an unknown key only makes a path less specific.
_PATH_KEYS = frozenset(
    {
        "title", "legend", "grid", "xAxis", "yAxis", "radar", "polar", "tooltip", "axisPointer", "visualMap",
        "dataZoom", "dataset", "series", "aria", "decal", "graphic", "toolbox", "textStyle", "color",
        "backgroundColor", "animation", "type", "name", "data", "source", "dimensions", "encode", "stack",
        "large", "largeThreshold", "show", "formatter", "label", "axisLabel", "axisLine", "axisTick",
        "splitLine", "itemStyle", "lineStyle", "areaStyle", "emphasis", "markPoint", "markLine", "indicator",
        "min", "max", "scale", "symbol", "symbolSize", "smooth", "step", "sampling", "left", "right", "top",
        "bottom", "width", "height", "radius", "center",
    }
)  # fmt: skip


def _path_key(key: object) -> str:
    return key if isinstance(key, str) and key in _PATH_KEYS else "<key>"


class OptionError(ValueError):
    """An option that is not plain, safe JSON. The message names a path and a type, never a value."""


def fmt(name: str) -> dict[str, str]:
    """A reference to the named formatter, ready to place where ECharts expects a function.

    Raises:
        OptionError: If ``name`` is not in :data:`FORMATTER_NAMES`.
    """
    if name not in FORMATTER_NAMES:
        # The name is not echoed: a builder that passed a column name here would put tenant text in the log.
        raise OptionError(
            f"Unknown formatter name (a {type(name).__name__}); the SPA implements {sorted(FORMATTER_NAMES)}."
        )
    return {FMT_KEY: name}


class BaseOptionBuilder(ABC):
    """Abstract base class of a chart's ECharts option builder.

    Stateless and classmethod-only, like every ``Base*`` in this package. A concrete builder is registered next
    to its chart (``ChartRegistration.option_builder``) and its result must pass :func:`validate_option`.
    """

    @classmethod
    @abstractmethod
    def build_option(cls, dataframe: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
        """Build the ECharts option for ``dataframe`` as plain JSON.

        Args:
            dataframe: The data to chart (or its reduced form, once CI.4's reducers exist).
            **kwargs: The same chart parameters the chart's ``BaseChart.build`` takes, so one spec drives
                either renderer.

        Raises:
            ServiceError: As ``BaseChart.build``: a named column is missing or the data cannot be charted.
        """
        raise NotImplementedError


def validate_option(option: object) -> None:
    """Raise :class:`OptionError` unless ``option`` is plain, safe JSON an ECharts client can revive.

    See the module docstring for the rules. The tree is walked once with an explicit stack, and its depth and
    node count are bounded, so a hostile or buggy builder cannot make the check itself expensive.
    """
    nodes = 0
    stack: list[tuple[object, str, int]] = [(option, "option", 0)]
    while stack:
        value, path, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise OptionError(f"option has more than {MAX_NODES} nodes.")
        if depth > MAX_DEPTH:
            raise OptionError(f"{path}: nested deeper than {MAX_DEPTH} levels.")
        if isinstance(value, str):
            if len(value) > MAX_STRING_LENGTH:
                raise OptionError(
                    f"{path}: a string longer than {MAX_STRING_LENGTH} characters."
                )
            continue
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, float):
            if not math.isfinite(value):
                raise OptionError(
                    f"{path}: a float that is not finite (NaN or infinity)."
                )
            continue
        if type(value) is int:  # not a numpy integer, which json.dumps refuses
            if abs(value) > MAX_INT:
                raise OptionError(f"{path}: an integer beyond 2**53.")
            continue
        if isinstance(value, (list, tuple)):
            stack.extend((v, f"{path}[{i}]", depth + 1) for i, v in enumerate(value))
            continue
        if isinstance(value, dict):
            _check_mapping(value, path)
            stack.extend(
                (v, f"{path}.{_path_key(k)}", depth + 1) for k, v in value.items()
            )
            continue
        raise OptionError(f"{path}: {type(value).__name__} is not plain JSON.")


def _check_mapping(mapping: dict[object, object], path: str) -> None:
    for key in mapping:
        if not isinstance(key, str):
            raise OptionError(
                f"{path}: a key of type {type(key).__name__} (keys must be str)."
            )
        # The key itself is not echoed: a builder that keyed a dict by a column name would put tenant text here.
        if len(key) > MAX_STRING_LENGTH:
            raise OptionError(
                f"{path}: a key longer than {MAX_STRING_LENGTH} characters."
            )
        if key in _FORBIDDEN_KEYS:
            raise OptionError(f"{path}: a key that is special to a JavaScript merge.")
        if key in _FETCH_KEYS or (
            key in _NAVIGATION_KEYS and isinstance(mapping[key], str)
        ):
            raise OptionError(
                f"{path}: a key that makes the browser navigate to or fetch a URL (see the module docstring)."
            )
        if key.startswith("$") and key != FMT_KEY:
            raise OptionError(
                f"{path}: a '$' key; only {FMT_KEY!r} is reserved for formatters."
            )
    if FMT_KEY in mapping:
        if len(mapping) != 1:
            raise OptionError(
                f"{path}: {FMT_KEY!r} must be the only key of its object."
            )
        name = mapping[FMT_KEY]
        if not isinstance(name, str) or name not in FORMATTER_NAMES:
            raise OptionError(
                f"{path}.{FMT_KEY}: not one of the formatter names the SPA implements."
            )
    template = mapping.get("formatter")
    if isinstance(template, str) and "<" in template:
        raise OptionError(
            f"{path}.formatter: a template with '<' could inject markup into a tooltip."
        )
    # ``symbol`` is a string, or a list of them (markLine, markPoint, visualMap).
    symbol = mapping.get("symbol")
    symbols = symbol if isinstance(symbol, (list, tuple)) else [symbol]
    if any(isinstance(s, str) and s.lower().startswith("image://") for s in symbols):
        raise OptionError(
            f"{path}.symbol: an image symbol would fetch a URL the data chose."
        )
    # ECharts sets what ``tooltip.formatter`` returns as HTML, so a function may not stand there (a tenant's text
    # would become markup); ``valueFormatter``, axis labels and labels are text or are encoded by ECharts.
    if path.endswith("tooltip") and isinstance(mapping.get("formatter"), dict):
        raise OptionError(
            f"{path}.formatter: a function here would be rendered as HTML; use valueFormatter."
        )
    kind = mapping.get("type")
    if (
        isinstance(kind, str)
        and kind in ("scatter", "effectScatter")
        and mapping.get("large") is not True
    ):
        raise OptionError(
            f"{path}: a scatter series must set large: true (CI.0: unusable from 100k points)."
        )
    # Truthy, not ``is True``: ECharts treats 1 and "true" as on too.
    if path.endswith("aria.decal") and mapping.get("show"):
        raise OptionError(
            f"{path}.show: aria.decal.show gives every series a default decal; set decals explicitly."
        )
