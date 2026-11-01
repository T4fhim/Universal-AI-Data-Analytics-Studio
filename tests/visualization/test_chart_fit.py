# File: tests/visualization/test_chart_fit.py
"""``ChartFit`` (chart intelligence CI.2): every built-in declares one, and it cannot drift from the chart.

The point of a fit living in the registration is that adding a chart means adding its selection metadata in
the same place; these tests are what makes that true rather than hoped. They pin the fit against the
registration (every field of the AI tool schema is bindable by some slot; a required field has a required
slot; a list field takes many columns), against the builders' own constants (the fold limit of a bar, the
panel cap of a pie, the matrix cap of a heatmap, the exactly-two series of a paired bar, the allowed
``variant`` literals), and check the construction-time validation and the variant merge rule that CI.3
will rely on.
"""

from __future__ import annotations

import pytest

from uadas_core.analysis.fingerprint import SemanticRole
from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization import (
    advanced_charts,
    categorical_charts,
    continuous_charts,
)
from uadas_core.visualization.categorical_charts import BarChart
from uadas_core.visualization.chart_fit import (
    HARD_NEEDS,
    SOFT_NEEDS,
    Bounds,
    ChartFit,
    ChartIntent,
    Need,
    Renderer,
    Slot,
    Variant,
)
from uadas_core.visualization.chart_registry import (
    ChartRegistration,
    fit_for,
    list_charts,
    list_fits,
    register_chart,
    unregister_chart,
)

# Where each builder keeps the literals a spec may pass, and which of them are the plain default (so not a
# declared variant). ``bar`` / ``pie`` / ``line`` / ``heatmap`` accept ``variant``; a scatter's ``frontier``
# takes a corner; a KPI's ``line`` look is what no variant gives you.
_ALLOWED_LITERALS = {
    "bar": ("variant", categorical_charts._BAR_VARIANTS, ()),
    "pie": ("variant", categorical_charts._PIE_VARIANTS, ()),
    "line": ("variant", continuous_charts._LINE_VARIANTS, ()),
    "scatter": ("frontier", continuous_charts._FRONTIERS, ()),
    "heatmap": ("variant", advanced_charts._HEATMAP_VARIANTS, ()),
    "kpi": ("variant", advanced_charts._KPI_VARIANTS, ("line",)),
}
# Literal fields that name a *value of a column* (not a look), so no shape of data can recommend them.
_NOT_RECOMMENDABLE = {"bar": {"incomplete_from"}, "scatter": {"pin"}}


def _all_slots(fit: ChartFit) -> list[Slot]:
    return list(fit.slots) + [s for v in fit.variants for s in v.slots]


# ------------------------------------------------------------------------------ the registry


def test_every_builtin_chart_declares_a_fit_that_names_it() -> None:
    charts = list_charts()
    assert len(charts) == 14
    for name, registration in charts.items():
        assert registration.fit is not None, f"{name} has no ChartFit"
        assert registration.fit.chart == name


def test_the_fit_list_is_exactly_the_charts_that_declare_one() -> None:
    assert set(list_fits()) == {n for n, r in list_charts().items() if r.fit}
    assert fit_for("bar") is list_charts()["bar"].fit


def test_a_chart_without_a_fit_is_never_listed_but_still_registered() -> None:
    register_chart("no_fit_probe", ChartRegistration(BarChart, ("category_column",)))
    try:
        assert "no_fit_probe" in list_charts()
        assert fit_for("no_fit_probe") is None
        assert "no_fit_probe" not in list_fits()
    finally:
        unregister_chart("no_fit_probe")


def test_asking_for_the_fit_of_an_unknown_chart_is_an_error_not_none() -> None:
    with pytest.raises(ServiceError):
        fit_for("not_a_chart")


# ------------------------------------------------------- the fit agrees with the registration


@pytest.mark.parametrize("name", sorted(list_charts()))
def test_every_field_of_the_ai_tool_schema_can_be_bound_by_some_slot(
    name: str,
) -> None:
    registration = list_charts()[name]
    assert registration.fit is not None
    fields = set(registration.required_fields) | set(registration.optional_fields)
    bound = {s.field for s in _all_slots(registration.fit) if s.field is not None}
    assert fields == bound, f"{name}: fields {fields ^ bound} are in one side only"


