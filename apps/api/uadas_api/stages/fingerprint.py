# File: apps/api/uadas_api/stages/fingerprint.py
"""Fingerprint a stored dataset frame without loading it whole (chart intelligence, CI.1).

``uadas_core.analysis.fingerprint`` describes a pandas frame; this module is the one place that turns a
Parquet object of any size into the two inputs it wants -- a uniformly random, seeded sample, and the
whole-dataset facts a sample cannot give (null counts and approximate distinct counts) -- in **one streamed
pass** over the record batches. CI.0 measured it (``plans/phase-4-ci0-findings.md`` section 6.2): about 1.5 s
for 1M rows by 20 columns, against 3.7 s for a full pandas read, so the budget of 2 s holds and Polars stays out.

Why this module, and only this one, imports ``duckdb`` (``.importlinter`` contract
``duckdb-only-in-the-fingerprint-module``): DuckDB is a second engine over the data, so the rules of CI.0
section 3 are enforced here, in one reviewable place, instead of being a habit of every caller:

* the connection is created with external access, extension install and autoload off, then
  ``lock_configuration`` is set, so the engine **cannot read a file, load an extension, attach a database or
  write**; ``test_stages_fingerprint.py`` proves each refusal. DuckDB therefore parses no bytes: Parquet is
  still decoded by pyarrow (as in ``frames.py``), so DuckDB adds no new parser to the web process and does not
  belong in the sandbox-boundary probe;
* it queries one registered Arrow ``RecordBatchReader`` and nothing else, never a path;
* **no tenant text reaches the SQL**: columns are renamed ``c0 .. cN`` before registration, so the statement
  contains only integers (column names are tenant text, and bandit skips B608).

The stream is the sampling pass too: each batch contributes its share of the sample to a seeded generator,
so the sample is uniform over the file (not its head) and its size is exact. Memory is a batch plus the
sample, not the frame (CI.0: the process peaks near 0.63 GB at 1M rows, so a worker running this needs a
memory limit of at least 1 GB at that size).

Bounds this module does enforce: at most :data:`MAX_COLUMNS` columns are read and fingerprinted (a wider file
gets the first ones and the ``columns_truncated`` note: the sample holds every column it reads, so memory is
sample rows x width, not a fixed amount); only those columns are decoded; the sample never exceeds
``sample_rows`` however the footer's row count compares with the rows actually streamed; and DuckDB may not
spill to disk (``max_temp_directory_size`` 0) nor use more than its memory limit.

What this does not do: bound the stream's own duration. The core's ``time_budget`` cuts the CPU stages that
follow it; reading a very large object is bounded by ``max_object_bytes`` and the job's time limit, as it is
for every other whole-frame read. Nor does it bound the *decoded* size of a small file (a constant column
decompresses by a large factor): the worker's memory limit does. A corrupt file raises a pyarrow exception
whose text can quote a field name, so the caller (CI.5's job handler) logs the class, never ``str(exc)``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import replace

import duckdb
import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa
import pyarrow.parquet as pq

from uadas_core.analysis.fingerprint import (
    SAMPLE_ROWS,
    ColumnSourceStats,
    DataFingerprint,
    SourceStats,
    build_fingerprint,
)

_logger = logging.getLogger(__name__)

_STREAM_BATCH_ROWS = 65_536
# Columns read and fingerprinted. A wider file is cut here (note ``columns_truncated``): each column costs
# memory in the sample and two aggregates in the statement.
MAX_COLUMNS = 1_000
# DuckDB's own allocations only (aggregate state is a few KB per column); the Arrow batches it scans are
# owned by pyarrow. Two threads keep a worker from taking every core of a shared host.
_DUCKDB_MEMORY_LIMIT = "512MB"
_DUCKDB_THREADS = 2


def locked_connection() -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB that can see only what is registered on it.

    The statements that would reach beyond that (``read_parquet``, ``COPY``, ``INSTALL``, ``ATTACH``, turning
    the switches back on) are refused; ``tests/test_stages_fingerprint.py`` runs each one.
    """
    connection = duckdb.connect(
        ":memory:",
        config={
            "enable_external_access": False,
            "autoinstall_known_extensions": False,
            "autoload_known_extensions": False,
            "memory_limit": _DUCKDB_MEMORY_LIMIT,
            "threads": _DUCKDB_THREADS,
            # No spilling: a query that would need disk fails instead of writing under the worker's cwd.
            "max_temp_directory_size": "0B",
            # A streamed aggregate does not need row order, and keeping it costs buffering.
            "preserve_insertion_order": False,
        },
    )
    connection.execute("SET lock_configuration=true")
    return connection


