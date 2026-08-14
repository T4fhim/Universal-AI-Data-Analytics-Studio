$ErrorActionPreference = "Continue"

Set-Location $env:CLAUDE_PROJECT_DIR

Write-Host "Running pytest..."
& ".\.venv\Scripts\python.exe" -m pytest

if ($LASTEXITCODE -ne 0) {
    Write-Error "Tests failed. Commit blocked."
    exit 2
}

Write-Host "Running Bandit..."
& ".\.venv\Scripts\python.exe" -m bandit -r src -q

if ($LASTEXITCODE -ne 0) {
    Write-Error "Security checks failed. Commit blocked."
    exit 2
}

Write-Host "Tests and security checks passed."
exit 0