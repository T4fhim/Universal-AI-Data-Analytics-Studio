# File: tests/analysis/test_fingerprint.py
"""The chart-intelligence fingerprint (CI.1): roles, structure, sampling, determinism and robustness.

Three kinds of proof, matching ``plans/phase-4-chart-intelligence.md`` section 4: the 29 gold-set frames
pin what each column is (``avoid_columns`` must come out unusable, a sequential id must not be a measure);
hand-built frames pin the structure rules (granularity, hierarchy, seasonality); and a Hypothesis property
test plus a list of hostile frames prove that no input raises, none emits a NaN, and the same input gives a
byte-identical result. The redaction test is the one that guards constraint 5 of the plan: a fingerprint
must never carry a cell value.
"""

from __future__ import annotations

import datetime as dt
import decimal
import json

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.pandas import column, data_frames, range_indexes

from tests.visualization.gold_set import GOLD_CASES
from uadas_core.analysis.fingerprint import (
    FINGERPRINT_VERSION,
    CardinalityClass,
    ColumnFingerprint,
    ColumnSourceStats,
    DataFingerprint,
    Issue,
    SemanticRole,
    SourceStats,
    build_fingerprint,
)


def _column(fp: DataFingerprint, name: str) -> ColumnFingerprint:
    return next(c for c in fp.columns if c.name == name)


def _fingerprint_of(case_name: str) -> DataFingerprint:
    case = next(c for c in GOLD_CASES if c.name == case_name)
    return build_fingerprint(case.build(case.rows))


# ------------------------------------------------------------------------------ the gold set


@pytest.mark.parametrize("case", GOLD_CASES, ids=lambda c: c.name)
def test_every_gold_case_fingerprints_and_never_binds_an_avoided_column(case) -> None:  # type: ignore[no-untyped-def]
    fp = build_fingerprint(case.build(case.rows))
    assert fp.version == FINGERPRINT_VERSION
    assert fp.rows == case.rows
    json.loads(fp.to_json())  # serialisable, no NaN (allow_nan=False would raise)
    for name in case.avoid_columns:
        assert not _column(fp, name).chartable, f"{case.name}: {name} is chartable"


@pytest.mark.parametrize(
    ("case_name", "column_name", "role"),
    [
        ("numeric_id_trap", "order_id", SemanticRole.IDENTIFIER),
        ("numeric_id_trap", "amount", SemanticRole.MEASURE),
        ("daily_timeseries", "date", SemanticRole.TIME),
        ("daily_timeseries", "sales", SemanticRole.MEASURE),
        ("survey_likert", "q1", SemanticRole.ORDINAL),
        ("survey_likert", "group", SemanticRole.DIMENSION),
        (
            "funnel_stages",
            "users",
            SemanticRole.MEASURE,
        ),  # five whole numbers are not a scale
        ("categorical_only", "channel", SemanticRole.DIMENSION),
        ("budget_vs_actual", "budget", SemanticRole.MEASURE),
    ],
)
def test_gold_case_column_roles(
    case_name: str, column_name: str, role: SemanticRole
) -> None:
    assert _column(_fingerprint_of(case_name), column_name).role is role


def test_the_constant_the_all_null_and_the_mixed_type_columns_are_flagged() -> None:
    flat = _column(_fingerprint_of("constant_measure"), "flat")
    assert (
        Issue.CONSTANT in flat.issues and flat.cardinality is CardinalityClass.CONSTANT
    )
    empty = _column(_fingerprint_of("all_null_measure"), "empty_col")
    assert empty.issues == (Issue.ALL_NULL,) and empty.role is SemanticRole.UNKNOWN
    mixed = _column(_fingerprint_of("ambiguous_mixed_column"), "code")
    assert Issue.AMBIGUOUS_TYPE in mixed.issues


def test_a_zero_row_frame_has_no_usable_column() -> None:
    fp = _fingerprint_of("zero_rows")
    assert fp.rows == 0 and not any(c.usable for c in fp.columns)


# ----------------------------------------------------------------------------- time structure


