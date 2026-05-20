# register_daily_task.ps1
# Cointegration screener — Phase 4 bootstrap.
# Registers the daily task, optionally triggers one immediate run for verification.
#
# MUST BE RUN AS ADMINISTRATOR (right-click -> Run as Administrator) because
# RunLevel=HighestAvailable requires elevation for schtasks /Create.

param(
    [switch] $TriggerOnce  # if set, run the task once immediately after registration
)

$ErrorActionPreference = 'Stop'

$TaskName   = 'CointegrationScreener_DailyRun'
$XmlPath    = 'C:\Users\faraw\Documents\Trade_Scan\outputs\cointegration_screener_v1\phase4\CointegrationScreener_DailyRun.task.xml'
$LogPath    = 'C:\Users\faraw\Documents\Trade_Scan\tmp\cointegration_daily.log'
$ArchiveLog = 'C:\Users\faraw\Documents\Trade_Scan\outputs\cointegration_screener_v1\phase4\phase4_first_run.log'

Write-Host '=== Phase 4 bootstrap — daily task registration ===' -ForegroundColor Cyan
Write-Host "task name: $TaskName"
Write-Host "task XML : $XmlPath"
Write-Host "trigger  : 22:30 UTC daily"
Write-Host ''

# --- 0. Elevation check
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'ABORT: this script must be run from an ELEVATED PowerShell.' -ForegroundColor Red
    Write-Host 'Right-click the script and choose "Run as Administrator".'
    exit 99
}
Write-Host '[OK] running elevated' -ForegroundColor Green

# --- 1. Unregister if exists (idempotent re-registration)
try {
    schtasks /Query /TN $TaskName 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host '[..] task exists, deleting'
        schtasks /Delete /TN $TaskName /F | Out-Null
    }
} catch {}

# --- 2. Register from XML
Write-Host '[..] registering task from XML'
schtasks /Create /TN $TaskName /XML $XmlPath /F
if ($LASTEXITCODE -ne 0) {
    Write-Host '[FAIL] schtasks /Create failed' -ForegroundColor Red
    exit 1
}
Write-Host '[OK] task registered (will fire daily at 22:30 UTC)' -ForegroundColor Green

if (-not $TriggerOnce) {
    Write-Host ''
    Write-Host 'Done. Re-run with -TriggerOnce to also run the task immediately.'
    exit 0
}

# --- 3. Optional: trigger the task once now for first-run verification
Write-Host ''
Write-Host '[..] triggering task now (verification run)'
if (Test-Path $LogPath) {
    Remove-Item $LogPath -Force
}
schtasks /Run /TN $TaskName | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[FAIL] schtasks /Run failed' -ForegroundColor Red
    exit 1
}

# --- 4. Wait for completion (max 5 min)
Write-Host '[..] waiting for completion (max 5 min)'
$deadline = (Get-Date).AddMinutes(5)
$lastResult = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 4
    $info = schtasks /Query /TN $TaskName /FO LIST /V 2>$null
    $status = ($info | Select-String -Pattern '^Status:').Line
    $result = ($info | Select-String -Pattern '^Last Result:').Line
    if ($status -match 'Ready' -and $result -notmatch '267009') {
        $lastResult = $result
        break
    }
}
if (-not $lastResult) {
    Write-Host '[FAIL] task did not finish within 5 min' -ForegroundColor Red
    exit 1
}
Write-Host "[OK] $lastResult" -ForegroundColor Green

# --- 5. Echo + archive the log
if (Test-Path $LogPath) {
    Write-Host ''
    Write-Host '=== daily-runner log (this run) ===' -ForegroundColor Cyan
    Get-Content $LogPath
    Write-Host '=== end log ===' -ForegroundColor Cyan
    Copy-Item $LogPath $ArchiveLog -Force
    Write-Host "[OK] archived first-run log -> $ArchiveLog" -ForegroundColor Green
}

# --- 6. Pass/fail
$lastLine = (Get-Content $LogPath | Select-Object -Last 1)
if ($lastLine -match 'PASS') {
    Write-Host ''
    Write-Host '*** PHASE 4 FIRST RUN PASSED ***' -ForegroundColor Green
    Write-Host '    Task will fire daily at 22:30 UTC.'
    Write-Host '    Monitor 7 consecutive runs before declaring v1 stable (spec §12).'
    exit 0
} else {
    Write-Host ''
    Write-Host '*** PHASE 4 FIRST RUN FAILED — see log above ***' -ForegroundColor Red
    exit 1
}