# A fit may be STRICTER than the builder (require what the builder leaves optional), never looser. Each is a
# recommendation precondition the builder cannot express: a line over the row index is not a trend, and the
# pivot heatmap is the only heatmap mode a spec can bind (the correlation mode takes no column parameter).
_STRICTER_THAN_THE_BUILDER = {
    ("line", "x_column"),
    ("heatmap", "row_column"),
    ("heatmap", "column_column"),
}


@pytest.mark.parametrize("name", sorted(list_charts()))
def test_a_required_field_has_a_required_slot_and_a_fit_is_only_ever_stricter(
    name: str,
) -> None:
    registration = list_charts()[name]
    assert registration.fit is not None
    base = {s.field: s for s in registration.fit.slots}
    for field_name in registration.required_fields:
        assert field_name in base, f"{name}: required {field_name} has no base slot"
        assert base[field_name].required, f"{name}.{field_name} must stay required"
    for field_name, slot in base.items():
        if slot.required and field_name not in registration.required_fields:
            assert (name, field_name) in _STRICTER_THAN_THE_BUILDER, (
                f"{name}.{field_name} is required by the fit but optional in the builder: "
                f"declare why in _STRICTER_THAN_THE_BUILDER"
            )


@pytest.mark.parametrize("name", sorted(list_charts()))
def test_a_list_field_takes_many_columns_and_only_a_list_field_does(
    name: str,
) -> None:
    registration = list_charts()[name]
    assert registration.fit is not None
    for slot in _all_slots(registration.fit):
        assert (slot.max_count > 1) == (
            slot.field in registration.list_fields
        ), f"{name}.{slot.field}"


# ------------------------------------------------------------ variants and the builders' literals


@pytest.mark.parametrize("name", sorted(_ALLOWED_LITERALS))
def test_the_declared_variant_literals_are_exactly_what_the_builder_accepts(
    name: str,
) -> None:
    parameter, allowed, defaults = _ALLOWED_LITERALS[name]
    fit = fit_for(name)
    assert fit is not None
    declared = {
        value
        for variant in fit.variants
        for param, value in variant.literals
        if param == parameter
    }
    assert declared == set(allowed) - set(
        defaults
    ), f"{name}: a variant literal the builder does not accept, or one it accepts that no variant declares"


@pytest.mark.parametrize("name", sorted(list_charts()))
def test_every_literal_a_variant_sets_is_a_registered_literal_field(
    name: str,
) -> None:
    registration = list_charts()[name]
    assert registration.fit is not None
    used = {param for v in registration.fit.variants for param, _ in v.literals}
    assert used <= set(registration.literal_fields)
    # Every literal field is either declared by some variant or deliberately not recommendable.
    unaccounted = (
        set(registration.literal_fields) - used - _NOT_RECOMMENDABLE.get(name, set())
    )
    assert not unaccounted, f"{name}: literal fields no variant declares: {unaccounted}"


def test_the_fit_limits_match_the_constants_the_builders_enforce() -> None:
    bar = fit_for("bar")
    pie = fit_for("pie")
    heatmap = fit_for("heatmap")
    radar = fit_for("radar")
    assert bar and pie and heatmap and radar
    category = bar.slots[0]
    assert category.distinct.sweet_max == categorical_charts._MAX_CATEGORIES
    panels = pie.variant("panels").slots[0]
    assert panels.distinct.hard_max == categorical_charts._MAX_PANELS
    for slots in (
        heatmap.slots_for(None),
        heatmap.slots_for(heatmap.variant("numbers")),
        heatmap.slots_for(heatmap.variant("grid")),
    ):
        axes = [s for s in slots if s.field in ("row_column", "column_column")]
        assert len(axes) == 2
        assert all(s.distinct.hard_max == advanced_charts._MAX_MATRIX for s in axes)
    values = next(s for s in radar.slots if s.field == "value_columns")
    assert values.min_count == 3  # RadarChart.build refuses fewer than 3 axes
    paired = next(s for s in bar.variant("paired").slots if s.field == "series_column")
    assert (paired.distinct.hard_min, paired.distinct.hard_max) == (2, 2)


# ----------------------------------------------------------------------- the merge rule (CI.3)


