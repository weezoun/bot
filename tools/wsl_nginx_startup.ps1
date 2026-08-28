# Ensures WSL2 (Ubuntu, hosting nginx which reverse-proxies
# trading.weezoun.com to this Windows box's Flask app) is up after every
# boot, and re-points the Windows-side port forward at WSL2's CURRENT
# private IP.
#
# 2026-08-28: WSL2's Ubuntu was uninstalled/reinstalled by the user (fresh
# distro, new user 'capta', old user 'weezoun' and its home dir/nginx/
# weezoun-website content all gone). Full setup redone from scratch: nginx
# + certbot + openssh-server reinstalled, /etc/nginx/sites-available/
# trading-bot recreated as its OWN separate file (never merged into
# weezoun-website's config, per standing instruction), rate-limit zones in
# /etc/nginx/conf.d/trading-bot-ratelimit.conf, SSL re-issued via certbot
# (worked immediately - confirms the Cloudflare DNS record for
# trading.weezoun.com is still Proxied). This script's embedded sudo
# password below updated to match the new user's password. Rebuilding
# weezoun-website itself was explicitly OUT of scope for this pass — only
# the bot's own nginx/dashboard setup was restored.
# REASON this exists, 2026-08-16: after a genuine Windows restart (not
# the softer restarts used earlier this session), WSL2 came back up in
# standard NAT mode with a private IP (172.25.x.x) instead of the
# bridged/shared-public-IP setup this whole domain setup was built on
# and tested against (198.44.118.152 on both Windows AND WSL2's own
# eth0) — that shared-IP behavior turned out to be a one-boot fluke, not
# a stable configuration, and there was no port-forwarding fallback in
# place, so the domain was fully unreachable (Cloudflare 522) until
# fixed by hand. WSL2's private IP can also change between boots (it's
# a NAT-assigned address, not fixed) — that's WHY this has to re-run
# fresh on every boot rather than being a one-time netsh command.
#
# What it does:
#   1. Runs any `wsl` command, which starts the WSL2 VM if not already
#      running (WSL2 distros are otherwise lazy-started).
#   2. Starts nginx inside it if not already running.
#   3. Reads WSL2's current private IP.
#   4. Replaces the Windows netsh portproxy rules (198.44.118.152:80/443
#      -> that current WSL2 IP:80/443) with the fresh address — this is
#      what actually lets external traffic (Cloudflare, proxied) reach
#      nginx at all. The existing Windows Firewall rule scoping 80/443
#      to Cloudflare's IP ranges only (see bot-deployment-infra memory)
#      still applies on top of this and is untouched by this script.
#
# 2026-08-20: also forwards port 22 the same way, for sshd inside WSL2 —
# needed so GitHub Actions can reach the VPS to run weezoun-website's
# deploy.sh. Same drift problem, same fix. Port 22's Windows Firewall
# rule is intentionally open to any source (GitHub Actions has no fixed
# IP range), unlike 80/443's Cloudflare-only scoping.

Start-Sleep -Seconds 10  # give the network adapters a moment right after logon

wsl -- true

Start-Sleep -Seconds 5

wsl -- bash -c "pgrep -x nginx > /dev/null || echo 'Prison3R!' | sudo -S nginx"

Start-Sleep -Seconds 2

$wslIp = (wsl -- bash -c "ip -4 addr show eth0 | grep -oP '(?<=inet\s)\d+(\.\d+){3}'").Trim()

if ($wslIp -match '^\d+\.\d+\.\d+\.\d+$') {
    netsh interface portproxy delete v4tov4 listenport=80 listenaddress=198.44.118.152 2>$null | Out-Null
    netsh interface portproxy delete v4tov4 listenport=443 listenaddress=198.44.118.152 2>$null | Out-Null
    netsh interface portproxy delete v4tov4 listenport=22 listenaddress=198.44.118.152 2>$null | Out-Null
    netsh interface portproxy add v4tov4 listenport=80 listenaddress=198.44.118.152 connectport=80 connectaddress=$wslIp | Out-Null
    netsh interface portproxy add v4tov4 listenport=443 listenaddress=198.44.118.152 connectport=443 connectaddress=$wslIp | Out-Null
    netsh interface portproxy add v4tov4 listenport=22 listenaddress=198.44.118.152 connectport=22 connectaddress=$wslIp | Out-Null
    Add-Content -Path "c:\bot\logs\wsl_nginx_startup.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') OK - portproxy set to $wslIp"
} else {
    Add-Content -Path "c:\bot\logs\wsl_nginx_startup.log" -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') FAILED - could not read WSL2 IP (got: '$wslIp')"
}
