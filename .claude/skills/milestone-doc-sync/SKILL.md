---
name: milestone-doc-sync
description: Claude-only background check that catches documentation/skill files describing this project's CURRENT tooling or test state going stale after a milestone changes that state. Run automatically at milestone completion, alongside milestone-verification.
user-invocable: false
---

# Milestone Doc Sync

This skill exists because the exact same staleness was found and hand-fixed twice in one session
(2026-09-01): `docs/ARCHITECTURE.md`'s "Important architectural constraints to preserve" section and
`.claude/skills/milestone-verification/SKILL.md`'s "Test Verification" section both asserted "no
test suite exists, tooling has no committed config" long after milestone 16 made that false — and
nothing caught the drift until an unrelated `/init` run noticed it. This skill turns that
noticing into a repeatable check instead of relying on it happening again incidentally.

## Scope boundary

This is NOT `milestone-verification` (that checks the milestone's own correctness/completeness) and
NOT `project-architecture` (that checks integration points for a new extension). This checks
whether *pre-existing documentation and skill files* still describe reality after this milestone
changed something they claim.

## When to run

Immediately after `milestone-verification` passes for a milestone that changed any of: test
coverage/structure, CI configuration, linting/formatting/type-checking configuration, build
tooling, or the set of empty/unbuilt `src/` subpackages. Skip for milestones that only add
application features without touching tooling/test/build state.

## What to check

Grep the following files for claims a just-landed change may have falsified — specifically claims
about *current state* (a test suite existing or not, a subpackage being empty or not, tooling being
configured or not), not architectural design decisions (those don't drift the same way a "here's
what currently exists" claim does):

1. `docs/ARCHITECTURE.md` — especially its "Important architectural constraints to preserve"
   section.
2. `.claude/skills/milestone-verification/SKILL.md` — especially its "Test Verification" section.
3. `docs/ROADMAP.md` — especially "What is explicitly not built yet".
4. `CLAUDE.md` — especially the "Commands" section (tool versions, hook behavior, test invocation).

For each, ask: does anything in this file describe a state (tests exist/don't, tooling
configured/not, a subpackage empty/built) that this milestone just changed? If yes, that file is
now stale.

## What to do when something is stale

- **CLAUDE.md**: fix directly — it's not a staged-review skill, it's the project's own
  root-level doc.
- **docs/*.md**: fix directly — same reasoning; these are plain documentation, not skills subject to
  a staging/approval workflow.
- **A skill file under `.claude/skills/`**: do NOT edit it live. Stage a corrected copy (see that
  skill's own rules, or `references/skill-authoring.md`-equivalent guidance if the skill defines
  one) and tell the user what changed and where the staged copy is, exactly as was done for
  `milestone-verification` — see `~/.claude/skill-updates/milestone-verification/NOTES.md` for the
  precedent this skill is modeled on.

## Output

One line per file checked: either "no stale claims found" or "stale: <what it claimed> vs <what is
now true>, fixed directly / staged at <path>". Do not silently skip a file because it "probably
hasn't changed" — the whole point is that assumption is what let this drift happen twice already.
