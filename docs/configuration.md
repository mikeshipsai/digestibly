# Configuration

Settings load from `.env` via `app.core.config.get_settings()`. Schedule can be overridden at runtime via bot `/set_schedule` (stored in SQLite `user_settings`).

Copy `.env.example` → `.env`. Install deps: `make install` (uv).

## Required variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_API_ID` | From [my.telegram.org](https://my.telegram.org) |
| `TELEGRAM_API_HASH` | Same |
| `TELEGRAM_PHONE` | Account that subscribes to channels |
| `BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) |
| `OWNER_CHAT_ID` or `ADMIN_CHAT_ID` | Your Telegram user id (digest destination) |
| `GEMINI_API_KEY` | From [Google AI Studio](https://aistudio.google.com) |

## Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_PASSWORD` / `TELEGRAM_2FA_PASSWORD` | empty | 2FA for Telethon login |
| `BATCH_HOUR` | `4` | Night batch hour (collect + summarize) |
| `BATCH_MINUTE` | `0` | Night batch minute |
| `DIGEST_HOUR` | `9` | Morning digest hour (top-5 + send) |
| `DIGEST_MINUTE` | `0` | Morning digest minute |
| `TIMEZONE` | `Europe/Moscow` | Scheduler and calendar-day window |
| `DIGEST_TOP_N` | `5` | Top posts per theme |
| `MIN_POSTS_PER_THEME` | `3` | Merge smaller themes into «Прочее» |
| `DEBUG_COLLECT_ONLY` | `false` | Collect + SQLite only, skip LLM and send |
| `AI_CLUSTER_ENABLED` | `true` | LLM for channels where keywords return «Прочее» |
| `GEMINI_RPM` | `4` | Max Gemini requests/min (free tier ≈ 5) |
| `GROQ_API_KEY` | empty | Groq fallback when Gemini hits limits ([console.groq.com](https://console.groq.com)) |
| `GROQ_MODEL` | `qwen/qwen3-32b` | Groq model for fallback |
| `GROQ_RPM` | `30` | Max Groq requests/min |
| `SQLITE_PATH` | `data/debug_posts.sqlite3` | SQLite database |
| `TELETHON_SESSION_NAME` | `data/telegram_digest_userbot` | Session file path |
| `CHANNELS_CSV_PATH` | `data/channels.csv` | Channel catalog (keyword theme fallback) |

## Constants (code, not env)

In `app.core.config`:

- `MAX_MESSAGES_PER_CHANNEL = 50`

LLM model: `gemini-2.5-flash` in `app.llm.gemini_client.MODEL_NAME`.

## Docker

`docker/docker-compose.yml` overrides for containers:

- `SQLITE_PATH=/data/debug_posts.sqlite3`
- `TELETHON_SESSION_NAME=/data/telegram_digest_userbot`
- Volume `./data:/data`