def _engine_supports(dtype: pa.DataType) -> bool:
    """Whether a column is handed to DuckDB (nested types are left to the sample alone).

    Dictionary arrays are supported: a pandas categorical comes back from Parquet as one, and leaving it out
    would silently drop its whole-file counts.
    """
    return not pa.types.is_nested(dtype)


def _read_columns(pf: pq.ParquetFile) -> tuple[int, list[str] | None]:
    """``(width, names to decode)``: the columns fingerprinted, and a pruning list when it is safe.

    ``None`` means decode everything (the file is no wider than the cap, or repeats a column name in the
    part we keep, where naming columns would be ambiguous); the caller keeps the first ``width`` either way.
    """
    names = [str(name) for name in pf.schema_arrow.names]
    width = min(len(names), MAX_COLUMNS)
    kept = names[:width]
    prune = len(names) > width and len(set(kept)) == width
    return width, kept if prune else None


def _feed(
    pf: pq.ParquetFile,
    width: int,
    read_columns: list[str] | None,
    engine_columns: list[int],
    total_rows: int,
    sample_rows: int,
    seed: int,
    kept: list[pa.RecordBatch],
) -> Iterator[pa.RecordBatch]:
    """Stream the file once: keep this batch's share of the sample, yield the engine's columns.

    The target is cumulative (``round(sample_rows * seen / total)``), so the sample is exactly
    ``sample_rows`` long however the batches fall, and every row has the same chance of being picked. ``seen``
    is capped at the footer's row count, so a footer that under-declares the rows cannot grow the sample.
    """
    rng = np.random.default_rng(seed)
    renamed = [f"c{i}" for i in range(len(engine_columns))]
    seen = taken = 0
    for full in pf.iter_batches(batch_size=_STREAM_BATCH_ROWS, columns=read_columns):
        batch = full.select(list(range(width)))
        seen += batch.num_rows
        target = round(sample_rows * min(seen, total_rows) / max(total_rows, 1))
        want = max(0, min(target - taken, batch.num_rows))
        if want:
            picks = np.sort(rng.choice(batch.num_rows, size=want, replace=False))
            kept.append(batch.take(pa.array(picks)))
            taken += want
        yield batch.select(engine_columns).rename_columns(renamed)


