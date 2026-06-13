# Digestibly

Personal Telegram digest bot: collects yesterday's posts from all broadcast channels on your account, groups them into macro themes, summarizes with Gemini (Groq fallback), and sends a daily digest to one owner.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Telegram API credentials ([my.telegram.org](https://my.telegram.org))
- Bot token ([@BotFather](https://t.me/BotFather))
- Gemini API key ([Google AI Studio](https://aistudio.google.com))
- Optional: `GROQ_API_KEY` for fallback when Gemini limits are hit

## Setup

```bash
git clone git@github.com:mikeshipsai/digestibly.git
cd digestibly
cp .env.example .env   # fill in secrets
make install
make login             # one-time Telethon auth → data/telegram_digest_userbot.session
make bot               # local dev (foreground)
```

### Required `.env` variables

| Variable | Description |
|----------|-------------|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` | Telethon userbot |
| `TELEGRAM_PASSWORD` | 2FA password (if enabled) |
| `BOT_TOKEN` | Aiogram bot token |
| `OWNER_CHAT_ID` | Your Telegram user ID |
| `GEMINI_API_KEY` | LLM summarization |

## Production (24/7)

Run via systemd on a VPS:

```bash
cd /opt/tg_summarizator
uv sync
systemctl enable --now tg-summarizator
journalctl -u tg-summarizator -f
```

Service unit example:

```ini
[Service]
WorkingDirectory=/opt/tg_summarizator
ExecStart=/root/.local/bin/uv run python -m app.main
Restart=always
```

## Schedule

Default (override via `/start` or `/set_schedule`):

- **04:00** — night batch: collect + summarize all posts
- **09:00** — morning digest: top-5 per theme + TOC with inline buttons

Timezone: `TIMEZONE` in `.env` (default `Europe/Moscow`).

## Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Set digest time (onboarding) |
| `/digest` | Run full pipeline now |
| `/mute @channel` | Hide channel from digest |
| `/unmute @channel` | Restore channel |
| `/status` | Last runs and schedule |

Hidden owner commands: `/batch`, `/set_schedule`, `/move`, `/themes`.

## Manual pipeline

```bash
uv run python -m scripts.run_digest --no-send          # full pipeline, no Telegram
uv run python -m scripts.run_digest --batch-only       # collect + summarize only
uv run python -m scripts.run_digest --morning-only     # send from last batch
```

## Docker

```bash
make init-auth   # Telethon login in container (once)
make up
make logs
```

## Data

Runtime files live in `data/` (gitignored): SQLite DB, Telethon session, channel cache.

Do not run the bot on two machines with the same session file.
