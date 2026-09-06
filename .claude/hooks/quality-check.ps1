$ErrorActionPreference = "Continue"

# Only act on Python files.
$inputJson = [Console]::In.ReadToEnd()

try {
    $event = $inputJson | ConvertFrom-Json
} catch {
    exit 0
}

$filePath = $event.tool_input.file_path

if (-not $filePath -or -not $filePath.EndsWith(".py")) {
    exit 0
}

# Make sure we're operating from the project root.
Set-Location $env:CLAUDE_PROJECT_DIR

# Fix import order first (isort remains the tool of record for import sorting per
# pyproject.toml's [tool.isort] section and its own comment on why ruff's "I" rule
# group is deliberately not enabled -- this was previously only *checked* in CI,
# never auto-fixed on save, leaving isort violations to surface only at commit/CI
# time). Runs before the formatter so import-order fixes don't fight with
# whitespace/formatting fixes applied after it, matching the standard isort-then-
# formatter ordering.
& ".\.venv\Scripts\isort.exe" $filePath

# Format the file with BLACK, not `ruff format`. black is the formatter of record
# (pyproject.toml [tool.black]) and the one CI's `black --check` and
# .pre-commit-config.yaml actually gate on. ruff-format and black are not always
# byte-identical, so running `ruff format` here would let every on-save pass
# silently flip a file between the two styles depending on which tool touched it
# last -- and then fail CI's black check. Fixed in Phase 0.6 of the web-transition
# plan; .pre-commit-config.yaml's own header comment documents the same conflict.
& ".\.venv\Scripts\black.exe" $filePath

# Lint/fix safe issues (ruff's non-formatting rules only -- the selected groups in
# pyproject.toml [tool.ruff.lint], not "I" and not `ruff format`).
& ".\.venv\Scripts\ruff.exe" check $filePath --fix

exit 0
