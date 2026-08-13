# Безопасность VPS (СРО-бот)

Обновлено: 06.08.2026

## Что включено на `147.45.225.70`

| Мера | Статус |
|------|--------|
| SSH только по ключу (пароль выключен) | `/etc/ssh/sshd_config.d/99-sro-hardening.conf` |
| UFW: входящие закрыты, SSH только с IP Паши | `82.204.178.85` → порт 22 |
| `config_keys.py` | `chmod 600`, владелец `srobot` |
| fail2ban (ssh) | активен |
| Пароль «Контакты отделов» | 16 символов (см. локальный `config_keys.py`) |

Повторный прогон hardening:

```bash
bash /opt/sro-bot/vps/harden_vps.sh ВАШ_IP
```

## Если сменился домашний IP

SSH перестанет пускать с нового адреса. Варианты:

1. **Timeweb консоль** (VNC/веб-терминал в панели) → добавить IP:
   ```bash
   ufw allow from НОВЫЙ_IP to any port 22 proto tcp comment 'SSH Pasha'
   ```
2. Или временно (осторожно): `ufw allow 22/tcp` — пока ключ-only, пароль всё равно не работает.

## OpenRouter — лимит на ключе (ручная настройка)

1. https://openrouter.ai/keys  
2. Ключ **SRO-бот** (тот, что в `OPENROUTER_API_KEY`)  
3. **Credit limit** — например `$15–25` / месяц (под ваш объём)  
4. **Reset** — `monthly`  
5. Сохранить  

Без Management API key лимит ставится только в кабинете.

## Закрытые порты (после UFW)

- `8787` — MC AI bridge (ес понадобится снаружи — отдельное правило)
- `10050` — zabbix (мониторинг Timeweb)

## Не делать

- Не копировать Windows `config_keys.py` на VPS целиком (пути `SRO_FILES_DIR`).
- Не запускать бота локально с тем же `BOT_TOKEN` (409 conflict).
- Не коммитить `config_keys.py` в git.

## Смена пароля контактов

Локально `config_keys.py` → на VPS:

```powershell
scp @ssh vps/set_contacts_password_vps.py root@147.45.225.70:/root/
# отредактировать NEW= в скрипте или config_keys на VPS
ssh @ssh root@147.45.225.70 "python3 /root/set_contacts_password_vps.py"
```

Перезапуск бота не нужен — пароль читается с диска при входе в «Контакты».
