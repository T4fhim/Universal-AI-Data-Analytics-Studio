---
title: "Toggle Theme"
anchors:
  - view/theme
---

# Toggle Dark / Light Theme

**View > Toggle Theme**.

Switches between the dark and light theme and saves the choice immediately (unlike most
settings, this one action both applies and persists in a single click, rather than requiring a
separate Save in [Settings](../settings.md)).

A third theme, **high contrast**, exists for users who need it but is not part of this
toggle -- it is selected explicitly from the Theme dropdown in Settings, since cycling through
three states with one button would make "get back to the theme I actually want" less
predictable than a two-way toggle.

Every themed surface -- window chrome, docks, charts, icons -- recolors live; nothing requires
a restart. A chart already on screen is re-rendered in place via Plotly's own `relayout` rather
than being rebuilt from scratch.
