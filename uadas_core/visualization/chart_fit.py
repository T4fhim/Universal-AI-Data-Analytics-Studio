# File: uadas_core/visualization/chart_fit.py
"""Declarative selection metadata for a chart: what question it answers and what data it needs (CI.2).

``plans/phase-4-chart-intelligence.md`` section 3.3. Before this, the only chart metadata in
:class:`~uadas_core.visualization.chart_registry.ChartRegistration` was field *names*, so the recommender
(:mod:`~uadas_core.visualization.chart_recommender`) hardcoded its own list of charts and the data shape
that triggers each: the "registry plus a separately hardcoded consumer" gap CLAUDE.md warns about. A
:class:`ChartFit` is the same chart's selection metadata, declared in the same ``ChartRegistration`` call, so
adding a chart means adding its fit in the same place and a test fails when the two disagree
(``tests/visualization/test_chart_fit.py``).

What a fit says, and in which vocabulary. It is written in terms of the fingerprint
(:mod:`~uadas_core.analysis.fingerprint`), never the data: a :class:`Slot` names the builder parameter it
fills, the :class:`~uadas_core.analysis.fingerprint.SemanticRole` a column may have, how many columns and how
many distinct values it takes (:class:`Bounds`: a hard limit that makes a candidate invalid, and a sweet spot
the scorer rewards), and the properties the values need (:class:`Need`). :class:`Variant` is a way of
drawing the same chart that changes the question it answers or what it needs (``stacked``, ``donut``,
``dual_axis``, ...). ``renderers`` lists the renderers that can draw it **today**, in preference order: every
built-in is Plotly-only until a CI.8 port wave passes its golden parity, and that wave adds ``echarts``.

What a fit deliberately is not: a scorer (CI.3 turns these declarations and a fingerprint into ranked
candidates), the intent of a dataset (stage 2, which lives beside the recommender because ``visualization``
sits above ``analysis``), or a promise that a chart is *good* for the data: the numbers here are starting
values that CI.3 tunes against the gold set.

Why the declarations are validated at construction: a fit is plugin-writable (``ChartRegistration.fit`` is
optional, a plugin chart without one is simply never recommended), so a malformed one must fail when it is
built, with a message naming the problem, not when the recommender meets it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from uadas_core.analysis.fingerprint import SemanticRole


class ChartIntent(StrEnum):
    """The question a chart answers. ``GEO`` and ``FORECAST`` are reserved, not built (plan section 3.2)."""

    TREND = "trend"
    COMPARISON = "comparison"
    COMPOSITION = "composition"
    DISTRIBUTION = "distribution"
    RELATIONSHIP = "relationship"
    DEVIATION = "deviation"
    FLOW = "flow"
    PROFILE = "profile"
    SUMMARY = "summary"
    PATTERN = "pattern"


class Renderer(StrEnum):
    """A renderer that can draw a chart. Closed: the client never picks one from user input.

    ``d3`` is reserved for the first chart neither library draws (CI.10) and is not a member yet.
    """

    ECHARTS = "echarts"
    PLOTLY = "plotly"
    # (The ``component`` renderer of plan section 3.7 joins when the first chart lists it: CI.8e's KPI.)


class Need(StrEnum):
    """A property the values bound to a slot must have for the chart to be honest.

    A need is either *hard*, decidable from a fingerprint and so a constraint that makes a candidate
    invalid (:data:`HARD_NEEDS`), or *soft*, a judgement about what the numbers mean that no fingerprint can
    settle, so the scorer treats it as evidence (:data:`SOFT_NEEDS`). Declaring a soft need is still worth
    it: it is what the scorer rewards and what the reason string explains.
    """

    NON_NEGATIVE = "non_negative"  # no value below zero (a pie slice, a treemap area)
    NON_INCREASING = (
        "non_increasing"  # in row order each value is at most the one before (a funnel)
    )
    ADDITIVE = "additive"  # the values sum to something meaningful (a share, a total); a rate does not
    ORDERED = "ordered"  # the rows have a meaningful order (funnel stages, waterfall steps, a time axis)
    SIGNED = "signed"  # both increases and decreases are expected (a waterfall)


# Hard: ``distribution.negative_share == 0`` and the column's ``row_order`` (exact fingerprints only: a
# sample cannot see a negative row or the order of the file, so on a sampled one the dataset gate at accept
# time is the backstop). Soft: nothing in the data says whether a measure is a count or a rate, or whether the
# row order of a category column means anything.
HARD_NEEDS = frozenset({Need.NON_NEGATIVE, Need.NON_INCREASING})
SOFT_NEEDS = frozenset({Need.ADDITIVE, Need.ORDERED, Need.SIGNED})


@dataclass(frozen=True, slots=True)
class Bounds:
    """Limits on the number of distinct values in a column.

    ``hard_min`` / ``hard_max`` make a candidate invalid (score 0, never shown); ``sweet_min`` /
    ``sweet_max`` are where the chart reads best, which the scorer rewards but does not require. ``None``
    means unbounded on that side. ``hard_min`` 0 imposes nothing.

    Distinct values are counted the way the **builder** draws them: it makes a ``(missing)`` category of the
    nulls of a categorical column, while a fingerprint's ``distinct`` counts non-null values only, so a
    consumer compares ``distinct + (1 if missing_share > 0 else 0)`` for a categorical slot.
    """

    hard_min: int = 0
    hard_max: int | None = None
    sweet_min: int | None = None
    sweet_max: int | None = None

    def __post_init__(self) -> None:
        ladder = [
            v
            for v in (self.hard_min, self.sweet_min, self.sweet_max, self.hard_max)
            if v is not None
        ]
        if self.hard_min < 0 or ladder != sorted(ladder):
            raise ValueError(
                "Bounds must satisfy 0 <= hard_min <= sweet_min <= sweet_max <= hard_max "
                f"(got {self})."
            )


@dataclass(frozen=True, slots=True)
class Slot:
    """One place a chart takes columns.

    No column fills two slots of one candidate (the builders refuse a pie whose panel column is its category,
    a line whose second axis is its first, a pivot whose rows and columns are the same column).

    Attributes:
        field: The builder parameter this fills: a name in the registration's required or optional fields.
        roles: The semantic roles a bound column may have, any one of them. This, not
            :attr:`~uadas_core.analysis.fingerprint.ColumnFingerprint.chartable`, is the authority for what
            may fill *this* slot (a radar's entity label and a scatter's point label take identifiers and text).
        required: Whether a recommendation needs the slot filled. A registration-required field must be
            required here; a fit may be *stricter* than the builder (a line whose ``x_column`` the builder
            leaves optional is only recommended with one, because a line over the row index is not a trend).
        min_count / max_count: How many columns fill it. 1 and 1 is a single column; a list field
            (``path_columns``, ``value_columns``) allows more, and ``min_count`` > 1 is a hard requirement.
        distinct: The bounds on each bound column's distinct values (see :class:`Bounds`).
        needs: Properties each bound column's values must have (see :class:`Need` for hard and soft).
        unique: The column must hold one distinct value per non-null row. A chart that draws one mark per row
            without aggregating (a funnel, a waterfall, a radar, a candlestick, a line) is a zig-zag or a
            repeated bar when its label or axis repeats. Decided as ``distinct == non-null rows`` on an exact
            fingerprint; the ``unique_key`` cardinality class needs 20 rows and so misses small frames.
        nested: The bound columns, in order, are a chain in which each determines the next (a treemap's
            country -> region), decided from the fingerprint's ``hierarchies``.
        name_hints: Lower-case tokens a column *name* should contain (``("open",)``), matched as whole tokens
            of the name (:func:`~uadas_core.analysis.fingerprint.name_tokens`), never as substrings (``low`` is
            not in ``flow``). A fingerprint cannot tell an open price from any other measure, so a slot that
            is meaningless without its name says so here instead of the recommender hardcoding the chart.
        hint_required: Whether a name hint is a hard requirement (a candlestick) or only evidence.
    """

    field: str
    roles: tuple[SemanticRole, ...]
    required: bool = True
    min_count: int = 1
    max_count: int = 1
    distinct: Bounds = Bounds()
    needs: frozenset[Need] = frozenset()
    unique: bool = False
    nested: bool = False
    name_hints: tuple[str, ...] = ()
    hint_required: bool = False

    def __post_init__(self) -> None:
        if not self.field:
            raise ValueError("A slot must name the builder parameter it fills.")
        if not self.roles:
            raise ValueError(f"Slot {self.field!r} must accept at least one role.")
        if self.nested and self.min_count < 2:
            raise ValueError(
                f"Slot {self.field!r}: a nested slot needs min_count >= 2."
            )
        if self.min_count < 1 or self.max_count < self.min_count:
            raise ValueError(
                f"Slot {self.field!r}: need 1 <= min_count <= max_count "
                f"(got {self.min_count}..{self.max_count})."
            )
        if self.hint_required and not self.name_hints:
            raise ValueError(f"Slot {self.field!r}: hint_required needs name_hints.")


@dataclass(frozen=True, slots=True)
class Variant:
    """A way of drawing the chart that changes what it answers or needs.

    A variant's ``slots`` are bound **in addition to** the chart's, and a slot naming a field the chart
    already has *replaces* it (that is how ``stacked`` tightens ``value_column`` to non-negative and
    additive, and how a series bar lets its category be a time axis). :meth:`ChartFit.slots_for` applies the
    rule so no consumer reimplements it. A candidate is exactly one variant (or none), so two variants never
    combine (a builder refuses a donut with panels, an area under two axes).

    Attributes:
        name: Unique within the chart.
        literals: ``(parameter, value)`` pairs a spec sets to get this look (``("variant", "donut")``).
        slots: See above.
        intents: The questions this variant answers; empty means the chart's own.
        explicit: Offer it only when the user asks. Nothing in the data says which Pareto corner is "best" or
            which KPI look a reader prefers, so those are not recommended unprompted.
        min_rows / max_rows: Override the chart's row bounds when set (labels on a scatter stop being
            readable past a few dozen points).
    """

    name: str
    literals: tuple[tuple[str, str], ...] = ()
    slots: tuple[Slot, ...] = ()
    intents: tuple[ChartIntent, ...] = ()
    explicit: bool = False
    min_rows: int | None = None
    max_rows: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("A variant needs a name.")
        _require_unique(
            [k for k, _ in self.literals], f"variant {self.name!r} literals"
        )
        _require_unique([s.field for s in self.slots], f"variant {self.name!r} slots")


@dataclass(frozen=True, slots=True)
class ChartFit:
    """The selection metadata of one registered chart. See the module docstring.

    Attributes:
        chart: The registry key this belongs to. Redundant with where it is declared, on purpose: pasting
            one chart's fit into another's registration fails the consistency test instead of silently
            recommending the wrong chart.
        intents: The questions the plain chart (no variant) answers.
        slots: The columns the plain chart takes.
        renderers: The renderers that can draw it today, preferred first. Never empty.
        min_rows / max_rows: The dataset sizes it is worth drawing at.
        variants: The other ways to draw it.
    """

    chart: str
    intents: tuple[ChartIntent, ...]
    slots: tuple[Slot, ...]
    renderers: tuple[Renderer, ...]
    min_rows: int = 1
    max_rows: int | None = None
    variants: tuple[Variant, ...] = ()

    def __post_init__(self) -> None:
        if not self.chart:
            raise ValueError("A ChartFit must name its chart.")
        if not self.intents:
            raise ValueError(f"{self.chart}: a fit must answer at least one intent.")
        if not self.renderers:
            raise ValueError(
                f"{self.chart}: a fit must list at least one renderer (a chart nothing can draw "
                f"is never a valid candidate)."
            )
        _require_unique(list(self.renderers), f"{self.chart} renderers")
        _require_unique([s.field for s in self.slots], f"{self.chart} slots")
        _require_unique([v.name for v in self.variants], f"{self.chart} variants")
        if self.min_rows < 1 or (
            self.max_rows is not None and self.max_rows < self.min_rows
        ):
            raise ValueError(
                f"{self.chart}: need 1 <= min_rows <= max_rows (got {self.min_rows}..{self.max_rows})."
            )

    def variant(self, name: str) -> Variant:
        """The variant called ``name``.

        Raises:
            KeyError: If the chart has no such variant.
        """
        for candidate in self.variants:
            if candidate.name == name:
                return candidate
        raise KeyError(f"{self.chart} has no variant {name!r}")

    def slots_for(self, variant: Variant | None = None) -> tuple[Slot, ...]:
        """The slots a spec using ``variant`` (or none) has to fill: the merge rule of :class:`Variant`."""
        if variant is None:
            return self.slots
        replaced = {s.field for s in variant.slots}
        kept = tuple(s for s in self.slots if s.field not in replaced)
        return kept + variant.slots

    def intents_for(self, variant: Variant | None = None) -> tuple[ChartIntent, ...]:
        """The questions answered, with the variant's own intents when it declares any."""
        return (
            variant.intents if variant is not None and variant.intents else self.intents
        )

    def rows_for(self, variant: Variant | None = None) -> tuple[int, int | None]:
        """``(min_rows, max_rows)`` with the variant's overrides applied."""
        if variant is None:
            return self.min_rows, self.max_rows
        return (
            variant.min_rows if variant.min_rows is not None else self.min_rows,
            variant.max_rows if variant.max_rows is not None else self.max_rows,
        )


def _require_unique(values: list[object], what: str) -> None:
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"Duplicate in {what}: {value!r}.")
        seen.add(value)
