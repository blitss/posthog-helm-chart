# PostHog Manifests (GitOps / Flux)

Production-grade install path. Every stateful dependency is managed by a dedicated operator, and the PostHog Helm chart is deployed as a Flux `HelmRelease` pointing at an OCI registry.

Use this path when you want the full operator story: declarative CRs, rolling upgrades managed by operators, proper backup/restore hooks, and no hand-rolled StatefulSets. For a quicker single-command install, use the [chart path](../charts/posthog/README.md).

## Architecture

```
cert-manager                    CNPG operator            Altinity CH operator    Redpanda operator
    │                               │                            │                         │
    ▼                               ▼                            ▼                         ▼
Certificate ──── Issuer      Cluster (Postgres)          CHI (ClickHouse)           Redpanda CR
                             posthog-pg                  chi-posthog-posthog-0-0-0  posthog-redpanda-0
                                                         ClickHouseKeeperInstallation
                                                         chk-posthog-keeper-0-0-0

                        Flux HelmRelease (posthog-chart) ───▶ PostHog app + rustfs subchart
                                           │
                                           ▼
                                 Kustomize / Flux kustomize-controller
                                           │
                                           ▼
                          kubectl apply -k manifests/
```

What each piece does:

| Operator | Controls | CR kind |
|---|---|---|
| **cert-manager** | TLS certs for OIDC, ingress, and Redpanda listeners | `Certificate`, `Issuer` |
| **CloudNativePG** | Postgres clusters with backups, failover, PITR | `Cluster` |
| **Altinity ClickHouse Operator** | ClickHouse deployments with cluster topology, users, macros | `ClickHouseInstallation` |
| **Altinity ClickHouse Keeper Operator** | Raft-based ClickHouse coordinator (replaces ZooKeeper) | `ClickHouseKeeperInstallation` |
| **Elastic Cloud on Kubernetes** | Elasticsearch deployment for Temporal visibility | `Elasticsearch` |
| **Redpanda Operator** | Kafka-compatible message broker | `Redpanda` |
| **Flux helm-controller** | Deploys the PostHog Helm chart from OCI | `HelmRelease` |
| **Flux kustomize-controller** | Reconciles any of these from git (optional — you can also `kubectl apply -k`) | `Kustomization` |

The PostHog chart itself still ships **rustfs** as a subchart, so the S3-compatible object store is installed alongside the app pods rather than via its own operator.

## Prerequisites

- Kubernetes 1.28+
- Cluster admin access (operators install cluster-scoped CRDs)
- Flux v2 installed in the cluster (`flux install`)
- ~16 GiB RAM across worker nodes for the full production stack

## Directory layout

```
manifests/
  kustomization.yaml              # kustomize root: includes infra/ and posthog/

  infra/                          # Cluster-wide prerequisites
    kustomization.yaml
    namespaces.yaml               # cert-manager, cnpg-system namespaces
    cert-manager.yaml             # HelmRelease for cert-manager
    cnpg.yaml                     # HelmRelease for CloudNativePG
    # ECK is installed from Elastic's official crds.yaml + operator.yaml
    # because the Helm chart tarball endpoint currently returns 403.
    # ... plus remote CRD references:
    #   external-snapshotter CRDs
    #   gateway-api standard-install
    #   carvel secretgen-controller

  posthog/                        # PostHog namespace: operators + CRs + chart
    kustomization.yaml
    namespace.yaml                # posthog namespace with pod-security labels
    issuer.yaml                   # self-signed Issuer for OIDC
    oidc-certificate.yaml         # cert-manager Certificate for OIDC RSA keypair
    postgres-cnpg.yaml            # CNPG Cluster CR (posthog-pg)
    clickhouse-password.yaml      # secretgen.k14s.io Password CR (auto-generated)
    clickhouse-keeper.yaml        # ClickHouseKeeperInstallation CR
    clickhouse-initdb.yaml        # ConfigMap with init script for /docker-entrypoint-initdb.d
    clickhouse.yaml               # ClickHouseInstallation CR with cluster + user config
    elasticsearch.yaml            # ECK Elasticsearch CR for Temporal visibility
    redpanda.yaml                 # Redpanda CR
    ocirepository.yaml            # Flux OCIRepository pointing at ghcr.io/blitss/charts/posthog
    release.yaml                  # Flux HelmRelease for PostHog
    kind-values.local.yaml        # Local kind override (gitignored via convention)
```

