# File: apps/api/tests/test_stages_fingerprint.py
"""Fingerprinting a stored frame (CI.1): the streamed pass, the DuckDB lockdown and the 1M-row budget.

The core's rules are proved in ``tests/analysis/test_fingerprint.py``; this file proves what only the API
side can break: that the sample is uniform over the *file* (not its head) and exactly sized, that the counts
DuckDB adds are right, that the engine really cannot touch a file or an extension (the CI.0 section 3
posture, one refusal per statement), that no tenant text reaches the SQL, that a failing engine degrades to a
sample-only fingerprint instead of an error, and that 1M rows by 20 columns stay inside twice the 2 s budget
of the plan (the margin absorbs a slow shared runner; CI.0 measured about 1.5 s here).
"""

from __future__ import annotations

import gc
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from uadas_api.stages import fingerprint as stage
from uadas_core.analysis.fingerprint import (
    CardinalityClass,
    Issue,
    SemanticRole,
    build_fingerprint,
)

ROWS = 20_000
SAMPLE = 2_000


def _frame(rows: int = ROWS) -> pd.DataFrame:
    rng = np.random.default_rng(5)
    return pd.DataFrame(
        {
            "when": pd.date_range("2024-01-01", periods=rows, freq="min"),
            "uid": [f"u{i}" for i in range(rows)],
            "region": rng.choice(["n", "s", "e", "w"], rows),
            "amount": rng.gamma(2.0, 40.0, rows),
            "maybe": [None if i % 4 == 0 else "x1" for i in range(rows)],
        }
    )


def _write(tmp_path: Path, frame: pd.DataFrame, group: int = 3_000) -> pq.ParquetFile:
    path = tmp_path / "frame.parquet"
    pq.write_table(pa.Table.from_pandas(frame), path, row_group_size=group)
    return pq.ParquetFile(path)


def test_a_small_frame_is_read_whole_and_fingerprinted_exactly(tmp_path: Path) -> None:
    frame = _frame(500)
    fingerprint = stage.fingerprint_frame(_write(tmp_path, frame))
    direct = build_fingerprint(frame)
    assert fingerprint.rows == 500 and fingerprint.sampled_rows == 500
    assert fingerprint.notes == () and fingerprint.confidence == 1.0
    assert [c.role for c in fingerprint.columns] == [c.role for c in direct.columns]


def test_a_large_frame_is_streamed_into_an_exact_sample_with_whole_file_counts(
    tmp_path: Path,
) -> None:
    pf = _write(tmp_path, _frame())
    fingerprint = stage.fingerprint_frame(pf, sample_rows=SAMPLE)
    assert fingerprint.rows == ROWS and fingerprint.sampled_rows == SAMPLE
    assert "sampled" in fingerprint.notes and "no_source_stats" not in fingerprint.notes

    columns = {c.name: c for c in fingerprint.columns}
    assert columns["maybe"].missing_share == 0.25  # DuckDB's exact non-null count
    uid = columns[
        "uid"
    ]  # a sample of 2,000 cannot see 20,000 distinct ids; the whole-file count can
    assert uid.cardinality is CardinalityClass.UNIQUE_KEY and not uid.distinct_exact
    assert abs(uid.distinct - ROWS) / ROWS < 0.05
    assert uid.role is SemanticRole.IDENTIFIER
    assert columns["region"].distinct == 4


def test_the_sample_is_uniform_over_the_file_not_its_head(tmp_path: Path) -> None:
    fingerprint = stage.fingerprint_frame(
        _write(tmp_path, _frame()), sample_rows=SAMPLE
    )
    when = next(c for c in fingerprint.columns if c.name == "when").time
    assert when is not None
    # The file spans 13.9 days; its first 2,000 rows (a head sample) would span 1.4.
    assert when.span_seconds > 13 * 86_400


def test_the_same_file_gives_a_byte_identical_fingerprint(tmp_path: Path) -> None:
    pf = _write(tmp_path, _frame())
    first = stage.fingerprint_frame(pf, sample_rows=SAMPLE, seed=9)
    second = stage.fingerprint_frame(pf, sample_rows=SAMPLE, seed=9)
    assert first.to_json() == second.to_json()


def test_a_nested_column_is_left_out_of_the_engine_and_flagged(tmp_path: Path) -> None:
    frame = _frame()
    frame["tags"] = [["a", "b"]] * len(frame)
    fingerprint = stage.fingerprint_frame(_write(tmp_path, frame), sample_rows=SAMPLE)
    tags = next(c for c in fingerprint.columns if c.name == "tags")
    assert tags.issues == (Issue.UNSUPPORTED_TYPE,)
    assert fingerprint.rows == ROWS and any(c.usable for c in fingerprint.columns)