def _whole_dataset_stats(
    pf: pq.ParquetFile,
    width: int,
    read_columns: list[str] | None,
    engine_columns: list[int],
    total_rows: int,
    sample_rows: int,
    seed: int,
    kept: list[pa.RecordBatch],
) -> SourceStats:
    """One pass: the sample into ``kept`` and, from DuckDB, each column's non-null and distinct counts."""
    stats = [ColumnSourceStats() for _ in range(width)]
    stream = _feed(
        pf, width, read_columns, engine_columns, total_rows, sample_rows, seed, kept
    )
    if not engine_columns:
        # Every column is nested: nothing for the engine, but the sample still needs the pass.
        for _ in stream:
            pass
        return SourceStats(row_count=total_rows, columns=tuple(stats))

    schema = pa.schema(
        [
            pa.field(f"c{i}", pf.schema_arrow.field(position).type)
            for i, position in enumerate(engine_columns)
        ]
    )
    # Only integers are formatted into the statement; no tenant text can reach it.
    select = ", ".join(
        f"count(c{i}), approx_count_distinct(c{i})" for i in range(len(engine_columns))
    )
    connection = locked_connection()
    try:
        connection.register("t", pa.RecordBatchReader.from_batches(schema, stream))
        row = connection.execute(f"SELECT {select} FROM t").fetchone()
    finally:
        connection.close()
    if (
        row is None
    ):  # an aggregate over no rows still returns one row; kept for the type checker
        return SourceStats(row_count=total_rows, columns=tuple(stats))
    for i, position in enumerate(engine_columns):
        non_null, distinct = int(row[2 * i]), int(row[2 * i + 1])
        stats[position] = ColumnSourceStats(
            null_count=max(total_rows - non_null, 0), distinct_count=distinct
        )
    return SourceStats(row_count=total_rows, columns=tuple(stats))


def fingerprint_frame(
    pf: pq.ParquetFile,
    *,
    seed: int = 0,
    sample_rows: int = SAMPLE_ROWS,
    time_budget: float | None = None,
) -> DataFingerprint:
    """The :class:`DataFingerprint` of the dataset behind ``pf``.

    A frame of at most ``sample_rows`` rows is read whole and fingerprinted exactly. A larger one is
    streamed once (see the module docstring); if DuckDB itself fails the sample is taken again without it and
    the fingerprint says so (``no_source_stats``, a lower confidence) instead of failing.

    Args:
        pf: A Parquet reader over the dataset (``frames.parquet_file``). Not closed here.
        seed: Seed of the sample and of every random choice in the core, so equal data gives an equal result.
        sample_rows: Rows the statistics are computed from.
        time_budget: Seconds after which the core skips its remaining stages (a partial fingerprint).
    """
    total_rows = int(pf.metadata.num_rows)
    width, read_columns = _read_columns(pf)
    truncated = len(pf.schema_arrow.names) > width

    if total_rows <= sample_rows:
        frame: pd.DataFrame = pf.read(columns=read_columns).to_pandas()
        fingerprint = build_fingerprint(
            frame.iloc[:, :width],
            seed=seed,
            sample_rows=sample_rows,
            time_budget=time_budget,
        )
        return _mark_truncated(fingerprint) if truncated else fingerprint

    schema = pa.schema(list(pf.schema_arrow)[:width])
    engine_columns = [
        i for i, field in enumerate(schema) if _engine_supports(field.type)
    ]
    kept: list[pa.RecordBatch] = []
    try:
        source = _whole_dataset_stats(
            pf,
            width,
            read_columns,
            engine_columns,
            total_rows,
            sample_rows,
            seed,
            kept,
        )
    except duckdb.Error:
        # The message of an engine error can quote a value; log the class of failure only.
        _logger.warning("fingerprint: the DuckDB pass failed; using the sample alone")
        kept.clear()
        for _ in _feed(
            pf, width, read_columns, [], total_rows, sample_rows, seed, kept
        ):
            pass
        source = SourceStats(row_count=total_rows)

    # ``schema`` keeps an empty sample (a footer that over-declares its rows) a valid zero-row table.
    sample: pd.DataFrame = pa.Table.from_batches(kept, schema=schema).to_pandas()
    fingerprint = build_fingerprint(
        sample,
        source=source,
        seed=seed,
        sample_rows=sample_rows,
        time_budget=time_budget,
    )
    return _mark_truncated(fingerprint) if truncated else fingerprint


def _mark_truncated(fingerprint: DataFingerprint) -> DataFingerprint:
    """Record that the file had more than :data:`MAX_COLUMNS` columns and only the first were read."""
    return replace(
        fingerprint,
        notes=(*fingerprint.notes, "columns_truncated"),
        confidence=round(fingerprint.confidence * 0.9, 6),
    )
