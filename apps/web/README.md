# apps/web — Glass-Box Analyst SPA

Vite + React 19 + TypeScript. This is the frontend workspace for the
desktop → web transition (`plans/web-transition-glass-box-studio.md`).

## Status: Phase 4 workbench with the first data views wired to the API

What is **real** in here today (design: `plans/phase-4-design-reference.md`):

- **The Instrument workbench** (`src/workbench/`): a chrome band with a View
  menu, five fixed panes laid out like the C6 reference (data grid, inspector,
  rules/report, profile/chart, schema/lineage) and a status strip. Drag a
  gutter or use its arrow keys to resize; collapse any pane to a strip or
  maximise it; sizes persist in `localStorage`. The five areas (Data, Clean,
  Analyze, Visualize, Report) are views opened from the View menu or the keys
  `1`-`5` (View > Single-key shortcuts turns them off); `F6` / `Shift+F6` move
  focus between panes and `Esc` restores a maximised pane. Built on headless primitives (`react-resizable-panels`,
  Radix menubar and tabs) with our own flat CSS, no shadcn/Tailwind.
- **Components** (`src/components/`): buttons, select, radio, alert bar, a sortable
  table, a keyboard-operable tree-table, and the sheet pieces (numbered sections,
  key/value list, quote strip, editable value). Dev gallery: `/components.html`.
- **Design tokens** (`src/theme/tokens.css`) are **generated**: edit
  `assets/design-tokens/instrument.json`, then run
  `python scripts/build_design_tokens.py` (it fails on any contrast pair below
  WCAG). The theme is dark only.
- `src/pipeline.ts` still holds the 10-stage pipeline IA ported from the
  desktop app; nothing renders it since the old mock shell was replaced, and
  the five areas above are the navigation going forward.

- **Data views** (`src/workbench/views/`, state in `src/workbench/data.tsx`):
  sign-in, the calm first-run pane, upload (picker or drop; the first upload
  creates "Untitled project"), a virtualised cell grid that pages rows from the
  API and sorts on the server, the inspector, the schema and lineage trees and a
  per-column completeness plot. Signed in users work in their first organization
  and its first project; there is no organization or project picker yet.
- **API client** (`src/api/`): `openapi-fetch` over `schema.d.ts`, which is
  generated from `apps/api/openapi.json` (`pnpm gen:api` after the contract
  changes). allauth's sign-in routes are not in that schema and are hand-written
  in `auth.ts`. Server state is cached with TanStack Query.

What is **still placeholder**: the Rule editor, Report and Chart tabs (hints
only), signup / email verification / password reset screens, and narrow-screen
layout.

## Run

```bash
pnpm install
pnpm dev          # http://localhost:5173, forwards /api to Django on 127.0.0.1:8000
pnpm build        # tsc -b && vite build
pnpm exec tsc -b  # typecheck only
pnpm gen:api      # regenerate src/api/schema.d.ts from ../api/openapi.json
```

To use the data views you need the API running too (see `apps/api/README.md`):
MinIO from `docker-compose.dev.yml`, then in `apps/api` set `JOBS_EAGER=1` (jobs
run inline, no worker) and run `python manage.py migrate` and
`python manage.py runserver`. Sign up through the API (there is no signup screen
yet), then sign in on the workbench. The dev server keeps the browser's `Host`
header when proxying (`changeOrigin: false`) because Django's CSRF check compares
`Origin` with `Host`.

Dev-only galleries while `pnpm dev` is running: `/tokens.html` (swatches, region
fills at 50 %, contrast audit) and `/components.html` (every component, with
states).

Node 22+ / pnpm. No environment variables required for the web app.
