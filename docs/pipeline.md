# Digest pipeline

## Triggers

| Trigger | Handler |
|---------|---------|
| **Night batch** cron (`BATCH_HOUR:BATCH_MINUTE`) | `run_night_batch()` |
| **Morning digest** cron (`DIGEST_HOUR:DIGEST_MINUTE`) | `run_morning_digest()` |
| `/batch` | `run_night_batch()` |
| `/digest` | `run_digest()` (batch + morning) |

Schedule defaults: batch **04:00**, digest **09:00** (`TIMEZONE`). Override via `/set_schedule` (persisted in SQLite `user_settings`).

## Stage 1 — Night batch

### 1. Collect (`telegram.collector.collect_messages`)

- Telethon session from `TELETHON_SESSION_NAME`
- All **broadcast** channels in account dialogs
- **Calendar yesterday** in `TIMEZONE` (not rolling 24h)
- Up to **50** messages per channel with non-empty text after preprocess
- Engagement: `views`, `reactions`, `replies`

### 2. Theme assignment (`channels.resolve.resolve_channel_theme`)

Priority:

1. `channel_overrides` (bot `/move`)
2. `channel_ai_themes` (LLM classification, cached)
3. `data/channels.csv` (if not «Прочее»)
4. Keyword inference (`channels.cluster`)

### 3. Merge small themes (`pipeline.themes_merge`)

Categories with fewer than `MIN_POSTS_PER_THEME` (default 3) posts → **«Прочее»**.

### 4. Persist (`storage.posts.save_collected_posts`)

Table `collected_posts` with engagement columns. Path: `SQLITE_PATH`.

### 5. Summarize posts by theme (`llm.summarizer.summarize_all_posts`)

- Model: **gemini-2.5-flash** via REST (`llm.gemini_client`)
- Batched per theme (≤20 posts/chunk); on failure: split chunk → single post; LLM via Gemini → Groq
- Per post: title, 4–5 sentence summary, `llm_relevance` (0–1)
- Score: `0.3 × engagement_norm + 0.7 × llm_relevance`
- Saved to `post_summaries_all` linked to `digest_runs` (`run_type='batch'`)

If `DEBUG_COLLECT_ONLY=true`: stop after step 4.

## Stage 2 — Morning digest

### 1. Load batch summaries

From latest `digest_runs` where `run_type='batch'`. Re-merge small themes.

### 2. Select top-N (`llm.summarizer.select_top_from_summaries`)

- Default **5** posts per theme (`DIGEST_TOP_N`)
- LLM picks from pre-summarized posts using combined score as signal
- Fallback: sort by `combined_score`
- Saved to `post_summaries` (`run_type='digest'`)

### 3. Deliver (`telegram.bot.send_digest_by_category`)

- One Telegram message per theme
- Card format: **title → summary → link**
- First message notifies; rest are silent
- HTML formatting with plain-text fallback

### 4. Cleanup

- Delete `collected_posts` older than 2 days
- Prune old `digest_runs` (keep current batch + digest)

## Bot commands (owner only)

| Command | Action |
|---------|--------|
| `/set_schedule digest 09:00` | Morning digest time |
| `/set_schedule batch 04:00` | Night batch time |
| `/move @channel Тема` | Override channel theme |
| `/create_theme Название` | Add custom theme |
| `/themes` | List overrides and custom themes |
| `/status` | Last runs and schedule |

## Channel catalog (optional, separate from daily run)

| Script | Purpose |
|--------|---------|
| `scripts.export_channels` | Fetch channels → CSV |
| `scripts.recluster_channels` | Recompute keyword `theme_cluster` in CSV |
| `scripts.preview_clusters` | Cluster histogram from CSV |

CSV is a fallback after AI cache and overrides.

## Token budget (reference)

```bash
make test-collect   # → data/token_report.json
```

Estimates stage-1 (batch per theme) + stage-2 (per-category top selection) requests separately.
