# scheduled_task_identity_smoke.ps1
#
# CI-style guard for scheduled-task service-account migrations.
#
# WHY THIS EXISTS
# The 2026-05-07 MASTER_DATA wipe incident was followed by a service-account
# migration (svc-data-ingress + LogonType=Password). A "smoke test" was run
# and reported PASS, but the test actually executed as faraw (interactive),
# not as svc-data-ingress (batch). The script printed "Identity: faraw,
# INTERACTIVE=True, BATCH=False" but no code REJECTED that mismatch — the
# verification was advisory. The architecture was approved on a false
# positive and broke at the first natural production trigger.
#
# THE RULE THIS ENFORCES
# Before any scheduled task is migrated to a new run-as identity / logon
# type, this script must run successfully against the new configuration.
# Mismatches are binary failures with non-zero exit codes — no human
# interpretation, no "advisory" output.
#
# USAGE
#   Selfcheck (runs INSIDE the target identity, e.g., from a scheduled task):
#     powershell -File scheduled_task_identity_smoke.ps1 `
#         -Mode selfcheck `
#         -ExpectedUser   'svc-data-ingress' `
#         -RequiredGroup  'BATCH' `
#         -ForbiddenGroup 'INTERACTIVE' `
#         -TargetDir      'C:\Users\faraw\Documents\Anti_Gravity_DATA_ROOT\MASTER_DATA\XAUUSD_OCTAFX_MASTER\RESEARCH' `
#         -ResultLog      'C:\Users\faraw\Documents\Trade_Scan\tmp\identity_smoke.log'
#
#   Validate (registers + triggers a one-shot task as the target identity,
#   then asserts the selfcheck log shows the expected identity AND exit 0):
#     powershell -File scheduled_task_identity_smoke.ps1 `
#         -Mode validate `
#         -ExpectedUser   'svc-data-ingress' `
#         -RequiredGroup  'BATCH' `
#         -ForbiddenGroup 'INTERACTIVE' `
#         -TargetDir      'C:\Users\faraw\Documents\Anti_Gravity_DATA_ROOT\MASTER_DATA\XAUUSD_OCTAFX_MASTER\RESEARCH' `
#         -LogonType      'Password' `
#         -Credential     (Get-Credential)
#     # validate mode requires elevation
#
# EXIT CODES
#   0   PASS (every assertion + file op succeeded)
#   100 generic FAIL (script-level error)
#   101 FAIL identity mismatch    (actual user != ExpectedUser)
#   102 FAIL required group missing
#   103 FAIL forbidden group present
#   104 FAIL file-op failed
#   105 FAIL validate-mode parse: result log absent or unreadable
#   106 FAIL validate-mode parse: result log identity does not match
#   107 FAIL validate-mode: task did not return success exit code

[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('selfcheck','validate')]
    [string] $Mode,

    [Parameter(Mandatory)]
    [string] $ExpectedUser,

    [Parameter(Mandatory)]
    [string] $RequiredGroup,

    [Parameter(Mandatory)]
    [string] $ForbiddenGroup,

    [Parameter(Mandatory)]
    [string] $TargetDir,

    [Parameter()]
    [string] $ResultLog = 'C:\Users\faraw\Documents\Trade_Scan\tmp\identity_smoke.log',

    [Parameter()]
    [ValidateSet('Password','S4U','Interactive')]
    [string] $LogonType = 'Password',

    [Parameter()]
    [System.Management.Automation.PSCredential] $Credential
)

$ErrorActionPreference = 'Continue'

function Write-Result {
    param([string] $Path, [string] $Message)
    "$([DateTime]::UtcNow.ToString('o')) | $Message" | Out-File -Append -Encoding utf8 $Path
}

# ============================================================================
# SELFCHECK MODE — runs INSIDE the target identity context
# ============================================================================
function Invoke-Selfcheck {
    if (Test-Path $ResultLog) { Remove-Item $ResultLog -Force }

    Write-Result $ResultLog ('SELFCHECK START expected_user=' + $ExpectedUser + ' required_group=' + $RequiredGroup + ' forbidden_group=' + $ForbiddenGroup)

    # Capture identity
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $actualUser = $id.Name
    $actualGroups = @($id.Groups | ForEach-Object {
        try { $_.Translate([Security.Principal.NTAccount]).Value } catch { $_.Value }
    })

    Write-Result $ResultLog ("ACTUAL_USER " + $actualUser)
    Write-Result $ResultLog ("ACTUAL_GROUPS " + ($actualGroups -join ' | '))

    # Identity assertion (binary)
    $userMatch = ($actualUser -eq $ExpectedUser) -or ($actualUser -like "*\$ExpectedUser")
    if (-not $userMatch) {
        Write-Result $ResultLog ("FAIL identity_mismatch expected=" + $ExpectedUser + " actual=" + $actualUser)
        exit 101
    }
    Write-Result $ResultLog ("ASSERT identity OK")

    # Required group assertion (binary)
    $reqQualified = "NT AUTHORITY\$RequiredGroup"
    if (-not ($actualGroups -contains $reqQualified)) {
        Write-Result $ResultLog ("FAIL required_group_missing expected=" + $reqQualified)
        exit 102
    }
    Write-Result $ResultLog ("ASSERT required_group OK")

    # Forbidden group assertion (binary)
    $fbdQualified = "NT AUTHORITY\$ForbiddenGroup"
    if ($actualGroups -contains $fbdQualified) {
        Write-Result $ResultLog ("FAIL forbidden_group_present found=" + $fbdQualified)
        exit 103
    }
    Write-Result $ResultLog ("ASSERT forbidden_group_absent OK")

    # File-op smoke (mirrors DATA_INGRESS write pattern: create + append + atomic-replace + read + delete)
    if (-not (Test-Path $TargetDir)) {
        Write-Result $ResultLog ("FAIL target_dir_missing path=" + $TargetDir)
        exit 104
    }

    $ts = Get-Date -Format 'yyyyMMddHHmmssfff'
    $tmp = Join-Path $TargetDir "__identity_smoke_${ts}.tmp"
    $tgt = Join-Path $TargetDir "__identity_smoke_${ts}.dat"
    try {
        'sentinel' | Out-File -Encoding utf8 $tmp
        if (-not (Test-Path $tmp)) { throw "create-fail" }
        'second' | Out-File -Encoding utf8 -Append $tmp
        Move-Item -Path $tmp -Destination $tgt -Force
        if (-not (Test-Path $tgt)) { throw "replace-fail" }
        $content = Get-Content $tgt -Raw
        if ($content -notmatch 'sentinel') { throw "read-fail" }
        Remove-Item $tgt -Force
        if (Test-Path $tgt) { throw "delete-fail" }
    } catch {
        Write-Result $ResultLog ("FAIL file_op error=" + $_)
        Remove-Item $tmp, $tgt -Force -ErrorAction SilentlyContinue
        exit 104
    }
    Write-Result $ResultLog ("ASSERT file_ops OK")

    Write-Result $ResultLog ("PASS all assertions green")
    exit 0
}

