# Phase 3.6 — API surface

**Branch:** `phase-3/django-backend` · **Code:** `apps/api/uadas_api/{web,stages}/`, `exports/service.py` · **Prior:** [phase-3-5-jobs.md](phase-3-5-jobs.md)
**Contract:** `apps/api/openapi.json` (OpenAPI 3.1, committed; `python -m uadas_api.web.openapi [--check]`; CI + a test fail on drift).

## Resources (below `/api/organizations/{org_id}`; roles: viewer reads, editor writes, admin manages)

| Route | Role | Notes |
|---|---|---|
| `projects` CRUD | viewer / editor / admin (delete) | `409` duplicate name, or delete while datasets/reports exist |
| `projects/{p}/datasets` list, get, delete; `/preview`, `/summary` | viewer / editor | preview: server paging (≤200), validated `sort`, core cell formatters; summary from the Parquet footer |
| `projects/{p}/datasets/upload` | editor | multipart, `202` + ingest job |
| `projects/{p}/jobs` list, get, `/cancel`, `/stage-result` | viewer / editor | polling; result sections of a stage run |
| `projects/{p}/charts` CRUD, `POST /{id}/render` | viewer / editor | render = bounded sync call on ≤5,000 rows (below the resampler threshold), ≤2 MiB JSON |
| `projects/{p}/dashboards` CRUD | viewer / editor | typed tiles; chart ids resolved in the project at write **and** read |
| `projects/{p}/reports` create (`202`, job), list, get, delete, `/download` | viewer / editor | download = presigned URL, 60 s |
| `projects/{p}/pipeline/nodes`, `/edges`, `recipes` list, get | viewer | read-only; written only by jobs |

## Stage → router (generated from `PipelineStage`; tags = stage names; `catalog` always, `run` if it has operations)

`upload` (multipart route) · `understand` profile · `clean` 5 cleaning ops → derived dataset · `explore` aggregate, cross-tab · `analyze` 9 statistics · `visualize` `build_chart` · `predict` 6 forecasters · `explain`, `report`, `reproduce`: empty catalog (their own resources or an AI provider, absent not stubbed). Catalog = the core `tool_registry` (name, description, JSON-Schema parameters, strict); `STAGE_OPERATIONS` is the one hand-kept map, pinned both ways by `test_web_stages.py`. A run validates, then enqueues a `run_operation` job; the worker loads the frame, runs the same tool the AI chat calls, and stores the Phase 1.5 sections on the job (cap 4 MiB). Cleaning writes a derived `DatasetRecord` (`parent_dataset_id`, `derivation_description`) + provenance node/edge in the job's success transaction.

## Security rules

* Every route: session + CSRF (default auth), `member(request, org_id, role)` first, then `project_of` / `in_project` (`for_organization` + the path's project). Foreign = missing = `404`. JSON ids are never dereferenced unresolved (job result, node dataset, dashboard tiles, report config).
* `tests/test_web_idor.py` walks **every** schema operation as an org-B owner: foreign org, foreign ids, foreign ids in bodies (each with an own-ids twin); an unclassifiable route fails the walk.
* Errors: one envelope, closed code set, fixed sentences, 422 details = location + type only; job failures are closed codes.
* Upload: Django parses a multipart body before auth runs, so the upload handler itself gates the upload route (signed in, editor of the path's organization, throttle) *before* any body byte is read; a run's `periods`/`k`/`n_components`/`seasonal_periods`/`degree` are bounded in the catalog schema; the stored original is always `application/octet-stream`.
* Limits: page ≤200; JSON body ≤1 MiB; upload ≤ sandbox input cap enforced **while streaming** (only upload handler; no memory handler); upload throttle 30/h, run 120/h, render 600/h, report 30/h per user+org (atomic fixed-window counter in the cache).

## Decisions

Upload is server-side (the server sees every admitted byte; presigned-then-complete is the later optimisation). Chart render is sync-bounded; full-data charts are the `visualize` job. Stage results live on the `Job` row (display text, bounded), not in the bucket (the reconciler would call them leaks). New job kinds `run_operation`, `build_report`; new code `operation_failed`. Schemathesis runs in process against the committed schema (GET fuzz + real-id smoke).

## Deferred

Recipe create-from-DAG; per-operation expertise hints (core has only per-stage weights); figures in reports; `explain`; SSE (3.7); quotas, SQL capability (3.8); range-reads of Parquet (the object is spooled to disk, page memory is bounded); `PATCH`-level audit events; organization offboarding.