def test_a_variant_slot_replaces_the_chart_slot_of_the_same_field() -> None:
    bar = fit_for("bar")
    assert bar is not None
    plain = {s.field: s for s in bar.slots_for(None)}
    stacked = {s.field: s for s in bar.slots_for(bar.variant("stacked"))}
    assert Need.ADDITIVE not in plain["value_column"].needs
    assert Need.ADDITIVE in stacked["value_column"].needs
    assert set(stacked) == {"category_column", "value_column", "series_column"}
    # ... and a series bar lets its category be a time axis, which the plain bar (sorted by value) cannot.
    assert SemanticRole.TIME not in plain["category_column"].roles
    assert SemanticRole.TIME in stacked["category_column"].roles


def test_a_variant_that_tightens_the_axes_keeps_the_other_slots() -> None:
    heatmap = fit_for("heatmap")
    assert heatmap is not None
    plain = {s.field: s for s in heatmap.slots_for(None)}
    numbers = {s.field: s for s in heatmap.slots_for(heatmap.variant("numbers"))}
    assert set(plain) == set(numbers) == {"row_column", "column_column", "value_column"}
    assert numbers["row_column"].distinct.sweet_max == 12
    assert numbers["value_column"] is plain["value_column"]


def test_a_variant_overrides_intents_and_rows_only_when_it_declares_them() -> None:
    bar = fit_for("bar")
    scatter = fit_for("scatter")
    assert bar and scatter
    assert bar.intents_for(None) == (ChartIntent.COMPARISON,)
    assert bar.intents_for(bar.variant("stacked")) == (ChartIntent.COMPOSITION,)
    assert bar.intents_for(bar.variant("grouped")) == (ChartIntent.COMPARISON,)
    assert scatter.rows_for(None) == (8, None)
    assert scatter.rows_for(scatter.variant("labelled")) == (8, 40)
    assert scatter.rows_for(scatter.variant("frontier_upper_left")) == (20, None)


def test_looks_that_are_a_matter_of_taste_are_only_offered_on_request() -> None:
    explicit = {
        (name, v.name)
        for name, fit in list_fits().items()
        for v in fit.variants
        if v.explicit
    }
    assert ("kpi", "lollipop") in explicit
    assert ("scatter", "frontier_lower_right") in explicit
    assert ("bar", "stacked") not in explicit and ("pie", "donut") not in explicit


def test_an_unknown_variant_is_a_key_error() -> None:
    bar = fit_for("bar")
    assert bar is not None
    with pytest.raises(KeyError):
        bar.variant("no_such_variant")


# ---------------------------------------------------------------------------- the data shape


def test_the_triggers_of_the_use_case_map_are_declared() -> None:
    """A few of plan section 3.5's rows, as declared: the shapes CI.3 will turn into hard constraints."""
    pie, hist, funnel, candle, waterfall, treemap = (
        fit_for(n)
        for n in ("pie", "histogram", "funnel", "candlestick", "waterfall", "treemap")
    )
    assert pie and hist and funnel and candle and waterfall and treemap
    assert pie.slots[0].distinct.hard_max == 6  # no pie over more than 6 slices
    assert Need.NON_NEGATIVE in pie.slots[1].needs
    assert hist.min_rows == 30 and hist.slots[0].distinct.hard_min == 5
    assert Need.NON_INCREASING in funnel.slots[1].needs and funnel.max_rows == 12
    ohlc = {s.field: s for s in candle.slots}
    for field_name in ("open_column", "high_column", "low_column", "close_column"):
        assert ohlc[field_name].hint_required
    assert not ohlc["volume_column"].required
    assert {Need.ADDITIVE, Need.SIGNED} <= waterfall.slots[1].needs
    path = treemap.slots[0]
    assert (path.min_count, path.max_count, path.nested) == (2, 2, True)
    assert path.distinct.hard_max == 200
    assert treemap.slots[1].needs == {Need.NON_NEGATIVE, Need.ADDITIVE}


def test_every_need_is_either_hard_or_soft_and_never_both() -> None:
    assert set(Need) == HARD_NEEDS | SOFT_NEEDS
    assert not HARD_NEEDS & SOFT_NEEDS
    # Hard means decidable from a fingerprint (negative_share, row_order); the rest is judgement.
    assert {Need.NON_NEGATIVE, Need.NON_INCREASING} == HARD_NEEDS


