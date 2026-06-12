# Architecture

## Purpose

Single-user bot that builds a **daily digest** of Telegram channel posts: collect → preprocess → summarize (stage 1) → select top posts (stage 2) → deliver by theme to owner chat.

## Layer diagram

```
┌─────────────────────────────────────────────────────────────┐
│  runtime/bootstrap.py                                       │
│  Aiogram polling + APScheduler (2 cron jobs)                │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  pipeline/digest.py                                           │
│  run_night_batch() · run_morning_digest() · run_digest()      │
└─┬─────────┬──────────┬──────────┬──────────┬────────────────┘
  │         │          │          │          │
  ▼         ▼          ▼          ▼          ▼
telegram  channels  storage    llm     scheduling
collector resolve   posts      summarizer  scheduler
          ai_cluster summaries
          preprocess settings
                      themes
```

## Module responsibilities

| Module | Responsibility |
|--------|----------------|
| `core.config` | Load and validate `.env` |
| `telegram.collector` | Telethon I/O, engagement metrics, calendar-day window |
| `telegram.bot` | Aiogram commands, per-theme digest delivery |
| `channels.resolve` | Theme priority: override → AI → CSV → keywords |
| `channels.ai_cluster` | LLM channel classification with SQLite cache |
| `channels.cluster` | Keyword `theme_cluster` labels |
| `channels.preprocess` | NFKC, strip emoji, extract tags/mentions |
| `storage.posts` | `collected_posts` |
| `storage.summaries` | `digest_runs`, `post_summaries_all`, `post_summaries` |
| `storage.settings` | Persisted schedule (`user_settings`) |
| `storage.themes` | `custom_themes`, `channel_overrides`, `channel_ai_themes` |
| `llm.gemini_client` | Gemini REST API |
| `llm.summarizer` | Stage-1 per-post + stage-2 top selection |
| `llm.token_estimate` | Offline cost estimate for scripts |
| `pipeline.scoring` | Engagement normalization + combined score |
| `pipeline.themes_merge` | Small themes → «Прочее» |
| `scheduling.scheduler` | Night batch + morning digest cron |
| `pipeline.digest` | Orchestration; track `last_digest_at` / `last_batch_at` |

## Dependency rules

- `core` has no imports from other `app.*` packages
- `channels`, `storage`, `llm`, `scheduling` do not import `telegram` or `pipeline`
- `telegram.collector` may use `channels.*` and `core`
- `pipeline` orchestrates everything
- `runtime` only starts `pipeline` + `telegram.bot` + `scheduling`

## External services

- Telegram MTProto (Telethon) — read channels
- Telegram Bot API (Aiogram) — interact with owner
- Google Gemini API (REST via `aiohttp`) — summarization

## Entry points

| Command | Entry |
|---------|--------|
| Production bot | `python -m app.main` |
| Telethon login | `python -m scripts.telethon_login` |
| Test collect | `python -m scripts.test_collect` |
| Run pipeline (CLI) | `python -m scripts.run_digest` |
