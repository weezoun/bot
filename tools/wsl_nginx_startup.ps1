# Keeps WSL2 (Ubuntu) reachable from native Windows nginx, self-healing
# automatically whenever WSL2's internal IP changes.
#
# ARCHITECTURE CHANGED 2026-08-29: trading.weezoun.com and weezoun.com
# both moved OFF WSL2 entirely onto native Windows nginx (C:\nginx,
# Windows Service "nginx") - the fragile netsh-portproxy-for-80/443 path
# this script used to maintain is GONE. Native nginx now owns the public
# IP's 80/443 directly. WSL2 nginx keeps running underneath purely as a
# FALLBACK/GENERAL-PURPOSE BACKEND: any site name native nginx doesn't
# recognize (i.e. any FUTURE project set up inside WSL2 with its own
# nginx server block there) falls through to WSL2 automatically, via:
#   - HTTP (port 80): C:\nginx\conf\weezoun-passthrough.conf's
#     default_server proxy_pass
#   - HTTPS (port 443): nginx.conf's top-level stream{} block's SNI map
#     `default` entry (ssl_preread passthrough, no decryption)
# Both of those currently have WSL2's IP address hardcoded, which is
# exactly the same "goes stale when WSL2's IP changes" problem the OLD
# portproxy-based version of this script existed to solve - just moved
# one layer up. This script now targets THAT instead of portproxy.
#
# REASON this needs to keep self-healing automatically, not just once:
# WSL2's IP can change any time the underlying Host Network Service
# (HNS) restarts - confirmed via Windows Event Log, happens
# intermittently and unpredictably, not just at boot/logon. The user's
# stated need: they intend to host OTHER, future projects inside WSL2
# too, behind this same generic fallback - if the fallback's target IP
# goes stale, EVERY project living there becomes unreachable, not just
# one specific site. Fixed by running this on a short RECURRING schedule
# (see the matching Scheduled Task, not just "At logon" like before),
# so a mid-session HNS restart self-heals within a couple minutes
# instead of needing a manual fix or a full logon cycle.
#
# Port 22's portproxy (SSH into WSL2, used by weezoun-website's GitHub
# Actions deploy pipeline) is a SEPARATE, still-real need - kept exactly
# as before, also self-healed here.
#
# Idempotent by design: does nothing (no nginx reload, no portproxy
# churn) unless something has actually changed - safe to run every
# couple of minutes indefinitely without disrupting live connections.

$logPath = "c:\bot\logs\wsl_nginx_startup.log"
$nginxConfDir = "C:\nginx\conf"
$passthroughFile = "$nginxConfDir\weezoun-passthrough.conf"
$nginxConfFile = "$nginxConfDir\nginx.conf"
$publicIp = "198.44.118.152"

function Log($msg) {
    Add-Content -Path $logPath -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg"
}

wsl -- true
Start-Sleep -Seconds 2
wsl -- bash -c "pgrep -x nginx > /dev/null || echo 'Prison3R!' | sudo -S nginx"

$wslIp = (wsl -- bash -c "ip -4 addr show eth0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}'").Trim()

if ($wslIp -notmatch '^\d+\.\d+\.\d+\.\d+$') {
    Log "FAILED - could not read WSL2 IP (got: '$wslIp')"
    exit 1
}

$changed = $false

# --- Port 22 portproxy (SSH into WSL2 - GitHub Actions deploy pipeline) ---
$current22 = (netsh interface portproxy show v4tov4 | Select-String "^$publicIp\s+22\s+(\S+)\s+22").Matches
$current22Ip = if ($current22.Count -gt 0) { $current22[0].Groups[1].Value } else { $null }
if ($current22Ip -ne $wslIp) {
    netsh interface portproxy delete v4tov4 listenport=22 listenaddress=$publicIp 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenport=22 listenaddress=$publicIp connectport=22 connectaddress=$wslIp | Out-Null
    $changed = $true
    Log "portproxy 22 updated: $current22Ip -> $wslIp"
}

# --- Native nginx's WSL2 fallback backend (HTTP passthrough + stream SNI default) ---
$passthroughContent = Get-Content $passthroughFile -Raw
$nginxConfContent = Get-Content $nginxConfFile -Raw

$ipPattern = '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'

$newPassthrough = $passthroughContent -replace "proxy_pass http://$ipPattern`:80;", "proxy_pass http://${wslIp}:80;"
$newNginxConf = $nginxConfContent -replace "default\s+$ipPattern`:443;", "default             ${wslIp}:443;"

if ($newPassthrough -ne $passthroughContent -or $newNginxConf -ne $nginxConfContent) {
    Set-Content -Path $passthroughFile -Value $newPassthrough -NoNewline
    Set-Content -Path $nginxConfFile -Value $newNginxConf -NoNewline

    $testResult = & "C:\nginx\nginx.exe" -t -p "C:\nginx" 2>&1
    if ($LASTEXITCODE -eq 0) {
        # Structural change (stream{} backend address) needs a full
        # restart, not just -s reload, to take effect reliably.
        Restart-Service nginx -ErrorAction SilentlyContinue
        $changed = $true
        Log "nginx WSL2-fallback IP updated -> $wslIp, service restarted"
    } else {
        Log "FAILED - nginx config test failed after IP patch, NOT restarting: $testResult"
    }
}

if (-not $changed) {
    Log "OK - no change needed (WSL2 IP still $wslIp)"
}
