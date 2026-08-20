# Milestone 28 — manual screen-reader verification (open)

This file exists because milestone 28's own plan section requires it explicitly:

> **Manual screen-reader (NVDA) pass performed and recorded** — see 2.4-equivalent Tools note
> below; not merely automated.

and, from the plan's "Tools: CI, screen readers, profiling, previews" section:

> Automated a11y checks catch roughly a third of real accessibility defects industry-wide.

## What this milestone actually did, automated

- `src.ui.a11y.audit.audit_widget_tree` walks a real, fully constructed `MainWindow` (menu bar,
  toolbar, status bar, every dock, every workbench stage page, and any dialog already parented to
  the window at construction time) and reports every finding from the eight rules in
  `src.ui.a11y.rules`: missing accessible names on button-like and field-like controls, `Qt.NoFocus`
  on interactive widgets, dialogs with no keyboard-focusable content, duplicate window-scoped
  keyboard shortcuts, untitled docks, undescribed illustration labels, a structurally degenerate
  tab-order chain, and WCAG 2.2 AA contrast failures (reusing `src.ui.theme.contrast`'s math and
  `src.ui.a11y.contrast_manifest.CONTRAST_REQUIREMENTS` directly, not a reimplementation).
- Run for real, with a dataset loaded (so every workbench stage page actually exists, not just the
  welcome page), this returns **zero ERROR findings** — see `tests/ui/a11y/test_audit.py::
  test_audit_widget_tree_finds_zero_errors_against_a_populated_main_window`. Two real defects were
  found and fixed along the way (not suppressed): `CommandPalette`'s search field had no accessible
  name (`src/ui/command_palette.py`), and the same gap in the M28-added Settings-dialog controls was
  avoided by describing them at construction time.
- `src.ui.a11y.audit.ALL_DIALOG_CLASSES` is discovered by walking `src/ui/`'s module tree at import
  time (`pkgutil.walk_packages` + `inspect.getmembers`), not hand-maintained — currently resolves to
  the 8 `QDialog` subclasses that exist in this codebase today. This closes the specific drift risk
  the plan calls out: a new dialog is automatically included the next time this constant is imported,
  with no second list to remember to update.
- `HIGH_CONTRAST_TOKENS` (shipped since M15) passes the identical `CONTRAST_REQUIREMENTS` suite dark
  and light already do — `tests/ui/theme/test_contrast.py` parametrizes over every entry in
  `TOKENS_BY_NAME`, so this was already true and is now additionally exercised via
  `audit_widget_tree`'s own contrast rule in `tests/ui/a11y/test_audit.py`.
- `accessibility.reduced_motion` and `accessibility.base_font_size` are real `config.yaml` keys
  (default `false` / `13`), applied at startup (`src/core/app.py`) and live from the Settings dialog
  (`ThemeController.apply_theme_from_settings`), and actually change runtime behavior: reduced motion
  swaps the status bar's indeterminate ("marquee") busy indicator for a static, fully-filled bar
  (`ApplicationStatusBar.set_reduced_motion`) — the one piece of continuous animation that existed
  anywhere in `src/ui/` at the time this milestone was built, confirmed by grep, not assumed — and
  base font size scales `ThemeTokens.font_size_sm/md/lg` together via
  `ThemeTokens.with_base_font_size`, re-applied through the same stylesheet-recompile path
  `set_density` already used.

None of the above is a substitute for the item below. It is the floor the plan itself says automated
tooling represents — real, and worth having, but not the same claim as "a screen reader user can
actually operate this application."

## What remains open

**A full NVDA (or other Windows screen reader) pass through the running application has not been
performed.** This requires a human at a real Windows machine with NVDA (or Narrator/JAWS) installed
and running, driving the actual GUI — cold start, import a dataset, walk every workbench stage with
Tab and screen-reader-specific navigation keys (not just Tab), open every dialog `ALL_DIALOG_CLASSES`
now enumerates, toggle the theme (including `high_contrast`) and the two new accessibility settings,
and record what NVDA actually announces at each step. No agent running in this environment has a
screen reader available to drive, and no automated substitute (however thorough the widget-tree audit
above is) can stand in for that walkthrough — this is the same limitation the M16/M17/M18/M20
milestones already flagged for their own narrower manual-NVDA-pass acceptance boxes, restated here at
the whole-application scope this milestone was supposed to close it at.

**This acceptance box stays open until a human performs that pass and records findings in this file**
(append a dated section below with what was tested, on what screen reader/version, and what was
found — pass or fail). Do not check it off, and do not let a future milestone assume it happened,
until a real entry exists here.

## Findings log

*(empty — no manual pass has been recorded yet)*