## Install

```bash
# 1. Install Flux v2 if you haven't
flux install

# 2. Apply everything (may need two passes on first install — CRDs need to land
#    before CRs can be validated)
kubectl apply -k manifests/
# ... wait for cert-manager + CNPG + Altinity + Redpanda HelmReleases
#     and the ECK operator StatefulSet to report Ready
kubectl apply -k manifests/
```

Or with Flux's kustomize-controller, commit the repo and create a root `Kustomization` CR pointing at it.

## Why `kubectl apply -k` twice

First pass creates the HelmReleases for cert-manager, CNPG, Altinity, and Redpanda, installs ECK from Elastic's official YAML manifests, and lands the CRDs. The second pass applies the CRs that depend on those CRDs (`Certificate`, `Issuer`, `Cluster`, `Elasticsearch`, `ClickHouseInstallation`, `Redpanda`, etc.). Running the command twice is fine — everything is idempotent.

With Flux's kustomize-controller, this dance happens automatically (it retries failed resources), so you only need one commit.

## Post-install check

```bash
# Operators and CRs
kubectl get helmrelease -A
kubectl get clickhouseinstallation,clickhousekeeperinstallation,elasticsearch,redpanda,cluster -n posthog

# PostHog app
kubectl get pods -n posthog
```

Expected state after convergence: ~32 pods Running, hooks completed, `posthog` HelmRelease `True`.

### Preflight endpoint

```bash
WEB=$(kubectl get pod -n posthog -l app.kubernetes.io/component=web -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n posthog "$WEB" -- python -c \
  "import urllib.request, json; print(json.dumps(json.loads(urllib.request.urlopen('http://localhost:8000/_preflight/').read()), indent=2))"
```

Every infra component should be `true`: `django`, `db`, `clickhouse`, `kafka`, `redis`, `plugins`, `celery`, `object_storage`. Expected fails on a fresh self-host install: `cloud`, `demo`, `email_service_available`, `initiated`.

## Key design decisions

### `disableWait: true` on the Flux HelmRelease

Flux's helm-controller runs its own kstatus-based readiness check after `helm install`. Without `disableWait: true`, the PostHog install fails because web/cymbal/worker pods crash-loop waiting for migrations to complete — and migrations only run after the Helm hooks fire, which Flux treats as "stalled". Disabling the wait lets hooks finish, pods eventually self-recover, and the release is marked Ready.

### ClickHouse Keeper instead of ZooKeeper

`ClickHouseKeeperInstallation` gives us a Raft-based coordinator without running a separate ZooKeeper fleet. The CHI references it via `spec.configuration.zookeeper.nodes`:

```yaml
zookeeper:
  nodes:
    - host: chk-posthog-keeper-keeper-0-0
      port: 2181
```

### CH cluster secret

```yaml
clusters:
  - name: posthog
    secret:
      auto: "true"
```

This tells the operator to generate a shared secret used for inter-node authentication when executing distributed DDL (`CREATE TABLE ... ON CLUSTER posthog`). Without it, inter-node connections fall back to the `default` user and fail because that user requires a password.

### PostHog macros

PostHog migrations use `getMacro('hostClusterType')` and `getMacro('hostClusterRole')`. We inject them via CHI `files`:

```yaml
files:
  config.d/posthog_macros.xml: |
    <clickhouse>
      <macros>
        <hostClusterType>online</hostClusterType>
        <hostClusterRole>data</hostClusterRole>
      </macros>
    </clickhouse>
```

### Remote servers for PostHog-specific cluster names

PostHog references several cluster names (`posthog_migrations`, `posthog_single_shard`, `posthog_writable`, `posthog_primary_replica`, `ai_events`, `aux`, `ops`, `sessions`). The CHI's `files` field adds a second `remote_servers` config that aliases all of them to the single `posthog` shard. Production with actual sharding would have these point at the right shards.

