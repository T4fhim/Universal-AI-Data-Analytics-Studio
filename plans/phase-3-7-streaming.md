# Phase 3.7 — Streaming (SSE)

**Branch:** `phase-3/django-backend` · **Code:** `apps/api/uadas_api/{web/{sse,streams,job_events,assistant}.py,jobs/events.py,ai/assistant.py,settings/_assistant.py}` · **Prior:** [phase-3-6-api.md](phase-3-6-api.md)
**Contract:** two operations answer `text/event-stream` and are in the committed `openapi.json` (`x-sse-events` types each event); the IDOR walk, route-walk and auth guards cover them unchanged.

## Routes (async views, served by ASGI; Ninja's built-in `SSE` format has no `event:`/`id:`/`retry:`, so frames are our own)

| Route | Role | Events |
|---|---|---|
| `GET /organizations/{o}/projects/{p}/jobs/{j}/events` | viewer+ | `job` {job_id,status,progress,message,error_code}, `id:` monotonic, `retry:` hint, `: keep-alive` comments. `204` if `Last-Event-ID` already is the terminal id. |
| `POST /organizations/{o}/assistant/messages` | editor+, CSRF | `message` {index,text}, `tool_call` {call_id,name,arguments,proposed:true}, `done` {tool_calls,dropped}, `error` {code,message} |

Deviation: the job route is under its project (like every other job route), not `/organizations/{o}/jobs/{j}`.

## Mechanism: DB polling, not a Redis nudge (decision)

The `Job` row is the only truth; the stream re-reads it (one indexed PK `SELECT`) every 1 s ±20 % jitter, backing off x1.5 to 5 s while unchanged, plus a membership check every 30 s. Why: no second moving part, nothing to lose or reorder, and "Redis down" is a non-event. `redis` is imported by no API module (`test_jobs_boundary`), so pub/sub would also widen that boundary. **Cost per open stream:** ~0.2-1 query/s and one connect/close per poll (no connection held across a sleep); bounded by the caps. A pub/sub nudge (worker publishes, stream wakes early, polling stays as the fallback) is the optimisation if streams outnumber the budget.

## Event ids and resume

`id = attempts*10000 + rank*1000 + progress` (rank queued 0, running 1, terminal 2): derived from state, so no stored history. A (re)connect is always sent the *current* state first, never a replay; ids only grow (a retry bumps `attempts`); a client holding the terminal id gets `204` so `EventSource` stops reconnecting.

## Safety rules

* Events carry only the fields above: never `params`, `result`, rows or `error_message`. Frames: names/ids from a closed alphabet, payload JSON with `ensure_ascii` (one line), per-event size cap (16 KiB job, 64 KiB assistant message, 16 KiB per tool call).
* Caps (cache leases, released on every exit incl. disconnect and a never-started body; TTL heals a killed process): job streams 5/user/org, 50/org; assistant turns 2/user/org, 10/org; `429` `rate_limited`; a cache outage is `503`. Assistant throttle 60/hour/user+org. Stream max life 15 min (client reconnects with `Last-Event-ID`); idle comment every 15 s.
* Async-safe ORM: every query goes through `sync_to_async` and ends in `release_connections()`; no transaction or connection is held while sleeping (`test_web_streaming` counts server connections on PostgreSQL: 8 sleeping streams hold none, mutation-checked).
* **F6: the AI proposes, never mutates.** The assistant path calls the provider directly and returns *proposed* tool calls; it cannot reach a tool handler (AST test) and creates no rows. Proposals are run through the stage endpoints. Unknown tool names and oversized/non-JSON proposals are dropped (counted in `done.dropped`).
* Provider key from deployment env only (`ASSISTANT_PROVIDER`/`_API_KEY`/`_MODEL`; anthropic, gemini, groq; `ollama` refused); unset = `503 unavailable`. Provider errors become a closed code (`provider_error`/`provider_timeout`/`event_too_large`); only the exception class is logged. Stateless: history comes from the client (<=20 turns, <=32k chars), no state on the server.
* CORS allows `Last-Event-ID` (cross-origin `EventSource` reconnects are preflighted).

## Deferred

Token-level streaming (providers' `send()` returns whole turns; a streaming method on `BaseLLMProvider` is needed, and splitting a finished turn would be fake streaming); server-side conversation threads and dataset-schema context for the model; per-user provider keys (need encrypted storage); the Redis nudge; token quotas (3.8).

**Known, bounded, accepted:** (1) a *session* logged out or revoked while a job stream is open keeps streaming -- only membership/active-user loss is rechecked (every 30 s), not the session -- for **at most 900 s** (`sse_max_seconds`), and only that job's state (no data rows); (2) a slow reader (a client that stops reading) holds one stream slot for **at most 900 s** (job) or **90 s** (assistant turn) -- the ASGI server's send buffer, not this code, bounds the bytes, and the caps (5 per user, 50 per organization; 2 / 10 for the assistant) bound the count.

**Review-fix pass:** stream leases are taken in the async body (never in the `sync_to_async` open step, whose result a cancelled handler drops); an assistant turn holds its lease and one of `assistant_max_inflight` (8) process-wide slots on a dedicated pool until the provider thread *ends* (SDK timeout 60 s, SDK retries off), with an extra per-user throttle (120/h across organizations); cap counters refresh their TTL on every acquire; reply parts are split by encoded size (an emoji is 12 bytes); nested SDK argument containers (Gemini/protobuf) are converted to JSON, not dropped; `Cache-Control: no-cache, no-transform, private`.
