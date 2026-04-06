# PostHog Helm Chart

A Helm chart to deploy [PostHog](https://posthog.com) -- the open-source product analytics platform -- on Kubernetes.

This chart is derived from the official PostHog "hobby" Docker Compose deployment and translates all 20+ services into Kubernetes-native resources with production-ready features.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.x
- An Ingress controller (NGINX Ingress by default, Traefik optional)
- Minimum **8 GB RAM** available across the cluster (all-in-one mode)

## Quick Start

### All-in-one (includes all dependencies)

```bash
helm install posthog ./charts/posthog \
  --set ingress.hostname=posthog.example.com
```

### With external services

```bash
helm install posthog ./charts/posthog \
  --set ingress.hostname=posthog.example.com \
  --set postgresql.enabled=false \
  --set externalPostgresql.url="postgres://user:pass@cnpg-cluster:5432/posthog" \
  --set redis.enabled=false \
  --set externalRedis.url="redis://dragonfly:6379/" \
  --set clickhouse.enabled=false \
  --set externalClickhouse.host="clickhouse.prod" \
  --set kafka.enabled=false \
  --set externalKafka.brokers="kafka-1:9092,kafka-2:9092" \
  --set minio.enabled=false \
  --set externalObjectStorage.endpoint="https://myaccount.blob.core.windows.net" \
  --set externalObjectStorage.accessKey="mykey" \
  --set externalObjectStorage.secretKey="mysecret"
```

### Using Traefik instead of NGINX Ingress

```bash
helm install posthog ./charts/posthog \
  --set ingress.hostname=posthog.example.com \
  --set ingress.nginx.enabled=false \
  --set ingress.traefik.enabled=true \
  --set ingress.traefik.tls.certResolver=letsencrypt
```

## Architecture

The chart deploys the following services, matching the PostHog hobby deployment architecture:

```
                         Ingress (NGINX / Traefik)
                                   |
        +-----------+-----------+--+--+-----------+-----------+
        |           |           |     |           |           |
   /e /batch    /s/*       /flags  /livestream  /public/    /*
   /i/v0                                       webhooks
   /capture                                                 
        |           |           |     |           |           |
     capture   replay-     feature  livestream  plugins      web
               capture     flags                           (Django)
                                                              |
                                                           worker
                                                          (Celery)
```

### Core Application Services

| Service | Image | Description |
|---------|-------|-------------|
| **web** | `posthog/posthog` | Main Django web application (Granian ASGI server) |
| **worker** | `posthog/posthog` | Celery worker with scheduler for background tasks |
| **plugins** | `posthog/posthog-node` | Node.js plugin server (CDP, webhooks, session recording API) |
| **capture** | `ghcr.io/posthog/posthog/capture` | Rust-based event capture service |
| **replay-capture** | `ghcr.io/posthog/posthog/capture` | Rust-based session recording capture |
| **feature-flags** | `ghcr.io/posthog/posthog/feature-flags` | Rust-based feature flag evaluation |
| **property-defs-rs** | `ghcr.io/posthog/posthog/property-defs-rs` | Rust-based property definitions service |
| **livestream** | `ghcr.io/posthog/posthog/livestream` | Live event streaming (WebSocket) |
| **cymbal** | `ghcr.io/posthog/posthog/cymbal` | Error/exception processing (stack traces, symbolication) |
| **cyclotron-janitor** | `ghcr.io/posthog/posthog/cyclotron-janitor` | Cleanup service for the Cyclotron job queue |
| **temporal-django-worker** | `posthog/posthog` | Django worker that processes Temporal workflows |

### Infrastructure Services (all optional)

| Service | Image | Description |
|---------|-------|-------------|
| **PostgreSQL** | `postgres:15.12-alpine` | Primary relational database |
| **ClickHouse** | `clickhouse/clickhouse-server:25.12.5.44` | Analytics/OLAP database |
| **Redis** | `redis:7.2-alpine` | Cache and queue broker |
| **Kafka (Redpanda)** | `redpanda:v25.1.9` | Event streaming / message queue |
| **ZooKeeper** | `zookeeper:3.7.0` | Distributed coordination for ClickHouse |
| **MinIO** | `minio/minio` | S3-compatible object storage |
| **SeaweedFS** | `chrislusf/seaweedfs:4.03` | S3-compatible storage for session recordings v2 |
| **Elasticsearch** | `elasticsearch:7.17.28` | Search engine (used by Temporal) |
| **Temporal** | `temporalio/auto-setup:1.20.0` | Workflow orchestration engine |
| **Temporal UI** | `temporalio/ui:2.31.2` | Web UI for Temporal workflows |

## Production Features

This chart includes a comprehensive set of production hardening features applied consistently across all components via shared helper templates.

### Security

- **Pod security contexts** (`global.podSecurityContext`): `runAsNonRoot`, `runAsUser`, `fsGroup`, `seccompProfile: RuntimeDefault` applied to all pods by default; per-component overrides merge with global defaults
- **Container security contexts** (`global.containerSecurityContext`): `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]` applied to all containers by default
- **ServiceAccount**: Dedicated service account with `automountServiceAccountToken: false`; supports annotations for IRSA (AWS), Workload Identity (GCP), etc.
- **Existing Secrets**: Use `existingSecret` to reference a pre-created Kubernetes Secret instead of having the chart generate one
- **ClickHouse passwords**: User passwords stored in a Kubernetes Secret (not a ConfigMap)
- **Network Policies**: Optional default-deny ingress with allow rules for frontend services, infrastructure access, and intra-app traffic (`networkPolicies.enabled`)

### High Availability

- **HorizontalPodAutoscaler (HPA)**: Available for web, worker, plugins, capture, replay-capture, and feature-flags; supports CPU and memory metrics (autoscaling/v2)
- **PodDisruptionBudget (PDB)**: Available for web, worker, plugins, capture, replay-capture, feature-flags, and temporal-django-worker; configurable `minAvailable` or `maxUnavailable`
- **Topology spread constraints**: Automatic zone and node spreading for all application deployments
- **HPA-aware replicas**: The `replicas` field is omitted from Deployments when HPA is enabled, allowing the autoscaler to manage the replica count

### Scheduling & Placement

- **Node selectors** (`nodeSelector`): Per-component, merges with `global.nodeSelector`
- **Tolerations** (`tolerations`): Per-component, overrides `global.tolerations`
- **Affinity** (`affinity`): Per-component, overrides `global.affinity`

### Extensibility

- **Extra environment variables** (`extraEnv`): Per-component and global (`global.extraEnv`)
- **Extra volumes / volume mounts** (`extraVolumes`, `extraVolumeMounts`): For web, worker, plugins
- **Sidecar containers** (`sidecarContainers`): For web, worker, plugins
- **Pod annotations** (`podAnnotations`): Per-component, merges with `global.podAnnotations`
- **Image pull secrets** (`global.imagePullSecrets`): For private container registries

### Monitoring

- **ServiceMonitors**: Prometheus ServiceMonitor resources for web, plugins, capture, and feature-flags (requires prometheus-operator CRDs; `metrics.enabled`)
- **Configurable scrape interval and timeout**
- **Additional labels** for ServiceMonitor discovery

## Configuration Reference

All configuration is done through `values.yaml`. See sections below for details.

### Global Production Settings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `global.imagePullSecrets` | Image pull secrets for private registries | `[]` |
| `global.podSecurityContext` | Default pod security context for all pods | `runAsNonRoot: true, runAsUser: 1000, ...` |
| `global.containerSecurityContext` | Default container security context | `allowPrivilegeEscalation: false, ...` |
| `global.nodeSelector` | Default node selector for all pods | `{}` |
| `global.tolerations` | Default tolerations for all pods | `[]` |
| `global.affinity` | Default affinity rules for all pods | `{}` |
| `global.podAnnotations` | Default pod annotations for all pods | `{}` |
| `global.extraEnv` | Extra env vars injected into all PostHog app containers | `[]` |

### ServiceAccount

| Parameter | Description | Default |
|-----------|-------------|---------|
| `serviceAccount.create` | Create a dedicated ServiceAccount | `true` |
| `serviceAccount.name` | ServiceAccount name override | `""` (uses fullname) |
| `serviceAccount.annotations` | ServiceAccount annotations (IRSA, Workload Identity) | `{}` |

### Existing Secrets

| Parameter | Description | Default |
|-----------|-------------|---------|
| `existingSecret` | Name of a pre-created Secret to use instead of chart-managed one | `""` |

When `existingSecret` is set, the chart will NOT create its own Secret. The referenced Secret must contain these keys:
`posthog-secret`, `encryption-salt-keys`, `database-url`, `redis-url`, `clickhouse-api-password`, `clickhouse-app-password`, `object-storage-access-key`, `object-storage-secret-key`, `seaweedfs-access-key`, `seaweedfs-secret-key`, `postgresql-password`

### PostHog Application

| Parameter | Description | Default |
|-----------|-------------|---------|
| `posthog.image.repository` | PostHog app image repository | `posthog/posthog` |
| `posthog.image.tag` | PostHog app image tag | `latest` |
| `posthog.image.pullPolicy` | Image pull policy | `Always` |
| `posthog.secret` | Django secret key (auto-generated if empty) | `""` |
| `posthog.encryptionSaltKeys` | Encryption salt keys (auto-generated if empty) | `""` |
| `posthog.optOutCapture` | Disable anonymous telemetry | `"false"` |

### Ingress

| Parameter | Description | Default |
|-----------|-------------|---------|
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.hostname` | Hostname for PostHog | `posthog.example.com` |
| `ingress.nginx.enabled` | Use NGINX Ingress controller | `true` |
| `ingress.nginx.className` | NGINX ingress class name | `nginx` |
| `ingress.nginx.annotations` | Additional NGINX ingress annotations | `{}` |
| `ingress.nginx.tls.enabled` | Enable TLS | `true` |
| `ingress.nginx.tls.secretName` | TLS secret name (empty = default issuer) | `""` |
| `ingress.traefik.enabled` | Use Traefik IngressRoute | `false` |
| `ingress.traefik.entryPoints` | Traefik entrypoints | `[websecure]` |
| `ingress.traefik.tls.certResolver` | Traefik cert resolver name | `""` |

### PostgreSQL

| Parameter | Description | Default |
|-----------|-------------|---------|
| `postgresql.enabled` | Deploy built-in PostgreSQL | `true` |
| `postgresql.image.repository` | PostgreSQL image | `postgres` |
| `postgresql.image.tag` | PostgreSQL version | `15.12-alpine` |
| `postgresql.auth.username` | Database username | `posthog` |
| `postgresql.auth.password` | Database password | `posthog` |
| `postgresql.auth.database` | Database name | `posthog` |
| `postgresql.persistence.enabled` | Enable persistent storage | `true` |
| `postgresql.persistence.size` | PVC size | `20Gi` |
| `postgresql.persistence.storageClass` | Storage class (empty = default) | `""` |
| `postgresql.resources` | CPU/memory resources | `500m/1Gi req, 2Gi limit` |
| `externalPostgresql.url` | External PostgreSQL URL (when `postgresql.enabled=false`) | `""` |

**External alternatives:** CNPG, Amazon RDS, Azure Database for PostgreSQL, Google Cloud SQL

### ClickHouse

| Parameter | Description | Default |
|-----------|-------------|---------|
| `clickhouse.enabled` | Deploy built-in ClickHouse | `true` |
| `clickhouse.image.repository` | ClickHouse image | `clickhouse/clickhouse-server` |
| `clickhouse.image.tag` | ClickHouse version | `25.12.5.44` |
| `clickhouse.database` | Database name | `posthog` |
| `clickhouse.secure` | Use TLS for ClickHouse connections | `"false"` |
| `clickhouse.verify` | Verify TLS certificates | `"false"` |
| `clickhouse.apiUser` / `clickhouse.apiPassword` | API user credentials | `api` / `apipass` |
| `clickhouse.appUser` / `clickhouse.appPassword` | App user credentials | `app` / `apppass` |
| `clickhouse.persistence.enabled` | Enable persistent storage | `true` |
| `clickhouse.persistence.size` | PVC size | `50Gi` |
| `clickhouse.persistence.storageClass` | Storage class | `""` |
| `clickhouse.resources` | CPU/memory resources | `1/4Gi req, 8Gi limit` |
| `externalClickhouse.host` | External ClickHouse host (when `clickhouse.enabled=false`) | `""` |

### Redis

| Parameter | Description | Default |
|-----------|-------------|---------|
| `redis.enabled` | Deploy built-in Redis | `true` |
| `redis.image.repository` | Redis image | `redis` |
| `redis.image.tag` | Redis version | `7.2-alpine` |
| `redis.maxmemory` | Max memory for Redis | `200mb` |
| `redis.persistence.enabled` | Enable persistent storage | `true` |
| `redis.persistence.size` | PVC size | `5Gi` |
| `redis.persistence.storageClass` | Storage class | `""` |
| `redis.resources` | CPU/memory resources | `100m/256Mi req, 512Mi limit` |
| `externalRedis.url` | External Redis URL (when `redis.enabled=false`) | `""` |

**External alternatives:** Dragonfly, Amazon ElastiCache, Azure Cache for Redis

### Kafka (Redpanda)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `kafka.enabled` | Deploy built-in Kafka (Redpanda) | `true` |
| `kafka.image.repository` | Redpanda image | `docker.redpanda.com/redpandadata/redpanda` |
| `kafka.image.tag` | Redpanda version | `v25.1.9` |
| `kafka.persistence.enabled` | Enable persistent storage | `true` |
| `kafka.persistence.size` | PVC size | `20Gi` |
| `kafka.persistence.storageClass` | Storage class | `""` |
| `kafka.logRetentionMs` | Kafka log retention (milliseconds) | `3600000` |
| `kafka.logRetentionHours` | Kafka log retention (hours) | `1` |
| `kafka.resources` | CPU/memory resources | `500m/1Gi req, 2Gi limit` |
| `externalKafka.brokers` | External Kafka brokers (when `kafka.enabled=false`) | `""` |

**External alternatives:** Amazon MSK, Confluent Cloud, Azure Event Hubs (Kafka protocol)

### ZooKeeper

| Parameter | Description | Default |
|-----------|-------------|---------|
| `zookeeper.enabled` | Deploy built-in ZooKeeper | `true` |
| `zookeeper.image.repository` | ZooKeeper image | `zookeeper` |
| `zookeeper.image.tag` | ZooKeeper version | `3.7.0` |
| `zookeeper.persistence.enabled` | Enable persistent storage | `true` |
| `zookeeper.persistence.size` | PVC size | `5Gi` |
| `zookeeper.persistence.storageClass` | Storage class | `""` |
| `zookeeper.resources` | CPU/memory resources | `100m/256Mi req, 512Mi limit` |

### MinIO (Object Storage)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `minio.enabled` | Deploy built-in MinIO | `true` |
| `minio.image.repository` | MinIO image | `minio/minio` |
| `minio.image.tag` | MinIO version | `RELEASE.2025-04-22T22-12-26Z` |
| `minio.accessKey` | MinIO root access key | `object_storage_root_user` |
| `minio.secretKey` | MinIO root secret key | `object_storage_root_password` |
| `minio.persistence.enabled` | Enable persistent storage | `true` |
| `minio.persistence.size` | PVC size | `20Gi` |
| `minio.persistence.storageClass` | Storage class | `""` |
| `minio.resources` | CPU/memory resources | `100m/256Mi req, 1Gi limit` |
| `objectStorage.enabled` | Enable object storage integration | `"true"` |
| `externalObjectStorage.endpoint` | External S3-compatible endpoint | `""` |
| `externalObjectStorage.accessKey` | External access key | `""` |
| `externalObjectStorage.secretKey` | External secret key | `""` |

**External alternatives:** AWS S3, Azure Blob Storage, Google Cloud Storage

### SeaweedFS (Session Recordings v2)

| Parameter | Description | Default |
|-----------|-------------|---------|
| `seaweedfs.enabled` | Deploy built-in SeaweedFS | `true` |
| `seaweedfs.image.repository` | SeaweedFS image | `chrislusf/seaweedfs` |
| `seaweedfs.image.tag` | SeaweedFS version | `4.03` |
| `seaweedfs.accessKey` | S3 access key | `any` |
| `seaweedfs.secretKey` | S3 secret key | `any` |
| `seaweedfs.persistence.enabled` | Enable persistent storage | `true` |
| `seaweedfs.persistence.size` | PVC size | `20Gi` |
| `seaweedfs.persistence.storageClass` | Storage class | `""` |
| `seaweedfs.resources` | CPU/memory resources | `100m/256Mi req, 1Gi limit` |
| `externalSeaweedfs.endpoint` | External S3-compatible endpoint | `""` |
| `externalSeaweedfs.accessKey` | External access key | `""` |
| `externalSeaweedfs.secretKey` | External secret key | `""` |

### Elasticsearch

| Parameter | Description | Default |
|-----------|-------------|---------|
| `elasticsearch.enabled` | Deploy built-in Elasticsearch (for Temporal) | `true` |
| `elasticsearch.image.repository` | Elasticsearch image | `elasticsearch` |
| `elasticsearch.image.tag` | Elasticsearch version | `7.17.28` |
| `elasticsearch.persistence.enabled` | Enable persistent storage | `true` |
| `elasticsearch.persistence.size` | PVC size | `10Gi` |
| `elasticsearch.persistence.storageClass` | Storage class | `""` |
| `elasticsearch.resources` | CPU/memory resources | `500m/1Gi req, 2Gi limit` |

### Temporal

| Parameter | Description | Default |
|-----------|-------------|---------|
| `temporal.enabled` | Deploy built-in Temporal | `true` |
| `temporal.server.image.repository` | Temporal server image | `temporalio/auto-setup` |
| `temporal.server.image.tag` | Temporal server version | `1.20.0` |
| `temporal.server.resources` | Server CPU/memory resources | `250m/512Mi req, 1Gi limit` |
| `temporal.adminTools.image.repository` | Temporal admin tools image | `temporalio/admin-tools` |
| `temporal.adminTools.image.tag` | Temporal admin tools version | `1.20.0` |
| `temporal.ui.enabled` | Deploy Temporal UI | `true` |
| `temporal.ui.image.repository` | Temporal UI image | `temporalio/ui` |
| `temporal.ui.image.tag` | Temporal UI version | `2.31.2` |
| `temporal.ui.resources` | UI CPU/memory resources | `50m/64Mi req, 128Mi limit` |
| `externalTemporal.host` | External Temporal host (when `temporal.enabled=false`) | `""` |

### Core PostHog Services

Each core service supports these common production parameters (in addition to `image`, `replicas`, and `resources`):

| Parameter suffix | Description | Default |
|-----------------|-------------|---------|
| `.podSecurityContext` | Pod security context override | `{}` (uses global) |
| `.containerSecurityContext` | Container security context override | `{}` (uses global) |
| `.nodeSelector` | Node selector override | `{}` (uses global) |
| `.tolerations` | Tolerations override | `[]` (uses global) |
| `.affinity` | Affinity override | `{}` (uses global) |
| `.podAnnotations` | Pod annotations override | `{}` (merges with global) |
| `.extraEnv` | Extra environment variables | `[]` |

Services with autoscaling support (`web`, `worker`, `plugins`, `capture`, `replayCapture`, `featureFlags`):

| Parameter suffix | Description | Default |
|-----------------|-------------|---------|
| `.autoscaling.enabled` | Enable HPA | `false` |
| `.autoscaling.minReplicas` | Minimum replicas | `1` |
| `.autoscaling.maxReplicas` | Maximum replicas | varies |
| `.autoscaling.targetCPUUtilizationPercentage` | CPU target | `60-70` |
| `.autoscaling.targetMemoryUtilizationPercentage` | Memory target | `70-80` |

Services with PDB support (`web`, `worker`, `plugins`, `capture`, `replayCapture`, `featureFlags`, `temporalDjangoWorker`):

| Parameter suffix | Description | Default |
|-----------------|-------------|---------|
| `.podDisruptionBudget.enabled` | Enable PDB | `false` |
| `.podDisruptionBudget.minAvailable` | Minimum available pods | `1` |

Services with sidecar/volume support (`web`, `worker`, `plugins`):

| Parameter suffix | Description | Default |
|-----------------|-------------|---------|
| `.extraVolumes` | Extra volumes | `[]` |
| `.extraVolumeMounts` | Extra volume mounts | `[]` |
| `.sidecarContainers` | Sidecar containers | `[]` |

### Network Policies

| Parameter | Description | Default |
|-----------|-------------|---------|
| `networkPolicies.enabled` | Enable NetworkPolicies | `false` |

When enabled, creates:
- **Default deny**: Blocks all ingress to PostHog pods
- **Allow ingress**: Permits traffic to frontend services (web, capture, replay-capture, feature-flags, livestream, plugins)
- **Allow infrastructure**: Permits app pods to reach infrastructure services (PostgreSQL, Redis, ClickHouse, Kafka, etc.)
- **Allow internal**: Permits traffic between all PostHog app pods

### Prometheus Monitoring

| Parameter | Description | Default |
|-----------|-------------|---------|
| `metrics.enabled` | Enable ServiceMonitor creation | `false` |
| `metrics.serviceMonitor.additionalLabels` | Extra labels for discovery | `{}` |
| `metrics.serviceMonitor.interval` | Scrape interval | `"30s"` |
| `metrics.serviceMonitor.scrapeTimeout` | Scrape timeout | `"10s"` |

Requires the prometheus-operator CRDs to be installed in the cluster.

### Init Jobs

| Parameter | Description | Default |
|-----------|-------------|---------|
| `migrate.enabled` | Run Django migrations on install/upgrade | `true` |
| `kafkaInit.enabled` | Create required Kafka topics on install | `true` |
| `kafkaInit.topics` | List of Kafka topics to create | See values.yaml (11 topics) |
| `asyncMigrationsCheck.enabled` | Run async migrations check on install/upgrade | `true` |

## Production Deployment Example

```yaml
# production-values.yaml
ingress:
  hostname: posthog.mycompany.com

existingSecret: posthog-secrets  # pre-created via sealed-secrets / external-secrets

serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/posthog-role

# Use external managed services
postgresql:
  enabled: false
externalPostgresql:
  url: "postgres://posthog:secret@cnpg-cluster-rw:5432/posthog"

redis:
  enabled: false
externalRedis:
  url: "redis://dragonfly:6379/"

# Scale horizontally
web:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
  podDisruptionBudget:
    enabled: true
    minAvailable: 2

capture:
  replicas: 3
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 20
  podDisruptionBudget:
    enabled: true
    minAvailable: 2

worker:
  replicas: 2
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 5
  podDisruptionBudget:
    enabled: true
    minAvailable: 1

# Enable monitoring and network policies
networkPolicies:
  enabled: true

metrics:
  enabled: true
  serviceMonitor:
    additionalLabels:
      release: kube-prometheus-stack
```

```bash
helm install posthog ./charts/posthog -f production-values.yaml
```

## Using External Services

Every infrastructure dependency can be replaced with an external managed service. Set the built-in service to `enabled: false` and provide connection details via the corresponding `external*` parameters.

### Example: CNPG for PostgreSQL

```yaml
postgresql:
  enabled: false

externalPostgresql:
  url: "postgres://posthog:secretpassword@my-cnpg-cluster-rw:5432/posthog"
```

### Example: Dragonfly for Redis

```yaml
redis:
  enabled: false

externalRedis:
  url: "redis://dragonfly.default.svc:6379/"
```

### Example: Azure Blob Storage for Object Storage

```yaml
minio:
  enabled: false

externalObjectStorage:
  endpoint: "https://myaccount.blob.core.windows.net"
  accessKey: "myaccount"
  secretKey: "myaccountkey"
```

### Example: Azure Blob Storage for Session Recordings

```yaml
seaweedfs:
  enabled: false

externalSeaweedfs:
  endpoint: "https://myrecordingsaccount.blob.core.windows.net"
  accessKey: "myrecordingsaccount"
  secretKey: "myrecordingskey"
```

## Ingress Routing

The ingress is configured with path-based routing that mirrors the original Caddy reverse proxy from the Docker Compose deployment. WebSocket upgrade headers are included for the livestream service.

| Path Pattern | Backend Service | Port | Notes |
|-------------|-----------------|------|-------|
| `/e/*`, `/i/v0/*`, `/batch/*`, `/capture/*` | capture | 3000 | Event capture |
| `/s/*` | replay-capture | 3000 | Session recording |
| `/flags/*` | feature-flags | 3001 | Feature flag evaluation |
| `/livestream/*` | livestream | 8080 | WebSocket |
| `/public/webhooks/*` | plugins | 6738 | CDP webhooks |
| `/posthog/*` | minio (or web fallback) | 9000 | Object storage proxy |
| `/*` (default) | web | 8000 | Django app |

Ingress paths for optional services (capture, replay-capture, feature-flags, livestream, plugins) are automatically excluded when the corresponding service is disabled.

## Resource Requirements

Default total resource requests for the all-in-one deployment:

| Category | CPU Request | Memory Request | Memory Limit |
|----------|------------|----------------|--------------|
| Core app services (11) | ~2.4 cores | ~4.5 Gi | ~9 Gi |
| Infrastructure (9) | ~2.4 cores | ~8.5 Gi | ~17 Gi |
| **Total** | **~4.8 cores** | **~13 Gi** | **~26 Gi** |

For production use, consider:
- Increasing ClickHouse resources (it handles all analytics queries)
- Running multiple replicas for `web`, `capture`, and `worker`
- Using external managed services for databases to get replication, backups, and HA
- Enabling HPA and PDB for stateless services

## Upgrading

```bash
helm upgrade posthog ./charts/posthog \
  --set ingress.hostname=posthog.example.com
```

Django migrations run automatically as init containers on the web pod during upgrades. Kafka topic creation and async migration checks run as Helm hook Jobs.

## Uninstalling

```bash
helm uninstall posthog
```

Note: PersistentVolumeClaims created by StatefulSets are **not** automatically deleted. To fully clean up:

```bash
kubectl delete pvc -l app.kubernetes.io/instance=posthog
```

## Chart Structure

```
charts/posthog/
  Chart.yaml                          # Chart metadata
  values.yaml                         # Default configuration values (~830 lines)
  README.md                           # This file
  templates/
    _helpers.tpl                      # Template helpers (labels, env vars, security contexts, scheduling)
    serviceaccount.yaml               # ServiceAccount with IRSA/Workload Identity support
    secrets.yaml                      # Kubernetes Secret (auto-generated keys, skipped with existingSecret)
    pdb.yaml                          # PodDisruptionBudgets (conditional per-component)
    hpa.yaml                          # HorizontalPodAutoscalers (conditional per-component)
    networkpolicy.yaml                # NetworkPolicies (conditional on networkPolicies.enabled)
    servicemonitor.yaml               # Prometheus ServiceMonitors (conditional on metrics.enabled)
    NOTES.txt                         # Post-install instructions
    postgresql.yaml                   # PostgreSQL StatefulSet + Service
    clickhouse.yaml                   # ClickHouse StatefulSet + Service + ConfigMap + Secret
    redis.yaml                        # Redis StatefulSet + Service
    kafka.yaml                        # Kafka/Redpanda StatefulSet + Service
    zookeeper.yaml                    # ZooKeeper StatefulSet + Service
    minio.yaml                        # MinIO StatefulSet + Service
    seaweedfs.yaml                    # SeaweedFS StatefulSet + Service
    elasticsearch.yaml                # Elasticsearch StatefulSet + Service
    temporal.yaml                     # Temporal server + UI + Django worker
    web-worker-plugins.yaml           # Web, Celery worker, plugins Deployments + Services
    capture.yaml                      # Event capture + replay capture Deployments + Services
    auxiliary-services.yaml           # Feature flags, property-defs, livestream, cymbal, cyclotron-janitor
    ingress.yaml                      # NGINX Ingress + Traefik IngressRoute
    jobs.yaml                         # Kafka init + async migrations check (Helm hooks)
```
