# File: apps/api/tests/test_storage_workspace.py
"""Phase 2.7's atomicity property, over object storage (Phase 3.4, D4-on-S3).

``tests/persistence/test_persistence_atomicity.py`` pins that a failed or interrupted
``save_workspace`` leaves the *previous* save loadable. An object store has no atomic rename
and a PUT overwrites in place, so ``StorageBackedPersistence`` achieves the same property
differently: every object of a save is written under a **new, never-reused key**; the
pointer (``WorkspaceHead``) moves last, in one compare-and-swap row update; the objects the
old workspace alone referenced are deleted only after that swap, and a failure to delete them
is housekeeping, not a failed save. These tests inject each failure -- a frame upload, the
database upload, the pointer swap, the garbage collection, a crash with no cleanup, a second
writer in the middle -- and assert, every time, that the previous workspace still loads and
that nothing it references was touched.

Hermetic: the in-memory backend, wrapped by ``FaultyBackend`` for the faults.
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]  # no pandas-stubs in the api env
import plotly.graph_objects as go  # type: ignore[import-untyped]
import pytest
from django.db import OperationalError, connection, connections
from factories import factory_for, make_organization
from storage_support import (
    FaultyBackend,
    integration_enabled,
    minio_backend,
    write_behind_the_facade,
)

from uadas_api.storage import workspace as workspace_module
from uadas_api.storage.backend import ObjectBackend
from uadas_api.storage.errors import (
    ConcurrentSaveError,
    ManifestError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectTooLargeError,
    StorageUnavailableError,
    WorkspaceNotFoundError,
)
from uadas_api.storage.lifecycle import purge_orphaned_objects, reconcile_tenant_storage
from uadas_api.storage.memory import InMemoryBackend
from uadas_api.storage.models import OrphanedObject, WorkspaceHead
from uadas_api.storage.store import TenantObjectStore, override_backend
from uadas_api.storage.workspace import StorageBackedPersistence
from uadas_api.tenancy import TenantIsolationError
from uadas_api.workspaces.models import Project
from uadas_core.core.exceptions import ServiceError
from uadas_core.models import Dashboard, DashboardTile, Dataset, Visualization
from uadas_core.persistence.persistence_service import PersistenceService

pytestmark = pytest.mark.django_db

Capture = Callable[..., Any]


def _dataset(name: str, values: list[int]) -> Dataset:
    return Dataset(
        name=name, dataframe=pd.DataFrame({"x": values}), source_format="csv"
    )


def _viz(dataset: Dataset, name: str = "v") -> Visualization:
    return Visualization(
        name=name,
        dataset_id=dataset.dataset_id,
        figure=go.Figure(),
        chart_type="bar",
        chart_parameters={"category_column": "x"},
    )


class Env:
    """One organization + project, an instrumented in-memory store, and helpers."""

    def __init__(self, capture: Capture, scratch: Path, raw: ObjectBackend) -> None:
        self.capture = capture
        self.scratch = scratch
        self.org = make_organization()
        self.project: Project = factory_for(Project).create(self.org)
        self.raw = raw  # the real backend (memory, or MinIO in the integration run)
        self.faulty = FaultyBackend(raw)
        self.store = TenantObjectStore(self.org.pk, self.faulty)
        self.service = PersistenceService()

    def persistence(self, project: Project | None = None) -> StorageBackedPersistence:
        return StorageBackedPersistence(
            project or self.project,
            store=self.store,
            persistence=self.service,
            scratch_dir=self.scratch,
        )

    def save(
        self,
        datasets: list[Dataset],
        *,
        expected: int,
        visualizations: list[Visualization] | None = None,
        dashboards: list[Dashboard] | None = None,
        execute_commit_hooks: bool = True,
        persistence: StorageBackedPersistence | None = None,
    ) -> Any:
        target = persistence or self.persistence()
        with self.capture(execute=execute_commit_hooks):
            return target.save(
                datasets,
                visualizations or [],
                dashboards or [],
                expected_version=expected,
            )

    def stored_keys(self) -> list[str]:
        """Every object of this organization, listed straight from the backend (no fault hooks)."""
        return sorted(info.key for info in self.raw.list(f"{self.org.pk}/"))

    def head(self) -> WorkspaceHead | None:
        return (
            WorkspaceHead.objects.for_organization(self.org)
            .filter(project=self.project)
            .first()
        )

    def assert_loads(self, *datasets: Dataset, version: int) -> None:
        """The workspace at ``version`` loads and holds exactly ``datasets``, byte-for-byte."""
        loaded = self.persistence().load()
        assert loaded.version == version
        assert sorted(d.dataset_id for d in loaded.snapshot.datasets) == sorted(
            d.dataset_id for d in datasets
        )
        by_id = {d.dataset_id: d for d in loaded.snapshot.datasets}
        for expected in datasets:
            pd.testing.assert_frame_equal(
                by_id[expected.dataset_id].dataframe, expected.dataframe
            )
        assert list(self.scratch.iterdir()) == [], "a scratch directory was left behind"


@pytest.fixture(
    params=[
        "memory",
        pytest.param(
            "minio",
            marks=pytest.mark.skipif(
                not integration_enabled(), reason="set STORAGE_INTEGRATION=1 for MinIO"
            ),
        ),
    ]
)
def env(
    request: pytest.FixtureRequest,
    django_capture_on_commit_callbacks: Capture,
    tmp_path: Path,
) -> Iterator[Env]:
    """The whole file runs twice: on the in-memory fake, and on real MinIO when enabled."""
    # The core rebuilds chart figures through its registry, which `bootstrap_process`
    # populates in a real process; these tests construct the persistence service directly, so
    # they do what the core's own suite does (idempotent, registers built-ins only).
    from uadas_core.visualization import chart_registry

    chart_registry._register_builtins()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    raw = InMemoryBackend() if request.param == "memory" else minio_backend()
    environment = Env(django_capture_on_commit_callbacks, scratch, raw)
    try:
        with override_backend(environment.faulty):
            yield environment
    finally:
        # Clean up only what this test created: its own (random) organization's namespace.
        environment.faulty.heal()
        TenantObjectStore(environment.org.pk, raw).delete_prefix(
            f"{environment.org.pk}/", allow_org_root=True
        )


def _is_frame(key: str) -> bool:
    return "/frames/" in key


def _is_db(key: str) -> bool:
    return key.endswith("/workspace.db")


# --- the ordinary round trip ---------------------------------------------------------


def test_a_saved_workspace_loads_back_with_its_datasets_charts_and_dashboards(
    env: Env,
) -> None:
    dataset = _dataset("d", [1, 2, 3])
    viz = _viz(dataset)
    dashboard = Dashboard(
        name="board",
        tiles=[DashboardTile(visualization_id=viz.visualization_id, row=0, column=1)],
    )

    outcome = env.save(
        [dataset], expected=0, visualizations=[viz], dashboards=[dashboard]
    )

    assert outcome.version == 1
    loaded = env.persistence().load()
    assert loaded.version == 1
    assert [v.visualization_id for v in loaded.snapshot.visualizations] == [
        viz.visualization_id
    ]
    assert [d.name for d in loaded.snapshot.dashboards] == ["board"]
    assert loaded.snapshot.dashboards[0].tiles[0].column == 1
    env.assert_loads(dataset, version=1)


def test_every_object_a_manifest_names_exists_with_the_hash_it_records(
    env: Env,
) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    head = env.head()
    assert head is not None
    manifest = head.manifest
    for ref in (manifest["workspace_db"], *manifest["datasets"].values()):
        stored = env.store.head(ref["key"])
        assert stored is not None
        assert stored.sha256 == ref["sha256"] and stored.size == ref["size"]


def test_a_project_with_nothing_saved_has_no_workspace(env: Env) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        env.persistence().load()
    assert env.persistence().current_version() == 0
    assert env.persistence().datasets() == []


def test_a_save_replaces_the_workspace_and_bumps_the_version(env: Env) -> None:
    first, second = _dataset("first", [1, 2, 3]), _dataset("second", [4, 5, 6])
    env.save([first], expected=0)
    outcome = env.save([second], expected=1)
    assert outcome.version == 2
    env.assert_loads(second, version=2)


def test_a_successful_save_leaves_exactly_the_new_generations_objects(env: Env) -> None:
    first, second = _dataset("first", [1]), _dataset("second", [2])
    env.save([first], expected=0)
    env.save([second], expected=1)  # commit hooks ran: retired objects are gone
    head = env.head()
    assert head is not None
    referenced = {head.manifest["workspace_db"]["key"]} | {
        e["key"] for e in head.manifest["datasets"].values()
    }
    assert set(env.stored_keys()) == referenced
    assert not OrphanedObject.objects.for_organization(env.org).exists()


def test_an_unchanged_dataset_is_not_uploaded_again_and_keeps_its_key(env: Env) -> None:
    kept, changed = _dataset("kept", [1, 2, 3]), _dataset("other", [7, 8, 9])
    env.save([kept, changed], expected=0)
    before = env.head()
    assert before is not None
    kept_key = before.manifest["datasets"][kept.dataset_id]["key"]

    env.faulty.calls.clear()
    env.save([kept], expected=1)  # `changed` closed, `kept` untouched

    puts = [key for op, key in env.faulty.calls if op == "put"]
    assert [k for k in puts if _is_frame(k)] == []  # no frame was re-uploaded
    assert any(_is_db(k) for k in puts)
    after = env.head()
    assert after is not None
    assert after.manifest["datasets"][kept.dataset_id]["key"] == kept_key
    env.assert_loads(kept, version=2)


def test_a_dataset_whose_frame_changed_gets_a_new_generation_key(env: Env) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    old_key = env.head().manifest["datasets"][dataset.dataset_id]["key"]  # type: ignore[union-attr]
    dataset.dataframe = pd.DataFrame({"x": [9, 9, 9]})
    env.save([dataset], expected=1)
    new_key = env.head().manifest["datasets"][dataset.dataset_id]["key"]  # type: ignore[union-attr]
    assert new_key != old_key
    assert old_key not in env.stored_keys()  # retired and collected after the swap
    env.assert_loads(dataset, version=2)


# --- Phase 2.7's failure modes, over objects ------------------------------------------


def test_a_failed_frame_upload_leaves_the_previous_workspace_loadable(env: Env) -> None:
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    before = env.stored_keys()
    env.faulty.fail("put", when=_is_frame)

    with pytest.raises(StorageUnavailableError):
        env.save([old, new], expected=1)

    env.faulty.heal()
    assert env.stored_keys() == before, "a failed save left objects behind"
    assert env.head().version == 1  # type: ignore[union-attr]
    env.assert_loads(old, version=1)


def test_a_failure_part_way_through_the_frames_removes_the_frames_already_uploaded(
    env: Env,
) -> None:
    old = _dataset("old", [1])
    env.save([old], expected=0)
    before = env.stored_keys()
    first, second = _dataset("a", [1, 2]), _dataset("b", [3, 4])
    seen: list[str] = []

    def count_frames(key: str) -> bool:
        if not _is_frame(key):
            return False
        seen.append(key)
        return len(seen) == 2  # the second new frame fails

    env.faulty.fail("put", when=count_frames)
    with pytest.raises(StorageUnavailableError):
        env.save([old, first, second], expected=1)
    env.faulty.heal()
    assert env.stored_keys() == before
    env.assert_loads(old, version=1)


def test_a_failed_database_upload_leaves_the_previous_workspace_loadable(
    env: Env,
) -> None:
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    before = env.stored_keys()
    env.faulty.fail("put", when=_is_db)

    with pytest.raises(StorageUnavailableError):
        env.save([new], expected=1)

    env.faulty.heal()
    assert (
        env.stored_keys() == before
    )  # the new frame uploaded before the failure is gone
    env.assert_loads(old, version=1)


def test_an_error_after_a_swap_that_did_commit_does_not_delete_the_live_objects(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exception from the commit does not prove it did not happen (a lost connection)."""
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    real_commit = StorageBackedPersistence._commit_head

    def committed_then_connection_lost(self: Any, *args: Any, **kwargs: Any) -> None:
        real_commit(self, *args, **kwargs)
        raise OperationalError("injected: the connection dropped after the commit")

    monkeypatch.setattr(
        StorageBackedPersistence, "_commit_head", committed_then_connection_lost
    )
    with pytest.raises(OperationalError):
        env.save([new], expected=1)
    monkeypatch.undo()

    env.assert_loads(new, version=2)  # the new generation's objects were left alone


