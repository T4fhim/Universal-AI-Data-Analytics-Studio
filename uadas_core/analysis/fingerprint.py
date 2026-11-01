# File: uadas_core/analysis/fingerprint.py
"""A versioned, JSON-serialisable description of what is in a dataset (chart intelligence, CI.1).

Stage 1 of ``plans/phase-4-chart-intelligence.md`` section 3.1: every later stage (intent, candidate
charts, scoring, the render plan) reads this object instead of the data, so the choice of chart is a pure
function of a fingerprint and a goal, and the same input always gives the same answer.

What it holds, per column: a semantic role (:class:`SemanticRole`) with a confidence, a cardinality class,
the distribution shape of a measure, the time structure of a time column and the missing share; per pair of
columns (never all N squared): |Pearson| / |Spearman| for measures and functional dependencies between
dimensions; per dataset: the row and column counts, the grain, the duplicate share and the sample it was
built from. **It holds aggregates and column names, never a cell value** (a minimum or maximum is kept only
for numbers and times), so it may be logged, cached and sent to a worker without carrying tenant rows.

Why a builder over a DataFrame and not over a file: this package is Qt-free and Django-free and must not
parse bytes (``.importlinter``). The caller hands in a pandas frame, which is the whole dataset when it is
small and one *uniformly random, seeded* sample of it when it is not (never the head: a head is the earliest
period of a time series, which is the bug section 2 of the plan found in ``charts_render``). Whole-dataset
facts a sample cannot give (the exact row count, null counts, approximate distinct counts) arrive as
:class:`SourceStats`; ``apps/api/uadas_api/stages/fingerprint.py`` produces them from the Parquet footer and
one streamed DuckDB pass. Without them the fingerprint is built from the sample alone and says so
(``notes``, a lower ``confidence``).

Why it reuses the idea of :func:`~uadas_core.readers.type_inference.find_ambiguous_type_columns` but not
the function: that function counts a missing value as "non-numeric", so a text column of numeric strings
with a few nulls would be reported as a mixed-type column. Here ambiguity is "some but not all *non-null*
values parse as numbers". Layering: ``visualization`` sits above ``analysis`` (``.importlinter``), so the
fingerprint is intent-free; ``ChartIntent`` and stage 2 live in ``visualization/``.

Degradation, not failure: a ``time_budget`` that runs out skips the remaining stages and returns a partial
fingerprint (``partial`` is true, ``confidence`` drops, columns not reached carry the ``not_analysed``
issue); no input -- NaN, infinities, all-null, mixed types, constant, thousands of columns, odd names -- is
allowed to raise. Changing any rule or threshold below changes what the recommender sees, so it bumps
:data:`FINGERPRINT_VERSION` (a cached recommendation set is keyed on it).
"""

from __future__ import annotations

import datetime as _dt
import decimal
import hashlib
import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from functools import partial
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# The stdlib logger, like core/config.py: a log line here carries a stage name and an exception class, never
# a column name or a value (tenant data and secrets share one server log).
_logger = logging.getLogger(__name__)

# Bump on ANY change to a rule, threshold or field below: a cached recommendation set is keyed on it.
FINGERPRINT_VERSION = 2  # 2: ColumnFingerprint.row_order, name_tokens public (CI.2)

# The most rows a fingerprint is computed from. A bigger frame is sampled down (uniformly, seeded).
SAMPLE_ROWS = 100_000

# Cardinality classes (plan section 3.1): constant, low <= 15, medium <= 50, high, unique key.
LOW_CARDINALITY = 15
MEDIUM_CARDINALITY = 50
# A column is a unique key when this share of its non-null values are distinct ...
UNIQUE_KEY_RATIO = 0.95
# ... and there are at least this many of them (below it "all distinct" proves nothing).
MIN_ROWS_FOR_KEY = 20
# Whole-number columns with at most this many levels are ordinal (a 1-5 survey scale), not measures.
ORDINAL_MAX_LEVELS = 7
# ... whose values span at most this much, and which repeat at least this many times per level.
ORDINAL_MAX_RANGE = 10
ORDINAL_MIN_REPEATS = 3
# Distinct text values parsed when looking for a mixed numeric / non-numeric column.
_AMBIGUITY_PROBE = 5_000
# A string is free text above this mean length, or when most values hold a space and most are distinct.
TEXT_MEAN_LENGTH = 40
# Pair statistics are bounded: never more than this many columns of a kind, rows, or reported pairs.
MAX_PAIR_MEASURES = 40
MAX_PAIR_DIMENSIONS = 12
PAIR_ROWS = 20_000
TOP_PAIRS = 20
# Trend and seasonality are reported for the first time column against at most this many measures.
MAX_TIME_SIGNAL_MEASURES = 6
TREND_POINTS = 5_000
MAX_SEASONAL_LAG = 400
MIN_SEASONAL_STRENGTH = 0.3
# The bimodality hint (a hint, never a claim): needs this many values, peaks this tall (share of the
# tallest) and a valley this shallow (share of the lower peak). See _is_bimodal for why not Sarle's.
_BIMODAL_MIN_ROWS = 100
_PEAK_FLOOR = 0.2
_VALLEY_RATIO = 0.6
# At this many measures, or columns, a dataset is "wide".
_WIDE_MEASURES = 10
_WIDE_COLUMNS = 30
# Duplicate rows are only counted when hashing every cell is cheap.
_MAX_DUPLICATE_COLUMNS = 200

_DAY = 86_400.0
_FIXED_UNITS = (
    ("week", 7 * _DAY),
    ("day", _DAY),
    ("hour", 3_600.0),
    ("minute", 60.0),
    ("second", 1.0),
)
_ISO_DATE_PREFIX = r"^\d{4}-\d{2}"
# A UTC offset after a time ("Z", "+01:00", "-0500"); a bare date's "-01" never matches (four digits needed).
_TZ_SUFFIX = r"(?:Z|[+-]\d{2}:?\d{2})$"
_ID_TOKENS = frozenset({"id", "uuid", "guid", "key", "pk"})
_LATITUDE_NAMES = frozenset({"lat", "latitude"})
_LONGITUDE_NAMES = frozenset({"lon", "lng", "long", "longitude"})


