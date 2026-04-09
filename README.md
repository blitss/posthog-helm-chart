# PostHog Bundle

Kubernetes deployment of [PostHog](https://posthog.com) with two install paths:

1. **Chart** (`helm install`) — self-contained, bundled infrastructure, one command to get running.
2. **Manifests** (GitOps / Flux + operators) — hardened production setup where every stateful dependency is managed by a dedicated operator.

Both paths deploy the same PostHog app; they differ only in how infrastructure (ClickHouse, Kafka, Postgres, object storage) is provisioned.

## What's in the repo

```
charts/posthog/              # Helm chart (both paths use this)
  templates/hooks/           # Install hooks: db-check, kafka-init, create-buckets, migrate, async-migrations
  templates/external/        # Bundled infra deployments (used only when enabled=true)
  templates/posthog/         # PostHog application Deployments
  templates/routing/         # Ingress / Gateway API / Traefik / Istio / OpenShift route options
  charts/                    # Subchart dependencies: bitnami/kafka, rustfs  (gitignored)

manifests/                   # GitOps path — Flux-managed operators and CRs
  infra/                     # cert-manager, CNPG, CRDs — cluster-wide prerequisites
  posthog/                   # PostHog namespace: operators, CRs, Flux HelmRelease

images/
  clickhouse/                # Custom ClickHouse image with PostHog UDF scripts
  posthog/                   # Split Python-slim images: web, worker, worker-exports, migrate

scripts/
  kind-bootstrap.sh          # Create a local kind cluster with registry mirrors + loaded images
  update-topics.sh           # Sync Kafka topic list from upstream PostHog

.github/workflows/
  build-posthog-images.yaml  # Build and publish split PostHog images + ClickHouse to ghcr.io
  sync-posthog-topics.yaml   # Daily PR to sync Kafka topics with upstream
  sync-posthog-user-scripts.yaml  # Daily sync of ClickHouse UDF scripts

vendor/posthog/              # Upstream PostHog UDFs (auto-synced from github.com/PostHog/posthog)
```

## Which path to use

For production use external ClickHouse and Kafka — the bundled ClickHouse is single-node and the `kafka` subchart is `bitnami/kafka` (now `bitnamilegacy`, unmaintained). The manifests path sets both up via operators.

| | Chart | Manifests |
|---|---|---|
| **Use when** | Local dev, quick demo, POC | Production, HA, proper operator story |
| **ClickHouse** | Single-node StatefulSet | Altinity Clickhouse Operator + CHI + CHK (keeper) |
| **Kafka** | bitnami/kafka subchart | Redpanda Operator + `Redpanda` CR |
| **Postgres** | StatefulSet in chart | CloudNativePG (`Cluster` CR) |
| **Object storage** | rustfs subchart | rustfs subchart (still in chart) |
| **Deployment tooling** | `helm install` | Flux HelmRelease + Kustomize |
| **Hook order resolution** | Helm `--wait` | Flux `disableWait: true` + pod crash-loop backoff |

See [charts/posthog/README.md](charts/posthog/README.md) for the chart path, and [manifests/README.md](manifests/README.md) for the GitOps path.

## Local testing with kind

Both paths can be tested on a single-node kind cluster. The bootstrap script creates the cluster, installs container registry mirrors, and loads locally-built images:

```bash
./scripts/kind-bootstrap.sh --recreate
```

What it does:

- Creates a single-node cluster from `kind-config.local.yaml`
- Configures containerd mirrors so `docker.io/*` and `ghcr.io/*` pulls go through an internal Harbor proxy (configurable via `MIRROR_HOST`)
- Loads any local `local/posthog-*:test` images into the cluster so you don't need to push them

After that, follow either install path below.

## Custom images

The chart and manifests reference pre-built images on `ghcr.io/blitss/`:

- `posthog-web`, `posthog-worker`, `posthog-worker-exports`, `posthog-migrate` — split Python-slim images (2–4 GB each instead of the 9.8 GB upstream monolith)
- `posthog-clickhouse` — stock ClickHouse plus PostHog UDF scripts baked in

These are published by `.github/workflows/build-posthog-images.yaml`. To build locally:

```bash
docker build -f images/posthog/Dockerfile.web -t local/posthog-web:test .
docker build -f images/posthog/Dockerfile.worker -t local/posthog-worker:test .
docker build -f images/posthog/Dockerfile.worker-exports -t local/posthog-worker-exports:test .
docker build -f images/posthog/Dockerfile.migrate -t local/posthog-migrate:test .
docker build -f images/clickhouse/Dockerfile -t local/posthog-clickhouse:test .
```

The chart and manifests work with either `ghcr.io/blitss/*` or `local/*:test` — override via `--set` / `values.yaml`.

## Publish targets

- Chart OCI: `oci://ghcr.io/blitss/charts/posthog`
- ClickHouse image: `ghcr.io/blitss/posthog-clickhouse`
- Split PostHog images: `ghcr.io/blitss/posthog-{web,worker,worker-exports,migrate}`
