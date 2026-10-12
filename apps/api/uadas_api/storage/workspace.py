# File: apps/api/uadas_api/storage/workspace.py
"""``StorageBackedPersistence``: Phase 2.7's atomic workspace save, over object storage.

The property (``uadas_core/persistence/persistence_service.py``, Phase 1 diagnosis D4, pinned
by ``tests/persistence/test_persistence_atomicity.py``): *a failure or crash at any step of a
save leaves the previous save loadable.* On a filesystem the core gets it from staging files,
an atomic ``os.replace`` of ``workspace.db`` and garbage collection only after the swap.
An object store gives none of those primitives: no rename, and a PUT silently overwrites in
place. So the same property is rebuilt from what an object store *does* guarantee -- a single
PUT is atomic, a key nobody else writes never changes, and a database row can be updated
conditionally:

1. **Write new objects under new keys; never overwrite one the current head references.**
   Every frame and the workspace database of a save go to keys containing that attempt's
   unique token (``keys.new_save_token``): ``datasets/<id>/frames/<token>.parquet``,
   ``projects/<id>/workspace/<token>/workspace.db``. A frame whose content hash is unchanged
   is *not* re-uploaded -- the new manifest keeps referencing the old key. (A dataset is
   never mutated in place, so this is the common case.) Two concurrent attempts have
   different tokens, so neither can corrupt the other's objects.
2. **The swap is one conditional row update.** ``WorkspaceHead`` (project, version, manifest)
   moves from *n* to *n + 1* with ``UPDATE ... WHERE version = n``. That row update is the
   analogue of ``os.replace(workspace.db.tmp, workspace.db)``: until it commits the old
   manifest is the workspace; after it the new one is. It is also the optimistic-concurrency
   check: a second writer that started from the same version updates zero rows and gets
   :class:`ConcurrentSaveError` instead of silently overwriting the first. (Row, not
   ``If-Match`` on an object: conditional PUT is not supported by every S3-compatible store,
   and a store that ignores the header would turn compare-and-swap into last-writer-wins.)
3. **Garbage is collected only after the swap, and its collection cannot fail a save.** The
   keys the old manifest referenced and the new one does not are written to the
   ``OrphanedObject`` queue *in the swap's transaction* and deleted after commit
   (``lifecycle``). A failed or skipped deletion leaves harmless extra objects and a durable
   entry the sweeper retries -- exactly the "worst case is harmless extra frames" of the
   filesystem version.
4. **A failed save cleans up its own uploads** (best effort, and only after checking the
   swap did not in fact commit). A hard kill cannot, so it leaves unreferenced objects of an
   uncommitted generation; the previous workspace is untouched and
   ``lifecycle.reconcile_tenant_storage`` lists them.

The local half is the core's own ``PersistenceService.save_workspace`` / ``load_workspace``,
unchanged: this class runs them against a per-call temporary directory (``scratch_dir``,
removed afterwards, also on failure) and moves the resulting files to and from the store.
Everything fetched is verified against the manifest's SHA-256 *and* size, independently of
the object's own metadata, and every manifest key is checked to belong to this organization
before any request is made.

Loading is lazy at the granularity the core allows: :meth:`datasets` reads only the head row
(names, row and column counts), and :meth:`load` with ``dataset_ids`` downloads the database
plus only those frames, rebuilding only their visualizations (the temporary database copy is
pruned of the other datasets first, so the core never asks for their frames). Cost: the whole
``workspace.db`` (kilobytes to a few megabytes) plus the requested frames per call; a request
needing no frame should use :meth:`datasets` instead. Not done: column-level or row-group
reads of a frame, and caching frames across requests.

Not done here: syncing ``DatasetRecord`` rows with the workspace (the 3.6 API owns that), and
quotas. Closing a dataset should be a save without it; deleting its row alone leaves its frame
in the saved workspace (the sweeper then *defers* that deletion, see ``lifecycle``).
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import tempfile
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from uadas_api.storage import keys
from uadas_api.storage.errors import (
    ConcurrentSaveError,
    ManifestError,
    ObjectNotFoundError,
    ObjectTooLargeError,
    StorageError,
    WorkspaceNotFoundError,
)
from uadas_api.storage.lifecycle import queue_object_deletion, schedule_purge
from uadas_api.storage.manifest import (
    DatasetEntry,
    Manifest,
    ObjectRef,
    keys_of,
    owned_keys_of,
)
from uadas_api.storage.models import WorkspaceHead
from uadas_api.storage.store import TenantObjectStore, get_store
from uadas_api.tenancy import TenantIsolationError
from uadas_api.workspaces.models import Project
from uadas_core.core.exceptions import ServiceError
from uadas_core.models import Dashboard, Dataset, Visualization
from uadas_core.persistence.persistence_service import (
    PersistenceService,
    SaveReport,
    WorkspaceSnapshot,
)

_logger = logging.getLogger(__name__)

PARQUET = "application/vnd.apache.parquet"
SQLITE = "application/vnd.sqlite3"
DEFAULT_MAX_LOAD_BYTES = 2 * 1024**3
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class LoadedWorkspace:
    """A loaded snapshot and the head version it was read at (pass it to the next save)."""

    snapshot: WorkspaceSnapshot
    version: int
    loaded_dataset_ids: list[str]


@dataclass(frozen=True)
class SaveOutcome:
    """What a committed save did. ``reused`` frames were not re-uploaded."""

    version: int
    report: SaveReport
    uploaded: int
    reused: int
    retired: int


def _default_persistence() -> PersistenceService:
    from uadas_api.core_bridge import get_process_context

    return get_process_context().container.resolve(PersistenceService)


def _digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _prune_database(path: Path, keep: Collection[str]) -> None:
    """Remove every dataset (and its visualizations) not in ``keep`` from a *temporary* copy.

    The core's loader requires a frame for every dataset row, so asking for a subset means
    handing it a database that only describes that subset. Dashboard tiles are left alone:
    a tile whose visualization is gone is legal state the core tolerates.
    """
    try:
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            drop = [
                (row[0],)
                for row in connection.execute('SELECT "dataset_id" FROM datasets')
                if row[0] not in keep
            ]
            connection.executemany(
                'DELETE FROM visualizations WHERE "dataset_id" = ?', drop
            )
            connection.executemany('DELETE FROM datasets WHERE "dataset_id" = ?', drop)
            connection.commit()
        finally:
            connection.close()
    except sqlite3.Error as error:
        raise ServiceError(
            f"Could not narrow the workspace to the requested datasets: {error}"
        ) from error


class StorageBackedPersistence:
    """Load and save one project's workspace through object storage. See the module docstring."""

    def __init__(
        self,
        project: Project,
        *,
        store: TenantObjectStore | None = None,
        persistence: PersistenceService | None = None,
        scratch_dir: Path | None = None,
    ) -> None:
        self._project = project
        self._org = project.organization_id
        self._store = store or get_store(self._org)
        if self._store.organization_id != str(self._org):
            raise TenantIsolationError(
                "the object store handle belongs to a different organization than the project"
            )
        self._persistence = persistence or _default_persistence()
        self._scratch_dir = scratch_dir

    # --- the head ---------------------------------------------------------------------

    def _head(self) -> WorkspaceHead | None:
        return (
            WorkspaceHead.objects.for_organization(self._org)
            .filter(project_id=self._project.pk)
            .first()
        )

    def current_version(self) -> int:
        """The committed version (0 when nothing has been saved): what a save must expect."""
        head = self._head()
        return head.version if head is not None else 0

    def datasets(self) -> list[DatasetEntry]:
        """List the saved datasets (name, rows, columns, hash) from the head row alone.

        No object request is made: this is the cheap way to answer "what is in this
        project?" without paying for any frame.
        """
        head = self._head()
        if head is None:
            return []
        manifest = Manifest.from_json(head.manifest, self._org, self._project.pk)
        return sorted(
            manifest.datasets.values(), key=lambda entry: (entry.name, entry.key)
        )

    # --- load -------------------------------------------------------------------------

    def load(
        self,
        *,
        dataset_ids: Iterable[str] | None = None,
        max_total_bytes: int = DEFAULT_MAX_LOAD_BYTES,
    ) -> LoadedWorkspace:
        """Load the committed workspace (or only ``dataset_ids`` of it) into memory.

        Every object is verified against the manifest's hash and size; the manifest's keys
        are checked against this organization before anything is fetched. ``max_total_bytes``
        bounds what a single call may pull into the scratch directory. Raises
        :class:`WorkspaceNotFoundError` when nothing was ever saved.

        A load that reads the head and then finds an object gone has raced a save that
        committed and collected the previous generation's garbage in between (a *valid*
        workspace, merely superseded). It re-reads the head and retries **once**, and only if
        the head actually moved; an object missing from an unchanged head is real corruption
        and raises.
        """
        head = self._head()
        if head is None:
            raise WorkspaceNotFoundError("this project has no saved workspace")
        try:
            return self._load_head(head, dataset_ids, max_total_bytes)
        except ObjectNotFoundError:
            newer = self._head()
            if newer is None or newer.version == head.version:
                raise
            return self._load_head(newer, dataset_ids, max_total_bytes)

    def _load_head(
        self,
        head: WorkspaceHead,
        dataset_ids: Iterable[str] | None,
        max_total_bytes: int,
    ) -> LoadedWorkspace:
        dataset_ids = None if dataset_ids is None else list(dataset_ids)
        manifest = Manifest.from_json(head.manifest, self._org, self._project.pk)
        wanted = self._select(manifest, dataset_ids)
        entries = [manifest.datasets[dataset_id] for dataset_id in wanted]
        if manifest.workspace_db.size + sum(e.size for e in entries) > max_total_bytes:
            raise ObjectTooLargeError(
                "the requested datasets exceed the load size budget"
            )
        subset = len(wanted) != len(manifest.datasets)
        with tempfile.TemporaryDirectory(
            prefix="uadas-ws-", dir=self._scratch_dir
        ) as scratch:
            base = Path(scratch)
            self._fetch(manifest.workspace_db, base / "workspace.db")
            for dataset_id, entry in zip(wanted, entries, strict=True):
                self._fetch(entry, base / f"{dataset_id}.parquet")
            if subset:
                _prune_database(base / "workspace.db", wanted)
            snapshot = self._persistence.load_workspace(base)
        return LoadedWorkspace(
            snapshot=snapshot, version=head.version, loaded_dataset_ids=list(wanted)
        )

    def _select(
        self, manifest: Manifest, dataset_ids: Iterable[str] | None
    ) -> list[str]:
        if dataset_ids is None:
            return sorted(manifest.datasets)
        wanted: list[str] = []
        for raw in dataset_ids:
            dataset_id = keys.uuid_text(raw, "dataset id")
            if dataset_id not in manifest.datasets:
                raise ObjectNotFoundError("the workspace does not contain that dataset")
            if dataset_id not in wanted:
                wanted.append(dataset_id)
        return wanted

    def _fetch(self, ref: ObjectRef, target: Path) -> None:
        self._store.download_to(
            ref.key, target, expected_sha256=ref.sha256, max_bytes=ref.size
        )
        if target.stat().st_size != ref.size:
            target.unlink(missing_ok=True)
            raise ManifestError(
                "a stored object's size differs from its manifest entry"
            )

    # --- save -------------------------------------------------------------------------

    def save(
        self,
        datasets: list[Dataset],
        visualizations: list[Visualization],
        dashboards: list[Dashboard],
        *,
        expected_version: int,
    ) -> SaveOutcome:
        """Replace the saved workspace atomically; ``expected_version`` is what the caller loaded.

        ``0`` means "I believe nothing has been saved". A mismatch -- checked up front, and
        again by the conditional row update at the swap -- raises
        :class:`ConcurrentSaveError`: reload, reconcile and retry. Raises the core's
        ``ServiceError`` when its own save fails, and a storage error when an upload fails;
        in every failure case the previously saved workspace is untouched and loadable.
        """
        head = self._head()
        current = head.version if head is not None else 0
        if current != expected_version:
            raise ConcurrentSaveError(
                "the workspace changed since it was loaded; reload before saving"
            )
        previous = self._previous_manifest(head)
        token = keys.new_save_token(current + 1)
        uploaded: list[str] = []
        with tempfile.TemporaryDirectory(
            prefix="uadas-ws-", dir=self._scratch_dir
        ) as scratch:
            base = Path(scratch) / "workspace"
            report = self._persistence.save_workspace(
                datasets, visualizations, dashboards, base
            )
            try:
                entries, reused = self._upload_frames(
                    datasets, base, previous, token, uploaded
                )
                db_ref = self._upload_file(
                    base / "workspace.db",
                    keys.workspace_db_key(self._org, self._project.pk, token),
                    SQLITE,
                    uploaded,
                    {"kind": "workspace"},
                )
                manifest = Manifest(token=token, workspace_db=db_ref, datasets=entries)
                # Only keys inside this project's own namespaces may ever be queued for
                # deletion: an edited manifest cannot make a save erase someone else's objects.
                old_keys = (
                    owned_keys_of(head.manifest, self._org, self._project.pk)
                    if head is not None
                    else set()
                )
                retired = old_keys - manifest.keys()
                self._commit_head(current, manifest.to_json(), retired)
            except BaseException:
                self._abandon(uploaded, current + 1, token)
                raise
        return SaveOutcome(
            version=current + 1,
            report=report,
            uploaded=len(uploaded),
            reused=reused,
            retired=len(retired),
        )

    def _previous_manifest(self, head: WorkspaceHead | None) -> Manifest | None:
        if head is None:
            return None
        try:
            return Manifest.from_json(head.manifest, self._org, self._project.pk)
        except ManifestError:
            # A corrupt head cannot be reused from, but it must not make saving impossible:
            # a fresh save is how it gets repaired. Its in-namespace objects are retired.
            _logger.error(
                "the stored workspace manifest is invalid; saving without reuse"
            )
            return None

    def _upload_file(
        self,
        path: Path,
        key: str,
        content_type: str,
        uploaded: list[str],
        metadata: dict[str, str],
    ) -> ObjectRef:
        with path.open("rb") as handle:
            stored = self._store.put(
                key,
                handle,
                content_type=content_type,
                allowed_content_types={content_type},
                metadata=metadata,
            )
        uploaded.append(key)
        if (
            stored.sha256 is None
        ):  # the facade always records one; refuse to commit without
            raise ManifestError(
                "the store did not record a hash for an uploaded object"
            )
        return ObjectRef(key=key, sha256=stored.sha256, size=stored.size)

    def _upload_frames(
        self,
        datasets: list[Dataset],
        base: Path,
        previous: Manifest | None,
        token: str,
        uploaded: list[str],
    ) -> tuple[dict[str, DatasetEntry], int]:
        entries: dict[str, DatasetEntry] = {}
        reused = 0
        for dataset in datasets:
            dataset_id = keys.uuid_text(dataset.dataset_id, "dataset id")
            local = base / f"{dataset.dataset_id}.parquet"
            digest, size = _digest(local)
            old = previous.datasets.get(dataset_id) if previous is not None else None
            if old is not None and old.sha256 == digest and old.size == size:
                ref = ObjectRef(key=old.key, sha256=old.sha256, size=old.size)
                reused += 1
            else:
                ref = self._upload_file(
                    local,
                    keys.dataset_frame_key(self._org, dataset_id, token),
                    PARQUET,
                    uploaded,
                    {"kind": "frame", "dataset-id": dataset_id},
                )
            entries[dataset_id] = DatasetEntry(
                key=ref.key,
                sha256=ref.sha256,
                size=ref.size,
                name=dataset.name,
                rows=int(dataset.row_count),
                columns=int(dataset.column_count),
            )
        return entries, reused

    def _commit_head(
        self, expected_version: int, manifest: dict[str, Any], retired: set[str]
    ) -> None:
        """The swap: move the head from ``expected_version`` to the next, and owe the retired keys.

        One transaction: the conditional update (or, for a first save, the insert that the
        unique constraint serialises) and the ``OrphanedObject`` rows for everything the old
        manifest referenced and the new one does not. Zero rows updated means another writer
        committed first.
        """
        with transaction.atomic():
            if expected_version == 0:
                try:
                    with transaction.atomic():
                        WorkspaceHead.objects.create(
                            organization_id=self._org,
                            project_id=self._project.pk,
                            version=1,
                            manifest=manifest,
                        )
                except IntegrityError:
                    raise ConcurrentSaveError(
                        "another save created this project's workspace first"
                    ) from None
            else:
                changed = (
                    WorkspaceHead.objects.for_organization(self._org)
                    .filter(project_id=self._project.pk, version=expected_version)
                    .update(
                        version=expected_version + 1,
                        manifest=manifest,
                        updated_at=timezone.now(),
                    )
                )
                if changed != 1:
                    raise ConcurrentSaveError(
                        "another save committed first; reload before saving"
                    )
            for key in sorted(retired):
                queue_object_deletion(self._org, key, reason="workspace-retired")
            if retired:
                # Registered *inside* the transaction: if anything above fails, the head update,
                # the debt and the sweep registration all vanish together.
                schedule_purge(self._org)

    def _abandon(self, uploaded: list[str], new_version: int, token: str) -> None:
        """Best-effort removal of a failed save's uploads -- unless the swap actually committed.

        An exception from the commit does not prove it did not happen (the connection can die
        after the server committed), so the head is re-read and **every key the current head
        still references is kept**, whatever its version or token: if this attempt's swap did
        commit (or a later save moved the head on but kept a reused frame) those objects are
        live. Only keys the head does not reference are deleted. If the head cannot be read the
        objects are left for the reconciliation report rather than risk deleting live data.
        ``new_version`` and ``token`` are kept for the log line of a confirmed commit.
        """
        try:
            head = self._head()
        except DatabaseError:
            _logger.error(
                "could not confirm the save outcome; leaving its uploads in place"
            )
            return
        live = keys_of(head.manifest) if head is not None else set()
        if head is not None and head.version == new_version:
            _logger.info("the save committed despite the error; keeping its objects")
        for key in uploaded:
            if key in live:
                continue
            try:
                self._store.delete(key)
            except StorageError:
                _logger.warning(
                    "could not remove an object of a failed save; it is unreferenced"
                )
