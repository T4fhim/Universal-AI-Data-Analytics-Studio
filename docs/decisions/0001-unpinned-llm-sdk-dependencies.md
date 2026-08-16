# 0001 — LLM SDK dependencies (anthropic, openai, google-genai) remain unpinned

## Status

Accepted.

## Context

Phase 5's code review flagged (MEDIUM) that `anthropic`, `openai`, and
`google-genai` were added to `requirements.txt` with no version
constraint, and that these three packages sit directly on the
credential-handling path (`AnthropicProvider`, `GroqProvider`, and
`GeminiProvider` in `src/ai/llm_provider.py` all take a raw API key at
construction). The concern: an unpinned dependency can silently pull a
compromised or breaking release on the next `pip install -r
requirements.txt`.

Before deciding, `requirements.txt` was inspected directly: of its 55
lines, only 2 are version-pinned — `ruff==0.16.3` and `bandit==1.9.4`.
Every other dependency, including packages at least as consequential
as the three LLM SDKs (`sqlalchemy`, `prophet`, `pandas`, `pymupdf`,
`opencv-python`, and so on), is unpinned. `pyproject.toml` records no
stated dependency-pinning policy anywhere, and no prior decision
record exists on this topic (`docs/decisions/` was empty before this
file).

## Decision

Leave `anthropic`, `openai`, and `google-genai` unpinned in
`requirements.txt`, matching every other runtime application
dependency in the file.

The observed convention in this project is not "pin nothing" or "pin
everything security-sensitive" — it is specifically: pin the tools
that are invoked *automatically, outside a human's direct control* by
the project's own automation (`ruff`/`bandit`, run on every Edit/Write
and every `git commit` via `.claude/hooks/`), and leave application
runtime dependencies — however consequential — unpinned. Carving out
just these three SDKs from that pattern would be an inconsistent,
one-off exception applied only because they happen to be the most
recently added dependencies, not because they are meaningfully
different in kind from `sqlalchemy` or `pymupdf`, which handle
similarly sensitive inputs (arbitrary SQL connections, arbitrary
user-supplied files) and are equally unpinned today.

If this project later adopts a general dependency-pinning policy (e.g.
a lockfile, `pip-compile`, or a blanket pin-everything rule), these
three should be pinned as part of that broader change, not ahead of
it in isolation.

## Consequences

- A future `pip install -r requirements.txt` can pull a newer
  `anthropic`/`openai`/`google-genai` release without warning, same as
  it already can for every other dependency in this file.
- No `.venv` change was made as a result of this decision — the
  versions already installed during Work Item 0 (this session) remain
  as installed.
- This is explicitly a "consistent with existing convention" choice,
  not a claim that the convention itself is ideal — a future,
  separately-scoped decision could revisit pinning strategy for the
  whole file.
