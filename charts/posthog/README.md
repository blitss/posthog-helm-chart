# PostHog Helm Chart

Deploys [PostHog](https://posthog.com) on Kubernetes with bundled infrastructure (ClickHouse, Kafka, Postgres, Redis, object storage). Use this path for **local dev, POCs, and quick self-host demos**. For a production-grade operator-based setup, use the manifests path in [`../../manifests`](../../manifests/README.md).

For anything beyond dev/demo, **use external ClickHouse and Kafka** — the bundled ClickHouse is a single-node StatefulSet, and the `kafka` subchart is `bitnami/kafka` which pulls from the unmaintained `bitnamilegacy/*` mirrors. The [manifests path](../../manifests/README.md) wires up the Altinity ClickHouse Operator and the Redpanda operator for you.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.x
- Minimum ~10 GiB RAM available across nodes (everything bundled)
- An Ingress controller *or* Gateway API implementation (NGINX, Traefik, Gateway API, Istio, and OpenShift routes all supported)

## Quick start

```bash
helm install posthog oci://ghcr.io/blitss/charts/posthog \
  --namespace posthog --create-namespace \
  --set ingress.hostname=posthog.example.com
```

Or from a local checkout:

```bash
helm dependency build ./charts/posthog
helm install posthog ./charts/posthog \
  --namespace posthog --create-namespace \
  --set ingress.hostname=posthog.example.com
```

Defaults deploy:

| Component | How |
|---|---|
| ClickHouse | Single-node StatefulSet, `ghcr.io/blitss/posthog-clickhouse` with PostHog UDFs |
| Kafka | bitnami/kafka subchart in KRaft mode with topic auto-provisioning |
| Postgres | Single StatefulSet with `postgres:15-alpine` |
| Redis | Single StatefulSet with `redis:7-alpine` |
| Object storage | rustfs subchart (S3-compatible) |
| Temporal | Auto-setup server + UI |
| Elasticsearch | Single node, for Temporal visibility |

## Install hooks

The chart runs ordered Helm hook Jobs:

| Weight | Hook | Runs at | Purpose |
|---:|---|---|---|
| `-1` | `db-check` | `post-install,post-upgrade` | `nc -z` probe against Redis, Kafka, Postgres, ClickHouse, ZooKeeper — waits until everything is reachable before the other hooks run |
| `0` | `kafka-init` | `pre-install,pre-upgrade` | Only when using **external** Kafka (`kafka.enabled=false`). Creates topics via `kafka-topics.sh` against `externalKafka.brokers`. Skipped for bundled Kafka because the subchart has its own `provisioning.topics`. |
| `1` | `create-buckets` | `post-install,post-upgrade` | When `rustfs.enabled=true`, provisions application and AI blob buckets. External buckets must already exist. |
| `7` | `migrate` | `post-install,post-upgrade` | Runs Django/product, persons SQL, ClickHouse and async migrations. |
| `10` | `async-migrations-check` | `post-install,post-upgrade` | Runs `python manage.py run_async_migrations`. |

The hook container for `migrate`/`async-migrations-check` is the `posthog-migrate` slim image (`ghcr.io/blitss/posthog-migrate` by default) — no Node, no Chromium, no Playwright.

## Upgrading to 0.22

This release targets September 2026 PostHog. Back up PostgreSQL and ClickHouse before upgrading; use matching immutable application images. ClickHouse must be **26.6.2 or newer**. Complete the new migration job before admitting new application traffic: post-upgrade hooks alone are not a pre-rollout barrier.

For legacy installations, the `migrate` hook requires this release's rebuilt `posthog-migrate` image. Its guarded preparation command runs original product model moves before September squash selection, without faking migrations or skipping data operations. It preserves original migration records; any repaired squash-summary marker must have all original operations recorded and a demonstrably unmet dependency. See [the legacy upgrade issue](https://github.com/blitss/posthog-helm-chart/issues/65). The image also [backports the SCIM migration's historical-field lookup](https://github.com/blitss/posthog-helm-chart/issues/66), retaining its database column, dependencies, and data-selection behavior.

- **PersonHog** router/replica and clients are enabled by default. Keep the existing persons database; do not redirect existing persons to a new empty database. `migrate.persons.skipPartitioning=true` runs the supported nonpartitioned `--hobby` migration. Identity/leader mode is not required.
- **Cymbal resolution** is mandatory and enabled by default, inheriting the Cymbal image. It uses a headless gRPC Service on 50061 and HTTP health endpoints on 9106. Replace any existing non-headless resolver Service before upgrading. For an external resolver, disable `cymbalResolution` and set `cymbal.remoteResolution.host`.
- **Valkey** is an independent, disposable CDP shadow store; Redis remains the primary cache. Bundled Valkey is authenticated. An `existingSecret` must gain `valkey-password`; external settings are under `externalValkey`.
- **Browserless** replaces local Chromium. An `existingSecret` must gain `browserless-token`. External CDP/heatmap endpoints use `externalBrowserless` and separate `browserless-token` / `heatmap-browserless-token` keys. Browserless must reach `SITE_URL` and screenshot targets. Disable cloud-only consent-modal blocking on saved heatmaps when using Browserless OSS.
- **AI ingestion** uses `events_plugin_ingestion_ai` and the combined worker. External storage must provision `objectStorage.aiBlobs.bucket` (default `ai-blobs`), with HEAD/GET/PUT/self-copy permissions. Keep bucket/prefix stable and retention at least 31 days.
- **Granian** is the only web server; it runs as the configured UID and exposes Prometheus on 8001. Remove `web.granian.enabled`, `USE_GRANIAN`, Unit-specific overrides, `personhog.rolloutPercentage`, `cyclotronJanitor`, and legacy `externalPostgresql.cyclotron*` keys except the retained `cyclotronNode*` settings.
- **Usage ingestion** is optional (`usageIngestion.enabled=false`). Before enabling reporting, migrate ClickHouse, provision `clickhouse_billing_usage_records`, pin its image and set `reportTeams` deliberately. Keep its unauthenticated gRPC service internal. Flags-consumer remains upstream opt-in and is not required.

External ClickHouse operators may set `externalClickhouse.dictReaderUser=dict_reader` after provisioning that local-only SELECT user with the existing ClickHouse password. Endpoint overrides remain under `posthog.env` / `posthog.secretEnv`; empty dedicated Node Redis hosts intentionally reuse `REDIS_URL`, including authentication and TLS.

## Two ClickHouse modes

The chart supports two installation methods for ClickHouse:

### Bundled (default)

```yaml
clickhouse:
  enabled: true
  database: posthog
  apiPassword: "change-me"
  appPassword: "change-me"
```

Deploys a single-node ClickHouse StatefulSet as part of the chart. Good for dev and small demos. Zero external dependencies.

### External (production)

```yaml
clickhouse:
  enabled: false

externalClickhouse:
  host: clickhouse-posthog.posthog.svc.cluster.local
  user: default
  apiUser: api
  appUser: app
  cluster: posthog
  secretName: posthog-clickhouse-password
  secretPasswordKey: password
```

Points the chart at an externally-managed ClickHouse (operator-managed, managed service, etc.). Passwords come from a Kubernetes Secret you own. The manifests path in `../../manifests` sets this up with the Altinity ClickHouse Operator.

## Using external infrastructure

Every bundled dependency can be disabled and replaced with an external endpoint:

```yaml
postgresql:
  enabled: false
externalPostgresql:
  host: my-cnpg-cluster-rw
  port: 5432
  database: posthog
  personsDatabase: posthog_persons
  secretName: posthog-pg-app
  usernameKey: username
  passwordKey: password

kafka:
  enabled: false
externalKafka:
  brokers: "kafka-1:9092,kafka-2:9092"

redis:
  enabled: false
externalRedis:
  url: "redis://dragonfly:6379/"

rustfs:
  enabled: false
externalObjectStorage:
  endpoint: https://my-account.r2.cloudflarestorage.com
  accessKey: "…"
  secretKey: "…"
```

When `clickhouse.enabled=false`, the bundled `zookeeper` is also automatically skipped — external ClickHouse brings its own coordinator.

## Ingress routing

The chart supports five ingress implementations, enabled via `ingress.<type>.enabled`:

| Type | Values key | When to use |
|---|---|---|
| NGINX Ingress | `ingress.nginx.enabled` | Standard NGINX Ingress Controller |
| Traefik IngressRoute | `ingress.traefik.enabled` | Traefik v2/v3 CRDs |
| Gateway API | `ingress.gateway.enabled` | Kubernetes Gateway API (v1) |
| Istio VirtualService | `ingress.istio.enabled` | Istio service mesh |
| OpenShift Route | `ingress.openshift.enabled` | OpenShift clusters |

All five produce path-based routing that mirrors PostHog's upstream Caddy config:

| Path | Backend |
|---|---|
| `/e/*`, `/i/v0/*`, `/batch/*`, `/capture/*`, `/i/v1/analytics/events` | capture |
| `/i/v0/ai/*`, `/i/v1/ai/events` | capture-ai |
| `/s/*` | replay-capture |
| `/flags/*` | feature-flags |
| `/livestream/*` | livestream (WebSocket) |
| `/public/webhooks/*` | plugins |
| `/*` | web (Django) |

Set `ingress.hostname` before installing — the default `posthog.example.com` won't resolve.

## Production checklist

- [ ] Override `posthog.secret` and `posthog.encryptionSaltKeys`, or set `existingSecret` to point at a pre-created Secret
- [ ] Set a real `ingress.hostname`
- [ ] Enable TLS: `ingress.nginx.tls.enabled=true` with cert-manager or a pre-populated secret
- [ ] Switch at least Postgres and ClickHouse to external managed services
- [ ] Enable `podDisruptionBudget.enabled=true` on `web`, `worker`, `capture`
- [ ] Enable `autoscaling.enabled=true` on horizontally scalable services such as `web`, `capture`, `feature-flags`, `workerExports`, and `temporalDjangoWorker`
- [ ] Pin storage classes via `persistence.storageClass`
- [ ] Enable `networkPolicies.enabled=true` for network-level isolation
- [ ] Enable `metrics.enabled=true` if you run `prometheus-operator`

## Uninstall

```bash
helm uninstall posthog -n posthog
kubectl delete pvc -n posthog -l app.kubernetes.io/instance=posthog
```

PersistentVolumeClaims are not deleted automatically.

## Configuration reference

All configuration is in [`values.yaml`](values.yaml), organized by top-level section:

| Section | What it configures |
|---|---|
| `global` | Default security contexts, scheduling, image pull secrets |
| `posthog` | PostHog app image and env var overrides |
| `ingress` | Ingress/Gateway routing (five backends) |
| `postgresql` / `externalPostgresql` | Primary Postgres (Django + Cyclotron) |
| `clickhouse` / `externalClickhouse` | Analytics database |
| `redis` / `externalRedis` | Cache and Celery broker |
| `kafka` / `externalKafka` | Event streaming (bitnami subchart) |
| `zookeeper` | Bundled CH coordinator — auto-disabled when `clickhouse.enabled=false` |
| `rustfs` / `externalObjectStorage` | S3-compatible blob storage |
| `externalSeaweedfs` | Session recording v2 storage (defaults to RustFS when bundled) |
| `elasticsearch` | Temporal visibility backend |
| `temporal` | Workflow orchestrator |
| `geoip` | MaxMind GeoIP sidecar |
| `web` / `worker` / `workerBeat` / `workerExports` | Django app, Celery workers, and Celery scheduler |
| `mcp` | Model Context Protocol server for agent access |
| `plugins` | Node.js CDP / ingestion service |
| `capture` / `replayCapture` / `captureAi` / `captureLogs` | Rust capture services |
| `featureFlags` / `propertyDefsRs` / `livestream` / `cymbal` / `cymbalResolution` | Auxiliary Rust services |
| `personhog` / `personhogRouter` / `personhogReplica` | Required persons read services |
| `valkey` / `externalValkey` | CDP shadow cache |
| `browserless` / `externalBrowserless` | Remote export and heatmap rendering |
| `usageIngestion` | Optional internal usage-reporting gateway |
| `temporalDjangoWorker` | Django worker processing Temporal workflows |
| `migrate` / `asyncMigrationsCheck` / `kafkaInit` | Install hook settings |
| `networkPolicies` | Default-deny ingress + explicit allow rules |
| `metrics` | Prometheus ServiceMonitor CRs |

Each application component supports `replicas`, `image`, `resources`, `podSecurityContext`, `containerSecurityContext`, `nodeSelector`, `tolerations`, `affinity`, `podAnnotations`, `extraEnv`, and (where relevant) `autoscaling`, `podDisruptionBudget`, `extraVolumes`, `extraVolumeMounts`, `sidecarContainers`.

Worker scaling is controlled with `worker.replicas`, `worker.concurrency`, `worker.autoscaling`, `workerExports.replicas`, `workerExports.concurrency`, and `temporalDjangoWorker.autoscaling`. The chart maps worker concurrency to `WEB_CONCURRENCY`, which is the value consumed by PostHog's Celery entrypoint, and also emits `CELERY_WORKER_CONCURRENCY` for compatibility/visibility. `workerBeat.enabled=true` runs RedBeat as a separate scheduler pod, so scheduler restarts do not restart the main Celery worker.

### MCP server

The MCP server is disabled by default. Enable it on the existing PostHog hostname:

```yaml
mcp:
  enabled: true
```

MCP clients connect to `https://<ingress.hostname>/mcp`. The chart routes the
protocol, legacy SSE, UI apps, and OAuth metadata paths to the MCP service while
PostHog web continues to serve the OAuth authorization endpoints.

`mcp.apiBaseUrl`, `mcp.publicUrl`, and `mcp.appsBaseUrl` default to
`https://<ingress.hostname>` and can be overridden independently. The chart
generates and preserves `mcp-signed-state-key`; when `existingSecret` is used,
that Secret must provide both `redis-url` and `mcp-signed-state-key`.

## Chart dependencies

```yaml
dependencies:
  - name: kafka
    repository: oci://registry-1.docker.io/bitnamicharts
  - name: rustfs
    repository: https://charts.rustfs.com
```

Build them before packaging:

```bash
helm dependency build ./charts/posthog
```
