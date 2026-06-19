@echo off
REM Manual wrapper for backup_repos.ps1 (same script the "TradeScan NAS Backup"
REM scheduled task runs every 6h). Double-click to run on demand with visible
REM output; scheduled task still runs hidden via its own action.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_repos.ps1"
set RC=%ERRORLEVEL%

echo.
if %RC%==0 (
    echo === Backup complete (exit 0) ===
) else (
    echo === Backup FAILED with exit code %RC% ===
)
pause
