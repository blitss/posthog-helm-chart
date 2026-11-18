# PostHog Helm chart

Community chart that runs [PostHog](https://posthog.com) on Kubernetes. It is not published or supported by PostHog.

By default it deploys PostHog and every store it needs in one release: PostgreSQL, ClickHouse (with ZooKeeper), Kafka, Redis, Valkey, S3-compatible object storage (RustFS), Temporal and Elasticsearch. Each store is a single pod. That is fine for a trial or a small install. For production, switch the stores to external services (see [External stores](#external-stores)) or use the operator-based [Flux manifests](../../manifests/README.md).

CI smoke-tests the chart through the Flux manifests (operator-managed stores, split images). The all-bundled defaults are render-tested only.

- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Reach the UI](#reach-the-ui)
- [Common configurations](#common-configurations)
- [Values reference](#values-reference)
- [Install hooks](#install-hooks)
- [Troubleshooting](#troubleshooting)
- [Uninstall](#uninstall)
- [Upgrading](#upgrading)

## Prerequisites

| Requirement | Notes |
|---|---|
| Kubernetes 1.23 or newer | `kubeVersion: '>= 1.23.0-0'` in `Chart.yaml` (autoscaling/v2). |
| Helm 3 | CI and `mise.toml` use Helm 3.22.1. Helm 4 is untested. |
| CPU and memory | With the defaults, pod requests total about 18 GiB of memory and 8.5 CPUs (limits about 37 GiB). Lower `<component>.resources.requests` to fit a smaller node. |
| Storage | A default StorageClass. Bundled volumes total about 130 GiB (ClickHouse 50Gi, PostgreSQL 20Gi, Kafka 20Gi, RustFS 20Gi, Elasticsearch 10Gi, Redis 5Gi, ZooKeeper 5Gi). |
| CPU architecture | amd64. The split PostHog images from this repository are built for amd64 only. |
| Routing (optional) | One of: ingress-nginx, Traefik CRDs, Gateway API, Istio, OpenShift Routes. Not needed for port-forward access. |

## Quick start

From a checkout of this repository. This installs everything bundled, with no ingress, and uses port-forward:

```bash
git clone https://github.com/blitss/posthog-helm-chart
cd posthog-helm-chart
helm install posthog ./charts/posthog \
  --namespace posthog --create-namespace \
  -f charts/posthog/examples/images.yaml \
  -f charts/posthog/examples/local.yaml \
  --timeout 30m
```

What the flags do:

- `examples/images.yaml` selects the split PostHog images that this repository builds and CI smoke-tests. The `migrate` hook runs `manage.py migrate_legacy_model_moves`, which exists only in the `posthog-migrate` image.
- `examples/local.yaml` disables routing and sets `SITE_URL=http://localhost:8000` and `SECURE_COOKIES=false`.
- `--timeout 30m`: `helm install` waits for the hook Jobs (database checks and migrations). The default 5 minutes is often too short.
- Do not add `--wait` or `--atomic`. With `--wait`, Helm waits for all pods to be ready before it runs post-install hooks, but the web pod is not ready until the `migrate` hook has run. The install then times out.

The chart is also published as an OCI artifact. Pass an explicit version; the newest published version can lag behind `main`:

```bash
helm show chart oci://ghcr.io/blitss/charts/posthog   # prints the newest published version
helm install posthog oci://ghcr.io/blitss/charts/posthog --version <version> \
  --namespace posthog --create-namespace -f my-values.yaml --timeout 30m
```

A kind cluster for local tests: `./scripts/kind-bootstrap.sh --recreate` (see `--help`).

## Reach the UI

Without ingress or DNS:

```bash
kubectl -n posthog port-forward svc/posthog-web 8000:8000
```

Open http://localhost:8000 and create the first user. Plain-http login needs `posthog.env.SITE_URL=http://localhost:8000` and `posthog.env.SECURE_COOKIES="false"` (both set by `examples/local.yaml`).

Resource names are `<release>-<component>` (`posthog-web` for release `posthog`). If the release name contains `posthog`, the prefix is the release name alone.

With routing enabled, PostHog is at `https://<ingress.hostname>`. Point DNS for that hostname at your ingress controller or gateway.

The install notes (URL, routing, hook commands, a production checklist) can be printed again at any time:

```bash
helm get notes posthog -n posthog
```

## Common configurations

All examples live in [`examples/`](examples/) and are render-tested by `scripts/test-chart-render.sh`. Combine them with `-f`; later files win.

| File | Use |
|---|---|
| [`images.yaml`](examples/images.yaml) | Split PostHog images. Include it in every install for now. |
| [`local.yaml`](examples/local.yaml) | Local or kind cluster, no ingress, port-forward. |
| [`ingress-nginx-tls.yaml`](examples/ingress-nginx-tls.yaml) | ingress-nginx with a cert-manager certificate. |
| [`gateway-api.yaml`](examples/gateway-api.yaml) | Gateway API HTTPRoute. |
| [`external-stores.yaml`](examples/external-stores.yaml) | External PostgreSQL, ClickHouse, Kafka, Redis, Valkey and S3 with `existingSecret`. |

### Hostname and SITE_URL

`ingress.hostname` (default `posthog.example.com`) sets the route host and these defaults:

| Variable | Default |
|---|---|
| `SITE_URL` | `https://<ingress.hostname>` |
| `OBJECT_STORAGE_PUBLIC_ENDPOINT` | `https://<ingress.hostname>` |
| `LIVESTREAM_HOST` | `https://<ingress.hostname>/livestream` |

Override `SITE_URL` with `posthog.env.SITE_URL`, for example when TLS is terminated somewhere else or for plain-http access.

### Routing

`ingress.enabled` (default `true`) is the master switch. Each mode has its own flag; only `ingress.nginx.enabled` is on by default. More than one mode can be enabled.

| Mode | Flag | Renders | Settings |
|---|---|---|---|
| ingress-nginx | `ingress.nginx.enabled` | `networking.k8s.io/v1` Ingress | `className`, `annotations`, `tls.enabled`, `tls.secretName` |
| Traefik | `ingress.traefik.enabled` | `traefik.io/v1alpha1` IngressRoute | `entryPoints`, `annotations`, `tls.certResolver`, `tls.secretName` |
| Gateway API | `ingress.gateway.enabled` | `gateway.networking.k8s.io/v1` HTTPRoute | `gatewayName`, `gatewayNamespace`, `listenerName` |
| Istio | `ingress.istio.enabled` | `networking.istio.io/v1` VirtualService | `gateway` (`namespace/name`), `annotations` |
| OpenShift | `ingress.openshift.enabled` | `route.openshift.io/v1` Routes | `tls.termination`, `tls.insecureEdgeTerminationPolicy` |

Every mode sends these paths to these Services (paths of disabled components are left out):

| Path | Service |
|---|---|
| `/mcp`, `/sse`, `/ui-apps`, `/.well-known/oauth-protected-resource`, `/.well-known/openai-apps-challenge` | mcp (only with `mcp.enabled`) |
| `/i/v0/ai`, `/i/v1/ai/events` | capture-ai |
| `/i/v1/logs`, `/i/v1/traces` | capture-logs |
| `/e`, `/i/v0`, `/i/v1/analytics/events`, `/batch`, `/capture` | capture |
| `/s` | replay-capture |
| `/flags` | feature-flags |
| `/surveys`, `/api/surveys`, `/array` | hypercache-server |
| `/livestream` | livestream (WebSocket) |
| `/public/webhooks`, `/public/m` | plugins |
| `/posthog` | rustfs (bundled object storage), else web |
| everything else | web |

ingress-nginx notes: TLS is on by default. With an empty `ingress.nginx.tls.secretName` the controller serves its default certificate; the chart adds no cert-manager annotation itself. The chart always sets the `nginx.ingress.kubernetes.io/configuration-snippet` annotation (WebSocket upgrade headers), so the controller must allow snippet annotations.

### Secrets

By default the chart creates `<release>-secrets`. It generates `posthog-secret`, `encryption-salt-keys`, `internal-api-secret`, `browserless-token`, `valkey-password` and `mcp-signed-state-key` on first install and keeps them on upgrade (Helm `lookup`). Back this Secret up: losing `posthog-secret` or `encryption-salt-keys` breaks sessions and encrypted data.

`lookup` returns nothing under `helm template` and tools built on it (for example Argo CD). There, new random values are rendered on every sync. Use `existingSecret` in that case.

Set `existingSecret: <name>` to manage the Secret yourself. The chart then creates no Secret. Required keys:

| Condition | Keys |
|---|---|
| always | `posthog-secret`, `encryption-salt-keys`, `internal-api-secret`, `recording-api-jwt-secret`, `redis-url`, `object-storage-access-key`, `object-storage-secret-key`, `seaweedfs-access-key`, `seaweedfs-secret-key` |
| `postgresql.enabled` (bundled) | `database-url`, `postgresql-password` |
| `clickhouse.enabled` (bundled) | `clickhouse-api-password`, `clickhouse-app-password` |
| `valkey.enabled` (bundled) | `valkey-password` (optional with external Valkey) |
| `browserless.enabled` (bundled) | `browserless-token` |
| `externalBrowserless.cdpUrl` / `heatmapUrl` | `browserless-token` / `heatmap-browserless-token` |
| `mcp.enabled` | `mcp-signed-state-key` |

With bundled RustFS, the object-storage and seaweedfs keys must equal `rustfs.secret.rustfs.access_key` and `secret_key`. The chart does not check the keys at render time; a missing key shows up as a pod in `CreateContainerConfigError`.

Do not switch an existing release from the chart-managed Secret to `existingSecret` in one upgrade: Helm deletes `<release>-secrets` when it leaves the chart. Copy it under a new name first.

Other secret-related values: `posthog.secretEnv` maps environment variables to keys in any Secret; `externalPostgresql.secretName`, `externalClickhouse.secretName` and `externalElasticsearch.secretName` hold store credentials.

### External stores

Disable the bundled store and fill its `external*` block. A disabled store without its endpoint fails at render time (see [Render-time errors](#render-time-errors)). [`examples/external-stores.yaml`](examples/external-stores.yaml) shows all of them together.

| Store | Disable | Configure |
|---|---|---|
| PostgreSQL | `postgresql.enabled=false` | `externalPostgresql.host` plus `secretName` (keys `usernameKey`/`passwordKey`; URLs for the main, persons and `cyclotron_node` databases are built from them). Inline `url`/`personsUrl`/`cyclotronNodeUrl` also work. Always set `host`: the db-check hook waits for it. |
| ClickHouse | `clickhouse.enabled=false` | `externalClickhouse.host`, `user`, `apiUser`, `appUser`, `cluster`, `secretName`, `secretPasswordKey` (one password for all users). Also set `zookeeper.enabled=false`. `externalClickhouse.logsDatabase` must equal `clickhouse.database`. |
| Kafka | `kafka.enabled=false` | `externalKafka.brokers`. The `kafka-init` hook creates the topics in `kafkaInit.topics`. Use a single `host:port`: the db-check hook cannot parse a list. |
| Redis | `redis.enabled=false` | `externalRedis.url` (`rediss://` for TLS), or the `redis-url` key of `existingSecret`, or `posthog.secretEnv.REDIS_URL`. |
| Valkey | `valkey.enabled=false` | `externalValkey.host`, `port`, `tls`, `password`, `readerHost`. |
| Object storage | `rustfs.enabled=false` | `externalObjectStorage.endpoint`, `accessKey`, `secretKey`; session recordings use `externalSeaweedfs.endpoint`, `accessKey`, `secretKey`. Path-style S3. The bucket `posthog` and `objectStorage.aiBlobs.bucket` (default `ai-blobs`) must already exist; the chart only creates buckets in bundled RustFS. |
| Temporal | `temporal.enabled=false` | `externalTemporal.host`. The Temporal Django worker is then not deployed. |
| Elasticsearch | `elasticsearch.enabled=false` | `externalElasticsearch.host`, `scheme`, `user`, `password` or `secretName`/`passwordKey`, `version`. Used only by the bundled Temporal. |
| Browserless | `browserless.enabled=false` | `externalBrowserless.cdpUrl`, `token`, `heatmapUrl`, `heatmapToken`. |

### Scaling, resources and availability

Every workload block has `resources`. Most have `replicas`, `podSecurityContext`, `containerSecurityContext`, `nodeSelector`, `tolerations`, `affinity`, `podAnnotations` and `extraEnv`. `web`, `worker`, `workerBeat`, `workerExports` and `plugins` also have `extraVolumes`, `extraVolumeMounts` and `sidecarContainers`. `global.*` holds defaults that components override (security contexts and annotations are merged; `nodeSelector` is merged; `tolerations` and `affinity` are replaced).

HPA (`<component>.autoscaling.enabled`, `minReplicas`, `maxReplicas`, `targetCPUUtilizationPercentage`, `targetMemoryUtilizationPercentage`) and PDB (`<component>.podDisruptionBudget.enabled`, `minAvailable` or `maxUnavailable`) exist for: `web`, `worker`, `workerExports`, `temporalDjangoWorker`, `plugins`, `capture`, `replayCapture`, `featureFlags`, `hypercacheServer`, `personhogReplica`, `personhogRouter`, `cymbalResolution`. `workerBeat` has a PDB only. An HPA or PDB renders only when its workload is enabled.

The `ingestionGeneral`, `ingestionSessionReplay`, `recordingApi`, `ingestionErrorTracking`, `ingestionLogs` and `ingestionTraces` Deployments run `plugins.image` with one replica; only `resources` is configurable.

Other tuning: `worker.concurrency` (Celery prefork, exported as `WEB_CONCURRENCY` and `CELERY_WORKER_CONCURRENCY`), `worker.queues`, `workerExports.concurrency`, `web.granian.workers`, `web.startupProbe.*`, `redis.maxmemory`, `valkey.maxmemory`. Volume size and class: `postgresql.persistence.*`, `clickhouse.persistence.*`, `redis.persistence.*`, `zookeeper.persistence.*`, `elasticsearch.persistence.*`, `kafka.controller.persistence.*`, `rustfs.storageclass.*`.

### Images, mirrors and pull secrets

| What | Values |
|---|---|
| Django images (web, workers, hooks) | `posthog.image` is the default; `web.image`, `worker.image`, `workerBeat.image` (then `worker.image`), `workerExports.image`, `temporalDjangoWorker.image`, `migrate.image`, `asyncMigrationsCheck.image` override it field by field. |
| Other PostHog services | `<component>.image.repository`, `tag`, `pullPolicy` (`plugins`, `capture`, `featureFlags`, `cymbal`, ...). `cymbalResolution.image` falls back to `cymbal.image`. Defaults are pinned as `tag@digest` with pull policy `IfNotPresent`. |
| Shell helpers | `utilityImage`: one busybox reference for db-check, wait-for-redis, GeoIP download and server, the Elasticsearch sysctl init container and the cymbal wait. Needs `sh`, `nc`, `wget`, `httpd`, `sysctl`. |
| Third-party images | `postgresql.image`, `clickhouse.image`, `redis.image`, `valkey.image`, `zookeeper.image`, `elasticsearch.image`, `temporal.server.image`, `temporal.ui.image`, `browserless.image`, `geoip.image`, `kafkaInit.image`, `rustfs.image.clientImage` (create-buckets), `cyclotronMigrate.image`. |
| Subcharts | Kafka: `kafka.image.registry`, `kafka.image.repository` (Bitnami chart values). RustFS: `rustfs.image.*`. |
| Pull secrets | `global.imagePullSecrets` (also read by the Kafka subchart). RustFS reads `rustfs.imagePullSecrets`. The db-check, create-buckets, migrate and async-migrations-check Jobs get neither and run as the namespace's `default` ServiceAccount; add the secret there: `kubectl -n posthog patch serviceaccount default -p '{"imagePullSecrets":[{"name":"my-registry-secret"}]}'`. |

### Network policies

`networkPolicies.enabled=true` adds ingress-only NetworkPolicies: default-deny for chart pods, any source to the public HTTP services, and release pods to the stores and internal services. Egress is not restricted. The `geoip` and `recording-api` pods match no allow rule, so other pods cannot reach them while policies are on.

### Metrics

`metrics.enabled=true` creates ServiceMonitors (prometheus-operator CRDs required) for web (`/metrics` on the metrics port), plugins, capture, personhog-replica, personhog-router and cymbal-resolution. Set `metrics.serviceMonitor.additionalLabels` to match your Prometheus selector; `interval` and `scrapeTimeout` are also there.

### Optional components

| Component | Enable | Notes |
|---|---|---|
| MCP server | `mcp.enabled` | Served at `https://<ingress.hostname>/mcp`. `mcp.apiBaseUrl`, `publicUrl`, `appsBaseUrl` default to the ingress URL. |
| Export worker | `workerExports.enabled` | Separate Celery worker for the `exports` queue. |
| HogFlow scheduler | `cdpHogflowScheduler.enabled` | Scheduled Workflows. Needs a current `plugins.image`. |
| Cyclotron v2 janitor | `cdpCyclotronV2Janitor.enabled` | Needs `cyclotronMigrate.enabled`. |
| Cyclotron migration | `cyclotronMigrate.enabled` | Hook that creates and migrates the `cyclotron_node` database. |
| Usage ingestion | `usageIngestion.enabled` | Reports nothing until `usageIngestion.reportTeams` is set. |
| GeoIP | `geoip.enabled` (on) | `geoip.downloadUrl`, `brotli`, `filename`, or `geoip.existingPvc` with the MMDB file. |

## Values reference

[`values.yaml`](values.yaml) is the full reference and is commented. This section lists the top-level blocks and the settings people change most.

### Components

| Block | What it is | Default | Turned off by / external block |
|---|---|---|---|
| `web` | Django UI and API (Granian) | on | `web.enabled` |
| `worker` | Celery worker | on | `worker.enabled` |
| `workerBeat` | Celery beat (RedBeat), separate pod | on | `workerBeat.enabled`; also off when `worker.enabled=false` |
| `workerExports` | Celery `exports` queue worker | off | `workerExports.enabled` |
| `temporalDjangoWorker` | Django worker for Temporal workflows | on | follows `temporal.enabled` |
| `plugins` | Node.js plugin server; also runs the `ingestion*` and `recordingApi` Deployments | on | `plugins.enabled` |
| `cdpHogflowScheduler`, `cdpCyclotronV2Janitor` | Plugin-server singletons | off | `<block>.enabled` |
| `capture`, `replayCapture`, `captureAi`, `captureLogs` | Rust capture endpoints | on | `<block>.enabled` |
| `featureFlags`, `hypercacheServer`, `propertyDefsRs`, `livestream` | Rust services | on | `<block>.enabled` |
| `cymbal` | Error-tracking processor | on | `cymbal.enabled` |
| `cymbalResolution` | Symbol resolution for cymbal | on | `cymbalResolution.enabled`, then `cymbal.remoteResolution.host` is required |
| `personhog`, `personhogRouter`, `personhogReplica` | Persons read service | on | `personhog.enabled`; with the router off, `personhog.addr` is required |
| `usageIngestion` | Internal usage gateway | off | `usageIngestion.enabled` |
| `mcp` | MCP server | off | `mcp.enabled` |
| `browserless` | Remote Chromium for exports and heatmaps | on | `browserless.enabled` / `externalBrowserless` |
| `geoip` | Serves the GeoIP database to other pods | on | `geoip.enabled` |
| `postgresql` | PostgreSQL StatefulSet | on | `postgresql.enabled` / `externalPostgresql` |
| `clickhouse` | ClickHouse StatefulSet, image with the PostHog UDFs | on | `clickhouse.enabled` / `externalClickhouse` |
| `zookeeper` | Coordination for bundled ClickHouse | on | `zookeeper.enabled`; set false with external ClickHouse |
| `redis` | Redis StatefulSet, primary cache | on | `redis.enabled` / `externalRedis` |
| `valkey` | Valkey Deployment, CDP shadow store | on | `valkey.enabled` / `externalValkey` |
| `kafka` | Bitnami Kafka subchart, KRaft | on | `kafka.enabled` / `externalKafka` |
| `rustfs` | RustFS subchart, S3-compatible | on | `rustfs.enabled` / `externalObjectStorage`, `externalSeaweedfs` |
| `elasticsearch` | Elasticsearch StatefulSet, Temporal visibility | on | `elasticsearch.enabled` / `externalElasticsearch` |
| `temporal` | Temporal server (`temporal.server`) and UI (`temporal.ui.enabled`) | on | `temporal.enabled` / `externalTemporal` |
| `migrate`, `asyncMigrationsCheck`, `cyclotronMigrate`, `kafkaInit` | Hook Jobs | see [Install hooks](#install-hooks) | `<block>.enabled` |
| `objectStorage` | `OBJECT_STORAGE_ENABLED`, AI blob bucket and prefix | | |
| `networkPolicies`, `metrics` | See above | off | |
| `global`, `serviceAccount`, `utilityImage`, `nameOverride`, `fullnameOverride` | Shared settings | | |

### Frequently changed settings

| Key | Default | Effect |
|---|---|---|
| `ingress.hostname` | `posthog.example.com` | Route host; default for `SITE_URL`. |
| `ingress.enabled`, `ingress.<mode>.enabled` | `true`, nginx only | Routing. |
| `posthog.env` | `{}` | Extra environment for all PostHog containers, for example `SITE_URL`, `SECURE_COOKIES`, `ALLOWED_HOSTS`, `TRUSTED_PROXIES`. `values.yaml` lists common upstream settings. |
| `posthog.secretEnv` | `{}` | Same, from Secrets: `NAME: {name: <secret>, key: <key>}`. Wins over `posthog.env`. |
| `global.extraEnv`, `<component>.extraEnv` | `[]` | Plain env lists. |
| `existingSecret` | `''` | See [Secrets](#secrets). |
| `posthog.secret`, `posthog.encryptionSaltKeys`, `posthog.internalApiSecret` | generated | Fixed values instead of generated ones. |
| `postgresql.auth.password`, `clickhouse.apiPassword`, `clickhouse.appPassword` | `posthog`, `apipass`, `apppass` | Bundled store passwords. Change them. |
| `rustfs.secret.rustfs.access_key`, `secret_key` | placeholders | Bundled RustFS credentials. |
| `posthog.optOutCapture` | `'false'` | `'true'` disables PostHog's anonymous telemetry. |
| `serviceAccount.annotations` | `{}` | For IRSA or Workload Identity. |
| `objectStorage.aiBlobs.bucket`, `prefix`, `offloadTeams` | `ai-blobs`, `aio/`, `*` | AI payload offload. |
| `migrate.persons.enabled`, `migrate.persons.skipPartitioning` | `true`, `true` | Persons SQL migrations; `--hobby` (nonpartitioned) mode. |
| `migrate.resources`, `cyclotronMigrate.resources` | `{}` | Hook Job resources. |

### Render-time errors

The chart refuses to render these configurations. The first five come from `templates/validate.yaml`:

| Message | Fix |
|---|---|
| `kafka.enabled=false requires externalKafka.brokers` | Set `externalKafka.brokers`. |
| `redis.enabled=false requires externalRedis.url (or existingSecret / posthog.secretEnv.REDIS_URL)` | Provide the Redis URL in one of those places. |
| `rustfs.enabled=false requires externalObjectStorage.endpoint` | Set `externalObjectStorage.endpoint`. |
| `temporal.enabled=false requires externalTemporal.host` | Set `externalTemporal.host`. |
| `elasticsearch.enabled=false with the bundled Temporal requires externalElasticsearch.host` | Set `externalElasticsearch.host`. |
| `externalClickhouse.host is required when clickhouse.enabled=false` | Set `externalClickhouse.host`. |
| `externalValkey.host is required when valkey.enabled=false` | Set `externalValkey.host`. |
| `externalClickhouse.logsDatabase must match clickhouse.database: ...` | Remove the override or make the two equal. |
| `cymbal requires cymbalResolution.enabled=true or cymbal.remoteResolution.host ...` | Keep `cymbalResolution` on or point at an external resolver. |
| `personhog.enabled=true requires either personhogRouter.enabled=true ... or personhog.addr ...` | Keep the router on or set `personhog.addr`. |
| `externalBrowserless.token is required with externalBrowserless.cdpUrl (or use existingSecret)` | Same for `heatmapToken` with `heatmapUrl`. |
| `externalPostgresql.cyclotronNodeUrl is required when using a URI-key secret for cyclotron` | Set it, or set `externalPostgresql.host` so URLs are built from the Secret. |

## Install hooks

`helm install` and `helm upgrade` run the pre-install hook first, then the post-install hooks in weight order. Each Job is deleted when it succeeds; a failed Job stays so you can read its logs.

| Weight | Job | Hook | Runs when | What it does |
|---:|---|---|---|---|
| 0 | `kafka-init` | pre-install, pre-upgrade | `kafkaInit.enabled` and `kafka.enabled=false` | Creates `kafkaInit.topics` on `externalKafka.brokers` with `kafka-topics.sh`. |
| -1 | `db-check` | post-install, post-upgrade | always | Waits (`nc -z`) for bundled Redis, the first Kafka broker, bundled ZooKeeper (if `zookeeper.enabled`), external ClickHouse on 8123 and external PostgreSQL. It does not probe bundled ClickHouse or PostgreSQL. No timeout. |
| 0 | `kafka-provisioning` | post-install, post-upgrade | `kafka.enabled` | Bitnami subchart Job; creates `kafka.provisioning.topics`. |
| 1 | `create-buckets` | post-install, post-upgrade | `rustfs.enabled` | Creates the `posthog` and `objectStorage.aiBlobs.bucket` buckets in RustFS with curl (SigV4, `rustfs.image.clientImage`). |
| 6 | `cyclotron-migrate` | post-install, post-upgrade | `cyclotronMigrate.enabled` | Creates and migrates the `cyclotron_node` database with SQLx. |
| 7 | `migrate` | post-install, post-upgrade | `migrate.enabled` | Legacy model moves, Django and product migrations, persons SQL migrations, then ClickHouse migrations. |
| 10 | `async-migrations-check` | post-install, post-upgrade | `asyncMigrationsCheck.enabled` | `manage.py run_async_migrations --check`. |

Application pods start at the same time as the hooks and wait for them:

- `web` loops on `bin/migrate-check` and logs `Waiting for migrations to complete before starting web...` until `migrate` finishes. Its startup probe allows 20 minutes (`web.startupProbe`).
- `cymbal` and `cymbal-resolution` have an `ensure-object-storage-bucket` init container (bundled RustFS) and `cymbal` waits for `cymbal-resolution`.
- Pods that use Redis wait for bundled Redis; pods that use GeoIP download it from the `geoip` pod first.

## Troubleshooting

Start here:

```bash
kubectl -n posthog get jobs,pods -l app.kubernetes.io/instance=posthog
kubectl -n posthog logs -f job/posthog-db-check
kubectl -n posthog logs -f job/posthog-migrate
helm get notes posthog -n posthog
```

| Symptom | Cause and fix |
|---|---|
| `helm install` times out, release `failed` | The hooks took longer than `--timeout`, or `--wait` was used (see [Quick start](#quick-start)). Check the Job logs. When the cause is fixed, run `helm upgrade` with the same values; it re-runs the hooks. |
| `db-check` never finishes, logs `<host>:<port> not ready` | It retries forever. The named endpoint is unreachable or wrong. Known traps: `zookeeper.enabled` left on with external ClickHouse; `externalPostgresql.host` empty (it then logs `:5432 not ready`); a comma-separated `externalKafka.brokers`. |
| `migrate` fails with `Unknown command: 'migrate_legacy_model_moves'` | The hook image is not `posthog-migrate`. Set `migrate.image` (see `examples/images.yaml`). |
| `web` not Ready, logs `Waiting for migrations to complete` | Normal until `migrate` succeeds. If `migrate` failed, fix it and run `helm upgrade`. |
| `cymbal*` pods stuck in `Init` (`rustfs bucket posthog not ready`) | RustFS is not up or the object-storage keys do not match `rustfs.secret.rustfs.*`. Check `kubectl -n posthog logs deploy/posthog-rustfs`. |
| Pods in `CreateContainerConfigError`, `couldn't find key ... in Secret` | `existingSecret` (or another referenced Secret) lacks a key. See the key table in [Secrets](#secrets). |
| Temporal fails with a missing `<release>-app` Secret | External PostgreSQL without `externalPostgresql.secretName`. The bundled Temporal reads credentials from `secretName`, else from the CloudNativePG Secret `<release>-app`. |
| `Error: execution error ...` at install | A render-time check failed. See [Render-time errors](#render-time-errors). |
| Pods `Pending` | Not enough CPU or memory for the requests (about 18 GiB and 8.5 CPUs by default), or no default StorageClass. |
| Ingress rejected by the ingress-nginx admission webhook | Snippet annotations are disabled on the controller. Allow them, or use another routing mode. |
| Login loops or cookies are not set over http | Set `posthog.env.SITE_URL` to the URL you use and `posthog.env.SECURE_COOKIES: "false"` for plain http. |
| Image pull errors only on hook Jobs | Hooks do not get `global.imagePullSecrets`. Add the pull secret to the namespace's `default` ServiceAccount (see [Images](#images-mirrors-and-pull-secrets)). |

## Uninstall

```bash
helm uninstall posthog -n posthog
kubectl -n posthog get pvc            # data volumes remain after uninstall
kubectl delete namespace posthog      # deletes everything left, including all data
```

StatefulSet volumes and the RustFS volumes (`helm.sh/resource-policy: keep`) are not deleted by `helm uninstall`.

## Upgrading

Back up PostgreSQL and ClickHouse before every upgrade. Migrations are forward-only: `helm rollback` does not undo them. Read every section between your version and the target.

### Upgrading to 0.24

This release targets the PostHog build of 2026-11-17 (`f9239c1`). Databases created before the September 2026 squash must go through 0.23.x first.

- `existingSecret` needs a new key, `recording-api-jwt-secret`. Without it every application pod fails to start. With the chart-managed Secret the value is generated and kept; set `posthog.recordingApiJwtSecret` to choose it.
- Every upstream image default is now pinned as `tag@digest` and the pull policy changed from `Always` to `IfNotPresent`. If you override only `tag`, override the whole tag string, digest included.
- Capture reads `CAPTURE_OUTPUT_*`. Move any `KAFKA_TOPIC` or `CAPTURE_V1_*` set through `extraEnv` to the new names.
- External ClickHouse needs the four new default-profile settings and the `signals` profile and user that the bundled ClickHouse template now defines. Django fails without signals credentials.
- Bundled stores move: Temporal 1.20 to 1.29.7 (skips minors; schema auto-setup on an existing database is not verified), RustFS alpha.91 to beta.12 (on-disk compatibility is not verified), Kafka 3.7 to 3.9, PostgreSQL 15.20, ZooKeeper 3.9.7. Back up first, and test the upgrade on a copy if you run bundled Temporal or RustFS with data you cannot lose.
- The split Django images run Python 3.14.
- flags-consumer stays opt-in, as upstream does not start it by default.

### Upgrading to 0.23

- Fail-fast validation: a disabled bundled store without its external endpoint now fails at render time with one of the five `templates/validate.yaml` messages in [Render-time errors](#render-time-errors). Before, such configurations rendered and pointed at Services that did not exist.
- HPAs, PDBs and ServiceMonitors render only for enabled workloads. Objects that targeted a disabled Deployment (for example the `worker-exports` HPA and PDB with `workerExports.enabled=false`) are removed on upgrade.
- New `utilityImage` value: the busybox image for init, wait and helper containers. The default is the same pinned image as before; set it to use a mirror.
- `create-buckets` is a post-install/post-upgrade hook that runs after the migration hooks (weight 20) that uses curl instead of `minio/mc`. The cymbal bucket init containers use the same curl image (`rustfs.image.clientImage`).
- Removed values keys. No template read them, so setting them had no effect before either; delete them from your values: `bootstrapClickhouse`, `temporal.adminTools`, `externalClickhouse.createDatabase`, `objectStorage.containerSecurityContext`, `objectStorage.nodeSelector`, `objectStorage.tolerations`, `objectStorage.affinity`, `objectStorage.podAnnotations`.
- `NOTES.txt` now shows every routing mode, the effective `SITE_URL`, the hook commands and the port-forward command.

### Upgrading to 0.22

This release targets the September 2026 PostHog. ClickHouse must be 26.6.2 or newer. Use matching, immutable application images, and let the new migration Job finish before new application pods take traffic: post-upgrade hooks alone do not hold back the rollout.

- Legacy installations need this release's rebuilt `posthog-migrate` image. It runs the original product model moves before the September squash and backports the SCIM migration lookup ([#65](https://github.com/blitss/posthog-helm-chart/issues/65), [#66](https://github.com/blitss/posthog-helm-chart/issues/66)).
- Logs, traces and metrics must use `clickhouse.database`; a different `externalClickhouse.logsDatabase` fails rendering. If older versions created logs tables in `default`, reconcile them first ([#70](https://github.com/blitss/posthog-helm-chart/issues/70)).
- PersonHog router, replica and clients are on by default and use the existing persons database. `migrate.persons.skipPartitioning=true` keeps the nonpartitioned table.
- Cymbal resolution is required and on by default: headless gRPC Service on 50061, health and metrics on 9106. Replace an existing non-headless resolver Service before upgrading. For an external resolver, disable `cymbalResolution` and set `cymbal.remoteResolution.host`.
- Valkey is a new, authenticated CDP shadow store; Redis stays the primary cache. `existingSecret` needs `valkey-password`. External settings are under `externalValkey`.
- Browserless replaces local Chromium. `existingSecret` needs `browserless-token`. External endpoints use `externalBrowserless` with `browserless-token` / `heatmap-browserless-token`. Browserless must reach `SITE_URL`. Disable consent-modal blocking on saved heatmaps with Browserless OSS.
- AI ingestion uses `events_plugin_ingestion_ai`. External storage must provide `objectStorage.aiBlobs.bucket` (default `ai-blobs`) with HEAD, GET, PUT and self-copy permissions. Keep bucket and prefix stable and retain objects at least 31 days.
- Granian is the only web server; it exposes Prometheus metrics on 8001. Remove `web.granian.enabled`, `USE_GRANIAN`, Unit-specific overrides, `personhog.rolloutPercentage`, `cyclotronJanitor` and the `externalPostgresql.cyclotron*` keys except `cyclotronNode*`.
- Usage ingestion is optional (`usageIngestion.enabled=false`). Before enabling reporting, migrate ClickHouse, provision `clickhouse_billing_usage_records`, pin its image and set `reportTeams`. Keep its unauthenticated gRPC Service internal.
- External ClickHouse may set `externalClickhouse.dictReaderUser=dict_reader` after creating that SELECT-only user with the shared password. Empty `CDP_REDIS_HOST`, `LOGS_REDIS_HOST` and `TRACES_REDIS_HOST` reuse `REDIS_URL`.

The guarded procedure used to upgrade the `hub-production` deployment to 0.22 is in [manifests/README.md](../../manifests/README.md#guarded-setup-and-upgrade-runner).

## Development

See the [root README](../../README.md#contributing). Before sending a chart change, run `bash scripts/test-chart-render.sh`.
