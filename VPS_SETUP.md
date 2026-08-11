# VPS для СРО-бота — пошагово

Бот на сервере в EU отвечает за **1–2 сек** без домашнего VPN.

## Шаг 1. Аренда VPS (15 мин)

Подойдёт любой из:

| Провайдер | Цена | Регион |
|-----------|------|--------|
| [Hetzner](https://www.hetzner.com/cloud) | ~€4/мес | Falkenstein / Helsinki |
| [Timeweb Cloud](https://timeweb.cloud) | ~350 ₽/мес | NL / PL |
| [Selectel](https://selectel.ru) | ~400 ₽/мес | — |

**Параметры:**
- OS: **Ubuntu 22.04** или **24.04**
- RAM: **1 GB** достаточно
- Диск: **10–20 GB**

После создания запишите: **IP**, **логин** (обычно `root`), **пароль** или SSH-ключ.

---

## Шаг 2. Первый вход (2 мин)

PowerShell на вашем ПК:

```powershell
ssh root@ВАШ_IP
```

При первом входе спросит fingerprint — `yes`.

---

## Шаг 3. Подготовка сервера (5 мин)

На VPS:

```bash
mkdir -p /opt/sro-bot
```

На **Windows** (из папки GOLD):

```powershell
cd "C:\Users\User\OneDrive\Рабочие\GOLD"
.\vps\upload_to_vps.ps1 -VpsIp "ВАШ_IP"
```

Скрипт:
- остановит **локальный** бот (иначе будет 409 Conflict)
- зальёт код, реестр, папку `sro files`

---

## Шаг 4. Установка на VPS (5 мин)

На VPS:

```bash
bash /opt/sro-bot/vps/install.sh
```

Отредактируйте ключи (если путь Windows остался в config_keys):

```bash
nano /opt/sro-bot/config_keys.py
```

Должно быть:

```python
SRO_FILES_DIR = "/opt/sro-bot/sro_data"
```

---

## Шаг 5. Запуск (1 мин)

```bash
systemctl start sro-bot
systemctl status sro-bot
```

Лог в реальном времени:

```bash
journalctl -u sro-bot -f
```

Должно появиться: `🚀 Бот запускается...`

Проверьте бота в Telegram — ответы должны быть **быстрыми**.

---

## Полезные команды

```bash
systemctl restart sro-bot   # перезапуск
systemctl stop sro-bot      # остановка
journalctl -u sro-bot -n 50 # последние 50 строк лога
```

---

## Обновление бота с ПК

1. Остановите локальный бот (не запускайте параллельно с VPS!)
2. `.\vps\upload_to_vps.ps1 -VpsIp "ВАШ_IP"`
3. На VPS: `systemctl restart sro-bot`

---

## Важно

- **Один бот = один процесс.** Либо VPS, либо домашний ПК — не оба сразу.
- VPN на телефоне для Telegram можно оставить; **бот на VPS VPN не нужен**.
- Позже можно добавить ночное обновление реестра (cron) — напишите, когда будете готовы.
