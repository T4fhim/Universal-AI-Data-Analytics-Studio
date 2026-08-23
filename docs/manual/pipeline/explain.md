---
title: "Explain"
anchors:
  - pipeline.explain
---

# Explain

Eighth stage of the guided pipeline. **Rationale:** every prior stage's result should be
interpreted in plain language before reporting -- this is the AI's role: interpret, not invent
new numbers.

Shows an `Explanation` -- a structured, plain-language account of a computed result (what it
is, why it matters, how it was calculated, its confidence/uncertainty, assumptions, and
alternative approaches) -- once an AI provider has generated one. See
[the AI layer](../ai/overview.md) for what "interpret, don't invent" means concretely: every
number in an `Explanation` already exists in the result it describes; the AI never computes a
new statistic on this page.

**Without a configured AI provider, this page's fields stay empty**, and say so plainly -- the
rest of the pipeline remains fully usable either way. This is a deliberate design point of the
whole application: no stage's *core* functionality depends on having an API key, only this
interpretive layer does.

**Next, typically:** [Report](report.md).
