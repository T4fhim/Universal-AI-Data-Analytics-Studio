---
name: project-architecture
description: Project-specific integration and architectural touchpoints for Universal AI Data Analytics Studio. Use when adding readers, operations, charts, LLM providers, configuration keys, or dependency-container services, especially when multiple files must remain synchronized.
---

# Project Architecture Integration

This skill contains repository-specific integration rules that are not generic
software-engineering advice and should not duplicate CLAUDE.md.

Use this skill when modifying the architecture or adding a new extension point.

## Adding a Reader

A new reader requires all relevant integration points to be updated:

1. Create the reader under `src/readers/`.
2. Subclass the project's `BaseReader`.
3. Register the reader in:

   `src/readers/reader_registry.py`

4. Update the dataset file-dialog filter in:

   `src/ui/main_window.py`

The file-dialog filter is manually maintained and does not automatically derive
from the registered reader extensions.

Therefore, adding a reader to the registry without updating the UI filter
creates an incomplete integration.

## Adding a Configuration Key

A new configuration value must remain synchronized across the configuration
schema and dataclass.

Check:

- `_default_config_dict()` in `src/core/config.py`
- `_TOP_LEVEL_SCHEMA` / `_NESTED_SCHEMA` in `src/core/config.py`
- `AppConfig.from_dict()` and the corresponding dataclass field

Do not add a configuration field to only one of these locations.

## Adding a Session-Wide Service

Services shared across the application should be registered through the
dependency container during application bootstrap rather than constructed
ad hoc inside UI components.

Relevant locations:

- `src/core/bootstrap.py`
- `src/core/container.py`

Follow the existing registration pattern and preserve required initialization
ordering.

## Extension-Class Integration

When adding one of the project's extension types:

- `BaseReader`
- `BaseOperation`
- `BaseChart`
- `BaseLLMProvider`

inspect the corresponding registry/factory/integration path before declaring
the implementation complete.

Do not assume that creating the subclass is sufficient.

## Scope Boundary

This skill does NOT provide:

- generic architecture advice
- generic Python conventions
- implementation planning
- TDD methodology
- debugging methodology
- code-review methodology

Use Superpowers, ECC, feature-dev, or Claude Code built-ins for those concerns.

Use CLAUDE.md for the project's general architecture explanation.

This skill exists specifically to prevent repository-specific integration
points from being missed.

## Verification

Before completing architectural changes:

1. Identify every registry/factory/schema/UI integration point.
2. Confirm each required location was updated.
3. Run the project's applicable verification commands.
4. For milestone-level changes, invoke `milestone-verification`.
