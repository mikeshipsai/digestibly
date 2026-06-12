#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="${1:-"$ROOT_DIR/data/debug_posts.sqlite3"}"

mkdir -p "$(dirname "$DB_PATH")"

if [[ -f "$DB_PATH" ]]; then
  rm -f "$DB_PATH"
fi

sqlite3 "$DB_PATH" "VACUUM;"
echo "Database reset: $DB_PATH"
