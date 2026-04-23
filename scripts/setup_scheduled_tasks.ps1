# ============================================================================
# setup_scheduled_tasks.ps1
# ============================================================================
# Create 2 Windows Scheduled Tasks for vnstock_dashboard pipeline:
#
#   1. VnStock Daily Pipeline  — 18:00 Mon-Fri
#      sync (updater + rollup + fix-units + auto-heal) → validate → audit
#      Command: python run.py --warehouse data_warehouse all
#
#   2. VnStock Weekly Corp Actions  — 09:00 Sunday
#      Scrape Vietstock for new dividends / splits → register
#      Command: python run.py --warehouse data_warehouse vietstock --bulk --register
#
# Both tasks have StartWhenAvailable = ON:
#   If the machine is off at scheduled time → task runs automatically
#   the next time the machine boots (no manual intervention needed).
#
# Usage (run PowerShell AS ADMINISTRATOR):
#   .\scripts\setup_scheduled_tasks.ps1              # create / update tasks
#   .\scripts\setup_scheduled_tasks.ps1 -Remove      # remove tasks
#   .\scripts\setup_scheduled_tasks.ps1 -DryRun      # preview only (no admin)
#
# Optional:
#   -PythonExe "C:\path\to\python.exe"  # override auto-detected Python
#   -DailyTime "17:00"                  # change daily trigger time (default 18:00)
#   -WeeklyTime "08:00"                 # change weekly trigger time (default 09:00)
# ============================================================================

param(
    [switch]$Remove,
    [switch]$DryRun,
    [string]$PythonExe  = "",
    [string]$DailyTime  = "18:00",
    [string]$WeeklyTime = "09:00"
)

$ErrorActionPreference = "Stop"

# ---- Admin check ------------------------------------------------------------
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
    Write-Host "  2. Right-click Start -> 'Windows PowerShell (Admin)' (or Terminal Admin)"
    Write-Host "  3. cd to project directory:"
    Write-Host "     cd '$((Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)))'"
    Write-Host "  4. Re-run: .\scripts\setup_scheduled_tasks.ps1"
    Write-Host ""
    Write-Host "Preview without admin: .\scripts\setup_scheduled_tasks.ps1 -DryRun"
    exit 1
}

# ---- Paths ------------------------------------------------------------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$SystemPython = (Get-Command python.exe -ErrorAction SilentlyContinue).Source

if ($PythonExe -ne "") {
    if (-not (Test-Path $PythonExe)) { Write-Error "Python not found: $PythonExe"; exit 1 }
    Write-Host "Using custom Python : $PythonExe" -ForegroundColor Cyan
}
elseif (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
    Write-Host "Using venv Python   : $PythonExe" -ForegroundColor Cyan
}
elseif ($SystemPython) {
    $PythonExe = $SystemPython
    Write-Host "Using system Python : $PythonExe" -ForegroundColor Yellow
    Write-Host "(Tip: create .venv to isolate dependencies)" -ForegroundColor DarkGray
}
else {
    Write-Error "Python not found. Install Python or create .venv"
    exit 1
}

$RunPy    = Join-Path $ProjectRoot "run.py"
$WareHouse = "data_warehouse"

# ---- Task definitions -------------------------------------------------------
# Each entry: Name, Args (passed to python after run.py), Trigger block
$TaskDefinitions = @(
    @{
        Name        = "VnStock Daily Pipeline"
        Args        = "--warehouse $WareHouse all"
        TriggerDesc = "Daily $DailyTime Mon-Fri  (+run-on-boot if missed)"
        Trigger     = {
            New-ScheduledTaskTrigger `
                -Weekly `
                -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
                -At $DailyTime
        }
        MaxMinutes  = 120
        Description = "sync (updater+rollup+fix-units+auto-heal) -> validate -> audit"
    },
    @{
        Name        = "VnStock Weekly Corp Actions"
        Args        = "--warehouse $WareHouse vietstock --bulk --register"
        TriggerDesc = "Weekly $WeeklyTime Sunday  (+run-on-boot if missed)"
        Trigger     = {
            New-ScheduledTaskTrigger `
                -Weekly `
                -DaysOfWeek Sunday `
                -At $WeeklyTime
        }
        MaxMinutes  = 60
        Description = "Scrape Vietstock dividends/splits -> corp_actions_registry"
    }
)

# ---- Remove mode ------------------------------------------------------------
if ($Remove) {
    Write-Host "`n=== Removing VnStock Scheduled Tasks ===" -ForegroundColor Yellow
    foreach ($task in $TaskDefinitions) {
        $name = $task.Name
        $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($existing) {
            if ($DryRun) {
                Write-Host "[dry-run] Would remove: $name" -ForegroundColor Cyan
            } else {
                Unregister-ScheduledTask -TaskName $name -Confirm:$false
                Write-Host "[OK] Removed: $name" -ForegroundColor Green
            }
        } else {
            Write-Host "     Not found: $name (skip)" -ForegroundColor Gray
        }
    }
    exit 0
}

# ---- Create mode ------------------------------------------------------------
Write-Host ""
Write-Host "=== Setting up VnStock Scheduled Tasks ===" -ForegroundColor Cyan
Write-Host "Hostname    : $env:COMPUTERNAME"
Write-Host "Project root: $ProjectRoot"
Write-Host "Python      : $PythonExe"
Write-Host ""
Write-Host "  StartWhenAvailable = ON" -ForegroundColor Green
Write-Host "  => If machine is OFF at scheduled time, task runs automatically" -ForegroundColor Green
Write-Host "     the next time Windows boots. No manual action needed." -ForegroundColor Green
Write-Host ""

foreach ($task in $TaskDefinitions) {
    $name    = $task.Name
    $argList = "`"$RunPy`" $($task.Args)"

    Write-Host "---- $name ----" -ForegroundColor Cyan
    Write-Host "  Trigger : $($task.TriggerDesc)"
    Write-Host "  Command : $PythonExe $argList"
    Write-Host "  Workdir : $ProjectRoot"
    Write-Host "  Timeout : $($task.MaxMinutes) min"

    if ($DryRun) {
        Write-Host "  [dry-run] Would create task" -ForegroundColor Yellow
        Write-Host ""
        continue
    }

    try {
        # Remove old task with same name if present
        $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($existing) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "  (replaced existing task)" -ForegroundColor Gray
        }

        $action = New-ScheduledTaskAction `
            -Execute        $PythonExe `
            -Argument       $argList `
            -WorkingDirectory $ProjectRoot

        $trigger = & $task.Trigger

        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes $task.MaxMinutes)

        Register-ScheduledTask `
            -TaskName    $name `
            -Action      $action `
            -Trigger     $trigger `
            -Settings    $settings `
            -Description $task.Description `
            -RunLevel    Limited `
            -ErrorAction Stop | Out-Null

        Write-Host "  [OK] Created" -ForegroundColor Green
    }
    catch {
        Write-Host "  [FAIL] $($_.Exception.Message)" -ForegroundColor Red
    }
    Write-Host ""
}

Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor DarkGray
Write-Host "  List tasks  : Get-ScheduledTask -TaskName 'VnStock *' | Select TaskName,State,LastRunTime,NextRunTime"
Write-Host "  Run daily   : Start-ScheduledTask -TaskName 'VnStock Daily Pipeline'"
Write-Host "  Run weekly  : Start-ScheduledTask -TaskName 'VnStock Weekly Corp Actions'"
Write-Host "  Remove all  : .\scripts\setup_scheduled_tasks.ps1 -Remove"
