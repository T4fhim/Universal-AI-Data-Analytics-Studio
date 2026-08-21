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

## Tier 1 follow-up: real Windows UI Automation verification (closed)

`audit_widget_tree` above proves something real but narrower than it sounds: every check it runs reads
Qt's *in-process* accessible properties (`widget.accessibleName()`, `widget.focusPolicy()`, etc.). It
never proves Qt actually handed that information to the real Windows UI Automation (UIA) layer — the
one NVDA, Narrator, and JAWS all actually consume — and a Qt application can have every in-process
property look correct while UIA itself exposes something else, or nothing, to a real screen reader.
That gap is exactly what a human NVDA pass would have caught, but a large fraction of it is also
mechanically checkable without a screen reader: does the real OS accessibility tree expose the names,
roles, and live keyboard-focus behavior a screen reader's narration would be built from at all.

`tests/ui/a11y/test_uia_integration.py` (plus its out-of-process launch target,
`tests/ui/a11y/_uia_target_app.py`) is that check, added as a Milestone 28 follow-up. It launches a
real, visible, OS-level top-level window — genuinely windowed, not `QT_QPA_PLATFORM=offscreen`, since
offscreen never creates real UIA elements — running the actual `MainWindow` (bootstrapped, themed, with
a dataset loaded, the same "fully populated" shape `test_audit.py`'s own fixture uses), and drives it
with `pywinauto`'s real UIA backend from a separate OS process, the same way an actual screen reader
observes a running application. Concretely, it asserts, against the *real* UI Automation tree, not Qt's
in-process view of itself:

- Every control `audit.py`'s own name-requiring rules cover (`interactive-name`, `input-buddy`'s
  explicit-accessible-name case) is not just described in-process but genuinely visible with that exact
  name in the real UIA tree, for the main window and for two representative on-demand dialogs
  (`AboutDialog`, `CommandPalette` — chosen because both need no service wiring beyond what
  `bootstrap()` already provides; this does **not** exhaustively open every dialog
  `ALL_DIALOG_CLASSES` discovers, a disclosed scope limit, not an oversight — see that test module's
  own docstring).
- Roles are sane: `QPushButton`/`QToolButton` expose the UIA `Button` control type, `QLineEdit` exposes
  `Edit`, `QComboBox` exposes `ComboBox`, `QListWidget` exposes `List`, `QLabel` exposes `Text` — all
  four empirically confirmed while building this test, not assumed from Qt documentation.
- `CommandPalette`'s tab order is checked *live*, not statically: `rules._check_tab_order_
  nondegenerate`'s own docstring explains why a static widget-tree walk cannot verify Tab actually moves
  focus in a sensible order — it needs "a live event loop and a shown window", which this test is the
  first thing in the suite to actually provide. It drives a real Tab keypress into the real window and
  confirms keyboard focus moves from the search field to the results list, via UIA's own
  `HasKeyboardFocus`, not an assumption.

This is Windows-only (`pytest.mark.skipif(sys.platform != "win32", ...)`) and skips cleanly, not
silently, if `pywinauto` cannot be imported or a real visible window genuinely cannot be created in a
given environment (both real `pytest.mark.skipif`/`pytest.skip()` calls, visible in the run's summary).
It is wired into CI as a separate, non-blocking `uia_integration` job in
`.github/workflows/ci.yml` (`continue-on-error: true`) rather than folded into the main blocking `test`
job — manual verification while building it found individual UI Automation queries occasionally slow,
and on repeated connects to the same long-lived process, non-deterministically stalling (mitigated with
per-test bounded timeouts and one fresh process per test, but not eliminated as a risk this early); see
that test module's own docstring and the `uia_integration` job's comment in `ci.yml` for the full
reasoning behind that judgment call.

**What this still does not, and cannot, prove.** Whether the *sequence and wording* of what a screen
reader actually speaks is comprehensible — whether "Search actions, edit" said in that order, at that
moment, with that phrasing, would actually make sense to someone who cannot see the screen — is a
judgment call about spoken narration, not a structural property of the accessibility tree. No automated
UIA walk can render that judgment; only a human listening to real NVDA/Narrator/JAWS output can. That is
Tier 2, and it is exactly the item below: still open, still requiring a human, not narrowed by anything
in this section.

## What remains open (Tier 2: human NVDA pass)

**A full NVDA (or other Windows screen reader) pass through the running application has not been
performed.** This requires a human at a real Windows machine with NVDA (or Narrator/JAWS) installed
and running, driving the actual GUI — cold start, import a dataset, walk every workbench stage with
Tab and screen-reader-specific navigation keys (not just Tab), open every dialog `ALL_DIALOG_CLASSES`
now enumerates, toggle the theme (including `high_contrast`) and the two new accessibility settings,
and record what NVDA actually announces at each step, judging whether that spoken output is
comprehensible and sanely ordered — the one thing Tier 1 above cannot judge (see that section's closing
paragraph). No agent running in this environment has a screen reader available to drive, and no
automated substitute (however thorough the widget-tree audit and the Tier 1 real-UIA checks above are)
can stand in for that walkthrough — this is the same limitation the M16/M17/M18/M20 milestones already
flagged for their own narrower manual-NVDA-pass acceptance boxes, restated here at the whole-application
scope this milestone was supposed to close it at.

**This acceptance box stays open until a human performs that pass and records findings in this file**
(append a dated section below with what was tested, on what screen reader/version, and what was
found — pass or fail). Do not check it off, and do not let a future milestone assume it happened,
until a real entry exists here.

## Findings log

*(empty — no manual pass has been recorded yet)*