@pytest.mark.parametrize(
    ("case_name", "column_name", "granularity"),
    [
        ("daily_timeseries", "date", "day"),
        ("two_measures_over_time", "month", "month"),
        ("huge_timeseries", "ts", "minute"),
    ],
)
def test_time_granularity(case_name: str, column_name: str, granularity: str) -> None:
    structure = _column(_fingerprint_of(case_name), column_name).time
    assert structure is not None
    assert structure.granularity == granularity
    assert structure.regularity == 1.0 and structure.coverage == 1.0


def test_a_grid_with_holes_has_low_coverage_but_full_regularity() -> None:
    structure = _column(_fingerprint_of("irregular_timeseries"), "visit_date").time
    assert structure is not None and structure.granularity == "day"
    assert structure.regularity == 1.0
    assert structure.coverage is not None and structure.coverage < 0.5


def test_quarter_year_and_odd_steps() -> None:
    quarters = pd.DataFrame({"t": pd.date_range("2018-01-01", periods=12, freq="QS")})
    years = pd.DataFrame({"t": pd.date_range("2000-01-01", periods=12, freq="YS")})
    odd = pd.DataFrame(
        {
            "t": pd.Timestamp("2024-01-01")
            + pd.to_timedelta(np.arange(12) * 7.3, unit="s")
        }
    )
    granularities = [
        getattr(_column(build_fingerprint(frame), "t").time, "granularity", None)
        for frame in (quarters, years, odd)
    ]
    assert granularities == ["quarter", "year", "irregular"]


def test_iso_strings_dates_and_timezones_are_all_time_columns() -> None:
    frame = pd.DataFrame(
        {
            "iso": [f"2024-03-{d:02d}" for d in range(1, 21)],
            "dates": [dt.date(2024, 3, d) for d in range(1, 21)],
            "aware": pd.date_range(
                "2024-03-01", periods=20, freq="D", tz="Europe/Paris"
            ),
            # looks like a year, is not an ISO date
            "years": [str(2000 + i) for i in range(20)],
        }
    )
    fp = build_fingerprint(frame)
    roles = [_column(fp, n).role for n in ("iso", "dates", "aware")]
    assert roles == [SemanticRole.TIME] * 3
    assert _column(fp, "years").role is not SemanticRole.TIME
    iso = _column(fp, "iso").time
    assert iso is not None and iso.granularity == "day"


def test_trend_and_weekly_seasonality_of_a_daily_series() -> None:
    signal = _fingerprint_of("daily_timeseries").time_signals[0]
    assert signal.trend_tau is not None and signal.trend_tau > 0.5
    assert signal.seasonality_lag == 7
    assert signal.seasonality_strength is not None and signal.seasonality_strength > 0.5


def test_a_downward_trend_has_a_negative_tau() -> None:
    frame = pd.DataFrame(
        {
            "day": pd.date_range("2024-01-01", periods=60, freq="D"),
            "v": np.arange(60)[::-1] * 1.0,
        }
    )
    assert build_fingerprint(frame).time_signals[0].trend_tau == -1.0


# ------------------------------------------------------------------------------ pair statistics


def test_correlated_and_independent_measures() -> None:
    strong = _fingerprint_of("correlated_pair").correlations[0]
    weak = _fingerprint_of("independent_pair").correlations[0]
    assert strong.pearson > 0.8 and abs(weak.pearson) < 0.2


def test_a_country_belongs_to_exactly_one_region() -> None:
    fp = _fingerprint_of("hierarchy_sales")
    pairs = {
        (fp.columns[h.child].name, fp.columns[h.parent].name) for h in fp.hierarchies
    }
    assert pairs == {("country", "region")}


def test_grain_is_a_key_or_time_plus_a_dimension() -> None:
    assert _fingerprint_of("numeric_id_trap").grain == ("order_id",)
    assert _fingerprint_of("composition_over_time").grain == ("month", "segment")
    assert _fingerprint_of("region_sales_low_cardinality").grain == ()


def test_a_wide_frame_is_marked_wide() -> None:
    assert _fingerprint_of("wide_numeric_12").shape == "wide"
    assert _fingerprint_of("daily_timeseries").shape == "long"


