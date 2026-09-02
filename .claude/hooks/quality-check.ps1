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
# time). Runs before ruff format/check so import-order fixes don't fight with
# whitespace/formatting fixes applied after it, matching the standard isort-then-
# formatter ordering.
& ".\.venv\Scripts\isort.exe" $filePath

# Format the file.
& ".\.venv\Scripts\ruff.exe" format $filePath

# Lint/fix safe issues.
& ".\.venv\Scripts\ruff.exe" check $filePath --fix

exit 0
