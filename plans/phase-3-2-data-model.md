# Phase 3.2 — Data model + tenancy

**Branch:** `phase-3/django-backend` · **Code:** `apps/api/uadas_api/` · **Prior:** [phase-3-readiness.md](phase-3-readiness.md)
**Plan rule honoured:** the tenant-isolation harness (`tests/test_tenant_isolation.py`) was written before any
tenant model beyond the identity trio existed, and is discovery-based (see Tenancy). Three independent reviews then
found nine defects; all are fixed and each has a test (the Hardening section).

## Models

All primary keys are UUIDs (non-enumerable ids). `T` = tenant-owned (`organization` FK, `PROTECT`).

| Model | App | T | Notes / constraints |
|---|---|---|---|
| `User` | accounts | no | Email login, NFKC-normalised; `UNIQUE (lower(email))` (+ `unique=True`, required by `auth.E003`) |
| `Organization` | accounts | no | The tenant. `slug` unique |
| `Membership` | accounts | no | user + organization + `role` ∈ owner/admin/editor/viewer (DB `CHECK`); unique (user, organization); user and organization immutable |
| `AuditEvent` | accounts | yes | actor detached on user delete, `action`, `target_type`, `target_id` (text), `metadata`; **append-only** |
| `Project` | workspaces | yes | unique (organization, name); `created_by` `SET_NULL` |
| `DatasetRecord` | workspaces | yes | `id` = core `dataset_id`; `parent_dataset_id` plain nullable UUID (**not** an FK); `storage_key`; counts `>= 0`; not its own parent |
| `ChartSpec` | workspaces | yes | `dataset` `SET_NULL`; `chart_type`, `spec` JSON, `title` |
| `Dashboard` | workspaces | yes | `layout` JSON (tile grid) |
| `PipelineNode` | pipeline | yes | `kind` ∈ dataset/artifact; `dataset` `SET_NULL`; `payload` JSON |
| `PipelineEdge` | pipeline | yes | source/target → node `CASCADE`; `kind` = transform; unique (source, target, kind); `source != target` |
| `Recipe` | pipeline | yes | `version >= 1`; unique (project, name, version); `definition` = exported DAG JSON |
| `Report` | exports | yes | format, status (pending/ready/failed), `storage_key` (blank until ready), `config` |

`ai` has no models yet. `AUTH_USER_MODEL = "accounts.User"` is set in the same change as the first migrations.

## Tenancy rules (`uadas_api/tenancy.py`)

`TenantOwnedModel` supplies `id`, a non-null `organization` FK (`PROTECT`, `related_name="+"`) and a
`TenantManager`/`TenantQuerySet` (`for_organization(org | pk)`). Enforced in Python on `save()`, `bulk_create()`,
`bulk_update()` and `queryset.update()`, **and on `_base_manager`** (every tenant model sets `base_manager_name =
"objects"`, because related managers such as `project.datasets.add(row)` and the delete collector use it):

1. every FK to another tenant row, and every declared plain-UUID reference (`soft_tenant_refs`), stays inside the
   same organization (a soft reference may *dangle*, per the core's non-cascade rule, but not cross tenants);
2. `organization` (and `Membership.user`/`.organization`) is immutable once saved, including after a deferred
   `.only()` load (the stored value is fetched) and when a bulk write also changes a link;
3. `bulk_create(update_conflicts=True)` is refused on every tenant model (an upsert by id re-parents another tenant's row);
4. `storage_key` (`DatasetRecord`, `Report`) starts with `"<organization_id>/"` and every segment matches
   `[A-Za-z0-9._-]+`, is not `.`/`..` and does not end with `.` (so `%2e%2e`, a `..` with a trailing space, and Unicode lookalikes are refused).

Errors name the field, never the foreign row's id. Harness: discovers every concrete `TenantOwnedModel` and checks FK
shape, `for_organization` scoping, cross-tenant rejection and same-tenant acceptance on four write paths, related-manager
`add()`, per-organization uniqueness, PROTECT on organization delete, immutability, storage keys, index coverage (the
`organization` FK has no index of its own because every table has a composite leading with it; the harness fails on a
missing or a duplicate one), no many-to-many fields, and an independent `_meta.get_fields()` cross-check of the FK
discovery. It fails if a model has no factory, and every `uadas_api` model must be tenant-owned or allowlisted.

## Hardening after review (all tested)

Upsert re-parenting; `_base_manager` bypass (also unlocked `AuditEvent`: the actor is now detached by a custom
`on_delete`, because the delete collector applies `SET_NULL` with `QuerySet.update`); `bulk_update` skipping the
immutability check; deferred loads; cross-tenant `parent_dataset_id`; email lookup (`LOWER(email)` like the constraint, not
`iexact`), NFKC, `full_clean` in `create_user`; membership immutability; storage-key grammar; redundant indexes dropped.

## Limitations and obligations (stated plainly)

- **No database enforcement of tenancy.** Django has no composite foreign keys; raw SQL, `_raw_delete`, fixtures, psql and
  other writers bypass the Python guard. Row-level security or a trigger would close it; not done.
- **JSON fields that carry ids are UNVALIDATED:** `ChartSpec.spec`, `Dashboard.layout`, `PipelineNode.payload`,
  `Recipe.definition`, `Report.config`. **Obligation for 3.6:** every reader must resolve such ids through
  `for_organization`, never `objects.get(pk=id_from_json)`.
- `update()` verifies a model/PK value; an expression on a tenant reference is refused, not checked.
- Same-**project** consistency (an edge whose endpoints sit in different projects of one organization) is not enforced.
- `PROTECT` on a project only stops `Project.delete()`; `DatasetRecord.delete()`/`Report.delete()` succeed and orphan the
  bucket object. Deleting such rows must go through a service that deletes the object first (Phase 3.4).
- `AuditEvent` is append-only in Python only (a trigger or revoked privileges would survive raw SQL). An organization with
  audit history can never be deleted, and no organization-offboarding path exists: **a 3.3 follow-up.**
- **Last-owner protection** (an organization must keep an owner) is deferred to 3.3 with permissions.
- Storage-key prefixing is not a DB `CHECK` (UUID text casts differ between SQLite and Postgres).
- UUIDv4 keys fragment B-tree indexes; UUIDv7 is a later optimisation, not done here.
- Verified on SQLite only; Postgres 17 runs in CI's `api-test` job (Docker was down locally).

## Deviations from the brief (flagged)

The core has **no node/edge-kind enum** (kinds = dataclass types) and no source-format registry (literals in readers), so
parity is derived (`ast` scan; `*Node`/`*Edge` classes). `Report.storage_key` may be blank until `ready` (a `ready` report
needs one, `CHECK`). `chart_type` stores registry names (`"bar"`), not `Visualization.chart_type` class names (`"BarChart"`).
`Recipe.version` is an integer revision; the core's string `Recipe.version` ("1.0") lives inside `definition`.
