# Icon set — provenance

These 41 SVGs are **hand-authored for this project**, drawn to the conventions the
Lucide icon set established:

- `24 x 24` viewBox
- `fill="none"`, `stroke="currentColor"`, `stroke-width="2"`
- `stroke-linecap="round"`, `stroke-linejoin="round"`

They are *not* copies of Lucide's files, so no third-party licence applies to them.
They are covered by this project's own licence.

## Why `currentColor` matters

`currentColor` is a CSS cascade keyword and means nothing to Qt's SVG renderer —
Qt has no cascade to inherit from. `src/ui/theme/icon_provider.py` substitutes the
active theme's colour into the markup as a plain string before rendering. **Any icon
added here must use `stroke="currentColor"`**, or it will render in a fixed colour
and become invisible against one of the themes.

## Swapping in real Lucide files

`IconProvider` resolves icons by filename stem, so dropping genuine Lucide SVGs into
this directory under the same names replaces these with no code change. Lucide is
ISC-licensed; if you do that, record its licence here and keep this file's
`currentColor` requirement in mind — Lucide already satisfies it.
