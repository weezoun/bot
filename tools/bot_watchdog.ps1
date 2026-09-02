# Watchdog for BOTH trading bots (demo c:\bot, live c:\bot - Live),
# 2026-08-31 - requested directly after the live bot crashed silently
# (WSL2/vmmem memory pressure, see c:\bot - Live\versions\v2.18\NOTES.md)
# and sat down undetected for 40+ minutes. Neither bot's own scheduled
# task actually catches a real crash: RestartOnFailure only fires on a
# task-level failure, but the wrapper's `Start-Process -Wait` reports
# success to Task Scheduler the moment the wrapped pythonw.exe exits,
# crash or not - so a dead bot process was never treated as a "failure"
# at all. This is a genuinely independent check instead: a real HTTP
# request to each bot's own dashboard (catches a HUNG process too, not
# just a dead one), on a short recurring interval (see the matching
# "BotWatchdog" Scheduled Task, PT5M - same repeating-trigger pattern
# already used by WSLNginxAutoStart).
#
# Each bot's check+restart is fully independent (own function call, own
# task name, own port) - one failing never touches or restarts the other.
#
# Notification: user asked for WhatsApp specifically; no WhatsApp/Twilio
# integration exists, so this uses ntfy.sh instead (free, no account
# needed) - the user subscribes their phone to this exact topic name in
# the ntfy app. Topic is a random string, not a guessable name, since
# ntfy.sh topics are public to anyone who knows the exact topic string.

$ntfyTopic = "weezoun-bots-1zbkcgxeti"
$logPath = "c:\bot\logs\watchdog.log"

function Log($msg) {
    Add-Content -Path $logPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
}

function Notify($msg) {
    try {
        Invoke-RestMethod -Uri "https://ntfy.sh/$ntfyTopic" -Method Post -Body $msg -TimeoutSec 10 -Headers @{Title="Trading Bot Watchdog"} | Out-Null
    } catch {
        Log "ntfy notify failed: $($_.Exception.Message)"
    }
}

function Check-Bot {
    param([string]$Name, [int]$Port, [string]$TaskName)

    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/login" -UseBasicParsing -TimeoutSec 8
        if ($r.StatusCode -eq 200) { return }
    } catch {}

    Log "$Name DOWN (port $Port not responding) - restarting $TaskName"
    Notify "$Name bot is DOWN - restarting it now"

    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 20

    try {
        $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/login" -UseBasicParsing -TimeoutSec 8
        if ($r2.StatusCode -eq 200) {
            Log "$Name back up after restart"
            Notify "$Name bot is back UP after restart"
            return
        }
    } catch {}

    Log "$Name still not responding after restart attempt"
    Notify "$Name bot restart attempted but still NOT responding - needs manual check"
}

Check-Bot -Name "Demo" -Port 5050 -TaskName "TradingBotAutoStart"
Check-Bot -Name "Live" -Port 5051 -TaskName "TradingBotLiveAutoStart"
