# uadas-api

The Django 6 + Django Ninja backend for the Universal AI Data Analytics Studio web app
(Phase 3 of [the web-transition plan](../../plans/web-transition-glass-box-studio.md)).
It is a separate distribution from the framework-free core (`uadas_core`, repo root) and
depends on it; the core never imports it (enforced by `.importlinter`).

**Status: sub-step 3.2, the data model and tenancy.** Five Django apps (`accounts`,
`workspaces`, `pipeline`, `ai`, `exports`), split settings, one endpoint, `GET /api/health`
(`{"status": "ok"}`, liveness only, no database access), and the models described under
[Data model](#data-model). No authentication flow, storage, background tasks or API
endpoints over the models yet (3.3 onwards). `AUTH_USER_MODEL = "accounts.User"`.

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

## Health probe

`GET /api/health` is a liveness check and touches no database. `ALLOWED_HOSTS` still
applies to it: an orchestrator probe that sends the pod IP as `Host` gets a 400, so
configure the probe to send one of the allowed host names in its `Host` header.

The OpenAPI schema and docs routes (`/api/openapi.json`, `/api/docs`) exist only when
`DEBUG` is on; the contract is generated offline with `api.get_openapi_schema()`.

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
