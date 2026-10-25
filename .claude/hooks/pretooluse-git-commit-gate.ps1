# File: .claude/hooks/pretooluse-git-commit-gate.ps1
# PreToolUse gate (Bash|PowerShell matcher): runs pre-commit-check.ps1, but only
# when the tool call is actually a `git commit`.
#
# Split out from settings.json's hook `command`, which previously inlined this
# check as a `-Command "..."` script containing `& '$CLAUDE_PROJECT_DIR\...'`
# -- SINGLE-quoted. PowerShell never expands a variable reference inside
# single quotes, regardless of whether $CLAUDE_PROJECT_DIR is set in the
# environment -- so that `&` was invoking a file literally named
# `$CLAUDE_PROJECT_DIR\.claude\hooks\pre-commit-check.ps1` (with a literal
# dollar sign), which does not exist. The gate silently no-op'd on every
# commit: a commit gate that was not gating anything -- the exact failure
# class pre-commit-check.ps1's own top-of-file comment already documents and
# fixed for *itself*, just never propagated to this wrapper. (Confirmed
# 2026-09-10/11: commits returned in seconds with none of pre-commit-check's
# "Running pytest..." output, for the entire length of Phase 2.1 -- every
# commit was instead verified by manually running the suite.)
#
# Fix: invoke this file via `-File "$CLAUDE_PROJECT_DIR\...\<this file>.ps1"`
# -- the exact pattern quality-check.ps1 and protect-files.ps1 already use
# and have demonstrably fired correctly on every Edit/Write this session --
# and resolve pre-commit-check.ps1 from $PSScriptRoot (this script's own
# location) rather than re-relying on $CLAUDE_PROJECT_DIR a second time
# inside the script body, so this stays correct even if that substitution
# is ever unreliable again.
$ErrorActionPreference = "Continue"

$stdin = [Console]::In.ReadToEnd()
$event = $stdin | ConvertFrom-Json

if ($event.tool_input.command -match 'git\s+commit(?![\w-])') {
    & (Join-Path $PSScriptRoot "pre-commit-check.ps1")
    exit $LASTEXITCODE
}

exit 0