# ============================================================================
# VALIDATE MODE — registers + triggers + parses result
# ============================================================================
function Invoke-Validate {
    # Validate mode requires admin (registering tasks for another user)
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Output "FAIL: validate mode requires elevated PowerShell"
        exit 100
    }

    if ($LogonType -eq 'Password' -and -not $Credential) {
        Write-Output "FAIL: -Credential is required when -LogonType is Password"
        exit 100
    }

    $taskName = '__identity_smoke_' + (Get-Date -Format 'yyyyMMddHHmmss')
    $scriptPath = $PSCommandPath

    # Build the selfcheck invocation
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -Mode selfcheck -ExpectedUser `"$ExpectedUser`" -RequiredGroup `"$RequiredGroup`" -ForbiddenGroup `"$ForbiddenGroup`" -TargetDir `"$TargetDir`" -ResultLog `"$ResultLog`""
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $args
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddYears(10)

    $logonTypeMap = @{ 'Password' = 'Password'; 'S4U' = 'S4U'; 'Interactive' = 'Interactive' }
    $principal = New-ScheduledTaskPrincipal -UserId $ExpectedUser -LogonType $logonTypeMap[$LogonType] -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -Hidden

    if (Test-Path $ResultLog) { Remove-Item $ResultLog -Force }

    try {
        if ($LogonType -eq 'Password') {
            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
                -Principal $principal -Settings $settings `
                -User $Credential.UserName -Password $Credential.GetNetworkCredential().Password -Force | Out-Null
        } else {
            # S4U / Interactive: no password
            Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
                -Principal $principal -Settings $settings -Force | Out-Null
        }

        Start-ScheduledTask -TaskName $taskName

        $deadline = (Get-Date).AddSeconds(60)
        do {
            Start-Sleep -Seconds 2
            $st = (Get-ScheduledTask -TaskName $taskName).State
        } while ($st -eq 'Running' -and (Get-Date) -lt $deadline)

        $info = Get-ScheduledTaskInfo -TaskName $taskName
        $taskExitCode = $info.LastTaskResult

        if (-not (Test-Path $ResultLog)) {
            Write-Output "FAIL: validate mode could not find result log at $ResultLog (selfcheck never ran)"
            exit 105
        }

        $log = Get-Content $ResultLog -Raw

        # Parse the ACTUAL_USER line and reject if it doesn't match ExpectedUser
        $actualLine = ($log -split "`n") | Where-Object { $_ -match 'ACTUAL_USER ' } | Select-Object -First 1
        if (-not $actualLine) {
            Write-Output "FAIL: result log has no ACTUAL_USER line"
            exit 106
        }
        $actualUser = ($actualLine -split 'ACTUAL_USER ')[1].Trim()
        $userMatch = ($actualUser -eq $ExpectedUser) -or ($actualUser -like "*\$ExpectedUser")
        if (-not $userMatch) {
            Write-Output ("FAIL: result log shows actual user = '" + $actualUser + "' but expected '" + $ExpectedUser + "'")
            exit 106
        }

        if ($log -notmatch 'PASS all assertions green') {
            Write-Output "FAIL: result log does not contain PASS marker"
            Write-Output "--- result log ---"
            Write-Output $log
            exit 107
        }

        if ($taskExitCode -ne 0) {
            Write-Output ("FAIL: task LastTaskResult = " + $taskExitCode + " (expected 0)")
            exit 107
        }

        Write-Output "PASS: identity verified, all assertions green, file-ops succeeded"
        Write-Output ("  ACTUAL_USER:    " + $actualUser)
        Write-Output ("  ExpectedUser:   " + $ExpectedUser)
        Write-Output ("  RequiredGroup:  " + $RequiredGroup)
        Write-Output ("  ForbiddenGroup: " + $ForbiddenGroup)
        Write-Output ("  TaskExitCode:   " + $taskExitCode)
        exit 0

    } finally {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    }
}

# ============================================================================
# Dispatch
# ============================================================================
switch ($Mode) {
    'selfcheck' { Invoke-Selfcheck }
    'validate'  { Invoke-Validate }
}