def test_a_skewed_measure_is_not_called_bimodal_but_two_clusters_are() -> None:
    rng = np.random.default_rng(0)
    skewed = pd.DataFrame({"x": rng.lognormal(3.0, 1.1, 1_000)})
    uniform = pd.DataFrame({"x": rng.uniform(0, 1, 1_000)})
    clusters = pd.DataFrame(
        {"x": np.concatenate([rng.normal(0, 1, 500), rng.normal(10, 1, 500)])}
    )
    hints = [
        getattr(_column(build_fingerprint(f), "x").distribution, "bimodal_hint", None)
        for f in (skewed, uniform, clusters)
    ]
    assert hints == [False, False, True]


# ---------------------------------------------------------------- sampling and source statistics


def test_a_large_frame_is_sampled_uniformly_never_from_the_head() -> None:
    rows = 60_000
    frame = pd.DataFrame(
        {
            "t": pd.date_range("2020-01-01", periods=rows, freq="min"),
            "v": np.arange(rows, dtype=float),
        }
    )
    fp = build_fingerprint(frame, sample_rows=5_000)
    assert fp.rows == rows and fp.sampled_rows == 5_000
    assert "sampled" in fp.notes and not fp.partial
    structure = _column(fp, "t").time
    assert structure is not None
    # A head sample would end on day 3; a uniform one reaches the end of the 41-day series.
    assert structure.span_seconds > 40 * 86_400
    assert 0.0 < fp.confidence < 1.0


def test_source_statistics_override_what_a_sample_cannot_know() -> None:
    sample = pd.DataFrame(
        {"k": [f"k{i % 40}" for i in range(500)], "x": np.linspace(0, 1, 500)}
    )
    source = SourceStats(
        row_count=1_000_000,
        columns=(
            ColumnSourceStats(null_count=250_000, distinct_count=42),
            ColumnSourceStats(null_count=0, distinct_count=990_000),
        ),
    )
    fp = build_fingerprint(sample, source=source)
    key, value = _column(fp, "k"), _column(fp, "x")
    assert fp.rows == 1_000_000 and fp.sampled_rows == 500
    assert key.missing_share == 0.25
    assert key.distinct == 42 and not key.distinct_exact
    assert key.cardinality is CardinalityClass.MEDIUM
    assert value.cardinality is CardinalityClass.UNIQUE_KEY
    assert "no_source_stats" not in fp.notes


def test_a_sample_without_source_statistics_says_so() -> None:
    fp = build_fingerprint(
        pd.DataFrame({"x": np.arange(200.0)}), source=SourceStats(row_count=10_000)
    )
    assert "no_source_stats" in fp.notes


def test_numeric_strings_with_nulls_are_not_mixed_type() -> None:
    frame = pd.DataFrame({"n": ["1", "2", None, "4", "5", "6", "7", "8", "9", "10"]})
    assert Issue.AMBIGUOUS_TYPE not in _column(build_fingerprint(frame), "n").issues


# ----------------------------------------------------------------------------- the three promises


def test_the_same_input_gives_a_byte_identical_fingerprint() -> None:
    case = next(c for c in GOLD_CASES if c.name == "seasonal_sales_region_product")
    first = build_fingerprint(case.build(case.rows), sample_rows=200, seed=3)
    second = build_fingerprint(case.build(case.rows), sample_rows=200, seed=3)
    assert first.to_json() == second.to_json()
    assert first.fingerprint_hash() == second.fingerprint_hash()
    other_seed = build_fingerprint(case.build(case.rows), sample_rows=200, seed=4)
    assert other_seed.fingerprint_hash() != first.fingerprint_hash()


def test_no_cell_value_reaches_a_fingerprint() -> None:
    secrets = ["ACME-SECRET-7731", "jane.doe@example.com", "4111 1111 1111 1111"]
    frame = pd.DataFrame(
        {
            "customer": [secrets[i % 3] for i in range(60)],
            "note": [f"{secrets[i % 3]} called about invoice {i}" for i in range(60)],
            "when": pd.date_range("2024-01-01", periods=60, freq="D"),
            "amount": np.arange(60, dtype=float),
        }
    )
    text = build_fingerprint(frame).to_json()
    assert not any(secret in text for secret in secrets)


