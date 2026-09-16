# PostHog Bundle

Kubernetes deployment of [PostHog](https://posthog.com) with two install paths:

1. **Chart** (`helm install`) — self-contained, bundled infrastructure, one command to get running.
2. **Manifests** (GitOps / Flux + operators) — operator-managed databases, with an explicit `hub-production` profile matching the observed live configuration.

The generic chart/manifests examples and production profile have different images, resources, ingress and storage settings. Use the production profile, not the generic example, to reproduce hub-production.

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
  posthog/                   # Generic namespace example: operator CRs + Flux HelmRelease
  hub-production/            # Explicit live production profile; existing cluster operators required

images/
  clickhouse/                # Custom ClickHouse image with PostHog UDF scripts
  posthog/                   # Split Python-slim images: web, worker, worker-exports, migrate

scripts/
  kind-bootstrap.sh          # Create a local kind cluster with registry mirrors + loaded images
  update-topics.sh           # Sync Kafka topic list from upstream PostHog

.github/workflows/
  build-posthog-images.yaml  # Build immutable test artifacts; no publication
  kind-happy-path.yaml       # Fresh-cluster smoke tests and required release-ready gate
  publish-posthog-artifacts.yaml  # Publish the tested artifacts without rebuilding
  sync-posthog-topics.yaml   # Daily PR to sync Kafka topics with upstream
  sync-posthog-user-scripts.yaml  # Daily sync of ClickHouse UDF scripts

vendor/posthog/              # Upstream PostHog UDFs (auto-synced from github.com/PostHog/posthog)
```

## Which path to use

For production use external ClickHouse and Kafka — the bundled ClickHouse is single-node and the `kafka` subchart is `bitnami/kafka` (now `bitnamilegacy`, unmaintained). The manifests path sets both up via operators.

| | Chart | Manifests |
|---|---|---|
| **Use when** | Local dev, quick demo, POC | Operator-managed stateful dependencies; explicit production profile |
| **ClickHouse** | Single-node StatefulSet | Altinity Clickhouse Operator + CHI + CHK (keeper) |
| **Kafka** | bitnami/kafka subchart | Redpanda Operator + `Redpanda` CR |
| **Postgres** | StatefulSet in chart | CloudNativePG (`Cluster` CR) |
| **Object storage** | rustfs subchart | Generic: RustFS; hub-production: external Cloudflare R2 |
| **Deployment tooling** | `helm install` | Flux HelmRelease + Kustomize |
| **Hook order resolution** | Chart hooks; normal Helm wait policy | Staged dependencies/migrations, Flux `disableWait: true`; hooks still wait |

See [charts/posthog/README.md](charts/posthog/README.md) for the chart path, and [manifests/README.md](manifests/README.md) for the GitOps path.

`manifests/hub-production` records the working production configuration and verified image digests. The worker repository-name correction preserves those exact digests while making fresh pulls possible. Start with the [production prerequisites, secret bootstrap and read-only alignment check](manifests/README.md#hub-production). The deployment runner defaults to a plan; reproducibility checks do not implicitly redeploy production.

Install the pinned CLI tools with `mise install`, then create an operations environment:

```sh
python3 -m venv .venv-ops
.venv-ops/bin/pip install -r requirements-ops.txt
```

Use `.venv-ops/bin/python` for the deployment and alignment scripts.

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

- `posthog-web`, `posthog-worker`, `posthog-worker-exports`, `posthog-migrate` — split Python-slim images, with source evidence in `manifests/hub-production/image-provenance.json`
- `posthog-clickhouse` — stock ClickHouse plus PostHog UDF scripts baked in

`.github/workflows/kind-happy-path.yaml` builds and tests exact artifacts before allowing publication. Builds pin their upstream/base images, Debian package snapshot, and SQLx Cargo dependencies. To build locally:

```bash
docker build -f images/posthog/Dockerfile.web -t local/posthog-web:test .
docker build -f images/posthog/Dockerfile.worker -t local/posthog-worker:test .
docker build -f images/posthog/Dockerfile.worker-exports -t local/posthog-worker-exports:test .
docker build -f images/posthog/Dockerfile.migrate -t local/posthog-migrate:test .
docker build -f images/clickhouse/Dockerfile -t local/posthog-clickhouse:test .
```

The chart and manifests work with either `ghcr.io/blitss/*` or `local/*:test` — override via `--set` / `values.yaml`.

## Release verification

Require the GitHub Actions `release-ready` status check on `main`, with the branch up to date before merging. Runtime PRs test three fresh kind environments: declared images, production-profile images, and same-run candidate artifacts. The smoke check verifies ingestion as well as readiness; publication on `main` uses those tested artifacts rather than rebuilding them.

Bot workflows explicitly dispatch verification when using `GITHUB_TOKEN`, whose pushes do not trigger ordinary PR workflows. Renovate rebases behind-base branches and never automerges dependency updates. Stateful major upgrades still need a separate migration decision; a fresh-install smoke test does not prove an in-place data migration.

To recover an unpublished release after fixing CI, run `gh workflow run kind-happy-path.yaml --ref main -f publish=true` without `base_sha`. This rebuilds and verifies the full release before publication; it does not promote artifacts from a failed run. Manual publication is restricted to `main`; ordinary manual/bot verification never publishes.

## Publish targets

- Chart OCI: `oci://ghcr.io/blitss/charts/posthog`
- ClickHouse image: `ghcr.io/blitss/posthog-clickhouse`
- Split PostHog images: `ghcr.io/blitss/posthog-{web,worker,worker-exports,migrate}`
