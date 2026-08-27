---
title: "Reproduce"
anchors:
  - pipeline.reproduce
---

# Reproduce

Tenth and final stage of the guided pipeline. Like [Report](report.md), not part of the
automatic stage-proposal sequence -- reproduction is an explicit action, not something the
guidance system suggests on its own.

**Replay** re-runs every stage recorded in the active dataset's analysis log, in the original
order, via `AnalysisOrchestratorService.reproduce` -- including following the chain of derived
datasets a [Clean](clean.md)-stage entry may have produced, so a cleaning operation logged
against one dataset is re-applied to the correct one in the chain, not blindly to whichever
dataset happens to be active when Reproduce is clicked.

This is most useful after re-importing the same source data (a refreshed export of the same
report, for instance) to confirm the identical pipeline produces the same results -- the
Reproducible Analysis feature this whole guided pipeline is built to support: every step that
ran is a fact recorded in the log, not something you have to remember or redo by hand.
