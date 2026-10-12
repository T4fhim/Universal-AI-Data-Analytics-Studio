# Phase 3.4 — Storage

**Branch:** `phase-3/django-backend` · **Code:** `apps/api/uadas_api/storage/`, `settings/_storage.py` ·
**Prior:** [phase-3-session-seam.md](phase-3-session-seam.md), [phase-3-2-data-model.md](phase-3-2-data-model.md)
**Scope:** S3-compatible storage behind one tenant facade; the Phase 2.7 atomic save over objects; row/object
lifecycle. **Not here:** the upload endpoint and parsing (3.5/3.8 sandbox), background jobs, quotas.

## Key layout (`keys.py`, the only place keys are built)

```
<org>/datasets/<dataset_id>/original/<uuid4hex>                 uploaded original
<org>/datasets/<dataset_id>/frames/<save_token>.parquet         materialised frame
<org>/projects/<project_id>/workspace/<save_token>/workspace.db  workspace metadata
<org>/exports/<report_id>/<uuid4hex>.<ext>                       generated report
```

Builders take identifiers, never names: a user's file name is object metadata (percent-encoded). Every key passes
`tenancy.validate_storage_key` (`<org>/` prefix, ASCII `[A-Za-z0-9._-]` segments, no `.`/`..`/trailing dot/empty
segment) plus 512/128-character limits; NUL, `%2e`, backslash and Unicode look-alikes fail the grammar.

## `TenantObjectStore` (`store.py`) — the only way in

Bound to one organization; **every** operation re-validates its key before any request, so A's key cannot be read,
written, deleted, listed, copied or presigned through B's handle. put (bytes/stream, size cap that no call can raise,
mandatory content-type allow-list, create-only unless `overwrite=True`), get/open/download_to (SHA-256 verified; an object
with no recorded hash is refused), head/exists, delete, `delete_prefix` (directory semantics, refuses `<org>/` unless
`allow_org_root`), list_prefix, `presigned_get` (default = maximum = `STORAGE_PRESIGN_SECONDS` ≤ 900), copy. Backends
(`s3.py` boto3 via django-storages, `memory.py` fake) implement `backend.ObjectBackend`; `test_storage_boundary.py` fails if
any other module imports the SDKs or a backend. No ACL is ever sent; SSE-S3 only when `STORAGE_SSE=aes256`. The S3 backend
sends `ChecksumSHA256`, so the store itself rejects a corrupted single-request upload (proved on MinIO).

## D4 on object storage (`workspace.py`, `StorageBackedPersistence`)

Property kept: *a failure or crash at any step leaves the previous save loadable.* A store has no rename and a PUT overwrites,
so: (1) every object of a save goes to a **new key** containing a per-attempt token (`g0000007-<random>`), never a key the
head references; unchanged frames (equal SHA-256) are reused, not re-uploaded. Generation-only keys would let two concurrent
saves collide on one key, hence the random suffix. (2) The swap is one **conditional row update** of `WorkspaceHead`
(`UPDATE … WHERE version = n`), holding the manifest (db + frame keys, hashes, sizes, names, counts). (3) Objects only the old
manifest referenced are written to `OrphanedObject` **in the swap's transaction** and deleted after commit; failure is
housekeeping. (4) A failed save deletes its own uploads (after re-checking that the swap did not commit); a hard kill leaves
unreferenced objects, listed by `reconcile_storage`. The core is unchanged: it saves into a per-call temp dir and the files
move to/from the store; loads verify hash **and** size against the manifest, and every manifest key is re-checked per tenant.

**Concurrency choice:** a version column on a Postgres row, not S3 conditional PUT / ETag. The row update is atomic and
conditional on every backend we run (SQLite, Postgres) and is the swap itself; `If-Match`/`If-None-Match` writes are not on
every S3-compatible store, and one that ignores the header turns compare-and-swap into last-writer-wins silently. Callers pass
the loaded version as `expected_version`; a stale one (or a lost race) raises `ConcurrentSaveError`. Proved with a
deterministic interleaving on both DBs and two real threads on Postgres.

