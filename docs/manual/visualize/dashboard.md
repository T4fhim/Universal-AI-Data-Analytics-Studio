---
title: "Create a Dashboard"
anchors:
  - visualize/dashboard
---

# Create a Dashboard

**Analysis > Create Dashboard**. Requires at least two open visualizations.

Combines the currently open visualizations into a single dashboard layout. Unlike a chart's own
column choices, a dashboard's real precondition ("at least two visualizations exist") is a
count, not a yes/no state -- so this action is enabled by a predicate that reads
`ActionContext.visualization_count` directly rather than a boolean `Requirement`.

Closing a dashboard, or a visualization it references, does not cascade: a dashboard tile can
end up pointing at a closed visualization, which is treated as expected, recoverable state
(the tile shows that it is no longer available) rather than an error condition the application
guards against. This matches how closing a dataset never cascades to charts or dashboards built
from it elsewhere in the workspace.
