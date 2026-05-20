# register_and_run_phase0a.ps1
# Cointegration screener — Phase 0a bootstrap.
# Registers the one-shot task, triggers it, waits, reports.
#
# MUST BE RUN AS ADMINISTRATOR (right-click -> Run as Administrator).
# The /Create needs elevation because RunLevel=HighestAvailable. The
# probe itself then runs as faraw + InteractiveToken (matches the
# TradeScan NAS Backup identity pattern).

$ErrorActionPreference = 'Stop'

$TaskName   = 'CointegrationScreener_Phase0aProbe'
$XmlPath    = 'C:\Users\faraw\Documents\Trade_Scan\outputs\cointegration_screener_v1\phase0a\CointegrationScreener_Phase0aProbe.task.xml'
$LogPath    = 'C:\Users\faraw\Documents\Trade_Scan\tmp\cointegration_smoke.log'
$ArchiveLog = 'C:\Users\faraw\Documents\Trade_Scan\outputs\cointegration_screener_v1\phase0a\phase0a_run.log'

Write-Host '=== Phase 0a bootstrap ===' -ForegroundColor Cyan
Write-Host "task name: $TaskName"
Write-Host "task XML : $XmlPath"
Write-Host "log file : $LogPath"
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

# --- 1. Unregister if exists (idempotent)
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
Write-Host '[OK] task registered' -ForegroundColor Green

# --- 3. Clear the result log so we know we are reading THIS run
if (Test-Path $LogPath) {
    Remove-Item $LogPath -Force
}

# --- 4. Trigger
Write-Host '[..] triggering task'
schtasks /Run /TN $TaskName | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[FAIL] schtasks /Run failed' -ForegroundColor Red
    exit 1
}

# --- 5. Wait for the task to finish (poll the LastTaskResult)
Write-Host '[..] waiting for completion (max 60s)'
$deadline = (Get-Date).AddSeconds(60)
$lastRunResult = $null
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    $info = schtasks /Query /TN $TaskName /FO LIST /V 2>$null
    $status = ($info | Select-String -Pattern '^Status:').Line
    $result = ($info | Select-String -Pattern '^Last Result:').Line
    if ($status -match 'Ready' -and $result -notmatch '267009') {
        # Status 'Ready' AND Last Result is not "still running" code 267009
        $lastRunResult = $result
        break
    }
}
if (-not $lastRunResult) {
    Write-Host '[FAIL] task did not finish within 60s' -ForegroundColor Red
    exit 1
}
Write-Host "[OK] $lastRunResult" -ForegroundColor Green

# --- 6. Read and echo the probe's log
if (-not (Test-Path $LogPath)) {
    Write-Host '[FAIL] probe wrote no log; check task history' -ForegroundColor Red
    exit 1
}
Write-Host ''
Write-Host '=== probe log ===' -ForegroundColor Cyan
Get-Content $LogPath
Write-Host '=== end log ===' -ForegroundColor Cyan

# --- 7. Archive the log alongside the XML for audit
Copy-Item $LogPath $ArchiveLog -Force
Write-Host ''
Write-Host "[OK] archived log -> $ArchiveLog" -ForegroundColor Green

# --- 8. Final pass/fail
$lastLine = (Get-Content $LogPath | Select-Object -Last 1)
if ($lastLine -match 'PASS Phase 0a all steps succeeded') {
    Write-Host ''
    Write-Host '*** PHASE 0a PASSED — gate cleared for Phase 1 ***' -ForegroundColor Green
    exit 0
} else {
    Write-Host ''
    Write-Host '*** PHASE 0a FAILED — DO NOT begin Phase 1 ***' -ForegroundColor Red
    exit 1
}