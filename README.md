# English Flashcards (FastAPI)

Невеликий застосунок для вивчення англійських слів:

- реєстрація і вхід, кожен користувач бачить лише свої картки;
- картка = англійське слово + переклади. Перекладач пропонує всі варіанти, ви позначаєте потрібні.
  Якщо нічого не позначити, зберігаються 3 найпопулярніші. Можна додати свій варіант і пізніше змінити вибір;
- дві окремі гри у випадковому порядку: **EN → UA** (бачите слово, згадуєте переклад) і **UA → EN** (навпаки).
  Після «Показати відповідь» ви самі відмічаєте «Знав» або «Не знав», а статистика зберігається в картці.

## Структура

```
app/
  main.py        — усі ендпоінти API + віддача сторінки
  models.py      — таблиці users і cards
  db.py          — підключення (SQLite локально, Postgres через DATABASE_URL)
  auth.py        — хешування паролів і підписані токени
  translator.py  — перекладач (Google gtx → запасний MyMemory) з кешем
  schemas.py     — Pydantic-схеми
  static/index.html — мінімальний інтерфейс (vanilla JS)
```

### База даних

| users | cards |
|---|---|
| id, username (unique), password_hash, created_at | id, user_id → users.id, word, translations (JSON-список обраних), options (JSON-список усіх варіантів), correct_count, wrong_count, created_at |

Пара `(user_id, word)` унікальна: одне слово в одного користувача буде лише один раз.
Таблиці створюються автоматично при першому запуску.

### Як вбудовано перекладач

`GET /api/translate?word=run` спершу звертається до безкоштовного endpoint Google Translate
(`translate.googleapis.com/translate_a/single?client=gtx&dt=t&dt=bd`). Він працює без ключа і повертає словникові
варіанти з оцінкою популярності `score`, тож «3 найпопулярніші» — це основний переклад плюс варіанти з найбільшим score.
Це неофіційний API: він може обмежувати кількість запитів. Тоді спрацьовує запасний варіант, MyMemory
(безкоштовний, близько 5000 символів на день; з `MYMEMORY_EMAIL` ліміт більший).
Якщо обидва джерела недоступні, переклад можна ввести вручну.
Мову перекладу можна змінити змінною `TARGET_LANG` (за замовчуванням `uk`).

## Локальний запуск

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Відкрийте http://127.0.0.1:8000, а документацію API — на http://127.0.0.1:8000/docs.
Дані зберігаються у файлі `flashcards.db` поруч із проєктом.

Для локального підключення до Neon запустіть `neon init` — CLI збереже `DATABASE_URL` у `.env.local`,
який застосунок завантажує автоматично. Файл уже виключений із Git. Змінні середовища, задані поза файлом,
мають пріоритет.

Для продакшену задайте `SECRET_KEY` (будь-який довгий випадковий рядок):
`python -c "import secrets; print(secrets.token_hex(32))"`.

## Безкоштовний деплой: Render + Neon

Файлова система безкоштовного сервісу на Render не зберігається між перезапусками, тому SQLite там «забуде» всі картки.
Безкоштовний Postgres Render видаляється через 30 днів, тому базу краще тримати в Neon: там постійний безкоштовний план.

1. **Neon** (neon.com) → створіть проєкт → скопіюйте Connection string (`postgresql://...`).
2. Залийте проєкт на GitHub.
3. **Render** (render.com) → New → Blueprint → оберіть репозиторій (підхопиться `render.yaml`).
   Або New → Web Service:
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. У змінних середовища вкажіть `DATABASE_URL` = рядок з Neon і `SECRET_KEY` (Blueprint генерує його сам).

Обмеження: безкоштовний сервіс Render засинає після 15 хвилин без запитів, і перше відкриття після цього займає близько хвилини.

## API коротко

| Метод | Шлях | Що робить |
|---|---|---|
| POST | /api/auth/register, /api/auth/login | `{username, password}` → `{token}` |
| GET | /api/translate?word= | варіанти перекладу |
| GET/POST | /api/cards | список / створення `{word, translations?}` |
| PUT/DELETE | /api/cards/{id} | змінити обрані переклади / видалити |
| GET | /api/game/deck?mode=en_uk\|uk_en | перемішана колода |
| POST | /api/cards/{id}/review | `{knew: true/false}` — статистика |

Усі запити, крім реєстрації і входу, вимагають заголовок `Authorization: Bearer <token>`.
