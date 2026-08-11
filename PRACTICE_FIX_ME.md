# Упражнение: починить бота (безопасно)

Это **не prod**. Поломка включается только файлом `practice_bug_local.py` на вашем ПК.  
На сервер IT этот файл **не заливает** — боевой бот не затронут.

---

## Что сейчас «сломано»

При **`PRACTICE_ACTIVE = True`** в `practice_bug_local.py` (файл уже создан у вас):

- запрос **`размеры взносов`** снова отвечает про партнёра **НОСО**, а не про таблицу взносов;
- `python routing_regression.py` падает на строке **`[no_partner]`**.

Это **тот же класс бага**, что вы уже ловили в Telegram (подстрока «носо» в «взносов»).

---

## Как тренироваться

1. **Перезапустите бота** (`STOP_BOT.bat` → `START_BOT.bat`).
2. В Telegram отправьте: **`размеры взносов`** — убедитесь, что ответ про НОСО (поломка есть).
3. Почините **сами** (Cursor / ИИ как в работе куратора). Подсказки по уровням — ниже.
4. Проверка:
   - `python routing_regression.py` — все OK;
   - в Telegram снова **`размеры взносов`** — взносы / сайт, не НОСО.
5. **Выключите учебный режим:** в `practice_bug_local.py` → `PRACTICE_ACTIVE = False`  
   или **удалите** `practice_bug_local.py`.

Код в `partners_data.py` после правки должен **остаться правильным** (как до упражнения).

---

## Подсказки (открывайте по одной)

<details>
<summary>1. С чего начать</summary>

Симптом — **партнёры**, значит смотрите не справочник и не FAQ, а модуль **`partners_data.py`** и порядок в **`get_ai_response`** (партнёры проверяются первыми).
</details>

<details>
<summary>2. Как воспроизвести без Telegram</summary>

```text
python routing_regression.py
```

или в Python:

```python
from partners_data import match_partner_query
print(match_partner_query("размеры взносов"))
```

Должно быть `None`, сейчас — словарь с НОСО.
</details>

<details>
<summary>3. В чём суть бага</summary>

Алиас **`носо`** находится **внутри слова «взносов»**. Нужны **границы слова** и/или **не искать партнёра**, если в запросе «взнос».
</details>

<details>
<summary>4. Где учебный переключатель</summary>

Файлы **`practice_bug.py`** + **`practice_bug_local.py`**.  
В `partners_data.py` есть ветки `is_practice_active()` — при починке верните **нормальную** логику и выключите `PRACTICE_ACTIVE`.
</details>

---

## Что нельзя ломать в упражнении

- не трогайте **`config_keys.py`** (токены);
- не коммитьте **`practice_bug_local.py`** (он в `.gitignore`);
- на VPS не создавайте `practice_bug_local.py`.

---

*После упражнения можно удалить `practice_bug_local.py` и оставить проект как обычно.*
