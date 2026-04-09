# PostHog Helm Chart

Deploys [PostHog](https://posthog.com) on Kubernetes with bundled infrastructure (ClickHouse, Kafka, Postgres, Redis, object storage). Use this path for **local dev, POCs, and quick self-host demos**. For a production-grade operator-based setup, use the manifests path in [`../../manifests`](../../manifests/README.md).

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
| ClickHouse | Single-node StatefulSet, stock `clickhouse/clickhouse-server` |
| Kafka | bitnami/kafka subchart in KRaft mode with topic auto-provisioning |
| Postgres | Single StatefulSet with `postgres:15-alpine` |
| Redis | Single StatefulSet with `redis:7-alpine` |
| Object storage | rustfs subchart (S3-compatible) |
| Temporal | Auto-setup server + UI |
| Elasticsearch | Single node, for Temporal visibility |

## Install hooks

The chart ships with five install hooks that run as Helm Jobs, ordered by weight:

| Weight | Hook | Runs at | Purpose |
|---:|---|---|---|
| `-1` | `db-check` | `post-install,post-upgrade` | `nc -z` probe against Redis, Kafka, Postgres, ClickHouse, ZooKeeper — waits until everything is reachable before the other hooks run |
| `0` | `kafka-init` | `pre-install,pre-upgrade` | Only when using **external** Kafka (`kafka.enabled=false`). Creates topics via `kafka-topics.sh` against `externalKafka.brokers`. Skipped for bundled Kafka because the subchart has its own `provisioning.topics`. |
| `1` | `create-buckets` | `post-install` | Only when `rustfs.enabled=true`. Uses `minio/mc` to create the `posthog` bucket on the bundled RustFS instance. |
| `7` | `migrate` | `post-install,post-upgrade` | Runs `python manage.py migrate` and `migrate_clickhouse`. |
| `10` | `async-migrations-check` | `post-install,post-upgrade` | Runs `python manage.py run_async_migrations`. |

The hook container for `migrate`/`async-migrations-check` is the `posthog-migrate` slim image (`ghcr.io/blitss/posthog-migrate` by default) — no Node, no Chromium, no Playwright.

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
  migrationsCluster: posthog
  singleShardCluster: posthog
  writableCluster: posthog
  primaryReplicaCluster: posthog
  logsCluster: posthog
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
  cyclotronDatabase: cyclotron
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
| `/e/*`, `/i/v0/*`, `/batch/*`, `/capture/*` | capture |
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
- [ ] Enable `autoscaling.enabled=true` on `web`, `capture`, `feature-flags`
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
| `web` / `worker` / `workerExports` | Django app + Celery workers |
| `plugins` | Node.js CDP / ingestion service |
| `capture` / `replayCapture` / `captureAi` / `captureLogs` | Rust capture services |
| `featureFlags` / `propertyDefsRs` / `livestream` / `cymbal` / `cyclotronJanitor` | Auxiliary Rust services |
| `temporalDjangoWorker` | Django worker processing Temporal workflows |
| `migrate` / `asyncMigrationsCheck` / `kafkaInit` | Install hook settings |
| `networkPolicies` | Default-deny ingress + explicit allow rules |
| `metrics` | Prometheus ServiceMonitor CRs |

Each application component supports `replicas`, `image`, `resources`, `podSecurityContext`, `containerSecurityContext`, `nodeSelector`, `tolerations`, `affinity`, `podAnnotations`, `extraEnv`, and (where relevant) `autoscaling`, `podDisruptionBudget`, `extraVolumes`, `extraVolumeMounts`, `sidecarContainers`.

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
