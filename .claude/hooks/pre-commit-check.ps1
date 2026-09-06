$ErrorActionPreference = "Continue"

# Repo root resolution. This used to be a bare `Set-Location
# $env:CLAUDE_PROJECT_DIR`, which silently no-ops when that variable is not
# populated in the hook's environment (observed 2026-09-06: some Claude Code
# hosts do not export it to PreToolUse hooks). When that happened the script
# stayed in an arbitrary cwd, every `.\.venv\Scripts\python.exe` call failed to
# launch, `$LASTEXITCODE` kept a stale 0, and the hook printed "passed" and
# exited 0 -- a commit gate that was not gating anything. Resolve from the
# script's own location instead (this file is at <repo>\.claude\hooks\), and
# fall back to CLAUDE_PROJECT_DIR only if that somehow fails.
$repoRoot = try { (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path } catch { $env:CLAUDE_PROJECT_DIR }
if (-not $repoRoot -or -not (Test-Path $repoRoot)) {
    Write-Error "pre-commit-check: could not resolve the repository root. Commit blocked."
    exit 2
}
Set-Location $repoRoot

$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "pre-commit-check: $py not found (no .venv?). Commit blocked rather than skipped silently."
    exit 2
}

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
& $py "scripts\run_tests_and_exit_cleanly.py" "tests\ui\test_worker_runner.py" -q
$testExit1 = $LASTEXITCODE
& $py "scripts\run_tests_and_exit_cleanly.py" "tests" -q -m "not uia_integration" --ignore="tests\ui\test_worker_runner.py"
$testExit2 = $LASTEXITCODE

if ($testExit1 -ne 0 -or $testExit2 -ne 0) {
    Write-Error "Tests failed (exit $testExit1 / $testExit2). Commit blocked."
    exit 2
}

Write-Host "Running Bandit..."
# -b .bandit-baseline.json: `bandit -r src -q` has a known, accepted baseline of
# low-severity findings (asserts, the deliberate parametrised-SQL construction in
# src/database, empty-string password *defaults* on a profile dataclass that
# holds no real password). Added in Phase 0.6 of the web-transition plan, same
# invocation the CI `lint` job runs. Phase 1.8's security pass removes baseline
# entries as it fixes them; anything NOT in the baseline fails the commit.
& $py -m bandit -r src -q -b ".bandit-baseline.json"
$banditExit = $LASTEXITCODE

if ($banditExit -ne 0) {
    Write-Error "Security checks failed (new bandit finding not in .bandit-baseline.json). Commit blocked."
    exit 2
}

Write-Host "Tests and security checks passed."
exit 0
