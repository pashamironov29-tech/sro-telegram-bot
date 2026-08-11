param(
    [Parameter(Mandatory = $true)]
    [string]$VpsIp,
    [string]$VpsUser = "root"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
Set-Location $ProjectRoot

if (-not (Get-Command scp -ErrorAction SilentlyContinue)) {
    Write-Error "OpenSSH Client (scp) is required."
}

Write-Host "Stopping local bot process to avoid Telegram 409 conflict..." -ForegroundColor Yellow
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='py.exe'" |
    Where-Object { $_.CommandLine -like '*bot_FINAL_GOLD*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$SroFiles = Join-Path $ProjectRoot "sro files"
if (-not (Test-Path $SroFiles)) {
    Write-Warning "Folder not found: $SroFiles. Upload plany/blanki manually later."
}

$RuntimeFiles = @(
    "bot_FINAL_GOLD.py",
    "ai_assistant.py",
    "reestr_sync.py",
    "voprosy_faq.py",
    "sro_site_qa.py",
    "partners_data.py",
    "contacts_data.py",
    "contacts_access.py",
    "contacts_search.py",
    "sro_context.py",
    "sro_profiles.py",
    "blanki_sro.py",
    "info_list_fill.py",
    "trusted_members.py",
    "sro_about.py",
    "sro_fees.py",
    "sro_contacts.py",
    "users_log.py",
    "feedback_log.py",
    "controller_access.py",
    "checko_client.py",
    "nrs_search_links.py",
    "doc_qa.py",
    "prevent_sleep.py",
    "requirements.txt"
)

foreach ($f in $RuntimeFiles) {
    if (-not (Test-Path $f)) {
        Write-Error "Missing file: $f"
    }
}

$remote = "${VpsUser}@${VpsIp}:/opt/sro-bot/"
Write-Host "Uploading runtime files to $remote" -ForegroundColor Cyan

ssh "${VpsUser}@${VpsIp}" "mkdir -p /opt/sro-bot/sro_data/plany /opt/sro-bot/sro_data/blanki /opt/sro-bot/vps"

scp @RuntimeFiles $remote
scp reestr_cache.json $remote
scp -r vps $remote

if (Test-Path $SroFiles) {
    scp -r "$SroFiles\plany" "${VpsUser}@${VpsIp}:/opt/sro-bot/sro_data/"
    if (Test-Path "$SroFiles\blanki") {
        scp -r "$SroFiles\blanki" "${VpsUser}@${VpsIp}:/opt/sro-bot/sro_data/"
    }
}

# Do not overwrite server secrets/path with local Windows config_keys.py.
# First deploy: create config on VPS manually from vps/config_keys.vps.example.py
Write-Host "Skip config_keys.py upload (keep VPS secrets and Linux SRO_FILES_DIR)." -ForegroundColor Yellow

Write-Host "Done. On VPS run:" -ForegroundColor Green
Write-Host "  bash /opt/sro-bot/vps/install.sh"
Write-Host "  systemctl start sro-bot"
Write-Host "  journalctl -u sro-bot -f"