def test_an_expired_time_budget_gives_a_partial_fingerprint_not_an_error() -> None:
    ticks = iter(range(10_000))
    frame = pd.DataFrame({f"c{i}": np.arange(30.0) for i in range(12)})
    # Budget 3 "seconds" on a clock that advances one per call: stage 1 gets through a few columns.
    fp = build_fingerprint(frame, time_budget=3, clock=lambda: float(next(ticks)))
    assert fp.partial and "deadline" in fp.notes
    skipped = [c for c in fp.columns if Issue.NOT_ANALYSED in c.issues]
    assert skipped and all(not c.usable for c in skipped)
    assert fp.confidence <= 0.6
    json.loads(fp.to_json())


def test_a_budget_that_is_not_exhausted_leaves_the_fingerprint_complete() -> None:
    frame = pd.DataFrame({"a": np.arange(30.0), "b": np.arange(30.0) ** 2})
    fp = build_fingerprint(frame, time_budget=1_000)
    assert not fp.partial and fp.confidence == 1.0 and len(fp.correlations) == 1


# ----------------------------------------------------------------------------- hostile frames


def _hostile_frames() -> dict[str, pd.DataFrame]:
    n = 30
    return {
        "nan_and_inf": pd.DataFrame(
            {"x": np.r_[[np.nan, np.inf, -np.inf], np.linspace(1.0, 2.0, 27)]}
        ),
        "all_nan": pd.DataFrame({"x": [np.nan] * n, "y": [None] * n}),
        "mixed_objects": pd.DataFrame(
            {"m": [1, "a", 2.5, None, True, dt.date(2020, 1, 1)] * 5}
        ),
        "lists_and_dicts": pd.DataFrame({"l": [[1, 2]] * n, "d": [{"a": 1}] * n}),
        "bytes": pd.DataFrame({"b": [b"\x00\xff"] * n}),
        "complex": pd.DataFrame({"c": np.arange(n) + 1j}),
        "decimals": pd.DataFrame({"d": [decimal.Decimal(i) / 3 for i in range(n)]}),
        "timedelta": pd.DataFrame({"d": pd.to_timedelta(np.arange(n), unit="h")}),
        "categorical": pd.DataFrame({"c": pd.Categorical(["a", "b", "c"] * 10)}),
        "nullable_int": pd.DataFrame(
            {"i": pd.array(list(range(n - 1)) + [None], dtype="Int64")}
        ),
        "huge_ints": pd.DataFrame({"i": np.arange(n, dtype="int64") + 2**62}),
        "empty_and_weird_names": pd.DataFrame(
            {
                "": np.arange(n),
                " ": np.arange(n) * 2.0,
                "a" * 5_000: np.arange(n) % 5,
                "naive\u0000": ["x"] * n,
            }
        ),
        "duplicate_names": pd.DataFrame(
            np.arange(n * 3).reshape(n, 3), columns=["a", "a", "a"]
        ),
        "non_string_labels": pd.DataFrame(
            {1: np.arange(n), (2, 3): np.arange(n) * 1.5, None: ["k"] * n}
        ),
        "no_columns": pd.DataFrame(index=range(5)),
        "no_rows_no_columns": pd.DataFrame(),
        "out_of_range_dates": pd.DataFrame(
            {"t": pd.Series([dt.date(1, 1, 1), dt.date(9999, 12, 31)] * 15)}
        ),
        "bool_objects": pd.DataFrame(
            {"b": pd.Series([True, False, None] * 10, dtype=object)}
        ),
    }


@pytest.mark.parametrize("label", sorted(_hostile_frames()))
def test_hostile_frames_never_raise_and_stay_json_clean(label: str) -> None:
    fp = build_fingerprint(_hostile_frames()[label])
    assert json.loads(fp.to_json())["column_count"] == len(fp.columns)
    again = build_fingerprint(_hostile_frames()[label])
    assert again.fingerprint_hash() == fp.fingerprint_hash()


def test_infinities_are_left_out_of_the_statistics_and_flagged() -> None:
    column_ = _column(build_fingerprint(_hostile_frames()["nan_and_inf"]), "x")
    assert Issue.NON_FINITE in column_.issues
    assert column_.distribution is not None and column_.distribution.maximum == 2.0


