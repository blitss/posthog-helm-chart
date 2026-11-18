# PostHog on Kubernetes

Community Helm chart and Flux manifests for self-hosting [PostHog](https://posthog.com). Not affiliated with PostHog.

There are two ways to install. Both deploy the same chart.

| | Helm chart | Flux manifests |
|---|---|---|
| Start here | [charts/posthog/README.md](charts/posthog/README.md) | [manifests/README.md](manifests/README.md) |
| Install with | `helm install` | Flux `HelmRelease` + Kustomize |
| Stores | Bundled single pods by default; each can be switched to an external service | Operators: CloudNativePG, Altinity ClickHouse + Keeper, Redpanda, ECK Elasticsearch |
| Object storage | Bundled RustFS or external S3 | Generic profile: RustFS. `hub-production`: Cloudflare R2 |
| Good for | Trying PostHog, small installs, or production with your own managed stores | Clusters that already run Flux and these operators |
| Tested | Bundled-store defaults: render tests only (`scripts/test-chart-render.sh`, run locally) | Fresh-cluster smoke test on kind in CI for every runtime PR |

Which do I want? Use the chart unless you already run Flux and want operator-managed databases. To try PostHog, follow the chart [Quick start](charts/posthog/README.md#quick-start).

`manifests/hub-production` is the recorded configuration of one production deployment, not a template. Use `manifests/posthog` as the generic example.

## Repository layout

```
charts/posthog/              Helm chart
  templates/hooks/           Hook Jobs: db-check, kafka-init, create-buckets, cyclotron-migrate, migrate, async-migrations-check
  templates/external/        Bundled stores (rendered only when enabled)
  templates/posthog/         PostHog workloads, HPA/PDB, ServiceMonitors
  templates/routing/         nginx, Traefik, Gateway API, Istio, OpenShift
  templates/validate.yaml    Fail-fast checks for disabled stores
  examples/                  Render-tested values files
  charts/                    Vendored subcharts (bitnami/kafka, rustfs), committed

manifests/
  infra/                     Cluster-wide operators for a new test cluster
  posthog/                   Generic Flux profile (namespace CRs + HelmRelease)
  posthog-ci/                CI overlay of the generic profile (smaller requests)
  hub-production/            Recorded production profile and its evidence files

images/
  clickhouse/                ClickHouse with PostHog UDF scripts
  posthog/                   Split Python images: web, worker, worker-exports, migrate, cyclotron-migrate

vendor/posthog/              Upstream PostHog ClickHouse UDF scripts (synced daily)

scripts/
  test-chart-render.sh       helm lint + helm template over a value-set matrix
  kind-bootstrap.sh          Local kind cluster, optional registry mirror, local images
  update-topics.sh           Sync Kafka topic lists in values.yaml from upstream
  deploy-hub-production.py, check-hub-production.py, bootstrap-hub-production-secrets.py,
  reconcile-clickhouse-logs.py
                             hub-production runner, alignment check, secrets, logs repair
  verify-release-*.py        CI helpers
  test-*                     Tests for the scripts above
```

## Images

The chart and manifests use images built here and published to `ghcr.io/blitss/`:

- `posthog-web`, `posthog-worker`, `posthog-worker-exports`, `posthog-migrate`, `posthog-cyclotron-migrate`: slim images that copy runtime files out of an upstream `posthog/posthog` digest. See [images/posthog/README.md](images/posthog/README.md). amd64 only.
- `posthog-clickhouse`: ClickHouse plus the PostHog UDF scripts. amd64 and arm64.

Tags: `sha-<commit>` for each published build, and `latest` for the last build that passed CI on `main`.

To build locally (from the repository root):

```bash
docker build -f images/posthog/Dockerfile.web -t local/posthog-web:test .
docker build -f images/posthog/Dockerfile.worker -t local/posthog-worker:test .
docker build -f images/posthog/Dockerfile.worker-exports -t local/posthog-worker-exports:test .
docker build -f images/posthog/Dockerfile.migrate -t local/posthog-migrate:test .
docker build -f images/clickhouse/Dockerfile -t local/posthog-clickhouse:test .
```

## Local testing with kind

```bash
./scripts/kind-bootstrap.sh --recreate
```

This creates a single-node cluster from `kind-config.local.yaml` and loads any local `local/posthog-*:test` images. With `MIRROR_HOST` (or `--mirror-host`) set, it also routes `docker.io`, `ghcr.io` and `docker.redpanda.com` pulls through that Harbor-style mirror. Then install with the chart [Quick start](charts/posthog/README.md#quick-start), or apply the manifests.

## Contributing

Tools are pinned in `mise.toml` (Helm 3.22.1, kubectl, kind, Flux 2.6, yq, Python, actionlint):

```bash
mise trust && mise install
bash scripts/test-chart-render.sh
```

`test-chart-render.sh` runs `helm lint`, renders the chart for a matrix of value sets (defaults, external stores, every routing mode, all HPA/PDB toggles, optional workloads, every file in `charts/posthog/examples/`, both Flux releases), and checks that each fail-fast validation still rejects a disabled store without its endpoint. CI does not run it; run it before you push a chart change.

For the hub-production scripts, create a separate environment:

```bash
python3 -m venv .venv-ops
.venv-ops/bin/pip install -r requirements-ops.txt
```

### How CI gates merges

`.github/workflows/kind-happy-path.yaml` runs on pull requests, the merge queue and pushes to `main`:

1. Classify the change. A change limited to `*.md` files (and other paths outside charts, images, manifests, scripts, workflows and tool pins) skips the build and smoke test.
2. Build the images (`build-posthog-images.yaml`; nothing is pushed).
3. Smoke-test the Flux manifests on three fresh kind clusters: declared images, the hub-production images and the images just built. The test checks ingestion, not only readiness.
4. `release-ready` passes only if the build and all three smoke tests passed, or were skipped for a docs-only change. Make it a required status check on `main`.
5. On `main`, `publish-posthog-artifacts.yaml` pushes the tested images (when image inputs such as `images/` or `vendor/` changed) and the chart (when `version` in `Chart.yaml` changed) to GHCR. It does not rebuild.

To retry a failed publication after fixing CI: `gh workflow run kind-happy-path.yaml --ref main -f publish=true`. This rebuilds and re-tests before publishing.

### Upstream tracking and Renovate

- `posthog-tracker.yaml` (daily): reads upstream PostHog commits since the SHA in `.github/posthog-tracker.last-sha`, has Claude file `posthog-tracker` issues for changes the chart may need, and opens a PR that moves the cursor.
- `posthog-tracker-resolve.yaml`: on a `posthog-tracker` label, a `/resolve` issue comment or manual dispatch, Claude implements the issue on a branch and opens a draft PR.
- `sync-posthog-topics.yaml` and `sync-posthog-user-scripts.yaml` (daily): PRs that sync the Kafka topic lists (`scripts/update-topics.sh`) and the ClickHouse UDF scripts in `vendor/posthog/`.
- Renovate (`.github/renovate.json5`, weekly): updates image tags and digests in `manifests/` (except `manifests/hub-production/`, which is recorded state), GitHub Actions and `mise.toml`. Updates are grouped; major updates get their own PR; stateful-store majors (PostgreSQL, Redis, Valkey, Kafka, Elasticsearch) are disabled; nothing auto-merges. Renovate does not update `charts/posthog/values.yaml`.
- `claude.yml` and `claude-code-review.yml`: Claude on `@claude` mentions and PR review.

Bot PRs created with `GITHUB_TOKEN` do not trigger PR workflows, so these workflows dispatch `kind-happy-path` themselves (`scripts/verify-release-dispatch.py`).

## Publish targets

- Chart (OCI): `oci://ghcr.io/blitss/charts/posthog`
- Images: `ghcr.io/blitss/posthog-{web,worker,worker-exports,migrate,cyclotron-migrate,clickhouse}`
