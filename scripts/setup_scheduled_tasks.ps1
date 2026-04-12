# ============================================================================
# setup_scheduled_tasks.ps1
# ============================================================================
# Create 2 Windows Scheduled Tasks for vnstock_dashboard pipeline:
#
#   1. VnStock Daily Rollup  (15:30 Mon-Fri)
#      Merge 1m bars from _live into warehouse daily OHLCV
#      Command: python vnstock_rollup.py
#
#   2. VnStock Daily Updater (18:00 Mon-Fri)
#      Fetch missing daily data from API if any gap
#      Command: python vnstock_updater.py --force
#
# Usage (run PowerShell AS ADMINISTRATOR):
#   .\scripts\setup_scheduled_tasks.ps1
#   .\scripts\setup_scheduled_tasks.ps1 -Remove    # Remove tasks
#   .\scripts\setup_scheduled_tasks.ps1 -DryRun    # Preview only
#
# Requirements:
#   - venv activated OR Python in PATH
#   - Project root must exist at parent of scripts/ dir
# ============================================================================

param(
    [switch]$Remove,
    [switch]$DryRun,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

# Check administrator privileges
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin -and -not $DryRun) {
    Write-Host ""
    Write-Host "[ERROR] This script must be run as Administrator." -ForegroundColor Red
    Write-Host ""
    Write-Host "How to fix:" -ForegroundColor Yellow
    Write-Host "  1. Close this PowerShell window"
    Write-Host "  2. Right-click Start menu -> 'Windows PowerShell (Admin)'"
    Write-Host "     (or 'Terminal (Admin)' on Windows 11)"
    Write-Host "  3. cd to project directory:"
    Write-Host "     cd '$((Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)))'"
    Write-Host "  4. Re-run the script:"
    Write-Host "     .\scripts\setup_scheduled_tasks.ps1"
    Write-Host ""
    Write-Host "Or try dry-run first (no admin needed):"
    Write-Host "  .\scripts\setup_scheduled_tasks.ps1 -DryRun"
    Write-Host ""
    exit 1
}

# Paths - auto-detect from script location
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SystemPython = (Get-Command python.exe -ErrorAction SilentlyContinue).Source

# Priority: -PythonExe param > local .venv > system python
if ($PythonExe -ne "") {
    if (-not (Test-Path $PythonExe)) {
        Write-Error "Custom Python path does not exist: $PythonExe"
        exit 1
    }
    Write-Host "Using custom Python: $PythonExe" -ForegroundColor Cyan
}
elseif (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host "Using venv Python: $PythonExe" -ForegroundColor Cyan
}
elseif ($SystemPython) {
    $PythonExe = $SystemPython
    Write-Host "Using system Python: $PythonExe" -ForegroundColor Yellow
    Write-Host "(Recommendation: create venv at .venv to isolate dependencies)" -ForegroundColor Yellow
}
else {
    Write-Error "Python not found. Install Python or create venv at .venv"
    exit 1
}

$TaskDefinitions = @(
    @{
        Name        = "VnStock Daily Rollup"
        Script      = "vnstock_rollup.py"
        Args        = "--skip-if-done"
        Time        = "15:30"
        Description = "Merge 1m bars to warehouse (skip if done by another machine)"
    },
    @{
        Name        = "VnStock Daily Updater"
        Script      = "vnstock_updater.py"
        Args        = "--force --skip-if-done"
        Time        = "18:00"
        Description = "Fetch daily data (skip if done by another machine)"
    }
)

# ---- Remove mode -----------------------------------------------------------
if ($Remove) {
    Write-Host "`n=== Removing Scheduled Tasks ===" -ForegroundColor Yellow
    foreach ($task in $TaskDefinitions) {
        $name = $task.Name
        try {
            $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            if ($existing) {
                if ($DryRun) {
                    Write-Host "[dry-run] Would remove: $name" -ForegroundColor Cyan
                }
                else {
                    Unregister-ScheduledTask -TaskName $name -Confirm:$false
                    Write-Host "[OK] Removed: $name" -ForegroundColor Green
                }
            }
            else {
                Write-Host "     Not found: $name (skip)" -ForegroundColor Gray
            }
        }
        catch {
            Write-Host "[FAIL] Remove $name : $_" -ForegroundColor Red
        }
    }
    exit 0
}

# ---- Create mode -----------------------------------------------------------
Write-Host "`n=== Setting up VnStock Scheduled Tasks ===" -ForegroundColor Cyan
Write-Host "Hostname:     $env:COMPUTERNAME"
Write-Host "Project root: $ProjectRoot"
Write-Host "Python:       $PythonExe"
Write-Host ""
Write-Host "Multi-machine mode: tasks will skip if another machine" -ForegroundColor DarkGray
Write-Host "has already completed today's job (checks pipeline_status.json)." -ForegroundColor DarkGray
Write-Host ""

foreach ($task in $TaskDefinitions) {
    $name = $task.Name
    $scriptPath = Join-Path $ProjectRoot $task.Script

    if (-not (Test-Path $scriptPath)) {
        Write-Host "[FAIL] Script not found: $scriptPath (skip)" -ForegroundColor Red
        continue
    }

    # Build argument string
    $argList = "`"$scriptPath`""
    if ($task.Args) {
        $argList += " " + $task.Args
    }

    Write-Host "---- $name ----" -ForegroundColor Cyan
    Write-Host "  Trigger:   Daily at $($task.Time), Mon-Fri"
    Write-Host "  Command:   $PythonExe $argList"
    Write-Host "  Working:   $ProjectRoot"

    if ($DryRun) {
        Write-Host "  [dry-run] Would create task" -ForegroundColor Yellow
        Write-Host ""
        continue
    }

    try {
        # Remove existing task if present
        $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "  (removed existing task with same name)" -ForegroundColor Gray
        }

        # Action - run Python with script
        $action = New-ScheduledTaskAction `
            -Execute $PythonExe `
            -Argument $argList `
            -WorkingDirectory $ProjectRoot

        # Trigger - daily Mon-Fri
        $trigger = New-ScheduledTaskTrigger `
            -Weekly `
            -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
            -At $task.Time

        # Settings - allow run even if missed (laptop sleep), stop after 30 min
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

        # Register task for current user
        Register-ScheduledTask `
            -TaskName $name `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Description $task.Description `
            -RunLevel Limited `
            -ErrorAction Stop | Out-Null

        Write-Host "  [OK] Created" -ForegroundColor Green
    }
    catch {
        Write-Host "  [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    }
    Write-Host ""
}

Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host "Verify with:  Get-ScheduledTask -TaskName 'VnStock *'" -ForegroundColor Gray
Write-Host "Run manually: Start-ScheduledTask -TaskName 'VnStock Daily Rollup'" -ForegroundColor Gray
