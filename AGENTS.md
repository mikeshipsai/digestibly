# AGENTS.md

Personal Telegram digest bot. One owner, all broadcast channels from a Telethon account, 7 macro themes, two-stage LLM digest via Aiogram.

## Stack

| Component | Role |
|-----------|------|
| Telethon | Read channel posts (userbot + session file) |
| Aiogram | Bot commands + digest delivery |
| APScheduler | Night batch + morning digest cron |
| SQLite | Posts, summaries, channel themes, schedule |
| Gemini 2.5 Flash | Primary LLM; Groq fallback on limits |

## Pipeline

1. **Night batch** — collect yesterday's posts → classify channels (AI cache + posts) → summarize all → save to DB
2. **Morning digest** — pick top-N per theme → send TOC with inline theme buttons

Theme resolution: override → AI cache → keywords → 7 macro themes (`app/channels/macro_themes.py`).

## Layout

```
app/main.py              entry point
app/pipeline/digest.py   batch + digest orchestration
app/telegram/bot.py      Aiogram handlers
app/telegram/collector.py Telethon collection
app/channels/ai_cluster.py  channel classification
app/llm/summarizer.py    two-stage summarization
app/storage/             SQLite persistence
scripts/run_digest.py    CLI pipeline
scripts/telethon_login.py one-time auth
```

## Do not

- Commit `.env`, `data/`, `*.session`
- Run two bot instances with the same Telethon session
- Re-introduce CSV-based runtime theme resolution or multi-user mode unless asked

## Commands

```bash
make install && make login && make bot
uv run python -m scripts.run_digest --no-send
```
