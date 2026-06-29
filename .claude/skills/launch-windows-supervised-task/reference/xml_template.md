# Reference XML template

> Reference for [`/launch-windows-supervised-task`](../SKILL.md). Moved out of the main skill (2026-06-29) to keep the execution path tight; content unchanged. Operator commands **Step 2** writes this template out (UTF-16 LE BOM, tokens replaced).

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
