#!/bin/sh
# Reproducibly migrate the cyclotron + cyclotron_node databases using the
# canonical sqlx engine. Mirrors upstream rust/bin/migrate-entry: the Rust
# cyclotron (CYCLOTRON_DATABASE_URL) uses cyclotron-core/migrations, while the
# Node v2 cyclotron (CYCLOTRON_NODE_DATABASE_URL) uses the SEPARATE
# cyclotron-node-migrations (different schema — has the person/distinct_id
# columns the cdp-cyclotron-v2 worker/janitor need). The runtime PostHog images
# ship neither sqlx nor these migrations, so this dedicated image carries both.
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

run "${CYCLOTRON_DATABASE_URL:-}"      "cyclotron"      "$MIGRATIONS_DIR/cyclotron-core/migrations"
run "${CYCLOTRON_NODE_DATABASE_URL:-}" "cyclotron_node" "$MIGRATIONS_DIR/cyclotron-node-migrations"
echo "cyclotron migrations complete"