class SemanticRole(StrEnum):
    """What a column is *for* when it is charted. ``unknown`` can never be bound to a chart slot."""

    MEASURE = "measure"
    DIMENSION = "dimension"
    TIME = "time"
    IDENTIFIER = "identifier"
    BINARY = "binary"
    ORDINAL = "ordinal"
    TEXT = "text"
    GEO = "geo"
    UNKNOWN = "unknown"


class CardinalityClass(StrEnum):
    """How many distinct non-null values a column has."""

    EMPTY = "empty"
    CONSTANT = "constant"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNIQUE_KEY = "unique_key"


class Issue(StrEnum):
    """A closed set of reasons a column should not be charted (or should be charted with care)."""

    ALL_NULL = "all_null"
    CONSTANT = "constant"
    AMBIGUOUS_TYPE = "ambiguous_type"
    UNSUPPORTED_TYPE = "unsupported_type"
    NOT_ANALYSED = "not_analysed"
    NON_FINITE = (
        "non_finite"  # informational: infinities were left out of the statistics
    )


# The roles a chart slot can be bound to today (identifier and text are descriptive; geo has no chart yet).
_CHARTABLE_ROLES = frozenset(
    {
        SemanticRole.MEASURE,
        SemanticRole.DIMENSION,
        SemanticRole.TIME,
        SemanticRole.ORDINAL,
        SemanticRole.BINARY,
    }
)

# An issue in this set means "never bind this column to a chart slot".
_BLOCKING = frozenset(
    {
        Issue.ALL_NULL,
        Issue.CONSTANT,
        Issue.AMBIGUOUS_TYPE,
        Issue.UNSUPPORTED_TYPE,
        Issue.NOT_ANALYSED,
    }
)


@dataclass(frozen=True, slots=True)
class ColumnSourceStats:
    """Whole-dataset facts about one column that a sample cannot give. ``None`` means unknown."""

    null_count: int | None = None
    distinct_count: int | None = (
        None  # approximate (HyperLogLog) over the whole dataset
    )


@dataclass(frozen=True, slots=True)
class SourceStats:
    """Whole-dataset facts, aligned with the frame's columns **by position** (names may repeat)."""

    row_count: int
    columns: tuple[ColumnSourceStats, ...] = ()


@dataclass(frozen=True, slots=True)
class DistributionShape:
    """The shape of a measure, from its finite values."""

    minimum: float
    maximum: float
    skew: float | None
    excess_kurtosis: float | None
    outlier_share: float  # share outside Tukey's fences (1.5 x IQR)
    zero_share: float
    negative_share: float
    bimodal_hint: bool


@dataclass(frozen=True, slots=True)
class TimeStructure:
    """The structure of a time column.

    ``granularity`` is the smallest step between distinct values, named as a calendar unit
    (``subsecond | second | minute | hour | day | week | month | quarter | year``), ``single`` for one distinct
    value, or ``irregular`` when no unit divides it. ``regularity`` is the share of gaps that are a whole
    number of steps (1.0 for a clean grid, also for a grid with holes). ``coverage`` is distinct values over
    the values a gap-free grid between the first and last would hold (1.0 = no holes); ``None`` when the step
    is not a unit. Both survive sampling, which a count of gaps does not.
    """

    granularity: str
    regularity: float
    coverage: float | None
    span_seconds: float
    minimum: str
    maximum: str


@dataclass(frozen=True, slots=True)
class ColumnFingerprint:
    """Everything the recommender is told about one column.

    ``row_order`` is how a measure or time column runs through the rows **in the order of the file**
    (``ascending`` / ``descending`` are non-strict, ``flat`` is constant, ``mixed`` is neither). It is what a
    funnel (non-increasing values) or a time axis (ascending) needs, and it is ``None`` unless the fingerprint
    is exact: a sample cannot see the order of the file.
    """

    name: str
    position: int
    dtype: str
    role: SemanticRole
    role_confidence: float
    cardinality: CardinalityClass
    distinct: int
    distinct_exact: bool
    missing_share: float
    issues: tuple[Issue, ...] = ()
    distribution: DistributionShape | None = None
    time: TimeStructure | None = None
    row_order: str | None = None

    @property
    def usable(self) -> bool:
        """Whether the column is understood and sound: a role was found and no blocking issue applies.

        An identifier is usable (it defines the grain) but is not chartable.
        """
        return self.role is not SemanticRole.UNKNOWN and not _BLOCKING.intersection(
            self.issues
        )

    @property
    def chartable(self) -> bool:
        """Whether the column may be an axis, a measure or a grouping: usable, and a role that can be one.

        Identifiers and free text are never an axis or a measure (a sequential id summed is noise), and
        ``geo`` has no chart yet. A convenience, **not** the authority for a given slot: a slot's own
        ``roles`` decide what may fill it (a radar's entity label and a scatter's point label take
        identifiers and text, which are not chartable here).
        """
        return self.usable and self.role in _CHARTABLE_ROLES


@dataclass(frozen=True, slots=True)
class CorrelationPair:
    """Two measures that move together (or against each other); positions index ``columns``."""

    left: int
    right: int
    pearson: float
    spearman: float


@dataclass(frozen=True, slots=True)
class DimensionPair:
    """``child`` is a finer dimension that determines the coarser ``parent`` (country -> region).

    ``distinct_ratio`` is parent levels over child levels. (Whether columns together identify a row is
    :attr:`DataFingerprint.grain`; a child that identified rows by itself is an identifier, not a dimension.)
    """

    child: int
    parent: int
    distinct_ratio: float


@dataclass(frozen=True, slots=True)
class TimeSignal:
    """How one measure moves over the first time column.

    ``trend_tau`` is Kendall's tau between time order and value (-1..1). ``seasonality_lag`` is the
    shortest repeating period in rows of a regular series, or ``None`` (including every sampled frame,
    where the rows are no longer a regular series); ``seasonality_strength`` is the autocorrelation there.
    """

    time: int
    measure: int
    trend_tau: float | None
    seasonality_lag: int | None
    seasonality_strength: float | None


