# ============================================================================
# setup_scheduled_tasks.ps1
# ============================================================================
# Create 4 Windows Scheduled Tasks for vnstock_dashboard pipeline:
#
#   1. VnStock Daily Pipeline     — 18:00 Mon-Fri
#      sync → validate → screener → news → ... → audit → train → doctor
#      → brief chiều Telegram (14 steps; brief added 2026-07-29 — trước đây
#      user chạy tay; guard chống gửi trùng + không đẩy trước 15:00)
#      Command: python run.py --warehouse data_warehouse all
#
#   2. VnStock Weekend Pipeline   — 09:00 Saturday (gộp 3 task cũ, 2026-07-29)
#      rates-weekly (Telegram) → vietstock corp actions → fundamentals --force
#      Command: python run.py --warehouse data_warehouse weekend
#      Máy tắt lúc 09:00 T7 → StartWhenAvailable chạy lúc mở máy sớm nhất
#      cuối tuần. (3 task cũ Corp Actions CN / Fundamentals T2 / Rates T7
#      được script TỰ GỠ khi chạy lại — không cần xoá tay.)
#
# Note: News sentiment (run.py news) is now a built-in step of the daily
# pipeline — no separate task needed. Skip with --no-news if desired.
#
# All tasks have StartWhenAvailable = ON:
#   If the machine is off at scheduled time → task runs automatically
#   the next time the machine boots (no manual intervention needed).
#
# Usage (run PowerShell AS ADMINISTRATOR):
#   .\scripts\setup_scheduled_tasks.ps1              # create / update all tasks
#   .\scripts\setup_scheduled_tasks.ps1 -Remove      # remove all tasks
#   .\scripts\setup_scheduled_tasks.ps1 -DryRun      # preview only (no admin)
#
# Optional:
#   -PythonExe "C:\path\to\python.exe"  # override auto-detected Python
#   -DailyTime "18:00"                  # daily pipeline time (default 18:00)
#   -WeekendTime "09:00"                # weekend pipeline time Sat (default 09:00)
# ============================================================================

param(
    [switch]$Remove,
    [switch]$DryRun,
    [string]$PythonExe        = "",
    [string]$DailyTime   = "18:00",
    [string]$WeekendTime = "09:00"
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

$RunPy     = Join-Path $ProjectRoot "run.py"
$WareHouse = "data_warehouse"

# ---- Task definitions -------------------------------------------------------
# Each entry: Name, Execute (python exe), Args, Trigger block
$TaskDefinitions = @(
    @{
        Name        = "VnStock Daily Pipeline"
        Execute     = $PythonExe
        Args        = "`"$RunPy`" --warehouse $WareHouse all"
        TriggerDesc = "Weekly $DailyTime Mon-Fri  (+run-on-boot if missed)"
        Trigger     = {
            New-ScheduledTaskTrigger `
                -Weekly `
                -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
                -At $DailyTime
        }
        # 120 -> 180 (19/08): phat 18/08 chay 96.6' MOI DEN buoc 9 (sync 60' +
        # screener 28'), con 4 buoc nua moi toi brief. Du dia chi 16' — mot dem
        # sync phinh nhu 17/08 (74') la task bi cham dut TRUOC brief, dung cai
        # da xay ra. Weekend da dung 180 tu dau.
        # 180 -> 240 (29/09): 21/09 khoi dong 20:12, sync 99' (VCI om) + screener
        # 23' + news 17' + train 12' => buoc brief bat dau o phut 168, bi giet o
        # phut 180 giua chung (khong TONG, khong Telegram); 28/09 178.2' chi con 2'.
        # Buoc brief dem Gemini om mat 23-42' (viec #21) nen 180 khong du.
        MaxMinutes  = 240
        Description = "14 buoc: sync -> validate -> screener -> ... -> audit -> train -> doctor -> brief chieu Telegram"
    },
    @{
        Name        = "VnStock Weekend Pipeline"
        Execute     = $PythonExe
        Args        = "`"$RunPy`" --warehouse $WareHouse weekend"
        TriggerDesc = "Weekly $WeekendTime Saturday  (+run-on-boot if missed)"
        Trigger     = {
            New-ScheduledTaskTrigger `
                -Weekly `
                -DaysOfWeek Saturday `
                -At $WeekendTime
        }
        MaxMinutes  = 180
        Description = "Gop 3 viec cuoi tuan (2026-07-29): rates-weekly Telegram -> vietstock corp actions -> fundamentals --force (~30-40 phut)"
    }
)

# Task cu da GOP vao Weekend Pipeline (2026-07-29) — tu go khi chay lai script
$LegacyTaskNames = @(
    "VnStock Weekly Corp Actions",
    "VnStock Fundamentals",
    "VnStock Rates Weekly"
)

# ---- Remove mode ------------------------------------------------------------
if ($Remove) {
    Write-Host "`n=== Removing VnStock Scheduled Tasks ===" -ForegroundColor Yellow
    $allNames = @($TaskDefinitions | ForEach-Object { $_.Name }) + $LegacyTaskNames
    foreach ($name in $allNames) {
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

# ---- Gỡ task cũ đã gộp (create mode) ----------------------------------------
foreach ($name in $LegacyTaskNames) {
    $existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($existing) {
        if ($DryRun) {
            Write-Host "[dry-run] Would remove legacy task: $name" -ForegroundColor Yellow
        } else {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "[OK] Removed legacy task (da gop vao Weekend): $name" -ForegroundColor Yellow
        }
    }
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
    $exe     = $task.Execute
    $argList = $task.Args

    Write-Host "---- $name ----" -ForegroundColor Cyan
    Write-Host "  Trigger : $($task.TriggerDesc)"
    Write-Host "  Command : $exe $argList"
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
            -Execute        $exe `
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
Write-Host "  List tasks       : Get-ScheduledTask -TaskName 'VnStock *' | Select TaskName,State,LastRunTime,NextRunTime"
Write-Host "  Run daily        : Start-ScheduledTask -TaskName 'VnStock Daily Pipeline'"
Write-Host "  Run weekend      : Start-ScheduledTask -TaskName 'VnStock Weekend Pipeline'"
Write-Host "  Remove all       : .\scripts\setup_scheduled_tasks.ps1 -Remove"
Write-Host "  Update all       : .\scripts\setup_scheduled_tasks.ps1  (re-run same script)"