def test_hostile_column_names_never_reach_the_sql(tmp_path: Path) -> None:
    odd = ['x"; DROP TABLE t; --', "c0", "'; COPY t TO 'leak.csv'; --", ""]
    frame = pd.DataFrame({name: np.arange(ROWS, dtype=float) for name in odd})
    fingerprint = stage.fingerprint_frame(_write(tmp_path, frame), sample_rows=SAMPLE)
    assert [c.name for c in fingerprint.columns] == odd
    assert not (tmp_path / "leak.csv").exists()


def test_a_failing_engine_degrades_to_a_sample_only_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> duckdb.DuckDBPyConnection:
        raise duckdb.Error("simulated engine failure with a value 'secret-cell'")

    monkeypatch.setattr(stage, "locked_connection", broken)
    fingerprint = stage.fingerprint_frame(
        _write(tmp_path, _frame()), sample_rows=SAMPLE
    )
    assert fingerprint.sampled_rows == SAMPLE and fingerprint.rows == ROWS
    assert "no_source_stats" in fingerprint.notes
    assert "secret-cell" not in fingerprint.to_json()


def test_a_categorical_column_keeps_its_whole_file_counts(tmp_path: Path) -> None:
    # Parquet hands a pandas categorical back as a dictionary array; leaving those out of the engine would
    # have dropped their whole-file null and distinct counts and fallen back to the sample.
    frame = _frame()
    frame["tier"] = pd.Categorical(
        [None if i % 5 == 0 else f"t{i % 7}" for i in range(ROWS)]
    )
    pf = _write(tmp_path, frame)
    assert str(pf.schema_arrow.field("tier").type).startswith("dictionary")
    fingerprint = stage.fingerprint_frame(pf, sample_rows=SAMPLE)
    tier = next(c for c in fingerprint.columns if c.name == "tier")
    assert tier.missing_share == 0.2 and tier.distinct == 7


def test_a_file_wider_than_the_cap_is_cut_and_says_so(tmp_path: Path) -> None:
    width = stage.MAX_COLUMNS + 200
    frame = pd.DataFrame({f"c{i}": np.arange(3_000, dtype=float) for i in range(width)})
    pf = _write(tmp_path, frame, group=1_000)
    for sample_rows in (500, 5_000):  # the streamed path and the read-whole path
        fingerprint = stage.fingerprint_frame(pf, sample_rows=sample_rows)
        assert fingerprint.column_count == stage.MAX_COLUMNS
        assert "columns_truncated" in fingerprint.notes
        assert fingerprint.columns[-1].name == f"c{stage.MAX_COLUMNS - 1}"
        assert fingerprint.rows == 3_000


def test_a_footer_that_under_declares_its_rows_cannot_grow_the_sample(
    tmp_path: Path,
) -> None:
    pf = _write(tmp_path, _frame(1_000))
    kept: list[pa.RecordBatch] = []
    for _ in stage._feed(
        pf,
        width=5,
        read_columns=None,
        engine_columns=[],
        total_rows=100,  # the file really holds 1,000 rows
        sample_rows=50,
        seed=0,
        kept=kept,
    ):
        pass
    assert sum(b.num_rows for b in kept) == 50


def test_a_failure_in_the_middle_of_the_stream_degrades_to_the_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pf = _write(tmp_path, _frame())
    real = pq.ParquetFile.iter_batches
    calls = {"n": 0}

    def flaky(self: pq.ParquetFile, *args: object, **kwargs: object) -> object:
        calls["n"] += 1
        batches = real(self, *args, **kwargs)
        if calls["n"] > 1:
            yield from batches
            return
        yield next(iter(batches))
        raise pa.ArrowInvalid("mid-stream failure quoting 'secret-cell'")

    monkeypatch.setattr(pq.ParquetFile, "iter_batches", flaky)
    fingerprint = stage.fingerprint_frame(pf, sample_rows=SAMPLE)
    assert calls["n"] == 2  # the engine pass failed, the sample-only pass succeeded
    assert fingerprint.sampled_rows == SAMPLE
    assert "no_source_stats" in fingerprint.notes
    assert "secret-cell" not in fingerprint.to_json()