@dataclass(frozen=True, slots=True)
class DataFingerprint:
    """The versioned description of one dataset. See the module docstring."""

    version: int
    rows: int
    column_count: int
    sampled_rows: int
    confidence: float
    notes: tuple[str, ...]
    shape: str  # "long" | "wide"
    grain: tuple[str, ...]
    duplicate_share: float | None
    columns: tuple[ColumnFingerprint, ...]
    correlations: tuple[CorrelationPair, ...] = ()
    hierarchies: tuple[DimensionPair, ...] = ()
    time_signals: tuple[TimeSignal, ...] = ()

    @property
    def partial(self) -> bool:
        """Whether the time budget ran out before every stage finished."""
        return "deadline" in self.notes

    def to_json(self) -> str:
        """Canonical JSON: sorted keys, no whitespace, never a NaN (``allow_nan=False`` is the tripwire)."""
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        )

    def to_dict(self) -> dict[str, Any]:
        """The JSON-serialisable form (enums become their strings, tuples become lists)."""
        result: dict[str, Any] = json.loads(self.to_json())
        return result

    def fingerprint_hash(self) -> str:
        """SHA-256 of :meth:`to_json`: the provenance key of a recommendation set."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------ helpers


def _num(value: Any, digits: int = 6) -> float | None:
    """``value`` as a rounded float, or ``None`` when it is not a finite number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # ``+ 0.0`` turns -0.0 into 0.0: the sign of a float-noise zero depends on summation order and would
    # make the canonical JSON (and its hash) differ between machines.
    return round(number, digits) + 0.0 if math.isfinite(number) else None


def _share(value: Any) -> float:
    number = _num(value)
    return 0.0 if number is None else min(1.0, max(0.0, number))


def name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
    return [token for token in re.split(r"[^a-z0-9]+", spaced) if token]


def _looks_like_id(name: str) -> bool:
    tokens = name_tokens(name)
    return bool(tokens) and (tokens[-1] in _ID_TOKENS or tokens[0] == "id")


def _cardinality(distinct: int, non_null: int) -> CardinalityClass:
    if distinct <= 0:
        return CardinalityClass.EMPTY
    if distinct == 1:
        return CardinalityClass.CONSTANT
    if non_null >= MIN_ROWS_FOR_KEY and distinct / non_null >= UNIQUE_KEY_RATIO:
        return CardinalityClass.UNIQUE_KEY
    if distinct <= LOW_CARDINALITY:
        return CardinalityClass.LOW
    if distinct <= MEDIUM_CARDINALITY:
        return CardinalityClass.MEDIUM
    return CardinalityClass.HIGH


def _naive_times(values: pd.Series) -> pd.Series:
    """Datetimes as timezone-naive.

    A timezone-aware column keeps its **local wall clock** (``tz_localize(None)``): a daily series in
    New York is one value per local day, and converting to UTC would turn the 23-hour spring-forward day
    into a gap and the series into an "hourly" one. Anything else (objects, mixed zones) goes through UTC.
    """
    if isinstance(values.dtype, pd.DatetimeTZDtype):
        return values.dt.tz_localize(None)
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    return parsed.dt.tz_localize(None)


def _iso_strings(values: pd.Series) -> pd.Series:
    """The non-null values as ``str`` (never ``numpy.str_`` or a subclass) with a UTC offset removed.

    The offset is dropped, not applied, for the reason :func:`_naive_times` keeps wall-clock time: the
    structure of a series is that of its local timestamps.
    """
    present = values.dropna()
    text = pd.Series([str(v) for v in present], index=present.index, dtype=object)
    return text.str.replace(_TZ_SUFFIX, "", regex=True)


def _dtype_name(dtype: Any, kind: str | None = None) -> str:
    """A closed, version-stable name for a column's storage type.

    Never the dtype's own repr: ``Sparse[object, 'secret']`` embeds a cell value, and ``object`` /
    ``str``, ``datetime64[ns]`` / ``[us]`` change between pandas versions, which would change the
    fingerprint's hash for identical data.
    """
    if kind == "other":
        return "other"
    if isinstance(dtype, pd.CategoricalDtype):
        return "categorical"
    if kind == "bool" or pd.api.types.is_bool_dtype(dtype):
        return "boolean"
    if kind == "datetime" or pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime"
    if pd.api.types.is_timedelta64_dtype(dtype):
        return "timedelta"
    if pd.api.types.is_integer_dtype(dtype):
        return "integer"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if kind == "number":
        return "decimal"
    if kind == "string" or pd.api.types.is_string_dtype(dtype):
        return "text"
    return "other"


def _prepare(series: pd.Series) -> tuple[str, pd.Series]:
    """Classify the storage kind of a column and return it in the form later stages read.

    Kinds: ``bool | datetime | number | string | other``. A ``datetime`` is returned as naive local time and
    a ``timedelta`` as a ``number`` of seconds; other numbers are returned unchanged (an integer id above
    2**53 would lose precision as a float, so distinct counts use the original).
    """
    dtype = series.dtype
    if isinstance(dtype, pd.CategoricalDtype):
        categories = dtype.categories.dtype
        coded = (
            pd.api.types.is_numeric_dtype(categories)
            and not pd.api.types.is_bool_dtype(categories)
        ) or isinstance(categories, pd.IntervalDtype)
        series = series.astype(object)
        if coded:
            # A coded column (1-5, a pd.cut bin) holds levels, never quantities: it is text-like.
            return "string", series
        dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "bool", series
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "datetime", _naive_times(series)
    if pd.api.types.is_timedelta64_dtype(dtype):
        return "number", series.dt.total_seconds()
    if pd.api.types.is_complex_dtype(dtype):
        return "other", series
    if pd.api.types.is_numeric_dtype(dtype):
        return "number", series
    probe = series.dropna()
    if probe.empty:
        return "string", series
    # Every value's type, not a head sample: one list after a hundred strings must make the column
    # "other" here, because later stages hash these values (nunique, drop_duplicates) and would raise.
    kinds = set(map(type, probe))
    if all(issubclass(k, (bool, np.bool_)) for k in kinds):
        return "bool", series
    if all(issubclass(k, _dt.date) for k in kinds):
        parsed = _naive_times(series)
        # A date outside the nanosecond range (year 9999 as "no end date") parses to NaT on pandas 2 and to
        # a real value on pandas 3. A column that loses values here is unsupported rather than "all null"
        # (pandas 2) or "time" (pandas 3) for the same data.
        if parsed.notna().sum() < len(probe):
            return "other", series
        return "datetime", parsed
    if all(issubclass(k, decimal.Decimal) for k in kinds):
        return "number", pd.to_numeric(series, errors="coerce")
    if all(issubclass(k, str) for k in kinds):
        return "string", series
    return "other", series


