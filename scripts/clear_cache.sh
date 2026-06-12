#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${1:-"$ROOT_DIR/data/debug_posts.sqlite3"}"

if [[ -f "$DB_PATH" ]]; then
  sqlite3 "$DB_PATH" <<'SQL'
DELETE FROM channel_ai_themes;
DELETE FROM known_channels;
DELETE FROM collected_posts;
DELETE FROM post_summaries_all;
DELETE FROM post_summaries;
DELETE FROM digest_runs;
SQL
  echo "Cleared classification and digest cache in $DB_PATH"
else
  echo "No database at $DB_PATH"
fi
