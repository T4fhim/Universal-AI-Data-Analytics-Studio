# File: apps/api/uadas_api/stages/frames.py
"""Reading a stored dataset frame without loading the whole frame into the web process.

Why this module: a dataset's rows live in object storage as one Parquet object (3.5). The web
process must serve a *page* of it (preview), a *summary* of its columns and a bounded *sample* for
a chart; only a worker loads a whole frame (:func:`load_dataframe`). The rules, all verified by
``tests/test_web_frames.py``:

* the object is fetched through ``TenantObjectStore.open`` (key re-validated against the
  organization, size capped, SHA-256 verified) into a spooled temporary file -- bytes go to disk,
  never into one in-memory ``bytes``;
* a page is produced by streaming record batches of **only the row groups that hold it**
  (``iter_batches``), so memory is bounded by a batch plus one compressed row group, not by the
  frame; an offset deep into the file skips whole row groups by their row counts without decoding;
* a *sorted* page reads **one column** (the validated sort column), takes the page's row ids from
  its sort order and then streams only the row groups that contain those ids;
* column summaries come from the Parquet footer statistics (null count, min, max) with no data read.

What it does not do: range-read the object (the store has no ranged ``GET`` yet, so the file is
transferred to the temporary spool; the deployment's ``max_object_bytes`` bounds that), cache pages,
or sort a frame of more than ``ApiConfig.preview_max_sort_rows`` rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, BinaryIO

import pandas as pd  # type: ignore[import-untyped]
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from uadas_api.jobs.errors import JobError, JobErrorCode
from uadas_api.storage.store import TenantObjectStore
from uadas_api.workspaces.models import DatasetRecord

_BATCH_ROWS = 8192


def open_frame(store: TenantObjectStore, record: DatasetRecord) -> BinaryIO:
    """A verified, seekable stream of ``record``'s Parquet object. The caller closes it."""
    return store.open(record.storage_key, expected_sha256=record.sha256 or None)


def parquet_file(handle: BinaryIO) -> pq.ParquetFile:
    """A Parquet reader over ``handle`` (reads the footer only)."""
    return pq.ParquetFile(handle)


def column_names(pf: pq.ParquetFile) -> list[str]:
    """The frame's column names, in order."""
    return [str(name) for name in pf.schema_arrow.names]


def column_types(pf: pq.ParquetFile) -> list[tuple[str, str]]:
    """``(name, arrow type)`` for every column."""
    return [(str(f.name), str(f.type)) for f in pf.schema_arrow]


# ------------------------------------------------------------------------- pages


def _group_starts(pf: pq.ParquetFile) -> list[int]:
    starts: list[int] = []
    total = 0
    for index in range(pf.metadata.num_row_groups):
        starts.append(total)
        total += pf.metadata.row_group(index).num_rows
    return starts


def _collect(pf: pq.ParquetFile, ids: Sequence[int]) -> pd.DataFrame:
    """The rows with global row numbers ``ids``, in that order, streaming only the groups needed."""
    if not ids:
        return pf.schema_arrow.empty_table().to_pandas()
    starts = _group_starts(pf)
    ends = [start + pf.metadata.row_group(i).num_rows for i, start in enumerate(starts)]
    tables: list[pa.Table] = []
    picked: list[int] = []
    for group, (start, end) in enumerate(zip(starts, ends, strict=True)):
        wanted = sorted(i - start for i in ids if start <= i < end)
        if not wanted:
            continue
        cursor = 0
        for batch in pf.iter_batches(
            batch_size=_BATCH_ROWS, row_groups=[group], use_threads=False
        ):
            stop = cursor + batch.num_rows
            local = [i - cursor for i in wanted if cursor <= i < stop]
            if local:
                tables.append(pa.Table.from_batches([batch]).take(local))
                picked.extend(start + cursor + i for i in local)
            cursor = stop
            if cursor > wanted[-1]:
                break
    table = pa.concat_tables(tables)
    position = {row: n for n, row in enumerate(picked)}
    return table.take([position[i] for i in ids]).to_pandas()