def _floats(values: pd.Series) -> np.ndarray[Any, Any]:
    """A numeric series as a float64 array, missing values as NaN (works for nullable integers)."""
    return pd.to_numeric(values, errors="coerce").to_numpy(
        dtype="float64", na_value=np.nan
    )


def _distinct(non_null: pd.Series) -> int:
    try:
        return int(non_null.nunique())
    except TypeError:  # unhashable values; such a column is already "other"
        return 0


# ------------------------------------------------------------------------------ column roles


@dataclass
class _Draft:
    """A column mid-analysis; frozen into a :class:`ColumnFingerprint` once every stage has run."""

    name: str
    position: int
    dtype: str
    role: SemanticRole
    confidence: float
    cardinality: CardinalityClass
    distinct: int
    distinct_exact: bool
    missing_share: float
    issues: list[Issue] = field(default_factory=list)
    values: pd.Series | None = None  # prepared values; kept only for measures and times
    distribution: DistributionShape | None = None
    time: TimeStructure | None = None
    row_order: str | None = None

    def freeze(self) -> ColumnFingerprint:
        return ColumnFingerprint(
            name=self.name,
            position=self.position,
            dtype=self.dtype,
            role=self.role,
            role_confidence=_share(self.confidence),
            cardinality=self.cardinality,
            distinct=self.distinct,
            distinct_exact=self.distinct_exact,
            missing_share=_share(self.missing_share),
            issues=tuple(dict.fromkeys(self.issues)),
            distribution=self.distribution,
            time=self.time,
            row_order=self.row_order,
        )

    @property
    def usable(self) -> bool:
        return self.role is not SemanticRole.UNKNOWN and not _BLOCKING.intersection(
            self.issues
        )


def _unclassified(
    name: str,
    position: int,
    series: pd.Series,
    issue: Issue | None,
    kind: str | None = None,
) -> _Draft:
    return _Draft(
        name=name,
        position=position,
        dtype=_dtype_name(series.dtype, kind),
        role=SemanticRole.UNKNOWN,
        confidence=0.0,
        cardinality=CardinalityClass.EMPTY,
        distinct=0,
        distinct_exact=False,
        missing_share=0.0,
        issues=[] if issue is None else [issue],
    )