# ------------------------------------------------------------------------- the engine lockdown


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM read_parquet('{path}')",
        "SELECT * FROM read_csv('{path}')",
        "SELECT * FROM glob('*')",
        "SELECT * FROM read_text('{path}')",
        "SELECT * FROM read_blob('{path}')",
        "SELECT * FROM parquet_scan('{path}')",
        "SELECT * FROM '{path}'",
        "SELECT * FROM sniff_csv('{path}')",
        "SELECT * FROM duckdb_extensions()",
        "CREATE SECRET s (TYPE S3, KEY_ID 'a', SECRET 'b')",
        "EXPORT DATABASE '{out}'",
        "COPY (SELECT 1 AS a) TO '{out}'",
        "INSTALL httpfs",
        "LOAD httpfs",
        "ATTACH '{out}.db' AS leak",
        "SET enable_external_access=true",
        "SET lock_configuration=false",
        "SET autoload_known_extensions=true",
    ],
)
def test_the_engine_refuses_everything_that_reaches_beyond_a_registered_table(
    tmp_path: Path, statement: str
) -> None:
    _write(tmp_path, _frame(100))
    connection = stage.locked_connection()
    try:
        with pytest.raises(duckdb.Error):
            connection.execute(
                statement.format(
                    path=(tmp_path / "frame.parquet").as_posix(),
                    out=(tmp_path / "out").as_posix(),
                )
            )
    finally:
        connection.close()
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "out.db").exists()


def test_the_engine_still_aggregates_a_registered_arrow_reader() -> None:
    table = pa.table({"c0": [1, 2, None, 4]})
    connection = stage.locked_connection()
    try:
        connection.register(
            "t", pa.RecordBatchReader.from_batches(table.schema, table.to_batches())
        )
        row = connection.execute(
            "SELECT count(c0), approx_count_distinct(c0) FROM t"
        ).fetchone()
    finally:
        connection.close()
    assert row == (3, 3)


# --------------------------------------------------------------------------------- the budget


def _million_row_file(path: Path) -> None:
    """The 20-column frame CI.0 measured: 8 floats, 4 ints, 3 categoricals, an id, 2 times, a flag, a sparse."""
    n = 1_000_000
    rng = np.random.default_rng(0)
    columns: dict[str, object] = {}
    for i in range(8):
        columns[f"f{i}"] = rng.lognormal(3, 1, n) if i % 2 else rng.normal(0, 1, n)
    for i in range(4):
        columns[f"i{i}"] = rng.integers(0, 10 ** (i + 2), n)
    for name, k in (("cat5", 5), ("cat50", 50), ("cat5k", 5000)):
        columns[name] = np.array([f"{name}_{j}" for j in range(k)])[
            rng.integers(0, k, n)
        ]
    columns["id"] = np.char.add("u", np.arange(n).astype(str))
    columns["ts"] = pd.date_range("2024-01-01", periods=n, freq="min")
    columns["ts2"] = pd.Timestamp("2020-01-01") + pd.to_timedelta(
        rng.integers(0, 10**8, n), unit="s"
    )
    columns["flag"] = rng.random(n) < 0.1
    columns["sparse"] = np.where(rng.random(n) < 0.9, np.nan, rng.normal(size=n))
    # Written the way ingest writes (``DataFrame.to_parquet``), where a NaN becomes a null; building the Arrow
    # table straight from numpy would keep NaN as a value and the footer would rightly report no nulls.
    pd.DataFrame(columns).to_parquet(path, index=False, row_group_size=100_000)


def test_one_million_rows_by_twenty_columns_fit_the_budget(tmp_path: Path) -> None:
    path = tmp_path / "million.parquet"
    _million_row_file(path)
    gc.collect()
    pf = pq.ParquetFile(path)

    started = time.perf_counter()
    fingerprint = stage.fingerprint_frame(pf)
    elapsed = time.perf_counter() - started

    assert (
        elapsed < 4.0
    ), f"fingerprint took {elapsed:.2f}s (plan budget 2 s, test allows 2x)"
    assert fingerprint.rows == 1_000_000 and fingerprint.sampled_rows == 100_000
    assert fingerprint.column_count == 20 and not fingerprint.partial
    columns = {c.name: c for c in fingerprint.columns}
    assert abs(columns["sparse"].missing_share - 0.9) < 0.005
    assert columns["id"].role is SemanticRole.IDENTIFIER
    assert columns["cat50"].distinct == 50
    ts = columns["ts"].time
    assert ts is not None and ts.granularity == "minute"
    assert (ts.coverage or 0.0) >= 0.9
    print(f"\nfingerprint of 1M x 20: {elapsed:.2f}s")
