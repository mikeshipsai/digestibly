# Data files

All under `data/` (gitignored).

## `telegram_digest_userbot.session`

Telethon session created by `python -m scripts.telethon_login`. Required for collector and export scripts.

## `channels.csv`

Optional channel catalog (keyword theme fallback).

| Column | Meaning |
|--------|---------|
| `theme_cluster` | e.g. `ML/AI — Вакансии`, `Прочее` |
| `title` | Channel title |
| `username` | @handle if public |
| `url` | t.me link |
| `channel_id` | Telegram id |
| `participants_count` | Subscribers if available |
| `about` | Channel description |

Primary theme sources: bot `/move` overrides and AI cache in SQLite. CSV used when AI returns «Прочее» or before AI classifies a channel.

## `debug_posts.sqlite3`

### `collected_posts`

Raw posts with engagement metrics:

```
id, category, channel, channel_username, post_date, url, text,
views, reactions, replies
UNIQUE(url)
```

### `post_summaries_all`

Stage-1 summaries (one row per post per batch run):

```
run_id, category, channel, title, summary, url,
views, reactions, replies,
engagement_score, llm_relevance, combined_score, post_date
```

### `post_summaries`

Stage-2 selected top posts per digest run:

```
run_id, category, channel, title, summary, url, rank
```

### `digest_runs`

```
id, started_at, finished_at, posts_collected, categories_count, run_type
```

`run_type`: `batch` | `digest` | `full`

### `user_settings`

Persisted schedule keys: `batch_hour`, `batch_minute`, `digest_hour`, `digest_minute`.

### `custom_themes` / `channel_overrides` / `channel_ai_themes`

Bot-managed themes and AI classification cache.

## `token_report.json`

Output of `make test-collect` — estimated LLM tokens for stage-1 + stage-2.

## Cleanup

- **Automatic:** morning digest deletes posts older than 2 days and prunes old runs
- **Manual reset:** `make clean-db`
