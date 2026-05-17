---
name: launch-windows-supervised-task
description: Launch a long-running supervised Python daemon via Windows Task Scheduler — pythonw vs python, UTF-16 BOM XML, PYTHONPATH self-bootstrap, WinError 5 retry, .tmp cleanup-on-init, LogonType choice, schtasks elevation. Use when registering a Phase 7a-H2 live runner, Stage-5-equivalent field stress, basket_pipeline live runner, TS_Execution H2 shim, or any background daemon that must survive logoff / reboot. NOT for one-shot scripts.
---

# Launch a Windows-Supervised Long-Running Task

This skill captures the complete discipline for registering a Python daemon under Windows Task Scheduler. **Every gotcha listed below cost ~30 min of debugging on 2026-05-15.** Following the skill saves that cost on every subsequent deploy.

## When to use this skill (decision rule)

| Scenario | Use this skill? |
|---|---|
| Process must run for hours / days continuously | **Yes** |
| Must auto-restart on crash | **Yes** |
| Must auto-resume on logon / boot | **Yes** |
| Must survive screen lock / user logoff | **Yes** |
| State persists across restarts | **Yes** |
| One-shot script (< 30 min, runs once) | No — just run in foreground |
| Script needs a visible console | No — use foreground or a `.bat` |
| Need real-time stdout streaming | No — pythonw silences stdout |
| Quick `cron`-style poll every N minutes | Maybe — Task Scheduler works but a simpler `.bat` + Startup folder may suffice |

**Concrete examples that this skill applies to:**
- TS_SignalValidator validator (Stage 5)
- basket_pipeline live runner (Phase 7a-H2 Step 1)
- TS_Execution H2 shim (Phase 7a-H2 Step 2)
- heartbeat staleness monitor
- Any future strategy's live MT5 adapter

---

## The five hard-won lessons (apply ALL five)

### 1. Use `pythonw.exe`, not `python.exe`

`python.exe` is a console-subsystem binary. Even with `LogonType=InteractiveToken` and no visible console, Windows routes Ctrl-events (including spurious ones from session/console transitions) to it. Result: process exits with `STATUS_CONTROL_C_EXIT` (0xC000013A) after a few minutes — looks like the task died silently. Task Scheduler reports "successfully finished" (EID 102) because *Windows* terminated cleanly.

**Always:** `<Command>C:\Users\faraw\AppData\Local\Programs\Python\Python311\pythonw.exe</Command>`

Trade-off: `pythonw` has no stdin/stdout/stderr by default. Configure logging to a file via Python's `logging` module if you need diagnostics. Decision/heartbeat files are the audit surface; print() output is peripheral.

### 2. UTF-16 LE BOM encoding for the XML

`schtasks /Create /XML` is a native Win32 tool that expects UTF-16 LE with BOM (declaration `encoding="UTF-16"`). UTF-8 is rejected with "ERROR: The task XML is malformed." or "unable to switch the encoding".

**Always write with:**
```powershell
[System.IO.File]::WriteAllText($xml_path, $xml_content, [System.Text.UnicodeEncoding]::new($false, $true))
```

Verify the first 4 bytes are `FF-FE-3C-00`:
```powershell
[BitConverter]::ToString([System.IO.File]::ReadAllBytes($xml_path)[0..3])
```

### 3. Self-bootstrap `PYTHONPATH` inside the script

Task Scheduler does NOT propagate `PYTHONPATH` from the user's shell. A task running `python script.py` lands with `sys.path = [<script dir>, stdlib, site-packages]` only. Any `from <package>.X import Y` where `<package>` lives in a parent dir fails with `ModuleNotFoundError`. The task immediately exits code 1 — visible only via `LastTaskResult: 1`, no log.

**Always at the top of the entry-point script:**
```python
import sys
from pathlib import Path

_REPO_PARENT = Path(__file__).resolve().parent.parent  # adjust depth as needed
if str(_REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(_REPO_PARENT))

# Now safe to import the package
from <your_package>.X import Y  # noqa: E402
```

### 4. Atomic file writes need WinError 5 retry

If your task writes files frequently (decision files, heartbeats, action logs), Windows Defender / file-explorer preview / antivirus will transiently lock the destination during write-then-rename, causing `os.replace` to raise `OSError(13)` with `winerror=5` (ERROR_ACCESS_DENIED). After hundreds of successful writes, one fails — task FAIL-CLOSEDs.

**Always wrap the rename:**
```python
def atomic_replace_with_retry(src: str, dst: str, max_attempts: int = 5) -> None:
    backoff = 0.010
    for attempt in range(max_attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            if getattr(e, "winerror", None) not in (5, 32) or attempt == max_attempts - 1:
                raise
            time.sleep(backoff)
            backoff *= 2
```

