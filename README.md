# Digestibly

Личный бот: ежедневный дайджест постов из **всех** broadcast-каналов вашего Telegram-аккаунта.

- **Сбор:** Telethon (вчерашний календарный день, до 50 постов/канал)
- **Темы:** ИИ-классификация + `/move` + keyword fallback
- **Суммаризация:** двухэтапный пайплайн на **Gemini 2.5 Flash**
- **Доставка:** Aiogram → TOP-5 по теме, отдельное сообщение на тему

## Документация

- **[AGENTS.md](AGENTS.md)** — гид для AI-ассистентов
- [docs/architecture.md](docs/architecture.md) — модули и слои
- [docs/pipeline.md](docs/pipeline.md) — двухэтапный пайплайн
- [docs/configuration.md](docs/configuration.md) — переменные окружения
- [docs/data.md](docs/data.md) — SQLite, CSV, сессия
- [docs/scripts.md](docs/scripts.md) — CLI-утилиты

---

## Установка и запуск

### 1. Установить [uv](https://docs.astral.sh/uv/)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Клонировать проект и настроить окружение

```bash
cd digestibly
cp .env.example .env
# заполнить .env (см. таблицу ниже)
make install
```

`make install` (= `uv sync`) создаёт `.venv` и ставит зависимости из `pyproject.toml`.

### 3. Заполнить `.env`

| Переменная | Где взять |
|------------|-----------|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_PHONE` | Номер аккаунта с подписками на каналы |
| `TELEGRAM_PASSWORD` | Если включена 2FA |
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `OWNER_CHAT_ID` | Ваш Telegram ID ([@userinfobot](https://t.me/userinfobot)) |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com) |

### 4. Авторизовать Telethon (один раз)

```bash
make login
```

Создаётся `data/telegram_digest_userbot.session`.

### 5. Запустить бота

```bash
make bot
```

По расписанию: **batch 04:00**, **digest 09:00** (`TIMEZONE`). Команды — в Telegram у бота.

---

## Тестирование по шагам

Все команды ниже используют `uv run` через Makefile. Альтернатива: `uv run python -m ...`.

### Шаг 1 — только сбор (без LLM)

```bash
make test-collect
```

Проверяет Telethon, каналы, SQLite. Результат: `data/debug_posts.sqlite3`, `data/token_report.json`.

### Шаг 2 — ночной batch (сбор + саммари всех постов)

```bash
uv run python -m scripts.run_digest --batch-only --no-send
```

Проверка:

```bash
sqlite3 data/debug_posts.sqlite3 "SELECT COUNT(*) FROM post_summaries_all;"
```

### Шаг 3 — утренний дайджест (TOP-5, без отправки)

```bash
uv run python -m scripts.run_digest --morning-only --no-send
```

В консоли — preview дайджеста.

### Шаг 4 — полный пайплайн без Telegram

```bash
make run-digest
```

### Шаг 5 — полный пайплайн с отправкой

Напишите боту `/start`, затем:

```bash
uv run python -m scripts.run_digest
```

### Шаг 6 — через команды бота

```bash
make bot
```

| Команда | Действие |
|---------|----------|
| `/status` | Расписание и последние запуски |
| `/batch` | Ночной этап вручную |
| `/digest` | Полный пайплайн |
| `/set_schedule digest 09:00` | Время отправки |
| `/set_schedule batch 04:00` | Время batch |
| `/move @channel Тема` | Переопределить тему |
| `/create_theme Название` | Личная тема |
| `/themes` | Список тем |

### Если Gemini недоступен

Добавьте `GROQ_API_KEY` в `.env` — пайплайн автоматически переключится на Groq (`qwen/qwen3-32b`).
Без ключа Groq при исчерпании лимита Gemini дайджест завершится с ошибкой.

### Сброс данных

```bash
make clean-db
```

---

## Docker

```bash
make init-auth   # Telethon в контейнере (один раз)
make up
make logs
```

---

## Make-команды

```bash
make help
make install          # uv sync
make login            # Telethon auth
make bot              # запуск бота
make test-collect
make run-digest
make export-channels
make recluster-channels
make preview-clusters
make up / down / clean-db
```

## Структура `app/`

```
app/
  main.py
  pipeline/          # digest, format, scoring, themes_merge
  telegram/          # Telethon + Aiogram
  channels/          # cluster, ai_cluster, resolve, preprocess
  llm/               # gemini_client, summarizer, token_estimate
  storage/           # posts, summaries, settings, themes
  scheduling/
  core/
  runtime/
```

Данные в `data/` — в `.gitignore`.
