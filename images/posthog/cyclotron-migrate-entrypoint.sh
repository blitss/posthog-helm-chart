#!/bin/sh
# Reproducibly migrate the cyclotron / cyclotron_node databases using the
# canonical sqlx engine (PostHog's `rust/bin/migrate-cyclotron[-node]` runs the
# same `sqlx database create` + `sqlx migrate run`). The runtime PostHog images
# ship neither sqlx nor these migrations, so this dedicated image carries both.
set -eu

MIGRATIONS_DIR="${CYCLOTRON_MIGRATIONS_DIR:-/migrations}"

run() {
  url="$1"
  label="$2"
  if [ -z "$url" ]; then
    echo "[$label] database URL unset — skipping"
    return 0
  fi
  echo "[$label] ensuring database exists"
  # Idempotent: no-op if it already exists; tolerate lack of CREATEDB when the
  # database is provisioned externally (e.g. CNPG bootstrap).
  sqlx database create -D "$url" 2>/dev/null \
    || echo "[$label] database already exists (or not creatable here) — continuing"
  echo "[$label] applying migrations from $MIGRATIONS_DIR"
  sqlx migrate run -D "$url" --source "$MIGRATIONS_DIR"
  echo "[$label] up to date"
}

run "${CYCLOTRON_DATABASE_URL:-}" "cyclotron"
run "${CYCLOTRON_NODE_DATABASE_URL:-}" "cyclotron_node"
echo "cyclotron migrations complete"
