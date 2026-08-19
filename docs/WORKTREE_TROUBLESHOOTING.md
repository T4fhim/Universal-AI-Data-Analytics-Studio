# Git worktree isolation: symptom, diagnosis, and recovery

Each implementer/architect agent dispatched by the coordinator runs inside its
own linked git worktree under `.claude/worktrees/agent-<id>/`, on its own
branch `worktree-agent-<id>`, so concurrent agents never collide on the same
working tree. This document exists because that mechanism has a real,
reproducible failure mode: an agent's worktree branch going stale relative to
the actual work branch (`feature/defining-features-milestones`), sometimes
badly enough that the worktree contains none of the milestone code at all.

## The exact symptom

An agent's worktree is checked out on `worktree-agent-<id>`, but that branch's
tip commit predates most or all of the milestone work on
`feature/defining-features-milestones`. Concretely, in the session that wrote
this document:

```
$ git log --oneline -5           # inside the worktree
53b36c9 chore: establish Claude Code development infrastructure
13dfc2d chore: configure Claude Code development environment
...

$ git log --oneline -5 feature/defining-features-milestones
c73e534 milestone 27: Empty/error state system + i18n scaffolding
83d77ac milestone 26: GuidanceService + progressive expertise
...

$ git merge-base HEAD feature/defining-features-milestones
53b36c92649fc6f56f2b8488c27a4a029ab1845a   # == the worktree's own stale HEAD
```

i.e. the worktree branch is a genuine ancestor of the work branch with zero
milestone commits applied -- not a divergent branch with conflicting work, an
*empty* one. `src/ui/workbench/`, `src/ui/controllers/`, `src/ui/results/`,
and every other package added by milestones 19-27 are simply absent from the
working tree. Any task description that assumes those packages exist (as
every remediation/verification task after M19 does) cannot be carried out
until this is fixed.

## Root cause

```
$ git for-each-ref --format='%(refname:short) %(objectname:short)' refs/heads/
feature/defining-features-milestones c73e534
main                                 6d8404e
worktree-agent-a4e8edc876dabd028     53b36c9
worktree-agent-a92d011e17aece3cb     53b36c9
worktree-agent-adbaa04725fed5afb     53b36c9

$ git reflog show worktree-agent-a92d011e17aece3cb
53b36c9 worktree-agent-a92d011e17aece3cb@{0}: branch: Created from origin/main
```

Every one of this session's sibling worktree branches was created from
**`origin/main`** at the same commit (`53b36c9`, timestamped 2026-08-16
11:11), not from the actual work branch. `feature/defining-features-milestones`
was already three days and twenty-plus milestone commits ahead
(`c73e534`, 2026-08-19 18:01) by the time this agent's worktree was reused for
a task that needed it. The worktree branch is never refreshed after its
initial creation -- if a worktree is created once and then reused (locked,
long-lived) across multiple coordinator dispatches spanning days of ongoing
milestone work on the real branch, it silently falls further and further
behind every time.

`.claude/worktrees/` itself is correctly excluded from version control via
the **shared repo's local, non-committed** `.git/info/exclude` (not
`.gitignore` -- appropriate, since worktree state is inherently per-machine,
not something to commit and share), so this is not a tracked-files problem;
it is purely a "which commit was this branch created from, and was it ever
moved forward" problem.

## Recovery: what has worked

An agent running *inside* the stale worktree is (correctly) sandboxed from
performing this recovery itself in most cases -- the environment's own
permission classifier blocked both `git reset --hard <target>` and
`git merge --ff-only <target>` run from inside the worktree during this
session's first few attempts, and only allowed a `git reset --hard` after the
Fact-Forcing Gate's required disclosure (destination commit, rollback
command, and the verbatim task instruction requiring that commit) was
presented in the same turn as the command. Treat that gate as intentional,
not a bug to route around -- it exists so a worktree-branch-changing
operation is never silent.

**The commands that succeeded, once the gate's disclosure requirement was
met, run from inside the affected worktree itself** (not the shared
checkout -- an agent's git operations are refused if they'd target the
shared checkout instead of its own worktree):

```powershell
# From inside .claude/worktrees/agent-<id>/, only after presenting:
#  1. files/data affected (branch ref move; clean working tree; old commits
#     stay reachable via reflog)
#  2. rollback command (git reset --hard <old-sha>)
#  3. the verbatim task instruction requiring the target commit
git status                                   # confirm clean before touching anything
git reset --hard feature/defining-features-milestones
```

If a clean-working-tree precondition is not met (uncommitted work exists in
the stale worktree), do **not** run `reset --hard` -- that would discard real
work. Escalate to the coordinator instead; the coordinator's own
`git worktree unlock` / `git worktree remove` / `git worktree prune` sequence
against the *shared* checkout is the safe path in that case (removes the
worktree's directory and its lock, prunes the stale administrative entry,
then a fresh worktree can be added from the correct branch/commit) and does
not risk destroying uncommitted changes silently the way a blind reset would.

## Preventive steps

1. **Prefer creating (or refreshing) an agent's worktree branch from the
   current work branch tip at dispatch time, not from `origin/main`.** This
   session's three stale sibling branches all trace back to `origin/main`
   specifically -- if worktree creation is scripted anywhere in the
   coordinator's tooling, that is the one line to check first.
2. **Treat a long-lived, reused, locked worktree as a staleness risk
   proportional to how long it has been idle relative to how fast the work
   branch is moving.** A worktree dispatched for a single milestone and then
   torn down cannot go stale in a way that matters; one kept locked across
   multiple days of milestone work can, as this session demonstrated.
3. **A cheap early check any agent can run for itself, before doing
   anything else, costs three commands and catches this immediately:**
   ```powershell
   git log --oneline -1                                    # this worktree's HEAD
   git log --oneline -1 feature/defining-features-milestones  # the real work branch
   git merge-base HEAD feature/defining-features-milestones   # should equal work branch HEAD if current
   ```
   If the merge-base equals this worktree's own HEAD (not the work branch's),
   the worktree is behind by exactly that much and needs the recovery above
   before any other task step is attempted -- this is precisely the check
   that surfaced the problem documented here, spending under a second of
   agent time to avoid silently working from (or, worse, silently reporting
   results against) the wrong tree.