### System log tables baked into the CHI config

PostHog's `migrate_clickhouse` expects `system.crash_log`, `system.error_log`, and `system.metric_log` to exist on startup. These aren't created by ClickHouse until the first `SYSTEM FLUSH LOGS`. We declare them explicitly in `config.d/posthog_system_logs.xml` so they're materialized during boot.

### ClickHouse initdb for database creation

`manifests/posthog/clickhouse-initdb.yaml` is a ConfigMap mounted at `/docker-entrypoint-initdb.d` on the CH pod. It runs the upstream PostHog `init-db.sh` which creates the `posthog` database on first boot, so the `migrate` hook can find it without a separate bootstrap job.

### Redpanda replaces bundled Kafka

Redpanda is operator-managed via `cluster.redpanda.com/v1alpha2 Redpanda`. It's single-broker by default (bump `statefulset.replicas` for prod), KRaft-only, plaintext internal listener, no SASL. TLS is intentionally disabled because the PostHog clients in the chart aren't wired up for TLS-encrypted Kafka yet — see "Known gaps" below.

The chart's `kafka.enabled` is set to `false` in `release.yaml` and `externalKafka.brokers` points at `posthog-redpanda.posthog.svc.cluster.local:9093`. The chart's `kafka-init` hook is skipped because Redpanda auto-creates topics.

### CNPG instead of bundled Postgres

`postgres-cnpg.yaml` declares a `Cluster` CR managed by CloudNativePG. It creates the `posthog`, `posthog_persons`, and `cyclotron` databases, and a dedicated `posthog-pg-app` secret that the HelmRelease references via `externalPostgresql.secretName`.

## Local testing with kind

1. Create the cluster with registry mirrors:

   ```bash
   ./scripts/kind-bootstrap.sh --recreate
   ```

2. Install Flux:

   ```bash
   flux install
   ```

3. Apply manifests (twice on first install):

   ```bash
   kubectl apply -k manifests/
   kubectl apply -k manifests/
   ```

4. Wait for convergence (~5–10 minutes — operators pull images and reconcile CRs):

   ```bash
   watch kubectl get pods -n posthog
   ```

A local kind values override (`kind-values.local.yaml`) exists for swapping image repos to `local/*:test` and reducing replica counts during iteration. It's loaded by `scripts/kind-bootstrap.sh --install-posthog` but not by the manifests path.

## Known gaps

- **Redpanda TLS is disabled.** The CR has cert-manager certificates provisioned but the `kafka` listener is plaintext because the PostHog Helm chart has no `externalKafka.tls.caSecret` wiring yet. To enable: flip `listeners.kafka.tls.enabled: true` in `redpanda.yaml` and add CA volume mounts across every PostHog component + CHI Kafka named_collections.
- **No remote state for operators.** The CR revision is tied to the manifest; on a fresh install the operators rebuild everything from scratch. Add backups (CNPG `Backup`, CH backup hooks) before putting real data on it.
- **rustfs bucket creation is a helm hook, not an operator reconciliation.** On a destructive reinstall, the bucket is re-created by the chart's `create-buckets` hook.

## Customization

| Want to change | Edit |
|---|---|
| ClickHouse cluster topology (shards, replicas, disk, memory) | `manifests/posthog/clickhouse.yaml` — `clusters.layout`, `templates.podTemplates`, `templates.volumeClaimTemplates` |
| Redpanda broker count, resources, persistence | `manifests/posthog/redpanda.yaml` — `clusterSpec.statefulset.replicas`, `resources`, `storage` |
| Postgres size, database list, users | `manifests/posthog/postgres-cnpg.yaml` |
| PostHog app values (ingress host, image tags, resources) | `manifests/posthog/release.yaml` — `spec.values.*` |
| PostHog chart version | `manifests/posthog/ocirepository.yaml` — `spec.ref.semver` |
| Which operators to install | `manifests/infra/kustomization.yaml` and `manifests/posthog/kustomization.yaml` |
