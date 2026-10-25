# Two-week ship plan — 2026-10-25 → 2026-11-07

Supersedes the phase-by-phase sequencing in `docs/PROJECT_STATUS_2026-10-23.md` §3 and
`plans/web-transition-glass-box-studio.md` Phases 3.8–6. Those docs stay as history; **write no new plan docs**.

## Ground truth (verified 2026-10-25)
- Backend is done enough: 58 API operations, auth, tenancy, storage, jobs, sandbox, SSE, OpenAPI contract. 970 core / ~1900 api tests.
- **Frontend is an empty Vite scaffold** (`apps/web/src`: App.tsx, pipeline.ts, tokens.css; no client, router, auth, or screens).
- Nothing deploys: no Dockerfile, no prod compose. Phase 2 and 3 are unmerged stacked branches.
- The delay is not backend work. It is hardening, docs and process around a backend nobody can open in a browser.

## Definition of "working website" (the only scope)
A public HTTPS URL where a stranger can: sign up + verify email → create a project → upload CSV/Excel →
preview (paged) → clean → profile/analyze → chart → export an HTML/PDF report. Single instance, one region.

## CUT (not in the 2 weeks)
| Cut | Why |
|---|---|
| Phase 3.8 quotas, raw-SQL `execute_query`, stateful Schemathesis | Needed for hostile multi-tenant scale, not launch. Add a hard upload size cap + per-user rate limit instead (already built). |
| Phase 5 (F1–F10), Phase 4.7 manual-as-help, cmdk palette, i18n, Lighthouse ≥ 90 gate | Differentiators and polish. Post-launch. |
| SSE client (4.8) | Poll the job endpoint every 1–2 s. Backend SSE stays unused. |
| Assistant chat | Ship **flag off**. Fix the 3.7 defects only if enabled later. |
| 10 bespoke stage screens | Build **one generic stage-runner UI** driven by `uadas_api/stages/catalog.py` (form from schema, run → job → result). 5 nav entries: Data, Clean, Analyze, Visualize, Report. Forecast is stretch. |
| Deferred list D (offboarding, invitations, MFA, API keys, RLS, UUIDv7) and mypy debt | Post-launch backlog. |
| Per-step playbook / derisking / resource-plan docs and per-step dual reviews | ~35 docs in `plans/`. Replace with one security review at Day 12. |
| Stacked phase branches, 4-minute full-suite commit gate | Trunk-based: merge to `main` now; run the full suite on push/CI only. |

## Schedule
**D1 (Sun 10-25) — unblock.** Commit 3.7 WIP only if green (else `git stash`, revisit later). Delete stray `main.py`, `src/`. One PR: Phase 2 + 3 → `main`, merge. Split `requirements.txt` runtime/dev.
**D2 — backend runs from one command.** `apps/api/Dockerfile`, `docker-compose.yml` (api, worker, postgres, redis, minio, sandbox worker `network_mode: none`). Script: signup → CSV upload → job → preview passes on compose.
**D3 — frontend foundation.** `openapi-typescript` client, TanStack Router/Query, Tailwind + shadcn, tokens from `theme/tokens.css`. Auth screens (signup, verify, login), org/project list.
**D4 — app shell.** Layout, project page, nav for the 5 areas, error/empty states from `assets/ui-contract/ui-copy.json`.
**D5 — upload.** File picker (filters from `file-picker-filters.json`), upload, job polling, failure messages (closed error codes).
**D6 — preview.** TanStack Table + Virtual over server paging; column types/profile header.
**D7 — generic stage runner.** Catalog-driven form + run + result viewer. Wire Clean ops end to end.
**D8 — Analyze.** Profile, correlation, aggregation, a few stats through the same runner. Dataset lineage list (undo = pick parent).
**D9 — Visualize.** Plotly.js fed by the chart `render` endpoint, chart recommender, save visualization.
**D10 — Report.** Report endpoint → HTML/PDF download. (PDF slips → HTML only.)
**D11 — deploy.** One VPS + Docker Compose + Caddy (TLS). Prod env (`SANDBOX_*`, `STORAGE_*` + SSE, `EMAIL_*`, `FRONTEND_BASE_URL`), email provider, domain. Prove: malformed PDF fails safe.
**D12 — verify.** Playwright E2E of the happy path in CI; axe smoke; one security pass (auth, upload, sandbox, prod settings).
**D13–D14 — buffer, bugfixes, landing page, README quickstart. Ship Sat 11-07.**

## Rules
1. Scope is frozen by this file. New idea → `BACKLOG.md` line, not a doc.
2. A day that slips is recovered by cutting in this order: Forecast → PDF → charts beyond recommender → lineage UI. Never move the ship date.
3. Done = demonstrated in a browser against compose or prod, not "tests pass".
4. Two decisions I assumed (change by D2): hosting = single VPS, assistant = off at launch.
