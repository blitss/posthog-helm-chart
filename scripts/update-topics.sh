#!/usr/bin/env bash
#
# Fetches Kafka topic names from the PostHog repo (Python + Node sources),
# merges and deduplicates them, then updates charts/posthog/values.yaml
# in both kafka.provisioning.topics and kafkaInit.topics.
#
# Requirements: curl, yq (https://github.com/mikefarah/yq)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALUES="${SCRIPT_DIR}/../charts/posthog/values.yaml"

PY_URL="https://raw.githubusercontent.com/PostHog/posthog/master/posthog/kafka_client/topics.py"
TS_URL="https://raw.githubusercontent.com/PostHog/posthog/master/nodejs/src/config/kafka-topics.ts"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd yq

echo "Fetching topics from PostHog repo..."

py_topics=$(curl -sfL "$PY_URL" | grep -oP 'f"{KAFKA_PREFIX}\K[^{]+(?=\{SUFFIX\}")' || true)
ts_topics=$(curl -sfL "$TS_URL" | grep -oP 'prefix\}[a-z_0-9-]+' | sed 's/prefix}//' || true)

topics=$(printf '%s\n%s\n' "$py_topics" "$ts_topics" | sort -u | grep -v '^$')
count=$(echo "$topics" | wc -l)
echo "Found ${count} unique topics"

# Build yq expressions for both paths
provisioning_expr=".kafka.provisioning.topics = []"
kafkainit_expr=".kafkaInit.topics = []"

while IFS= read -r topic; do
  provisioning_expr="${provisioning_expr} | .kafka.provisioning.topics += [{\"name\": \"${topic}\"}]"
  kafkainit_expr="${kafkainit_expr} | .kafkaInit.topics += [\"${topic}\"]"
done <<< "$topics"

yq -i "${provisioning_expr}" "$VALUES"
yq -i "${kafkainit_expr}" "$VALUES"

echo "Updated ${VALUES}"
echo "  kafka.provisioning.topics: ${count} entries"
echo "  kafkaInit.topics: ${count} entries"