Retries 5x on WinError 5 (ACCESS_DENIED) and 32 (SHARING_VIOLATION). Non-retriable errors (ENOSPC etc.) propagate on the first attempt.

Reference: `TS_SignalValidator/atomic_io.py::atomic_replace_with_retry`.

### 5. Cleanup orphan `.tmp` files on init

A SIGKILL / hard-reset between `tempfile.mkstemp` and `os.replace` leaves a `.foo.*.tmp` file on disk. The atomic-rename contract is "the FINAL file is never torn" — NOT "no .tmp ever exists after crash". Post-crash debris is normal supervisor responsibility.

**Always at writer `__init__`:**
```python
for orphan in self.dir.glob(".<prefix>.*.tmp"):
    try:
        orphan.unlink()
    except OSError:
        pass  # locked by AV scan — leave; tempfile.mkstemp gives unique names
```

Reference: `TS_SignalValidator/decision_emitter.py::DecisionEmitter._cleanup_orphan_tmp_files`.

---

## Reference XML template

Save as UTF-16 LE BOM (per Lesson 2). Replace `${TOKENS}` per machine.

```xml
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>${TASK_DESCRIPTION}</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger><Enabled>true</Enabled></BootTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>${MACHINE}\${USER}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>${USER_SID}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT2M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>C:\Users\faraw\AppData\Local\Programs\Python\Python311\pythonw.exe</Command>
      <Arguments>${SCRIPT_NAME} ${SCRIPT_ARGS}</Arguments>
      <WorkingDirectory>${SCRIPT_WORKING_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
```

### Why each `<Settings>` matters

| Setting | Value | Why |
|---|---|---|
| `MultipleInstancesPolicy` | `IgnoreNew` | Single-writer rule. Logon trigger fires every logon; ignore if previous instance still running. |
| `DisallowStartIfOnBatteries` / `StopIfGoingOnBatteries` | `false` | Survives laptop unplug |
| `StartWhenAvailable` | `true` | Handles missed run after sleep / hibernate |
| `ExecutionTimeLimit` | `PT0S` | Continuous (no auto-stop) |
| `RestartOnFailure` | `PT2M` × `3` | Auto-recovery from crash |
| `LogonType=InteractiveToken` | (no creds) | Runs as your normal logon; no Password storage; no smoke test required |
| `RunLevel=LeastPrivilege` | (non-elevated) | Doesn't unnecessarily request admin |
| `BootTrigger + LogonTrigger` | both | Boot fires before user logon; logon trigger fires when user logs in |

---

## Operator commands

### Step 1: Gather machine values (no admin needed)

```powershell
whoami
$sid = (Get-WmiObject Win32_UserAccount -Filter "Name='$((whoami).Split('\')[1])'" | Select-Object -First 1).SID
Write-Output $sid
(Get-Command python).Path  # confirm python install dir; pythonw.exe is alongside
```

### Step 2: Generate filled XML (no admin needed)

Write the template to `tools/<scope>/<task>.local.xml` using `[System.IO.File]::WriteAllText(... [System.Text.UnicodeEncoding]::new($false, $true))`. Verify FF-FE-3C-00 first bytes.

### Step 3: Register the task — ONE elevated command

```powershell
schtasks /Create /TN "${TASK_NAME}" /XML "${ABSOLUTE_PATH_TO_XML}" /F
```

Expected output: `SUCCESS: The scheduled task "${TASK_NAME}" has successfully been created.`

`schtasks /Create` requires elevation. `Set-ScheduledTask` (PowerShell cmdlet) ALSO requires elevation — there is no admin-free alternative for task registration.

### Step 4: Start the task (no admin needed)

```powershell
schtasks /Run /TN "${TASK_NAME}"
```

### Step 5: Verify the task is genuinely running

```powershell
# State + last result
Get-ScheduledTask -TaskName "${TASK_NAME}" | Format-List State, TaskName
Get-ScheduledTaskInfo -TaskName "${TASK_NAME}" | Format-List LastRunTime, LastTaskResult, NumberOfMissedRuns

# Process check (the actual python(w) process)
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like "*${SCRIPT_NAME}*" } |
  Select-Object ProcessId, @{n='AgeMin';e={[math]::Round(((Get-Date)-(Get-Date $_.CreationDate)).TotalMinutes,1)}}
```

### Interpreting `LastTaskResult`

