# Project status and handover — 2026-10-23

Universal AI Data Analytics & Visualization Studio is moving from a PySide6 desktop app to a web app
(plan: [plans/web-transition-glass-box-studio.md](../plans/web-transition-glass-box-studio.md), phases 0–6).
This file is the one-page truth about **what is done, what is not, and exactly how to finish it**. Verify
every number against `git log` and `gh run list` before trusting it; it was true on the date above.

## 1. Where the code lives

| Branch | State |
|---|---|
| `main` | Phase 0 and Phase 1 merged (PRs #2, #3, #4). Still contains the desktop app. |
| `phase-2/retire-desktop-ui` | Phase 2 complete, tip `8253dec`, CI green. **No PR opened yet.** |
| `phase-3/django-backend` | Stacked on the Phase 2 branch. Tip `a538dc9` (pushed, CI green on `test`, `lint`, `api-test`). |

Every commit is `git commit -s` (DCO is enforcing, but the `dco` job only runs on pull requests).
Never touch or commit `config/config.yaml`. Untracked `main.py` and `src/` at the repo root are old July
Qt files that OneDrive resurrected — never stage them; delete them.

## 2. What is DONE

**Phases 0–1** (on `main`): licence AGPL-3.0, CI, DCO, packaging; the Qt-free core extracted to `uadas_core/`.

**Phase 2** (branch above): desktop UI deleted (`src/`, `main.py`, Qt tests/deps/markers); facts mined into
`assets/ui-contract/` (layout, constants, copy, rules) guarded by `tests/assets/`; stranded modules lifted
(`command_stack`, theme, a11y, help, data_table, actions); `uadas_core/models/` extracted; 3 import-linter
contracts; CI is one Linux workflow; save atomicity bug D4 fixed (stage frames → promote → swap DB → GC after);
docs and `.claude/` agents/skills synced. Core suite 970 passed at last run.

**Phase 3** (`apps/api`, Django 6 + Django Ninja, package `uadas_api`):

| Step | Commit(s) | What it gave |
|---|---|---|
| 3.0 readiness | `3cf56f0` | Baseline, rulings: [plans/phase-3-readiness.md](../plans/phase-3-readiness.md) |
| 3.1 skeleton | `e6db59a` | split settings (base/dev/test/prod, strict env parsing, prod fails closed), `/api/health`, `api-test` CI job on Postgres 17 |
| 3.2 data model | `ccb3f95` | 11 tenant-scoped models, `TenantOwnedModel` guard (save/bulk/update/upsert/base-manager), append-only `AuditEvent`, discovery-based isolation harness |
| 3.3 auth | `9538816` | allauth headless (session cookie + CSRF), email verification, GitHub/Google only when env creds exist, roles viewer<editor<admin<owner, last-owner lock, personal org at signup |
| session seam | `eff9294` | `DependencyContainer(parent=)`, `bootstrap_process` / `build_session`, server mode (no plugins, no YAML, no log files, no root logger), process-mode latch, `core_bridge` |
| 3.4 storage | `2fa1e39`, `096eaa2` | `TenantObjectStore` (only door to the bucket), D4 over S3 (`StorageBackedPersistence`: never-reused keys + version-column CAS + outbox), SSE required in prod. MinIO images vanished from Docker Hub → Chainguard digest-pinned |
| 3.5 jobs + sandbox | `43df185` | Celery/Redis facade, fenced `Job` model, heartbeat, sweepers; parser sandbox child (rlimits, netns, PDEATHSIG, verified reply, closed error codes); ingest job; contract `readers-only-in-the-sandbox-child` |
| 3.6 API surface | `e842cb7`, `e84f204`, `a538dc9` | 58 operations under `/api/organizations/{org_id}/...`, upload, preview paging, stage routers from `PipelineStage`, catalogs from the core registries, committed `apps/api/openapi.json` + drift check, Schemathesis smoke, IDOR walk |
| 3.7 streaming | `a538dc9` | SSE job-progress stream, assistant stream (whole message parts, PROPOSED tool calls only), stream caps |

Each step got independent security and Django reviews; every finding was fixed with a test (plan docs
`plans/phase-3-*.md` hold the details and known limits). Last verified counts: core **970**; api **1908**
(SQLite) / **1913** (Postgres) / **1997** (Postgres + MinIO + Redis). CI floors/skip budget live in `.github/workflows/ci.yml`.

## 3. What is LEFT — in the order to do it

### A. Finish 3.7 (in progress, uncommitted when this was written)
The security review of 3.7 reproduced four defects. Uncommitted partial work exists in
`uadas_core/ai/llm_provider.py` + `tests/ai/test_llm_provider.py` (3 tests were failing — do not commit
until green). Remaining, test-first:
1. **Cap lease leaks if the client disconnects while `_open` runs** (`web/job_events.py` ~158, `web/assistant.py` ~241): acquire the lease in the async body inside `try/finally`; test "disconnect before the body starts, next open succeeds".
2. **Abandoned provider threads escape the assistant cap** (`web/assistant.py` ~226): pass a provider timeout and `max_retries=0` (`uadas_core/ai/llm_provider.py`, then run the core suite), add a process-wide semaphore for in-flight provider calls, release the lease only when the thread ends, key the throttle per **user** as well as per org.
3. **Cap counter TTL never refreshes** (`web/streams.py` ~39): refresh on incr or use per-lease keys.
4. **Emoji-heavy parts exceed the 64 KB event cap** (`web/assistant.py` ~190): split by encoded size.
5. Add `private` to `Cache-Control`; make the connection-leak test behave (skip locally with a reason, run in CI).
Deferred and documented in [plans/phase-3-7-streaming.md](../plans/phase-3-7-streaming.md): session revalidation mid-stream (<=900 s), slow-reader duration, token-level streaming (providers cannot stream), per-user provider keys, Redis nudge.

### B. The rest of 3.8 (security)
- **Per-tenant quotas**: rows, storage bytes, job minutes, LLM tokens. Model a `Quota`/usage counter per organization, check in upload, job enqueue and assistant; return a closed `quota_exceeded` code; test with a positive twin.
- **Raw-SQL `execute_query` capability**: only behind an explicit capability flag, against a **read-only DB role**, with statement timeouts; add a directed manual security review (CI bandit skips B608, so SQL construction has no automated gate).
- **Stateful Schemathesis** (currently a GET smoke): authenticated, org-scoped, small and non-flaky.
- Already done from 3.8: plugin loader off in server mode, secrets env-only, parser sandbox, size caps.

### C. Phase 3 verification line (not yet satisfied)
The plan requires: `docker compose up` from a clean clone gives a working stack. Today only `docker-compose.dev.yml` (Postgres, Redis, MinIO) exists. To do:
1. **Split `requirements.txt`** into runtime and dev (the root distribution currently drags dev tools into any server image); keep `pandas<3`.
2. Write `apps/api/Dockerfile` (python:3.13-slim; native libs `libgl1 libglib2.0-0 libxcb1`; run as a non-root uid), plus a `docker-compose.yml` with `api`, `worker`, `postgres`, `redis`, `minio`, and a sandbox worker with `network_mode: none` (a commented sketch is in `docker-compose.dev.yml`).
3. Prod needs: `SANDBOX_CHILD_UID` or `SANDBOX_ISOLATION_ACKNOWLEDGED`, `SANDBOX_NETWORK_ISOLATION`, `STORAGE_*` with `STORAGE_SSE`, `REDIS_URL`, `EMAIL_*`, `FRONTEND_BASE_URL` (https), `CELERY_*` — see `tests/test_entrypoints.py::VALID_PROD_ENV` and the README env table. Run behind WSGI or a proxy with a body cap (ASGI spools the whole body first).
4. Prove it: fresh clone, `docker compose up`, create a user, upload a CSV, watch the job, preview the dataset, upload a deliberately malformed PDF and see it fail safe.

### D. Deferred items recorded in the plan docs
Organization offboarding/purge (a sole owner cannot be deleted today), invitations, MFA, API keys, transfer/delete-organization endpoints, recipe create-from-DAG, per-operation expertise hints, figures in reports, the preview footer/hash cache, optimistic version checks on PATCH, UUIDv7 keys, DB-level tenancy enforcement (row-level security), and two INFO-level log leaks (`analysis/t_test.py`, `cleaning/missing_values.py`).

### E. Pull requests and housekeeping
1. Open the **Phase 2 PR** (`phase-2/retire-desktop-ui` → `main`), then the **Phase 3 PR** against it or `main`; merging is a human decision. DCO will then run — every commit is already signed off.
2. Deferred deletions: `git rm -r .claude/skills/pyside6-development` (and its mention in `docs/RESOURCE_ORCHESTRATION.md`), the stale agent worktrees `.claude/worktrees/agent-*` and branches `worktree-agent-*`, the empty `resources/styles/`, and the stray `main.py` + `src/`.
3. 42 mypy errors sit in 7 `uadas_core` packages outside the CI mypy list (see `docs/MYPY_DEBT.md`).

### F. Phase 4 — web frontend (`apps/web` scaffold exists: Vite + React + TS)
Follow plan lines ~290–301: **4.1** generate the TS client from `apps/api/openapi.json` (`openapi-typescript` + `openapi-fetch`); **4.2** design tokens → CSS variables, Tailwind + shadcn/ui, contrast test from the ported manifest; **4.3** the workbench shell with the same 10 stages (source of truth: `assets/ui-contract/`, `uadas_core` `PipelineStage`); **4.4** Plotly.js fed by the chart `render` endpoint; **4.5** TanStack Table + Virtual with the server-side paging the API already has; **4.6** TanStack Query/Router + Zustand, `cmdk` palette from the action registry; **4.7** render `docs/manual/` as help with the anchor system; **4.8** SSE client for job progress and the assistant stream. Done when: Playwright E2E of UPLOAD → … → REPORT, axe-core clean, Lighthouse ≥ 90, the client compiles against the committed schema.

### G. Phase 5 (optional differentiators) and Phase 6 (ship)
Phase 5 features F1–F10 (provenance graph, replayable recipes, time-travel, expertise-adaptive UI, assumption sentinel, AI-proposes-never-mutates, living reports, semantic typing, graph-anchored collaboration, in-browser privacy mode) — each needs written acceptance criteria first; F10 is the riskiest, prototype before committing. Phase 6: Docker self-host, hosted instance, Sentry, OpenTelemetry, security policy, CONTRIBUTING.

## 4. Rules that must keep holding
- No Qt anywhere; `uadas_core` never imports Django or `uadas_api` (import-linter, 6 contracts: `PYTHONPATH=apps/api lint-imports`).
- Never import a reader/parsing library in web or worker code — parsing happens only in `python -I -m uadas_api.sandbox.child`.
- Every route: `member(request, org_id, role)` first, resolve ids with `for_organization` + the path's project, give it an `operation_id`, regenerate `openapi.json` (`cd apps/api && python -m uadas_api.web.openapi`); the IDOR walk covers it automatically.
- Object storage only through `uadas_api.storage.store.get_store()`; never write to an existing key; delete only after the swap commits.
- Never log `%r` of data or settings; SSE events carry no data rows; never hold a DB connection across a sleep.
- Cleaning operations never mutate a `Dataset`; closing a dataset does not cascade.
- A hardening/guard test needs a positive twin, and a mutation check where the harness allows it.

## 5. Operating notes (these cost real time)
- **Docker Desktop stops after every reboot.** Start it (`Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"`), then `docker compose -f docker-compose.dev.yml up -d`. Never run two pytest sessions against the same Postgres at once (they collide on `test_uadas`).
- MinIO integration env: `CI=true STORAGE_INTEGRATION=1 STORAGE_ENDPOINT_URL=http://localhost:9000 STORAGE_BUCKET=uadas-uploads STORAGE_ACCESS_KEY_ID=minioadmin STORAGE_SECRET_ACCESS_KEY=minioadmin DATABASE_URL=postgres://uadas:uadas@localhost:5432/uadas`. Two guard tests (`test_sandbox_ci_guard`, `test_jobs_ci_guard`) are expected to fail on Windows with `CI=true`; they pass on the Linux runner.
- The commit gate (`.claude/hooks/pre-commit-check.ps1`) runs the full core suite (~4 min) on any staged `.py`. It guards `tests/` + bandit only; `apps/api` is gated in CI.
- GateGuard blocks the first Edit/Write per file and the first Bash: state the facts, retry the same call.
- The formatter strips an import added before its use — add import and use in one edit.
- Local mypy and CI mypy see different pyarrow stubs: use `# type: ignore[code, unused-ignore]` for env-dependent ignores.
- Linux-only guarantees (rlimits, network namespace, PDEATHSIG) are proven only in CI or a Linux container, not on Windows.
- Observation log: `~/.claude/skill-observations/` (entries 0028–0040 cover the traps above).
