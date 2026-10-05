# uadas-api

The Django 6 + Django Ninja backend for the Universal AI Data Analytics Studio web app
(Phase 3 of [the web-transition plan](../../plans/web-transition-glass-box-studio.md)).
It is a separate distribution from the framework-free core (`uadas_core`, repo root) and
depends on it; the core never imports it (enforced by `.importlinter`).

**Status: sub-step 3.3, authentication and per-organization roles.** Five Django apps
(`accounts`, `workspaces`, `pipeline`, `ai`, `exports`), split settings, the models described
under [Data model](#data-model), sign-in through django-allauth (headless, session cookies),
and the account endpoints listed under [Authentication](#authentication) and
[Endpoints](#endpoints). `GET /api/health` stays public and database-free. No storage,
background tasks or API endpoints over the *data* models yet (3.4 onwards).
`AUTH_USER_MODEL = "accounts.User"`. Decisions and limits: [plans/phase-3-3-auth.md](../../plans/phase-3-3-auth.md).

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
| `DEFAULT_FROM_EMAIL` | prod | none | Sender of verification / reset mail, e.g. `UADAS <no-reply@example.com>`. **Required in prod.** |
| `EMAIL_HOST` | prod | none | SMTP relay host. **Required in prod.** |
| `EMAIL_PORT` | prod | `587` | SMTP port. |
| `EMAIL_USE_TLS` | prod | `true` | STARTTLS to the relay. |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | prod | none | SMTP credentials; unset means an unauthenticated relay. Environment only, never committed. |
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

## Data model

Full table, constraints and limitations: [plans/phase-3-2-data-model.md](../../plans/phase-3-2-data-model.md).

| App | Models |
|---|---|
| `accounts` | `User` (email login, case-insensitive unique), `Organization` (the tenant), `Membership` (role per organization), `AuditEvent` (append-only) |
| `workspaces` | `Project`, `DatasetRecord`, `ChartSpec`, `Dashboard` |
| `pipeline` | `PipelineNode`, `PipelineEdge` (the provenance DAG), `Recipe` |
| `exports` | `Report` |
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

## Test

```bash
python -m pytest apps/api/tests -q      # from the repo root
```

The pytest settings (`DJANGO_SETTINGS_MODULE = uadas_api.settings.test`) live in
`apps/api/pyproject.toml`, so the core suite (`python -m pytest tests -q`) is unaffected.
CI's `api-test` job runs this suite against a Postgres 17 service container by setting
`DATABASE_URL`; locally it falls back to in-memory SQLite.

Lint-imports needs the API on the path when run without the editable install:
`PYTHONPATH=apps/api lint-imports`.
