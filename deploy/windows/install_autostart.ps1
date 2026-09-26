# Run once in PowerShell from the repo folder:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install_autostart.ps1
# Registers a Task Scheduler job that starts the bot when you sign in and keeps it alive,
# and stops the laptop from sleeping while it is plugged in.

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$bat  = Join-Path $repo "deploy\windows\run_bot.bat"

$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`"" -WorkingDirectory $repo
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "TelegramTradingBot" -Action $action -Trigger $trigger `
    -Settings $settings -Description "24/7 Telegram + MT5 bot" -Force | Out-Null
Write-Host "Task 'TelegramTradingBot' registered (starts at sign-in)."

# Never sleep/hibernate on charger; closing the lid does nothing on charger.
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT
Write-Host "Power plan updated: no sleep on AC power, lid close = do nothing (on AC)."

Start-ScheduledTask -TaskName "TelegramTradingBot"
Write-Host "Bot started. Check it with /ping in Telegram."
