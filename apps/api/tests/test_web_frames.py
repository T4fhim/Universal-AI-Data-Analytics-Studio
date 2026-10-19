# File: apps/api/tests/test_web_frames.py
"""Lazy frame reads: a page, a sorted page and a sample never load the whole frame.

The brief's rule ("never the whole frame into the web process for a page") is shown, not asserted in
prose: the unsorted page path is run with ``ParquetFile.read`` made to fail (so it cannot have read
the table), the sorted path is shown to read exactly **one** column, and ``read_sample`` is shown to
stop after the rows it needs. Each has a twin (the same call with ``read`` allowed returns the same
rows), so the guard is not satisfied by a function that returns nothing.
"""

from __future__ import annotations

from typing import Any

import pandas as pd  # type: ignore[import-untyped]
import pyarrow.parquet as pq
import pytest
from web_support import make_world, parquet_bytes

from uadas_api.stages import frames
from uadas_api.storage.errors import ObjectIntegrityError
from uadas_api.storage.store import get_store

pytestmark = pytest.mark.django_db

FRAME = pd.DataFrame(
    {"n": range(40), "s": [f"k{(i * 11) % 40:02d}" for i in range(40)]}
)


def _open(world: Any) -> Any:
    handle = frames.open_frame(get_store(world.org), world.dataset)
    return handle, frames.parquet_file(handle)


@pytest.fixture
def world() -> Any:
    from web_support import store_dataset

    built = make_world()
    built.dataset = store_dataset(built.org, built.project, FRAME, row_group_size=9)
    return built


def test_an_unsorted_page_streams_batches_and_never_reads_the_table(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle, pf = _open(world)
    with handle:
        expected = frames.read_page(pf, offset=7, limit=5)["n"].tolist()
        assert expected == [7, 8, 9, 10, 11]  # crosses a row-group edge (groups of 9)

        def refuse(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("the whole table was read")

        monkeypatch.setattr(pq.ParquetFile, "read", refuse)
        assert frames.read_page(pf, offset=7, limit=5)["n"].tolist() == expected


def test_a_sorted_page_reads_exactly_one_column(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle, pf = _open(world)
    seen: list[Any] = []
    original = pq.ParquetFile.read

    def spy(self: Any, columns: Any = None, *args: Any, **kwargs: Any) -> Any:
        seen.append(columns)
        return original(self, columns, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "read", spy)
    with handle:
        page = frames.read_page(pf, offset=0, limit=3, sort="s")
    assert seen == [["s"]]  # the sort column only, never the frame
    assert page["s"].tolist() == ["k00", "k01", "k02"]


def test_a_sample_stops_after_the_rows_it_needs() -> None:
    world = make_world(pd.DataFrame({"n": range(50_000), "pad": ["x"] * 50_000}))
    handle, pf = _open(world)
    with handle:
        sample = frames.read_sample(pf, ["n", "missing-column"], 100)
    assert (
        list(sample.columns) == ["n"] and len(sample) == 100
    )  # an unknown column is dropped


def test_a_tampered_object_is_refused_by_the_hash_check(world: Any) -> None:
    store = get_store(world.org)
    key = world.dataset.storage_key
    store.put(
        key,
        parquet_bytes(FRAME.head(3)),
        content_type="application/vnd.apache.parquet",
        allowed_content_types=("application/vnd.apache.parquet",),
        overwrite=True,
    )
    with pytest.raises(
        ObjectIntegrityError
    ):  # the row's recorded SHA-256 no longer matches
        frames.open_frame(store, world.dataset)
