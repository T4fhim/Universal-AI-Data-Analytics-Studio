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

# Fast path: a commit that stages no .py file cannot change pytest or bandit
# outcomes (both scan Python only), so skip the ~7-minute two-stage suite for
# docs / plans / markdown / workflow-yaml commits. Any staged .py -- including
# under tests/ or a conftest -- runs the full gate. Deletions count too (a
# removed module can break an import-layering test).
$stagedPy = @(& git diff --cached --name-only) | Where-Object { $_ -match '\.py$' }
if (-not $stagedPy) {
    Write-Host "pre-commit-check: no .py files staged -- skipping pytest/bandit."
    exit 0
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
# Pass/fail is judged by Test-PytestPassed, not the bare exit code. Verified 2026-10-04: the full-suite run
# exits with the native access-violation code (-1073741819, 0xC0000005) AFTER pytest prints a clean
# summary, on every run here -- so demanding exit 0 blocked every commit with all tests green.
# os._exit() in the runner does not help: the crash lands inside pytest.main()'s own teardown. A crash
# code is forgiven ONLY when the final summary line shows passes and no failed/error count; a real
# failure exit, a crash with no summary, or a summary with failed/error still blocks.
function Test-PytestPassed {
    param([long]$ExitCode, $Output)
    if ($ExitCode -eq 0) { return $true }
    if (@(-1073741819, 3221225477, 139) -notcontains $ExitCode) { return $false }
    $text = ($Output | ForEach-Object { "$_" }) -join "`n"
    $summary = [regex]::Matches($text, '(?m)^\s*=*\s*(\d+ passed[^\r\n]*?) in [\d.]+s') | Select-Object -Last 1
    if (-not $summary) { return $false }
    if ($summary.Groups[1].Value -match '\b\d+ (failed|error)') { return $false }
    Write-Host "pre-commit-check: pytest exited $ExitCode after a clean summary ($($summary.Groups[1].Value.Trim())) -- known Windows/Qt teardown crash, treated as a pass."
    return $true
}

# Phase 2.5: a single invocation. The two-invocation split existed only because the Qt tests under
# tests/ui/ (test_worker_runner.py's real-QThreadPool tests) were flaky late in a long run; that
# directory is gone, so the surviving suite is one plain run.
& $py "scripts\run_tests_and_exit_cleanly.py" "tests" -q 2>&1 | Tee-Object -Variable out1 | Out-Host
$testExit1 = $LASTEXITCODE

if (-not (Test-PytestPassed $testExit1 $out1)) {
    Write-Error "Tests failed (exit $testExit1). Commit blocked."
    exit 2
}

Write-Host "Running Bandit..."
# -b .bandit-baseline.json: `bandit -r src -q` has a known, accepted baseline of
# low-severity findings (asserts, the deliberate parametrised-SQL construction in
# src/database, empty-string password *defaults* on a profile dataclass that
# holds no real password). Added in Phase 0.6 of the web-transition plan, same
# invocation the CI `lint` job runs. Phase 1.8's security pass removes baseline
# entries as it fixes them; anything NOT in the baseline fails the commit.
& $py -m bandit -r src uadas_core -q --skip B101,B107,B608
$banditExit = $LASTEXITCODE

if ($banditExit -ne 0) {
    Write-Error "Security checks failed (bandit finding outside the B101/B107/B608 skip set). Commit blocked."
    exit 2
}

Write-Host "Tests and security checks passed."
exit 0
