# Phase 3 — Readiness (sub-step 3.0)

**Date:** 2026-10-04 · **Branch:** `phase-3/django-backend`, cut from `phase-2/retire-desktop-ui` @ `8253dec`
(the Phase 2 PR to `main` is still open, so this branch is stacked on it).
**Scope:** Phase 3 of [web-transition-glass-box-studio.md](web-transition-glass-box-studio.md) — Django 6 +
Django Ninja backend. This file is the readiness gate only; each sub-step gets its own plan just before it runs.

## Verified facts (checked against the tree or the live docs, 2026-10-04)

| Claim | Result |
|---|---|
| Phase 3 deps resolve with `requirements.txt` on Python 3.13 | Yes: django 6.1.1, django-ninja 1.7.1, django-allauth 65.19.7, celery 5.6.3, schemathesis 4.29.1, psycopg 3.3.6; `pandas==2.3.3` (cap holds) |
| Distribution name | `universal-ai-data-analytics-studio` (pyproject.toml:13), **not** `uadas-core` as the plan says |
| `PROJECT_ROOT` | `Path(__file__).resolve().parents[2]` (constants.py:37) — breaks in a non-editable container install |
| Plugins in server mode | No server mode exists; `bootstrap()` always calls `load_plugins()` (bootstrap.py:248) |
| `DependencyContainer` scope/parent | None; the `(session, type)` seam is documented but not built (dependency_container.py:66-82) |
| `django.tasks` production backend | **Django 6.1 ships only `ImmediateBackend` and `DummyBackend`** (dev/test). A durable queue needs a third-party backend, so "`django.tasks` with Celery or RQ behind it" needs a concrete choice in 3.5 |
| Docker daemon | **Not running** on this machine; Postgres/MinIO/Redis cannot start until Docker Desktop is up |

## Rulings (from an `architect` review; claims spot-checked above)

1. **Packaging.** Separate `apps/api/pyproject.toml`, package `uadas_api` (`settings/{base,dev,prod}.py` plus apps
   `accounts`, `workspaces`, `pipeline`, `ai`, `exports`). Depends on the root distribution; install with
   `pip install -e . -e apps/api`. No uv workspace until `requirements.txt` is split into runtime and dev
   (today the root distribution's dependencies include dev tools, which would land in the server image).
   - `.importlinter`: add `uadas_api` to `root_packages`; forbid `uadas_core` → `uadas_api`; forbid `uadas_api` →
     `uadas_core.plugins` and `uadas_core.jobs`; treat underscore modules as private.
   - CI: `apps/api` joins ruff/black/isort; own mypy step with django-stubs; the lint job needs
     `PYTHONPATH=apps/api` or `lint-imports` cannot find `uadas_api`.
2. **Per-tenant scoping.** Unsafe shared state: the eight stateful services in `bootstrap.py` (ApplicationState,
   SettingsService — rewrites the shared `config.yaml` —, ProjectService, WorkspaceService,
   AnalysisOrchestratorService, GuidanceService, ReportService, DatabaseConnectionService, PluginManager) plus
   module globals (`reader_registry._PLUGIN_READERS`, `jobs/__init__.py:51`, `logger._configured`,
   `PROJECT_ROOT`). Smallest seam, in `uadas_core`: `DependencyContainer(parent=...)` and split `bootstrap()` into
   `bootstrap_process(server_mode)` and `build_session(process)`. In `apps/api`: a per-request dependency that
   builds the session from the database plus storage, tenant-checked. Nothing in memory is shared across requests.
3. **Order.** 3.1 skeleton + contracts + CI → server-mode part of 3.8 (plugins hard-off, env-only secrets) → 3.2
   models (tenant-isolation test before the second model) → 3.3 auth → core session seam → 3.4 storage → 3.5 jobs +
   parser sandbox → 3.6 API → 3.7 SSE → rest of 3.8 (quotas, SQL capability, Schemathesis).
   **Before any upload endpoint exists:** auth enforced; tenant-scoped storage keys; size caps; extension and
   magic-byte allowlist checked against `_BUILTIN_READERS`; readers only in the sandboxed worker; plugins cannot
   load; the malformed-PDF test passes.
4. **Tests.** `apps/api/tests` with `DJANGO_SETTINGS_MODULE` in `apps/api`'s own pytest config (a global env var
   would make pytest-django initialise Django during the core run). Postgres 17 as a CI service container in a new
   `api-test` job; SQLite via `DATABASE_URL` locally until Docker runs. Its own collected-test floor. Frozen: `tests/`,
   `testpaths`, the 860 floor, the commit gate's `pytest tests -q` (the api suite is a separate step).

## Open assumptions to settle before the step that needs them

- 3.1: how `uadas_core` is installed in the image without dev tools (split `requirements.txt`).
- 3.5: which durable `django.tasks` backend; progress crosses processes, so it needs a sink (DB or Redis) feeding SSE.
- Core session seam: `PersistenceService` writes to a local filesystem and is not yet compatible with django-storages;
  `assistant_service` → `workspace_service` import-linter ignore (`.importlinter`:86) still needs a Protocol.
- Loading Parquet per request is expensive; frames need lazy loading.

## Baseline

Core suite on `8253dec`: **874 passed, 0 failed, 0 skipped** (`python -m pytest tests -q`, exit 0, 266 s).
That is the 868 from Phase 2.5 plus the 6 persistence-atomicity tests from 2.7. Phase 3 must not change it.
