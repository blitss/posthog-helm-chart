#!/bin/sh
# Migrate the Node v2 cyclotron database with the canonical sqlx engine.
# Runtime PostHog images ship neither sqlx nor these migrations.
set -eu
: "${CYCLOTRON_NODE_DATABASE_URL:?CYCLOTRON_NODE_DATABASE_URL is required}"

MIGRATIONS_DIR="${CYCLOTRON_MIGRATIONS_DIR:-/migrations}"


echo "[cyclotron_node] ensuring database exists"
sqlx database create -D "$CYCLOTRON_NODE_DATABASE_URL"
echo "[cyclotron_node] applying migrations"
sqlx migrate run -D "$CYCLOTRON_NODE_DATABASE_URL" --source "$MIGRATIONS_DIR/cyclotron-node-migrations"
echo "[cyclotron_node] up to date"
