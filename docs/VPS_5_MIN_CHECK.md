# VPS 5-minute check

Server: `msk-1-vm-wwft` (Москва)
IP: `201.24.125.236`
Service: `sro-bot`
Было NL: `147.45.225.70` — бот там выключен

## 1) Quick status

```powershell
ssh root@201.24.125.236 "systemctl is-active sro-bot"
```

Expected: `active`

## 2) Restart bot

```powershell
ssh root@201.24.125.236 "systemctl restart sro-bot && systemctl status sro-bot --no-pager"
```

## 3) Last log lines

```powershell
ssh root@201.24.125.236 "journalctl -u sro-bot -n 50 --no-pager"
```

## 4) Live logs (Ctrl+C to stop)

```powershell
ssh root@201.24.125.236 "journalctl -u sro-bot -f"
```

## 5) Deploy update from PC

```powershell
cd "C:\Users\User\OneDrive\Рабочие\GOLD"
.\vps\upload_to_vps.ps1 -VpsIp "201.24.125.236"
ssh root@201.24.125.236 "systemctl restart sro-bot"
```

## If bot does not reply

1. Check service status (`is-active`).
2. Check last logs (`journalctl -n 50`).
3. Restart service.
4. Test `/start` in Telegram.

## Important

- Do not run the same bot token on PC and VPS at the same time.
- Keep one active VPS only (`Inventive Ganymede`).
- Before major edits run local backup: `C:\BACKUP_WORK\START_BACKUP.bat`.
- Nightly reestr sync: `sro-reestr-sync.timer` (02:00 MSK). Logs: `/opt/sro-bot/logs/reestr_daily_*.log`.
