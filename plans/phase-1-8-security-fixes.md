# Phase 1.8 — Four Security Fixes (as-built record)

**Status:** implemented 2026-09-07 on `phase-1/extract-uadas-core` · `security-reviewer`
scoped the set before implementation (verdict: APPROVE, one addition to Fix 2) · a
`security-reviewer` verification pass follows the commits below.

**Nature:** Part D step 5. Unlike steps 1.1 / 1.2 / 1.3 / 1.5, this step **does** change
behaviour — four named, test-guarded changes. Each is one commit with its own red-then-green
test. No `src/` shell code needed changing (the two AI/DB call paths affected have no
production caller yet or the change is additive).

---

## The four fixes

| # | Commit | Site | Change |
|---|---|---|---|
| 1 | `6b8a628` | `uadas_core/ai/assistant_service.py` | Tool-dispatch loop was `while True`. Now `for _ in range(_MAX_TOOL_ITERATIONS)` (25); exhausting it raises `ServiceError`. Datasets/visualizations already produced are registered in `WorkspaceService` as `_execute_tool` creates them, so only the reply is abandoned. |
| 2 | `88587b4` | `uadas_core/readers/archive_reader.py` | ZIP entry names came straight from `namelist()` (attacker-controlled) into `ZipFile.extract()`. CPython sanitises `..`/absolute paths *silently*; symlink entries are not neutralised portably. New `_reject_unsafe_archive_member()` (absolute / drive-letter / `..` / symlink) is applied in `list_tables()` (filter) and `_read_zip()` (raise on explicit request + re-check symlink bit against the real `ZipInfo`), plus a post-extraction `_is_within()` containment assertion. `_read_gzip()` routes its inner name through the same guard. |
| 3 | `12c7564` | `uadas_core/ai/provider_rotation.py` | `from_config_profiles()` resolved every `api_key_env_var` against `os.environ` only. New optional `secrets: Mapping[str, str] | None` — when given, keys are looked up there instead; when `None` (desktop default) `os.environ` is read exactly as before. This is the Phase 3 injection seam (Django settings / secrets manager). |
| 4 | `779e7e6` | `uadas_core/database/base_connection.py` | `execute_query()` ran any caller-supplied SQL for any connection. New `allow_arbitrary_queries: bool = False` on `__init__` (3rd positional, defaulted — subclasses inherit it; `database_connection_service`'s `connector_class(profile, password)` call is unaffected). `execute_query()` raises `ServiceError` before opening the engine unless the flag is set. No production caller of `execute_query` / `DatabaseReader.read_query` exists today (the UI only uses `read_table`). |

## `security-reviewer` scope verdict (pre-implementation)

- Fix 1 — APPROVE. 25 is a sane cap; partial work already persists; raising is correct.
- Fix 2 — APPROVE **+ add symlink rejection** to the member guard, with its own red test. (Done.)
- Fix 3 — APPROVE. `Mapping[str, str]` is the right injection type; keep the `os.environ`
  fallback; no "mandatory injection" switch needed yet.
- Fix 4 — APPROVE. Constructor bool is the right capability shape. **`B608` stays in the
  bandit `--skip` set** — it is triggered by `execute_query` still building SQL from a string,
  which the capability gate does not remove.

## Bandit / baseline housekeeping

`.bandit-baseline.json` was already deleted and both CI and `.claude/hooks/pre-commit-check.ps1`
already use `--skip B101,B107,B608` (done in the 1.1 codemod, `0c76a3b`). **Nothing further
needed** for 1.8 — confirmed with `security-reviewer`. `bandit -r src uadas_core -q --skip
B101,B107,B608` -> exit 0 after all four commits.

## Tests added (7)

- `tests/ai/test_assistant_service.py::test_send_message_stops_after_max_tool_iterations_instead_of_looping_forever`
  (`_NeverStopsProvider` returns a tool call on every `send()`; pre-fix the call never returns,
  post-fix it raises and `send` was called exactly `_MAX_TOOL_ITERATIONS` times).
- `tests/readers/test_new_format_readers.py::test_archive_reader_rejects_a_path_traversal_entry`
  and `::test_archive_reader_rejects_a_symlink_entry` (pre-fix both entries are listed and read
  successfully; post-fix both are filtered from `list_tables` and raise `ReaderError`).
- `tests/ai/test_provider_rotation.py::test_from_config_profiles_resolves_keys_from_injected_secrets_not_environ`
  (+ `::test_from_config_profiles_still_reads_environ_when_no_secrets_given` for the unchanged
  desktop path).
- `tests/database/test_base_connection.py::test_execute_query_refused_without_the_capability`
  and `tests/database/test_database_reader.py::test_read_query_refused_when_connection_lacks_the_query_capability`
  (+ a `query_connection` fixture in each file so the existing arbitrary-SQL tests stay green).

## Verification

- Targeted: `tests/ai/test_assistant_service.py` 11 passed · `tests/readers/test_new_format_readers.py`
  22 passed · `tests/ai/test_provider_rotation.py` 8 passed · `tests/database/test_base_connection.py`
  + `tests/database/test_database_reader.py` 20 passed.
- `black --check` / `isort --check-only` / `ruff check` clean on every touched file.
- `mypy uadas_core/database uadas_core/results uadas_core/jobs --ignore-missing-imports
  --follow-imports=silent` -> clean (`uadas_core/ai` is pre-existing mypy debt, excluded from
  the CI list — see `docs/MYPY_DEBT.md`).
- `bandit -r src uadas_core -q --skip B101,B107,B608` -> exit 0.
- Full suite (CI two-invocation split): **see `plans/phase-1-baseline.md` "Post-1.8"**.

## Unverified

- The red state of the "pre-fix succeeds" tests (1, 2x zip, 4) is argued structurally
  (`while True` + always-tool-call provider hangs; CPython `extract` sanitises rather than
  raises; `execute_query` had no gate) rather than demonstrated by reverting each fix. The
  `security-reviewer` verification pass re-checks this.
- `_MAX_TOOL_ITERATIONS = 25` has no profiling data behind the exact number — it is "far above
  any real chained analysis, low enough to kill a runaway loop fast". Tunable; a change is not
  a behaviour break for any legitimate caller.
