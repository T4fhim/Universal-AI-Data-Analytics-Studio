# uadas-api

The Django 6 + Django Ninja backend for the Universal AI Data Analytics Studio web app
(Phase 3 of [the web-transition plan](../../plans/web-transition-glass-box-studio.md)).
It is a separate distribution from the framework-free core (`uadas_core`, repo root) and
depends on it; the core never imports it (enforced by `.importlinter`).

**Status: sub-step 3.6, the API surface** (on top of 3.5 background jobs and the parser sandbox,
3.4 object storage, 3.3 authentication and per-organization roles). Seven Django apps (`accounts`,
`workspaces`, `pipeline`, `ai`, `exports`, `storage`, `jobs`), split settings, the models described
under [Data model](#data-model), sign-in through django-allauth (headless, session cookies), the
routes listed under [Authentication](#authentication) and [Endpoints](#endpoints) (projects,
datasets with a paged preview and upload, jobs, charts, dashboards, reports, lineage and one router
per pipeline stage), tenant-scoped S3-compatible storage ([Object storage](#object-storage)) and
durable background jobs with a sandboxed file parser
([Background jobs](#background-jobs-and-the-parser-sandbox)). `GET /api/health` stays public and
database-free. `AUTH_USER_MODEL = "accounts.User"`. Decisions and limits:
[plans/phase-3-3-auth.md](../../plans/phase-3-3-auth.md),
[plans/phase-3-4-storage.md](../../plans/phase-3-4-storage.md),
[plans/phase-3-5-jobs.md](../../plans/phase-3-5-jobs.md),
[plans/phase-3-6-api.md](../../plans/phase-3-6-api.md).

## Install

From the repository root, in a Python 3.13 virtualenv:

```bash
pip install -r requirements.txt -e . -e apps/api
# development tools (pytest-django, coverage, django-stubs):
pip install -e "apps/api[dev]"
```

## Run

```bash
cd apps/api
python manage.py check                 # uses uadas_api.settings.dev by default
python manage.py runserver             # dev settings: DEBUG on, SQLite db.sqlite3
curl http://127.0.0.1:8000/api/health  # {"status":"ok"}
```

`manage.py` defaults to `uadas_api.settings.dev`. `wsgi.py` / `asgi.py` default to
`uadas_api.settings.prod`, which refuses to start without a secret key and host list, so
a container that forgot to choose settings fails closed.

Settings modules: `base` (shared; no insecure defaults), `dev`, `test`, `prod`. Choose one
with `DJANGO_SETTINGS_MODULE`.

## Environment variables

Configuration is 12-factor: environment variables only. Do not commit `.env` files.

| Variable | Used by | Default | Meaning |
|---|---|---|---|
| `DJANGO_SETTINGS_MODULE` | all | `uadas_api.settings.dev` (`manage.py`), `.prod` (wsgi/asgi) | Which settings module is active. |
| `DJANGO_SECRET_KEY` | base, dev, prod | none (`dev`: an insecure built-in key) | Required in prod, at least 50 characters and not a `django-insecure-` placeholder; prod raises `ImproperlyConfigured` otherwise. |
| `DJANGO_DEBUG` | base, dev | `false` | `1`/`true`/`yes`/`on` or `0`/`false`/`no`/`off`; anything else raises. Ignored by prod (always off) and dev (always on). |
| `DJANGO_ALLOWED_HOSTS` | base, prod | none | Comma-separated host names. Required in prod; `*` is refused there. |
| `DATABASE_URL` | all | none (`dev`: `sqlite:///apps/api/db.sqlite3`; `test`: in-memory SQLite) | Parsed by `dj-database-url`, e.g. `postgres://user:pw@host:5432/db`. Required in prod. |
| `CORS_ALLOWED_ORIGINS` | base | none | Comma-separated origins allowed to call the API cross-origin. |
| `CSRF_TRUSTED_ORIGINS` | base | none | Comma-separated trusted origins for CSRF checks. |
| `DJANGO_SECURE_SSL_REDIRECT` | prod | `true` | Redirect HTTP to HTTPS; turn off when a proxy already does. |
| `DJANGO_SECURE_HSTS_SECONDS` | prod | `31536000` | HSTS max-age; must be a positive integer. |
| `DJANGO_SECURE_PROXY_SSL_HEADER` | prod | `false` | Trust `X-Forwarded-Proto: https`. Enable only behind a proxy that sets and strips it. |
| `DJANGO_TRUSTED_PROXY_COUNT` | prod | `0` | Number of proxies you control in front of the app (allauth's per-IP rate limits read the client address from `X-Forwarded-For`). `0` behind a proxy makes every client share the proxy's address; too high lets a client spoof it. |
| `REDIS_URL` | base, prod | none (`dev`/`test`: per-process cache) | Redis for the shared cache that holds allauth's rate-limit counters, e.g. `redis://host:6379/0`. **Required in prod.** |
| `FRONTEND_BASE_URL` | prod | none (`dev`/`test`: `http://localhost:5173`) | The SPA's address; verification and password-reset emails link to it. Absolute URL; must be `https://` in prod. **Required in prod.** |
| `UADAS_CORE_LOG_LEVEL` | base | `INFO` | Log level of the framework-free core, which runs in server mode here (stderr only, no plugins, no YAML) via `uadas_api/core_bridge.py`. One of `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`; anything else raises. `DEBUG` is refused unless Django `DEBUG` is on (and always in prod): core debug logs are shared by every tenant. |
| `DEFAULT_FROM_EMAIL` | prod | none | Sender of verification / reset mail, e.g. `UADAS <no-reply@example.com>`. **Required in prod.** |
| `EMAIL_HOST` | prod | none | SMTP relay host. **Required in prod.** |
| `EMAIL_PORT` | prod | `587` | SMTP port. |
| `EMAIL_USE_TLS` | prod | `true` | STARTTLS to the relay. |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | prod | none | SMTP credentials; unset means an unauthenticated relay. Environment only, never committed. |
| `STORAGE_BUCKET` | base, prod | none (`dev`: `uadas-uploads`) | The S3-compatible bucket holding every tenant's objects (3-63 lowercase letters, digits, dots, hyphens). The bucket and both credentials travel together; any one alone fails start-up. **Required in prod.** |
| `STORAGE_ACCESS_KEY_ID`, `STORAGE_SECRET_ACCESS_KEY` | base, prod | none (`dev`: the docker-compose MinIO root pair) | Explicit credentials; ambient `AWS_*` variables, profiles and instance roles are deliberately never consulted. **Required in prod**, where a short (< 24 characters), low-variety, placeholder-looking (`changeme`, `example`, `minioadmin`, ...) or access-key-equal secret is refused. Environment only. |
| `STORAGE_ENDPOINT_URL` | base, prod | none = AWS (`dev`: `http://localhost:9000`) | S3-compatible endpoint (MinIO, R2); scheme and host only, no credentials, path or query. Must be `https://` in prod. |
| `STORAGE_REGION` | base | `us-east-1` | Signing region, e.g. `us-east-1` (`auto` for Cloudflare R2). |
| `STORAGE_ADDRESSING` | base | `auto` (`dev`: `path`) | `auto`, `path` or `virtual` (S3 addressing style; MinIO needs `path`). |
| `STORAGE_SSE` | base, prod | `none` | `none` or `aes256`: send `ServerSideEncryption: AES256` (SSE-S3) on writes; where the store reports the encryption it applied, a different answer fails the write and removes the object. **Prod requires `aes256`**, or `none` together with `STORAGE_ENCRYPTION_ACKNOWLEDGED=1`. MinIO rejects the header without a KMS; R2 always encrypts. |
| `STORAGE_ENCRYPTION_ACKNOWLEDGED` | prod | `false` | `1` in prod when `STORAGE_SSE=none` is deliberate (the bucket/store encrypts at rest by default and rejects the header). Ignored when `aes256` is set. |
| `STORAGE_GC_GRACE_SECONDS` | base | `3600` (`test`: `0`) | Grace period before an owed deletion is paid, 0 to 604800: retired objects wait this long after the swap (a reader that loaded the previous workspace may still need them) and a directory purge never touches objects younger than this or written after its debt was queued (an in-flight save's upload). `purge_orphaned_objects --min-age` overrides it per run. |
| `STORAGE_PRESIGN_SECONDS` | base | `300` | Default and maximum lifetime of a presigned download URL, 1-900. |
| `STORAGE_MAX_OBJECT_BYTES` | base | `1073741824` | Deployment-wide size cap of one stored object; no call can raise it. |
| `STORAGE_INTEGRATION` | tests only | unset | `1` (with `STORAGE_ENDPOINT_URL`, `STORAGE_BUCKET` and the two credentials) also runs the storage tests against a real store. The `test` settings never read any `STORAGE_*`. |
| `CELERY_BROKER_URL` | base, prod | `REDIS_URL` **moved to another database number** (`/1`, or `/2` if the cache is on 1; `dev`: `redis://localhost:6379/0`; `test`: in-memory, ignored) | The job queue's broker, `redis://` / `rediss://`. **Prod requires one** (and refuses `memory://`) and **refuses one on the cache's Redis database**: the cache's `clear()` flushes its whole database, queued jobs included. |
| `JOBS_EAGER` | dev | `false` | `1` runs jobs inline in the calling process (a quick poke without a worker; the parse itself still happens in the sandbox child). **Refused in prod.** `test` is always eager. |
| `JOBS_QUEUE` | base | `uadas-jobs` | Queue name (1-64 of `A-Za-z0-9._-`). |
| `JOBS_MAX_ATTEMPTS` | base | `3` | 1-10. Runs per job (the first plus retries), counted in the database so it also bounds broker redeliveries of a task that kills its worker. |
| `JOBS_STALE_AFTER_SECONDS` | base | `300` | 30-3600. A `running` job whose heartbeat is older is considered dead (another worker may take it over; the sweeper repairs it). A heartbeat thread beats for the whole run, so this is the window for a *dead* worker. **Must exceed `SANDBOX_WALL_SECONDS` by more than 60** (and so must `JOBS_TIME_LIMIT_SECONDS`), or start-up fails. |
| `JOBS_SOFT_TIME_LIMIT_SECONDS`, `JOBS_TIME_LIMIT_SECONDS` | base | `600`, soft + 60 | Celery's soft limit (raised inside the task) and hard limit (kills the worker child). Not enforced by the `solo` pool (Windows). |
| `JOBS_RETRY_BACKOFF_BASE_SECONDS`, `JOBS_RETRY_BACKOFF_MAX_SECONDS` | base | `5`, `120` | Exponential retry delay (with jitter) for retryable failures only (storage or sandbox momentarily unavailable). |
| `JOBS_VISIBILITY_TIMEOUT_SECONDS` | base | the larger of `1800` and hard limit + max backoff + `600` | Redis redelivers an unacknowledged message after this long. **Must exceed the hard time limit plus the max backoff**; start-up refuses otherwise. |
| `JOBS_REQUEUE_AFTER_SECONDS` | base | `300` | A `queued` job whose message was never sent, or sent longer ago than this and still unclaimed, is sent again by the sweeper. |
| `JOBS_PROGRESS_INTERVAL_MS` | base | `1000` | Minimum time between progress writes of one job (it doubles as the heartbeat). |
| `SANDBOX_WALL_SECONDS`, `SANDBOX_CPU_SECONDS` | base | `120`, `120` | Wall-clock timeout (the parent kills the whole process tree) and CPU-seconds `RLIMIT_CPU` of one parse. |
| `SANDBOX_MEMORY_MB` | base | `4096` | `RLIMIT_AS` of the parser child (256-262144). Raise it only with a reason: it is the memory-bomb defence. |
| `SANDBOX_MAX_INPUT_MB`, `SANDBOX_MAX_OUTPUT_MB` | base | `100`, `512` | Largest file the sandbox accepts, and largest Parquet it may produce (also `RLIMIT_FSIZE`). |
| `SANDBOX_MAX_ROWS`, `SANDBOX_MAX_COLUMNS` | base | `10000000`, `5000` | Table-size caps on what the child may report. |
| `SANDBOX_MAX_DECOMPRESSED_MB`, `SANDBOX_MAX_COMPRESSION_RATIO`, `SANDBOX_MAX_ARCHIVE_ENTRIES` | base | `1024`, `200`, `10000` | Zip / gzip bomb limits, checked from the archive's central directory before any parse. |
| `SANDBOX_PROCESS_HEADROOM` | base | `64` | `RLIMIT_NPROC` = the user's current tasks + this (`0` switches the cap off). See the notes below on shared uids. |
| `SANDBOX_TMP_ROOT` | base | system temp | Absolute directory under which each parse gets a private temp dir (`0700`: this separates *users*; see the isolation rows below). Directories a killed worker left behind are removed once untouched for longer than the Celery hard limit + 5 minutes (at least 30). |
| `SANDBOX_CHILD_UID`, `SANDBOX_CHILD_GID` | base, prod | unset | Run the parser child as this dedicated, unprivileged user (both or neither; not root). The worker must be root or hold `CAP_SETUID`, `CAP_SETGID` and `CAP_CHOWN` (`check --deploy`: `uadas_jobs.E006`). This is what keeps the child away from the worker's files and secrets. |
| `SANDBOX_ISOLATION_ACKNOWLEDGED` | base, prod | unset | `container`: the operator states that the worker runs in a container (or other boundary) that separates the child from the worker and from other jobs, in place of a dedicated uid. A root worker with neither is `uadas_jobs.E005`. |
| `SANDBOX_NETWORK_ISOLATION` | base, prod | unset (the child still *tries* a network namespace and reports the outcome) | `unshare`: refuse a parse whose child could not unshare a network namespace (`E007` if the host cannot); `container`: the worker has no route out (stated, not measured); `none-acknowledged`: accept the bypassable in-process socket guard alone. **Prod requires one of the three.** |
| `SANDBOX_REQUIRE_NETNS` | tests only | unset | `1` makes the network-isolation test *demand* a namespace instead of asserting the honest "not isolated" report; set it where the kernel is known to allow `unshare` (CI sets it only if `unshare --user --net true` works on the runner). |
| `JOBS_INTEGRATION` | tests only | unset | `1` (with a broker, a **PostgreSQL** `DATABASE_URL` and the `STORAGE_*` variables) also runs `test_jobs_integration.py`: a real `celery worker` process. |
| `ASSISTANT_PROVIDER` | base | unset (assistant off: `503`) | `anthropic`, `gemini`, `groq` or `openrouter` (`ollama` is refused on a server). Requires `ASSISTANT_API_KEY`; a key without a provider fails start-up. |
| `ASSISTANT_API_KEY`, `ASSISTANT_MODEL` | base | none / the provider's default | The deployment's LLM credential (never a request field, never stored or logged) and an optional model name. |
| `QUOTA_MAX_ROWS` | base, prod | unset (unlimited) | 1 or more. Rows an organization may hold across its datasets (a standing total: a deleted dataset gives its rows back). A `quotas.OrganizationQuota` row overrides it per organization. |
| `QUOTA_MAX_STORAGE_MB` | base, prod | unset (unlimited) | Megabytes of uploaded originals an organization may hold (standing total; reserved before the upload is spooled, released if it fails or the dataset is deleted). |
| `QUOTA_MAX_JOB_MINUTES` | base, prod | unset (unlimited) | Wall-clock minutes of background-job runs per organization per UTC calendar month. New jobs are refused once it is used up; a run that is already going is charged in full when it ends. |
| `QUOTA_MAX_LLM_TOKENS` | base, prod | unset (unlimited) | Assistant tokens (input plus output, as the provider reports them) per organization per UTC calendar month. A turn is refused up front once it is used up; the turn that crosses the limit is the last one allowed. |
| `QUOTA_UNLIMITED_ACKNOWLEDGED` | base, prod | unset | `true`: the operator states that an unset quota above means unlimited on purpose. **Prod requires all four limits, or this.** Over a limit the API answers `429` with the closed code `quota_exceeded`. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | base | none | Enable "sign in with GitHub". Both or neither: one alone fails start-up. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | base | none | Enable "sign in with Google". Both or neither. |

Mail goes to the console in `dev`, to an in-memory outbox in `test`, to SMTP in `prod`
(`EMAIL_BACKEND` is the pre-Django-7 spelling; moving to `MAILERS` is a recorded follow-up).
Email verification is `optional` in `dev`, `none` in `test` and always `mandatory` in `prod`
(not switchable by an environment variable).

## Health probe

`GET /api/health` is a liveness check and touches no database. `ALLOWED_HOSTS` still
applies to it: an orchestrator probe that sends the pod IP as `Host` gets a 400, so
configure the probe to send one of the allowed host names in its `Host` header.

The OpenAPI schema and docs routes (`/api/openapi.json`, `/api/docs`) exist only when
`DEBUG` is on; the contract is generated offline with `api.get_openapi_schema()`.

## Authentication

Sign-in is django-allauth in *headless* mode, **browser client only**: the SPA sends JSON and
the session lives in an `HttpOnly`, `SameSite=Lax` cookie (`Secure` in prod). There are no
bearer tokens; the `/api/auth/app/...` client is disabled. Email is the only login name.

- **CSRF.** Every state-changing request (ours and allauth's) needs the CSRF token. Call
  `GET /api/auth/browser/v1/config` first: it sets the `csrftoken` cookie (readable by the
  SPA, not `HttpOnly`); echo it in an `X-CSRFToken` header on every `POST`/`PATCH`/`DELETE`.
  Login rotates the token, so re-read the cookie after signing in.
- **Flows** (all under `/api/auth/browser/v1/`): `auth/signup`, `auth/login`, `auth/session`
  (`GET` state, `DELETE` logout), `auth/email/verify`, `auth/password/request`,
  `auth/password/reset`, `auth/provider/redirect` (form `POST`: start GitHub/Google).
  Full request/response shapes: allauth's headless specification.
- **Signup** creates the user, a personal organization (named after the email's local part)
  with the user as `owner`, and the audit rows, in one transaction. OAuth first logins do the same.
- **OAuth** redirect URIs to register with the provider:
  `https://<api-host>/api/auth/oauth/github/login/callback/` and `.../google/login/callback/`.
  allauth only follows a `callback_url` whose host is the API's own or listed in
  `DJANGO_ALLOWED_HOSTS` (host names only, no port): list the SPA's host in production, and in
  development send a relative `callback_url` through the dev proxy. Anything else (an open
  redirect) is bounced to the SPA's error page.
- **Rate limits** (login, failed login per IP and per account, signup, password reset) are
  counted in the shared cache, so prod needs `REDIS_URL`. A locked-out login answers `400`
  with error code `too_many_login_attempts`; the per-IP limits answer `429`.

## Endpoints

All require a session and the CSRF token on writes, except `/api/health`. The organization is
chosen by the **path** (`/api/organizations/{org_id}/...`), never by session state: a
non-member gets `404` (identical to a nonexistent organization), a member with too low a role
gets `403`, no session gets `401`.

| Method and path | Role | Purpose |
|---|---|---|
| `GET /api/health` | public | Liveness. |
| `GET /api/me` | any | The user and their memberships. |
| `GET /api/organizations` | any | Organizations I belong to. |
| `POST /api/organizations` | any | Create an organization; the caller becomes `owner` (`201`; `409` over the per-user cap). |
| `GET /api/organizations/{org_id}/members` | viewer+ | List members. |
| `PATCH /api/organizations/{org_id}/members/{membership_id}` | admin+ | Change a role (`{"role": ...}`); `403` above your own role or for a member not strictly below yours (peer admins, owners; only an owner may change those); `409` if it would leave no owner. |
| `DELETE /api/organizations/{org_id}/members/{membership_id}` | admin+, or yourself | Remove a member / leave; `409` for the last owner. |

Roles, lowest first: `viewer < editor < admin < owner` (one definition:
`uadas_api/accounts/permissions.py`, with the capability matrix). Later routers reuse
`require_membership(request, org_id, min_role)` from `uadas_api/accounts/security.py`.

### Resource routes (3.6)

Below `/api/organizations/{org_id}/projects/{project_id}` (every id is resolved through
`for_organization` *and* that project; a foreign id is a `404` identical to a missing one). Lists are
paged (`limit` ≤ 200, `offset`) and answer `{items, total, limit, offset}`; every 4xx is
`{"error": {"code", "message", "details"}}` with a code from a closed set
(`uadas_api/web/errors.py`).

| Route | Role | Purpose |
|---|---|---|
| `GET, POST /api/organizations/{org_id}/projects`; `GET, PATCH, DELETE .../{project_id}` | viewer / editor / admin to delete | Projects (`409` on a duplicate name or a non-empty delete). |
| `GET .../datasets`, `GET, DELETE .../datasets/{id}` | viewer / editor | Datasets; delete queues the stored objects (3.4 outbox). |
| `GET .../datasets/{id}/preview?offset&limit&sort&descending` | viewer | One formatted page, sorted server-side; page size ≤ 200. |
| `GET .../datasets/{id}/summary` | viewer | Types, null counts, min/max from the file footer. |
| `POST .../datasets/upload` (multipart `file`) | editor | Streamed under the size cap, admitted by extension and signature, then an ingest job: `202` + `job_id`. |
| `GET .../jobs`, `GET .../jobs/{id}`, `POST .../jobs/{id}/cancel`, `GET .../jobs/{id}/stage-result` | viewer / editor to cancel | Job status and progress for polling; a stage run's result sections. |
| `GET .../stages/{stage}/catalog`; `POST .../stages/{stage}/run` | viewer / editor | One router per `PipelineStage`: the stage's operations and JSON-Schema parameters from the core registry; a run validates against it and enqueues a job (`202`). Tags are the stage names. |
| `GET .../pipeline/nodes`, `.../pipeline/edges`, `.../recipes`, `.../recipes/{id}` | viewer | Lineage and recipes (read-only). |
| `GET, POST .../charts`, `GET, PATCH, DELETE .../charts/{id}`, `POST .../charts/{id}/render` | viewer / editor | Saved charts; render builds the figure from a bounded row sample (a bounded sync call). |
| `GET, POST .../dashboards`, `GET, PATCH, DELETE .../dashboards/{id}` | viewer / editor | Dashboards of chart tiles (tile chart ids resolved in the project). |
| `GET, POST .../reports`, `GET, DELETE .../reports/{id}`, `GET .../reports/{id}/download` | viewer / editor | A report request is a job; download is a presigned URL valid 60 s. |

Upload and report request accept an optional `Idempotency-Key` header (1-56 of `A-Za-z0-9._:-`): a retry
with the same key returns the same job and dataset/report; another body or project is a `409`. Preview and
summary share a `preview` budget (120/min). Heavy endpoints (upload, stage run, chart render, report) are throttled per user and organization
(`uadas_api/web/config.py`: 30/h, 120/h, 600/h, 30/h; a `429` envelope). JSON bodies are capped at
1 MiB and an upload at the sandbox input cap, enforced while the bytes stream in. Only the upload
route takes a file part (and its auth, role and throttle are decided *before* the body is read, by the
upload handler); a file part or a multipart body over 1 MiB sent to any other route is refused before
a temporary file is opened (`415` / `413`). **Deployment:** run the API under **WSGI** (gunicorn) behind
a proxy that caps the request body (for example nginx `client_max_body_size`): under ASGI Django
spools the *whole* body before any handler runs, so none of these caps can act first.

**OpenAPI 3.1** is generated offline and committed as [`openapi.json`](openapi.json); regenerate with
`cd apps/api && python -m uadas_api.web.openapi` (add `--check` to fail on drift, as CI does). The HTTP
route `/api/openapi.json` still exists only when `DEBUG` is on.

**Adding a route:** declare `operation_id`, `response=responses({...})`, call `member(request,
org_id, <role>)` first, resolve every id with `project_of` / `in_project`, regenerate `openapi.json`
-- the IDOR walk (`tests/test_web_idor.py`) then covers it automatically (and fails until it can).

## Data model

Full table, constraints and limitations: [plans/phase-3-2-data-model.md](../../plans/phase-3-2-data-model.md).

| App | Models |
|---|---|
| `accounts` | `User` (email login, case-insensitive unique), `Organization` (the tenant), `Membership` (role per organization), `AuditEvent` (append-only) |
| `workspaces` | `Project`, `DatasetRecord`, `ChartSpec`, `Dashboard` |
| `pipeline` | `PipelineNode`, `PipelineEdge` (the provenance DAG), `Recipe` |
| `exports` | `Report` |
| `storage` | `WorkspaceHead` (the compare-and-swap pointer of a project's saved workspace), `OrphanedObject` (durable queue of owed object deletions) |
| `jobs` | `Job` (state machine, progress sink, heartbeat, sanitized error, idempotency key) |
| `ai` | none yet |

Every model except `User`/`Organization`/`Membership` inherits `TenantOwnedModel`
(`uadas_api/tenancy.py`): a UUID primary key, a non-null `organization` foreign key
(`PROTECT`), and a write-time rule that every foreign key to another tenant model must stay
inside the same organization. Always list through `Model.objects.for_organization(org)`. The
rule is application-level only (no composite foreign keys exist in Django); raw SQL
bypasses it. `DatasetRecord.parent_dataset_id` is a plain UUID, not a foreign key, mirroring
the core's non-cascading lineage. Value sets (source formats, chart types, report formats,
graph kinds) are defined here and pinned to `uadas_core` by `tests/test_choices_parity.py`;
the models never import the core.

Also enforced: `organization` (and a membership's user/organization) cannot change once saved;
`bulk_create(update_conflicts=True)` is refused on tenant models; the guards apply to
`_base_manager`, so related-manager calls such as `project.datasets.add(row)` are covered;
`storage_key` must sit under `"<organization_id>/"` with plain segments only. **Reader
obligation:** JSON fields that carry ids (`ChartSpec.spec`, `Dashboard.layout`,
`PipelineNode.payload`, `Recipe.definition`, `Report.config`) are not validated; resolve any id
read from them through `for_organization`, never `objects.get(pk=...)`.

Adding a tenant model: subclass `TenantOwnedModel` with `class Meta(TenantOwnedModel.Meta)`
(a bare `class Meta:` drops the guarded base manager; the harness catches it), give it an index
or unique constraint that leads with `organization`, register a factory in `tests/factories.py`
(the isolation harness fails until you do), `makemigrations`, done.

## Object storage

Tenant data (uploaded originals, Parquet frames, workspace snapshots, exports) lives in one
S3-compatible bucket, keyed `"<organization_id>/..."`. Design and limits:
[plans/phase-3-4-storage.md](../../plans/phase-3-4-storage.md).

- **One way in.** Application code uses `uadas_api.storage.store.get_store(organization)` and
  nothing else. The returned `TenantObjectStore` re-validates every key against the organization
  before any request (a key of organization A can never be read, written, deleted, listed, copied
  or presigned through B's handle), caps sizes, allow-lists content types, records and verifies a
  SHA-256, refuses to overwrite by default, and issues short-lived presigned URLs (at most 15
  minutes). `tests/test_storage_boundary.py` fails if another module imports boto3 /
  django-storages or a backend module. Keys come from `uadas_api.storage.keys` (fixed layouts built
  from identifiers; a user's file name is metadata, never a key segment).
- **Workspaces keep the Phase 2.7 guarantee.** `uadas_api.storage.workspace.StorageBackedPersistence`
  loads and saves a project's workspace through the core's unchanged `PersistenceService`: new
  immutable objects under unique keys, one conditional update of the `WorkspaceHead` row as the
  swap (also the optimistic-concurrency check), garbage collected only afterwards.
  `load(dataset_ids=[...])` fetches only the requested frames. A caller passes the version it
  loaded as `expected_version` to `save`; a stale one raises `ConcurrentSaveError`.
- **Rows own objects.** Deleting a `DatasetRecord`, `Report` or `WorkspaceHead` queues its objects in
  the same transaction and deletes them after commit; failures stay queued. Run
  `python manage.py purge_orphaned_objects [--min-age SECONDS]` (cron / worker) to retry, and
  `python manage.py reconcile_storage <organization-id>` for a read-only rows-versus-objects report.
- **Configuration is fail-closed.** `base` has no default bucket, endpoint or credential; `dev` points
  at the docker-compose MinIO (`docker compose -f docker-compose.dev.yml up -d`, bucket
  `uadas-uploads`); `test` uses an in-memory fake; `prod` refuses to start without real values.
  The bucket must not be public (the app never sends ACLs; use the provider's block-public-access
  and a bucket policy).

## Background jobs and the parser sandbox

Every long operation is a `Job` row (`uadas_api/jobs/`); Celery over Redis only carries its id.
Design, threat model and limits: [plans/phase-3-5-jobs.md](../../plans/phase-3-5-jobs.md).

- **Create / cancel / read** through `uadas_api.jobs.services` (`create_job` is authorized,
  idempotent per `(organization, kind, idempotency_key)` and enqueues after commit; `request_cancel`;
  `get_job`). Call sites never import Celery: `uadas_api.jobs.queue.enqueue` is the only door.
  The ingest job has a service, no endpoint yet: `uadas_api.ingest.service.request_ingest(...)` takes
  an already-stored original and its declared file name.
- **Run a worker.** `DJANGO_SETTINGS_MODULE` must be set (a worker, like `wsgi`, does not default to
  dev): `celery -A uadas_api.jobs.celery_app worker --queues uadas-jobs` (add `--pool=solo` on
  Windows, where the prefork pool and Celery's time limits do not exist) and **one** `celery -A
  uadas_api.jobs.celery_app beat` (it schedules `uadas.jobs.sweep` every minute), or run
  `python manage.py sweep_jobs` from cron. The sweeper requeues or fails jobs whose worker died and
  re-sends queued jobs whose message was lost; it is idempotent.
- **Local dev:** `docker compose -f docker-compose.dev.yml up -d` (Redis on `localhost:6379`), then
  `python manage.py runserver` plus the worker above. Without a worker, set `JOBS_EAGER=1`.
- **Production needs Linux.** The parser sandbox applies `setrlimit` memory/CPU/file-size/descriptor/
  process limits in a child (`python -I -m uadas_api.sandbox.child`), which exist only on POSIX and are
  only meaningful on Linux. `prod` settings **refuse to start** where they cannot be enforced; on
  Windows/macOS the sandbox still runs (timeout, size caps, socket block, process-tree kill) and
  reports `limits_enforced=False`. Install the packages into the interpreter's own site-packages (a
  virtualenv; **not** `pip install --user`, which `python -I` ignores -- `check --deploy` fails with
  `uadas_jobs.E004` if the child cannot start).
- **What separates the child from the worker (read this before deploying).** A child that runs as the
  worker's own user is *not* separated from it: `0700` directories and a stripped environment mean
  nothing between processes of one uid. What the code does: the worker makes itself non-dumpable (so the
  child cannot read `/proc/<worker>/environ`), the child is killed with its parent and by its own
  alarm, and a directory a SIGKILLed worker left behind is reaped. What it cannot do alone: stop a
  same-uid child reading the worker's files and *other jobs'* inputs. Production therefore requires one
  of **`SANDBOX_CHILD_UID`/`GID`** (a dedicated user; the worker runs as root or holds
  `CAP_SETUID/SETGID/CHOWN`) **or `SANDBOX_ISOLATION_ACKNOWLEDGED=container`** (the worker is in a
  container that does the separating); concurrent children of one dedicated uid can still read each
  other's directories, so give each worker process its own uid or container if that matters.
- **The network.** The child tries to unshare a network namespace (`CLONE_NEWNET`, plus `CLONE_NEWUSER`
  when unprivileged) and reports `network_isolated`; Docker's default seccomp profile and Ubuntu 24.04's
  AppArmor restriction refuse it. The in-process socket guard is bypassable (the raw `_socket` class is
  reachable from Python) and is **not** counted. Production requires an explicit
  `SANDBOX_NETWORK_ISOLATION` (`unshare`, `container` or `none-acknowledged`); the real isolation is a
  worker container with no route out beyond Redis, PostgreSQL and the object store. `setsid()`
  grandchildren escape a process-group kill; the bounds are `RLIMIT_NPROC` and the cgroup `pids_limit`.
  A compose sketch for a network-less sandbox service is in `docker-compose.dev.yml`.
- **System libraries for the parser child.** The readers import OpenCV, so the worker image needs
  `libgl1 libglib2.0-0 libxcb1` (Debian/Ubuntu; Tesseract is needed only to OCR images). A bare
  `python:3.13-slim` lacks them and every parse fails as `parse_error` (`ImportError: libxcb.so.1`).
- **Readers never run in a web or worker process.** Only `uadas_api.sandbox.child` imports
  `uadas_core.readers` (contract `readers-only-in-the-sandbox-child` in `.importlinter`, which sees direct
  imports only; fresh-interpreter tests in `test_sandbox_boundary.py` cover the parent side and the
  composition root `core_bridge`). Admission (extension and content signature, a zip size budget that
  reads *declared* sizes and is a heuristic -- the child's rlimits are the bound; `.gz`/`.gzip` are not
  admitted) happens before a child exists; failures are a closed set of codes with fixed sentences, never
  an exception's text.
- **Several workers are safe.** Every worker-side write is fenced by the attempt number the worker was
  given, a heartbeat thread keeps a long silent run alive, a retry's backoff is honoured by the sweeper,
  and a job the sweeper fails or cancels (or a user cancels while queued) cleans up its stored objects.

## Streaming (SSE, 3.7)

Two routes answer `text/event-stream` (full design: `plans/phase-3-7-streaming.md`):

* `GET /api/organizations/{org}/projects/{project}/jobs/{job}/events` -- a job's `status` / `progress`
  as `job` events with a monotonic `id:`, a `retry:` hint and `: keep-alive` comments; viewers and above.
  It closes after the terminal state (reconnect with `Last-Event-ID` and a terminal id gets `204`), after
  15 minutes, or when the viewer is removed from the organization. Events never carry data rows.
* `POST /api/organizations/{org}/assistant/messages` -- one assistant turn (`message`, `tool_call`
  *proposals*, `done`, `error`); editors and above, CSRF, 60 turns/hour. Nothing is executed: the client
  runs an accepted proposal through the stage endpoints. Providers return whole turns, so this is not
  token-level streaming (deferred).

Run it under **ASGI** (`uvicorn uadas_api.asgi:application`); under WSGI a stream pins a worker.
Behind a proxy, do not buffer or compress `text/event-stream` (`X-Accel-Buffering: no` is sent) and keep
the read timeout above 15 s. Caps: 5 job streams per user and 50 per organization, 2 assistant turns per
user and 10 per organization (`429`); a client that leaves releases its slot immediately.

## Quotas (3.8)

Four per-organization limits (`QUOTA_*` above; a `quotas.OrganizationQuota` row overrides one for one
organization). Over a limit the API answers **`429` with the closed code `quota_exceeded`** (the throttle's
`429` stays `rate_limited`).

| Resource | Window | Checked | Charged |
| --- | --- | --- | --- |
| stored bytes | standing | reserved by the upload handler before the body is spooled (strict, one conditional `UPDATE`) | the declared body length, kept under the dataset's ledger key; released if the request fails, the ingest fails, or the dataset is deleted |
| rows | standing | a new upload is refused once used up | by the ingest job when the dataset is committed (can overshoot by one file); released when the dataset is deleted |
| job time | calendar month (UTC) | a new job is refused once used up (a replay of an existing job is not) | seconds per attempt, when the attempt ends and wins the attempt fence; once per attempt |
| LLM tokens | calendar month (UTC) | an assistant turn is refused once used up | what the provider reported (an estimate if it reports none), by the provider thread when the call ends |

Every charge has a unique ledger key per organization, so a retry cannot bill twice. Known limits: charge-after
resources (job time, tokens, rows) overshoot by what was in flight when the limit was crossed, never by more; a
process killed mid-upload leaves its byte hold charged until released by hand (no reconcile job yet); an
idempotent replay of an upload needs room for its own hold; limits are not exposed by an endpoint.

## Test

```bash
python -m pytest apps/api/tests -q      # from the repo root
```

The job queue and the sandbox are hermetic by default: Celery runs eagerly against an in-memory broker
and the sandbox children are real subprocesses. The **Linux-only** guarantees (memory, CPU, file-size,
descriptor and fork limits, the `/proc` hardening, the kill-with-parent and alarm tests, the network
namespace) skip on Windows with a stated reason and run in CI; `test_sandbox_ci_guard.py` fails a CI run
that could not run them (it reads the skip condition out of the very marks the tests use, in
`tests/sandbox_support.py`). The dedicated-uid tests need a root worker and skip on the unprivileged CI
runner (budgeted in `ci.yml`); run them in a root Linux container. `test_jobs_integration.py` starts a
real `celery worker` against real Redis, PostgreSQL and MinIO when `JOBS_INTEGRATION=1`
`CELERY_BROKER_URL=redis://localhost:6379/5 DATABASE_URL=postgres://...` and the `STORAGE_*` variables
are exported (`test_jobs_ci_guard.py` fails CI if they are lost). To run the sandbox tests on Linux
from Windows, run the suite inside a `python:3.13` container as a non-root user (see the plan).

`test_web_schemathesis.py` fuzzes the committed OpenAPI schema in process (derandomized, no network);
it needs the `dev` extra (`schemathesis`).

The pytest settings (`DJANGO_SETTINGS_MODULE = uadas_api.settings.test`) live in
`apps/api/pyproject.toml`, so the core suite (`python -m pytest tests -q`) is unaffected.
CI's `api-test` job runs this suite against a Postgres 17 service container by setting
`DATABASE_URL`; locally it falls back to in-memory SQLite. The storage tests run against an
in-memory fake; to run them against a real store too, start the compose MinIO and export
`STORAGE_INTEGRATION=1 STORAGE_ENDPOINT_URL=http://localhost:9000 STORAGE_BUCKET=uadas-uploads
STORAGE_ACCESS_KEY_ID=... STORAGE_SECRET_ACCESS_KEY=...` (the root pair from
`docker-compose.dev.yml`; CI starts its own MinIO). Each test uses a random organization id and
deletes only its own objects.

Lint-imports needs the API on the path when run without the editable install:
`PYTHONPATH=apps/api lint-imports`.
