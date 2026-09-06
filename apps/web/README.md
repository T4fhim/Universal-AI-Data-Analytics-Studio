# apps/web — Glass-Box Analyst SPA

Vite + React 19 + TypeScript. This is the frontend workspace for the
desktop → web transition (`plans/web-transition-glass-box-studio.md`).

## Status: Phase 4.3 preview (shell only, no backend)

What is **real** in here today:

- The 10-stage pipeline IA and its rationale copy, ported verbatim from
  `src/services/analysis_orchestrator_service.py` (`PipelineStage`,
  `_AUTO_PROPOSED_STAGES`, `_STAGE_RATIONALE`).
- The provenance log-entry shape, ported from `AnalysisLogEntry`
  (`stage · tool · inputs · outputs · explanation · timestamp`).
- Theme-aware design tokens (`src/theme/tokens.css`) — layered surfaces,
  text roles, accent + semantic colors, spacing, radii, font sizes — a
  representative subset of `src/ui/theme/tokens.py`'s shape.
- The non-colour stage-status vocabulary (`✓ / → / ·`) from
  `src/ui/workbench/stage_rail.py`.

What is **mock**: every value, the AI proposal, and all interactivity
beyond stage selection and the theme toggle. There is no API. Phase 3
builds the Django + Django Ninja backend; Phase 4.1 generates a typed
client from its committed OpenAPI schema; Phase 4.2 does the faithful
token port and adds Tailwind + shadcn/ui.

## Run

```bash
pnpm install
pnpm dev          # http://localhost:5173  (this session used --port 5175)
pnpm build        # tsc -b && vite build
pnpm exec tsc -b  # typecheck only
```

Node 22+ / pnpm. No environment variables required.
