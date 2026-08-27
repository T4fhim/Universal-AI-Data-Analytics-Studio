---
name: model-orchestration
description: Project-specific model-tier and resource-selection discipline for the orchestrating session on Universal AI Data Analytics Studio — which phase maps to which subagent/skill, when to escalate/de-escalate model tier, and the confidence gate before acting. Use when deciding whether to delegate to a subagent, which model tier a task warrants, or whether enough investigation has happened before writing code.
---

# Model & Resource Orchestration

This skill governs how the *orchestrating* session routes work in this repo — not how any
individual subagent behaves internally. Per-agent model tiers are already fixed in each
agent's frontmatter (`model: haiku|sonnet` in `.claude/agents/*.md`) and are not decided here;
this skill is about *which* agent/skill/model to reach for and when to change tier mid-task.

## Current agent tiers (already configured — reference, don't duplicate)

Read-only, single-pass agents run on `haiku`: `architect`, `code-reviewer`,
`security-reviewer`, `planner`. Action agents that write code and get worktree isolation run
on `sonnet`: `implementer`, `debugger`, `test-engineer`. Do not override these per-task —
if a specific task seems to need a stronger tier than an agent's configured default, that's a
signal to do the reasoning in the main session (or explicitly pass `model:` to the `Agent`
tool call) rather than to edit the agent's frontmatter.

## Phase → resource mapping for this repo

- **Discover/understand a milestone or bug**: read `SPECIFICATION.md` + `docs/ROADMAP.md`'s
  "not built yet" list before assuming a module exists — do this directly, not via a subagent,
  it's cheaper than a delegation round-trip for a few file reads.
- **Plan new feature/milestone work**: `planner` agent (always inspects actual `src/`, not just
  CLAUDE.md/SPECIFICATION.md, since spec scope outruns implementation).
- **Architecture-boundary question** (new service vs. method, `src/analysis` vs `src/services`,
  does a new reader/chart/op fit the existing `Base*` shape): `architect` agent — before
  implementing, not after.
- **Implement approved work**: `implementer` agent, or inline if it's a single-file,
  pattern-following change the architect/planner step already fully specified.
- **Bug/crash/failing test**: `debugger` agent — reproduce and root-cause before proposing a fix.
- **Any new `Base*` implementation, service, or milestone stage**: check `project-architecture`
  skill for the integration points (registry, config 3-place rule, bootstrap registration)
  *before* declaring the change complete, then `test-engineer` for coverage.
- **Chart/visualization work**: `dataviz-development` skill.
- **Qt/PySide6 widget, threading, or lifecycle work**: `pyside6-development` skill.
- **Before claiming any milestone/feature/fix complete**: `milestone-verification` skill —
  non-negotiable per that skill's own scope; this skill does not restate its checklist.
- **Review after non-trivial change**: `code-reviewer` (quality) and/or `security-reviewer`
  (only for `src/ai/`, `src/readers/`, `src/database/`, credential/network/filesystem code) —
  select the one relevant to what changed, not both by default.

## Confidence gate before writing code

Proceed only when reasonably confident (not just hopeful) that:
- the relevant source file(s) actually exist as assumed (check `src/`, don't trust
  `SPECIFICATION.md` as proof of existing functionality),
- the integration points listed in `project-architecture` for this change type are known,
  and
- the change is in scope for the milestone/task as stated.

If not, close the gap first — read more source, check `docs/ARCHITECTURE.md`, or delegate a
narrow `architect`/`planner` investigation — rather than proceeding on an assumption and
correcting later. This is a bar for whether the *next concrete action* is right, not a
license to over-investigate work that's already clear.

## Escalation / de-escalation signals

Escalate a task from inline/haiku-tier reasoning to `sonnet`-tier (implementer/debugger/
test-engineer, or unblocking the main session's own reasoning) when: the change touches
more than one `src/` subpackage, an unexpected failure appears mid-implementation, or
requirements turn out ambiguous once the actual code is read. De-escalate back to direct,
undelegated action once the ambiguous part is resolved and what remains is mechanical
(e.g. registering an already-designed reader in `reader_registry.py`).

For an ad hoc "which model for this task" question outside this repo's own phase mapping,
use the `ecc:model-route` skill rather than re-deriving general model-tier heuristics here.

## Scope boundary

This skill does NOT provide:

- generic Claude Code model-selection philosophy (that's `ecc:model-route`, or Claude Code's
  own defaults),
- disciplined development workflow (brainstorming, TDD, systematic debugging — use
  Superpowers),
- the actual architectural integration checklist (`project-architecture` skill) or milestone
  completion checklist (`milestone-verification` skill) — this skill routes to them, it
  doesn't duplicate them.

Use CLAUDE.md for the project's general architecture explanation. This skill exists
specifically so the orchestrating session has a repo-grounded answer to "which
agent/skill/tier handles this" instead of re-deriving it per task.
