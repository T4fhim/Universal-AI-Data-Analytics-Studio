---
name: pyside6-development
description: Project-specific PySide6 and Qt development rules for Universal AI Data Analytics Studio. Use when modifying src/ui, QWebEngineView, QDockWidget, QApplication startup, theming, or Qt widget lifecycle and cleanup.
---

# PySide6 Development

This skill contains confirmed, repository-specific PySide6/Qt behavior and
gotchas. It does not replace general PySide6 documentation.

## QWebEngineView Rendering

### Software OpenGL

`src/core/app.py` configures:

- `AA_UseSoftwareOpenGL`
- `AA_ShareOpenGLContexts`

before constructing `QApplication`.

This ordering must be preserved.

The project previously encountered blank QWebEngineView rendering on the
tested Windows environment when GPU/hardware rendering was used. Do not move
these application attributes below `QApplication` construction without
retesting the complete rendering path.

### Plotly HTML Loading

`src/ui/widgets/chart_view.py` loads generated Plotly HTML through a temporary
file and `QWebEngineView.setUrl()`.

The established project implementation should be preserved.

Do not replace this with `setHtml()` casually. Large fully-inlined Plotly HTML
was observed to fail when loaded through the direct `setHtml()` path in this
application.

If changing this mechanism, verify the actual QWebEngine rendering behavior
with the application running.

## QApplication Lifecycle

There should be one `QApplication` instance per application process.

The project's normal construction point is:

`Application.run()` in `src/core/app.py`

Do not create additional application instances inside ordinary application
code.

Tests may require controlled Qt fixtures, but those should remain test-scoped
rather than becoming additional application startup paths.

## Application Theming

`ThemeManager.apply_theme()` applies the selected QSS stylesheet at the
application level through `QApplication.setStyleSheet()`.

Theme files are located under:

`resources/styles/<theme_name>.qss`

When implementing themeable UI:

- prefer the existing application-level QSS system
- avoid unnecessary per-widget stylesheets
- add reusable styling rules to the appropriate QSS theme
- preserve runtime theme switching through `ThemeManager`

Relevant implementation:

`src/ui/theme_manager.py`

## Dock Widgets

Dock construction is centralized around the project's dock-management system.

When creating a `QDockWidget`:

- assign a stable `objectName`
- use the existing dock-manager patterns
- expose the dock through its standard `toggleViewAction()` when appropriate
- preserve the existing tab/group layout unless the feature explicitly
  changes the UX

Current dock grouping includes:

- Project + Dataset Explorer
- Console + Log

The primary Chart dock remains independently visible.

Relevant implementation:

`src/ui/dock_manager.py`

## Live Widget References

If a dock or widget needs to receive updated application state after
construction, retain the relevant widget as an instance attribute.

For example, the dataset list widget is retained so later refresh operations
can update it without reconstructing the dock.

Follow this pattern for new UI components that require live updates.

## Qt Logging Handler Cleanup

The logging panel uses a Qt-aware logging handler.

Any logging handler, signal connection, timer, callback, or other long-lived
subscription that references a Qt widget must have an appropriate teardown
path.

In particular, handlers attached to the logging panel must be removed before
the associated Qt widgets are destroyed.

Otherwise the logging system can retain references to destroyed UI objects
and later attempt to write to them.

Inspect the existing teardown implementation before changing this area.

## Scope Boundary

This skill does NOT provide:

- generic Python advice
- generic software architecture
- generic debugging methodology
- generic testing methodology
- generic code review
- generic Qt documentation

Use existing Claude Code, Superpowers, ECC, and feature-dev capabilities for
those concerns.

This skill exists only for behavior and conventions specific to this
repository's PySide6 implementation.

## Verification

When changing UI code:

1. Inspect the relevant existing UI implementation first.
2. Preserve the application lifecycle and rendering assumptions above.
3. Run the application when practical.
4. For QWebEngineView changes, verify that the actual rendered content appears.
5. For dock/theme changes, verify the affected UI behavior manually.
6. For milestone-level changes, invoke `milestone-verification`.
