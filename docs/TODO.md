# TODO: Quality & Cost Optimizations

## 1) Near-Duplicate Filtering (High Priority)
- [x] Add lightweight dedup before summarization (`pipeline/post_filter.py`).
- [x] Implement normalized text fingerprint (SHA-256 of preprocessed text).
- [x] Drop near-duplicates inside one digest window.
- [x] Log dedup stats: `input_posts`, `deduped_posts`, `drop_rate`.

## 2) Promo/Ad Filtering (High Priority)
- [x] Add rule-based promo detector (`erid`, `промокод`, `кэшбэк`, `по ссылке`, etc.).
- [x] Exclude promo from summarization flow.
- [x] Log filter stats: `promo_excluded`, `deduped_posts`, `output_posts`.

## 3) Text Compression Before LLM (Medium Priority)
- [ ] Truncate by sentence boundaries instead of raw character cut.
- [ ] Remove boilerplate phrases and repetitive CTA fragments.

## 4) Summary Caching (Medium Priority)
- [ ] Add content-hash cache for already summarized posts.
- [ ] Reuse cached outputs for repeated/reposted content.
- [ ] Store cache TTL and invalidation strategy.

## 5) Observability (Medium Priority)
- [ ] Add per-run metrics: request count, retries, avg chunk size.
- [ ] Track token proxy metrics and cost estimate in logs.
- [ ] Add final report: posts collected, summarized, selected, sent.

## Done
- [x] Two-stage summarization (per-post batch + top selection)
- [x] Engagement + LLM combined score
- [x] Per-theme Telegram delivery
- [x] Bot schedule and theme management
