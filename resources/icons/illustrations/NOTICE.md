# Illustrations — provenance

These SVGs are **hand-authored for this project** (milestone 27), drawn to the same
convention `resources/icons/NOTICE.md` documents for the action-icon set:

- `24 x 24` viewBox
- `fill="none"`, `stroke="currentColor"`, `stroke-width="2"`
- `stroke-linecap="round"`, `stroke-linejoin="round"`

They are original, simple, decorative shapes (an open crate, a dashed "nothing found"
lens, an X-in-circle) built for `src/ui/widgets/empty_state.py`/`error_state.py`, not
copies of any licensed icon or illustration set. They are covered by this project's own
licence.

Kept in a separate `illustrations/` subdirectory from `resources/icons/` because they are
rendered larger (empty/error state heading art, not toolbar/menu glyphs) and are looked up
directly by `EmptyState`/`ErrorState` rather than through
`src/ui/theme/icon_provider.py`'s `IconProvider.available_icons()` -- which globs
`resources/icons/*.svg` non-recursively and therefore never needs to enumerate these.
