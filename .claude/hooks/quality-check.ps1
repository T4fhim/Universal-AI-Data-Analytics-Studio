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

# Format the file.
& ".\.venv\Scripts\ruff.exe" format $filePath

# Lint/fix safe issues.
& ".\.venv\Scripts\ruff.exe" check $filePath --fix

exit 0