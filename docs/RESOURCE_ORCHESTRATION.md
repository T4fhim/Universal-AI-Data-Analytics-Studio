# Resource Orchestration

**Read this every session, alongside `CLAUDE.md`.** It is the standing doctrine for *how* work
gets done on this project across the whole 7-phase desktop→web transition — which agent / skill /
model tier / MCP / tool for which kind of work, the delegation rules, and the hooks that already
run so you don't redo them. It does not restate architecture (that's `CLAUDE.md`) or per-task
tiering (that's the `model-orchestration` skill).

Plugin baseline: **`ecc/2.2.0`**. If an agent named below no longer resolves, the plugin cache
moved — treat routing as degraded until re-checked.

---

## §0 — How this composes with the other standing files

| File | Owns |
|---|---|
| `CLAUDE.md` | Architecture facts, conventions, the hook list, "what exists vs. not built yet". |
| `resource-router` (machine skill) | Machine-global meta: the workflow-skill decision table, "don't re-verify what a hook already runs", the caveman/cavecrew family. |
| `model-orchestration` (repo skill) | Per-*task* agent/tier: which of architect / planner / implementer / debugger / reviewer, when to escalate or de-escalate, the confidence gate before writing code. |
| **`docs/RESOURCE_ORCHESTRATION.md` (this)** | The project *arc*: phase → resources, the standing delegation & hook rules, the living-truth discipline, the condensed catalog. Points into the per-phase plan docs for detail. |

Precedence when two disagree: `CLAUDE.md` facts > this doctrine's rules > `model-orchestration`
tiering > `resource-router` defaults. The more specific and more recently verified statement wins.

---

## §1 — Standing delegation rules (phase-agnostic)

1. **Split delegation by what it adds.** A *writer* subagent duplicates the orchestrator's
   context — high cost, ~zero information added, and its diff must then be re-read to review. A
   *reviewer / scoper / investigator* subagent complements it: its value is that it does **not**
   share context — that is the Control A3 anti-hallucination mechanism. "Use every resource" and
   "stay in budget" therefore point the **same way**: maximize breadth of read-only specialists,
   minimize the count of writer subagents.
2. **Implement inline when the work is serial or single-file-mechanical.** No parallelism for a
   subagent to exploit; a cold-context round-trip buys nothing.
3. **`implementer` + worktree only for greenfield or abortable work.** Worktree isolation earns
   its keep when a step can be told to stop mid-way (Control A7 forbids the tidying rebase on a
   shared branch, so an inline abort leaves a dirty shared tree).
4. **Batch read-only work.** One opus `ecc:architect` pass for a cluster of interacting rulings,
   not four separate calls. Fire mutually-independent items as one parallel batch
   (`superpowers:dispatching-parallel-agents`). Never re-dispatch a reviewer against unchanged
   code.
5. **Hard budget rule.** Inside a per-commit cycle, the only subagent is the single per-commit
   `code-reviewer`. Heavier specialists (`ecc:python-reviewer`, `silent-failure-hunter`,
   `type-design-analyzer`, …) run at sub-step boundaries. This is what stops rate-limit
   exhaustion from stranding a half-done branch (the Phase-1.2 implementer already died this way).
6. **Every delegation prompt carries verified `file:line` facts inline.** Never hand a specialist
   a doc pointer as its primary context — the design docs cite pre-1.1 `src/` paths, and a
   review that finds nothing because it was pointed at empty air reads exactly like a clean
   review.
7. **Compress high-volume subagent returns.** When a read-only specialist's output will be long
   — a full-range review, a fixture enumeration, a whole-phase diagnosis sweep — end its prompt
   with *"report back caveman-compressed (`caveman` full/ultra): one line per finding —
   `file:line` · claim · fix. No prose, no preamble."* The compressed tool-result re-injected
   into the orchestrator is ~60% smaller, which is what keeps a long multi-stage run inside the
   token budget. Use `cavecrew-investigator` / `cavecrew-reviewer` (return is caveman by
   construction) for locate / diff-review delegations. **Never compress** code being written, a
   commit message the user will read, or the final user-facing summary — compression is for
   agent→orchestrator hops only.
8. **graphify-first for structure, grep for fields.** Once `graphify-out/graph.json` exists,
   open any "what connects / calls / imports X" question with `graphify query|path|explain`
   (cheaper than a fan-out `Explore`). Drop to `Grep` only for dataclass **field**-level reads
   (`parent_dataset_id`, `derivation_description` — graphify's Python AST layer does not track
   field access) or to edit specific lines. Re-run `graphify update .` (AST-only, 0 tokens)
   after a sub-step lands code; a full semantic rebuild only when plan/doc `.md` churn matters.

---

## §2 — Standing hook & environment awareness (runs automatically — do not redo)

- **`quality-check.ps1`** (PostToolUse, `.py` only): `isort` → `black` → `ruff check --fix` on
  every Edit/Write. **Never re-run those formatters by hand.** Quirk: it strips an import added
  in one Edit before the Edit that first *uses* it lands — so **add an import and its first use
  in the same Edit** (observation 0021).
- **`protect-files.ps1`** (PreToolUse Edit/Write): blocks `.env*`, `secrets.json`,
  `credentials.json`, `*.pem`, `*.key`. A block means route the change elsewhere (document the
  env var), not fight it.
- **`pre-commit-check.ps1`** (PreToolUse commit): two-stage `pytest` + `bandit`, blocks on
  failure. Matcher is `"Bash|PowerShell"`; it fast-exits when no `.py` file is staged. **A
  hook-config change needs a session reload to take effect** (observation 0019) — until then,
  run `scripts/run_tests_and_exit_cleanly.py` manually before a `.py` commit. Once live it *is*
  the "one suite run per commit" evidence — don't also run pytest by hand right before the
  commit.
- **ECC `gateguard-fact-force`** (PreToolUse Edit/Write): the fact-forcing gate — state
  callers / affected API / data shape / the verbatim user instruction before an edit. Keep it on
  for risky edits; relax per-session with
  `ECC_DISABLED_HOOKS=pre:edit-write:gateguard-fact-force` only for a genuinely mechanical batch
  (observation 0015). It also blocks destructive `git` commands even with facts — route recovery
  through scratchpad `subprocess` git calls.
- **`graphify hook-guard`** (global, PreToolUse Bash/Grep/Read): advisory nudges, inert until
  `graphify-out/graph.json` exists; building the graph activates them (never blocking). Once the
  graph exists, answer codebase-structure questions with `graphify query / path / explain`
  before grep.
- **`task-observer`** (SessionStart): active. Scan `~/.claude/skill-observations/observation-log/`
  frontmatter at session start; report the ids logged this session at each task boundary.
- **`gh`**: at `C:\Program Files\GitHub CLI\gh.exe`, **not on the Bash tool's PATH** — call it
  by full path, or via the PowerShell tool. Authenticated as `T4fhim`. This is how CI status is
  checked (`gh run list --branch <b>`, `gh run view <id>`).
- **`0xC0000005` note:** a non-zero exit from `scripts/run_tests_and_exit_cleanly.py` on the
  *second* invocation is the expected Windows Qt-shutdown access violation *after* a clean
  `pytest` result — CI-green-equivalent. Any Bash-capable subagent must be told this or it
  reports a passing suite as failed.
- **CI** (`.github/workflows/ci.yml`): `test` (Windows, full pytest), `lint`
  (ruff / black / isort / bandit / `lint-imports`), `dco` (advisory, `DCO_ENFORCING=0`),
  `uia_integration` (separate), and the Linux `import uadas_core` runtime job. `bandit` runs
  `--skip B101,B107,B608` — **B608 (SQL-injection) detection is OFF**, so a new SQL-building
  module has *no automated* injection gate; a directed manual security review is the only one.
- **MCP auth:** `context7` / `playwright` / `chrome-devtools` / `skillspector` need none;
  `vercel` needs OAuth (Phase 6); the `github` MCP is not required — `gh` covers it.

---

## §3 — Living-truth discipline

Plans and design docs in this repo lag the tree. Before acting on any claim in a plan/doc:

- **Re-verify `file:line` citations against the current tree** — the `plans/phase-1-6-*` and
  `phase-1-7-*` docs cite pre-1.1 `src/` paths throughout.
- **Re-verify counts against reality, not a hard-coded number** — the golden baseline is a
  *rolling* number (currently **1413 / 92 / 0**), tracked in `plans/phase-1-baseline.md`.
- **Re-verify branch / merge state against `origin/*` after a fetch**, never local refs
  (observation 0014).
- **Re-verify a "tool passes / is clean" claim by running the tool** — never inherit it from a
  PR body or a prior doc (observation 0016).
- **Check CI actually *ran* a step** — a step whose tool isn't installed in its job exits 127
  and looks like a config error, not a failure (observation 0022 — this hid a red `lint` job for
  a whole phase).

---

## §4 — Condensed resource catalog

**Repo subagents** (`.claude/agents/`): `planner`, `architect`, `code-reviewer`,
`security-reviewer`, `performance-analyzer`, `a11y-reviewer` — haiku, read-only.
`implementer`, `debugger`, `test-engineer` — sonnet, worktree isolation.

**ECC agents worth reaching for on Python-core work** (`ecc/2.2.0`): `python-reviewer`,
`architect` (opus — for open design questions), `type-design-analyzer`, `silent-failure-hunter`,
`comment-analyzer` (haiku), `security-reviewer`, `code-explorer`, `pr-test-analyzer`,
`doc-updater`, `docs-lookup` (Context7-backed).
**Phase 3 (Django):** `django-reviewer`, `django-build-resolver`, `database-reviewer`,
`fastapi-reviewer` (≈ Django Ninja — Pydantic + OpenAPI).
**Phase 4 (React):** `react-reviewer`, `react-build-resolver` (covers Vite), `typescript-reviewer`,
`a11y-architect`, `e2e-runner`, `gan-planner` / `gan-generator` / `gan-evaluator`.

**Workflow skills** (machine-global, stable path, editable): `safe-refactor` (behaviour-
preserving structural change — the Phase-1/2 primary), `surgical-patch` (narrowest bugfix),
`migration` (reversible schema / API / config transitions — Phase 3), `lean-build` (scope fence
+ explicit stop condition — any greenfield slice), `verify-and-stop` /
`superpowers:verification-before-completion` (completion proof), `investigate-first` →
`superpowers:systematic-debugging` (ambiguous failures), `graphify` (blast-radius),
`dev-resource-map` (current 2026 tooling — consult at Phase 3 and Phase 4 kickoff).
**Repo skills:** `add-extension`, `project-architecture`, `pyside6-development`,
`dataviz-development`, `milestone-verification`, `milestone-doc-sync`, `model-orchestration`.
**Volatile (plugin cache — do NOT hand-edit):** every `superpowers:*` and `ecc:*` skill.

**Ceremony — exclude by default:** `ecc:code-simplifier` / `ecc:refactor-cleaner` inside any
behaviour-frozen step (they propose exactly the changes the freeze forbids — they *do* belong in
Phase 2, which is deletion work); `ecc:spec-miner` when specs already exist as docs;
`a11y-reviewer` / `performance-analyzer` when nothing visual or data-volume changed; the
`caveman-*` family unless the user asks for compressed output; the ~40 other-language / domain
ECC agents (rust / go / swift / kotlin / homelab / marketing / …) — never for this project.

---

## §5 — Phase map

The detailed resource section for a phase is written **at that phase's kickoff**, when its code
is real. Phase 1's detail lives in `plans/phase-1-resource-plan.md`.

| Phase | Nature | Primary skills | Specialist agents | Comes online | Not this phase |
|---|---|---|---|---|---|
| **0** ground truth | done | — | — | CI, `gh` | — |
| **1** extract `uadas_core/` | refactor (frozen) + 2 additive subsystems | `safe-refactor`, `surgical-patch`, `migration`, `lean-build`, TDD, `milestone-verification` | `architect` (+opus), `code-reviewer`, `python-reviewer`, `type-design-analyzer`, `silent-failure-hunter`, `security-reviewer`, `code-explorer`, `test-engineer`, `implementer` (1.6/1.7) | graphify graph; Linux CI job | Django, React, any UI redesign |
| **2** retire desktop UI | deletion + shell collapse | `safe-refactor`, `lean-build`, `milestone-doc-sync` | `architect`, `code-reviewer`, `refactor-cleaner` (now appropriate), `code-explorer` | — | new features |
| **3** Django backend | greenfield API over `uadas_core/` | `migration`, `ecc:django-*`, `contract-first`, `api-design`, `dev-resource-map` | `django-reviewer`, `django-build-resolver`, `database-reviewer`, `fastapi-reviewer`, `architect` (opus), `security-reviewer` | `context7` / `docs-lookup`; `django` + `ninja` installed | React, glass-box UI |
| **4** React frontend | greenfield SPA — first runnable web app | `frontend-design`, `ecc:react-*`, `vite-patterns`, `dev-resource-map` | `react-reviewer`, `react-build-resolver`, `typescript-reviewer`, `a11y-architect`, `e2e-runner`, `gan-*` | `playwright` + `chrome-devtools` MCP; pnpm; `apps/web/` | Phase-5 differentiators |
| **5** glass-box | the differentiators (provenance UI, explainability, eval) | `mlflow:*` (AI-assistant eval), `lean-build` | `mle-reviewer`, `rag-pipeline-reviewer` (if RAG), `architect` (opus), `agent-evaluator` | mlflow tracing | polish / marketing |
| **6** ship | packaging, deploy, launch | `opensource-pipeline` (if public), `vercel:*` | `deployment-expert` | `vercel` MCP (OAuth) | — |
| **later** | maintenance / iteration | per-task via `model-orchestration` | as needed | — | — |

---

## §6 — Phase 2 (next; planning drafted, execution gated on user go-ahead)

**Phase 1 is DONE** — merged to `main` 2026-09-10 as merge commit `4d61b93` (PR #3, 71 commits,
merge-not-squash). Final rolling baseline **1542 / 92 / 0**. `DCO_ENFORCING=1` since this merge.
Phase 1 detail is retained in `plans/phase-1-*` for reference; the whole-branch diagnosis's
deferred items (D1–D15) are dispositioned in `plans/phase-1-diagnosis.md` §findings — Phase 2
owns D1 / D2 / D4 / D5 / D6.

- **De-risking controls (A1–A11, R2.1–R2.6, per-risk A–D, DoD):** `plans/phase-2-derisking-and-readiness.md`
- **Execution loop + per-step gates:** `plans/phase-2-execution-playbook.md`
- **Per-sub-step resource matrix + corrected facts:** `plans/phase-2-resource-plan.md`
- **Pre-Phase-2 baseline:** captured 2026-09-10 on `main` @ `4d61b93` — **1542 / 92 / 0**;
  `plans/phase-2-baseline.md` to be written at branch cut.
- **State ledger:** `.superpowers/sdd/phase-2/progress.md` (created at branch cut).

Phase 2 = **retire the desktop UI**: 2.0 scope lock (`ecc:code-explorer` inventory +
`ecc:architect` structural rulings + CI-transformation design) → 2.1 lift the 8 Qt-free
stranded modules (D5) → 2.2 extract `uadas_core/models/` (D1, cuts the `services↔ai` cycle) →
2.3 top-level `bootstrap.py` + `layers` contract (D2) → 2.4 mine remaining assets to committed
data files → 2.5 `git rm` `src/ui/` + `tests/ui/` + Qt entry paths + Qt deps → 2.6 CI
transformation (Linux single-invocation `test` job; delete `run_tests_and_exit_cleanly.py`) →
2.7 D4 persistence-atomicity follow-up (optional) → 2.8 doc + `.claude/` tooling sync → one PR
`phase-2/retire-desktop-ui → main`. `ecc:refactor-cleaner` / `ecc:code-simplifier` are
**in-scope** now (deletion work). Screenshot parity retires at 2.5 (no runnable app until
Phase 4 — deliberate, A11).

---

## §7 — Maintenance

Update this doc at every phase boundary (`milestone-doc-sync`). Bump the `ecc/2.2.0` line when
the plugin cache changes. Keep it short enough to reread each session — detail belongs in the
per-phase plan docs, not here.