def read_page(
    pf: pq.ParquetFile,
    *,
    offset: int,
    limit: int,
    sort: str | None = None,
    descending: bool = False,
) -> pd.DataFrame:
    """``limit`` rows from ``offset`` (in file order, or in the order of column ``sort``).

    ``sort`` must already be validated against :func:`column_names`. Nulls sort last either way.
    """
    total = int(pf.metadata.num_rows)
    if offset >= total:
        return pf.schema_arrow.empty_table().to_pandas()
    if sort is None:
        return _collect(pf, list(range(offset, min(offset + limit, total))))
    keys = pf.read(columns=[sort])
    # pyarrow's stubs differ between environments (CI types this attribute, a local
    # install may not), so the ignore is allowed to be unused.
    order = pc.sort_indices(  # type: ignore[attr-defined, unused-ignore]
        keys,
        sort_keys=[(sort, "descending" if descending else "ascending")],
        null_placement="at_end",
    )
    ids = [int(i) for i in order.slice(offset, limit).to_pylist()]
    return _collect(pf, ids)


def read_sample(
    pf: pq.ParquetFile, columns: Sequence[str], max_rows: int
) -> pd.DataFrame:
    """The first ``max_rows`` rows of ``columns`` (those that exist), streaming."""
    names = set(column_names(pf))
    wanted = [c for c in dict.fromkeys(columns) if c in names]
    if not wanted:
        return pd.DataFrame()
    tables: list[pa.Table] = []
    seen = 0
    for batch in pf.iter_batches(
        batch_size=min(max_rows, _BATCH_ROWS), columns=wanted, use_threads=False
    ):
        tables.append(pa.Table.from_batches([batch]))
        seen += batch.num_rows
        if seen >= max_rows:
            break
    if not tables:
        return pf.schema_arrow.empty_table().select(wanted).to_pandas()
    return pa.concat_tables(tables).slice(0, max_rows).to_pandas()


# --------------------------------------------------------------------- summaries


def column_summaries(pf: pq.ParquetFile) -> list[dict[str, Any]]:
    """Per column: name, type, null count, min, max -- from the footer, no data read.

    ``null_count`` / ``min`` / ``max`` are ``None`` where the writer recorded no statistics (or
    the schema is nested, where physical and logical columns no longer line up).
    """
    fields = column_types(pf)
    flat = pf.metadata.num_columns == len(fields)
    out: list[dict[str, Any]] = []
    for index, (name, dtype) in enumerate(fields):
        nulls: int | None = 0
        lows: list[Any] = []
        highs: list[Any] = []
        for group in range(pf.metadata.num_row_groups):
            stats = (
                pf.metadata.row_group(group).column(index).statistics if flat else None
            )
            if stats is None:
                nulls = None
                lows = highs = []
                break
            if nulls is not None and stats.has_null_count:
                nulls += int(stats.null_count)
            else:
                nulls = None
            if stats.has_min_max:
                lows.append(stats.min)
                highs.append(stats.max)
        out.append(
            {
                "name": name,
                "dtype": dtype,
                "null_count": nulls,
                "min": _extreme(lows, min),
                "max": _extreme(highs, max),
            }
        )
    return out


def _extreme(values: list[Any], pick: Any) -> str | None:
    if not values:
        return None
    try:
        return str(pick(values))
    except TypeError:  # mixed or unorderable statistics: say nothing rather than guess
        return None


# ------------------------------------------------------------------ whole frames


def load_dataframe(
    store: TenantObjectStore, record: DatasetRecord, max_rows: int
) -> pd.DataFrame:
    """The whole frame as pandas -- **workers only** (a stage job). Refuses an oversized frame."""
    with open_frame(store, record) as handle:
        pf = parquet_file(handle)
        if pf.metadata.num_rows > max_rows:
            raise JobError(JobErrorCode.TOO_MANY_ROWS)
        return pf.read().to_pandas()