def test_one_unhashable_value_deep_in_a_text_column_makes_it_unsupported_not_fatal() -> (
    None
):
    frame = pd.DataFrame({"t": ["a", "b"] * 150 + [["late", "list"]]})
    column_ = _column(build_fingerprint(frame), "t")
    assert column_.issues == (Issue.UNSUPPORTED_TYPE,) and not column_.usable


def test_unsupported_values_are_unusable_not_fatal() -> None:
    fp = build_fingerprint(_hostile_frames()["lists_and_dicts"])
    assert all(
        c.issues == (Issue.UNSUPPORTED_TYPE,) and not c.usable for c in fp.columns
    )


def test_a_huge_integer_id_keeps_its_distinct_count() -> None:
    column_ = _column(build_fingerprint(_hostile_frames()["huge_ints"]), "i")
    assert column_.distinct == 30  # float64 would have collapsed 2**62 + k to one value


def test_ten_thousand_columns_finish_inside_a_time_budget() -> None:
    frame = pd.DataFrame(np.arange(40.0).reshape(4, 10).repeat(1_000, axis=1))
    frame.columns = [f"c{i}" for i in range(frame.shape[1])]
    fp = build_fingerprint(frame, time_budget=2.0)
    assert fp.column_count == 10_000 and fp.shape == "wide"
    json.loads(fp.to_json())


# ------------------------------------------------- regressions found by the independent review


def test_a_span_of_centuries_does_not_overflow_nanoseconds() -> None:
    frame = pd.DataFrame({"d": pd.date_range("1700-01-01", "2020-01-01", freq="YS")})
    structure = _column(build_fingerprint(frame), "d").time
    assert structure is not None and structure.granularity == "year"


def test_opposite_float_extremes_do_not_break_the_histogram() -> None:
    frame = pd.DataFrame({"x": [-1e308, 0.0, 1e308] * 50})
    fp = build_fingerprint(frame)
    assert not any(note.startswith("stage_failed") for note in fp.notes)
    assert json.loads(fp.to_json())["columns"][0]["role"] == "measure"


def test_numpy_string_cells_and_surrogates_are_plain_text() -> None:
    dates = pd.DataFrame(
        {"c": list(np.array(["2020-01-01", "2020-01-02", "2020-02-03"] * 20))}
    )
    assert _column(build_fingerprint(dates), "c").role is SemanticRole.TIME
    odd = pd.DataFrame({"c": pd.Series(["\ud800", "a", "b"] * 20, dtype=object)})
    assert _column(build_fingerprint(odd), "c").role is SemanticRole.DIMENSION


def test_a_timezone_does_not_turn_a_daily_series_into_an_hourly_one() -> None:
    aware = pd.DataFrame(
        {"d": pd.date_range("2024-01-01", periods=365, freq="D", tz="America/New_York")}
    )
    offsets = pd.DataFrame(
        {
            "d": [
                f"2024-{m:02d}-15T00:00:00{'-05:00' if m < 4 or m > 10 else '-04:00'}"
                for m in range(1, 13)
            ]
            * 3
        }
    )
    for frame in (aware, offsets):
        structure = _column(build_fingerprint(frame), "d").time
        assert structure is not None and structure.regularity >= 0.9
    day = _column(build_fingerprint(aware), "d").time
    assert day is not None and day.granularity == "day"


def test_a_coded_categorical_is_a_dimension_not_unsupported() -> None:
    frame = pd.DataFrame(
        {
            "pclass": pd.Categorical([1, 2, 3, 1, 2, 3] * 20),
            "bin": pd.cut(pd.Series(np.arange(120.0)), bins=6),
        }
    )
    fp = build_fingerprint(frame)
    assert _column(fp, "pclass").role is SemanticRole.DIMENSION
    assert _column(fp, "bin").role is SemanticRole.DIMENSION
    assert not any(c.issues for c in fp.columns)


def test_the_dtype_is_a_closed_name_that_cannot_carry_a_value() -> None:
    sparse = pd.DataFrame(
        {
            "x": pd.arrays.SparseArray(
                ["secret-a"] * 50 + ["b"] * 5, fill_value="secret-a"
            )
        }
    )
    assert "secret-a" not in build_fingerprint(sparse).to_json()
    vocabulary = {
        "boolean", "categorical", "complex", "datetime", "decimal", "float",
        "integer", "other", "text", "timedelta",
    }  # fmt: skip
    for frame in list(_hostile_frames().values()) + [sparse]:
        assert {c.dtype for c in build_fingerprint(frame).columns} <= vocabulary