def _string_role(
    name: str, non_null: pd.Series, distinct: int, est_non_null: int
) -> tuple[SemanticRole, float, list[Issue]]:
    """Role of a text column: time, free text, identifier or dimension (plus mixed-type ambiguity)."""
    issues: list[Issue] = []
    # Whether a value parses as a number depends on the value, not on how often it repeats, so ask each
    # distinct value once (five levels cost five parses, not 100,000). A column with more than
    # _AMBIGUITY_PROBE distinct values is checked on an evenly spaced subset: a mixed column whose odd
    # values are rarer than that can be missed, which only matters for an identifier-like column.
    # Cells are turned into plain ``str`` (``dtype=object`` keeps pandas 3 from inferring an Arrow string
    # dtype, which rejects a lone surrogate; ``str()`` turns numpy.str_, ints and intervals into text).
    uniques = non_null.unique()
    if len(uniques) > _AMBIGUITY_PROBE:
        uniques = uniques[:: len(uniques) // _AMBIGUITY_PROBE]
    levels = pd.Series([str(v) for v in uniques], dtype=object)
    numeric = pd.to_numeric(levels, errors="coerce").notna()
    if numeric.any() and not numeric.all():
        issues.append(Issue.AMBIGUOUS_TYPE)

    step = max(1, len(non_null) // 1000)
    probe = pd.Series([str(v) for v in non_null.iloc[::step]], dtype=object)
    stripped = probe.str.replace(_TZ_SUFFIX, "", regex=True)
    if stripped.str.match(_ISO_DATE_PREFIX).mean() >= 0.95:
        parsed = pd.to_datetime(stripped, errors="coerce", format="ISO8601")
        if parsed.notna().mean() >= 0.95:
            return SemanticRole.TIME, 0.8, issues

    ratio = distinct / max(1, est_non_null)
    mean_length = float(probe.str.len().mean())
    spaced = float(probe.str.contains(" ", regex=False).mean())
    if mean_length > TEXT_MEAN_LENGTH or (spaced >= 0.5 and ratio >= 0.5):
        return SemanticRole.TEXT, 0.8, issues
    if est_non_null >= MIN_ROWS_FOR_KEY and ratio >= UNIQUE_KEY_RATIO:
        return SemanticRole.IDENTIFIER, 0.9 if _looks_like_id(name) else 0.8, issues
    return (
        SemanticRole.DIMENSION,
        0.9 if distinct <= MEDIUM_CARDINALITY else 0.8,
        issues,
    )


def _number_role(
    name: str,
    series: pd.Series,
    prepared: pd.Series,
    distinct: int,
    est_non_null: int,
) -> tuple[SemanticRole, float]:
    """Role of a numeric column: geo, identifier, dimension key, ordinal scale or measure."""
    values = _floats(prepared)
    finite = values[np.isfinite(values)]
    tokens = name_tokens(name)
    if finite.size and tokens:
        if tokens[-1] in _LATITUDE_NAMES and finite.min() >= -90 and finite.max() <= 90:
            return SemanticRole.GEO, 0.8
        if (
            tokens[-1] in _LONGITUDE_NAMES
            and finite.min() >= -180
            and finite.max() <= 180
        ):
            return SemanticRole.GEO, 0.8

    integer_dtype = pd.api.types.is_integer_dtype(series.dtype)
    whole = integer_dtype or bool(finite.size and np.all(finite == np.round(finite)))
    hint = _looks_like_id(name)
    unique = (
        est_non_null >= MIN_ROWS_FOR_KEY
        and distinct / max(1, est_non_null) >= UNIQUE_KEY_RATIO
    )

    if integer_dtype and unique:
        span = float(finite.max() - finite.min()) + 1 if finite.size else 0.0
        if span <= 1.5 * distinct:  # a dense run of whole numbers: a row number
            return SemanticRole.IDENTIFIER, 0.9
        if hint:
            return SemanticRole.IDENTIFIER, 0.7
        return SemanticRole.MEASURE, 0.5  # sparse unique integers could be anything
    if integer_dtype and hint:  # an id that repeats is a key to group by
        return SemanticRole.DIMENSION, 0.7
    # A scale (1-5 stars, 0-10) is a few small whole numbers repeated many times; five rows of 10000, 4200,
    # 1900 ... are a measure, however few distinct values there are.
    with np.errstate(
        over="ignore"
    ):  # -1e308 .. 1e308 overflows; inf is simply "not a small range"
        small_range = bool(
            finite.size and finite.max() - finite.min() <= ORDINAL_MAX_RANGE
        )
    if (
        whole
        and small_range
        and 3 <= distinct <= ORDINAL_MAX_LEVELS
        and est_non_null >= ORDINAL_MIN_REPEATS * distinct
    ):
        return SemanticRole.ORDINAL, 0.7 if integer_dtype else 0.6
    if integer_dtype and distinct <= LOW_CARDINALITY:
        return SemanticRole.MEASURE, 0.6
    return SemanticRole.MEASURE, 0.85 if integer_dtype else 0.9


def _classify(
    series: pd.Series,
    *,
    name: str,
    position: int,
    total_rows: int,
    work_rows: int,
    exact: bool,
    stats: ColumnSourceStats | None,
) -> _Draft:
    kind, prepared = _prepare(series)
    non_null = prepared.dropna()
    sampled = len(non_null)

    nulls = stats.null_count if stats is not None else None
    if nulls is not None and total_rows > 0:
        missing_share = min(1.0, max(0.0, nulls / total_rows))
        est_non_null = max(total_rows - nulls, 0)
    else:
        missing_share = 1 - sampled / work_rows if work_rows else 0.0
        est_non_null = round(sampled * total_rows / work_rows) if work_rows else 0

    if sampled == 0:
        # A sample with no values is "all null" only when we know the whole column is (a very sparse
        # column can miss every row of a sample).
        known_empty = total_rows > 0 and (exact or est_non_null == 0)
        draft = _unclassified(
            name, position, series, Issue.ALL_NULL if known_empty else None, kind
        )
        draft.confidence = 1.0 if known_empty else 0.0
        draft.missing_share = missing_share
        return draft
    if kind == "other":
        draft = _unclassified(name, position, series, Issue.UNSUPPORTED_TYPE, kind)
        draft.missing_share = missing_share
        return draft

    sample_distinct = _distinct(non_null)
    distinct = sample_distinct
    if stats is not None and stats.distinct_count is not None:
        # The sample's own count is a hard lower bound; the approximate whole-dataset count can only add.
        distinct = max(sample_distinct, int(stats.distinct_count))
    distinct = min(distinct, max(est_non_null, sample_distinct))
    cardinality = _cardinality(distinct, est_non_null)

    issues: list[Issue] = []
    if distinct == 1 and est_non_null >= 2:
        issues.append(Issue.CONSTANT)

    values: pd.Series | None = None
    if kind == "datetime":
        role, confidence = SemanticRole.TIME, 1.0
        values = prepared
    elif kind == "bool":
        role, confidence = SemanticRole.BINARY, 0.99
    elif distinct == 2 and kind in ("number", "string"):
        role, confidence = SemanticRole.BINARY, 0.9
    elif kind == "number":
        role, confidence = _number_role(name, series, prepared, distinct, est_non_null)
        floats = pd.Series(_floats(prepared))
        if np.isinf(floats.to_numpy()).any():
            issues.append(Issue.NON_FINITE)
        if role is SemanticRole.MEASURE:
            values = floats
    else:
        role, confidence, extra = _string_role(name, non_null, distinct, est_non_null)
        issues.extend(extra)
        if role is SemanticRole.TIME:
            values = pd.to_datetime(
                _iso_strings(prepared), errors="coerce", format="ISO8601"
            ).reindex(prepared.index)

    return _Draft(
        name=name,
        position=position,
        dtype=_dtype_name(series.dtype, kind),
        role=role,
        confidence=confidence,
        cardinality=cardinality,
        distinct=distinct,
        distinct_exact=exact,
        missing_share=missing_share,
        issues=issues,
        values=values,
    )


# ------------------------------------------------------------------ shape, time and pair stages


def _row_order(values: pd.Series) -> str | None:
    """How ``values`` run through the rows (missing values skipped): see ``ColumnFingerprint.row_order``."""
    present = values.dropna()
    if len(present) < 2:
        return None
    rising, falling = present.is_monotonic_increasing, present.is_monotonic_decreasing
    if rising and falling:
        return "flat"
    if rising:
        return "ascending"
    return "descending" if falling else "mixed"


def _is_bimodal(finite: np.ndarray[Any, Any]) -> bool:
    """Whether a smoothed histogram has two real peaks with a clear valley between them.

    Sarle's bimodality coefficient was tried first and rejected: it flags every skewed unimodal measure
    (a lognormal amount) and every uniform one (a trending series), because it is built from skew and
    kurtosis alone. Two peaks each above ``_PEAK_FLOOR`` of the tallest, separated by a valley below
    ``_VALLEY_RATIO`` of the lower peak, is a hint a reader can check by looking at a histogram.
    """
    if finite.size < _BIMODAL_MIN_ROWS:
        return False
    with np.errstate(over="ignore", invalid="ignore"):
        if not np.isfinite(
            np.ptp(finite)
        ):  # -1e308 .. 1e308: no histogram range exists
            return False
    bins = min(30, max(10, int(math.sqrt(finite.size))))
    counts, _ = np.histogram(finite, bins=bins)
    smooth = np.convolve(counts, np.ones(3) / 3, mode="same")
    peaks = [
        i
        for i in range(1, len(smooth) - 1)
        if smooth[i] > smooth[i - 1]
        and smooth[i] >= smooth[i + 1]
        and smooth[i] >= _PEAK_FLOOR * smooth.max()
    ]
    if len(peaks) < 2:
        return False
    low, high = sorted(sorted(peaks, key=lambda i: (-smooth[i], i))[:2])
    valley = smooth[low : high + 1].min()
    return bool(valley <= _VALLEY_RATIO * min(smooth[low], smooth[high]))


def _distribution(values: pd.Series) -> DistributionShape | None:
    """The shape of a measure. Overflow on extreme floats (1e308) is expected and ends in ``None`` through
    :func:`_num`, so numpy's warnings are silenced rather than logged once per column.
    """
    with np.errstate(all="ignore"):
        return _shape_of(values)


def _shape_of(values: pd.Series) -> DistributionShape | None:
    array = _floats(values)
    finite = array[np.isfinite(array)]
    if finite.size == 0:
        return None
    frame = pd.Series(finite)
    skew = _num(frame.skew()) if finite.size >= 8 else None
    kurt = _num(frame.kurt()) if finite.size >= 8 else None
    q1, q3 = np.percentile(finite, [25, 75])
    spread = q3 - q1
    outside = (finite < q1 - 1.5 * spread) | (finite > q3 + 1.5 * spread)
    bimodal = _is_bimodal(finite)
    return DistributionShape(
        minimum=_num(finite.min()) or 0.0,
        maximum=_num(finite.max()) or 0.0,
        skew=skew,
        excess_kurtosis=kurt,
        outlier_share=_share(outside.mean()),
        zero_share=_share((finite == 0).mean()),
        negative_share=_share((finite < 0).mean()),
        bimodal_hint=bool(bimodal),
    )


def _time_structure(
    values: pd.Series, distinct_total: int | None
) -> TimeStructure | None:
    index = pd.DatetimeIndex(values.dropna().unique()).sort_values()
    if len(index) == 0:
        return None
    minimum, maximum = index[0].isoformat(), index[-1].isoformat()
    if len(index) == 1:
        return TimeStructure("single", 1.0, None, 0.0, minimum, maximum)

    # Integer microseconds: exact, and a span of centuries cannot overflow (int64 nanoseconds overflow after
    # about 292 years, which a 1700-2020 series is).
    micros = index.as_unit("us").asi8
    seconds = (micros - micros[0]) / 1e6
    gaps = np.diff(seconds)
    step = float(gaps.min())
    span = float(seconds[-1])

    calendar = False
    nominal = step
    meaningful = True
    if step < 1.0:
        label, meaningful = "subsecond", False
    elif 28 * _DAY <= step <= 31 * _DAY:
        label, nominal, calendar = "month", 30.4375 * _DAY, True
    elif 89 * _DAY <= step <= 92 * _DAY:
        label, nominal, calendar = "quarter", 91.3125 * _DAY, True
    elif 365 * _DAY <= step <= 366 * _DAY:
        label, nominal, calendar = "year", 365.25 * _DAY, True
    else:
        label, meaningful = "irregular", False
        for unit, size in _FIXED_UNITS:
            if step >= size and math.isclose(
                step, round(step / size) * size, abs_tol=1e-6
            ):
                label, meaningful = unit, True
                break

    whole = np.maximum(1.0, np.round(gaps / nominal))
    tolerance = 0.1 * nominal if calendar else max(1e-6, 1e-9 * nominal)
    regularity = float((np.abs(gaps - whole * nominal) <= tolerance).mean())

    coverage: float | None = None
    if meaningful:
        expected = round(span / nominal) + 1
        seen = len(index) if distinct_total is None else max(distinct_total, len(index))
        coverage = _num(min(1.0, seen / expected)) if expected > 0 else None
    return TimeStructure(
        label, _share(regularity), coverage, _num(span) or 0.0, minimum, maximum
    )


def _time_signal(
    times: pd.Series,
    measure: pd.Series,
    *,
    time_position: int,
    measure_position: int,
    seasonal: bool,
) -> TimeSignal | None:
    y = _floats(measure)
    keep = times.notna().to_numpy() & np.isfinite(y)
    if keep.sum() < 10:
        return None
    # Dropping a row from a regular series moves every later row off the grid, so a "lag in rows" is only
    # meaningful when nothing was dropped.
    seasonal = seasonal and bool(keep.all())
    t = times.to_numpy()[keep]
    y = y[keep]
    order = np.argsort(t, kind="stable")
    t = t[order]
    y = y[order]

    picks = np.linspace(0, len(y) - 1, min(len(y), TREND_POINTS)).astype(int)
    result = scipy_stats.kendalltau(np.arange(len(picks)), y[picks])
    tau = _num(result.statistic)

    lag: int | None = None
    strength: float | None = None
    if seasonal and len(y) >= 8 and len(np.unique(t)) == len(t):
        lag, strength = _seasonality(y)
    return TimeSignal(time_position, measure_position, tau, lag, strength)


def _seasonality(y: np.ndarray[Any, Any]) -> tuple[int | None, float | None]:
    """The shortest strong repeating period of an evenly spaced series, after removing a linear trend."""
    n = len(y)
    x = np.arange(n, dtype="float64")
    slope, intercept = np.polyfit(x, y, 1)
    flat = y - (slope * x + intercept)
    flat = flat - flat.mean()
    spectrum = np.fft.rfft(flat, n=2 * n)
    autocov = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    if not autocov[0] > 0:
        return None, None
    acf = autocov / autocov[0]
    # At least three full cycles (a period of n/2 is two points of evidence), and an autocorrelation above
    # the 95 % band of white noise (2/sqrt(n)): at 0.3 alone, one white-noise series in five of 24 points was
    # reported as seasonal.
    top = min(n // 3, MAX_SEASONAL_LAG)
    floor = max(MIN_SEASONAL_STRENGTH, 2 / math.sqrt(n))
    peaks = [
        lag
        for lag in range(2, top)
        if acf[lag] > acf[lag - 1] and acf[lag] >= acf[lag + 1] and acf[lag] >= floor
    ]
    if not peaks:
        return None, None
    best = max(acf[lag] for lag in peaks)
    chosen = next(lag for lag in peaks if acf[lag] >= 0.8 * best)
    return int(chosen), _num(acf[chosen])


def _correlations(drafts: list[_Draft], seed: int) -> tuple[CorrelationPair, ...]:
    measures = [
        d
        for d in drafts
        if d.role is SemanticRole.MEASURE and d.values is not None and d.usable
    ][:MAX_PAIR_MEASURES]
    if len(measures) < 2:
        return ()
    frame = pd.DataFrame(
        {d.position: _floats(d.values) for d in measures if d.values is not None}
    )
    frame = frame.replace([np.inf, -np.inf], np.nan)
    if len(frame) > PAIR_ROWS:
        frame = frame.sample(n=PAIR_ROWS, random_state=seed)
    pearson = frame.corr(min_periods=10)
    spearman = frame.corr(method="spearman", min_periods=10)
    found: list[tuple[float, int, int, float, float]] = []
    keys = list(frame.columns)
    for i, left in enumerate(keys):
        for right in keys[i + 1 :]:
            p = _num(pearson.loc[left, right])
            s = _num(spearman.loc[left, right])
            if p is None or s is None:
                continue
            found.append((max(abs(p), abs(s)), int(left), int(right), p, s))
    found.sort(key=lambda row: (-row[0], row[1], row[2]))
    return tuple(
        CorrelationPair(left, right, p, s) for _, left, right, p, s in found[:TOP_PAIRS]
    )


def _hierarchies(
    work: pd.DataFrame, drafts: list[_Draft], expired: Callable[[], bool]
) -> tuple[tuple[DimensionPair, ...], bool]:
    """Which dimension determines which (country -> region), and whether the search finished.

    Each dimension is factorised once, so a pair costs one vectorised pass over integer codes instead of a
    ``drop_duplicates`` over two object columns (132 of those took 2.6 s on 100k rows). ``expired`` is polled
    between pairs: a spent time budget ends the search with what it found, and ``False`` is returned.
    """
    dims = [
        d
        for d in drafts
        if d.role is SemanticRole.DIMENSION
        and d.usable
        and d.cardinality
        in (CardinalityClass.LOW, CardinalityClass.MEDIUM, CardinalityClass.HIGH)
    ][:MAX_PAIR_DIMENSIONS]
    codes = {d.position: pd.factorize(work.iloc[:, d.position])[0] for d in dims}
    out: list[DimensionPair] = []
    complete = True
    for child in dims:
        for parent in dims:
            if child.position == parent.position or parent.distinct >= child.distinct:
                continue
            if expired():
                complete = False
                break
            a, b = codes[child.position], codes[parent.position]
            valid = (a >= 0) & (b >= 0)  # factorize codes a missing value as -1
            if not valid.any():
                continue
            a, b = a[valid], b[valid]
            # The parent last written for each child code; a function iff every row agrees with it.
            parent_of = np.full(int(a.max()) + 1, -1, dtype=np.int64)
            parent_of[a] = b
            if np.array_equal(parent_of[a], b):
                out.append(
                    DimensionPair(
                        child=child.position,
                        parent=parent.position,
                        distinct_ratio=_share(parent.distinct / child.distinct),
                    )
                )
        if not complete:
            break
    out.sort(key=lambda p: (p.child, p.parent))
    return tuple(out), complete


def _grain(work: pd.DataFrame, drafts: list[_Draft]) -> tuple[str, ...]:
    """The smallest column set that identifies a row: a key column, else time (+ one dimension)."""
    for d in drafts:
        if d.role is SemanticRole.IDENTIFIER and d.usable:
            return (d.name,)
    times = next((d for d in drafts if d.role is SemanticRole.TIME and d.usable), None)
    if times is None or len(work) == 0:
        return ()
    if work.iloc[:, times.position].is_unique:
        return (times.name,)
    for d in drafts:
        if (
            d.role is SemanticRole.DIMENSION
            and d.usable
            and d.cardinality in (CardinalityClass.LOW, CardinalityClass.MEDIUM)
            and not work.iloc[:, [times.position, d.position]].duplicated().any()
        ):
            return (times.name, d.name)
    return ()


def _time_signals(drafts: list[_Draft], exact: bool) -> tuple[TimeSignal, ...]:
    times = next(
        (
            d
            for d in drafts
            if d.role is SemanticRole.TIME and d.values is not None and d.usable
        ),
        None,
    )
    if times is None or times.values is None:
        return ()
    regular = (
        exact
        and times.time is not None
        and times.time.regularity >= 0.9
        and (times.time.coverage or 0.0) >= 0.9
    )
    measures = [
        d
        for d in drafts
        if d.role is SemanticRole.MEASURE and d.values is not None and d.usable
    ][:MAX_TIME_SIGNAL_MEASURES]
    out: list[TimeSignal] = []
    for m in measures:
        if m.values is None:
            continue
        signal = _time_signal(
            times.values,
            m.values,
            time_position=times.position,
            measure_position=m.position,
            seasonal=regular,
        )
        if signal is not None:
            out.append(signal)
    return tuple(out)


# ----------------------------------------------------------------------------------- builder


def build_fingerprint(
    frame: pd.DataFrame,
    *,
    source: SourceStats | None = None,
    seed: int = 0,
    sample_rows: int = SAMPLE_ROWS,
    time_budget: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> DataFingerprint:
    """Describe ``frame``.

    Args:
        frame: The dataset, or a uniformly random sample of it. Not mutated. A frame longer than
            ``sample_rows`` is sampled down with ``seed``.
        source: Whole-dataset facts when ``frame`` is a sample (see :class:`SourceStats`). Its
            ``columns`` align with ``frame``'s by position. Omit it when ``frame`` is the whole dataset.
        seed: Seed of every random choice, so the same input gives the same fingerprint.
        sample_rows: Cap on the rows the statistics are computed from.
        time_budget: Seconds after which the remaining stages are skipped (a partial fingerprint is
            returned, never an error). ``None`` means no limit.
        clock: Monotonic clock in seconds; injectable so a test can expire the budget deterministically.

    Never raises on data: the checks that can fail are about the arguments, not the values.
    """
    deadline = None if time_budget is None else clock() + time_budget

    def expired() -> bool:
        return deadline is not None and clock() >= deadline

    total_rows = source.row_count if source is not None else len(frame)
    work = (
        frame
        if len(frame) <= sample_rows
        else frame.sample(n=sample_rows, random_state=seed)
    )
    work_rows = len(work)
    exact = work_rows == total_rows
    notes: list[str] = []
    if not exact:
        notes.append("sampled")
        if source is None or not source.columns:
            notes.append("no_source_stats")

    # "deadline" is noted only when a stage was actually skipped or cut short, not merely because the clock
    # is late.
    cut = False
    failed: list[str] = []

    def guarded(stage: str, call: Callable[[], Any], default: Callable[[], Any]) -> Any:
        """Run one stage; if it raises, record its name and use ``default`` (never an error to the caller).

        "Never raises on data" is the contract at this trust boundary (tenant data of any shape), so it
        is enforced structurally as well as by fixing each defect found. Only the stage name and the
        exception *class* are recorded: a pandas error message can quote a cell.
        """
        try:
            return call()
        except Exception as error:  # noqa: BLE001
            _logger.warning(
                "fingerprint: stage %s failed (%s)", stage, type(error).__name__
            )
            if stage not in failed:
                failed.append(stage)
            return default()

    # Stage 1: role and cardinality of every column (the only stage a deadline may cut column by column).
    drafts: list[_Draft] = []
    for position in range(work.shape[1]):
        series = work.iloc[:, position]
        name = str(work.columns[position])
        if expired():
            cut = True
            drafts.append(_unclassified(name, position, series, Issue.NOT_ANALYSED))
            continue
        stats = (
            source.columns[position]
            if source is not None and position < len(source.columns)
            else None
        )
        drafts.append(
            guarded(
                "classify",
                partial(
                    _classify,
                    series,
                    name=name,
                    position=position,
                    total_rows=total_rows,
                    work_rows=work_rows,
                    exact=exact,
                    stats=stats,
                ),
                partial(_unclassified, name, position, series, Issue.NOT_ANALYSED),
            )
        )

    # Stage 2: distribution of measures and structure of time columns.
    for draft in drafts:
        if draft.values is None:
            continue
        if expired():
            cut = True
            break
        if exact:  # a sample has lost the order of the file
            draft.row_order = guarded(
                "row_order", partial(_row_order, draft.values), lambda: None
            )
        if draft.role is SemanticRole.MEASURE:
            draft.distribution = guarded(
                "distribution", partial(_distribution, draft.values), lambda: None
            )
        elif draft.role is SemanticRole.TIME:
            draft.time = guarded(
                "time_structure",
                partial(_time_structure, draft.values, draft.distinct),
                lambda: None,
            )

    correlations: tuple[CorrelationPair, ...] = ()
    hierarchies: tuple[DimensionPair, ...] = ()
    time_signals: tuple[TimeSignal, ...] = ()
    grain: tuple[str, ...] = ()
    duplicate_share: float | None = None

    # Stage 3: pairs, time signals, grain, duplicates -- each skipped once the budget is spent.
    if expired():
        cut = True
    else:
        correlations = guarded(
            "correlations", lambda: _correlations(drafts, seed), lambda: ()
        )
    if expired():
        cut = True
    else:
        hierarchies, complete = guarded(
            "hierarchies",
            lambda: _hierarchies(work, drafts, expired),
            lambda: ((), True),
        )
        cut = cut or not complete
    if expired():
        cut = True
    else:
        time_signals = guarded(
            "time_signals", lambda: _time_signals(drafts, exact), lambda: ()
        )
    if expired():
        cut = True
    else:
        grain = guarded("grain", lambda: _grain(work, drafts), lambda: ())
        # Columns of unhashable values (lists, dicts) cannot be hashed into a row; they are left out.
        hashable = [
            d.position for d in drafts if Issue.UNSUPPORTED_TYPE not in d.issues
        ]
        if work_rows and hashable and len(hashable) <= _MAX_DUPLICATE_COLUMNS:
            duplicate_share = guarded(
                "duplicates",
                lambda: _share(work.iloc[:, hashable].duplicated().mean()),
                lambda: None,
            )
    if cut:
        notes.append("deadline")
    notes.extend(f"stage_failed:{stage}" for stage in failed)

    columns = tuple(d.freeze() for d in drafts)
    measure_count = sum(c.role is SemanticRole.MEASURE and c.usable for c in columns)
    wide = measure_count >= _WIDE_MEASURES or len(columns) >= _WIDE_COLUMNS
    confidence = 1.0 if exact else 1 - 1 / math.sqrt(max(work_rows, 1))
    if "no_source_stats" in notes:
        confidence *= 0.9
    if "deadline" in notes:
        confidence *= 0.6
    if failed:
        confidence *= 0.8

    return DataFingerprint(
        version=FINGERPRINT_VERSION,
        rows=total_rows,
        column_count=len(columns),
        sampled_rows=work_rows,
        confidence=_share(confidence),
        notes=tuple(notes),
        shape="wide" if wide else "long",
        grain=grain,
        duplicate_share=duplicate_share,
        columns=columns,
        correlations=correlations,
        hierarchies=hierarchies,
        time_signals=time_signals,
    )
