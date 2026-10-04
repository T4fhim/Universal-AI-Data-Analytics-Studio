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
# Plain pytest. Until Phase 2.5 this gate ran scripts/run_tests_and_exit_cleanly.py and then
# judged the run by its summary line, because a Windows/Qt interpreter-shutdown crash
# (0xC0000005, after pytest had already printed a clean summary) made a fully green suite exit
# non-zero. Qt is gone with the desktop shell; verified 2026-10-04 that a bare run exits 0
# (868 passed). If a non-zero exit with a clean summary ever returns, investigate it rather than
# forgive it -- that is a real regression, not the old crash.
& $py -m pytest tests -q -p no:cacheprovider
$testExit1 = $LASTEXITCODE

if ($testExit1 -ne 0) {
    Write-Error "Tests failed (exit $testExit1). Commit blocked."
    exit 2
}

Write-Host "Running Bandit..."
# Same invocation as the CI `lint` job. `bandit -r uadas_core` has a known, accepted set of findings
# (asserts; the deliberate parametrised-SQL construction in uadas_core/database; empty-string password
# *defaults* on a profile dataclass that holds no real password), skipped by code (B101, B107, B608)
# rather than by a path-keyed baseline file, which breaks between Windows and Linux. See ci.yml's
# bandit step for the per-code rationale. Anything outside that skip set fails the commit.
& $py -m bandit -r uadas_core -q --skip B101,B107,B608
$banditExit = $LASTEXITCODE

if ($banditExit -ne 0) {
    Write-Error "Security checks failed (bandit finding outside the B101/B107/B608 skip set). Commit blocked."
    exit 2
}

Write-Host "Tests and security checks passed."
exit 0
