---
name: milestone-verification
description: Project-specific checklist for verifying that a milestone, feature, or fix is actually complete and integrated. Use before declaring milestone work complete, especially when claiming tests or runtime verification.
---

# Milestone Verification

This project is developed milestone-by-milestone. A milestone must be complete and integrated, not merely stubbed.

This skill adds project-specific verification on top of generic verification workflows. Do not use it as a replacement for Superpowers verification or feature-dev.

## Test Verification

The `tests/` directory may contain no tests.

Never report "tests pass" merely because:

    pytest tests/

returns exit code 0.

First verify that tests were actually collected and executed. Zero collected tests means there is currently no automated test evidence.

`pytest`, `black`, `isort`, and `mypy` are project dependencies, but they are not currently sufficient by themselves to establish milestone correctness because project-wide enforcement/configuration is incomplete.

## Structural Verification

Before declaring a milestone complete:

- Confirm every new source file has the project's required `# File: <path>` header.
- Confirm the module contains the required rationale/documentation.
- Confirm new `BaseReader`, `BaseOperation`, `BaseChart`, or `BaseLLMProvider` implementations are properly integrated.
- Confirm new configuration fields are registered through all required configuration/schema touchpoints.
- Confirm new services are registered through the project's dependency-container/bootstrap mechanism.
- Check the `project-architecture` skill when a change introduces a new extension point or configuration/service integration.
- Verify that implementation exists in `src/`; do not treat `SPECIFICATION.md` as proof that functionality has already been implemented.

## Runtime Verification

For UI or cross-module changes, static inspection is not sufficient.

Launch the application using the project's normal startup path:

    python main.py

Then manually exercise the functionality affected by the milestone.

For GUI changes, verify the actual visible behavior rather than only confirming that imports succeed.

## Integration Verification

Check that the new functionality is reachable through the application's existing architecture.

Examples:

- A new reader is registered and appears in the relevant file-selection path.
- A new chart is registered/usable through the visualization flow.
- A new service is available through dependency injection rather than being constructed ad hoc.
- A new configuration value is represented in defaults, schema validation, and the configuration model.
- A new UI component is actually connected to the relevant window/dock/workspace flow.

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
- manual runtime verification

Do not substitute one for another.

## When to Use

Automatically use this skill immediately before declaring a milestone, feature, or significant fix complete.

It is particularly important before:

- committing milestone work
- writing a completion summary
- claiming tests passed
- claiming a GUI feature works
- claiming integration is complete
