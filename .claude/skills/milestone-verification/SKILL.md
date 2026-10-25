---
name: milestone-verification
description: Project-specific checklist for verifying that a milestone, feature, or fix is actually complete and integrated. Use before declaring milestone work complete, especially when claiming tests or runtime verification.
---

# Milestone Verification

This project is developed milestone-by-milestone. A milestone must be complete and integrated, not merely stubbed.

This skill adds project-specific verification on top of generic verification workflows. Do not use it as a replacement for Superpowers verification or feature-dev.

## Test Verification

`tests/` mirrors `uadas_core/`'s package layout and has real, CI-gated coverage — this is no longer "may
contain no tests." Still verify that the tests relevant to this milestone were actually collected
and executed, not merely that some command's exit code was 0: a narrowed `--ignore`/`-k`/marker
selection, or a collection error masked by `-q`, can silently produce a misleadingly-green run.

Run the suite the way CI does — `python -m pytest tests -q` — see this project's root `CLAUDE.md`
("Tests" under "Commands"). Also run `lint-imports` (the 3 `.importlinter` contracts).

`black`, `isort`, `mypy` (scoped to a curated clean-module list, not repo-wide — see
`docs/MYPY_DEBT.md`), `ruff`, and `bandit` all have committed configuration in `pyproject.toml`,
pinned versions in `requirements.txt`, and are gated in `.github/workflows/ci.yml`. "Tests pass"
and "lint/type/security checks pass" are meaningful verification signals for this project — do not
discount them as insufficient by default. (This section previously said the opposite, written when
that was still true; it stayed unfixed for many milestones after tooling was actually configured —
treat a milestone that changes test/tooling state as also owning an update to this file and to
`docs/ARCHITECTURE.md`'s "Important architectural constraints to preserve" section.)

## Structural Verification

Before declaring a milestone complete:

- Confirm every new source file has the project's required `# File: <path>` header.
- Confirm the module contains the required rationale/documentation.
- Confirm new `BaseReader`, `BaseOperation`, `BaseChart`, or `BaseLLMProvider` implementations are properly integrated.
- Confirm new configuration fields are registered through all required configuration/schema touchpoints.
- Confirm new services are registered through the project's dependency-container/bootstrap mechanism.
- Check the `project-architecture` skill when a change introduces a new extension point or configuration/service integration.
- Verify that implementation exists in `uadas_core/`; do not treat `SPECIFICATION.md` as proof that functionality has already been implemented.

## Runtime Verification

For cross-module changes, static inspection is not sufficient. There is no runnable application
until the Phase 4 web UI exists, so execute the changed code path directly: run the relevant tests
and, where useful, a short script or REPL call that exercises the changed behaviour end to end
(e.g. through `bootstrap()`'s `BootstrapContext`, with a temp config/log dir).

Verify the actual behaviour rather than only confirming that imports succeed.

## Integration Verification

Check that the new functionality is reachable through the existing `uadas_core` architecture.

Examples:

- A new reader is registered in `_BUILTIN_READERS` and its extensions are in `assets/ui-contract/file-picker-filters.json`.
- A new chart is registered in `chart_registry` and buildable through it.
- A new service is available through dependency injection rather than being constructed ad hoc.
- A new configuration value is represented in defaults, schema validation, and the configuration model.

## Completion Rule

Do not claim:

- "implemented"
- "working"
- "tested"
- "verified"
- "ready"

until the appropriate structural and runtime checks have been performed.

When automated coverage is unavailable, explicitly distinguish:

- static verification
- automated test evidence
- direct execution of the changed code path (script/REPL)

Do not substitute one for another.

## When to Use

Automatically use this skill immediately before declaring a milestone, feature, or significant fix complete.

It is particularly important before:

- committing milestone work
- writing a completion summary
- claiming tests passed
- claiming integration is complete
