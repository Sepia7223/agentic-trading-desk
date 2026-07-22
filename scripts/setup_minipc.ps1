# Mini-PC migration: recreate the full working environment from GitHub + the
# data archive, verify it, and take over the daily paper-trading session.
#
# Usage (PowerShell on the mini PC, from any directory):
#   powershell -ExecutionPolicy Bypass -File setup_minipc.ps1 `
#     -ArchivePath "D:\trading-data.tar.gz" -Root "C:\trading"
#
# Idempotent: safe to re-run. Stops on the first error.

param(
    [Parameter(Mandatory = $true)][string]$ArchivePath,
    [string]$Root = "C:\trading",
    [string]$RepoUrl = "https://github.com/Sepia7223/agentic-trading-desk.git",
    [string]$SessionTime = "18:30"
)

$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n==== $msg ====" -ForegroundColor Cyan }

Step "0/7 prerequisites"
git --version
python --version
if (-not (Test-Path $ArchivePath)) { throw "archive not found: $ArchivePath" }

Step "1/7 clone or update the main repo"
$main = Join-Path $Root "agentic-trading-desk"
if (-not (Test-Path (Join-Path $main ".git"))) {
    New-Item -ItemType Directory -Force $Root | Out-Null
    git clone $RepoUrl $main
} else {
    git -C $main fetch --all --prune
}
git -C $main checkout feature/ig-demo-operational-certification
git -C $main pull --ff-only

Step "2/7 m12 worktree (the active branch: strategy + paper trading)"
$m12 = Join-Path $Root "agentic-trading-desk-m12"
if (-not (Test-Path $m12)) {
    git -C $main worktree add $m12 feature/multi-regime-strategy-portfolio
} else {
    git -C $m12 pull --ff-only
}

Step "3/7 restore data archive (validation FX + PIT stocks + paper state)"
tar -xzf $ArchivePath -C $m12
"restored:"; Get-ChildItem (Join-Path $m12 "data") -Directory | Select-Object Name

Step "4/7 python dependencies"
python -m pip install --quiet -e "$m12[dev]" 2>$null
if ($LASTEXITCODE -ne 0) { python -m pip install -e $m12 }

Step "5/7 verification: full test suite"
Push-Location $m12
python -m pytest tests/ -q
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "TESTS FAILED - do not proceed" }
Pop-Location

Step "6/7 one manual paper session (proves quotes + news + pipeline end-to-end)"
Push-Location $m12
$env:PYTHONPATH = "src;scripts"
python scripts/paper_trade.py
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "PAPER SESSION FAILED - investigate before scheduling" }
Pop-Location

Step "7/7 take over the daily schedule"
$wrapper = Join-Path $m12 "scripts\run_paper_session.cmd"
$action = New-ScheduledTaskAction -Execute $wrapper
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $SessionTime
Register-ScheduledTask -TaskName "AgenticDesk-PaperTrade" -Action $action -Trigger $trigger -Force | Out-Null
schtasks /Query /TN "AgenticDesk-PaperTrade" /FO LIST | Select-String "TaskName|Status|Next Run"

Write-Host @"

==== MIGRATION COMPLETE ====
- repo:        $main  (+ m12 worktree at $m12)
- paper state: restored; daily session scheduled weekdays $SessionTime
- REMINDER:    the laptop's task is already DISABLED; delete it there with:
                 schtasks /Delete /TN "AgenticDesk-PaperTrade" /F
- Two machines must NEVER both run sessions (state would fork).
"@ -ForegroundColor Green
