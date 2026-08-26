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

Write-Host "If sro-max-bot is active on VPS, stop local bot_MAX.py (same token)." -ForegroundColor Yellow
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='py.exe'" |
    Where-Object { $_.CommandLine -like '*bot_FINAL_GOLD*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$SroFiles = Join-Path $ProjectRoot "sro files"
if (-not (Test-Path $SroFiles)) {
    Write-Warning "Folder not found: $SroFiles. Upload plany/blanki manually later."
}

$RuntimeFiles = @(
    "bot_FINAL_GOLD.py",
    "bot_MAX.py",
    "max_api.py",
    "faq_menu_content.py",
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
    "info_list_quiz.py",
    "doc_checklist.py",
    "trusted_members.py",
    "sro_about.py",
    "sro_fees.py",
    "sro_contacts.py",
    "bot_disclaimers.py",
    "users_log.py",
    "feedback_log.py",
    "controller_access.py",
    "checko_client.py",
    "nrs_search_links.py",
    "doc_qa.py",
    "ai_rate_limit.py",
    "controller_ai.py",
    "prevent_sleep.py",
    "requirements.txt"
)

$missing = @()
foreach ($f in $RuntimeFiles) {
    if (-not (Test-Path $f)) {
        Write-Warning "Missing locally (keep VPS copy): $f"
        $missing += $f
    }
}
$RuntimeFiles = @($RuntimeFiles | Where-Object { Test-Path $_ })

# Жёсткий стоп: не залить bot без ИИ-помощника контролёра (голос/доки)

Write-Host "Checking prod SRO gate (15 SRO, unique sites)..." -ForegroundColor Cyan
& py -u (Join-Path $PSScriptRoot "check_prod_sro_gate.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Abort upload: prod SRO gate FAILED (урезанный/неверный набор СРО)"
}
Write-Host "Checking controller AI wiring..." -ForegroundColor Cyan
& py -u (Join-Path $PSScriptRoot "check_controller_ai_wired.py") (Join-Path $ProjectRoot "bot_FINAL_GOLD.py")
if ($LASTEXITCODE -ne 0) {
    Write-Error "Abort upload: controller AI (voice/docs) is NOT wired in bot_FINAL_GOLD.py"
}

$remote = "${VpsUser}@${VpsIp}:/opt/sro-bot/"
Write-Host "Uploading runtime files to $remote" -ForegroundColor Cyan

ssh "${VpsUser}@${VpsIp}" "mkdir -p /opt/sro-bot/sro_data/plany /opt/sro-bot/sro_data/blanki /opt/sro-bot/vps"

scp @RuntimeFiles $remote
scp reestr_cache.json $remote
scp -r vps $remote

# TLS for MAX API (корни Минцифры)
if (Test-Path (Join-Path $ProjectRoot "certs")) {
    scp -r certs "${VpsUser}@${VpsIp}:/opt/sro-bot/"
} else {
    Write-Warning "certs/ not found - MAX TLS may fail on VPS"
}

if (Test-Path $SroFiles) {
    scp -r "$SroFiles\plany" "${VpsUser}@${VpsIp}:/opt/sro-bot/sro_data/"
    if (Test-Path "$SroFiles\blanki") {
        scp -r "$SroFiles\blanki" "${VpsUser}@${VpsIp}:/opt/sro-bot/sro_data/"
    }
}

# Do not overwrite server secrets/path with local Windows config_keys.py.
# First deploy: create config on VPS manually from vps/config_keys.vps.example.py
Write-Host "Skip config_keys.py upload (keep VPS secrets and Linux SRO_FILES_DIR)." -ForegroundColor Yellow

Write-Host "Done. Upload finished." -ForegroundColor Green
Write-Host "First MAX on VPS: bash /opt/sro-bot/vps/install.sh" -ForegroundColor Yellow
Write-Host "Set MAX_BOT_TOKEN and MAX_CONTROLLER_IDS in /opt/sro-bot/config_keys.py" -ForegroundColor Yellow
Write-Host "Then: systemctl restart sro-bot sro-max-bot" -ForegroundColor Cyan
Write-Host "Check: systemctl is-active sro-bot sro-max-bot"