def test_cleanup_never_deletes_an_object_the_current_head_references(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if the attempt's own token no longer matches (another save moved the head on)."""
    old = _dataset("old", [1, 2, 3])
    env.save([old], expected=0)
    persistence = env.persistence()
    referenced = sorted(env.stored_keys())  # the live head's objects
    persistence._abandon(
        referenced, 99, "g0000099-unrelated"
    )  # a stale attempt "cleans up"
    assert sorted(env.stored_keys()) == referenced
    env.assert_loads(old, version=1)


def test_a_manifest_pointing_into_another_project_of_the_same_organization_is_refused(
    env: Env,
) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    other_project = factory_for(Project).create(env.org)
    manifest = env.head().manifest  # type: ignore[union-attr]
    manifest["workspace_db"][
        "key"
    ] = f"{env.org.pk}/projects/{other_project.pk}/workspace/g0000001-aaaaaaaaaaaa/workspace.db"
    WorkspaceHead.objects.filter(pk=env.head().pk).update(manifest=manifest)  # type: ignore[union-attr]
    env.faulty.calls.clear()
    with pytest.raises(ManifestError):
        env.persistence().load()
    assert env.faulty.calls == []


def test_a_manifest_pointing_a_dataset_at_another_datasets_frames_is_refused(
    env: Env,
) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    manifest = env.head().manifest  # type: ignore[union-attr]
    manifest["datasets"][dataset.dataset_id][
        "key"
    ] = f"{env.org.pk}/datasets/{uuid.uuid4()}/frames/g0000001-aaaaaaaaaaaa.parquet"
    WorkspaceHead.objects.filter(pk=env.head().pk).update(manifest=manifest)  # type: ignore[union-attr]
    with pytest.raises(ManifestError):
        env.persistence().load()


def test_discarding_a_head_only_queues_the_objects_inside_its_own_namespaces(
    env: Env,
) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    other_project = factory_for(Project).create(env.org)
    foreign = f"{env.org.pk}/projects/{other_project.pk}/workspace/g0000001-aaaaaaaaaaaa/workspace.db"
    manifest = env.head().manifest  # type: ignore[union-attr]
    own_keys = {
        manifest["workspace_db"]["key"],
        manifest["datasets"][dataset.dataset_id]["key"],
    }
    manifest["datasets"][str(uuid.uuid4())] = {
        "key": foreign,
        "sha256": "0" * 64,
        "size": 1,
    }
    WorkspaceHead.objects.filter(pk=env.head().pk).update(manifest=manifest)  # type: ignore[union-attr]

    env.head().delete()  # type: ignore[union-attr]

    queued = {
        o.storage_key
        for o in OrphanedObject.objects.for_organization(env.org)
        if not o.is_prefix
    }
    assert queued == own_keys
    assert foreign not in queued


def test_a_sweep_in_the_middle_of_a_save_cannot_delete_the_objects_it_is_about_to_commit(
    env: Env,
) -> None:
    """The data-loss race: a retried directory purge fires after the upload, before the swap.

    A discarded workspace leaves a directory entry (``projects/<id>``) owed. The project then
    starts a fresh workspace; the sweeper (cron, ``manage.py purge_orphaned_objects``) runs
    while that save has uploaded its new objects but not yet swapped the head. Those objects
    were written after the debt, so the purge must not touch them -- otherwise the save commits
    a head naming deleted objects and the workspace is unloadable.
    """
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    old_keys = set(env.stored_keys())
    time.sleep(
        1.1
    )  # a real store stamps whole seconds: put the debt clearly after the old objects
    with env.capture(
        execute=False
    ):  # the discard's own sweep never ran (store down, crash)
        env.head().delete()  # type: ignore[union-attr]
    assert (
        OrphanedObject.objects.for_organization(env.org).filter(is_prefix=True).exists()
    )
    fired: list[bool] = []

    def the_sweeper_fires_mid_save(key: str) -> None:
        if _is_db(key) and not fired:
            fired.append(True)
            purge_orphaned_objects(env.org)  # exactly what the management command does

    env.faulty.after("put", the_sweeper_fires_mid_save)
    env.save([dataset], expected=0)  # commits
    env.faulty.heal()
    assert fired

    env.assert_loads(dataset, version=1)  # the committed workspace is whole
    purge_orphaned_objects(env.org)  # a later sweep still completes the original debt
    leftovers = old_keys & set(env.stored_keys())
    assert (
        not leftovers
    )  # positive twin: the genuinely orphaned older objects are deleted
    assert not OrphanedObject.objects.for_organization(env.org).exists()  # debt settled
    env.assert_loads(dataset, version=1)


def test_a_load_that_races_the_post_swap_delete_retries_once_against_the_new_head(
    env: Env,
) -> None:
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    fired: list[bool] = []

    def a_save_commits_and_collects_garbage_mid_load(key: str) -> None:
        if not fired:
            fired.append(True)
            env.faulty.heal()
            env.save(
                [new], expected=1
            )  # grace is 0 in the test settings: old objects go now

    env.faulty.before("download", a_save_commits_and_collects_garbage_mid_load)
    loaded = env.persistence().load()  # read the v1 head, then v1's objects vanish
    assert fired
    assert loaded.version == 2
    assert [d.dataset_id for d in loaded.snapshot.datasets] == [new.dataset_id]


def test_a_load_does_not_retry_when_the_object_is_genuinely_missing(env: Env) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    key = env.head().manifest["datasets"][dataset.dataset_id]["key"]  # type: ignore[union-attr]
    env.raw.delete_many([key])  # lost behind the facade's back; the head is unchanged
    env.faulty.calls.clear()
    with pytest.raises(ObjectNotFoundError):
        env.persistence().load()
    downloads = [k for op, k in env.faulty.calls if op == "download"]
    assert len(downloads) <= 2  # one attempt per head read: no loop


def test_the_pointer_swap_and_the_debt_it_creates_commit_or_vanish_together(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failing the debt bookkeeping *inside* the real atomic block must undo the head update."""
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    before = env.stored_keys()

    def failing(*args: Any, **kwargs: Any) -> None:
        raise OperationalError(
            "injected: queueing the debt failed after the head update"
        )

    for name in ("queue_object_deletion", "schedule_purge"):
        with monkeypatch.context() as patch:
            patch.setattr(workspace_module, name, failing)
            with pytest.raises(OperationalError):
                env.save([new], expected=1)
        assert env.head().version == 1  # type: ignore[union-attr]  # the update rolled back
        assert not OrphanedObject.objects.for_organization(env.org).exists()
        assert env.stored_keys() == before  # the failed save cleaned up its own uploads
        env.assert_loads(old, version=1)

    env.save(
        [new], expected=1
    )  # positive twin: with the bookkeeping healthy it commits
    env.assert_loads(new, version=2)


@pytest.mark.django_db(transaction=True)
def test_the_swap_is_atomic_with_its_debt_across_a_real_commit(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same property without the test-suite's wrapping transaction (real commits; both databases)."""
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)

    def failing(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("injected")

    monkeypatch.setattr(workspace_module, "schedule_purge", failing)
    with pytest.raises(OperationalError):
        env.save([new], expected=1)
    monkeypatch.undo()
    assert env.head().version == 1  # type: ignore[union-attr]
    assert not OrphanedObject.objects.for_organization(env.org).exists()
    env.assert_loads(old, version=1)


def test_a_failed_pointer_swap_leaves_the_previous_workspace_loadable(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline D4 case: close dataset A, open B, and have the swap itself fail."""
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    before = env.stored_keys()

    def failing_swap(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("injected: the pointer update failed")

    monkeypatch.setattr(StorageBackedPersistence, "_commit_head", failing_swap)
    with pytest.raises(OperationalError):
        env.save([new], expected=1)  # A is "closed": only B is being saved
    monkeypatch.undo()

    assert (
        env.stored_keys() == before
    ), "objects of the failed save were not rolled back"
    env.assert_loads(old, version=1)


def test_a_crash_between_the_uploads_and_the_swap_still_loads_consistently(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hard kill runs no cleanup, so this pins the weaker guarantee that remains.

    The state a killed process leaves: the new generation's objects uploaded, the pointer
    never moved. The old workspace must load as if nothing happened; the strays are
    garbage that the reconciliation report lists, and the next save succeeds regardless.
    """
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    before = set(env.stored_keys())

    def killed(*args: Any, **kwargs: Any) -> None:
        raise SystemExit("injected: the process died before the swap")

    monkeypatch.setattr(StorageBackedPersistence, "_commit_head", killed)
    monkeypatch.setattr(StorageBackedPersistence, "_abandon", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        env.save([new], expected=1)
    monkeypatch.undo()

    strays = set(env.stored_keys()) - before
    assert strays, "the simulated crash should have left the new generation behind"
    env.assert_loads(old, version=1)
    report = reconcile_tenant_storage(env.org)
    assert set(report.objects_without_rows) == strays  # reported, not deleted

    env.save([new], expected=1)  # a later save is unaffected by the strays
    env.assert_loads(new, version=2)


def test_a_failed_save_by_the_core_uploads_nothing(env: Env) -> None:
    old = _dataset("old", [1, 2, 3])
    env.save([old], expected=0)
    before = env.stored_keys()
    broken = _viz(_dataset("other", [1]), name="orphan viz")
    broken.chart_type = "no-such-chart"
    bad_dataset = _dataset("bad", [1])
    broken.dataset_id = bad_dataset.dataset_id

    with pytest.raises(ServiceError):
        env.save([old, bad_dataset], expected=1, visualizations=[broken])

    assert env.stored_keys() == before
    env.assert_loads(old, version=1)


# --- garbage collection happens after the swap and cannot fail a save ------------------


def test_a_gc_failure_after_the_swap_does_not_fail_the_save_and_is_retried_later(
    env: Env,
) -> None:
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    old_keys = set(env.stored_keys())
    env.faulty.fail("delete")

    outcome = env.save([new], expected=1)  # must not raise

    assert outcome.version == 2
    env.faulty.heal()
    env.assert_loads(new, version=2)
    assert old_keys <= set(env.stored_keys())  # not collected yet ...
    owed = OrphanedObject.objects.for_organization(env.org)
    assert {o.storage_key for o in owed} == old_keys  # ... but owed, durably

    purge_orphaned_objects(env.org)  # the sweeper retries
    assert not (old_keys & set(env.stored_keys()))
    assert not OrphanedObject.objects.for_organization(env.org).exists()
    env.assert_loads(new, version=2)


def test_a_crash_after_the_swap_before_the_gc_leaves_the_debt_on_record(
    env: Env,
) -> None:
    old, new = _dataset("old", [1, 2, 3]), _dataset("new", [4, 5, 6])
    env.save([old], expected=0)
    old_keys = set(env.stored_keys())

    env.save(
        [new], expected=1, execute_commit_hooks=False
    )  # the process dies before GC

    env.assert_loads(new, version=2)
    assert {
        o.storage_key for o in OrphanedObject.objects.for_organization(env.org)
    } == old_keys
    purge_orphaned_objects(env.org)
    assert not (old_keys & set(env.stored_keys()))


def test_a_save_never_references_an_object_an_earlier_save_already_retired(
    env: Env,
) -> None:
    """Why a sweep may read the referenced set once: retired keys are never referenced again.

    A save reuses only keys of the head it replaces, and a retired key was dropped from that
    head's successor -- so content that returns later (the same dataset, byte for byte) gets a
    *new* key. A head committed mid-sweep therefore cannot name an object that was already owed.
    """
    a, b = _dataset("a", [1, 2, 3]), _dataset("b", [4, 5, 6])
    env.save([a], expected=0)
    env.save(
        [b], expected=1, execute_commit_hooks=False
    )  # a's objects retired, still stored
    retired = {o.storage_key for o in OrphanedObject.objects.for_organization(env.org)}
    assert retired
    env.save(
        [a], expected=2, execute_commit_hooks=False
    )  # the very same dataset comes back
    head = env.head()
    assert head is not None
    referenced = {head.manifest["workspace_db"]["key"]} | {
        e["key"] for e in head.manifest["datasets"].values()
    }
    assert not referenced & retired
    env.assert_loads(a, version=3)


def test_gc_never_deletes_an_object_the_new_workspace_still_references(
    env: Env,
) -> None:
    kept, dropped = _dataset("kept", [1, 2]), _dataset("dropped", [3, 4])
    env.save([kept, dropped], expected=0)
    env.save([kept], expected=1)
    # `kept`'s frame survived two saves because the manifest keeps referencing it.
    env.assert_loads(kept, version=2)
    assert len([k for k in env.stored_keys() if _is_frame(k)]) == 1


# --- concurrency: compare-and-swap on the head ---------------------------------------


def test_a_save_based_on_a_stale_version_is_refused_before_anything_is_uploaded(
    env: Env,
) -> None:
    env.save([_dataset("a", [1])], expected=0)
    winner = _dataset("b", [2])
    env.save([winner], expected=1)
    env.faulty.calls.clear()

    with pytest.raises(ConcurrentSaveError):
        env.save([_dataset("loser", [3])], expected=1)  # still believes it is at v1

    assert [op for op, _ in env.faulty.calls if op == "put"] == []
    env.assert_loads(winner, version=2)


def test_two_writers_from_the_same_version_cannot_both_commit(env: Env) -> None:
    base = _dataset("base", [1, 2, 3])
    env.save([base], expected=0)
    mine, theirs = _dataset("mine", [4, 5, 6]), _dataset("theirs", [7, 8, 9])
    other_writer = env.persistence()
    fired: list[bool] = []

    def competing_save_lands_in_the_middle(key: str) -> None:
        if _is_db(key) and not fired:
            fired.append(True)
            env.faulty.heal()  # the competing writer is a separate, healthy request
            other_writer.save([theirs], [], [], expected_version=1)

    env.faulty.after("put", competing_save_lands_in_the_middle)
    with pytest.raises(ConcurrentSaveError):
        env.save([mine], expected=1)
    env.faulty.heal()

    # The competitor's workspace is intact; mine left nothing behind and never became visible.
    env.assert_loads(theirs, version=2)
    head = env.head()
    assert head is not None
    referenced = {head.manifest["workspace_db"]["key"]} | {
        e["key"] for e in head.manifest["datasets"].values()
    }
    purge_orphaned_objects(env.org)
    assert set(env.stored_keys()) == referenced

    # The loser can retry from what it now sees.
    env.save([mine], expected=2)
    env.assert_loads(mine, version=3)


def test_two_first_saves_of_a_project_cannot_both_commit(env: Env) -> None:
    first, second = _dataset("first", [1]), _dataset("second", [2])
    other_writer = env.persistence()
    fired: list[bool] = []

    def competitor(key: str) -> None:
        if _is_db(key) and not fired:
            fired.append(True)
            other_writer.save([second], [], [], expected_version=0)

    env.faulty.after("put", competitor)
    with pytest.raises(ConcurrentSaveError):
        env.save([first], expected=0)
    env.faulty.heal()
    env.assert_loads(second, version=1)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("base_version", [0, 1], ids=["first-save", "later-save"])
def test_simultaneous_saves_in_separate_connections_commit_exactly_one(
    base_version: int,
) -> None:
    """The row-level compare-and-swap itself, with real concurrent transactions (PostgreSQL).

    Both writers are held at a barrier *after* they have passed the up-front version check
    and uploaded everything (a hook on the database upload), so neither can be refused by
    that cheap early check: the loser can only be rejected by the conditional update (or, for
    a first save, by the unique constraint). The assertion on the error text proves which.
    """
    if connection.vendor != "postgresql":
        pytest.skip(
            "concurrent writers need PostgreSQL row locking; CI's api-test runs this"
        )
    from uadas_core.visualization import chart_registry

    chart_registry._register_builtins()
    org = make_organization()
    project = factory_for(Project).create(org)
    memory = InMemoryBackend()
    service = PersistenceService()
    with override_backend(memory):
        if base_version:
            StorageBackedPersistence(
                project, store=TenantObjectStore(org.pk, memory), persistence=service
            ).save([_dataset("base", [0])], [], [], expected_version=0)
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        refusals: list[str] = []
        datasets = [_dataset("one", [1]), _dataset("two", [2])]

        def writer(dataset: Dataset) -> None:
            try:
                faulty = FaultyBackend(memory)
                persistence = StorageBackedPersistence(
                    project,
                    store=TenantObjectStore(org.pk, faulty),
                    persistence=service,
                )

                def meet_before_the_swap(key: str) -> None:
                    if _is_db(key):
                        barrier.wait(timeout=20)

                faulty.after("put", meet_before_the_swap)
                try:
                    persistence.save([dataset], [], [], expected_version=base_version)
                    outcomes.append("saved")
                except ConcurrentSaveError as error:
                    outcomes.append("refused")
                    refusals.append(str(error))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=writer, args=(d,)) for d in datasets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert sorted(outcomes) == ["refused", "saved"]
        # Rejected by the swap, not by the up-front check (whose message differs).
        assert len(refusals) == 1
        assert "reload before saving" in refusals[0] or "first" in refusals[0]
        assert "since it was loaded" not in refusals[0]
        loaded = StorageBackedPersistence(
            project, store=TenantObjectStore(org.pk, memory), persistence=service
        ).load()
        assert loaded.version == base_version + 1 and len(loaded.snapshot.datasets) == 1
        head = WorkspaceHead.objects.for_organization(org).get(project=project)
        referenced = {head.manifest["workspace_db"]["key"]} | {
            e["key"] for e in head.manifest["datasets"].values()
        }
        # Whatever the loser uploaded was cleaned up; only the winner's objects remain.
        assert set(memory.keys()) == referenced


# --- loading verifies, and loads lazily ----------------------------------------------


def test_a_tampered_frame_is_refused_on_load(env: Env) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    key = env.head().manifest["datasets"][dataset.dataset_id]["key"]  # type: ignore[union-attr]
    recorded = str(env.store.head(key).sha256)  # type: ignore[union-attr]
    # An attacker with bucket access replaces the bytes, keeping the recorded hash.
    write_behind_the_facade(env.raw, key, b"not parquet at all", {"sha256": recorded})
    with pytest.raises(ObjectIntegrityError):
        env.persistence().load()


def test_a_frame_swapped_for_another_valid_object_is_caught_by_the_manifest_hash(
    env: Env,
) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    key = env.head().manifest["datasets"][dataset.dataset_id]["key"]  # type: ignore[union-attr]
    # Replace the object with *different* bytes and a hash that matches those bytes: the
    # object is internally consistent (so the facade's own check would pass), yet it is not
    # what the manifest committed to.
    swapped = b"a perfectly self-consistent but different object"
    write_behind_the_facade(
        env.raw, key, swapped, {"sha256": hashlib.sha256(swapped).hexdigest()}
    )
    assert env.store.get(key) == swapped  # the facade alone is satisfied ...
    with pytest.raises(ObjectIntegrityError):  # ... the manifest's hash is not
        env.persistence().load()


def test_a_manifest_naming_another_tenants_object_is_refused(env: Env) -> None:
    dataset = _dataset("d", [1, 2, 3])
    env.save([dataset], expected=0)
    other_org = make_organization()
    foreign = f"{other_org.pk}/datasets/{dataset.dataset_id}/frames/g0000001-aaaaaaaaaaaa.parquet"
    manifest = env.head().manifest  # type: ignore[union-attr]
    manifest["datasets"][dataset.dataset_id]["key"] = foreign
    WorkspaceHead.objects.filter(pk=env.head().pk).update(manifest=manifest)  # type: ignore[union-attr]
    env.faulty.calls.clear()
    with pytest.raises(ManifestError):
        env.persistence().load()
    assert env.faulty.calls == []  # nothing was fetched


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.update(format=2),
        lambda m: m.update(datasets="nope"),
        lambda m: m["workspace_db"].update(sha256="xyz"),
        lambda m: m["workspace_db"].update(size=-1),
        lambda m: m.pop("token"),
    ],
)
def test_a_malformed_manifest_is_refused(
    env: Env, mutate: Callable[[dict[str, Any]], Any]
) -> None:
    env.save([_dataset("d", [1])], expected=0)
    manifest = env.head().manifest  # type: ignore[union-attr]
    mutate(manifest)
    WorkspaceHead.objects.filter(pk=env.head().pk).update(manifest=manifest)  # type: ignore[union-attr]
    with pytest.raises(ManifestError):
        env.persistence().load()


def test_a_save_repairs_a_head_whose_manifest_is_corrupt(env: Env) -> None:
    """A corrupt head must not make the project unsaveable; the next save replaces it."""
    old = _dataset("old", [1, 2, 3])
    env.save([old], expected=0)
    old_keys = set(env.stored_keys())
    manifest = env.head().manifest  # type: ignore[union-attr]
    manifest["workspace_db"]["sha256"] = "not-a-hash"
    WorkspaceHead.objects.filter(pk=env.head().pk).update(manifest=manifest)  # type: ignore[union-attr]
    with pytest.raises(ManifestError):
        env.persistence().load()

    new = _dataset("new", [4, 5, 6])
    env.save([new], expected=1)

    env.assert_loads(new, version=2)
    assert not (
        old_keys & set(env.stored_keys())
    )  # the corrupt head's objects were retired


def test_loading_a_subset_fetches_only_the_requested_frames(env: Env) -> None:
    a, b, c = _dataset("a", [1]), _dataset("b", [2]), _dataset("c", [3])
    va, vb = _viz(a, "va"), _viz(b, "vb")
    dashboard = Dashboard(
        name="board",
        tiles=[DashboardTile(visualization_id=vb.visualization_id, row=0, column=0)],
    )
    env.save([a, b, c], expected=0, visualizations=[va, vb], dashboards=[dashboard])
    head = env.head()
    assert head is not None
    env.faulty.calls.clear()

    loaded = env.persistence().load(dataset_ids=[a.dataset_id])

    downloads = [key for op, key in env.faulty.calls if op == "download"]
    assert sorted(downloads) == sorted(
        [
            head.manifest["workspace_db"]["key"],
            head.manifest["datasets"][a.dataset_id]["key"],
        ]
    )
    assert [d.dataset_id for d in loaded.snapshot.datasets] == [a.dataset_id]
    assert [v.visualization_id for v in loaded.snapshot.visualizations] == [
        va.visualization_id
    ]
    assert [d.name for d in loaded.snapshot.dashboards] == [
        "board"
    ]  # a tile may dangle
    assert loaded.loaded_dataset_ids == [a.dataset_id]


def test_loading_every_dataset_matches_loading_with_no_filter(env: Env) -> None:
    a, b = _dataset("a", [1]), _dataset("b", [2])
    env.save([a, b], expected=0)
    everything = env.persistence().load()
    named = env.persistence().load(dataset_ids=[a.dataset_id, b.dataset_id])
    assert sorted(d.dataset_id for d in everything.snapshot.datasets) == sorted(
        d.dataset_id for d in named.snapshot.datasets
    )


def test_asking_for_a_dataset_the_workspace_does_not_contain_is_not_found(
    env: Env,
) -> None:
    env.save([_dataset("a", [1])], expected=0)
    with pytest.raises(ObjectNotFoundError):
        env.persistence().load(dataset_ids=["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"])


def test_listing_the_datasets_needs_no_object_requests(env: Env) -> None:
    a = _dataset("alpha", [1, 2, 3])
    env.save([a], expected=0)
    env.faulty.calls.clear()
    entries = env.persistence().datasets()
    assert env.faulty.calls == []
    assert [(e.name, e.rows, e.columns) for e in entries] == [("alpha", 3, 1)]


def test_a_load_over_the_byte_budget_is_refused_before_downloading(env: Env) -> None:
    env.save([_dataset("a", list(range(100)))], expected=0)
    env.faulty.calls.clear()
    with pytest.raises(ObjectTooLargeError):
        env.persistence().load(max_total_bytes=10)
    assert [op for op, _ in env.faulty.calls if op == "download"] == []


def test_a_failed_load_leaves_no_scratch_directory(env: Env) -> None:
    env.save([_dataset("a", [1])], expected=0)
    env.faulty.fail("download", when=_is_db)
    with pytest.raises(StorageUnavailableError):
        env.persistence().load()
    assert list(env.scratch.iterdir()) == []


# --- tenancy ---------------------------------------------------------------------------


def test_a_persistence_cannot_be_built_for_a_project_of_another_organization(
    env: Env,
) -> None:
    other = factory_for(Project).create(make_organization())
    with pytest.raises(TenantIsolationError):
        StorageBackedPersistence(other, store=env.store, persistence=env.service)


def test_two_organizations_projects_never_see_each_others_workspaces(env: Env) -> None:
    mine = _dataset("mine", [1])
    env.save([mine], expected=0)
    other_org = make_organization()
    other_project = factory_for(Project).create(other_org)
    other_store = TenantObjectStore(other_org.pk, env.faulty)
    theirs = StorageBackedPersistence(
        other_project, store=other_store, persistence=env.service
    )
    with pytest.raises(WorkspaceNotFoundError):
        theirs.load()
    assert theirs.current_version() == 0
    env.assert_loads(mine, version=1)
