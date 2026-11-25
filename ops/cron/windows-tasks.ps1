# Phantom Fleet - Windows Task Scheduler registration.
#
# Run elevated. Registers one Scheduled Task per job in ops/cron/schedule.py.
# A matching task that already exists is overwritten; -Unregister removes
# the whole bundle.
#
# Usage:
#     .\ops\cron\windows-tasks.ps1                           # install
#     .\ops\cron\windows-tasks.ps1 -Unregister               # remove
#     .\ops\cron\windows-tasks.ps1 -PfRoot 'D:\pf' -Py 'python.exe'
#
# Each task runs as the current user (whatever started the script),
# whether or not the user is logged on. Logs go to $PfRoot\logs\cron-<job>.log.

[CmdletBinding()]
param(
    [string]$PfRoot = "C:\Users\admin\Desktop\PhantomFleet\phantom-fleet-clone",
    [string]$Py = "python.exe",
    [string]$Prefix = "PhantomFleet",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$jobs = @(
    @{Name="target_hydrate";     Minutes=1;      Argv="-m ops.targets.hydrator --apply --max 200"}
    @{Name="dispatch";           Minutes=1;      Argv="-m ops.dispatch.worker --apply --max 25"}
    @{Name="recovery";           Minutes=5;      Argv="-m ops.sched.recovery --apply"}
    @{Name="proxy";              Minutes=15;     Argv="-m ops.sched.proxy --apply --register trumpproxies_yuge"}
    @{Name="scheduler_tick";     Minutes=360;    Argv="-m ops.sched.tick --apply"}
    @{Name="replacement";        Minutes=360;    Argv="-m ops.sched.replacement --apply"}
    @{Name="weekly_commitment";  Minutes=10080;  Argv="-c 'from ops.intel import chain; print(chain.make_commitment())'"}
)

$logDir = Join-Path $PfRoot "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

foreach ($job in $jobs) {
    $taskName = "$Prefix-$($job.Name)"
    if ($Unregister) {
        try {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
            Write-Host "removed $taskName"
        } catch {
            Write-Host "no task $taskName (skipped)"
        }
        continue
    }

    $logFile = Join-Path $logDir ("cron-" + $job.Name + ".log")
    # cmd.exe /c lets us redirect both stdout and stderr to the log in
    # one place. PowerShell's own redirection would need to rewrap the
    # python invocation.
    $cmd = "cmd.exe"
    $cmdArgs = "/c cd /d `"$PfRoot`" && `"$Py`" $($job.Argv) >> `"$logFile`" 2>&1"

    $action  = New-ScheduledTaskAction -Execute $cmd -Argument $cmdArgs
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(30) `
        -RepetitionInterval (New-TimeSpan -Minutes $job.Minutes)
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

    try { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop } catch {}
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Phantom Fleet $($job.Name)" | Out-Null
    Write-Host "installed $taskName every $($job.Minutes) min  ->  $logFile"
}

if (-not $Unregister) {
    Write-Host ""
    Write-Host "All tasks live under Task Scheduler\$Prefix-*"
    Write-Host "Tail logs with: Get-Content -Wait -Tail 20 $logDir\cron-dispatch.log"
}
