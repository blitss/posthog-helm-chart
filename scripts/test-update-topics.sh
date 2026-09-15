#!/usr/bin/env bash
# Run with: bash scripts/test-update-topics.sh
# Exercise failed fetches and unusable sources without network access or real yq.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/scripts" "$work/charts/posthog" "$work/bin"
cp "$SCRIPT_DIR/update-topics.sh" "$work/scripts/"
printf 'original values\n' > "$work/original"

cat > "$work/bin/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${@: -1}" in
  */posthog/kafka_client/topics.py)
    source=python
    literal='KAFKA_EVENTS_JSON = f"{KAFKA_PREFIX}clickhouse_events_json{SUFFIX}"'
    ;;
  */nodejs/src/common/config/kafka-topics.ts)
    source=node
    literal='export const KAFKA_METRICS_INGESTION = `${prefix}metrics_ingestion${suffix}`'
    ;;
  *) exit 90 ;;
esac
if [[ "$source" == "$FAILED_SOURCE" ]]; then
  case "$FAILURE" in
    fetch) printf '%s\n' "$literal"; exit 22 ;;
    empty) exit 0 ;;
    unparseable) printf 'upstream format no longer recognized\n'; exit 0 ;;
  esac
fi
printf '%s\n' "$literal"
SH

cat > "$work/bin/yq" <<'SH'
#!/usr/bin/env bash
# Make any attempted mutation observable even if the updater later fails.
printf 'unexpected mutation\n' > "${@: -1}"
SH
chmod +x "$work/bin/curl" "$work/bin/yq"

for source in python node; do
  for failure in fetch empty unparseable; do
    cp "$work/original" "$work/charts/posthog/values.yaml"
    if PATH="$work/bin:$PATH" FAILED_SOURCE="$source" FAILURE="$failure" \
      bash "$work/scripts/update-topics.sh" > "$work/output" 2>&1; then
      cat "$work/output" >&2
      echo "Expected failure for $source/$failure" >&2
      exit 1
    fi
    if ! cmp -s "$work/original" "$work/charts/posthog/values.yaml"; then
      echo "Values changed for $source/$failure" >&2
      exit 1
    fi
  done
done

echo 'Topic sync leaves values unchanged on either source failing to fetch or parse.'
