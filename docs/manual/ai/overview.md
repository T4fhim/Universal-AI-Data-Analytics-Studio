---
title: "The AI Assistant Layer"
anchors:
  - ai.overview
---

# The AI Assistant Layer

The chat panel (`uadas_core.ai.assistant_service.AssistantService`) is scoped narrowly: it can clean,
profile, and statistically analyze your currently active dataset -- nothing else. It has no
general web or knowledge-base access, and is instructed to say so plainly if asked something
outside that scope rather than guessing. Every stage of the guided pipeline is fully usable
with no AI provider configured at all -- see [Explain](../pipeline/explain.md) for the one
stage that specifically depends on it.

## Interpret, don't invent

The AI's role throughout this application is to **interpret an already-computed result**, not
to compute new numbers of its own. Every statistic in an `Explanation` (what a result is, why
it matters, how it was calculated, its confidence/uncertainty, its assumptions, alternative
approaches) already exists in the deterministic result it describes -- nothing in that
interpretation layer performs its own calculation.

## Tool calling

The assistant calls into the exact same functions the guided pipeline's own stage pages call
directly (`uadas_core.analysis`, `uadas_core.forecasting`, `uadas_core.cleaning`), via `uadas_core.ai.tool_registry` --
every tool is a thin wrapper with no assistant-specific bypass of any validation those functions
already enforce (column existence, type checks, minimum row counts). A cleaning tool never
mutates your active dataset: like every cleaning operation, it returns a new, derived dataset
and tells you so, rather than claiming to have modified your original data.

## Providers and BYOK (bring your own key)

Configure one or more provider profiles in [Settings](../settings.md)'s AI tab: **Anthropic**,
**Gemini**, **Groq**, or a local **Ollama** instance (which needs no API key at all). Each
profile names an environment variable holding its API key -- **no key is ever written to
`config.yaml`**; only the environment variable's *name* is stored, and the key itself is read
from your environment at the moment a provider is constructed.

**Provider rotation** lets you configure several profiles (for example, several Groq keys) and
have a rate-limit (HTTP 429) failure from the active one automatically advance to the next
rather than failing the whole conversation turn. Enable it in Settings; it is off by default.

## Expertise level

Six levels (`beginner`, `student`, `analyst`, `researcher`, `engineer`, `decision_maker`)
steer both the AI's register/depth and result-card density/vocabulary -- a beginner-level
result headline names a conclusion in plain language; an engineer-level headline is terser and
may reference the statistic directly. Changeable live from the chat panel, applied to the next
turn onward, without restarting the assistant.
