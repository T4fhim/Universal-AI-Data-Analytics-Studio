---
title: "Upload"
anchors:
  - pipeline.upload
---

# Upload

The first of the ten pipeline stages, and the only one with no dedicated stage page -- there is
nothing to configure once you have a dataset, so it is represented by the **Welcome** page
(shown until a dataset is active) rather than a form. Use
[Open Dataset](../data/open-dataset.md) or [Connect to Database](../data/connect-database.md)
to complete it.

`PipelineStage.UPLOAD` exists in the pipeline enum for completeness and for the stage rail's
display (it is shown complete on the rail once any dataset is active), but it is never run
through `AnalysisOrchestratorService.run_stage` and is never proposed by the guidance system --
by the time a dataset exists for the orchestrator to reason about, uploading has already
happened.

Once a dataset is active, the workbench switches automatically from the Welcome page to the
next proposed stage -- normally [Understand](understand.md).