def test_white_noise_is_rarely_called_seasonal_and_a_real_cycle_is_found() -> None:
    rng = np.random.default_rng(0)
    days = pd.date_range("2024-01-01", periods=24, freq="D")
    flagged = sum(
        build_fingerprint(pd.DataFrame({"d": days, "v": rng.normal(size=24)}))
        .time_signals[0]
        .seasonality_lag
        is not None
        for _ in range(200)
    )
    assert flagged <= 14  # 7 %; it was 21 % with a bare 0.3 threshold
    weekly = pd.DataFrame(
        {
            "d": pd.date_range("2024-01-01", periods=84, freq="D"),
            "v": np.sin(np.arange(84) * 2 * np.pi / 7),
        }
    )
    assert build_fingerprint(weekly).time_signals[0].seasonality_lag == 7


def test_a_dropped_row_takes_a_series_off_its_grid_so_no_lag_is_reported() -> None:
    values = np.sin(np.arange(84) * 2 * np.pi / 7)
    values[::3] = np.nan
    frame = pd.DataFrame(
        {"d": pd.date_range("2024-01-01", periods=84, freq="D"), "v": values}
    )
    assert build_fingerprint(frame).time_signals[0].seasonality_lag is None


def test_a_float_noise_zero_has_no_sign() -> None:
    frame = pd.DataFrame({"y": np.sin(np.linspace(0, 20 * np.pi, 101))})
    assert "-0.0" not in build_fingerprint(frame).to_json()


def test_the_order_of_the_file_is_recorded_for_an_exact_fingerprint_only() -> None:
    frame = pd.DataFrame(
        {
            "falling": [100.0, 80.0, 80.0, 40.0, 10.0],
            "rising": [1.0, 2.0, 2.0, 5.0, 9.0],
            "jagged": [5.0, 1.0, 9.0, 2.0, 7.0],
            "flat": [3.0] * 5,
            "when": pd.date_range("2024-01-01", periods=5, freq="D"),
        }
    )
    fp = build_fingerprint(frame)
    order = {c.name: c.row_order for c in fp.columns}
    assert order == {
        "falling": "descending",
        "rising": "ascending",
        "jagged": "mixed",
        "flat": "flat",
        "when": "ascending",
    }
    # A sample has lost the order of the file, so it records none rather than a wrong one.
    big = pd.DataFrame({"v": np.arange(200.0)[::-1]})
    assert build_fingerprint(big, sample_rows=50).columns[0].row_order is None
    assert build_fingerprint(big).columns[0].row_order == "descending"


def test_a_funnel_shaped_measure_is_told_apart_from_a_budget_by_its_order() -> None:
    funnel = _column(_fingerprint_of("funnel_stages"), "users")
    budget = _column(_fingerprint_of("budget_vs_actual"), "budget")
    assert funnel.row_order == "descending"
    assert budget.row_order == "mixed"


def test_name_tokens_split_on_punctuation_and_camel_case_and_match_whole_words() -> (
    None
):
    from uadas_core.analysis.fingerprint import name_tokens

    assert name_tokens("openPrice") == ["open", "price"]
    assert name_tokens("Open_Price-adj") == ["open", "price", "adj"]
    assert "low" in name_tokens("day_low") and "low" not in name_tokens("flow")
    assert name_tokens("") == [] and name_tokens("___") == []


