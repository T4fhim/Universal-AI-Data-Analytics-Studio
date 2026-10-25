# File: tests/persistence/test_persistence_atomicity.py
"""A failed or interrupted ``save_workspace`` must leave the previous save loadable.

Phase 1 diagnosis D4: ``save_workspace`` used to write every frame in place and garbage-collect
orphaned frames *before* the atomic ``workspace.db`` swap, with no rollback. A failure between
those steps left the **old** database pointing at frames that had already been deleted -- the
user's last good save silently unloadable. The fix stages every frame as ``<id>.parquet.tmp``,
promotes frames, swaps the database, and only then garbage-collects, rolling back anything it
newly promoted if the swap fails.

These tests inject the failure (an ``OSError`` on the database swap, a failing frame write, a
failing post-swap GC) rather than killing a process: a hard kill cannot run any cleanup, so the
guarantee for that case is weaker and is stated in the last test -- it still leaves a *loadable,
consistent* workspace, with at worst harmless orphan frames that the next save collects.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.models import Dataset
from uadas_core.persistence import persistence_service
from uadas_core.persistence.persistence_service import PersistenceService


def _dataset(name: str, values: list[int]) -> Dataset:
    return Dataset(
        name=name, dataframe=pd.DataFrame({"x": values}), source_format="csv"
    )


def _save_one(service: PersistenceService, base: Path, dataset: Dataset) -> None:
    service.save_workspace([dataset], [], [], base)


def _names(base: Path, pattern: str) -> set[str]:
    return {p.name for p in base.glob(pattern)}


def _assert_previous_workspace_intact(
    service: PersistenceService, base: Path, previous: Dataset
) -> None:
    """The earlier save still loads, with its data, and nothing is left half-written."""
    snapshot = service.load_workspace(base)
    assert [d.dataset_id for d in snapshot.datasets] == [previous.dataset_id]
    pd.testing.assert_frame_equal(snapshot.datasets[0].dataframe, previous.dataframe)
    assert _names(base, "*.tmp") == set(), "staging files were left behind"


def test_a_failed_database_swap_leaves_the_previous_workspace_loadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline D4 case: close dataset A, open B, and have the final swap fail.

    Before the fix, A's frame had already been garbage-collected by then, so the old database
    referenced a frame that no longer existed.
    """
    base = tmp_path / "p.workspace"
    service = PersistenceService()
    old = _dataset("old", [1, 2, 3])
    new = _dataset("new", [9, 8, 7])
    _save_one(service, base, old)

    real_replace = os.replace

    def fail_on_database_swap(src: str | Path, dst: str | Path) -> None:
        if Path(dst).name == "workspace.db":
            raise OSError("injected: cannot swap workspace.db")
        real_replace(src, dst)

    monkeypatch.setattr(persistence_service.os, "replace", fail_on_database_swap)

    with pytest.raises(ServiceError):
        _save_one(service, base, new)  # A is "closed": only B is being saved

    monkeypatch.undo()
    _assert_previous_workspace_intact(service, base, old)
    assert not (base / f"{new.dataset_id}.parquet").exists(), (
        "a frame promoted for the failed save was not rolled back, "
        "leaving an orphan with no database row"
    )


def test_a_failed_frame_write_leaves_the_previous_workspace_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "p.workspace"
    service = PersistenceService()
    old = _dataset("old", [1, 2, 3])
    new = _dataset("new", [4, 5, 6])
    _save_one(service, base, old)

    real_write = persistence_service._write_parquet_frame

    def fail_for_new(dataframe: pd.DataFrame, path: Path) -> None:
        if path.name.startswith(new.dataset_id):
            raise ServiceError("injected: disk full while writing the frame")
        real_write(dataframe, path)

    monkeypatch.setattr(persistence_service, "_write_parquet_frame", fail_for_new)

    with pytest.raises(ServiceError):
        service.save_workspace([old, new], [], [], base)

    monkeypatch.undo()
    _assert_previous_workspace_intact(service, base, old)
    assert not (base / f"{new.dataset_id}.parquet").exists()


def test_a_successful_save_collects_orphans_and_leaves_no_staging_files(
    tmp_path: Path,
) -> None:
    base = tmp_path / "p.workspace"
    service = PersistenceService()
    old = _dataset("old", [1, 2, 3])
    new = _dataset("new", [4, 5, 6])
    _save_one(service, base, old)
    _save_one(service, base, new)

    assert _names(base, "*.parquet") == {f"{new.dataset_id}.parquet"}
    assert _names(base, "*.tmp") == set()
    snapshot = service.load_workspace(base)
    assert [d.dataset_id for d in snapshot.datasets] == [new.dataset_id]


def test_staging_files_from_a_crashed_save_are_cleared_by_the_next_save(
    tmp_path: Path,
) -> None:
    base = tmp_path / "p.workspace"
    service = PersistenceService()
    kept = _dataset("kept", [1, 2, 3])
    _save_one(service, base, kept)

    # What a hard-killed save leaves behind.
    (base / "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.parquet.tmp").write_bytes(b"partial")
    (base / "workspace.db.tmp").write_bytes(b"partial")

    _save_one(service, base, kept)

    assert _names(base, "*.tmp") == set()
    assert service.load_workspace(base).datasets[0].dataset_id == kept.dataset_id


def test_a_gc_failure_after_the_swap_does_not_fail_the_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """By then the new database is in place and the save has succeeded.

    Orphan collection is housekeeping; raising here would report a failed save for a workspace
    that is fully committed, and the next save collects the orphans anyway.
    """
    base = tmp_path / "p.workspace"
    service = PersistenceService()
    old = _dataset("old", [1, 2, 3])
    new = _dataset("new", [4, 5, 6])
    _save_one(service, base, old)

    def failing_gc(base: Path, saved_ids: set[str]) -> None:
        raise ServiceError("injected: could not garbage-collect")

    monkeypatch.setattr(persistence_service, "_gc_orphan_parquet", failing_gc)

    report = service.save_workspace([new], [], [], base)  # must not raise

    assert report.skipped_visualization_ids == []
    monkeypatch.undo()
    snapshot = service.load_workspace(base)
    assert [d.dataset_id for d in snapshot.datasets] == [new.dataset_id]


def test_a_crash_between_frame_promotion_and_the_swap_still_loads_consistently(
    tmp_path: Path,
) -> None:
    """A hard kill cannot run cleanup, so this pins the weaker guarantee that remains.

    Simulate the on-disk state of a process killed after promoting a new frame but before
    swapping the database: the old database plus an extra frame it knows nothing about. The old
    workspace must load as if nothing happened, and the next successful save collects the stray.
    """
    base = tmp_path / "p.workspace"
    service = PersistenceService()
    old = _dataset("old", [1, 2, 3])
    _save_one(service, base, old)

    stray = base / "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb.parquet"
    stray.write_bytes((base / f"{old.dataset_id}.parquet").read_bytes())

    snapshot = service.load_workspace(base)
    assert [d.dataset_id for d in snapshot.datasets] == [old.dataset_id]

    _save_one(service, base, old)
    assert not stray.exists()
