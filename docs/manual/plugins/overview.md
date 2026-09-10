---
title: "The Plugin System"
anchors:
  - plugins.overview
---

# The Plugin System

Third-party extensions are discovered from configured search paths and registered into the
same registries the application's own built-in readers, cleaning operations, and chart types
use (`uadas_core.readers.reader_registry`, `uadas_core.cleaning.operation_registry`,
`uadas_core.visualization.chart_registry`) -- a plugin-provided reader is used exactly the same way a
built-in one is, from [Open Dataset](../data/open-dataset.md) onward.

## What a plugin can provide

Three categories today: **readers**, **cleaning operations**, and **charts** -- each validated
against the same `Base*` abstract class the built-in implementations subclass
(`BaseReader`, `BaseOperation`, `BaseChart`). Forecast models and AI providers are explicitly
not yet plugin-extensible: forecasting is a set of plain functions with no shared base shape to
validate a plugin's contribution against, and the AI provider interface is this application's
one stateful exception to the stateless-classmethod pattern every other extension point follows.

## A plugin is a directory

A plugin is a directory containing a `plugin.json` manifest plus an importable Python package
of the same name, naming which classes it provides under each category as
`module.path:ClassName` strings.

## Bad plugins are skipped, not fatal

A malformed manifest, an import error, or a provided class that doesn't actually subclass the
right `Base*` class never prevents every other plugin (or the application itself) from
starting -- the specific problem is recorded and shown in the **Plugins** tab of
[Settings](../settings.md), so you can see exactly what went wrong with a specific plugin
without the rest of the session being affected.

## Enabling and disabling

Each discovered plugin can be individually enabled or disabled from the Plugins tab. A disabled
plugin is not merely hidden -- it is never imported at all on the next startup, so a broken or
untrusted plugin you've disabled has zero side effects, not just zero registered classes.