| Value | Meaning |
|---|---|
| `0` | Task completed successfully (clean exit) |
| `267009` (= `0x41301`) | Task is **currently running** — NOT a failure |
| `267011` (= `0x41303`) | Task has not yet run (state Ready, never triggered) |
| `0xC000013A` | STATUS_CONTROL_C_EXIT — process killed by Ctrl-event signal. **You're using `python.exe` instead of `pythonw.exe`.** Apply Lesson 1. |
| `1` | Generic Python exit error — usually `ModuleNotFoundError`. Apply Lesson 3 (PYTHONPATH self-bootstrap). |
| Other non-zero | Real Python exception. Check the script's logging-to-file output (pythonw silences stdout). |

### Interpreting Task Scheduler events

```powershell
Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' -MaxEvents 50 |
  Where-Object { $_.Message -like '*${TASK_NAME}*' } |
  Select-Object TimeCreated, Id, @{n='Msg';e={($_.Message -split "`n")[0]}} |
  Format-Table -AutoSize
```

Key event IDs:
- **EID 100** — Task started (instance ID logged)
- **EID 110** — Task launched action
- **EID 200** — Task launched the executable
- **EID 102** — Task **finished** (ANY exit; could be clean OR crash). Check `LastTaskResult` to disambiguate.
- **EID 201** — Task **completed** (action finished)
- **EID 129** — Launch detail
- **EID 325** — Queued
- **EID 140** — Task definition updated
- **EID 106** — Task registered

---

## Updating an existing task

`schtasks /Change` exists but has limited scope. Cleanest pattern: regenerate the XML + `schtasks /Create /F` (the `/F` overwrites). Same admin requirement as initial register.

`Set-ScheduledTaskAction` requires admin too. There is NO admin-free way to modify a scheduled task on Windows.

If the task is currently running and you need to change it:
```powershell
schtasks /End /TN "${TASK_NAME}"          # stop running instance (no admin)
# (Now do the schtasks /Create /F /XML ... admin command)
schtasks /Run /TN "${TASK_NAME}"          # restart (no admin)
```

---

## Anti-patterns

- **Don't skip the smoke test ONLY when changing IDENTITY.** Per CLAUDE.md HARD PROHIBITION: any change to run-as identity or LogonType requires `tools/scheduled_task_identity_smoke.ps1 -Mode validate`. **Same-user tasks at default LogonType=InteractiveToken don't qualify** — no identity migration. The 2026-05-07 incident was a service-account swap, not a same-user task.
- **Don't assume `LastTaskResult: 0` means the script ran successfully.** It only means Windows gave the task a clean shutdown. The script may have crashed in a way Windows interprets as "clean" (e.g., `STATUS_CONTROL_C_EXIT`). Cross-check with the actual process check + script's own log file.
- **Don't trust `EID 102 "successfully finished"` as proof of success.** EID 102 = "the task instance ended" (regardless of exit code).
- **Don't put your script in a location whose import resolution depends on PYTHONPATH.** Self-bootstrap as Lesson 3.
- **Don't use `Set-ScheduledTask`-via-PowerShell as an admin-free alternative to `schtasks /Create`.** Both require elevation. There is no admin-free path.
- **Don't run the staleness monitor in a Bash background that exits when your shell exits.** If you need an external supervisor, register IT as a separate scheduled task too.
- **Don't forget to add `pythonw.exe` to your antivirus exclusion list** if Defender is treating frequent file writes as suspicious. (Symptom: WinError 5 retries fire constantly even with the proper retry helper.)

---

## Related skills + cross-references

- `/repo-cleanup-refactor` — when refactoring code that runs as a scheduled task, follow that skill's "don't run during active scheduled task" rules.
- `/session-close` — periodic skills (`§8b.i`) reference `/system-health-maintenance` Phase 1 health audit which catches scheduled-task drift.
- `outputs/system_reports/01_system_architecture/H2_LIVE_EXECUTION_PLAN.md` §1 (basket_pipeline live runner) and §2 (TS_Execution H2 shim) — both will use this skill when they're built.
- `TS_SignalValidator/tools/stage5_setup/STAGE_5_DISRUPTION_PLAN.md` — the canonical operator runbook that THIS skill underlies.

---

## Recovery

If a task is misbehaving:
1. `schtasks /End /TN "${TASK_NAME}"` to stop the current instance (no admin)
2. Read the script's log file (you DID configure logging to file, right?)
3. Cross-reference with `Get-WinEvent` Task Scheduler events (commands above)
4. If the script is fundamentally broken: `schtasks /Delete /TN "${TASK_NAME}" /F` (admin) to remove the task; fix script; re-register from scratch
5. Process state across restarts: ensure your script handles "fresh start with leftover state files" gracefully (Lesson 5 + idempotency tokens)

---

## Friction log

Protocol: see [`../SELF_IMPROVEMENT.md`](../SELF_IMPROVEMENT.md).

| Date | Friction (1 line) | Edit landed |
|---|---|---|
| _none yet_ | | |
