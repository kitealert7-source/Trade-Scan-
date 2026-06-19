# backup_repos.ps1 - Mirror 6 pipeline repos to Synology NAS
# Runs every 6 hours via Windows Task Scheduler - TradeScan NAS Backup
# Robocopy exit codes 0-7 are normal/informational; 8+ = real copy failures

$NAS   = "\\FARAWAYTOURISM\faraway\Trade_Scan_Backup"
$SRC   = "C:\Users\faraw\Documents"
$LOG   = "$SRC\backup_repos.log"

$repos = @(
    "Trade_Scan",
    "TradeScan_State",
    "TS_Execution",
    "DATA_INGRESS",
    "Anti_Gravity_DATA_ROOT",
    "DRY_RUN_VAULT",
    "TS_Obsidian_Vault"
)

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts  $msg"
    Write-Host $line
    $line | Out-File -FilePath $LOG -Append -Encoding utf8
}

# Trim log to last 2000 lines to avoid unbounded growth
if (Test-Path $LOG) {
    $lines = Get-Content $LOG -Encoding utf8
    if ($lines.Count -gt 2000) {
        $lines | Select-Object -Last 2000 | Set-Content $LOG -Encoding utf8
    }
}

Log "================================================================"
Log "Backup started"

$any_error = $false

foreach ($repo in $repos) {
    $src_path = Join-Path $SRC $repo
    $dst_path = Join-Path $NAS $repo

    if (-not (Test-Path $src_path)) {
        Log "SKIP   $repo - source not found at $src_path"
        continue
    }

    Log "SYNC   $repo ..."

    # /MIR  = mirror (adds + removes to match source)
    # /ZB   = restartable mode, fallback to backup mode for locked files
    # /R:3  = retry 3 times on locked files
    # /W:5  = wait 5s between retries
    # /NP   = no progress percentage (cleaner log)
    # /NDL  = no directory list in log
    # /NC   = no file class labels
    # /XD   = exclude dirs: the git object store (large/binary) AND Trade_Scan\data_root,
    #         which is a JUNCTION to Anti_Gravity_DATA_ROOT (already its OWN backup entry).
    #         Without this, robocopy follows the junction and mirrors ~7.4GB of it nested
    #         under Trade_Scan -> double-copy + very slow (diagnosed 2026-06-19).
    #         NOTE: a global /XJ is deliberately NOT used -- it would also skip
    #         TradeScan_State's runs\<id> -> sandbox\<id> junctions (23 of them), which
    #         /MIR would then purge from the backup, harming restore fidelity.
    # /B    = backup mode -- enables SeBackupPrivilege/SeRestorePrivilege so robocopy
    #         can read/write past the Deny INTERACTIVE:(D,DC) ACE on MASTER_DATA that
    #         was added after the 2026-05-07 incident. The scheduled task must run
    #         with RunLevel=Highest for these privileges to be present in the token;
    #         dry run validated 0 Failed / 0 Extras on 2026-05-10.
    # /XF   = exclude files: editor temp (~$*), per-run logs, AND live-SQLite sidecars
    #         (*.db-shm / *.db-wal / *.db-journal). Those are locked while any process
    #         holds a DB open (e.g. the daily cointegration screener, or a basket regime
    #         read of cointegration.db) -> robocopy ERROR 32 (sharing violation), which
    #         made EVERY run report "finished WITH ERRORS" and masked real failures
    #         (2026-06-19). The .db itself still copies; the sidecars are transient and
    #         SQLite rebuilds them on open, so excluding them is the correct backup posture.
    robocopy $src_path $dst_path /MIR /DCOPY:D /B /R:3 /W:5 /NP /NDL /NC /XD ".git\objects" "$SRC\Trade_Scan\data_root" /XF "~$*" "producer.log" "shim.log" "*.db-shm" "*.db-wal" "*.db-journal" /TEE /LOG+:"$LOG"
    $rc = $LASTEXITCODE

    # Exit codes 0-7 are informational (no real failures)
    # 0=no change 1=copied 2=extras 4=mismatch 8+=actual errors
    if ($rc -le 7) {
        Log "OK     $repo  (exit $rc)"
    } else {
        Log "ERROR  $repo  (exit $rc) - files could not be copied, check log"
        $any_error = $true
    }
}

if ($any_error) {
    Log "Backup finished WITH ERRORS - review log above"
    exit 1
} else {
    Log "Backup finished OK"
    exit 0
}