**Lazy loading:** `datasets()` reads only the head row (no object I/O). `load(dataset_ids=[…])` downloads `workspace.db` plus
those frames only, after pruning the *temporary* db copy of other datasets so the core never asks for their frames and
rebuilds only their charts. Cost per call: the whole db (KB-MB) + requested frames. Not done: column/row-group reads, caching.

## Lifecycle (`lifecycle.py`, `signals.py`) — outbox, not a distributed transaction

`post_delete` on `DatasetRecord`/`Report`/`WorkspaceHead` queues the row's objects (a dataset's whole directory) inside
the delete's transaction; `on_commit` deletes them, idempotently; failures stay queued (attempts + error class).
`manage.py purge_orphaned_objects [--min-age]` is the sweeper (least-attempted entries first, so stuck entries cannot starve new
ones; what heads reference is read once per organization per sweep; one after-commit sweep per organization per transaction).
**What a sweep may delete (the in-flight-save race):** an exact (retired) key only once its debt is older than the grace period
(`STORAGE_GC_GRACE_SECONDS`, default 1 h, applied to the on-commit path too, which also covers a load racing the post-swap
delete); a directory entry only objects whose `last_modified` is not after the debt (compared conservatively, as stores stamp
whole seconds) and older than the grace, and never a referenced one. A debt is settled when nothing it covers remains. `load()`
re-reads the head and retries once if an object vanished and the head moved. Objects a current head references are **deferred**. Only `<org>/datasets/<uuid>` and `<org>/projects/<uuid>` directories can be
queued or paid wholesale, and a manifest's keys are bound to its own project/dataset namespaces (a tampered manifest naming
another project's objects is refused on load and ignored when queueing deletions).
`reconcile_tenant_storage` / `manage.py reconcile_storage` is read-only: rows without objects, objects without rows (with
`--min-age` for in-flight uploads), pending deletions. Two new tenant tables (`WorkspaceHead`, `OrphanedObject`), one migration.

## Threat notes

Isolation is by key prefix with one bucket credential: a bug in the facade, not IAM, is the boundary (hence the boundary
test, harness coverage and mutation-checked tests). A tampered DB manifest naming another tenant is refused before any fetch;
bucket-side tampering is caught by manifest hashes; bucket public-ness is the operator's (private ACL default, signed URLs
only, an anonymous GET is refused on MinIO in the integration test). Presigned URLs are bearer links for ≤ 15 minutes.

## Known limits (from review)

`StorageBackedPersistence.save` must run **outside** an outer transaction (no `ATOMIC_REQUESTS`; a test pins that): inside
one, the swap is only a savepoint and the caller could be told "committed" before it is. Deleting N rows in one transaction
schedules one after-commit sweep per organization, synchronous on the request thread. Retired objects live for the grace period
after a save (storage cost, by design). `storages["tenant_objects"]` stays reachable through Django's registry (no way to hide
it): a static scan of `uadas_api` and `uadas_core` (`test_storage_boundary.py`) is the guard, and cannot see dynamic access.
Prod requires SSE-S3 (or an explicit acknowledgement); S3 reports the applied encryption and the facade verifies it, MinIO does not.
CI fails when `CI=true` loses the MinIO environment and when more than 2 tests skip. `reconcile_tenant_storage` holds one
organization's listing in memory.

## Deferred / not done

Upload endpoint, malware/format validation, per-tenant quotas, bucket-lifecycle expiry of abandoned uploads, an age-based
sweeper for crashed-save strays (reconcile only reports), syncing `DatasetRecord` rows with the manifest (3.6; deleting a row
whose frame a head still references is deferred, close datasets by saving without them), KMS/SSE-C, multipart integrity beyond
the metadata hash, frame caching across requests, `QuerySet._raw_delete`/raw SQL bypassing the delete signals.
