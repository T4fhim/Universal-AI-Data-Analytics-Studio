$ErrorActionPreference = "Continue"

Set-Location $env:CLAUDE_PROJECT_DIR

Write-Host "Running pytest..."
# NOT a bare `python -m pytest`: verified directly (2026-09-01) that this exact bare
# invocation can report a fully clean pytest summary (e.g. "1384 passed, 103 skipped,
# 0 failed") and STILL exit non-zero -- a real Windows CPython/Qt interpreter-shutdown
# crash occurring after pytest's own result is already known, previously believed to be
# CI-only (see .github/workflows/ci.yml's own comment) but reproduced locally here too.
# scripts/run_tests_and_exit_cleanly.py (os._exit() once pytest's real result is known)
# is CI's actual fix for this and CLAUDE.md's documented command -- this hook had never
# been updated to match, so it could spuriously block a commit with all tests passing.
# Same two-invocation split as CI: tests/ui/test_worker_runner.py first (real-QThreadPool
# tests proved flaky once event-loop backpressure builds up later in a long run).
& ".\.venv\Scripts\python.exe" "scripts\run_tests_and_exit_cleanly.py" "tests\ui\test_worker_runner.py" -q
$testExit1 = $LASTEXITCODE
& ".\.venv\Scripts\python.exe" "scripts\run_tests_and_exit_cleanly.py" "tests" -q -m "not uia_integration" --ignore="tests\ui\test_worker_runner.py"
$testExit2 = $LASTEXITCODE

if ($testExit1 -ne 0 -or $testExit2 -ne 0) {
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
