# AGENTS.md — guide for AI assistants

**Digestibly** — personal Telegram digest bot: collects posts from **all** broadcast channels on a Telethon account, groups by theme, two-stage LLM summarization with **Gemini 2.5 Flash**, sends digest to **one owner** via Aiogram.

## Read first

| Doc | Content |
|-----|---------|
| [docs/architecture.md](docs/architecture.md) | Layers, modules, dependencies |
| [docs/pipeline.md](docs/pipeline.md) | Two-stage digest flow |
| [docs/configuration.md](docs/configuration.md) | `.env` variables |
| [docs/data.md](docs/data.md) | SQLite, CSV, session files |
| [docs/scripts.md](docs/scripts.md) | CLI utilities |

## Repository layout

```
app/
  main.py                 # entry: python -m app.main
  core/config.py          # Settings from .env
  core/logging.py
  pipeline/
    digest.py             # run_night_batch(), run_morning_digest(), run_digest()
    format.py             # Telegram message formatting
    scoring.py            # engagement + combined score
    themes_merge.py       # merge small themes → «Прочее»
    types.py
  runtime/bootstrap.py    # bot polling + scheduler
  telegram/
    collector.py          # Telethon: channels, yesterday's posts, engagement
    bot.py                # Aiogram commands (owner only)
  channels/
    cluster.py            # keyword theme labels
    ai_cluster.py         # LLM channel classification (cached)
    resolve.py            # override → AI → CSV → keywords
    preprocess.py           # clean text before LLM
  storage/
    posts.py              # collected_posts
    summaries.py          # digest_runs, post_summaries_all, post_summaries
    settings.py           # persisted schedule (overrides .env)
    themes.py             # custom themes, channel overrides
  llm/
    gemini_client.py      # Gemini HTTP client
    groq_client.py        # Groq fallback (Qwen3 32B)
    llm_client.py         # call_llm(): Gemini → Groq on limits
    summarizer.py         # stage-1 per-post, stage-2 top selection
    token_estimate.py     # offline token estimate (scripts)
  scheduling/scheduler.py # night batch + morning digest cron
scripts/                  # one-off CLI (no bot)
data/                     # gitignored: session, sqlite, csv
docker/
```

## Digest pipeline

### Night batch (`run_night_batch`) — default 04:00

1. `telegram.collector.collect_messages()` — yesterday (calendar day in `TIMEZONE`), all broadcast channels, max 50 posts/channel
2. Theme per channel: `/move` override → AI cache → `channels.csv` → keywords
3. Merge themes with &lt; 3 posts into «Прочее»
4. `storage.posts.save_collected_posts()` — with views/reactions/replies
5. `llm.summarizer.summarize_all_posts()` — batched Gemini calls per theme (≤20 posts/chunk) → `post_summaries_all`

### Morning digest (`run_morning_digest`) — default 09:00

1. Load `post_summaries_all` from last batch run
2. `llm.summarizer.select_top_from_summaries()` — top-5 per theme (score + LLM)
3. `telegram.bot.send_digest_by_category()` — one message per theme
4. Cleanup: posts older than 2 days, old digest runs

### Manual

- `/digest` — full pipeline
- `/batch` — night batch only
- `/set_schedule digest|batch HH:MM` — persist schedule in SQLite

## Two Telegram clients

| Client | Library | Role |
|--------|---------|------|
| Userbot | Telethon | Read channel posts (needs `TELEGRAM_*` + session file) |
| Bot | Aiogram | Commands + send digest (`BOT_TOKEN`) |

Session path: `TELETHON_SESSION_NAME` (default `data/telegram_digest_userbot`).

## Do not

- Re-introduce multi-user SQLite unless explicitly requested
- Require manual `/add_channel` — collection is **all** broadcast channels from the account
- Commit `.env`, `data/`, `*.session`

## Setup

Uses [uv](https://docs.astral.sh/uv/): `pyproject.toml` + `uv.lock`. Run `make install` (=`uv sync`) before any command.

## Common commands

```bash
make install                        # uv sync
make login                          # Telethon auth (once)
make recluster-channels             # refresh keyword themes in channels.csv
make test-collect                   # collect + sqlite + token report
uv run python -m scripts.run_digest --no-send --batch-only
make bot                            # run bot + scheduler
```

## Planned improvements

See [TODO.md](TODO.md): dedup, promo filter, summary caching.
