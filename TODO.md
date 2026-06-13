# Roadmap

Actionable backlog for pipeline and UX improvements. Items are ordered roughly by impact within each section.

---

## 1. Data collection (`app/telegram/collector.py`)

### Parallel channel collection
**Goal:** Cut night batch collect time when there are many channels.

**What to do:**
- Replace sequential `iter_dialogs` + per-channel fetch with a worker pool (asyncio semaphore, e.g. 5–10 concurrent channels).
- Respect Telethon `FloodWaitError`: pause all workers for N seconds when hit.
- Log per-channel timing and failures; failed channels must not block the rest.

**Acceptance:** Collect time scales sub-linearly with channel count; no session conflicts.

---

### Incremental collection
**Goal:** Avoid re-scanning full yesterday window for every channel every night.

**What to do:**
- Add SQLite table `channel_sync_state(channel_key, last_message_id, last_synced_at)`.
- On collect: for each channel, fetch messages with `id > last_message_id` (and still filter to target calendar day).
- Fallback: if no state or gap > 7 days, full day scan once.
- Update state after successful collect.

**Acceptance:** Second run same day only fetches new messages; posts for target date still complete.

---

### Retry + backoff
**Goal:** Transient errors on one channel should not fail the whole batch.

**What to do:**
- Wrap per-channel collect in retry (3 attempts, exponential backoff: 2s, 8s, 32s).
- Handle: `FloodWaitError`, network timeouts, `ChannelInvalidError` (no retry, log + skip).
- Aggregate stats in batch run metadata for `/status`.

**Acceptance:** Random network blip on 1 channel → retry succeeds or channel skipped with log; batch completes.

---

### Link-only posts (fetch article text)
**Goal:** Summarize posts that are mostly a URL + teaser.

**What to do:**
- After collect, detect short text + URL(s) in post (`preprocess` or new `link_posts.py`).
- HTTP fetch with timeout (5s), parse `og:title`, `og:description`, or first `<p>` from article.
- Append fetched text to `message["text"]` or new field `message["link_excerpt"]` before LLM.
- Cache by URL in SQLite to avoid re-fetch; respect robots / skip on error.

**Acceptance:** Link-only posts get meaningful summaries; fetch failures fall back to original text.

---

### Weekly channel reclassification
**Goal:** Refresh AI theme cache when channel content drifts.

**What to do:**
- New script `scripts/reclassify_channels.py` (or cron weekly):
  - Load all known channels from `themes` storage.
  - For each: fetch last N posts (reuse `PROFILE_POSTS_LIMIT`), call `classify_channel_by_posts()`.
  - Update AI cache; log theme changes.
- Optional: notify owner in Telegram if many channels changed theme.
- Run via systemd timer or manual `make reclassify-channels`.

**Acceptance:** Script completes without blocking bot; theme changes visible in logs/DB.

---

## 2. Text processing (before LLM)

### Deduplication (all variants)

#### Exact dedup (extend current)
- Already: `content_hash` after `preprocess_post`, keep higher engagement.
- **Add:** normalize URLs in text (strip utm_*, ya.cc unwrap) before hashing.

#### Cross-channel semantic dedup
**Goal:** Same news from 5 channels → one item in digest.

**What to do:**
- After exact dedup, cluster posts by embedding similarity (e.g. `sentence-transformers` local, or cheap embedding API).
- Threshold ~0.85 cosine; keep highest `engagement_raw` per cluster.
- Store `cluster_id` on message for debugging.

**Acceptance:** Reposted Apple news from 3 channels → 1 post in batch output.

#### Link-based dedup
- Same canonical URL in multiple posts → merge cluster (even if text differs slightly).

---

### Post series (part 1/2, continued…)
**Goal:** Avoid 5 digest slots for one story split across posts.

