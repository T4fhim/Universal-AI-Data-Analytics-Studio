# 0002 — Accept private `_configured`-flag coupling in logger tests

## Status

Accepted.

## Context

Phase 5's architect review flagged (MEDIUM) that `tests/conftest.py`'s
`reset_logging_state` fixture directly sets
`src.core.logger._configured = False` and manually strips root-logger
handlers, and that `tests/core/test_logger.py` asserts on
`logger_module._configured` directly. Both reach into a private,
underscore-prefixed module attribute rather than a public API.

`src/core/logger.py` was re-read in full before deciding.
`configure_logging()`'s own docstring documents the "configure exactly
once per process" guard as deliberate: "This should be called exactly
once, early in application startup... Calling it again after the
first call is a no-op." No public reset function exists today, and
nothing in `logger.py`'s docstring or CLAUDE.md anticipates test code
needing to reset this state.

Two options were considered:

1. Add a small public function to `logger.py` (e.g.
   `reset_for_testing()`) that tests call instead of touching
   `_configured` directly.
2. Leave the fixture as-is, documenting the coupling as an accepted,
   test-only pattern.

## Decision

Leave the existing fixture-level coupling in place. No change to
`src/core/logger.py`, `tests/conftest.py`, or
`tests/core/test_logger.py`.

Option 1 was rejected specifically because it adds production API
surface (`logger.py` gains a new public function) to serve a need that
exists only in test infrastructure. `logger.py`'s own module docstring
already explains why `configure_logging()`'s once-per-process guard
exists in production; a reset function would only ever be called from
`tests/`, meaning the "public" surface it adds is public in name only
— a test-only escape hatch dressed up as a real API. The existing
approach keeps that reality honest: the coupling is visible,
localized to two files, and each site already carries a comment
explaining exactly why it exists (see `tests/conftest.py`'s
`reset_logging_state` docstring, and `logger.py`'s own "Calling it
again after the first call is a no-op" documentation, which the
fixture's comment quotes directly).

This is a narrow, low-risk coupling: `_configured` is unlikely to be
renamed casually, since renaming it would also break
`configure_logging()`'s own internal `global _configured` reference —
any refactor of that name is already a deliberate, visible change to
`logger.py` itself, not something that could happen by accident
without the fixture's breakage being an expected, easily-diagnosed
consequence.

## Consequences

- If `logger.py`'s internal state-tracking mechanism is ever
  refactored (e.g. replaced with a different guard mechanism), the
  fixture and `test_logger.py`'s one assertion on `_configured` will
  need updating in the same change — this is an accepted, documented
  maintenance cost, not a silent risk.
- No new public function was added to `logger.py`, keeping its public
  surface exactly as small as before.
