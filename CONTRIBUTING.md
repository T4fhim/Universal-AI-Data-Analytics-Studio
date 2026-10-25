# Contributing

Thanks for your interest in Universal AI Data Analytics Studio.

## Licence

This project is licensed under **AGPL-3.0-or-later** (see [LICENSE](LICENSE)). By
contributing, you agree that your contributions are licensed under the same terms.

The AGPL's network-use clause is deliberate: anyone running a modified version as a
hosted service must make their modified source available to its users. This keeps a
self-hostable, forkable project from being turned into a closed hosted product.

## Developer Certificate of Origin (DCO)

Every commit must be signed off. The sign-off certifies that you wrote the change or
otherwise have the right to submit it under the project licence — the full text is the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).

Add the trailer automatically with `-s`:

```bash
git commit -s -m "your message"
```

This appends a line like:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and email must match your commit author identity (`git config user.name` /
`git config user.email`). To sign off a branch of commits you already made:

```bash
git rebase --exec 'git commit --amend --no-edit -s' <base>
```

CI runs a `dco` check on every pull request. It has been **enforcing** since Phase 2 of the
web transition: a commit introduced by the PR without a matching `Signed-off-by:` trailer
fails the build. Commits that predate the policy were not rewritten and are not re-flagged.

> A CLA (a signed contributor agreement, e.g. via CLA Assistant) is the stronger option
> if commercial dual-licensing becomes a near-term intent — see
> `plans/web-transition-glass-box-studio.md` Phase 0.8. DCO is the current choice: no
> paperwork, enforced entirely by the trailer + the CI check.

## Development setup

Python 3.13. A `.venv` is expected at the repo root.

```bash
python -m venv .venv
.venv/Scripts/Activate.ps1        # PowerShell;  source .venv/bin/activate on POSIX
pip install -r requirements.txt   # or: uv sync   (uv.lock is committed)
pip install -e .                  # editable install of the `uadas_core` package

pre-commit install                # activates the tool-agnostic commit hooks
```

There is no application to run: the PySide6 desktop shell and `main.py` were removed in
Phase 2.5, and the web UI arrives in Phase 4. The repository is the Qt-free core
(`uadas_core/`) plus its tests, so `python -m pytest tests -q` is the way to exercise a change.
Full commands (tests, formatters, linters, types) are in [CLAUDE.md](CLAUDE.md#commands).

## Before you open a pull request

- `black --check uadas_core/ tests/ scripts/` and `isort --check-only uadas_core/ tests/ scripts/`
  are clean.
- `ruff check uadas_core/ tests/`, `bandit -r uadas_core -q --skip B101,B107,B608` and
  `lint-imports` are clean (CI's `lint` job gates these).
- The test suite passes — exactly what CI runs: `python -m pytest tests -q`.
- Every commit is signed off (`git commit -s`).
- New modules follow the conventions in [CLAUDE.md](CLAUDE.md#conventions-to-follow):
  a `# File: <path>` first line, a rationale-focused module docstring,
  `from __future__ import annotations`, type hints throughout.