def test_a_chart_that_draws_one_mark_per_row_needs_a_unique_label() -> None:
    unique = {
        (name, slot.field)
        for name, fit in list_fits().items()
        for slot in _all_slots(fit)
        if slot.unique
    }
    assert unique == {
        ("line", "x_column"),
        ("radar", "category_column"),
        ("waterfall", "category_column"),
        ("funnel", "stage_column"),
        ("candlestick", "x_column"),
    }


def test_the_line_needs_an_axis_and_a_series_bar_may_have_a_time_axis() -> None:
    line = fit_for("line")
    assert line is not None
    x = next(s for s in line.slots if s.field == "x_column")
    assert x.required and x.unique
    # The builder leaves the axis optional; the fit is the stricter of the two.
    assert "x_column" not in list_charts()["line"].required_fields


def test_the_correlation_heatmap_is_not_declared_until_a_spec_can_bind_its_columns() -> (
    None
):
    heatmap = fit_for("heatmap")
    assert heatmap is not None
    assert heatmap.intents == (ChartIntent.PATTERN,)
    assert all(
        s.field in ("row_column", "column_column", "value_column")
        for s in heatmap.slots
    )


def test_every_intent_is_answered_by_some_built_in() -> None:
    answered = {i for fit in list_fits().values() for i in fit.intents}
    for fit in list_fits().values():
        for variant in fit.variants:
            answered |= set(variant.intents)
    assert answered == set(ChartIntent)


# ----------------------------------------------------------------------- construction checks


def _slot() -> Slot:
    return Slot("value_column", (SemanticRole.MEASURE,))


@pytest.mark.parametrize(
    "build",
    [
        lambda: Bounds(hard_min=5, sweet_min=3),
        lambda: Bounds(sweet_min=8, sweet_max=4),
        lambda: Bounds(hard_min=-1),
        lambda: Bounds(sweet_max=20, hard_max=10),
        lambda: Slot("x", ()),
        lambda: Slot("", (SemanticRole.MEASURE,)),
        lambda: Slot("x", (SemanticRole.MEASURE,), nested=True),
        lambda: Slot("x", (SemanticRole.MEASURE,), min_count=0),
        lambda: Slot("x", (SemanticRole.MEASURE,), min_count=3, max_count=2),
        lambda: Slot("x", (SemanticRole.MEASURE,), hint_required=True),
        lambda: Variant(""),
        lambda: Variant("v", literals=(("a", "1"), ("a", "2"))),
        lambda: Variant("v", slots=(_slot(), _slot())),
        lambda: ChartFit("", (ChartIntent.TREND,), (_slot(),), (Renderer.PLOTLY,)),
        lambda: ChartFit("c", (), (_slot(),), (Renderer.PLOTLY,)),
        lambda: ChartFit("c", (ChartIntent.TREND,), (_slot(),), ()),
        lambda: ChartFit(
            "c", (ChartIntent.TREND,), (_slot(),), (Renderer.PLOTLY, Renderer.PLOTLY)
        ),
        lambda: ChartFit(
            "c", (ChartIntent.TREND,), (_slot(), _slot()), (Renderer.PLOTLY,)
        ),
        lambda: ChartFit(
            "c",
            (ChartIntent.TREND,),
            (_slot(),),
            (Renderer.PLOTLY,),
            variants=(Variant("v"), Variant("v")),
        ),
        lambda: ChartFit(
            "c", (ChartIntent.TREND,), (_slot(),), (Renderer.PLOTLY,), min_rows=0
        ),
        lambda: ChartFit(
            "c",
            (ChartIntent.TREND,),
            (_slot(),),
            (Renderer.PLOTLY,),
            min_rows=10,
            max_rows=5,
        ),
    ],
)
def test_a_malformed_declaration_fails_when_it_is_built(build: object) -> None:
    with pytest.raises(ValueError):
        build()  # type: ignore[operator]


def test_a_well_formed_declaration_builds() -> None:
    fit = ChartFit(
        "c",
        (ChartIntent.TREND,),
        (_slot(),),
        (Renderer.ECHARTS, Renderer.PLOTLY),
        variants=(Variant("v", slots=(Slot("other", (SemanticRole.TIME,)),)),),
    )
    assert fit.renderers[0] is Renderer.ECHARTS
    assert [s.field for s in fit.slots_for(fit.variant("v"))] == [
        "value_column",
        "other",
    ]
