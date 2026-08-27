---
title: "Settings"
anchors:
  - settings
---

# Settings

**File > Settings...**, or **Ctrl+,**.

Edits `config.yaml` through a typed, validated form (`src.services.settings_service.
SettingsService`) rather than by hand. Changes take effect immediately in memory as you make
them, but are only written to disk when you click **Save** -- **Cancel** discards everything
changed during this dialog session and reloads whatever is currently on disk.

## General tab

- **Theme** -- dark, light, or high-contrast. See [Toggle Theme](view/theme.md) for the
  quick-toggle shortcut, which switches between dark and light only.
- **Autosave** -- enable/disable, and the interval in minutes. See [Save Project](project/save.md)
  for what autosave does and does not do (in particular: it never prompts for a filename).
- **Reduce motion** / **Base font size** -- accessibility settings applied live, and at every
  future startup.
- **Show the first-run tour again** -- resets the one-time onboarding tour so it reappears the
  next time the application starts, in case you dismissed it before reading it.

## AI tab

Configure one or more LLM provider profiles (Anthropic, Gemini, Groq, or a local Ollama
instance), whether to fail over between them on a rate-limit error, whether the assistant is
enabled at all, and the expertise level that controls how results and explanations are phrased.
See [the AI layer](ai/overview.md) for what each of these controls actually changes.

## Plugins tab

Lists discovered plugins (readers, cleaning operations, and chart types a plugin provides),
each with an enable/disable toggle and any load error recorded for it. See
[the plugin system](plugins/overview.md).
