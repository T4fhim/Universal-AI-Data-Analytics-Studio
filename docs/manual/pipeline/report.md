---
title: "Report Stage"
anchors:
  - pipeline.report
---

# Report Stage

Ninth of the ten guided-pipeline stages. Not part of the automatic stage-proposal sequence --
generating an export is an explicit user action, offered once every earlier stage has had a
chance to run, not something the guidance system pushes toward automatically.

This page displays a read-only view of what has actually been recorded for the active dataset
so far (which stages have run, and how many times), then re-opens the same
[Generate Report](../report/generate.md) dialog reachable from the Analysis menu -- it does not
duplicate that export logic itself, only surfaces "are you ready to export" before committing
to it.

**Next, typically:** [Reproduce](reproduce.md), if you later need to confirm the same pipeline
produces the same results against re-imported data.
