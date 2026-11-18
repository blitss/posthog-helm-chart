#!/usr/bin/env bash
# Run with: bash scripts/test-chart-render.sh   (needs helm 3 and yq from mise.toml)
# helm lint + helm template over a matrix of value sets; fails on any render error,
# and checks that the fail-fast validations still reject broken configurations.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
chart=charts/posthog
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

helm lint "$chart"

ext_kafka='kafka.enabled=false,externalKafka.brokers=kafka:9092'
ext_ch='clickhouse.enabled=false,externalClickhouse.host=ch,externalClickhouse.secretName=ch'
ext_pg='postgresql.enabled=false,externalPostgresql.url=postgres://u:p@pg/posthog,externalPostgresql.cyclotronNodeUrl=postgres://u:p@pg/cyclotron_node'
ext_rest='redis.enabled=false,externalRedis.url=redis://redis:6379,valkey.enabled=false,externalValkey.host=valkey,rustfs.enabled=false,externalObjectStorage.endpoint=https://s3,elasticsearch.enabled=false,externalElasticsearch.host=es,temporal.enabled=false,externalTemporal.host=temporal'
toggles=''
for c in web worker workerExports workerBeat temporalDjangoWorker plugins capture replayCapture featureFlags hypercacheServer personhogReplica personhogRouter cymbalResolution; do
  toggles+="$c.podDisruptionBudget.enabled=true,"
  [ "$c" = workerBeat ] || toggles+="$c.autoscaling.enabled=true,"
done

sets=(
  ''
  "$ext_kafka,$ext_ch,$ext_pg,$ext_rest"
  'postgresql.enabled=false,externalPostgresql.secretName=pg,externalPostgresql.host=pg-rw'
  'postgresql.enabled=false'
  'ingress.nginx.enabled=false,ingress.gateway.enabled=true,mcp.enabled=true'
  'ingress.nginx.enabled=false,ingress.traefik.enabled=true,mcp.enabled=true'
  'ingress.nginx.enabled=false,ingress.istio.enabled=true,mcp.enabled=true'
  'ingress.nginx.enabled=false,ingress.openshift.enabled=true,mcp.enabled=true'
  'ingress.enabled=false,existingSecret=my-secret'
  'redis.enabled=false,existingSecret=my-secret'
  'redis.enabled=false,posthog.secretEnv.REDIS_URL.name=r,posthog.secretEnv.REDIS_URL.key=url'
  "${toggles}workerExports.enabled=true,metrics.enabled=true,networkPolicies.enabled=true"
  'mcp.enabled=true,usageIngestion.enabled=true,cyclotronMigrate.enabled=true,cdpHogflowScheduler.enabled=true,cdpCyclotronV2Janitor.enabled=true'
)
for s in "${sets[@]}"; do
  echo "template: ${s:-defaults}"
  helm template posthog "$chart" -n posthog ${s:+--set "$s"} > /dev/null
done

for release in manifests/posthog/release.yaml manifests/hub-production/release.yaml; do
  echo "template: $release"
  yq '.spec.values' "$release" > "$work/values.yaml"
  helm template posthog "$chart" -n posthog -f "$work/values.yaml" > /dev/null
done

for s in kafka.enabled=false redis.enabled=false rustfs.enabled=false temporal.enabled=false elasticsearch.enabled=false; do
  if helm template posthog "$chart" -n posthog --set "$s" > /dev/null 2>&1; then
    echo "expected '$s' without its external endpoint to fail" >&2
    exit 1
  fi
done
echo OK
