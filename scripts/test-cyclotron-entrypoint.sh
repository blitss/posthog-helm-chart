#!/usr/bin/env bash
# Required connection inputs and database initialization errors must fail the Job.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin"
cat > "$work/bin/sqlx" <<'SH'
#!/bin/sh
if [ "$1 $2" = 'database create' ]; then
    exit 42
fi
exit 0
SH
chmod +x "$work/bin/sqlx"
if env -u CYCLOTRON_NODE_DATABASE_URL PATH="$work/bin:$PATH" sh "$root/images/posthog/cyclotron-migrate-entrypoint.sh" > "$work/output" 2>&1; then
    echo 'Missing database URL incorrectly succeeded' >&2
    exit 1
fi
if CYCLOTRON_NODE_DATABASE_URL=postgres://test:test@invalid/test PATH="$work/bin:$PATH" sh "$root/images/posthog/cyclotron-migrate-entrypoint.sh" > "$work/output" 2>&1; then
    echo 'Database initialization failure incorrectly succeeded' >&2
    exit 1
fi
printf 'SQLx initialization failures do not become successful migration Jobs.\n'
