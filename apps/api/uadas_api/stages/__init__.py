# File: apps/api/uadas_api/stages/__init__.py
"""The pipeline-stage layer of the API (Phase 3.6): catalog, execution, result serialization.

Not a Django app. It adapts the core's registries -- ``uadas_core.ai.tool_registry`` (the one
registry the AI assistant *and* the guided orchestrator already dispatch through), the chart
registry and the result-renderer registry -- to the web: ``catalog`` lists what each
``PipelineStage`` can run, ``execute`` runs one operation on a pandas frame (pure, Django-free),
``serialize`` turns the core's result sections into JSON, ``run`` is the ``run_operation`` job
handler that loads a frame from storage and persists the outcome, ``frames`` reads Parquet frames
lazily.
"""

from __future__ import annotations

from uadas_api.web.runtime import headless_plotting_defaults

# Before anything below (or the core's analysis stack) imports matplotlib: see the function.
headless_plotting_defaults()