def test_a_stage_that_raises_is_recorded_by_name_and_never_escapes(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise ValueError("a cell value: ACME-SECRET-7731")

    monkeypatch.setattr("uadas_core.analysis.fingerprint._distribution", boom)
    monkeypatch.setattr("uadas_core.analysis.fingerprint._hierarchies", boom)
    frame = pd.DataFrame({"v": np.arange(40.0), "k": ["a", "b"] * 20})
    with caplog.at_level("WARNING"):
        fp = build_fingerprint(frame)
    assert {"stage_failed:distribution", "stage_failed:hierarchies"} <= set(fp.notes)
    assert fp.confidence < 1.0 and _column(fp, "v").distribution is None
    assert "ACME-SECRET-7731" not in fp.to_json()
    assert "ACME-SECRET-7731" not in caplog.text and "ValueError" in caplog.text


def test_a_column_that_cannot_be_classified_is_marked_not_analysed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("never shown")

    monkeypatch.setattr("uadas_core.analysis.fingerprint._classify", boom)
    fp = build_fingerprint(pd.DataFrame({"v": np.arange(5.0)}))
    column_ = _column(fp, "v")
    assert column_.issues == (Issue.NOT_ANALYSED,) and not column_.usable
    assert "stage_failed:classify" in fp.notes


def test_a_sentinel_end_date_is_never_reported_as_all_null() -> None:
    frame = pd.DataFrame({"valid_to": [dt.date(9999, 12, 31)] * 30})
    assert Issue.ALL_NULL not in _column(build_fingerprint(frame), "valid_to").issues


def test_only_a_real_function_between_dimensions_is_a_hierarchy() -> None:
    frame = pd.DataFrame(
        {
            "city": [
                f"c{i % 20}" for i in range(80)
            ],  # 20 cities, each in exactly one state
            "state": [f"s{(i % 20) % 5}" for i in range(80)],
            "shop": [f"x{i % 8}" for i in range(80)],  # unrelated to city or state
        }
    )
    fp = build_fingerprint(frame)
    pairs = {
        (fp.columns[h.child].name, fp.columns[h.parent].name) for h in fp.hierarchies
    }
    assert pairs == {("city", "state")}


# --------------------------------------------------------------------------------- the fuzz


@st.composite
def _frames(draw: st.DrawFn) -> pd.DataFrame:
    kinds = draw(
        st.lists(
            st.sampled_from(["float", "int", "bool", "str", "datetime"]),
            min_size=0,
            max_size=6,
        )
    )
    # Up to 150 rows so that, with a sample cap above 100, the histogram branch (>= 100 finite values) runs.
    rows = draw(st.integers(min_value=0, max_value=150))
    columns = []
    for index, kind in enumerate(kinds):
        if kind == "float":
            columns.append(
                column(f"c{index}", elements=st.floats(width=64), dtype=float)
            )
        elif kind == "int":
            columns.append(
                column(
                    f"c{index}",
                    elements=st.integers(min_value=-(2**40), max_value=2**40),
                    dtype="int64",
                )
            )
        elif kind == "bool":
            columns.append(column(f"c{index}", elements=st.booleans(), dtype=bool))
        elif kind == "str":
            columns.append(
                column(f"c{index}", elements=st.text(max_size=12), dtype=object)
            )
        else:
            columns.append(
                column(
                    f"c{index}",
                    elements=st.datetimes(
                        # Wide enough that a series can span more than 292 years (int64 nanoseconds).
                        min_value=dt.datetime(1700, 1, 1),
                        max_value=dt.datetime(2250, 1, 1),
                    ),
                    dtype="datetime64[ns]",
                )
            )
    return draw(data_frames(columns, index=range_indexes(min_size=rows, max_size=rows)))


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(frame=_frames(), sample_rows=st.integers(min_value=5, max_value=200))
def test_property_any_frame_gives_a_valid_deterministic_fingerprint(
    frame: pd.DataFrame, sample_rows: int
) -> None:
    fp = build_fingerprint(frame, sample_rows=sample_rows)
    assert fp.rows == len(frame) and fp.column_count == frame.shape[1]
    assert fp.sampled_rows == min(len(frame), sample_rows)
    assert 0.0 <= fp.confidence <= 1.0
    assert all(
        0.0 <= c.missing_share <= 1.0 and 0.0 <= c.role_confidence <= 1.0
        for c in fp.columns
    )
    assert all(c.role is not SemanticRole.UNKNOWN for c in fp.columns if c.usable)
    for pair in fp.correlations:
        assert 0 <= pair.left < pair.right < fp.column_count
        assert -1.0 <= pair.pearson <= 1.0
    json.loads(fp.to_json())  # no NaN, no inf: allow_nan=False raises otherwise
    assert build_fingerprint(frame, sample_rows=sample_rows).to_json() == fp.to_json()
