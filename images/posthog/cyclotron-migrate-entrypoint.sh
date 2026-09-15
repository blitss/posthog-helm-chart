#!/bin/sh
# Migrate the Node v2 cyclotron database with the canonical sqlx engine.
# Runtime PostHog images ship neither sqlx nor these migrations.
set -eu

MIGRATIONS_DIR="${CYCLOTRON_MIGRATIONS_DIR:-/migrations}"

run() {
  url="$1"
  label="$2"
  source="$3"
  if [ -z "$url" ]; then
    echo "[$label] database URL unset — skipping"
    return 0
  fi
  echo "[$label] ensuring database exists"
  sqlx database create -D "$url" 2>/dev/null \
    || echo "[$label] database already exists (or not creatable here) — continuing"
  echo "[$label] applying migrations from $source"
  sqlx migrate run -D "$url" --source "$source"
  echo "[$label] up to date"
}

run "${CYCLOTRON_NODE_DATABASE_URL:-}" "cyclotron_node" "$MIGRATIONS_DIR/cyclotron-node-migrations"
echo "cyclotron migrations complete"
