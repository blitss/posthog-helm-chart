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


require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

require_cmd curl
require_cmd yq
POSTHOG_REF="${POSTHOG_REF:-$(yq -r '.appVersion' "${SCRIPT_DIR}/../charts/posthog/Chart.yaml")}"
if [[ ! "$POSTHOG_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "POSTHOG_REF must be an immutable 40-character commit SHA" >&2
  exit 1
fi
PY_URL="https://raw.githubusercontent.com/PostHog/posthog/${POSTHOG_REF}/posthog/kafka_client/topics.py"
TS_URL="https://raw.githubusercontent.com/PostHog/posthog/${POSTHOG_REF}/nodejs/src/common/config/kafka-topics.ts"

echo "Fetching topics from PostHog repo..."

# Fetch separately so an HTTP failure cannot become a partial topic list.
if ! py_source=$(curl -sfL "$PY_URL"); then
  echo "Failed to fetch Python topics from ${PY_URL}" >&2
  exit 1
fi
if ! ts_source=$(curl -sfL "$TS_URL"); then
  echo "Failed to fetch Node topics from ${TS_URL}" >&2
  exit 1
fi

# Match complete topic literals using portable sed (including macOS).
py_topics=$(printf '%s\n' "$py_source" | sed -nE 's/.*f"\{KAFKA_PREFIX\}([a-z_0-9-]+)\{SUFFIX\}".*/\1/p')
ts_topics=$(printf '%s\n' "$ts_source" | sed -nE 's/.*`\$\{prefix\}([a-z_0-9-]+)\$\{suffix\}`.*/\1/p')

if [[ -z "$py_topics" || -z "$ts_topics" ]]; then
  echo "Both Python and Node sources must contain parseable topics; values left unchanged" >&2
  exit 1
fi

topics=$(printf '%s\n%s\n' "$py_topics" "$ts_topics" | LC_ALL=C sort -u)
count=$(echo "$topics" | wc -l)
echo "Found ${count} unique topics"

# Build yq expressions for both paths
provisioning_expr=".kafka.provisioning.topics = []"
kafkainit_expr=".kafkaInit.topics = []"

while IFS= read -r topic; do
  provisioning_expr="${provisioning_expr} | .kafka.provisioning.topics += [{\"name\": \"${topic}\"}]"
  kafkainit_expr="${kafkainit_expr} | .kafkaInit.topics += [\"${topic}\"]"
done <<< "$topics"

yq -i "${provisioning_expr} | ${kafkainit_expr}" "$VALUES"

echo "Updated ${VALUES}"
echo "  kafka.provisioning.topics: ${count} entries"
echo "  kafkaInit.topics: ${count} entries"
