# Scripts

Run from project root. Dependencies via [uv](https://docs.astral.sh/uv/): `make install` then `uv run python -m ...` or use Makefile targets. All scripts need valid `.env`.

| Script | Make target | Needs Telethon |
|--------|-------------|----------------|
| `scripts.telethon_login` | `make init-auth` (docker) | interactive |
| `scripts.export_channels` | `make export-channels` | yes |
| `scripts.recluster_channels` | `make recluster-channels` | no |
| `scripts.preview_clusters` | `make preview-clusters` | no |
| `scripts.test_collect` | `make test-collect` | yes |
| `scripts.run_digest` | `make run-digest` | yes (unless `--from-db`) |

## `telethon_login`

One-time authorization; writes session to `TELETHON_SESSION_NAME`.

## `export_channels`

Fetches all broadcast channels, full descriptions (`GetFullChannel`), writes `CHANNELS_CSV_PATH`. Slow (~5–10 min) due to Telegram rate limits.

## `recluster_channels`

Re-runs `infer_theme_cluster(title, about)` on existing CSV — fast way to apply new keyword clustering rules.

## `preview_clusters`

Prints cluster counts from CSV without writing.

## `test_collect`

Collection without bot/LLM:

1. `collect_messages()` — yesterday's posts
2. Save SQLite
3. Print token estimate (stage-1 + stage-2) + `token_report.json`

## `run_digest`

Full or partial pipeline from CLI:

```bash
python -m scripts.run_digest --no-send              # full, preview only
python -m scripts.run_digest --batch-only --no-send # night batch only
python -m scripts.run_digest --morning-only         # top-5 from last batch
python -m scripts.run_digest --from-db --morning-only  # skip Telethon collect
```