**What to do:**
- Detect patterns: «часть 2», «продолжение», «(2/5)`, same channel within 24h, similar title prefix.
- Merge series into one virtual post (concat text, max length cap) OR keep only last part with boosted relevance.
- Log merged groups in filter stats.

**Acceptance:** Multi-part thread from one channel counts as one candidate for summarization.

---

## 3. LLM pipeline (`app/llm/summarizer.py`, `llm_client.py`)

### Reduce LLM call volume
**Goal:** Cut batch from ~30–60 min (Groq free) to minutes.

**What to do (pick combination):**
1. **Pre-filter:** Per theme, rank by engagement + length; send to LLM only top 50% (min 5, max 40).
2. **Summary cache:** Key `(content_hash, prompt_version)` → skip LLM if hit in SQLite.
3. **Drop stage-2 LLM select:** Use `combined_score` + MMR diversity instead of `select_top_from_summaries` LLM call (keep LLM select as optional flag).
4. **Theme-level map-reduce (optional):** One call: «from these 30 titles+excerpts pick and summarize top 5» instead of 30 full summaries.

**Acceptance:** Night batch LLM calls reduced ≥50% with comparable digest quality on manual review.

---

### JSON schema / structured output
**Goal:** Fewer broken JSON parses and retries.

**What to do:**
- Gemini: use `response_schema` / JSON mode where supported.
- Groq: `response_format: { type: "json_object" }` or tool calling with fixed schema.
- Centralize schemas in `app/llm/schemas.py` (batch summary, single post, top select, classify channel).
- On parse failure: one retry with «fix JSON» prompt, then fallback to single-post path.

**Acceptance:** Parse error rate < 1% on typical batch.

---

### Parallelism + providers
**Goal:** Use rate limits fully without blowing quotas.

**What to do:**
- Global async queue with RPM/TPM budgets shared across categories (`app/llm/rate_limiter.py`).
- Summarize categories in parallel (e.g. 3–4 at once) through the queue.
- Optional split: cheap model (Groq 8B) for batch summarize, Gemini for morning polish (config flag).
- Track provider per run for `/status`.

**Acceptance:** Wall-clock batch time drops with parallel themes; no 429 loops.

---

### Scoring improvements
**Goal:** Top-5 reflects interest, not just engagement or generic LLM score.

**What to do:**
- Extend `combined_score` in `app/pipeline/scoring.py`:
  - **Novelty:** downrank if similar to yesterday's digest summaries (embedding distance).
  - **Source diversity:** penalty if same channel already in top-K (MMR).
  - **Priority boost:** new `/priority @channel` → multiplier (mirror of `/mute`).
  - **Feedback boost:** use 👍/👎 history per channel/theme (see UX section).
- Expose weights in `.env` or settings.

**Acceptance:** Digest has fewer duplicate stories and fewer posts from same channel.

---

## 4. UX (`app/telegram/bot.py`)

### Pipeline transparency
**Goal:** User knows what `/digest` is doing during long runs.

**What to do:**
- Send progress messages (edit one message): stages Collect → Filter → Summarize (theme X/N) → Select → Send.
- Extend `/status`: last batch stats (posts in/out, promo dropped, deduped, LLM calls, provider, duration).
- On batch failure: notify with stage name and error summary.

**Acceptance:** Owner never waits 30+ min in silence; `/status` shows meaningful numbers.

---

### 👍 / 👎 on posts (training signal)
**Goal:** Collect preferences for future personalization / fine-tuning.

**What to do:**
- Add inline buttons under each post in expanded theme digest: `👍` / `👎` with callback `fb:{url_hash}`.
- SQLite table `post_feedback(url, channel, theme, vote, created_at)`.
- No immediate ranking change required in v1 — just persist data.
- v2: feed into scoring weights and optional prompt «user liked X style posts».

**Acceptance:** Clicks stored; queryable for offline analysis or future model training.

---

### Weekly digest
**Goal:** Sunday (or configurable) summary of the best posts across the week.

**What to do:**
- APScheduler job `weekly_digest` (e.g. Sun 10:00).
- Query `article_summaries` / `post_summaries` for last 7 days; pick top-N per theme by score + dedup.
- Send format similar to daily TOC + themes; label «Лучшее за неделю».
- Setting: enable/disable, day, hour via `/set_weekly` or env.

**Acceptance:** Weekly message sent automatically when enabled; no duplicate of daily posts without reason.

---

### Onboarding improvements
**Goal:** New user understands value before first scheduled digest.

**What to do:**
- After time selection in `/start`:
  1. Show channel count per macro theme (from current subscriptions).
  2. Offer «Пример дайджеста» — run lightweight pipeline on last 24h top 2 per theme (or cached batch).
  3. Hint: `/mute @channel` for noisy sources.
- Mark onboarding step in `settings` so sample runs once.

**Acceptance:** First `/start` ends with sample TOC or clear «digest at HH:MM» + theme breakdown.

---

## 5. Suggested implementation order

1. Retry + backoff + parallel collect (low risk, fast win)
2. Pipeline transparency (UX while batch stays slow)
3. Reduce LLM volume + parallelism (biggest cost/time win)
4. Dedup upgrades (exact URL → semantic)
5. Incremental collect + link fetch
6. JSON schema
7. Scoring + 👍/👎 storage
8. Weekly digest + onboarding polish
9. Weekly reclassify script

---

## Notes

- Keep `.env` secrets and `data/` out of git.
- Bump `prompt_version` in cache keys when changing summarize prompts.
- Each feature should log metrics compatible with `/status` and `digest_runs` table.
